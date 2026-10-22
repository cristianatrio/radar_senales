"""
Exporta un modelo estrella en CSV para Power BI a partir de una DB del radar.

    python exportar_powerbi.py                         # DB local -> output/powerbi/ (privado)
    python exportar_powerbi.py --db demo/salida/radar_demo.db --destino powerbi/datos_demo

Solo exporta tablas de MERCADO y de OPERACIÓN. Nunca exporta posiciones,
eventos de posición, snapshots/cambios de Ripio ni alertas: esas tablas son
privadas y quedan fuera de cualquier informe público.

Tablas generadas (ver powerbi/README_POWERBI.md):
  dim_activo, dim_fecha, dim_senal, dim_corrida              (dimensiones)
  fact_senales, fact_precios, fact_resultados_activo         (hechos)
Las banderas es_ultima / es_ultima_vela se calculan aquí para que las
medidas DAX sean simples y verificables contra valores_esperados.md.
"""

import argparse
import hashlib
import os
import sqlite3
import sys

import pandas as pd

import config
from consola import configurar_salida_utf8

TABLAS_PRIVADAS = ("posiciones", "eventos_posicion", "ripio_balance_snapshot",
                   "ripio_cambios_pendientes", "alertas_enviadas", "alertas_log")

# Orden, símbolo (para no depender solo del color) y descripción de cada señal.
DIM_SENAL = [
    ("COMPRA_FUERTE", 1, "▲▲", "Puntaje ≥ 4 con al menos 2 familias alcistas"),
    ("COMPRA_PROBABLE", 2, "▲", "Puntaje entre 2 y 3"),
    ("ESPERAR", 3, "■", "Puntaje entre -1 y 1"),
    ("VENTA_PROBABLE", 4, "▼", "Puntaje entre -3 y -2"),
    ("VENTA_FUERTE", 5, "▼▼", "Puntaje ≤ -4 con al menos 2 familias bajistas"),
    ("RIESGO_ALTO", 6, "⚠", "Ruptura con volumen alto y puntaje débil (|puntaje| < 3)"),
    ("SIN_DATOS", 7, "∅", "Historial insuficiente para calcular todos los indicadores"),
]


def _leer(conn, sql: str) -> pd.DataFrame:
    return pd.read_sql_query(sql, conn)


def _fecha(serie: pd.Series) -> pd.Series:
    return pd.to_datetime(serie, format="mixed").dt.strftime("%Y-%m-%d")


def construir_dim_activo(señales: pd.DataFrame, es_sintetico: bool) -> pd.DataFrame:
    grupos = config.GRUPOS_ACTIVOS
    ultimas = señales.sort_values("generado_utc").groupby("ticker").tail(1)
    filas = []
    for _, r in ultimas.iterrows():
        meta = grupos.get(r["tipo"], {})
        filas.append({
            "ticker": r["ticker"], "tipo": r["tipo"],
            "instrumento": "ETF" if r["ticker"] in config.ETFS else meta.get("instrumento"),
            "mercado": r.get("mercado") or meta.get("mercado"),
            "moneda": r.get("moneda") or meta.get("moneda"),
            "fuente": r["fuente"], "timeframe": r.get("timeframe"),
            "es_sintetico": es_sintetico,
        })
    return pd.DataFrame(filas).sort_values(["tipo", "ticker"]).reset_index(drop=True)


def construir_dim_fecha(fechas: pd.Series) -> pd.DataFrame:
    dias = pd.date_range(pd.to_datetime(fechas).min(), pd.to_datetime(fechas).max(), freq="D")
    return pd.DataFrame({
        "fecha": dias.strftime("%Y-%m-%d"), "anio": dias.year, "mes": dias.month,
        "anio_mes": dias.strftime("%Y-%m"), "dia": dias.day,
        "dia_semana": dias.dayofweek + 1, "es_habil": dias.dayofweek < 5,
    })


def construir_tablas(conn: sqlite3.Connection, es_sintetico: bool) -> dict:
    hist = _leer(conn, """
        SELECT id, run_id, ticker, tipo, fuente, timeframe, mercado, moneda, estado_dato,
               COALESCE(generado_utc, timestamp) AS generado_utc, capturado_utc, vela_utc,
               precio, señal, fuerza, rsi, macd_hist, vol_relativo, ma_corta, ma_larga, motivos
        FROM senales_historico
    """)
    hist = hist.sort_values(["ticker", "generado_utc", "id"]).reset_index(drop=True)
    hist["es_ultima"] = ~hist.duplicated("ticker", keep="last")
    anterior = hist.groupby("ticker")["señal"].shift(1)
    hist["cambio_senal"] = anterior.notna() & (anterior != hist["señal"])
    hist["fecha"] = _fecha(hist["vela_utc"].fillna(hist["generado_utc"]))

    precios = _leer(conn, """
        SELECT ticker, timeframe, COALESCE(timestamp_utc, timestamp) AS timestamp_utc,
               timestamp AS timestamp_original, open, high, low, close, volume,
               rsi, macd_hist, ma_corta, ma_larga, vol_relativo, ajuste
        FROM precios_ohlcv
    """)
    precios = precios.sort_values(["ticker", "timestamp_utc"]).reset_index(drop=True)
    precios["es_ultima_vela"] = ~precios.duplicated("ticker", keep="last")
    precios["fecha"] = _fecha(precios["timestamp_utc"])

    corridas = _leer(conn, "SELECT * FROM corridas ORDER BY inicio_utc")
    corridas["es_ultima_corrida"] = corridas["inicio_utc"] == corridas["inicio_utc"].max()
    resultados = _leer(conn, """
        SELECT run_id, ticker, tipo, fuente, timeframe, estado, capturado_utc, vela_utc,
               velas_recibidas, velas_descartadas, velas_abiertas, moneda, detalle
        FROM resultados_activo
    """)
    resultados["fecha"] = _fecha(resultados["capturado_utc"])

    fechas = pd.concat([hist["fecha"], precios["fecha"], resultados["fecha"]])
    return {
        "dim_activo": construir_dim_activo(hist, es_sintetico),
        "dim_fecha": construir_dim_fecha(fechas),
        "dim_senal": pd.DataFrame(DIM_SENAL, columns=["señal", "orden", "simbolo", "descripcion"]),
        "dim_corrida": corridas,
        "fact_senales": hist,
        "fact_precios": precios,
        "fact_resultados_activo": resultados,
    }


def exportar(path_db: str, destino: str, es_sintetico: bool = False) -> dict:
    """Escribe los CSV y un MANIFIESTO.txt con SHA-256 de cada archivo."""
    conn = sqlite3.connect(f"file:{path_db}?mode=ro", uri=True)
    try:
        tablas = construir_tablas(conn, es_sintetico)
    except (sqlite3.OperationalError, pd.errors.DatabaseError) as e:
        raise RuntimeError("La DB no tiene el esquema actual: corré `python main.py` una vez "
                           f"para migrarla ({type(e).__name__}).") from None
    finally:
        conn.close()

    os.makedirs(destino, exist_ok=True)
    manifiesto = []
    for nombre, df in tablas.items():
        ruta = os.path.join(destino, f"{nombre}.csv")
        df.to_csv(ruta, index=False, encoding="utf-8", lineterminator="\n")
        with open(ruta, "rb") as f:
            manifiesto.append(f"{hashlib.sha256(f.read()).hexdigest()}  {nombre}.csv  ({len(df)} filas)")
    with open(os.path.join(destino, "MANIFIESTO.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("# SHA-256 de cada CSV. Datos " +
                ("SINTÉTICOS (demo pública)" if es_sintetico else "REALES (privados: no publicar)") + "\n")
        f.write("\n".join(manifiesto) + "\n")
    return tablas


def main(argv=None) -> int:
    configurar_salida_utf8()
    parser = argparse.ArgumentParser(description="Exporta CSV en modelo estrella para Power BI.")
    parser.add_argument("--db", default=os.path.join(config.CARPETA_SALIDA, config.ARCHIVO_DB))
    parser.add_argument("--destino", default=os.path.join(config.CARPETA_SALIDA, "powerbi"))
    parser.add_argument("--sintetico", action="store_true",
                        help="marca los datos como sintéticos (solo para la demo)")
    args = parser.parse_args(argv)
    if not os.path.exists(args.db):
        print(f"[!] No existe {args.db}")
        return 1
    tablas = exportar(args.db, args.destino, args.sintetico)
    for nombre, df in tablas.items():
        print(f"  ✔ {nombre}.csv ({len(df)} filas)")
    print(f"Exportado en {args.destino}/ (sin tablas privadas: {', '.join(TABLAS_PRIVADAS)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
Genera la demo pública con datos 100% SINTÉTICOS y reproducibles.

    python demo/generar_demo.py            # 7 días simulados de corridas horarias
    python demo/generar_demo.py --dias 2   # más rápido

Qué hace:
1. Crea series OHLCV ficticias (semillas fijas) para 3 pares cripto 1h,
   2 acciones argentinas 1d y 2 acciones de EE. UU. 1d.
2. Ejecuta el pipeline REAL (main.correr_radar) una vez por hora simulada,
   con un reloj simulado, sin red y sin integraciones (sin Telegram, sin
   posiciones, sin Ripio). Incluye a propósito un activo que deja de
   actualizarse (obsoleto) y uno con fallas intermitentes del proveedor.
3. Exporta el modelo estrella a powerbi/datos_demo/ y calcula los valores
   esperados de cada medida en powerbi/valores_esperados.md.

Nada de esto lee output/, credenciales ni datos personales.
"""

import argparse
import contextlib
import io
import os
import sys
import types
from datetime import datetime, timedelta, timezone

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

import pandas as pd  # noqa: E402

import config as config_real  # noqa: E402
import exportar_powerbi  # noqa: E402
import main  # noqa: E402
from consola import configurar_salida_utf8  # noqa: E402
from datos_sinteticos import ProveedorSintetico, SerieSintetica, generar_ohlcv  # noqa: E402
from fuentes.red import ErrorProveedor  # noqa: E402

INICIO = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)
SALIDA_DB = os.path.join(RAIZ, "demo", "salida")
DESTINO_CSV = os.path.join(RAIZ, "powerbi", "datos_demo")
VALORES_ESPERADOS = os.path.join(RAIZ, "powerbi", "valores_esperados.md")

ACTIVOS = {
    # ticker: (grupo, precio inicial, volatilidad por vela, semilla, zona horaria)
    "ALFAUSDT": ("cripto", 100.0, 0.008, 11, "UTC"),
    "BETAUSDT": ("cripto", 4.0, 0.010, 12, "UTC"),
    "DELTAUSDT": ("cripto", 0.8, 0.012, 13, "UTC"),       # deja de actualizarse: obsoleto
    "ANDES.BA": ("accion_arg", 900.0, 0.020, 21, "America/Argentina/Buenos_Aires"),
    "PAMPA.BA": ("accion_arg", 2500.0, 0.022, 22, "America/Argentina/Buenos_Aires"),
    "ACME": ("accion_us", 50.0, 0.015, 31, "America/New_York"),
    "GLOBX": ("accion_us", 120.0, 0.012, 32, "America/New_York"),  # fallas intermitentes
}
TICKER_OBSOLETO = "DELTAUSDT"
TICKER_INTERMITENTE = "GLOBX"


def config_demo(carpeta_salida: str):
    valores = {k: getattr(config_real, k) for k in dir(config_real) if k.isupper()}
    cfg = types.SimpleNamespace(**valores)
    cfg.CARPETA_SALIDA = carpeta_salida
    cfg.ARCHIVO_DB = "radar_demo.db"
    cfg.CRIPTO = [t for t, a in ACTIVOS.items() if a[0] == "cripto"]
    cfg.ACCIONES_ARG = [t for t, a in ACTIVOS.items() if a[0] == "accion_arg"]
    cfg.CEDEARS = []
    cfg.ACCIONES_US = [t for t, a in ACTIVOS.items() if a[0] == "accion_us"]
    cfg.TELEGRAM_ACTIVO = False
    cfg.POSICIONES_ACTIVO = False
    cfg.RIPIO_ACTIVO = False
    cfg.EXPORTAR_CSVS = False
    return cfg


def series_demo(dias: int) -> dict:
    moneda = {"cripto": "USDT", "accion_arg": "ARS", "accion_us": "USD"}
    series = {}
    for ticker, (grupo, precio, vol, semilla, tz) in ACTIVOS.items():
        intervalo = "1h" if grupo == "cripto" else "1d"
        fuente = "binance" if grupo == "cripto" else "yahoo"
        historia = 300 if intervalo == "1h" else 400
        if intervalo == "1h":
            inicio, n = INICIO - timedelta(hours=historia), historia + dias * 24 + 1
        else:  # días hábiles desde el inicio hasta el final de la demo
            inicio = INICIO - timedelta(days=int(historia * 1.45))
            n = len(pd.bdate_range(inicio.date(), (INICIO + timedelta(days=dias + 1)).date()))
        serie = SerieSintetica(ticker, fuente, moneda[grupo], intervalo, precio, vol, semilla, tz)
        df = generar_ohlcv(serie, n, inicio)
        if ticker == TICKER_OBSOLETO:  # el "proveedor" deja de publicar velas a mitad de la demo
            df = df[df["timestamp_utc"] < pd.Timestamp(INICIO + timedelta(days=dias / 2))]
        series[ticker] = df
    return series


def generar(dias: int = 7, carpeta_salida: str = SALIDA_DB, destino: str = DESTINO_CSV,
            valores_esperados: str | None = VALORES_ESPERADOS) -> dict:
    cfg = config_demo(carpeta_salida)
    path_db = os.path.join(carpeta_salida, cfg.ARCHIVO_DB)
    os.makedirs(carpeta_salida, exist_ok=True)
    for sufijo in ("", "-journal"):
        if os.path.exists(path_db + sufijo):
            os.remove(path_db + sufijo)  # solo la DB sintética de la demo

    ahora = {"t": INICIO}
    reloj = lambda: ahora["t"]  # noqa: E731
    sintetico = ProveedorSintetico(series_demo(dias), reloj)
    corrida = {"n": 0}

    def yahoo(activo):
        if activo.ticker == TICKER_INTERMITENTE and corrida["n"] % 9 == 4:
            raise ErrorProveedor("yahoo", "rate limit tras 3 intentos (simulado)")
        return sintetico(activo)

    proveedores = {"binance": sintetico, "yahoo": yahoo}
    resumenes = []
    for hora in range(dias * 24):
        ahora["t"] = INICIO + timedelta(hours=hora, minutes=5)
        corrida["n"] = hora
        with contextlib.redirect_stdout(io.StringIO()):
            resumenes.append(main.correr_radar(
                cfg, proveedores=proveedores, reloj=reloj, path_db=path_db, notificador=None,
                integraciones=False, exportar=False,
                generar_run_id=lambda inicio: f"{inicio:%Y%m%dT%H%M%SZ}-demo"))

    tablas = exportar_powerbi.exportar(path_db, destino, es_sintetico=True)
    if valores_esperados:
        escribir_valores_esperados(tablas, valores_esperados)
    return {"corridas": len(resumenes), "tablas": tablas}


def calcular_valores_esperados(tablas: dict) -> dict:
    """Valores que cada medida DAX debe mostrar SIN filtros (para validar en Desktop)."""
    senales, precios = tablas["fact_senales"], tablas["fact_precios"]
    corridas, resultados = tablas["dim_corrida"], tablas["fact_resultados_activo"]
    actuales = senales[senales["es_ultima"]]
    ultima_corrida = corridas[corridas["es_ultima_corrida"]].iloc[0]
    res_ultima = resultados[resultados["run_id"] == ultima_corrida["run_id"]]
    ultimas_velas = precios[precios["es_ultima_vela"]].set_index("ticker")
    return {
        "Activos con señal actual": int(actuales["ticker"].nunique()),
        "Activos (filas de precios, NO usar en tarjetas)": int(len(precios)),
        "Distribución actual por señal": actuales["señal"].value_counts().sort_index().to_dict(),
        "Activos actuales con dato válido": int((actuales["estado_dato"] == "valido").sum()),
        "Última actualización (UTC)": str(senales["generado_utc"].max()),
        "Última corrida": f"{ultima_corrida['run_id']} ({ultima_corrida['estado']})",
        "Activos con problema en la última corrida": int((res_ultima["estado"] != "valido").sum()),
        "RSI última vela por activo": {t: round(float(v), 2)
                                       for t, v in ultimas_velas["rsi"].items() if pd.notna(v)},
        "Último cierre por activo": {t: round(float(v), 4) for t, v in ultimas_velas["close"].items()},
        "Corridas totales": int(len(corridas)),
        "Señales históricas (filas)": int(len(senales)),
    }


def escribir_valores_esperados(tablas: dict, ruta: str) -> None:
    valores = calcular_valores_esperados(tablas)
    lineas = ["# Valores esperados de las medidas (demo sintética)", "",
              "Generado por `demo/generar_demo.py` a partir de `powerbi/datos_demo/`. Con el informe "
              "SIN filtros, cada medida de `powerbi/medidas.dax` debe mostrar estos valores. Si no "
              "coinciden, revisá relaciones y contexto de filtro antes de publicar.", ""]
    for nombre, valor in valores.items():
        if isinstance(valor, dict):
            lineas.append(f"- **{nombre}:**")
            lineas += [f"  - {k}: {v}" for k, v in valor.items()]
        else:
            lineas.append(f"- **{nombre}:** {valor}")
    with open(ruta, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lineas) + "\n")


def main_cli(argv=None) -> int:
    configurar_salida_utf8()
    parser = argparse.ArgumentParser(description="Genera la demo sintética reproducible.")
    parser.add_argument("--dias", type=int, default=7, help="días simulados (corridas horarias)")
    args = parser.parse_args(argv)
    resultado = generar(args.dias)
    print(f"✔ {resultado['corridas']} corridas simuladas")
    for nombre, df in resultado["tablas"].items():
        print(f"  {nombre}.csv: {len(df)} filas")
    print(f"CSV en {os.path.relpath(DESTINO_CSV, RAIZ)}/ y valores esperados en "
          f"{os.path.relpath(VALORES_ESPERADOS, RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main_cli())

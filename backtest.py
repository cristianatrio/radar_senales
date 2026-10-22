"""
Backtest reproducible de las señales del radar. NO promete rentabilidad:
mide qué habría pasado con reglas fijas, costos y datos fuera de muestra.

Reglas (long-only, una posición por activo, sin apalancamiento):
- La señal de la vela t se calcula con velas <= t ya cerradas (mismo motor
  que el radar: senales.generar_señal). Los indicadores son causales.
- Entrada: si fuerza(t) >= umbral_entrada y la señal no es RIESGO_ALTO,
  se compra en la APERTURA de t+1 (nunca al cierre que generó la señal).
- Salida: si fuerza(t) <= umbral_salida, o tras `max_barras` velas, se vende
  en la apertura de t+1. Al final de cada segmento se cierra al último cierre.
- Costos por lado: comisión + spread/slippage (configurable por tipo de activo).
- Partición cronológica: train (60%) / validación (20%) / test (20%).
  Los parámetros se eligen SOLO en train; validación y test se reportan
  después y no influyen en la elección. Test es el resultado fuera de muestra.
- Benchmarks: comprar y mantener (con costos) y quedarse en efectivo (0%).

Uso:
    python backtest.py --demo                    # datos sintéticos (reproducible)
    python backtest.py --db output/radar.db      # historia local acumulada por el radar
    python backtest.py --csv datos.csv           # CSV propio (ver cargar_csv)
    python backtest.py --demo --salida docs/backtest_demo.md
"""

import argparse
import itertools
import json
import math
import sqlite3
import sys
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

import config
from indicadores import enriquecer_con_indicadores, velas_minimas
from senales import generar_señal
from consola import configurar_salida_utf8

PROPORCIONES = (0.6, 0.2, 0.2)
BARRAS_POR_AÑO = {"1h": 24 * 365, "4h": 6 * 365, "1d": 252, "1wk": 52}
MIN_OPERACIONES_SELECCION = 3


@dataclass(frozen=True)
class Costos:
    comision_pct: float   # por lado, en %
    slippage_pct: float   # spread + deslizamiento por lado, en %

    @property
    def por_lado(self) -> float:
        return (self.comision_pct + self.slippage_pct) / 100


# Supuestos documentados (ajustalos a tu broker/exchange real):
# - Binance spot: 0.10% de comisión + ~0.05% de spread/slippage en pares líquidos.
# - EE. UU.: 0.10% (broker con comisión) + 0.05%.
# - BYMA (acciones/CEDEARs): ~0.60% (comisión + derechos de mercado) + 0.20% de
#   spread en papeles menos líquidos.
COSTOS_POR_TIPO = {
    "cripto": Costos(0.10, 0.05),
    "accion_us": Costos(0.10, 0.05),
    "accion_arg": Costos(0.60, 0.20),
    "cedear": Costos(0.60, 0.20),
}


@dataclass(frozen=True)
class Parametros:
    umbral_entrada: int = 2        # COMPRA_PROBABLE o más
    umbral_salida: int = -2        # VENTA_PROBABLE o menos
    max_barras: int | None = None  # salida por tiempo (None = sin límite)


PARAMETROS_RADAR = Parametros()   # la regla tal como la etiqueta el radar
GRILLA = [Parametros(e, s, m) for e, s, m in itertools.product((2, 3, 4), (-2, 0), (None,))]


# ============================================================
# Señales causales
# ============================================================

def calcular_señales(df: pd.DataFrame, cfg=config) -> pd.DataFrame:
    """
    Devuelve una fila por vela con la señal que el radar habría emitido al
    cierre de esa vela, usando solo información disponible hasta ese cierre.
    """
    df = df.sort_values("timestamp_utc").reset_index(drop=True)
    enriquecido = enriquecer_con_indicadores(df, cfg)
    minimo = velas_minimas(cfg)
    fuerzas = np.zeros(len(enriquecido), dtype=int)
    señales = np.array(["SIN_DATOS"] * len(enriquecido), dtype=object)
    for t in range(minimo - 1, len(enriquecido)):
        r = generar_señal(enriquecido.iloc[t - minimo + 1:t + 1], cfg)
        fuerzas[t], señales[t] = r["fuerza"], r["señal"]
    return pd.DataFrame({
        "timestamp_utc": enriquecido["timestamp_utc"],
        "open": enriquecido["open"], "close": enriquecido["close"],
        "fuerza": fuerzas, "señal": señales,
    })


def particionar(n: int, inicio: int, proporciones=PROPORCIONES) -> dict:
    """Índices [desde, hasta) cronológicos y sin solapamiento para train/validación/test."""
    disponible = n - inicio
    cortes = np.cumsum([int(disponible * p) for p in proporciones[:-1]])
    limites = [inicio, inicio + cortes[0], inicio + cortes[1], n]
    return {nombre: (limites[i], limites[i + 1])
            for i, nombre in enumerate(("train", "validacion", "test"))}


# ============================================================
# Simulación
# ============================================================

def simular(señales: pd.DataFrame, desde: int, hasta: int, params: Parametros,
            costos: Costos) -> dict:
    """Simula la regla en las velas [desde, hasta). Devuelve curva y operaciones."""
    abre = señales["open"].to_numpy()
    cierra = señales["close"].to_numpy()
    fuerza = señales["fuerza"].to_numpy()
    etiqueta = señales["señal"].to_numpy()
    c = costos.por_lado

    capital, unidades, en_posicion = 1.0, 0.0, False
    entrada_capital, barras_en_pos, barras_expuestas = 0.0, 0, 0
    curva, operaciones = [], []

    for t in range(desde, hasta):
        # 1) Ejecutar en la apertura de t la orden decidida al cierre de t-1.
        if t > desde:
            previa = t - 1
            if not en_posicion and fuerza[previa] >= params.umbral_entrada \
                    and etiqueta[previa] != "RIESGO_ALTO":
                entrada_capital = capital
                unidades = capital / (abre[t] * (1 + c))
                en_posicion, barras_en_pos = True, 0
            elif en_posicion and (fuerza[previa] <= params.umbral_salida or
                                  (params.max_barras and barras_en_pos >= params.max_barras)):
                capital = unidades * abre[t] * (1 - c)
                operaciones.append(capital / entrada_capital - 1)
                en_posicion, unidades = False, 0.0
        # 2) Valuar al cierre de t.
        if en_posicion:
            barras_en_pos += 1
            barras_expuestas += 1
            capital_marcado = unidades * cierra[t]
        else:
            capital_marcado = capital
        curva.append(capital_marcado)

    if en_posicion:  # cierre forzado al final del segmento
        capital = unidades * cierra[hasta - 1] * (1 - c)
        operaciones.append(capital / entrada_capital - 1)
        curva[-1] = capital

    return {"curva": np.array(curva), "operaciones": operaciones,
            "exposicion": barras_expuestas / max(hasta - desde, 1)}


def max_drawdown(curva: np.ndarray) -> float:
    if len(curva) == 0:
        return 0.0
    picos = np.maximum.accumulate(curva)
    return float(((curva - picos) / picos).min())


def anualizar(retorno: float, barras: int, intervalo: str) -> float | None:
    por_año = BARRAS_POR_AÑO.get(intervalo)
    if not por_año or barras < por_año / 4 or retorno <= -1:
        return None  # menos de ~3 meses: anualizar exagera
    return (1 + retorno) ** (por_año / barras) - 1


def metricas(sim: dict, intervalo: str) -> dict:
    curva, ops = sim["curva"], sim["operaciones"]
    retorno = float(curva[-1] - 1) if len(curva) else 0.0
    return {
        "retorno_total": retorno,
        "retorno_anualizado": anualizar(retorno, len(curva), intervalo),
        "max_drawdown": max_drawdown(curva),
        "operaciones": len(ops),
        "tasa_acierto": (sum(1 for r in ops if r > 0) / len(ops)) if ops else None,
        "retorno_medio_operacion": float(np.mean(ops)) if ops else None,
        "exposicion": sim["exposicion"],
    }


def comprar_y_mantener(señales: pd.DataFrame, desde: int, hasta: int, costos: Costos,
                       intervalo: str) -> dict:
    c = costos.por_lado
    abre, cierra = señales["open"].to_numpy(), señales["close"].to_numpy()
    unidades = 1.0 / (abre[desde] * (1 + c))
    curva = unidades * cierra[desde:hasta]
    curva[-1] *= (1 - c)
    sim = {"curva": curva, "operaciones": [curva[-1] - 1], "exposicion": 1.0}
    return metricas(sim, intervalo)


# ============================================================
# Evaluación por activo y por grupo
# ============================================================

def elegir_parametros(señales: pd.DataFrame, train: tuple, costos: Costos, intervalo: str):
    """Elige parámetros usando EXCLUSIVAMENTE el segmento de train."""
    candidatos = []
    for params in GRILLA:
        m = metricas(simular(señales, *train, params, costos), intervalo)
        if m["operaciones"] >= MIN_OPERACIONES_SELECCION:
            candidatos.append((m["retorno_total"], -m["operaciones"], params))
    if not candidatos:
        return PARAMETROS_RADAR
    return max(candidatos, key=lambda x: (x[0], x[1]))[2]


def evaluar_activo(df: pd.DataFrame, tipo: str, intervalo: str, cfg=config) -> dict:
    costos = COSTOS_POR_TIPO[tipo]
    señales = calcular_señales(df, cfg)
    segmentos = particionar(len(señales), velas_minimas(cfg))
    elegidos = elegir_parametros(señales, segmentos["train"], costos, intervalo)

    resultado = {"ticker": df["ticker"].iloc[0], "tipo": tipo, "intervalo": intervalo,
                 "velas": len(señales), "parametros_elegidos_en_train": asdict(elegidos),
                 "segmentos": {}}
    for nombre, (desde, hasta) in segmentos.items():
        resultado["segmentos"][nombre] = {
            "desde_utc": str(señales["timestamp_utc"].iloc[desde]),
            "hasta_utc": str(señales["timestamp_utc"].iloc[hasta - 1]),
            "regla_radar": metricas(simular(señales, desde, hasta, PARAMETROS_RADAR, costos), intervalo),
            "regla_elegida": metricas(simular(señales, desde, hasta, elegidos, costos), intervalo),
            "comprar_y_mantener": comprar_y_mantener(señales, desde, hasta, costos, intervalo),
        }
    return resultado


def contar_huecos(df: pd.DataFrame, intervalo: str) -> int:
    """Huecos de más de 1.5 velas (sin contar fines de semana en 1d)."""
    ts = pd.to_datetime(df["timestamp_utc"]).sort_values()
    if intervalo == "1d":
        dias = pd.Series(np.busday_count(ts.dt.date.values[:-1].astype("datetime64[D]"),
                                         ts.dt.date.values[1:].astype("datetime64[D]")))
        return int((dias > 1).sum())
    paso = pd.Timedelta(hours=1) if intervalo == "1h" else pd.Timedelta(hours=4)
    return int((ts.diff().dropna() > 1.5 * paso).sum())


def evaluar_grupo(datos: dict, tipo_por_ticker: dict, intervalo: str, cfg=config) -> dict:
    """Evalúa por separado cada activo de un grupo (mismo intervalo) y agrega."""
    activos, omitidos = [], []
    minimo = velas_minimas(cfg) + 100
    for ticker, df in sorted(datos.items()):
        if len(df) < minimo:
            omitidos.append(f"{ticker} ({len(df)} velas, se requieren {minimo})")
            continue
        res = evaluar_activo(df, tipo_por_ticker[ticker], intervalo, cfg)
        res["huecos"] = contar_huecos(df, intervalo)
        activos.append(res)
    return {"intervalo": intervalo, "activos": activos, "omitidos": omitidos,
            "agregado": agregar(activos)}


def agregar(activos: list) -> dict:
    """Promedios simples entre activos (cada activo pesa igual)."""
    salida = {}
    for segmento in ("train", "validacion", "test"):
        filas = {}
        for regla in ("regla_radar", "regla_elegida", "comprar_y_mantener"):
            valores = [a["segmentos"][segmento][regla] for a in activos]
            if not valores:
                continue
            filas[regla] = {
                "retorno_medio": float(np.mean([v["retorno_total"] for v in valores])),
                "drawdown_medio": float(np.mean([v["max_drawdown"] for v in valores])),
                "operaciones": int(sum(v["operaciones"] for v in valores)),
                "exposicion_media": float(np.mean([v["exposicion"] for v in valores])),
                "activos_que_superan_byh": None,
            }
            if regla != "comprar_y_mantener":
                filas[regla]["activos_que_superan_byh"] = sum(
                    1 for a in activos if a["segmentos"][segmento][regla]["retorno_total"]
                    > a["segmentos"][segmento]["comprar_y_mantener"]["retorno_total"])
        salida[segmento] = filas
    return salida


# ============================================================
# Carga de datos
# ============================================================

def datos_demo() -> tuple:
    """Series sintéticas reproducibles: 3 cripto 1h y 3 acciones 1d."""
    from datos_sinteticos import SerieSintetica, generar_ohlcv
    inicio = pd.Timestamp("2023-01-02", tz="UTC")
    cripto = {f"{n}USDT": generar_ohlcv(SerieSintetica(f"{n}USDT", "sintetico", "USDT", "1h",
                                                       p, 0.008, s), 4000, inicio)
              for n, p, s in (("ALFA", 100.0, 101), ("BETA", 5.0, 102), ("GAMA", 0.5, 103))}
    acciones = {t: generar_ohlcv(SerieSintetica(t, "sintetico", m, "1d", p, 0.02, s, tz),
                                 1200, inicio)
                for t, m, p, s, tz in (("ACME", "USD", 50.0, 201, "America/New_York"),
                                       ("GLOBX", "USD", 120.0, 202, "America/New_York"),
                                       ("ANDES.BA", "ARS", 900.0, 203,
                                        "America/Argentina/Buenos_Aires"))}
    tipos = {**{t: "cripto" for t in cripto}, "ACME": "accion_us", "GLOBX": "accion_us",
             "ANDES.BA": "accion_arg"}
    return {"cripto 1h": (cripto, "1h"), "acciones 1d": (acciones, "1d")}, tipos


def _tipo_desde_ticker(ticker: str, fuente: str) -> str:
    if fuente == "binance":
        return "cripto"
    return "accion_arg" if ticker.endswith(".BA") else "accion_us"


def cargar_db(path_db: str) -> tuple:
    """
    Lee precios_ohlcv de una DB local (solo lectura). Si la fila no tiene
    timestamp_utc (versiones anteriores), Binance ya estaba en UTC y para
    Yahoo diario se usa la fecha (00:00 UTC aproximado: no afecta el orden).
    """
    conn = sqlite3.connect(f"file:{path_db}?mode=ro", uri=True)
    try:
        df = pd.read_sql_query("SELECT * FROM precios_ohlcv", conn)
    finally:
        conn.close()
    if "timestamp_utc" not in df.columns:
        df["timestamp_utc"] = None
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"].fillna(df["timestamp"]), utc=True,
                                       format="mixed")
    return _agrupar(df)


def cargar_csv(path_csv: str) -> tuple:
    """CSV con columnas: ticker, fuente (binance|yahoo), timestamp_utc, open, high, low, close, volume."""
    df = pd.read_csv(path_csv)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    return _agrupar(df)


def _agrupar(df: pd.DataFrame) -> tuple:
    grupos = {"cripto 1h": ({}, config.INTERVALO_CRIPTO),
              "acciones 1d": ({}, config.INTERVALO_ACCIONES)}
    tipos = {}
    for (ticker, fuente), g in df.groupby(["ticker", "fuente"]):
        tipo = _tipo_desde_ticker(ticker, fuente)
        destino = "cripto 1h" if tipo == "cripto" else "acciones 1d"
        serie = g[["timestamp_utc", "open", "high", "low", "close", "volume"]].dropna()
        serie = serie.drop_duplicates("timestamp_utc").sort_values("timestamp_utc")
        grupos[destino][0][ticker] = serie.assign(ticker=ticker).reset_index(drop=True)
        tipos[ticker] = tipo
    return grupos, tipos


# ============================================================
# Reporte
# ============================================================

def _pct(valor) -> str:
    return "—" if valor is None or (isinstance(valor, float) and math.isnan(valor)) else f"{valor:+.1%}"


def reporte_markdown(resultados: dict, origen: str) -> str:
    lineas = [
        "# Backtest de señales del radar",
        "",
        f"**Origen de datos:** {origen}",
        "",
        "> **Aviso:** resultados históricos/simulados con supuestos de costos. No son una "
        "promesa de rentabilidad ni una recomendación. `fuerza` es un puntaje heurístico, "
        "no una probabilidad. Los datos sintéticos solo validan la mecánica del backtest.",
        "",
        "Reglas: señal al cierre de t, ejecución en la apertura de t+1; long-only; costos por "
        "lado según tipo de activo; partición cronológica 60/20/20; parámetros elegidos solo "
        "en train; test = fuera de muestra. `regla_radar` = entrar con fuerza ≥ 2 (sin "
        "RIESGO_ALTO) y salir con fuerza ≤ −2, sin optimizar.",
        "",
    ]
    for grupo, res in resultados.items():
        lineas += [f"## {grupo}", ""]
        if not res["activos"]:
            lineas += ["Sin activos con historia suficiente.", ""]
        for segmento in ("train", "validacion", "test"):
            agregado = res["agregado"].get(segmento, {})
            if not agregado:
                continue
            titulo = {"train": "Train (selección de parámetros)", "validacion": "Validación",
                      "test": "Test (fuera de muestra)"}[segmento]
            lineas += [f"### {titulo} — promedio entre {len(res['activos'])} activos", "",
                       "| Regla | Retorno medio | Drawdown medio | Operaciones | Exposición | "
                       "Activos > comprar y mantener |",
                       "|---|---:|---:|---:|---:|---:|"]
            for regla, m in agregado.items():
                supera = "—" if m["activos_que_superan_byh"] is None else \
                    f"{m['activos_que_superan_byh']}/{len(res['activos'])}"
                lineas.append(f"| {regla} | {_pct(m['retorno_medio'])} | {_pct(m['drawdown_medio'])} | "
                              f"{m['operaciones']} | {m['exposicion_media']:.0%} | {supera} |")
            lineas.append("")
        lineas += ["### Detalle por activo (test)", "",
                   "| Activo | Velas | Huecos | Parámetros (train) | Retorno radar | Acierto | "
                   "Ops | Retorno elegida | Comprar y mantener | DD radar |",
                   "|---|---:|---:|---|---:|---:|---:|---:|---:|---:|"]
        for a in res["activos"]:
            t = a["segmentos"]["test"]
            p = a["parametros_elegidos_en_train"]
            acierto = t["regla_radar"]["tasa_acierto"]
            lineas.append(
                f"| {a['ticker']} | {a['velas']} | {a['huecos']} | "
                f"entrada≥{p['umbral_entrada']}, salida≤{p['umbral_salida']} | "
                f"{_pct(t['regla_radar']['retorno_total'])} | "
                f"{'—' if acierto is None else f'{acierto:.0%}'} | {t['regla_radar']['operaciones']} | "
                f"{_pct(t['regla_elegida']['retorno_total'])} | "
                f"{_pct(t['comprar_y_mantener']['retorno_total'])} | "
                f"{_pct(t['regla_radar']['max_drawdown'])} |")
        if res["omitidos"]:
            lineas += ["", "Omitidos por historia insuficiente: " + ", ".join(res["omitidos"])]
        lineas.append("")
    lineas += [
        "## Límites",
        "",
        "- Pocas operaciones por segmento implican mucha incertidumbre: no hay test estadístico de significancia.",
        "- Superar a comprar y mantener cuando el mercado cae puede deberse solo a estar menos tiempo expuesto, no a capacidad predictiva: compará también exposición y drawdown.",
        "- Si `regla_elegida` rinde mejor en train que en validación/test, es sobreajuste: la selección se hizo solo en train justamente para poder verlo.",
        "- Costos fijos supuestos; no modela libro de órdenes, gaps extremos, impuestos ni dividendos en efectivo.",
        "- Acciones argentinas: retornos NOMINALES en ARS (incluyen inflación/devaluación); comparalos solo contra su propio comprar y mantener.",
        "- Cripto opera 24/7 en USDT; las acciones solo en días hábiles (la apertura de t+1 incluye el gap nocturno).",
        "- Indicadores calculados sobre toda la historia previa a t (el radar usa las últimas ~200 velas; tras ~100 velas la diferencia de inicialización de RSI/EMA es despreciable).",
        "- Con datos del radar (`--db`) la historia puede tener huecos (PC apagada, fallos de proveedor) y precios no ajustados en filas antiguas.",
    ]
    return "\n".join(lineas) + "\n"


def main(argv=None) -> int:
    configurar_salida_utf8()
    parser = argparse.ArgumentParser(description="Backtest sin lookahead de las señales del radar.")
    origen = parser.add_mutually_exclusive_group(required=True)
    origen.add_argument("--demo", action="store_true", help="datos sintéticos reproducibles")
    origen.add_argument("--db", help="ruta a una DB local del radar (se abre en solo lectura)")
    origen.add_argument("--csv", help="CSV con OHLCV propio")
    parser.add_argument("--salida", help="guarda el reporte Markdown en este archivo")
    parser.add_argument("--json", help="guarda los resultados completos en JSON")
    args = parser.parse_args(argv)

    if args.demo:
        grupos, tipos = datos_demo()
        descripcion = "datos SINTÉTICOS generados con semilla fija (no representan mercados reales)"
    elif args.db:
        grupos, tipos = cargar_db(args.db)
        descripcion = "historia local acumulada por el radar (privada: no publicar el reporte sin revisarlo)"
    else:
        grupos, tipos = cargar_csv(args.csv)
        descripcion = f"CSV provisto por el usuario ({args.csv})"

    resultados = {nombre: evaluar_grupo(datos, tipos, intervalo)
                  for nombre, (datos, intervalo) in grupos.items()}
    reporte = reporte_markdown(resultados, descripcion)
    if args.salida:
        with open(args.salida, "w", encoding="utf-8") as f:
            f.write(reporte)
        print(f"✔ Reporte guardado en {args.salida}")
    else:
        print(reporte)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(resultados, f, ensure_ascii=False, indent=2, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())

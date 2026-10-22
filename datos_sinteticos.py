"""
Generador de datos de mercado SINTÉTICOS y reproducibles (semilla fija).

Se usa en los tests, en la demo pública y en el backtest de demostración.
Los activos tienen nombres ficticios y los precios no representan ningún
mercado real: sirven para verificar la mecánica del sistema, no para sacar
conclusiones de inversión.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from fuentes.normalizacion import COLUMNAS_NORMALIZADAS, duracion_intervalo


@dataclass(frozen=True)
class SerieSintetica:
    ticker: str
    fuente: str
    moneda: str
    intervalo: str
    precio_inicial: float
    volatilidad: float      # desvío por vela de los retornos logarítmicos
    semilla: int
    tz_original: str = "UTC"


def _marcas_de_tiempo(inicio_utc: pd.Timestamp, n: int, intervalo: str, tz: str) -> pd.DatetimeIndex:
    """Inicios de vela: continuos para intradiario; días hábiles para 1d (hora local 00:00)."""
    if intervalo == "1d":
        inicio_local = inicio_utc.tz_convert(tz).normalize().tz_localize(None)
        dias = pd.bdate_range(inicio_local, periods=n)
        return dias.tz_localize(tz)
    paso = duracion_intervalo(intervalo)
    return pd.date_range(inicio_utc.floor(paso), periods=n, freq=paso)  # alineado al intervalo


def generar_ohlcv(serie: SerieSintetica, n: int, inicio_utc) -> pd.DataFrame:
    """
    Serie con cambios de régimen (tendencias alcistas/bajistas/laterales),
    mechas y picos de volumen ocasionales. Devuelve el esquema normalizado.
    """
    rng = np.random.default_rng(serie.semilla)
    inicio_utc = pd.Timestamp(inicio_utc)
    inicio_utc = inicio_utc.tz_localize("UTC") if inicio_utc.tzinfo is None else inicio_utc

    # Regímenes de 30 a 150 velas con deriva aleatoria.
    deriva = np.empty(n)
    i = 0
    while i < n:
        largo = int(rng.integers(30, 150))
        deriva[i:i + largo] = rng.choice([-1.0, 0.0, 1.0]) * serie.volatilidad * rng.uniform(0.05, 0.25)
        i += largo
    retornos = deriva + rng.normal(0.0, serie.volatilidad, n)
    cierre = serie.precio_inicial * np.exp(np.cumsum(retornos))
    apertura = np.concatenate([[serie.precio_inicial], cierre[:-1]]) * np.exp(
        rng.normal(0.0, serie.volatilidad * 0.2, n))
    mecha_sup = np.abs(rng.normal(0.0, serie.volatilidad * 0.5, n))
    mecha_inf = np.abs(rng.normal(0.0, serie.volatilidad * 0.5, n))
    maximo = np.maximum(apertura, cierre) * (1 + mecha_sup)
    minimo = np.minimum(apertura, cierre) * (1 - mecha_inf)
    volumen = rng.lognormal(mean=10.0, sigma=0.4, size=n)
    picos = rng.random(n) < 0.03
    volumen[picos] *= rng.uniform(2.0, 5.0, picos.sum())

    inicios = _marcas_de_tiempo(inicio_utc, n, serie.intervalo, serie.tz_original)
    cierres = inicios + duracion_intervalo(serie.intervalo)
    df = pd.DataFrame({
        "timestamp": inicios.tz_localize(None),
        "timestamp_utc": inicios.tz_convert("UTC"),
        "cierre_utc": cierres.tz_convert("UTC"),
        "tz_original": serie.tz_original,
        "open": apertura, "high": maximo, "low": minimo, "close": cierre, "volume": volumen,
        "ticker": serie.ticker, "fuente": serie.fuente, "moneda": serie.moneda,
        "ajuste": "sintetico",
    })
    return df[COLUMNAS_NORMALIZADAS]


class ProveedorSintetico:
    """
    Simula un proveedor: dado el "ahora" del reloj, devuelve las últimas
    `ventana` velas cuyo inicio ya ocurrió (incluye la vela abierta, como
    las APIs reales, para ejercitar el filtro de velas cerradas).
    """

    def __init__(self, series: dict, reloj, ventana: int = 200):
        self.series = series      # ticker -> DataFrame completo
        self.reloj = reloj
        self.ventana = ventana

    def __call__(self, activo) -> pd.DataFrame:
        df = self.series.get(activo.ticker)
        if df is None:
            return pd.DataFrame(columns=COLUMNAS_NORMALIZADAS)
        ahora = pd.Timestamp(self.reloj())
        visibles = df[df["timestamp_utc"] <= ahora]
        return visibles.tail(self.ventana).reset_index(drop=True)

"""
Normalización y validación de velas OHLCV, común a todos los proveedores.

Esquema normalizado que devuelve cada proveedor (una fila por vela):
    timestamp      inicio de la vela tal como lo informa la fuente, sin zona
                   horaria (Binance: UTC; Yahoo: hora local del mercado).
                   Se conserva por compatibilidad con la DB y los CSV previos.
    timestamp_utc  inicio de la vela en UTC (tz-aware).
    cierre_utc     cierre de la vela en UTC (tz-aware).
    tz_original    zona horaria de `timestamp` (ej. "UTC", "America/New_York").
    open, high, low, close, volume
    ticker, fuente, moneda, ajuste
"""

import numpy as np
import pandas as pd

COLUMNAS_PRECIO = ["open", "high", "low", "close"]
COLUMNAS_NORMALIZADAS = [
    "timestamp", "timestamp_utc", "cierre_utc", "tz_original",
    "open", "high", "low", "close", "volume",
    "ticker", "fuente", "moneda", "ajuste",
]

# Duración de cada intervalo soportado. Para velas diarias o semanales se usa
# un desplazamiento de calendario para respetar los cambios de horario (DST).
DURACION_INTERVALO = {
    "1m": pd.Timedelta(minutes=1),
    "5m": pd.Timedelta(minutes=5),
    "15m": pd.Timedelta(minutes=15),
    "30m": pd.Timedelta(minutes=30),
    "1h": pd.Timedelta(hours=1),
    "60m": pd.Timedelta(hours=1),
    "4h": pd.Timedelta(hours=4),
    "1d": pd.DateOffset(days=1),
    "1wk": pd.DateOffset(weeks=1),
}


def duracion_intervalo(intervalo: str):
    try:
        return DURACION_INTERVALO[intervalo]
    except KeyError:
        raise ValueError(f"Intervalo no soportado: {intervalo}") from None


def a_utc(serie: pd.Series) -> pd.Series:
    """Convierte una serie de fechas a UTC. Las fechas sin zona se asumen UTC."""
    serie = pd.to_datetime(serie)
    if serie.dt.tz is None:
        return serie.dt.tz_localize("UTC")
    return serie.dt.tz_convert("UTC")


def validar_ohlcv(df: pd.DataFrame) -> tuple:
    """
    Descarta velas inválidas y devuelve (df_valido, cantidad_descartada).

    Una vela es inválida si algún precio no es finito o no es positivo, si el
    volumen es negativo/no finito, si high/low no envuelven a open/close o si
    su timestamp está duplicado. El resultado queda ordenado por timestamp_utc.
    """
    if df.empty:
        return df.copy(), 0

    precios = df[COLUMNAS_PRECIO].apply(pd.to_numeric, errors="coerce")
    volumen = pd.to_numeric(df["volume"], errors="coerce")

    finitos = np.isfinite(precios).all(axis=1) & np.isfinite(volumen)
    positivos = (precios > 0).all(axis=1) & (volumen >= 0)
    coherentes = (
        (precios["high"] >= precios[["open", "close", "low"]].max(axis=1))
        & (precios["low"] <= precios[["open", "close"]].min(axis=1))
    )
    no_duplicado = ~df["timestamp_utc"].duplicated(keep="last")

    validas = finitos & positivos & coherentes & no_duplicado
    limpio = df.loc[validas].copy()
    limpio[COLUMNAS_PRECIO] = precios.loc[validas]
    limpio["volume"] = volumen.loc[validas]
    limpio = limpio.sort_values("timestamp_utc").reset_index(drop=True)
    return limpio, int((~validas).sum())


def filtrar_velas_cerradas(df: pd.DataFrame, ahora_utc: pd.Timestamp) -> tuple:
    """
    Deja solo las velas cuyo cierre ya ocurrió en `ahora_utc`.
    Devuelve (df_cerradas, cantidad_abiertas_descartadas).

    Las señales se calculan únicamente sobre velas cerradas: una vela abierta
    cambia hasta su cierre y produciría señales que luego "desaparecen".
    """
    if df.empty:
        return df.copy(), 0
    cerradas = df["cierre_utc"] <= ahora_utc
    return df.loc[cerradas].reset_index(drop=True), int((~cerradas).sum())

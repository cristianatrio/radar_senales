"""
Indicadores técnicos calculados con pandas/numpy (sin dependencias externas).

Convenciones:
- Todas las funciones son causales: el valor en la vela t usa solo velas <= t.
- Durante el período de calentamiento el indicador vale NaN (no 0 ni 50):
  "sin dato suficiente" es distinto de "valor neutral".
- Las series de entrada deben venir validadas (sin NaN, finitas y positivas);
  si no, se lanza ValueError en lugar de propagar NaN silenciosamente.
"""

import numpy as np
import pandas as pd

PERIODO_RUPTURA = 20
VOLUMEN_PERIODO = 20


def _validar_precios(precios: pd.Series) -> None:
    valores = pd.to_numeric(precios, errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(valores).all() or (valores <= 0).any():
        raise ValueError("La serie de precios tiene NaN, infinitos o valores <= 0")


def _rsi_desde_promedios(avg_ganancia: float, avg_perdida: float) -> float:
    if avg_ganancia == 0 and avg_perdida == 0:
        return 50.0  # serie plana: neutral por definición
    if avg_perdida == 0:
        return 100.0
    rs = avg_ganancia / avg_perdida
    return 100.0 - 100.0 / (1.0 + rs)


def calcular_rsi(precios: pd.Series, periodo: int = 14) -> pd.Series:
    """
    Relative Strength Index (Wilder).

    Inicialización documentada: el primer promedio de ganancias y pérdidas es
    la media simple de los primeros `periodo` cambios (como Wilder y
    TradingView). Luego se suaviza con alpha = 1/periodo. Las primeras
    `periodo` velas quedan en NaN.

    Casos límite: serie plana -> 50; solo subas -> 100; solo bajas -> 0.
    """
    _validar_precios(precios)
    valores = precios.to_numpy(dtype=float)
    rsi = np.full(len(valores), np.nan)
    if len(valores) <= periodo:
        return pd.Series(rsi, index=precios.index)

    delta = np.diff(valores)
    ganancias = np.clip(delta, 0, None)
    perdidas = np.clip(-delta, 0, None)

    avg_g = ganancias[:periodo].mean()
    avg_p = perdidas[:periodo].mean()
    rsi[periodo] = _rsi_desde_promedios(avg_g, avg_p)
    for i in range(periodo + 1, len(valores)):
        avg_g = (avg_g * (periodo - 1) + ganancias[i - 1]) / periodo
        avg_p = (avg_p * (periodo - 1) + perdidas[i - 1]) / periodo
        rsi[i] = _rsi_desde_promedios(avg_g, avg_p)
    return pd.Series(rsi, index=precios.index)


def calcular_macd(precios: pd.Series, rapida: int = 12, lenta: int = 26, señal: int = 9) -> pd.DataFrame:
    """
    MACD = EMA(rapida) - EMA(lenta)
    Señal = EMA(MACD, periodo_señal)
    Histograma = MACD - Señal

    Calentamiento: MACD es NaN en las primeras `lenta - 1` velas y la señal /
    el histograma en las primeras `lenta + señal - 2`.
    """
    _validar_precios(precios)
    ema_rapida = precios.ewm(span=rapida, adjust=False).mean()
    ema_lenta = precios.ewm(span=lenta, adjust=False).mean()
    macd = ema_rapida - ema_lenta
    linea_señal = macd.ewm(span=señal, adjust=False).mean()
    histograma = macd - linea_señal

    posicion = np.arange(len(precios))
    macd = macd.where(posicion >= lenta - 1)
    linea_señal = linea_señal.where(posicion >= lenta + señal - 2)
    histograma = histograma.where(posicion >= lenta + señal - 2)

    return pd.DataFrame({
        "macd": macd,
        "macd_señal": linea_señal,
        "macd_hist": histograma,
    })


def calcular_media_movil(precios: pd.Series, periodo: int) -> pd.Series:
    """Media móvil simple (NaN hasta tener `periodo` velas)."""
    return precios.rolling(window=periodo, min_periods=periodo).mean()


def calcular_volumen_relativo(volumen: pd.Series, periodo: int = VOLUMEN_PERIODO) -> pd.Series:
    """
    Volumen de la vela / promedio de las `periodo` velas ANTERIORES.
    La vela actual no entra en su propio baseline (si no, un pico de volumen
    se diluye a sí mismo). NaN durante el calentamiento o si el baseline es 0.
    Valores > 1.5 indican volumen anormalmente alto.
    """
    base = volumen.shift(1).rolling(window=periodo, min_periods=periodo).mean()
    return volumen / base.where(base > 0)


def detectar_ruptura(df: pd.DataFrame, periodo: int = PERIODO_RUPTURA) -> dict:
    """
    Detecta si el cierre de la última vela superó el máximo (o perforó el
    mínimo) de las `periodo` velas anteriores.
    """
    if len(df) < periodo + 1:
        return {"ruptura_max": False, "ruptura_min": False}

    ultimo_close = df["close"].iloc[-1]
    # Excluyo la última vela del rango porque sino se compara consigo misma
    rango = df.iloc[-(periodo + 1):-1]
    max_previo = rango["high"].max()
    min_previo = rango["low"].min()

    return {
        "ruptura_max": bool(ultimo_close > max_previo),
        "ruptura_min": bool(ultimo_close < min_previo),
        "max_previo": max_previo,
        "min_previo": min_previo,
    }


def velas_minimas(config) -> int:
    """Cantidad mínima de velas cerradas para que todas las familias tengan dato."""
    return max(
        config.MA_LARGA,
        config.MACD_LENTA + config.MACD_SEÑAL - 1,
        config.RSI_PERIODO + 1,
        PERIODO_RUPTURA + 1,
        VOLUMEN_PERIODO + 1,
    )


def enriquecer_con_indicadores(df: pd.DataFrame, config) -> pd.DataFrame:
    """
    Toma un DataFrame con OHLCV (velas cerradas y validadas) y le agrega todas
    las columnas de indicadores. Lanza ValueError si los precios son inválidos.
    """
    if df.empty:
        return df

    orden = "timestamp_utc" if "timestamp_utc" in df.columns else "timestamp"
    df = df.copy().sort_values(orden).reset_index(drop=True)

    df["rsi"] = calcular_rsi(df["close"], config.RSI_PERIODO)

    macd_df = calcular_macd(df["close"], config.MACD_RAPIDA, config.MACD_LENTA, config.MACD_SEÑAL)
    df = pd.concat([df, macd_df], axis=1)

    df[f"ma_{config.MA_CORTA}"] = calcular_media_movil(df["close"], config.MA_CORTA)
    df[f"ma_{config.MA_LARGA}"] = calcular_media_movil(df["close"], config.MA_LARGA)

    df["vol_relativo"] = calcular_volumen_relativo(df["volume"], periodo=VOLUMEN_PERIODO)

    return df

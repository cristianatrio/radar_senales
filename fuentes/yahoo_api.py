"""
Cliente de Yahoo Finance vía yfinance (fuente no oficial).
Funciona para acciones argentinas (sufijo .BA, en ARS), CEDEARs (.BA, en ARS)
y acciones/ETFs de EE. UU. (sin sufijo, en USD).

Política de precios:
- Se piden precios AJUSTADOS por splits y dividendos (auto_adjust=True). Así
  un split o un dividendo grande no aparece como una caída artificial que
  dispare RSI/rupturas. El cierre de las velas recientes coincide con el
  precio negociado; las velas anteriores al último evento quedan ajustadas.
- Yahoo devuelve fechas en la zona horaria del mercado. Se conserva ese valor
  sin zona en `timestamp` (compatibilidad) y se agrega `timestamp_utc`.
- Una vela diaria se considera cerrada a la medianoche local siguiente
  (criterio conservador: evita usar la vela parcial del día).
- Fallos de red/rate limit lanzan ErrorProveedor; "sin precios" devuelve un
  DataFrame vacío.
"""

import time

import pandas as pd

from fuentes.normalizacion import COLUMNAS_NORMALIZADAS, duracion_intervalo
from fuentes.red import ErrorProveedor, LimitadorTasa, calcular_espera

PROVEEDOR = "yahoo"
LIMITADOR_YAHOO = LimitadorTasa(intervalo_min_s=0.5)
REINTENTOS_YAHOO = 2
TIMEOUT_YAHOO_S = 15


def _excepciones_yfinance():
    """Clases de error de yfinance (pueden variar entre versiones)."""
    try:
        from yfinance import exceptions as yfe
    except ImportError:  # pragma: no cover - depende de la versión instalada
        return (), (), ()
    sin_datos = tuple(getattr(yfe, n) for n in ("YFPricesMissingError", "YFTickerMissingError")
                      if hasattr(yfe, n))
    transitorias = tuple(getattr(yfe, n) for n in ("YFRateLimitError",) if hasattr(yfe, n))
    zona = tuple(getattr(yfe, n) for n in ("YFTzMissingError",) if hasattr(yfe, n))
    return sin_datos, transitorias, zona


def _fabrica_por_defecto(ticker: str):
    import yfinance as yf
    return yf.Ticker(ticker)


def _moneda_informada(objeto_ticker) -> str | None:
    """
    Moneda que informó Yahoo en la respuesta de history().
    Se lee la metadata ya descargada para no hacer un request adicional;
    si no está disponible se devuelve None (moneda no verificada).
    """
    # yfinance 1.x guarda la metadata en el objeto PriceHistory interno.
    historial = getattr(objeto_ticker, "_price_history", None)
    for meta in (getattr(historial, "_history_metadata", None),
                 getattr(objeto_ticker, "_history_metadata", None)):
        if isinstance(meta, dict) and meta.get("currency"):
            return str(meta["currency"]).upper()
    return None


def history_a_dataframe(df: pd.DataFrame, ticker: str, intervalo: str,
                        moneda: str | None) -> pd.DataFrame:
    """Convierte la salida de yfinance.history() al esquema normalizado."""
    if df is None or df.empty:
        return pd.DataFrame(columns=COLUMNAS_NORMALIZADAS)

    df = df.reset_index()
    fecha_col = "Datetime" if "Datetime" in df.columns else "Date"
    faltantes = {fecha_col, "Open", "High", "Low", "Close", "Volume"} - set(df.columns)
    if faltantes:
        raise ErrorProveedor(PROVEEDOR, f"faltan columnas {sorted(faltantes)}")

    inicio = pd.to_datetime(df[fecha_col])
    if inicio.dt.tz is None:
        # No debería ocurrir con yfinance >= 0.2; se asume UTC y se deja registrado.
        inicio = inicio.dt.tz_localize("UTC")
        tz_original = "UTC (asumida)"
    else:
        tz_original = str(inicio.dt.tz)

    cierre = inicio + duracion_intervalo(intervalo)
    salida = pd.DataFrame({
        "timestamp": inicio.dt.tz_localize(None),
        "timestamp_utc": inicio.dt.tz_convert("UTC"),
        "cierre_utc": cierre.dt.tz_convert("UTC"),
        "tz_original": tz_original,
        "open": df["Open"], "high": df["High"], "low": df["Low"],
        "close": df["Close"], "volume": df["Volume"],
    })
    salida["ticker"] = ticker
    salida["fuente"] = PROVEEDOR
    salida["moneda"] = moneda
    salida["ajuste"] = "split_dividendo"
    return salida[COLUMNAS_NORMALIZADAS]


def obtener_velas_yahoo(ticker: str, intervalo: str = "1d", periodo: str = "1y", *,
                        fabrica_ticker=None, limitador: LimitadorTasa | None = LIMITADOR_YAHOO,
                        reintentos: int = REINTENTOS_YAHOO, dormir=time.sleep) -> pd.DataFrame:
    """
    Trae velas históricas de Yahoo Finance en el esquema normalizado.

    Args:
        ticker: símbolo del activo (ej "GGAL.BA", "AAPL", "SPY")
        intervalo: 1m, 5m, 15m, 30m, 60m, 1h, 1d, 1wk
        periodo: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max

    Raises:
        ErrorProveedor: fallo de red, rate limit persistente o formato inesperado.
    """
    duracion_intervalo(intervalo)  # valida el intervalo antes de llamar a la red
    fabrica = fabrica_ticker or _fabrica_por_defecto
    sin_datos, transitorias, zona = _excepciones_yfinance()
    ultimo_motivo = "error desconocido"

    for intento in range(reintentos + 1):
        if limitador is not None:
            limitador.esperar()
        try:
            t = fabrica(ticker)
            crudo = t.history(period=periodo, interval=intervalo, auto_adjust=True,
                              actions=False, timeout=TIMEOUT_YAHOO_S, raise_errors=True)
            return history_a_dataframe(crudo, ticker, intervalo, _moneda_informada(t))
        except ErrorProveedor:
            raise
        except sin_datos:
            return pd.DataFrame(columns=COLUMNAS_NORMALIZADAS)
        except zona:
            raise ErrorProveedor(PROVEEDOR, "zona horaria no disponible "
                                            "(ticker inválido o falla de Yahoo)") from None
        except transitorias:
            ultimo_motivo = "rate limit"
        except Exception as e:  # noqa: BLE001 - yfinance lanza tipos muy variados
            # Solo el tipo: el texto puede incluir URLs o respuestas crudas.
            ultimo_motivo = f"error ({type(e).__name__})"
        if intento < reintentos:
            dormir(calcular_espera(intento))

    raise ErrorProveedor(PROVEEDOR, f"{ultimo_motivo} tras {reintentos + 1} intentos")

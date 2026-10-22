"""
Cliente de Binance API pública (sin API key necesaria para datos de mercado).
Endpoint: GET https://api.binance.com/api/v3/klines

Política de datos:
- Los pares cotizan contra USDT (stablecoin), no contra USD.
- Binance informa open_time/close_time en milisegundos UTC.
- La función NO filtra la vela abierta: eso lo hace el pipeline con la hora
  de captura (ver fuentes/normalizacion.filtrar_velas_cerradas).
- Un fallo de red/HTTP lanza ErrorProveedor; una respuesta vacía devuelve un
  DataFrame vacío ("sin datos"), que es un estado distinto.
"""

import pandas as pd

from fuentes.normalizacion import COLUMNAS_NORMALIZADAS
from fuentes.red import ErrorProveedor, LimitadorTasa, request_json

BINANCE_BASE_URL = "https://api.binance.com"
PROVEEDOR = "binance"
MAX_VELAS_POR_REQUEST = 1000

# Binance permite ~1200 de peso por minuto; 0.2 s entre requests es holgado.
LIMITADOR_BINANCE = LimitadorTasa(intervalo_min_s=0.2)

COLUMNAS_KLINES = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades",
    "taker_buy_base", "taker_buy_quote", "ignore",
]


def moneda_cotizacion(symbol: str) -> str | None:
    """Moneda en la que cotiza el par (ej. BTCUSDT -> USDT)."""
    for quote in ("USDT", "USDC", "FDUSD", "BTC", "ETH"):
        if symbol.endswith(quote) and len(symbol) > len(quote):
            return quote
    return None


def klines_a_dataframe(data: list, symbol: str) -> pd.DataFrame:
    """Convierte la respuesta cruda de /klines al esquema normalizado."""
    if not data:
        return pd.DataFrame(columns=COLUMNAS_NORMALIZADAS)
    if not isinstance(data, list) or not all(isinstance(f, list) and len(f) >= 7 for f in data):
        raise ErrorProveedor(PROVEEDOR, "formato de klines inesperado")

    df = pd.DataFrame([f[:7] for f in data], columns=COLUMNAS_KLINES[:7])
    try:
        apertura = pd.to_datetime(df["open_time"].astype("int64"), unit="ms", utc=True)
        # close_time es el último milisegundo de la vela: el cierre real es +1 ms.
        cierre = pd.to_datetime(df["close_time"].astype("int64") + 1, unit="ms", utc=True)
        valores = df[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
    except (ValueError, TypeError):
        raise ErrorProveedor(PROVEEDOR, "valores de klines no numéricos") from None

    salida = pd.DataFrame({
        "timestamp": apertura.dt.tz_localize(None),
        "timestamp_utc": apertura,
        "cierre_utc": cierre,
        "tz_original": "UTC",
    })
    salida = pd.concat([salida, valores], axis=1)
    salida["ticker"] = symbol
    salida["fuente"] = PROVEEDOR
    salida["moneda"] = moneda_cotizacion(symbol)
    salida["ajuste"] = "ninguno"
    return salida[COLUMNAS_NORMALIZADAS]


def obtener_velas_binance(symbol: str, interval: str = "1h", limit: int = 200,
                          *, sesion=None, limitador: LimitadorTasa | None = LIMITADOR_BINANCE,
                          end_time_ms: int | None = None) -> pd.DataFrame:
    """
    Trae velas (klines) de Binance en el esquema normalizado.

    Args:
        symbol: par de trading, ej "BTCUSDT"
        interval: timeframe (1m, 5m, 15m, 1h, 4h, 1d, etc)
        limit: cantidad de velas (máx 1000)
        end_time_ms: opcional, última apertura a incluir (para paginar hacia atrás)

    Raises:
        ErrorProveedor: fallo de red, HTTP o formato.
    """
    params = {"symbol": symbol, "interval": interval,
              "limit": min(int(limit), MAX_VELAS_POR_REQUEST)}
    if end_time_ms is not None:
        params["endTime"] = int(end_time_ms)

    data = request_json(PROVEEDOR, "GET", f"{BINANCE_BASE_URL}/api/v3/klines",
                        params=params, limitador=limitador, sesion=sesion)
    return klines_a_dataframe(data, symbol)

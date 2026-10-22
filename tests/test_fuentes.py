import pandas as pd
import pytest
import requests

from fuentes import binance_api, yahoo_api
from fuentes.normalizacion import filtrar_velas_cerradas, validar_ohlcv
from fuentes.red import ErrorProveedor, LimitadorTasa, request_json

TOKEN_FALSO = "123456:TOKEN-DE-PRUEBA-NO-REAL"


class RespuestaFalsa:
    def __init__(self, status=200, payload=None, headers=None, json_invalido=False):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}
        self._json_invalido = json_invalido

    def json(self):
        if self._json_invalido:
            raise ValueError("no json")
        return self._payload


class SesionFalsa:
    """Devuelve (o lanza) los elementos de la lista en orden."""

    def __init__(self, secuencia):
        self.secuencia = list(secuencia)
        self.llamadas = 0

    def request(self, *args, **kwargs):
        self.llamadas += 1
        item = self.secuencia.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _sin_espera(_):
    return None


# ---------------- red.py ----------------

def test_reintenta_errores_transitorios_y_luego_tiene_exito():
    sesion = SesionFalsa([RespuestaFalsa(503), requests.exceptions.ConnectionError("x"),
                          RespuestaFalsa(200, {"ok": True})])
    assert request_json("demo", "GET", "https://ejemplo", sesion=sesion, dormir=_sin_espera) == {"ok": True}
    assert sesion.llamadas == 3


def test_respeta_retry_after_acotado():
    esperas = []
    sesion = SesionFalsa([RespuestaFalsa(429, headers={"Retry-After": "3"}), RespuestaFalsa(200, [])])
    request_json("demo", "GET", "https://ejemplo", sesion=sesion, dormir=esperas.append)
    assert esperas == [3.0]


def test_error_4xx_no_se_reintenta():
    sesion = SesionFalsa([RespuestaFalsa(400, {"msg": "Invalid symbol"})])
    with pytest.raises(ErrorProveedor) as exc:
        request_json("binance", "GET", "https://ejemplo", sesion=sesion, dormir=_sin_espera)
    assert exc.value.status == 400 and sesion.llamadas == 1


def test_agotar_reintentos_lanza_error_sin_url_ni_token():
    url = f"https://api.telegram.org/bot{TOKEN_FALSO}/sendMessage"
    error = requests.exceptions.ConnectionError(f"Max retries exceeded with url: {url}")
    sesion = SesionFalsa([error] * 4)
    with pytest.raises(ErrorProveedor) as exc:
        request_json("telegram", "POST", url, sesion=sesion, reintentos=3, dormir=_sin_espera)
    assert sesion.llamadas == 4
    assert TOKEN_FALSO not in str(exc.value) and "api.telegram.org" not in str(exc.value)


def test_cuerpo_no_json_es_error_explicito():
    sesion = SesionFalsa([RespuestaFalsa(200, json_invalido=True)])
    with pytest.raises(ErrorProveedor, match="JSON"):
        request_json("demo", "GET", "https://ejemplo", sesion=sesion, dormir=_sin_espera)


def test_limitador_de_tasa_espera_el_intervalo_minimo():
    tiempos = iter([0.0, 0.05, 0.2])  # 1ª llamada; 2ª llamada (50 ms después); tras dormir
    esperas = []
    limitador = LimitadorTasa(0.2, reloj=lambda: next(tiempos), dormir=esperas.append)
    limitador.esperar()
    limitador.esperar()
    assert esperas == [pytest.approx(0.15)]


# ---------------- Binance ----------------

def _kline(open_ms, close="101.5"):
    return [open_ms, "100.0", "102.0", "99.0", close, "12.5", open_ms + 3_599_999,
            "0", 10, "0", "0", "0"]


def test_binance_normaliza_utc_y_cierre_de_vela():
    inicio = int(pd.Timestamp("2026-03-10 13:00", tz="UTC").timestamp() * 1000)
    sesion = SesionFalsa([RespuestaFalsa(200, [_kline(inicio), _kline(inicio + 3_600_000)])])
    df = binance_api.obtener_velas_binance("BTCUSDT", "1h", 2, sesion=sesion, limitador=None)
    assert list(df["timestamp_utc"]) == [pd.Timestamp("2026-03-10 13:00", tz="UTC"),
                                         pd.Timestamp("2026-03-10 14:00", tz="UTC")]
    assert df["cierre_utc"].iloc[0] == pd.Timestamp("2026-03-10 14:00", tz="UTC")
    assert (df["moneda"] == "USDT").all() and (df["tz_original"] == "UTC").all()
    assert df["close"].dtype.kind == "f"


def test_binance_respuesta_vacia_es_sin_datos_y_error_http_lanza():
    vacio = binance_api.obtener_velas_binance(
        "BTCUSDT", sesion=SesionFalsa([RespuestaFalsa(200, [])]), limitador=None)
    assert vacio.empty
    with pytest.raises(ErrorProveedor):
        binance_api.obtener_velas_binance(
            "BTCUSDT", sesion=SesionFalsa([RespuestaFalsa(500)] * 4), limitador=None)


def test_binance_formato_inesperado_lanza():
    with pytest.raises(ErrorProveedor):
        binance_api.klines_a_dataframe([{"no": "es lista"}], "BTCUSDT")


# ---------------- Yahoo ----------------

class TickerFalso:
    def __init__(self, df=None, error=None, moneda="USD"):
        self._df, self._error = df, error
        self._history_metadata = {"currency": moneda}
        self.kwargs = None

    def history(self, **kwargs):
        self.kwargs = kwargs
        if self._error:
            raise self._error
        return self._df


def _history_diario(tz="America/New_York"):
    idx = pd.DatetimeIndex(pd.to_datetime(["2026-03-05", "2026-03-06", "2026-03-09"]), name="Date")
    idx = idx.tz_localize(tz)
    return pd.DataFrame({"Open": [10.0, 11.0, 12.0], "High": [11.0, 12.0, 13.0],
                         "Low": [9.0, 10.0, 11.0], "Close": [10.5, 11.5, 12.5],
                         "Volume": [100, 200, 300]}, index=idx)


def test_yahoo_conserva_hora_local_y_agrega_utc_con_precios_ajustados():
    ticker = TickerFalso(_history_diario())
    df = yahoo_api.obtener_velas_yahoo("AAPL", "1d", fabrica_ticker=lambda _: ticker,
                                       limitador=None, dormir=_sin_espera)
    assert ticker.kwargs["auto_adjust"] is True
    assert df["timestamp"].iloc[0] == pd.Timestamp("2026-03-05")
    assert df["timestamp_utc"].iloc[0] == pd.Timestamp("2026-03-05 05:00", tz="UTC")
    # Vela diaria: cierra a la medianoche local siguiente.
    assert df["cierre_utc"].iloc[0] == pd.Timestamp("2026-03-06 05:00", tz="UTC")
    assert (df["tz_original"] == "America/New_York").all()
    assert (df["moneda"] == "USD").all() and (df["ajuste"] == "split_dividendo").all()


def test_yahoo_lee_la_moneda_de_la_metadata_interna_de_yfinance():
    ticker = TickerFalso(_history_diario(), moneda=None)
    ticker._history_metadata = None
    ticker._price_history = type("PH", (), {"_history_metadata": {"currency": "ars"}})()
    df = yahoo_api.obtener_velas_yahoo("GGAL.BA", fabrica_ticker=lambda _: ticker,
                                       limitador=None, dormir=_sin_espera)
    assert (df["moneda"] == "ARS").all()


def test_yahoo_sin_precios_devuelve_vacio():
    from yfinance.exceptions import YFPricesMissingError
    ticker = TickerFalso(error=YFPricesMissingError("XYZ", ""))
    df = yahoo_api.obtener_velas_yahoo("XYZ", fabrica_ticker=lambda _: ticker,
                                       limitador=None, dormir=_sin_espera)
    assert df.empty


def test_yahoo_error_generico_reintenta_y_lanza_error_explicito():
    intentos = []

    def fabrica(t):
        intentos.append(t)
        return TickerFalso(error=RuntimeError("https://query1.finance.yahoo.com/... detalle crudo"))

    with pytest.raises(ErrorProveedor) as exc:
        yahoo_api.obtener_velas_yahoo("AAPL", fabrica_ticker=fabrica, limitador=None,
                                      reintentos=2, dormir=_sin_espera)
    assert len(intentos) == 3
    assert "yahoo.com" not in str(exc.value)


def test_yahoo_intervalo_no_soportado_falla_antes_de_la_red():
    with pytest.raises(ValueError):
        yahoo_api.obtener_velas_yahoo("AAPL", "3mo", fabrica_ticker=lambda _: None)


# ---------------- Normalización ----------------

def _velas(precios_cierre, inicio="2026-03-10 00:00"):
    n = len(precios_cierre)
    ts = pd.date_range(inicio, periods=n, freq="h", tz="UTC")
    return pd.DataFrame({"timestamp_utc": ts, "cierre_utc": ts + pd.Timedelta(hours=1),
                         "open": precios_cierre, "high": [p * 1.01 if p == p and p else p for p in precios_cierre],
                         "low": [p * 0.99 if p == p and p else p for p in precios_cierre],
                         "close": precios_cierre, "volume": [1.0] * n})


def test_validar_ohlcv_descarta_nan_no_positivos_e_incoherentes():
    df = _velas([10.0, float("nan"), -1.0, 11.0, 12.0])
    df.loc[3, "high"] = 5.0  # high < close: incoherente
    limpio, descartadas = validar_ohlcv(df)
    assert descartadas == 3
    assert list(limpio["close"]) == [10.0, 12.0]


def test_validar_ohlcv_descarta_timestamps_duplicados():
    df = pd.concat([_velas([10.0, 11.0]), _velas([12.0])], ignore_index=True)
    limpio, descartadas = validar_ohlcv(df)
    assert descartadas == 1 and len(limpio) == 2


def test_filtrar_velas_cerradas_excluye_la_vela_en_curso():
    df = _velas([10.0, 11.0, 12.0])
    ahora = pd.Timestamp("2026-03-10 02:30", tz="UTC")  # la tercera vela (02:00-03:00) está abierta
    cerradas, abiertas = filtrar_velas_cerradas(df, ahora)
    assert abiertas == 1 and len(cerradas) == 2

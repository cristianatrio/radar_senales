import numpy as np
import pandas as pd

import config
from datos_sinteticos import SerieSintetica, generar_ohlcv
from indicadores import enriquecer_con_indicadores
from senales import SEÑALES_POSIBLES, generar_señal


def _serie(n=300, semilla=7):
    s = SerieSintetica("ALFAUSDT", "binance", "USDT", "1h", 100.0, 0.01, semilla)
    return generar_ohlcv(s, n, "2026-01-01")


def test_historial_insuficiente_devuelve_sin_datos():
    df = enriquecer_con_indicadores(_serie(40), config)
    resultado = generar_señal(df, config)
    assert resultado["señal"] == "SIN_DATOS"
    assert "Historial insuficiente" in resultado["motivos"]
    assert resultado["precio"] is None


def test_serie_plana_es_neutral():
    n = 80
    df = pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=n, freq="h"),
        "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1000.0,
    })
    resultado = generar_señal(enriquecer_con_indicadores(df, config), config)
    assert resultado["rsi"] == 50.0
    assert resultado["señal"] == "ESPERAR"
    assert resultado["fuerza"] == 0


def test_señales_siempre_dentro_del_conjunto_y_rango():
    df = enriquecer_con_indicadores(_serie(400, semilla=3), config)
    for t in range(60, len(df), 7):
        r = generar_señal(df.iloc[:t + 1], config)
        assert r["señal"] in SEÑALES_POSIBLES
        assert -9 <= r["fuerza"] <= 9


def test_sin_lookahead_la_señal_no_cambia_al_agregar_velas_futuras():
    completo = _serie(260, semilla=11)
    df_full = enriquecer_con_indicadores(completo, config)
    for t in (80, 120, 200, 250):
        truncado = enriquecer_con_indicadores(completo.iloc[:t + 1], config)
        a = generar_señal(truncado, config)
        b = generar_señal(df_full.iloc[:t + 1], config)
        assert a["señal"] == b["señal"] and a["fuerza"] == b["fuerza"]
        assert np.isclose(a["rsi"], b["rsi"])

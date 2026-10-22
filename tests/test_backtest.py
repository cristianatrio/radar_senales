import numpy as np
import pandas as pd
import pytest

import backtest as bt
import config
from datos_sinteticos import SerieSintetica, generar_ohlcv


def _serie(n=400, semilla=5):
    return generar_ohlcv(SerieSintetica("ALFAUSDT", "sintetico", "USDT", "1h", 100.0, 0.01, semilla),
                         n, "2026-01-01")


def test_sin_lookahead_cambiar_el_futuro_no_cambia_señales_pasadas():
    df = _serie()
    t = 250
    alterado = df.copy()
    alterado.loc[t + 1:, ["open", "high", "low", "close"]] *= 3.0  # futuro muy distinto
    a = bt.calcular_señales(df, config)
    b = bt.calcular_señales(alterado, config)
    pd.testing.assert_frame_equal(a.iloc[:t + 1], b.iloc[:t + 1])
    assert not a.iloc[t + 1:].equals(b.iloc[t + 1:])


def test_particion_cronologica_sin_solapamiento():
    seg = bt.particionar(1000, 50)
    assert seg == {"train": (50, 620), "validacion": (620, 810), "test": (810, 1000)}


def _señales(opens, closes, fuerzas, etiquetas=None):
    n = len(opens)
    return pd.DataFrame({"timestamp_utc": pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC"),
                         "open": opens, "close": closes, "fuerza": fuerzas,
                         "señal": etiquetas or ["ESPERAR"] * n})


def test_ejecuta_en_la_apertura_siguiente_con_costos():
    # Señal de compra al cierre de t=0 -> compra en open[1]=100; venta decidida en t=2 -> open[3]=120.
    s = _señales(opens=[90, 100, 110, 120, 130], closes=[95, 105, 115, 125, 135],
                 fuerzas=[3, 0, -3, 0, 0])
    costos = bt.Costos(comision_pct=0.5, slippage_pct=0.5)  # 1% por lado
    sim = bt.simular(s, 0, 5, bt.PARAMETROS_RADAR, costos)
    esperado = (1 / (100 * 1.01)) * 120 * 0.99
    assert sim["curva"][-1] == pytest.approx(esperado)
    assert sim["operaciones"] == [pytest.approx(esperado - 1)]
    assert sim["exposicion"] == pytest.approx(2 / 5)  # en posición durante las velas 1 y 2


def test_riesgo_alto_no_abre_posicion_y_cierre_forzado_al_final():
    s = _señales([10, 10, 10, 10], [10, 10, 10, 12], [3, 3, 0, 0],
                 ["RIESGO_ALTO", "COMPRA_PROBABLE", "ESPERAR", "ESPERAR"])
    sim = bt.simular(s, 0, 4, bt.PARAMETROS_RADAR, bt.Costos(0, 0))
    assert sim["operaciones"] == [pytest.approx(0.2)]  # entra en open[2], sale al último cierre


def test_salida_por_tiempo():
    s = _señales([10] * 6, [10] * 6, [3, 0, 0, 0, 0, 0])
    sim = bt.simular(s, 0, 6, bt.Parametros(2, -2, max_barras=2), bt.Costos(0, 0))
    assert len(sim["operaciones"]) == 1 and sim["exposicion"] == pytest.approx(2 / 6)


def test_drawdown_y_comprar_y_mantener():
    assert bt.max_drawdown(np.array([1.0, 1.2, 0.9, 1.3])) == pytest.approx(-0.25)
    s = _señales([100, 110], [105, 120], [0, 0])
    m = bt.comprar_y_mantener(s, 0, 2, bt.Costos(0, 0), "1h")
    assert m["retorno_total"] == pytest.approx(0.2)


def test_seleccion_de_parametros_solo_mira_train():
    df = _serie(700, semilla=9)
    señales = bt.calcular_señales(df, config)
    seg = bt.particionar(len(señales), 50)
    costos = bt.COSTOS_POR_TIPO["cripto"]
    elegido = bt.elegir_parametros(señales, seg["train"], costos, "1h")

    alterado = señales.copy()
    desde = seg["validacion"][0]
    alterado.loc[desde:, "fuerza"] = -alterado.loc[desde:, "fuerza"]
    alterado.loc[desde:, ["open", "close"]] *= np.linspace(1, 5, len(alterado) - desde)[:, None]
    assert bt.elegir_parametros(alterado, seg["train"], costos, "1h") == elegido


def test_reporte_incluye_aviso_y_segmentos(tmp_path):
    datos = {"ALFAUSDT": _serie(450)}
    res = {"cripto 1h": bt.evaluar_grupo(datos, {"ALFAUSDT": "cripto"}, "1h")}
    texto = bt.reporte_markdown(res, "sintético de prueba")
    assert "no una probabilidad" in texto and "Test (fuera de muestra)" in texto
    assert res["cripto 1h"]["activos"][0]["segmentos"]["test"]["regla_radar"]["operaciones"] >= 0


def test_historia_insuficiente_se_omite_explicitamente():
    res = bt.evaluar_grupo({"CORTO": _serie(120)}, {"CORTO": "cripto"}, "1h")
    assert res["activos"] == [] and "CORTO" in res["omitidos"][0]

import math

import numpy as np
import pandas as pd
import pytest

import config
from indicadores import (
    calcular_macd,
    calcular_rsi,
    calcular_volumen_relativo,
    detectar_ruptura,
    velas_minimas,
)

PRECIOS = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
           45.89, 46.03, 45.61, 46.28, 46.28, 46.00]


def test_rsi_inicializacion_sma_y_suavizado_de_wilder():
    # Primeros 14 cambios: ganancias suman 3.34 y pérdidas 1.40 (cálculo a mano).
    avg_g, avg_p = 3.34 / 14, 1.40 / 14
    primero = 100 - 100 / (1 + avg_g / avg_p)
    # Cambio siguiente: -0.28 -> suavizado de Wilder con alpha = 1/14.
    avg_g, avg_p = avg_g * 13 / 14, (avg_p * 13 + 0.28) / 14
    segundo = 100 - 100 / (1 + avg_g / avg_p)

    rsi = calcular_rsi(pd.Series(PRECIOS), periodo=14)
    assert rsi.iloc[:14].isna().all()
    np.testing.assert_allclose(rsi.iloc[14:].to_numpy(), [primero, segundo], atol=1e-9)


def test_rsi_serie_plana_es_neutral():
    rsi = calcular_rsi(pd.Series([100.0] * 40), periodo=14)
    assert rsi.iloc[:14].isna().all()
    assert (rsi.iloc[14:] == 50.0).all()


def test_rsi_extremos_solo_suba_y_solo_baja():
    assert calcular_rsi(pd.Series(np.arange(1.0, 41.0)), 14).iloc[-1] == 100.0
    assert calcular_rsi(pd.Series(np.arange(40.0, 0.0, -1.0)), 14).iloc[-1] == 0.0


def test_rsi_historial_insuficiente_devuelve_todo_nan():
    assert calcular_rsi(pd.Series([1.0, 2.0, 3.0]), 14).isna().all()


@pytest.mark.parametrize("invalido", [float("nan"), float("inf"), 0.0, -5.0])
def test_rsi_rechaza_precios_invalidos(invalido):
    precios = pd.Series([10.0] * 20)
    precios.iloc[7] = invalido
    with pytest.raises(ValueError):
        calcular_rsi(precios, 14)


def test_volumen_relativo_excluye_la_vela_actual_del_baseline():
    volumen = pd.Series([1.0] * 20 + [10.0])
    rel = calcular_volumen_relativo(volumen, periodo=20)
    assert rel.iloc[-1] == pytest.approx(10.0)
    assert rel.iloc[:20].isna().all()  # calentamiento: 20 velas previas necesarias


def test_volumen_relativo_baseline_cero_es_nan_no_infinito():
    rel = calcular_volumen_relativo(pd.Series([0.0] * 20 + [5.0]), periodo=20)
    assert math.isnan(rel.iloc[-1])


def test_macd_calentamiento_documentado():
    df = calcular_macd(pd.Series(np.linspace(10, 20, 60)), 12, 26, 9)
    assert df["macd"].iloc[:25].isna().all() and df["macd"].iloc[25:].notna().all()
    assert df["macd_hist"].iloc[:33].isna().all() and df["macd_hist"].iloc[33:].notna().all()


def test_ruptura_usa_solo_velas_previas():
    df = pd.DataFrame({"high": [10.0] * 20 + [12.0], "low": [9.0] * 21,
                       "close": [9.5] * 20 + [11.0]})
    assert detectar_ruptura(df, 20)["ruptura_max"] is True
    corto = df.iloc[:10]
    assert detectar_ruptura(corto, 20) == {"ruptura_max": False, "ruptura_min": False}


def test_velas_minimas_con_config_por_defecto():
    assert velas_minimas(config) == 50

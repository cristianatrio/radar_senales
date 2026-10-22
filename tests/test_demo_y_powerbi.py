"""La demo es sintética, reproducible y no exporta tablas privadas."""

import hashlib
import os
import sqlite3

import pandas as pd
import pytest

import exportar_powerbi
from demo import generar_demo

COLUMNAS_PRIVADAS = {"cantidad", "precio_compra", "amount", "locked_amount", "notas",
                     "saldo_anterior", "saldo_nuevo", "pnl_pct", "chat_id", "token"}


def _hashes(carpeta):
    return {f: hashlib.sha256(open(os.path.join(carpeta, f), "rb").read()).hexdigest()
            for f in sorted(os.listdir(carpeta)) if f.endswith(".csv")}


@pytest.fixture(scope="module")
def demo_generada(tmp_path_factory):
    base = tmp_path_factory.mktemp("demo")
    res = generar_demo.generar(dias=1, carpeta_salida=str(base / "db1"),
                               destino=str(base / "csv1"), valores_esperados=None)
    return base, res


def test_demo_reproducible(demo_generada):
    base, _ = demo_generada
    generar_demo.generar(dias=1, carpeta_salida=str(base / "db2"), destino=str(base / "csv2"),
                         valores_esperados=None)
    assert _hashes(base / "csv1") == _hashes(base / "csv2")


def test_demo_es_sintetica_y_sin_columnas_privadas(demo_generada):
    base, res = demo_generada
    assert res["tablas"]["dim_activo"]["es_sintetico"].all()
    for archivo in os.listdir(base / "csv1"):
        if archivo.endswith(".csv"):
            columnas = set(pd.read_csv(base / "csv1" / archivo, nrows=0).columns)
            assert not columnas & COLUMNAS_PRIVADAS, archivo
    texto = "".join(open(base / "csv1" / f, encoding="utf-8").read()
                    for f in os.listdir(base / "csv1"))
    assert "Users" not in texto and ":\\" not in texto  # sin rutas locales


def test_demo_incluye_estados_de_calidad_y_flags_de_ultima(demo_generada):
    _, res = demo_generada
    estados = set(res["tablas"]["fact_resultados_activo"]["estado"])
    assert {"valido", "error_proveedor"} <= estados
    senales = res["tablas"]["fact_senales"]
    assert senales.groupby("ticker")["es_ultima"].sum().eq(1).all()
    precios = res["tablas"]["fact_precios"]
    assert precios.groupby("ticker")["es_ultima_vela"].sum().eq(1).all()


def test_valores_esperados_cuentan_activos_no_filas(demo_generada):
    _, res = demo_generada
    valores = generar_demo.calcular_valores_esperados(res["tablas"])
    assert valores["Activos con señal actual"] == len(generar_demo.ACTIVOS)
    assert sum(valores["Distribución actual por señal"].values()) == len(generar_demo.ACTIVOS)
    assert valores["Activos (filas de precios, NO usar en tarjetas)"] > len(generar_demo.ACTIVOS)


def test_exportador_ignora_tablas_privadas(demo_generada, tmp_path):
    base, _ = demo_generada
    path = str(base / "db1" / "radar_demo.db")
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO posiciones (ticker, fuente_precio, fecha_compra, precio_compra, "
                 "cantidad, notas) VALUES ('ALFAUSDT', 'radar', '2026-01-01', 1, 1, 'NOTA_PRIVADA')")
    conn.commit()
    conn.close()
    exportar_powerbi.exportar(path, str(tmp_path / "pbi"))
    for archivo in os.listdir(tmp_path / "pbi"):
        assert "NOTA_PRIVADA" not in open(tmp_path / "pbi" / archivo, encoding="utf-8").read()
    assert not any(t in " ".join(os.listdir(tmp_path / "pbi")) for t in exportar_powerbi.TABLAS_PRIVADAS)

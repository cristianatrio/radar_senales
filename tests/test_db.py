import glob
import sqlite3
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

import db


def _crear_db_legacy(path):
    """DB con el esquema de la versión anterior (user_version 0) y datos FICTICIOS."""
    conn = sqlite3.connect(path)
    for sql in db.MIGRACION_1:
        conn.execute(sql)
    conn.execute("INSERT INTO posiciones (ticker, fuente_precio, fecha_compra, precio_compra, "
                 "cantidad, estado) VALUES ('ALFAUSDT', 'binance', '2026-01-02', 10.0, 1.0, 'abierta')")
    for _ in range(3):  # el bug viejo: el mismo gatillo registrado en cada corrida
        conn.execute("INSERT INTO eventos_posicion (posicion_id, timestamp, tipo, precio) "
                     "VALUES (1, '2026-01-05 10:00:00', 'stop_loss', 9.0)")
    conn.execute("INSERT INTO senales_historico (ticker, tipo, fuente, timestamp, señal) "
                 "VALUES ('ALFAUSDT', 'cripto', 'binance', '2026-01-05 10:00:00', 'ESPERAR')")
    conn.commit()
    conn.close()


def test_db_nueva_queda_en_la_ultima_version_con_foreign_keys(tmp_path):
    conn = db.conectar(str(tmp_path / "nueva.db"))
    assert db.version_esquema(conn) == db.SCHEMA_VERSION
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert db.aplicar_migraciones(conn) == []  # idempotente
    conn.close()
    assert glob.glob(str(tmp_path / "*.respaldo-*")) == []  # DB vacía: no hace falta respaldo


def test_migracion_desde_esquema_legacy_conserva_datos_y_crea_respaldo(tmp_path):
    path = str(tmp_path / "legacy.db")
    _crear_db_legacy(path)
    conn = db.conectar(path)
    assert db.version_esquema(conn) == 2
    assert conn.execute("SELECT COUNT(*) FROM senales_historico").fetchone()[0] == 1
    # Eventos previos: se asumen notificados (solo se guardaban tras enviar).
    assert conn.execute("SELECT COUNT(*) FROM eventos_posicion WHERE notificado = 1").fetchone()[0] == 3
    clave = conn.execute("SELECT clave_csv FROM posiciones").fetchone()[0]
    assert clave == "ALFAUSDT|2026-01-02|10"
    conn.close()
    respaldos = glob.glob(path + ".respaldo-v0-*")
    assert len(respaldos) == 1
    copia = sqlite3.connect(respaldos[0])
    assert copia.execute("PRAGMA user_version").fetchone()[0] == 0
    copia.close()


def test_db_con_esquema_mas_nuevo_no_se_toca(tmp_path):
    path = str(tmp_path / "futura.db")
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA user_version = 99")
    conn.close()
    with pytest.raises(RuntimeError, match="más nuevo"):
        db.conectar(path)


def test_migracion_fallida_hace_rollback(tmp_path, monkeypatch):
    path = str(tmp_path / "rota.db")
    _crear_db_legacy(path)

    def migracion_que_falla(conn):
        conn.execute("CREATE TABLE temporal (x INTEGER)")
        raise RuntimeError("falla simulada")

    monkeypatch.setitem(db.MIGRACIONES, 2, migracion_que_falla)
    with pytest.raises(RuntimeError):
        db.conectar(path)
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'temporal'").fetchone()[0] == 0
    conn.close()


def test_foreign_keys_impiden_resultados_huerfanos(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO resultados_activo (run_id, ticker, tipo, fuente, timeframe, "
                     "estado, capturado_utc) VALUES ('no-existe', 'X', 'cripto', 'binance', '1h', "
                     "'valido', '2026-01-01 00:00:00')")


def test_check_rechaza_estados_desconocidos(conn):
    db.iniciar_corrida(conn, "r1", datetime(2026, 1, 1, tzinfo=timezone.utc))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO resultados_activo (run_id, ticker, tipo, fuente, timeframe, "
                     "estado, capturado_utc) VALUES ('r1', 'X', 'cripto', 'binance', '1h', "
                     "'inventado', '2026-01-01 00:00:00')")


def test_transaccion_por_corrida_es_todo_o_nada(conn):
    db.iniciar_corrida(conn, "r1", datetime(2026, 1, 1, tzinfo=timezone.utc))
    fila = {"ticker": "ALFAUSDT", "tipo": "cripto", "fuente": "binance",
            "timestamp": "2026-01-01 00:00:00", "señal": "ESPERAR", "fuerza": 0, "run_id": "r1"}
    with pytest.raises(sqlite3.IntegrityError):
        with conn:
            db.insertar_señal_historico(conn, fila)
            db.insertar_señal_historico(conn, {**fila, "ticker": None})  # viola NOT NULL
    assert conn.execute("SELECT COUNT(*) FROM senales_historico").fetchone()[0] == 0


def test_corrida_en_curso_previa_queda_interrumpida(conn):
    t = datetime(2026, 1, 1, tzinfo=timezone.utc)
    db.iniciar_corrida(conn, "r1", t)
    db.iniciar_corrida(conn, "r2", t + timedelta(hours=1))
    estados = dict(conn.execute("SELECT run_id, estado FROM corridas"))
    assert estados == {"r1": "interrumpida", "r2": "en_curso"}


def test_retencion_por_tabla_y_cascada(conn):
    ahora = datetime(2026, 6, 1, tzinfo=timezone.utc)
    viejo = ahora - timedelta(days=400)
    db.iniciar_corrida(conn, "vieja", viejo)
    db.finalizar_corrida(conn, "vieja", viejo, "completa", {"total": 1, "valido": 1})
    db.iniciar_corrida(conn, "nueva", ahora)
    with conn:
        for run in ("vieja", "nueva"):
            conn.execute("INSERT INTO resultados_activo (run_id, ticker, tipo, fuente, timeframe, "
                         "estado, capturado_utc) VALUES (?, 'X', 'cripto', 'binance', '1h', "
                         "'valido', '2026-05-31 00:00:00')", (run,))
        conn.execute("INSERT INTO posiciones (ticker, fuente_precio, fecha_compra, precio_compra, "
                     "cantidad) VALUES ('X', 'radar', '2020-01-01', 1, 1)")
        borradas = db.aplicar_retencion(conn, {"corridas": 365, "posiciones": None}, ahora)
    assert borradas == {"corridas": 1}
    assert conn.execute("SELECT COUNT(*) FROM resultados_activo").fetchone()[0] == 1  # cascada
    assert conn.execute("SELECT COUNT(*) FROM posiciones").fetchone()[0] == 1  # sin retención
    assert conn.execute("SELECT estado FROM corridas WHERE run_id = 'nueva'").fetchone()[0] == "en_curso"


def test_bloqueo_impide_dos_corridas_simultaneas(tmp_path):
    path = str(tmp_path / "radar.db")
    with db.BloqueoCorrida(path):
        with pytest.raises(db.CorridaEnCurso):
            db.BloqueoCorrida(path).adquirir()
    with db.BloqueoCorrida(path):  # liberado: se puede volver a tomar
        pass


def test_upsert_precios_usa_formato_legacy_de_timestamp(conn):
    df = pd.DataFrame({
        "timestamp": pd.to_datetime(["2026-03-05", "2026-03-06"]),
        "timestamp_utc": pd.to_datetime(["2026-03-05 05:00", "2026-03-06 05:00"], utc=True),
        "open": [1.0, 2.0], "high": [1.0, 2.0], "low": [1.0, 2.0], "close": [1.0, 2.0],
        "volume": [1.0, 2.0], "ma_20": [None, 1.5], "ma_50": [None, None],
    })
    with conn:
        assert db.upsert_precios(conn, df, "AAPL", "yahoo", "1d", "r1") == 2
        db.upsert_precios(conn, df, "AAPL", "yahoo", "1d", "r2")  # upsert, no duplica
    filas = conn.execute("SELECT timestamp, timestamp_utc, ma_corta, run_id FROM precios_ohlcv "
                         "ORDER BY timestamp").fetchall()
    assert filas == [("2026-03-05", "2026-03-05 05:00:00", None, "r2"),
                     ("2026-03-06", "2026-03-06 05:00:00", 1.5, "r2")]

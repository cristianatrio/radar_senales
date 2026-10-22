"""Tests de posiciones con datos 100% ficticios."""

from datetime import datetime, timezone

import pytest

import posiciones as pos

ENCABEZADO = "ticker,fecha_compra,precio_compra,cantidad,stop_loss_pct,take_profit_pct,trailing_pct,notas\n"
AHORA = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)


def _csv(tmp_path, filas, encabezado=ENCABEZADO):
    path = tmp_path / "posiciones.csv"
    path.write_text(encabezado + "".join(f + "\n" for f in filas), encoding="utf-8")
    return str(path)


def _importar(conn, path):
    return pos.importar_posiciones(conn, path, ahora=AHORA)


# ---------------- Importación CSV ----------------

def test_csv_valido_inserta_y_fila_de_ejemplo_se_ignora(conn, tmp_path):
    path = _csv(tmp_path, ["ALFAUSDT,2026-01-02,10.0,2,5,20,8,test",
                           "BETAUSDT,2026-01-03,5,1,,,,",
                           f"BTCUSDT,2026-01-01,1,1,,,,{pos.MARCADOR_EJEMPLO} - borrar"])
    r = _importar(conn, path)
    assert (r.nuevas, r.ejemplo_ignoradas, r.errores) == (2, 1, [])
    fila = conn.execute("SELECT stop_loss_pct, take_profit_pct, precio_max FROM posiciones "
                        "WHERE ticker = 'BETAUSDT'").fetchone()
    assert fila == (None, None, 5.0)


@pytest.mark.parametrize("fila, fragmento", [
    ("alfa usdt,2026-01-02,10,1,,,,", "ticker inválido"),
    ("ALFAUSDT,02/01/2026,10,1,,,,", "fecha_compra inválida"),
    ("ALFAUSDT,2027-01-01,10,1,,,,", "futuro"),
    ("ALFAUSDT,2026-01-02,-10,1,,,,", "precio_compra"),
    ("ALFAUSDT,2026-01-02,nan,1,,,,", "precio_compra"),
    ("ALFAUSDT,2026-01-02,inf,1,,,,", "precio_compra"),
    ("ALFAUSDT,2026-01-02,\"10,5\",1,,,,", "punto decimal"),
    ("ALFAUSDT,2026-01-02,10,0,,,,", "cantidad"),
    ("ALFAUSDT,2026-01-02,10,1,150,,,", "stop_loss_pct"),
    ("ALFAUSDT,2026-01-02,10,1,,0,,", "take_profit_pct"),
    ("ALFAUSDT,2026-01-02,10,1,,,abc,", "trailing_pct"),
])
def test_csv_invalido_se_informa_con_linea_y_no_se_importa(conn, tmp_path, fila, fragmento):
    r = _importar(conn, _csv(tmp_path, [fila]))
    assert r.nuevas == 0
    assert len(r.errores) >= 1 and all(e.startswith("línea 2") for e in r.errores)
    assert any(fragmento in e for e in r.errores)


def test_errores_no_incluyen_valores_del_usuario(conn, tmp_path):
    r = _importar(conn, _csv(tmp_path, ["ALFAUSDT,2026-01-02,-12345.678,1,,,,nota secreta"]))
    assert not any("12345" in e or "secreta" in e for e in r.errores)


def test_faltan_columnas_requeridas_es_error_explicito(conn, tmp_path):
    path = _csv(tmp_path, ["ALFAUSDT,10"], encabezado="ticker,precio_compra\n")
    with pytest.raises(pos.ErrorCSVPosiciones, match="fecha_compra"):
        _importar(conn, path)


def test_fila_duplicada_en_el_csv(conn, tmp_path):
    r = _importar(conn, _csv(tmp_path, ["ALFAUSDT,2026-01-02,10,1,,,,", "ALFAUSDT,2026-01-02,10.0,3,,,,"]))
    assert r.nuevas == 1 and any("duplicada" in e for e in r.errores)


def test_editar_campos_actualiza_la_posicion_abierta(conn, tmp_path):
    _importar(conn, _csv(tmp_path, ["ALFAUSDT,2026-01-02,10,1,5,,,"]))
    r = _importar(conn, _csv(tmp_path, ["ALFAUSDT,2026-01-02,10.00,2,7,30,,nueva nota"]))
    assert (r.nuevas, r.actualizadas) == (0, 1)
    assert conn.execute("SELECT cantidad, stop_loss_pct, take_profit_pct, notas FROM posiciones"
                        ).fetchone() == (2.0, 7.0, 30.0, "nueva nota")
    r = _importar(conn, _csv(tmp_path, ["ALFAUSDT,2026-01-02,10,2,7,30,,nueva nota"]))
    assert (r.actualizadas, r.sin_cambios) == (0, 1)


def test_cambiar_campo_clave_crea_otra_posicion_y_reporta_la_ausente(conn, tmp_path):
    _importar(conn, _csv(tmp_path, ["ALFAUSDT,2026-01-02,10,1,,,,"]))
    r = _importar(conn, _csv(tmp_path, ["ALFAUSDT,2026-01-02,11,1,,,,"]))
    assert r.nuevas == 1 and r.ausentes_en_csv == 1
    assert conn.execute("SELECT COUNT(*) FROM posiciones WHERE estado = 'abierta'").fetchone()[0] == 2


def test_posicion_cerrada_no_se_modifica_desde_el_csv(conn, tmp_path):
    _importar(conn, _csv(tmp_path, ["ALFAUSDT,2026-01-02,10,1,,,,"]))
    assert pos.cerrar_posicion(conn, 1, "manual", 12.0, ahora=AHORA)
    r = _importar(conn, _csv(tmp_path, ["ALFAUSDT,2026-01-02,10,5,,,,"]))
    assert r.cerradas_no_modificadas == 1
    assert conn.execute("SELECT cantidad, estado, pnl_pct FROM posiciones").fetchone() == (
        1.0, "cerrada_manual", pytest.approx(20.0))


# ---------------- Gatillos idempotentes ----------------

def _posicion(conn, tmp_path, fila="ALFAUSDT,2026-01-02,100,1,5,20,10,"):
    _importar(conn, _csv(tmp_path, [fila]))


def _eventos(conn):
    return conn.execute("SELECT id, tipo, notificado, rearmado_utc FROM eventos_posicion").fetchall()


def test_mismo_stop_loss_no_se_registra_en_cada_corrida(conn, tmp_path):
    _posicion(conn, tmp_path)
    for _ in range(3):
        with conn:
            pos.evaluar_posiciones(conn, {"ALFAUSDT": 94.0}, run_id="r", ahora=AHORA)
    assert _eventos(conn) == [(1, "stop_loss", 0, None)]


def test_notificacion_fallida_se_reintenta_hasta_exito(conn, tmp_path, notificador_factory):
    _posicion(conn, tmp_path)
    notificador = notificador_factory([False, True])
    with conn:
        pos.evaluar_posiciones(conn, {"ALFAUSDT": 94.0}, ahora=AHORA)
    assert pos.notificar_eventos_pendientes(conn, notificador, ahora=AHORA) == (0, 1)
    assert _eventos(conn)[0][2] == 0
    with conn:
        pos.evaluar_posiciones(conn, {"ALFAUSDT": 93.0}, ahora=AHORA)  # no crea otro evento
    assert pos.notificar_eventos_pendientes(conn, notificador, ahora=AHORA) == (1, 0)
    assert pos.notificar_eventos_pendientes(conn, notificador, ahora=AHORA) == (0, 0)
    assert len(_eventos(conn)) == 1 and _eventos(conn)[0][2] == 1
    assert conn.execute("SELECT intentos_notificacion FROM eventos_posicion").fetchone()[0] == 2


def test_rearmar_permite_un_nuevo_evento_y_nunca_se_cierra_sola(conn, tmp_path):
    _posicion(conn, tmp_path)
    with conn:
        pos.evaluar_posiciones(conn, {"ALFAUSDT": 94.0}, ahora=AHORA)
    assert pos.rearmar_evento(conn, 1, ahora=AHORA)
    assert not pos.rearmar_evento(conn, 1, ahora=AHORA)  # ya rearmado
    with conn:
        nuevos = pos.evaluar_posiciones(conn, {"ALFAUSDT": 94.0}, ahora=AHORA)
    assert [e["tipo"] for e in nuevos] == ["stop_loss"] and len(_eventos(conn)) == 2
    assert conn.execute("SELECT estado FROM posiciones").fetchone()[0] == "abierta"


def test_confirmar_no_rearma(conn, tmp_path):
    _posicion(conn, tmp_path)
    with conn:
        pos.evaluar_posiciones(conn, {"ALFAUSDT": 94.0}, ahora=AHORA)
    assert pos.confirmar_evento(conn, 1, ahora=AHORA)
    with conn:
        assert pos.evaluar_posiciones(conn, {"ALFAUSDT": 94.0}, ahora=AHORA) == []


def test_trailing_y_take_profit_son_gatillos_distintos(conn, tmp_path):
    _posicion(conn, tmp_path)
    with conn:
        pos.evaluar_posiciones(conn, {"ALFAUSDT": 118.0}, ahora=AHORA)   # sube: nuevo máximo
        tr = pos.evaluar_posiciones(conn, {"ALFAUSDT": 106.0}, ahora=AHORA)  # cae >10% del máximo
        tp = pos.evaluar_posiciones(conn, {"ALFAUSDT": 125.0}, ahora=AHORA)
    assert [e["tipo"] for e in tr] == ["trailing"] and [e["tipo"] for e in tp] == ["take_profit"]


def test_precio_invalido_o_ausente_no_evalua(conn, tmp_path):
    _posicion(conn, tmp_path)
    with conn:
        assert pos.evaluar_posiciones(conn, {"ALFAUSDT": float("nan")}, ahora=AHORA) == []
        assert pos.evaluar_posiciones(conn, {}, ahora=AHORA) == []
    assert conn.execute("SELECT precio_max FROM posiciones").fetchone()[0] == 100.0


def test_mensaje_de_posicion_escapa_notas(conn, tmp_path):
    _posicion(conn, tmp_path, "ALFAUSDT,2026-01-02,100,1,5,,,<i>nota</i> & más")
    with conn:
        pos.evaluar_posiciones(conn, {"ALFAUSDT": 90.0}, ahora=AHORA)
    texto = pos.formatear_alerta_posicion(pos.eventos_pendientes_de_notificar(conn)[0])
    assert "&lt;i&gt;nota&lt;/i&gt; &amp; más" in texto
    assert "rearmar 1" in texto


def test_cerrar_posicion_valida_precio(conn, tmp_path):
    _posicion(conn, tmp_path)
    with pytest.raises(ValueError):
        pos.cerrar_posicion(conn, 1, "manual", float("nan"))
    assert not pos.cerrar_posicion(conn, 99, "manual", 10.0)

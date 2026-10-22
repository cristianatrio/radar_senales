import requests

import telegram_alertas as ta
from fuentes.red import ErrorProveedor


def _fila(ticker="ALFAUSDT", señal="COMPRA_PROBABLE", estado="valido", motivos="RSI sobrevendido (25)"):
    return {"ticker": ticker, "señal": señal, "fuerza": 2, "precio": 10.0, "rsi": 25.0,
            "vol_relativo": 1.2, "motivos": motivos, "moneda": "USDT", "timeframe": "1h",
            "estado_dato": estado}


def _entregadas(conn):
    return dict(conn.execute("SELECT ticker, señal FROM alertas_enviadas"))


def test_falla_reintenta_exito_y_no_duplica(conn, notificador_factory):
    notificador = notificador_factory([False, True])
    filas = [_fila()]

    # Corrida 1: el envío falla -> no queda registrado como entregado.
    assert ta.procesar_alertas(conn, filas, notificador=notificador) == 0
    assert _entregadas(conn) == {}

    # Corrida 2: misma señal -> se reintenta y esta vez se entrega.
    assert ta.procesar_alertas(conn, filas, notificador=notificador) == 1
    assert _entregadas(conn) == {"ALFAUSDT": "COMPRA_PROBABLE"}

    # Corrida 3: misma señal ya entregada -> no se vuelve a enviar.
    assert ta.procesar_alertas(conn, filas, notificador=notificador) == 0
    assert len(notificador.mensajes) == 2

    log = [r[0] for r in conn.execute("SELECT resultado FROM alertas_log ORDER BY id")]
    assert log == ["fallida", "enviada"]


def test_volver_a_esperar_rearma_y_permite_nueva_alerta(conn, notificador_factory):
    notificador = notificador_factory([True, True])
    ta.procesar_alertas(conn, [_fila()], notificador=notificador)
    ta.procesar_alertas(conn, [_fila(señal="ESPERAR")], notificador=notificador)
    assert _entregadas(conn) == {}
    assert ta.procesar_alertas(conn, [_fila()], notificador=notificador) == 1


def test_cambio_de_señal_reemplaza_el_estado_entregado(conn, notificador_factory):
    notificador = notificador_factory([True, True])
    ta.procesar_alertas(conn, [_fila()], notificador=notificador)
    ta.procesar_alertas(conn, [_fila(señal="VENTA_FUERTE")], notificador=notificador)
    assert _entregadas(conn) == {"ALFAUSDT": "VENTA_FUERTE"}


def test_datos_obsoletos_no_alertan_ni_tocan_el_estado(conn, notificador_factory):
    notificador = notificador_factory([True])
    ta.procesar_alertas(conn, [_fila()], notificador=notificador)
    assert ta.procesar_alertas(conn, [_fila(señal="VENTA_FUERTE", estado="obsoleto")],
                               notificador=notificador) == 0
    assert _entregadas(conn) == {"ALFAUSDT": "COMPRA_PROBABLE"}


def test_modo_individual_registra_solo_los_envios_exitosos(conn, notificador_factory):
    notificador = notificador_factory([True, False])
    entregadas, fallidas = ta.enviar_alertas_señales(
        conn, [_fila("ALFAUSDT"), _fila("BETAUSDT")], modo_resumen=False, notificador=notificador)
    assert (entregadas, fallidas) == (1, 1)
    assert _entregadas(conn) == {"ALFAUSDT": "COMPRA_PROBABLE"}


def test_mensajes_escapan_contenido_no_confiable():
    fila = _fila(ticker="<b>X</b>", motivos="<script>alert(1)</script> & co")
    individual = ta.formatear_alerta_individual(fila)
    assert "<script>" not in individual and "&lt;script&gt;" in individual
    assert "&amp; co" in individual
    for texto in (individual, ta.formatear_resumen([fila])):
        assert "&lt;b&gt;X&lt;/b&gt;" in texto
        assert "no es recomendación" in texto


def test_enviar_mensaje_sin_credenciales_no_hace_requests(capsys):
    assert ta.enviar_mensaje("hola") is False
    assert "no configurado" in capsys.readouterr().out


class _SesionQueFalla:
    def __init__(self, error):
        self.error = error

    def request(self, *a, **k):
        raise self.error


def test_error_de_envio_no_expone_el_token(monkeypatch, capsys):
    token = "999999:TOKEN-FICTICIO-SOLO-PARA-TEST"
    monkeypatch.setattr(ta, "_cargar_credenciales", lambda: (token, "42"))
    monkeypatch.setattr("fuentes.red.time.sleep", lambda _: None)
    error = requests.exceptions.ConnectionError(f"https://api.telegram.org/bot{token}/sendMessage")
    monkeypatch.setattr(ta, "request_json", _envoltorio_sin_espera())
    assert ta.enviar_mensaje("hola", sesion=_SesionQueFalla(error)) is False
    salida = capsys.readouterr().out
    assert token not in salida and "telegram" in salida


def _envoltorio_sin_espera():
    from fuentes import red

    def llamar(*args, **kwargs):
        return red.request_json(*args, dormir=lambda _: None, **kwargs)
    return llamar


def test_respuesta_sin_ok_true_no_cuenta_como_entregada(monkeypatch):
    monkeypatch.setattr(ta, "_cargar_credenciales", lambda: ("t", "c"))
    monkeypatch.setattr(ta, "request_json", lambda *a, **k: {"ok": False})
    assert ta.enviar_mensaje("hola") is False

    def falla(*a, **k):
        raise ErrorProveedor("telegram", "respuesta de error", 401)

    monkeypatch.setattr(ta, "request_json", falla)
    assert ta.enviar_mensaje("hola") is False

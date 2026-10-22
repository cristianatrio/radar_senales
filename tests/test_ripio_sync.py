"""Sincronización Ripio con respuestas SINTÉTICAS (no se usa la API real)."""

from datetime import datetime, timezone

import ripio_sync as rs
from fuentes.red import ErrorProveedor

AHORA = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)


class ClienteFalso:
    def __init__(self, respuesta=None, error=None, configurado=True):
        self.respuesta, self.error, self.configurado = respuesta, error, configurado

    def credenciales_configuradas(self):
        return self.configurado

    def obtener_balance_wallet(self):
        if self.error:
            raise self.error
        return self.respuesta


def _wallet(*items):
    return {"wallet": [dict(zip(("currency", "amount", "locked_amount"), i)) for i in items]}


def _abrir_posicion(conn, ticker="BTCUSDT", cantidad=0.5):
    with conn:
        conn.execute("INSERT INTO posiciones (ticker, fuente_precio, fecha_compra, precio_compra, "
                     "cantidad) VALUES (?, 'radar', '2026-01-01', 100, ?)", (ticker, cantidad))


def _sync(conn, cliente):
    return rs.sincronizar(conn, run_id="r1", ahora=AHORA, cliente=cliente)


def _tipos(res):
    return [c["tipo"] for c in res["cambios"]]


def test_saldo_bajo_umbral_no_es_venta_total(conn):
    _abrir_posicion(conn)
    res = _sync(conn, ClienteFalso(_wallet(("BTC", "0.000001", "0"))))
    assert _tipos(res) == ["saldo_bajo_umbral"]


def test_saldo_bloqueado_cuenta_como_tenencia(conn):
    _abrir_posicion(conn, cantidad=0.5)
    res = _sync(conn, ClienteFalso(_wallet(("BTC", "0.1", "0.4"))))
    assert _tipos(res) == []  # 0.1 disponible + 0.4 bloqueado = 0.5


def test_moneda_ausente_es_advertencia_no_venta(conn):
    _abrir_posicion(conn)
    res = _sync(conn, ClienteFalso(_wallet(("ETH", "1", "0"))))
    assert res["estado"] == "ok" and "posible_venta_total" not in _tipos(res)
    assert {"tipo": "dato_ausente", "ticker": "BTCUSDT"} in res["advertencias"]


def test_monto_no_numerico_es_dato_invalido(conn):
    _abrir_posicion(conn)
    res = _sync(conn, ClienteFalso(_wallet(("BTC", "abc", "0"))))
    assert _tipos(res) == [] and res["advertencias"] == [{"tipo": "dato_invalido", "ticker": "BTCUSDT"}]


def test_cero_confirmado_es_posible_venta_total(conn):
    _abrir_posicion(conn)
    res = _sync(conn, ClienteFalso(_wallet(("BTC", "0", "0"))))
    assert _tipos(res) == ["posible_venta_total"]


def test_consulta_fallida_no_compara_ni_guarda_snapshot(conn):
    _abrir_posicion(conn)
    res = _sync(conn, ClienteFalso(error=ErrorProveedor("ripio", "timeout")))
    assert res["estado"] == "consulta_fallida" and res["cambios"] == []
    assert conn.execute("SELECT COUNT(*) FROM ripio_balance_snapshot").fetchone()[0] == 0


def test_respuesta_sin_wallet_es_invalida(conn):
    _abrir_posicion(conn)
    res = _sync(conn, ClienteFalso({"otra": []}))
    assert res["estado"] == "respuesta_invalida" and res["cambios"] == []


def test_no_configurado_no_llama_a_la_api(conn):
    cliente = ClienteFalso(error=AssertionError("no debería llamarse"), configurado=False)
    assert _sync(conn, cliente)["estado"] == "no_configurado"


def test_nueva_aumento_y_reduccion(conn):
    _abrir_posicion(conn, "BTCUSDT", 0.5)
    _abrir_posicion(conn, "ETHUSDT", 2.0)
    res = _sync(conn, ClienteFalso(_wallet(("BTC", "0.6", "0"), ("ETH", "1.0", "0"),
                                           ("SOL", "3", "0"), ("USDT", "50", "0"))))
    assert sorted(_tipos(res)) == ["aumento_saldo", "nueva_cripto", "reduccion_saldo"]


def test_cambio_repetido_se_registra_y_notifica_una_vez_con_reintento(conn, notificador_factory):
    _abrir_posicion(conn)
    cliente = ClienteFalso(_wallet(("BTC", "0", "0")))
    assert _sync(conn, cliente)["cambios_nuevos"] == 1
    assert _sync(conn, cliente)["cambios_nuevos"] == 0  # mismo cambio pendiente: no duplica

    notificador = notificador_factory([False, True])
    assert rs.notificar_cambios_pendientes(conn, notificador, ahora=AHORA) == (0, 1)
    assert rs.notificar_cambios_pendientes(conn, notificador, ahora=AHORA) == (1, 0)
    assert rs.notificar_cambios_pendientes(conn, notificador, ahora=AHORA) == (0, 0)


def test_alerta_de_cambio_escapa_y_muestra_bloqueado():
    texto = rs.formatear_alerta_cambio({"tipo": "reduccion_saldo", "currency": "<X>",
                                        "ticker": "XUSDT", "saldo_anterior": 1.0,
                                        "saldo_nuevo": 0.5, "bloqueado": 0.1})
    assert "&lt;X&gt;" in texto and "Bloqueado" in texto

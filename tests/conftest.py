"""
Fixtures comunes. Todos los tests son offline: cualquier intento de abrir
una conexión de red falla de inmediato (ver bloquear_red).
"""

import os
import socket
import sys
import types
from datetime import datetime, timezone

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

import config as config_real  # noqa: E402
import db  # noqa: E402


class RedBloqueada(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def bloquear_red(monkeypatch):
    """Garantiza que ningún test haga requests reales."""
    def prohibido(*args, **kwargs):
        raise RedBloqueada("Los tests no pueden usar la red")

    monkeypatch.setattr(socket.socket, "connect", prohibido)
    monkeypatch.setattr(socket.socket, "connect_ex", prohibido)
    monkeypatch.setattr(socket, "create_connection", prohibido)
    monkeypatch.setattr(socket, "getaddrinfo", prohibido)


@pytest.fixture(autouse=True)
def sin_credenciales(monkeypatch, tmp_path):
    """Ningún test lee credenciales reales (variables de entorno ni archivos)."""
    for var in ("TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID", "RIPIO_API_KEY", "RIPIO_SECRET_KEY"):
        monkeypatch.delenv(var, raising=False)
    import ripio_api
    import telegram_alertas
    monkeypatch.setattr(telegram_alertas, "_cargar_credenciales", lambda: ("", ""))
    monkeypatch.setattr(ripio_api, "_cargar_credenciales", lambda: ("", ""))


@pytest.fixture
def ahora():
    return datetime(2026, 3, 10, 15, 30, tzinfo=timezone.utc)


@pytest.fixture
def cfg(tmp_path):
    """Copia de config.py apuntando a una carpeta temporal y sin integraciones."""
    valores = {k: getattr(config_real, k) for k in dir(config_real) if k.isupper()}
    c = types.SimpleNamespace(**valores)
    c.CARPETA_SALIDA = str(tmp_path / "salida")
    c.CRIPTO, c.ACCIONES_ARG, c.CEDEARS, c.ACCIONES_US = [], [], [], []
    c.TELEGRAM_ACTIVO = False
    c.POSICIONES_ACTIVO = False
    c.RIPIO_ACTIVO = False
    c.EXPORTAR_CSVS = False
    return c


@pytest.fixture
def conn(tmp_path):
    conexion = db.conectar(str(tmp_path / "test.db"))
    yield conexion
    conexion.close()


class NotificadorFalso:
    """Notificador controlable: devuelve los resultados de la lista en orden."""

    def __init__(self, resultados):
        self.resultados = list(resultados)
        self.mensajes = []

    def __call__(self, texto):
        self.mensajes.append(texto)
        return self.resultados.pop(0) if self.resultados else True


@pytest.fixture
def notificador_factory():
    return NotificadorFalso

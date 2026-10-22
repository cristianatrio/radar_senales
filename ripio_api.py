"""
Cliente de Ripio API (modo solo lectura). Uso local y privado.
Documentación oficial: https://apidocs.ripio.com/

La API requiere autenticación con HMAC-SHA256 sobre cada request.
Credenciales: variables de entorno RIPIO_API_KEY / RIPIO_SECRET_KEY
(preferido) o ripio_config.txt local, ignorado por git (ver
ripio_config.example.txt). Usá una API key con permisos de SOLO LECTURA.

Seguridad: este módulo nunca imprime credenciales, saldos ni respuestas
crudas. Los errores se informan con proveedor, motivo y código HTTP.
"""

import base64
import hashlib
import hmac
import json
import os
import time

from fuentes.red import ErrorProveedor, request_json

BASE_URL = "https://api.ripio.com"
PROVEEDOR = "ripio"


# ============================================================
# Carga de credenciales
# ============================================================

def _cargar_credenciales():
    """Carga API_KEY y SECRET_KEY de variables de entorno o ripio_config.txt."""
    api_key = os.environ.get("RIPIO_API_KEY", "")
    secret_key = os.environ.get("RIPIO_SECRET_KEY", "")

    if not api_key or not secret_key:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ripio_config.txt")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                for linea in f:
                    linea = linea.strip()
                    if linea.startswith("API_KEY=") and not api_key:
                        api_key = linea.split("=", 1)[1].strip()
                    elif linea.startswith("SECRET_KEY=") and not secret_key:
                        secret_key = linea.split("=", 1)[1].strip()

    return api_key, secret_key


def credenciales_configuradas() -> bool:
    api_key, secret_key = _cargar_credenciales()
    return bool(api_key and secret_key)


# ============================================================
# Firma HMAC-SHA256 (lo que requiere Ripio)
# ============================================================

def _generar_firma(secret_key: str, timestamp_ms: int, method: str,
                   path: str, body: str = "") -> str:
    """
    Firma según docs de Ripio:
        message = Timestamp + HTTP_Method + Path + JSON_Payload
        signature = base64(hmac_sha256(secret_key, message))
    """
    mensaje = f"{timestamp_ms}{method.upper()}{path}{body}"
    firma = hmac.new(
        secret_key.encode("utf-8"),
        mensaje.encode("utf-8"),
        hashlib.sha256
    ).digest()
    return base64.b64encode(firma).decode("utf-8")


def _request(method: str, path: str, params: dict = None, body: dict = None, *, sesion=None):
    """
    Hace un request firmado a Ripio y devuelve el campo `data` de la respuesta.
    Lanza ErrorProveedor ante credenciales faltantes, errores HTTP/red o
    respuestas con error_code (sin incluir el contenido de la respuesta).
    """
    api_key, secret_key = _cargar_credenciales()
    if not api_key or not secret_key:
        raise ErrorProveedor(PROVEEDOR, "credenciales no configuradas")

    timestamp_ms = int(time.time() * 1000)
    body_str = json.dumps(body) if body else ""

    # IMPORTANTE: la firma se hace sobre el path SIN query params
    firma = _generar_firma(secret_key, timestamp_ms, method, path, body_str)
    headers = {
        "Authorization": api_key,
        "Timestamp": str(timestamp_ms),
        "Timestamp-tolerance": "10000",
        "Signature": firma,
        "Content-Type": "application/json",
    }

    # Un solo reintento: la firma incluye el timestamp y tiene tolerancia de 10 s.
    data = request_json(PROVEEDOR, method.upper(), BASE_URL + path, params=params,
                        data=body_str if body else None, headers=headers,
                        reintentos=1, sesion=sesion)
    if not isinstance(data, dict):
        raise ErrorProveedor(PROVEEDOR, "respuesta con formato inesperado")
    if data.get("error_code"):
        raise ErrorProveedor(PROVEEDOR, "la API devolvió un código de error")
    return data.get("data")


# ============================================================
# Endpoints de lectura
# ============================================================

def obtener_balance_wallet(*, sesion=None):
    """
    Trae el balance de tu Ripio Wallet (cuenta normal).
    Endpoint: GET /wallet/balance/
    Devuelve dict con keys 'wallet' (lista de balances) y 'virals'.
    """
    return _request("GET", "/wallet/balance/", sesion=sesion)


def obtener_balance_trade(*, sesion=None):
    """
    Trae el balance de tu Ripio Trade (plataforma de trading).
    Endpoint: GET /trade/user/balances
    """
    return _request("GET", "/trade/user/balances", sesion=sesion)


def health_check_wallet(*, sesion=None):
    """
    Test simple de autenticación - no requiere permisos especiales.
    Endpoint: GET /wallet/health-check
    """
    return _request("GET", "/wallet/health-check", sesion=sesion)

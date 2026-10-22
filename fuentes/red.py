"""
Utilidades HTTP compartidas por los proveedores de datos y las integraciones.

Política común:
- timeout explícito en cada request;
- reintentos limitados con backoff exponencial, solo ante errores transitorios
  (red, timeout, HTTP 429 y 5xx). Un 4xx distinto de 429 no se reintenta;
- rate limit mínimo entre requests del mismo proveedor (LimitadorTasa);
- errores explícitos (ErrorProveedor). Los mensajes NUNCA incluyen la URL,
  los parámetros ni el cuerpo de la respuesta: algunas APIs (Telegram) llevan
  el token en la URL y otras devuelven datos privados en el cuerpo.
"""

import time

import requests

ESTADOS_REINTENTABLES = {429, 500, 502, 503, 504}
TIMEOUT_DEFAULT_S = 15
REINTENTOS_DEFAULT = 3
BACKOFF_BASE_S = 0.5
BACKOFF_MAX_S = 8.0


class ErrorProveedor(Exception):
    """Fallo de un proveedor externo, con un mensaje seguro para mostrar/loguear."""

    def __init__(self, proveedor: str, motivo: str, status: int | None = None):
        self.proveedor = proveedor
        self.motivo = motivo
        self.status = status
        detalle = f"{proveedor}: {motivo}"
        if status is not None:
            detalle += f" (HTTP {status})"
        super().__init__(detalle)


class LimitadorTasa:
    """Garantiza un intervalo mínimo entre llamadas sucesivas."""

    def __init__(self, intervalo_min_s: float, reloj=time.monotonic, dormir=time.sleep):
        self.intervalo_min_s = intervalo_min_s
        self._reloj = reloj
        self._dormir = dormir
        self._ultima = None

    def esperar(self) -> None:
        if self._ultima is not None:
            restante = self.intervalo_min_s - (self._reloj() - self._ultima)
            if restante > 0:
                self._dormir(restante)
        self._ultima = self._reloj()


def calcular_espera(intento: int, base: float = BACKOFF_BASE_S,
                    maximo: float = BACKOFF_MAX_S, retry_after: str | None = None) -> float:
    """Backoff exponencial acotado. Respeta Retry-After (en segundos) sin superar el máximo."""
    if retry_after:
        try:
            return min(max(float(retry_after), 0.0), maximo)
        except ValueError:
            pass
    return min(base * (2 ** intento), maximo)


def request_json(proveedor: str, metodo: str, url: str, *, params=None, json=None,
                 data=None, headers=None, timeout: float = TIMEOUT_DEFAULT_S,
                 reintentos: int = REINTENTOS_DEFAULT, limitador: LimitadorTasa | None = None,
                 sesion=None, dormir=time.sleep):
    """
    Hace un request y devuelve el JSON decodificado.
    Lanza ErrorProveedor si se agotan los reintentos, si la respuesta es un
    error no reintentable o si el cuerpo no es JSON.
    """
    cliente = sesion or requests
    ultimo_error = None

    for intento in range(reintentos + 1):
        if limitador is not None:
            limitador.esperar()
        try:
            r = cliente.request(metodo, url, params=params, json=json, data=data,
                                headers=headers, timeout=timeout)
        except requests.exceptions.Timeout:
            ultimo_error = ErrorProveedor(proveedor, "timeout")
        except requests.exceptions.RequestException as e:
            # Solo el tipo de excepción: el texto puede contener la URL.
            ultimo_error = ErrorProveedor(proveedor, f"error de red ({type(e).__name__})")
        else:
            if r.status_code in ESTADOS_REINTENTABLES:
                ultimo_error = ErrorProveedor(proveedor, "respuesta transitoria", r.status_code)
                if intento < reintentos:
                    dormir(calcular_espera(intento, retry_after=r.headers.get("Retry-After")))
                    continue
                break
            if r.status_code >= 400:
                raise ErrorProveedor(proveedor, "respuesta de error", r.status_code)
            try:
                return r.json()
            except ValueError:
                raise ErrorProveedor(proveedor, "respuesta no es JSON válido",
                                     r.status_code) from None

        if intento < reintentos:
            dormir(calcular_espera(intento))

    raise ErrorProveedor(proveedor, f"{ultimo_error.motivo} tras {reintentos + 1} intentos",
                         ultimo_error.status)

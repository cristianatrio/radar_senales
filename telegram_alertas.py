"""
Módulo de alertas por Telegram.

Sólo manda mensaje cuando hay señales accionables (compra/venta/riesgo) con
datos VÁLIDOS (no obsoletos). Lleva control de qué señal se ENTREGÓ por
ticker para no repetir la misma alerta cada hora.

Ciclo de una alerta (alertar_solo_cambios=True):
  1. La señal accionable se compara con la última señal ENTREGADA del ticker.
  2. Si es nueva, se intenta enviar.
  3. Solo si Telegram confirma el envío se registra como entregada. Si el
     envío falla, no se registra nada: la próxima corrida la reintenta.
  4. Cuando el ticker vuelve a ESPERAR/SIN_DATOS se borra el registro, así
     una nueva entrada a un estado accionable vuelve a alertar.

Seguridad:
- Credenciales: variables de entorno TELEGRAM_TOKEN / TELEGRAM_CHAT_ID o
  telegram_config.txt local (ignorado por git). Nunca se imprimen.
- El token viaja en la URL de la API: los errores se informan solo con
  proveedor, motivo y código HTTP (ver fuentes/red.py).
- Todo texto dinámico se escapa antes de armar el HTML del mensaje.
"""

import html
import os
import sqlite3

from fuentes.red import ErrorProveedor, request_json
from tiempo import ahora_utc, local_str, utc_str

PROVEEDOR = "telegram"
TELEGRAM_API = "https://api.telegram.org"
MAX_FILAS_POR_RESUMEN = 25  # mantiene cada mensaje bien debajo de 4096 caracteres


def escapar(valor) -> str:
    """Escapa texto no confiable para parse_mode=HTML de Telegram."""
    return html.escape("" if valor is None else str(valor), quote=False)


def _cargar_credenciales():
    """
    Intenta cargar credenciales de:
    1. Variables de entorno TELEGRAM_TOKEN y TELEGRAM_CHAT_ID (preferido)
    2. Archivo telegram_config.txt en la carpeta del proyecto (local, ignorado por git)
    """
    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "telegram_config.txt")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                for linea in f:
                    linea = linea.strip()
                    if linea.startswith("TOKEN=") and not token:
                        token = linea.split("=", 1)[1].strip()
                    elif linea.startswith("CHAT_ID=") and not chat_id:
                        chat_id = linea.split("=", 1)[1].strip()

    return token, chat_id


def telegram_configurado() -> bool:
    token, chat_id = _cargar_credenciales()
    return bool(token and chat_id)


def enviar_mensaje(texto: str, *, sesion=None) -> bool:
    """
    Manda un mensaje a Telegram. Devuelve True solo si Telegram confirma
    el envío (`ok: true`). Si no hay credenciales, no hace nada y devuelve False.
    """
    token, chat_id = _cargar_credenciales()

    if not token or not chat_id:
        print("  [!] Telegram no configurado. Definí TELEGRAM_TOKEN y TELEGRAM_CHAT_ID "
              "(ver telegram_config.example.txt).")
        return False

    payload = {
        "chat_id": chat_id,
        "text": texto,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        respuesta = request_json(PROVEEDOR, "POST", f"{TELEGRAM_API}/bot{token}/sendMessage",
                                 json=payload, reintentos=2, sesion=sesion)
    except ErrorProveedor as e:
        print(f"  [!] Envío fallido: {e}")
        return False

    if not isinstance(respuesta, dict) or respuesta.get("ok") is not True:
        print("  [!] Envío fallido: telegram: respuesta sin confirmación")
        return False
    return True


# ============================================================
# Estado de alertas entregadas (tabla alertas_enviadas) y log
# ============================================================

def _obtener_ultima_alerta(conn: sqlite3.Connection, ticker: str) -> str | None:
    """Devuelve la última señal ENTREGADA para un ticker, o None."""
    cur = conn.execute(
        "SELECT señal FROM alertas_enviadas WHERE ticker = ? ORDER BY timestamp DESC LIMIT 1",
        (ticker,))
    row = cur.fetchone()
    return row[0] if row else None


def _registrar_entrega(conn: sqlite3.Connection, ticker: str, señal: str,
                       run_id: str | None, ahora) -> None:
    """Guarda que esta señal fue entregada (deja una sola fila por ticker)."""
    conn.execute("DELETE FROM alertas_enviadas WHERE ticker = ? AND señal != ?", (ticker, señal))
    conn.execute("""
        INSERT INTO alertas_enviadas (ticker, señal, timestamp, timestamp_utc, run_id)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(ticker, señal) DO UPDATE SET
            timestamp = excluded.timestamp,
            timestamp_utc = excluded.timestamp_utc,
            run_id = excluded.run_id
    """, (ticker, señal, local_str(ahora), utc_str(ahora), run_id))


def _rearmar_ticker(conn: sqlite3.Connection, ticker: str) -> None:
    """El ticker volvió a un estado no accionable: la próxima entrada vuelve a alertar."""
    conn.execute("DELETE FROM alertas_enviadas WHERE ticker = ?", (ticker,))


def registrar_log(conn: sqlite3.Connection, categoria: str, referencia: str, resultado: str,
                  run_id: str | None = None, ahora=None, detalle: str | None = None) -> None:
    """Registro de intentos de notificación (sin montos ni datos personales)."""
    conn.execute("""
        INSERT INTO alertas_log (run_id, timestamp_utc, canal, categoria, referencia, resultado, detalle)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (run_id, utc_str(ahora or ahora_utc()), PROVEEDOR, categoria, referencia, resultado, detalle))


# ============================================================
# Formateo
# ============================================================

# Señales sobre las que alertar
SEÑALES_ALERTABLES = {
    "COMPRA_FUERTE": "🟢🟢",
    "COMPRA_PROBABLE": "🟢",
    "VENTA_FUERTE": "🔴🔴",
    "VENTA_PROBABLE": "🔴",
    "RIESGO_ALTO": "⚠️",
}
ORDEN_SEÑALES = ["COMPRA_FUERTE", "COMPRA_PROBABLE", "VENTA_FUERTE", "VENTA_PROBABLE", "RIESGO_ALTO"]
AVISO_HEURISTICO = "<i>Señal heurística, no es recomendación de inversión.</i>"


def _fmt_num(valor, formato: str, defecto: str = "?") -> str:
    return format(valor, formato) if valor is not None else defecto


def formatear_alerta_individual(fila: dict) -> str:
    """Devuelve un texto HTML formateado para Telegram con una señal individual."""
    emoji = SEÑALES_ALERTABLES.get(fila["señal"], "📊")
    señal_legible = escapar(fila["señal"].replace("_", " ").title())
    moneda = escapar(fila.get("moneda") or "")

    return (
        f"{emoji} <b>{señal_legible}</b>\n"
        f"<b>{escapar(fila['ticker'])}</b> — {_fmt_num(fila.get('precio'), ',.4f')} {moneda} "
        f"({escapar(fila.get('timeframe') or '')})\n"
        f"Fuerza: {fila['fuerza']:+d} | RSI: {_fmt_num(fila.get('rsi'), '.0f')} | "
        f"Vol: {_fmt_num(fila.get('vol_relativo'), '.1f')}x\n"
        f"<i>{escapar(fila['motivos'])}</i>\n"
        f"{AVISO_HEURISTICO}"
    )


def formatear_resumen(filas_alerta: list, ahora=None) -> str:
    """Junta varias alertas de una corrida en un solo mensaje."""
    sello = utc_str(ahora or ahora_utc())[:16]
    lineas = [f"📡 <b>Radar — {sello} UTC</b>"]

    por_señal = {}
    for fila in filas_alerta:
        por_señal.setdefault(fila["señal"], []).append(fila)

    for señal in ORDEN_SEÑALES:
        if señal not in por_señal:
            continue
        nombre = señal.replace("_", " ").title()
        lineas.append(f"\n{SEÑALES_ALERTABLES[señal]} <b>{nombre}</b>")
        for fila in por_señal[señal]:
            rsi_str = f", RSI {fila['rsi']:.0f}" if fila.get("rsi") is not None else ""
            lineas.append(
                f"  • <b>{escapar(fila['ticker'])}</b> {_fmt_num(fila.get('precio'), ',.4f')} "
                f"{escapar(fila.get('moneda') or '')} (fuerza {fila['fuerza']:+d}{rsi_str})"
            )
    lineas.append(f"\n{AVISO_HEURISTICO}")
    return "\n".join(lineas)


# ============================================================
# Lógica principal de alertas
# ============================================================

def seleccionar_alertas(conn: sqlite3.Connection, filas_señales: list,
                        alertar_solo_cambios: bool = True) -> list:
    """
    Devuelve las filas a notificar en esta corrida y rearma los tickers que
    salieron de un estado accionable. No registra entregas (eso ocurre solo
    después de un envío exitoso). No hace commit.
    """
    filas_a_alertar = []
    for fila in filas_señales:
        if fila.get("estado_dato", "valido") != "valido":
            continue  # datos obsoletos o incompletos: no se alerta ni se toca el estado

        señal_actual = fila["señal"]
        if señal_actual not in SEÑALES_ALERTABLES:
            if alertar_solo_cambios:
                _rearmar_ticker(conn, fila["ticker"])
            continue

        if alertar_solo_cambios and _obtener_ultima_alerta(conn, fila["ticker"]) == señal_actual:
            continue  # ya se entregó esta misma señal
        filas_a_alertar.append(fila)
    return filas_a_alertar


def enviar_alertas_señales(conn: sqlite3.Connection, filas_señales: list,
                           modo_resumen: bool = True, alertar_solo_cambios: bool = True,
                           *, notificador=None, run_id: str | None = None, ahora=None) -> tuple:
    """
    Selecciona, envía y registra alertas de señales.
    Devuelve (entregadas, fallidas). Las fallidas no se marcan como entregadas,
    así que la próxima corrida las vuelve a intentar.
    """
    notificador = notificador or enviar_mensaje
    ahora = ahora or ahora_utc()

    with conn:
        filas_a_alertar = seleccionar_alertas(conn, filas_señales, alertar_solo_cambios)
    if not filas_a_alertar:
        return 0, 0

    if modo_resumen:
        lotes = [filas_a_alertar[i:i + MAX_FILAS_POR_RESUMEN]
                 for i in range(0, len(filas_a_alertar), MAX_FILAS_POR_RESUMEN)]
        envios = [(lote, formatear_resumen(lote, ahora)) for lote in lotes]
    else:
        envios = [([fila], formatear_alerta_individual(fila)) for fila in filas_a_alertar]

    entregadas = fallidas = 0
    for lote, texto in envios:
        ok = bool(notificador(texto))
        with conn:
            for fila in lote:
                referencia = f"{fila['ticker']}:{fila['señal']}"
                if ok and alertar_solo_cambios:
                    _registrar_entrega(conn, fila["ticker"], fila["señal"], run_id, ahora)
                registrar_log(conn, "senal", referencia, "enviada" if ok else "fallida",
                              run_id, ahora)
        if ok:
            entregadas += len(lote)
        else:
            fallidas += len(lote)
    return entregadas, fallidas


def procesar_alertas(conn: sqlite3.Connection, filas_señales: list,
                     modo_resumen: bool = True, alertar_solo_cambios: bool = True,
                     *, notificador=None, run_id: str | None = None, ahora=None) -> int:
    """
    Procesa las señales de la corrida actual y manda alertas por Telegram.

    Args:
        conn: conexión SQLite ya abierta (esquema migrado)
        filas_señales: lista de dicts con las señales generadas
        modo_resumen: True = un mensaje por lote de alertas; False = uno por señal
        alertar_solo_cambios: True = sólo alerta cuando cambia el estado entregado
        notificador: función texto -> bool (por defecto enviar_mensaje)

    Devuelve cantidad de alertas entregadas.
    """
    entregadas, _ = enviar_alertas_señales(
        conn, filas_señales, modo_resumen, alertar_solo_cambios,
        notificador=notificador, run_id=run_id, ahora=ahora)
    return entregadas

"""
Sincronización Ripio API ↔ tabla de posiciones (uso local y privado).

Cada corrida del radar:
  1. Trae el balance actual de Ripio (solo lectura).
  2. Clasifica cada moneda en un estado explícito.
  3. Compara contra las posiciones abiertas y registra cambios nuevos.
  4. Guarda un snapshot del balance (tabla privada, nunca en la demo pública).

Estados por moneda (no se confunden entre sí):
  con_saldo        disponible + bloqueado >= umbral mínimo
  bajo_umbral      0 < disponible + bloqueado < umbral ("polvo")
  cero_confirmado  la API informa la moneda con saldo 0
  dato_invalido    la API informa la moneda pero el monto no es numérico/finito
  (ausente)        la moneda no aparece en la respuesta: NO se asume saldo 0

Solo `cero_confirmado` puede producir "posible_venta_total". Una consulta
fallida o una respuesta sin la lista `wallet` no compara nada.
"""

import math
import sqlite3

import ripio_api
from fuentes.red import ErrorProveedor
from tiempo import ahora_utc, local_str, utc_str

# Mapeo de currency de Ripio → ticker del radar
MAPEO_TICKERS = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "SOL": "SOLUSDT",
    "BNB": "BNBUSDT",
    "XRP": "XRPUSDT",
    "ADA": "ADAUSDT",
    "DOGE": "DOGEUSDT",
    "AVAX": "AVAXUSDT",
    "DOT": "DOTUSDT",
    "LINK": "LINKUSDT",
    "MATIC": "MATICUSDT",
    "POL": "POLUSDT",
    "LTC": "LTCUSDT",
    "USDT": None,  # stablecoins no se trackean (no se mueve el precio)
    "USDC": None,
    "DAI": None,
    "ARS": None,
    "RPC": None,   # token de Ripio, no está en Binance
}

# Umbrales mínimos de saldo para considerar "posición real" (filtra polvos).
UMBRALES_MINIMOS = {
    "BTC": 0.00001,
    "ETH": 0.001,
    "SOL": 0.01,
    "BNB": 0.001,
    "XRP": 1.0,
    "ADA": 1.0,
    "DOGE": 10.0,
    "AVAX": 0.1,
    "DOT": 1.0,
    "LINK": 0.1,
    "MATIC": 1.0,
    "POL": 1.0,
    "LTC": 0.01,
    "_default": 0.001,
}

# Diferencia relativa mínima para considerar que el saldo cambió.
TOLERANCIA_RELATIVA = 0.01

TIPOS_CAMBIO = ("nueva_cripto", "aumento_saldo", "reduccion_saldo",
                "saldo_bajo_umbral", "posible_venta_total")


def asegurar_schema_ripio(conn: sqlite3.Connection):
    """Compatibilidad: el esquema lo gestionan las migraciones versionadas (db.py)."""
    import db
    db.aplicar_migraciones(conn)


def es_polvo(currency: str, amount: float) -> bool:
    """Devuelve True si el saldo es tan chico que se considera polvo."""
    umbral = UMBRALES_MINIMOS.get(currency, UMBRALES_MINIMOS["_default"])
    return amount < umbral


def _a_float(valor) -> float | None:
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return numero if math.isfinite(numero) else None


def parsear_balance(balance_data) -> dict:
    """
    Convierte la respuesta de Ripio en estados por moneda.
    Devuelve {"valido": bool, "motivo": str | None, "monedas": {currency: info}}.
    """
    if not isinstance(balance_data, dict) or not isinstance(balance_data.get("wallet"), list):
        return {"valido": False, "motivo": "respuesta sin lista 'wallet'", "monedas": {}}

    monedas = {}
    for item in balance_data["wallet"]:
        if not isinstance(item, dict) or not item.get("currency"):
            continue
        currency = str(item["currency"]).strip().upper()
        amount = _a_float(item.get("amount"))
        locked = _a_float(item.get("locked_amount", 0))

        if amount is None or locked is None or amount < 0 or locked < 0:
            estado, total = "dato_invalido", None
        else:
            total = amount + locked
            if total == 0:
                estado = "cero_confirmado"
            elif es_polvo(currency, total):
                estado = "bajo_umbral"
            else:
                estado = "con_saldo"

        monedas[currency] = {
            "amount": amount,
            "locked": locked,
            "total": total,
            "estado": estado,
            "ticker_binance": MAPEO_TICKERS.get(currency),
        }
    return {"valido": True, "motivo": None, "monedas": monedas}


def guardar_snapshot(conn: sqlite3.Connection, balance_data: dict, ahora=None):
    """Guarda un snapshot histórico del balance (tabla privada). No hace commit."""
    timestamp = local_str(ahora or ahora_utc())
    for item in balance_data.get("wallet", []):
        if not isinstance(item, dict) or not item.get("currency"):
            continue
        amount = _a_float(item.get("amount"))
        locked = _a_float(item.get("locked_amount", 0))
        if amount is None or locked is None or (amount <= 0 and locked <= 0):
            continue
        conn.execute("""
            INSERT OR REPLACE INTO ripio_balance_snapshot
                (timestamp, currency, amount, locked_amount)
            VALUES (?, ?, ?, ?)
        """, (timestamp, str(item["currency"]).upper(), amount, locked))


def _ticker_a_currency() -> dict:
    return {t: c for c, t in MAPEO_TICKERS.items() if t}


def detectar_cambios(conn: sqlite3.Connection, monedas: dict) -> tuple:
    """
    Compara los estados por moneda contra las posiciones abiertas.
    Devuelve (cambios, advertencias). Las advertencias (moneda ausente o dato
    inválido) se informan pero NO se interpretan como venta.
    """
    posiciones_abiertas = dict(conn.execute("""
        SELECT ticker, SUM(cantidad) FROM posiciones WHERE estado = 'abierta' GROUP BY ticker
    """).fetchall())

    cambios, advertencias = [], []
    tickers = set(posiciones_abiertas) | {i["ticker_binance"] for i in monedas.values()
                                          if i["ticker_binance"] and i["estado"] == "con_saldo"}
    inverso = _ticker_a_currency()

    for ticker in sorted(tickers):
        currency = inverso.get(ticker)
        cantidad_db = posiciones_abiertas.get(ticker, 0) or 0
        info = monedas.get(currency) if currency else None

        if info is None:
            if cantidad_db > 0:
                advertencias.append({"tipo": "dato_ausente", "ticker": ticker})
            continue
        if info["estado"] == "dato_invalido":
            if cantidad_db > 0:
                advertencias.append({"tipo": "dato_invalido", "ticker": ticker})
            continue

        base = {"currency": currency, "ticker": ticker, "saldo_anterior": cantidad_db,
                "saldo_nuevo": info["total"], "diferencia": info["total"] - cantidad_db,
                "bloqueado": info["locked"], "estado_dato": info["estado"]}

        if info["estado"] == "cero_confirmado":
            if cantidad_db > 0:
                cambios.append({**base, "tipo": "posible_venta_total"})
        elif info["estado"] == "bajo_umbral":
            if cantidad_db > 0:
                cambios.append({**base, "tipo": "saldo_bajo_umbral"})
        elif cantidad_db == 0:
            cambios.append({**base, "tipo": "nueva_cripto"})
        elif info["total"] > cantidad_db * (1 + TOLERANCIA_RELATIVA):
            cambios.append({**base, "tipo": "aumento_saldo"})
        elif info["total"] < cantidad_db * (1 - TOLERANCIA_RELATIVA):
            cambios.append({**base, "tipo": "reduccion_saldo"})

    return cambios, advertencias


def _registrar_cambio_pendiente(conn, cambio: dict, run_id, ahora) -> bool:
    """Inserta el cambio si no hay uno idéntico pendiente. Devuelve True si es nuevo."""
    cur = conn.execute("""
        SELECT id FROM ripio_cambios_pendientes
        WHERE currency = ? AND tipo = ? AND procesado = 0
          AND ABS(saldo_nuevo - ?) < 0.0000001
    """, (cambio["currency"], cambio["tipo"], cambio["saldo_nuevo"]))
    if cur.fetchone():
        return False

    conn.execute("""
        INSERT INTO ripio_cambios_pendientes
            (timestamp, timestamp_utc, run_id, currency, tipo, saldo_anterior, saldo_nuevo,
             diferencia, estado_dato, notificado)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
    """, (local_str(ahora), utc_str(ahora), run_id, cambio["currency"], cambio["tipo"],
          cambio["saldo_anterior"], cambio["saldo_nuevo"], cambio["diferencia"],
          cambio["estado_dato"]))
    return True


def formatear_alerta_cambio(cambio: dict) -> str:
    """Formato HTML para Telegram (canal privado del usuario)."""
    from telegram_alertas import escapar

    titulos = {
        "nueva_cripto": ("🆕", "NUEVA TENENCIA DETECTADA EN RIPIO",
                         "Para trackearla con stop loss / take profit, agregá la compra "
                         "en output/posiciones.csv con el precio real."),
        "aumento_saldo": ("📈", "SALDO AUMENTADO EN RIPIO",
                          "Probable compra adicional. Actualizá posiciones.csv si corresponde."),
        "reduccion_saldo": ("📉", "SALDO REDUCIDO EN RIPIO", "Probable venta parcial."),
        "saldo_bajo_umbral": ("🔎", "SALDO POR DEBAJO DEL UMBRAL EN RIPIO",
                              "Queda un saldo mínimo ('polvo'). No se asume venta total: "
                              "revisalo y cerrá la posición manualmente si corresponde."),
        "posible_venta_total": ("💸", "SALDO EN CERO EN RIPIO",
                                "Ripio informa saldo 0. Si vendiste, cerrá la posición con "
                                "gestionar_posiciones.py; el radar no la cierra solo."),
    }
    emoji, titulo, nota = titulos.get(cambio["tipo"], ("📊", "CAMBIO DETECTADO EN RIPIO", ""))
    saldo_nuevo = cambio.get("saldo_nuevo")
    ahora_txt = f"{saldo_nuevo:.8f}" if saldo_nuevo is not None else "sin dato"
    texto = (
        f"{emoji} <b>{titulo}</b>\n\n"
        f"<b>{escapar(cambio['currency'])}</b> ({escapar(cambio['ticker'])})\n"
        f"Antes (posiciones): {cambio['saldo_anterior']:.8f}\n"
        f"Ahora (disponible + bloqueado): {ahora_txt}\n"
    )
    if cambio.get("bloqueado"):
        texto += f"Bloqueado: {cambio['bloqueado']:.8f}\n"
    return texto + f"\n<i>{escapar(nota)}</i>"


def sincronizar(conn: sqlite3.Connection, run_id: str | None = None, ahora=None,
                cliente=ripio_api) -> dict:
    """
    Trae balance, clasifica, compara y registra cambios nuevos.

    Returns dict con:
        - 'estado': ok | no_configurado | consulta_fallida | respuesta_invalida
        - 'error': mensaje seguro (sin datos privados) o None
        - 'monedas_con_saldo': cantidad de monedas con saldo significativo
        - 'cambios': cambios detectados en esta corrida
        - 'cambios_nuevos': cantidad registrada por primera vez
        - 'advertencias': monedas ausentes o con dato inválido
    """
    ahora = ahora or ahora_utc()
    resultado = {"estado": "ok", "error": None, "monedas_con_saldo": 0,
                 "cambios": [], "cambios_nuevos": 0, "advertencias": []}

    if not cliente.credenciales_configuradas():
        return {**resultado, "estado": "no_configurado",
                "error": "Credenciales de Ripio no configuradas"}

    try:
        balance_raw = cliente.obtener_balance_wallet()
    except ErrorProveedor as e:
        return {**resultado, "estado": "consulta_fallida", "error": str(e)}

    parseado = parsear_balance(balance_raw)
    if not parseado["valido"]:
        return {**resultado, "estado": "respuesta_invalida", "error": f"ripio: {parseado['motivo']}"}

    monedas = parseado["monedas"]
    with conn:
        guardar_snapshot(conn, balance_raw, ahora)
        cambios, advertencias = detectar_cambios(conn, monedas)
        nuevos = sum(_registrar_cambio_pendiente(conn, c, run_id, ahora) for c in cambios)

    return {**resultado,
            "monedas_con_saldo": sum(1 for i in monedas.values() if i["estado"] == "con_saldo"),
            "cambios": cambios, "cambios_nuevos": nuevos, "advertencias": advertencias}


def notificar_cambios_pendientes(conn: sqlite3.Connection, notificador, run_id=None,
                                 ahora=None) -> tuple:
    """Envía los cambios no notificados. Solo un envío confirmado los marca. Devuelve (ok, fallidos)."""
    from telegram_alertas import registrar_log

    ahora = ahora or ahora_utc()
    pendientes = conn.execute("""
        SELECT id, currency, tipo, saldo_anterior, saldo_nuevo
        FROM ripio_cambios_pendientes
        WHERE notificado = 0 AND procesado = 0
        ORDER BY id
    """).fetchall()

    enviados = fallidos = 0
    for cambio_id, currency, tipo, anterior, nuevo in pendientes:
        cambio = {"currency": currency, "ticker": MAPEO_TICKERS.get(currency) or "?",
                  "tipo": tipo, "saldo_anterior": anterior or 0, "saldo_nuevo": nuevo}
        ok = bool(notificador(formatear_alerta_cambio(cambio)))
        with conn:
            if ok:
                conn.execute("UPDATE ripio_cambios_pendientes SET notificado = 1, notificado_utc = ? "
                             "WHERE id = ?", (utc_str(ahora), cambio_id))
            registrar_log(conn, "ripio", f"cambio:{cambio_id}:{tipo}",
                          "enviada" if ok else "fallida", run_id, ahora)
        enviados += ok
        fallidos += not ok
    return enviados, fallidos

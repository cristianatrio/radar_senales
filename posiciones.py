"""
Módulo de seguimiento de posiciones personales (solo uso local/privado).

Dispara avisos cuando:
  - El precio baja del stop loss (cortar pérdida)
  - El precio sube al take profit (tomar ganancia)
  - El trailing stop se gatilla (proteger ganancia)

Reglas de idempotencia (ver docs/POSICIONES.md):
  - Un gatillo (posición + tipo) genera UN evento en eventos_posicion. Mientras
    ese evento no se rearme, las corridas siguientes no crean otro registro.
  - La notificación es independiente del registro: un evento con
    notificado = 0 se reintenta en cada corrida hasta que Telegram confirme.
  - Rearmar (volver a vigilar ese gatillo) y cerrar una posición son
    decisiones explícitas del usuario: `python gestionar_posiciones.py ...`.
    El sistema nunca cierra posiciones por su cuenta.

Las posiciones se cargan desde output/posiciones.csv (ver
posiciones.example.csv). Clave estable de cada fila: ticker + fecha_compra +
precio_compra. Si cambian cantidad, stop/take-profit/trailing o notas, la
posición abierta se actualiza; si cambia alguno de los campos clave, se trata
como una compra distinta (la anterior no se toca y se informa).
"""

import math
import os
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

import db
from tiempo import ahora_utc, local_str, utc_str

# ==========================================================
# Esquema (las tablas se crean con las migraciones de db.py)
# ==========================================================


def asegurar_schema_posiciones(conn: sqlite3.Connection):
    """Compatibilidad: el esquema lo gestionan las migraciones versionadas."""
    db.aplicar_migraciones(conn)


# ==========================================================
# Carga desde CSV (formato amigable para humanos)
# ==========================================================

CSV_COLUMNAS = [
    "ticker", "fecha_compra", "precio_compra", "cantidad",
    "stop_loss_pct", "take_profit_pct", "trailing_pct", "notas"
]
COLUMNAS_REQUERIDAS = ["ticker", "fecha_compra", "precio_compra", "cantidad"]
COLUMNAS_EDITABLES = ["cantidad", "stop_loss_pct", "take_profit_pct", "trailing_pct", "notas"]
MARCADOR_EJEMPLO = "Compra de ejemplo"
PATRON_TICKER = re.compile(r"^[A-Z0-9][A-Z0-9._-]{1,19}$")
# Límites de porcentajes: (mínimo exclusivo, máximo inclusivo)
LIMITES_PCT = {
    "stop_loss_pct": (0.0, 99.99),
    "take_profit_pct": (0.0, 1000.0),
    "trailing_pct": (0.0, 99.99),
}
FORMATOS_FECHA = ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S")


class ErrorCSVPosiciones(ValueError):
    """El archivo no se puede procesar (columnas faltantes, encoding, etc.)."""


@dataclass
class ResultadoImportacion:
    nuevas: int = 0
    actualizadas: int = 0
    sin_cambios: int = 0
    cerradas_no_modificadas: int = 0
    ejemplo_ignoradas: int = 0
    ausentes_en_csv: int = 0
    errores: list = field(default_factory=list)


def crear_csv_ejemplo(path: str):
    """Crea un CSV de ejemplo si no existe, para que el usuario lo edite."""
    if os.path.exists(path):
        return
    df = pd.DataFrame([
        {
            "ticker": "BTCUSDT",
            "fecha_compra": "2026-04-30",
            "precio_compra": 76000.0,
            "cantidad": 0.005,
            "stop_loss_pct": 5.0,
            "take_profit_pct": 15.0,
            "trailing_pct": 7.0,
            "notas": f"{MARCADOR_EJEMPLO} - editá o borrá esta fila",
        }
    ])
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"  ✔ Creado {path} con una fila de ejemplo (se ignora). Editalo con tus compras.")


def _normalizar_numero(valor: float) -> str:
    return format(float(valor), ".10g")


def clave_posicion(ticker: str, fecha: str, precio) -> str:
    """Clave estable de una compra: TICKER|fecha|precio normalizado."""
    return f"{str(ticker).strip().upper()}|{str(fecha).strip()}|{_normalizar_numero(precio)}"


def _parsear_numero(texto: str) -> float | None:
    texto = texto.strip()
    if not texto:
        return None
    return float(texto)  # ValueError si no es número (ej. "1,5")


def _validar_fila(fila: dict, linea: int, hoy) -> tuple:
    """Devuelve (registro_valido | None, [errores]). Los errores no incluyen valores."""
    errores = []
    ticker = fila.get("ticker", "").strip().upper()
    if not PATRON_TICKER.match(ticker):
        errores.append(f"línea {linea}: ticker inválido (usar el símbolo del radar, ej. BTCUSDT)")

    fecha = fila.get("fecha_compra", "").strip()
    fecha_dt = None
    for formato in FORMATOS_FECHA:
        try:
            fecha_dt = datetime.strptime(fecha, formato)
            break
        except ValueError:
            continue
    if fecha_dt is None:
        errores.append(f"línea {linea}: fecha_compra inválida (formato AAAA-MM-DD)")
    elif fecha_dt.date() > hoy:
        errores.append(f"línea {linea}: fecha_compra está en el futuro")

    registro = {"ticker": ticker, "fecha_compra": fecha, "notas": fila.get("notas", "").strip()}
    for campo in ("precio_compra", "cantidad"):
        try:
            valor = _parsear_numero(fila.get(campo, ""))
        except ValueError:
            valor = float("nan")
        if valor is None or not math.isfinite(valor) or valor <= 0:
            errores.append(f"línea {linea}: {campo} debe ser un número finito > 0 "
                           "(usar punto decimal)")
        registro[campo] = valor

    for campo, (minimo, maximo) in LIMITES_PCT.items():
        try:
            valor = _parsear_numero(fila.get(campo, ""))
        except ValueError:
            valor = float("nan")
        if valor is not None and (not math.isfinite(valor) or not minimo < valor <= maximo):
            errores.append(f"línea {linea}: {campo} debe estar entre {minimo:g} (excl.) "
                           f"y {maximo:g}, o quedar vacío")
        registro[campo] = valor

    return (None if errores else registro), errores


def leer_csv_posiciones(path_csv: str, hoy=None) -> tuple:
    """
    Lee y valida el CSV. Devuelve (registros_validos, errores, filas_ejemplo).
    Lanza ErrorCSVPosiciones si el archivo no tiene la estructura esperada.
    """
    hoy = hoy or datetime.now().date()
    try:
        df = pd.read_csv(path_csv, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    except (UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as e:
        raise ErrorCSVPosiciones(f"No se pudo leer el CSV de posiciones ({type(e).__name__})") from None

    df.columns = [str(c).strip() for c in df.columns]
    faltantes = [c for c in COLUMNAS_REQUERIDAS if c not in df.columns]
    if faltantes:
        raise ErrorCSVPosiciones(f"Faltan columnas requeridas: {', '.join(faltantes)}")
    desconocidas = [c for c in df.columns if c not in CSV_COLUMNAS]
    errores = [f"columna desconocida ignorada: {c}" for c in desconocidas]

    validos, claves, ejemplo = [], set(), 0
    for i, fila in enumerate(df.to_dict(orient="records")):
        linea = i + 2  # +1 por encabezado, +1 por base 1
        fila = {k: ("" if v is None else str(v)) for k, v in fila.items()}
        if not any(v.strip() for v in fila.values()):
            continue
        if fila.get("notas", "").strip().startswith(MARCADOR_EJEMPLO):
            ejemplo += 1
            continue
        registro, errores_fila = _validar_fila(fila, linea, hoy)
        if errores_fila:
            errores.extend(errores_fila)
            continue
        clave = clave_posicion(registro["ticker"], registro["fecha_compra"], registro["precio_compra"])
        if clave in claves:
            errores.append(f"línea {linea}: compra duplicada (mismo ticker, fecha y precio)")
            continue
        claves.add(clave)
        registro["clave_csv"] = clave
        validos.append(registro)
    return validos, errores, ejemplo


def importar_posiciones(conn: sqlite3.Connection, path_csv: str, ahora=None) -> ResultadoImportacion:
    """
    Sincroniza el CSV con la tabla posiciones en una sola transacción.
    - Clave nueva -> INSERT.
    - Clave existente y abierta -> UPDATE de los campos editables si cambiaron.
    - Clave existente pero cerrada -> no se modifica (se informa).
    - Posiciones abiertas cargadas desde CSV que ya no figuran -> no se tocan (se informa).
    Las filas inválidas se informan en `errores` y no se importan.
    """
    ahora = ahora or ahora_utc()
    resultado = ResultadoImportacion()
    if not os.path.exists(path_csv):
        return resultado

    registros, errores, ejemplo = leer_csv_posiciones(path_csv, hoy=ahora.astimezone().date())
    resultado.errores = errores
    resultado.ejemplo_ignoradas = ejemplo

    with conn:
        for reg in registros:
            existente = conn.execute(
                f"SELECT id, estado, {', '.join(COLUMNAS_EDITABLES)} FROM posiciones WHERE clave_csv = ?",
                (reg["clave_csv"],)).fetchone()
            if existente is None:
                conn.execute("""
                    INSERT INTO posiciones (
                        ticker, fuente_precio, fecha_compra, precio_compra, cantidad,
                        stop_loss_pct, take_profit_pct, trailing_pct, notas, precio_max,
                        clave_csv, actualizado_utc
                    ) VALUES (?, 'radar', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (reg["ticker"], reg["fecha_compra"], reg["precio_compra"], reg["cantidad"],
                      reg["stop_loss_pct"], reg["take_profit_pct"], reg["trailing_pct"],
                      reg["notas"], reg["precio_compra"], reg["clave_csv"], utc_str(ahora)))
                resultado.nuevas += 1
                continue

            pos_id, estado, *actuales = existente
            nuevos = [reg[c] for c in COLUMNAS_EDITABLES]
            if list(actuales) == nuevos:
                resultado.sin_cambios += 1
            elif estado != "abierta":
                resultado.cerradas_no_modificadas += 1
            else:
                asignaciones = ", ".join(f"{c} = ?" for c in COLUMNAS_EDITABLES)
                conn.execute(f"UPDATE posiciones SET {asignaciones}, actualizado_utc = ? WHERE id = ?",
                             (*nuevos, utc_str(ahora), pos_id))
                resultado.actualizadas += 1

        claves_csv = {r["clave_csv"] for r in registros}
        abiertas = conn.execute(
            "SELECT clave_csv FROM posiciones WHERE estado = 'abierta' AND clave_csv IS NOT NULL")
        resultado.ausentes_en_csv = sum(1 for (clave,) in abiertas if clave not in claves_csv)
    return resultado


def cargar_posiciones_desde_csv(conn: sqlite3.Connection, path_csv: str) -> int:
    """Compatibilidad con versiones anteriores: devuelve la cantidad de posiciones nuevas."""
    return importar_posiciones(conn, path_csv).nuevas


# ==========================================================
# Evaluación de posiciones contra precios actuales
# ==========================================================

def _calcular_gatillo(precio_actual, precio_compra, sl_pct, tp_pct, trail_pct, precio_max):
    """Misma prioridad que versiones anteriores: take profit > trailing > stop loss."""
    gatillo = None
    if sl_pct is not None:
        precio_sl = precio_compra * (1 - sl_pct / 100)
        if precio_actual <= precio_sl:
            gatillo = {"tipo": "stop_loss", "precio_gatillo": precio_sl}

    if tp_pct is not None:
        precio_tp = precio_compra * (1 + tp_pct / 100)
        if precio_actual >= precio_tp:
            gatillo = {"tipo": "take_profit", "precio_gatillo": precio_tp}

    if trail_pct is not None and precio_max is not None and precio_max > precio_compra:
        precio_trail = precio_max * (1 - trail_pct / 100)
        if precio_trail > precio_compra and precio_actual <= precio_trail:
            if gatillo is None or gatillo["tipo"] != "take_profit":
                gatillo = {"tipo": "trailing", "precio_gatillo": precio_trail}
    return gatillo


def _gatillo_activo(conn: sqlite3.Connection, posicion_id: int, tipo: str):
    return conn.execute("""
        SELECT id FROM eventos_posicion
        WHERE posicion_id = ? AND tipo = ? AND rearmado_utc IS NULL
        ORDER BY id DESC LIMIT 1
    """, (posicion_id, tipo)).fetchone()


def evaluar_posiciones(conn: sqlite3.Connection, precios_actuales: dict,
                       run_id: str | None = None, ahora=None) -> list:
    """
    Evalúa cada posición abierta contra el último cierre válido del radar
    ({"BTCUSDT": 76000.0, ...}). Actualiza el máximo para el trailing y
    registra UN evento por gatillo nuevo (idempotente entre corridas).

    Devuelve la lista de eventos NUEVOS de esta corrida. No hace commit.
    """
    ahora = ahora or ahora_utc()
    posiciones = conn.execute("""
        SELECT id, ticker, precio_compra, stop_loss_pct, take_profit_pct,
               trailing_pct, precio_max
        FROM posiciones WHERE estado = 'abierta'
    """).fetchall()

    nuevos = []
    for pos_id, ticker, precio_compra, sl_pct, tp_pct, trail_pct, precio_max in posiciones:
        precio_actual = precios_actuales.get(ticker)
        if precio_actual is None or not math.isfinite(precio_actual) or precio_actual <= 0:
            continue  # sin precio válido en esta corrida

        if precio_max is None or precio_actual > precio_max:
            conn.execute("UPDATE posiciones SET precio_max = ? WHERE id = ?", (precio_actual, pos_id))
            precio_max = precio_actual

        gatillo = _calcular_gatillo(precio_actual, precio_compra, sl_pct, tp_pct, trail_pct, precio_max)
        if gatillo is None or _gatillo_activo(conn, pos_id, gatillo["tipo"]):
            continue

        pnl_pct = (precio_actual - precio_compra) / precio_compra * 100
        cur = conn.execute("""
            INSERT INTO eventos_posicion
                (posicion_id, timestamp, timestamp_utc, run_id, tipo, precio, pnl_pct,
                 mensaje, notificado)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
        """, (pos_id, local_str(ahora), utc_str(ahora), run_id, gatillo["tipo"],
              precio_actual, pnl_pct, f"{gatillo['tipo']} gatillado"))
        nuevos.append({"evento_id": cur.lastrowid, "posicion_id": pos_id,
                       "ticker": ticker, "tipo": gatillo["tipo"]})
    return nuevos


def eventos_pendientes_de_notificar(conn: sqlite3.Connection) -> list:
    """Eventos vigentes (no rearmados) de posiciones abiertas aún no notificados."""
    filas = conn.execute("""
        SELECT e.id, e.posicion_id, e.tipo, e.precio, e.pnl_pct,
               p.ticker, p.precio_compra, p.cantidad, p.precio_max, p.notas
        FROM eventos_posicion e
        JOIN posiciones p ON p.id = e.posicion_id
        WHERE e.notificado = 0 AND e.rearmado_utc IS NULL AND p.estado = 'abierta'
        ORDER BY e.id
    """).fetchall()
    claves = ["evento_id", "posicion_id", "tipo", "precio_actual", "pnl_pct",
              "ticker", "precio_compra", "cantidad", "precio_max", "notas"]
    return [dict(zip(claves, f)) for f in filas]


def notificar_eventos_pendientes(conn: sqlite3.Connection, notificador, run_id=None,
                                 ahora=None) -> tuple:
    """
    Intenta notificar cada evento pendiente. Solo un envío confirmado marca
    notificado = 1; un fallo suma un intento y se reintenta la próxima corrida.
    Devuelve (enviados, fallidos).
    """
    from telegram_alertas import registrar_log

    ahora = ahora or ahora_utc()
    enviados = fallidos = 0
    for evento in eventos_pendientes_de_notificar(conn):
        ok = bool(notificador(formatear_alerta_posicion(evento)))
        with conn:
            if ok:
                conn.execute("UPDATE eventos_posicion SET notificado = 1, notificado_utc = ?, "
                             "intentos_notificacion = intentos_notificacion + 1 WHERE id = ?",
                             (utc_str(ahora), evento["evento_id"]))
            else:
                conn.execute("UPDATE eventos_posicion SET intentos_notificacion = "
                             "intentos_notificacion + 1 WHERE id = ?", (evento["evento_id"],))
            registrar_log(conn, "posicion", f"evento:{evento['evento_id']}",
                          "enviada" if ok else "fallida", run_id, ahora)
        enviados += ok
        fallidos += not ok
    return enviados, fallidos


# ==========================================================
# Decisiones explícitas del usuario
# ==========================================================

def rearmar_evento(conn: sqlite3.Connection, evento_id: int, ahora=None) -> bool:
    """Rearma el gatillo: si la condición se vuelve a cumplir, se genera un evento nuevo."""
    with conn:
        cur = conn.execute("UPDATE eventos_posicion SET rearmado_utc = ? "
                           "WHERE id = ? AND rearmado_utc IS NULL",
                           (utc_str(ahora or ahora_utc()), evento_id))
    return cur.rowcount == 1


def confirmar_evento(conn: sqlite3.Connection, evento_id: int, ahora=None) -> bool:
    """Marca el evento como visto. No lo rearma ni cierra la posición."""
    with conn:
        cur = conn.execute("UPDATE eventos_posicion SET confirmado_utc = ? "
                           "WHERE id = ? AND confirmado_utc IS NULL",
                           (utc_str(ahora or ahora_utc()), evento_id))
    return cur.rowcount == 1


def cerrar_posicion(conn: sqlite3.Connection, posicion_id: int, tipo_cierre: str,
                    precio_cierre: float, pnl_pct: float | None = None, ahora=None) -> bool:
    """Marca la posición como cerrada. Solo se usa por decisión explícita del usuario."""
    if not math.isfinite(precio_cierre) or precio_cierre <= 0:
        raise ValueError("precio_cierre debe ser un número finito > 0")
    estado = {"stop_loss": "cerrada_sl", "take_profit": "cerrada_tp",
              "trailing": "cerrada_trail"}.get(tipo_cierre, "cerrada_manual")
    with conn:
        fila = conn.execute("SELECT precio_compra FROM posiciones WHERE id = ? AND estado = 'abierta'",
                            (posicion_id,)).fetchone()
        if fila is None:
            return False
        if pnl_pct is None:
            pnl_pct = (precio_cierre - fila[0]) / fila[0] * 100
        conn.execute("""
            UPDATE posiciones SET estado = ?, fecha_cierre = ?, precio_cierre = ?, pnl_pct = ?,
                actualizado_utc = ?
            WHERE id = ?
        """, (estado, local_str(ahora or ahora_utc()), precio_cierre, pnl_pct,
              utc_str(ahora or ahora_utc()), posicion_id))
    return True


def registrar_evento(conn: sqlite3.Connection, posicion_id: int, tipo: str,
                     precio: float, pnl_pct: float, mensaje: str):
    """Compatibilidad: registra un evento ya notificado."""
    ahora = ahora_utc()
    with conn:
        conn.execute("""
            INSERT INTO eventos_posicion (posicion_id, timestamp, timestamp_utc, tipo, precio,
                                          pnl_pct, mensaje, notificado, notificado_utc)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
        """, (posicion_id, local_str(ahora), utc_str(ahora), tipo, precio, pnl_pct, mensaje,
              utc_str(ahora)))


# ==========================================================
# Formateo de mensajes para Telegram (canal privado del usuario)
# ==========================================================

def formatear_alerta_posicion(evento: dict) -> str:
    """Devuelve mensaje HTML formateado para Telegram con guía de acción."""
    from telegram_alertas import escapar

    emoji = {"stop_loss": "🛑", "take_profit": "💰", "trailing": "📉"}.get(evento["tipo"], "📊")
    titulo = {
        "stop_loss": "STOP LOSS GATILLADO",
        "take_profit": "TAKE PROFIT GATILLADO",
        "trailing": "TRAILING STOP GATILLADO",
    }.get(evento["tipo"], "ALERTA POSICIÓN")

    pnl = evento["pnl_pct"]
    pnl_marca = "▲" if pnl > 0 else "▼" if pnl < 0 else "="
    valor_compra = evento["precio_compra"] * evento["cantidad"]
    valor_actual = evento["precio_actual"] * evento["cantidad"]
    pnl_abs = valor_actual - valor_compra

    texto = (
        f"{emoji} <b>{titulo}</b>\n\n"
        f"<b>{escapar(evento['ticker'])}</b> (posición #{int(evento['posicion_id'])}, "
        f"evento #{int(evento['evento_id'])})\n"
        f"Compra: {evento['precio_compra']:,.4f} ({evento['cantidad']})\n"
        f"Último cierre: {evento['precio_actual']:,.4f}\n"
        f"{pnl_marca} P&L: <b>{pnl:+.2f}%</b> ({pnl_abs:+,.2f})\n"
    )
    if evento["tipo"] == "trailing" and evento.get("precio_max") is not None:
        texto += f"Máximo alcanzado: {evento['precio_max']:,.4f}\n"
    if evento.get("notas"):
        texto += f"\n<i>{escapar(evento['notas'])}</i>"

    texto += "\n\n<b>📋 Qué considerar:</b>"
    if evento["tipo"] == "stop_loss":
        texto += (
            "\n• Llegaste a tu límite de pérdida planeado."
            "\n• Chequear si la caída es del mercado entero o solo este activo."
            "\n• Recordatorio: cambiar el stop loss <i>en caliente</i> suele empeorar las cosas."
            "\n• Vender en un exchange tiene costo de spread y comisiones."
        )
    elif evento["tipo"] == "take_profit":
        texto += (
            "\n• Tu objetivo de ganancia se cumplió."
            "\n• Ganancia en pantalla ≠ ganancia realizada hasta que vendas."
        )
    elif evento["tipo"] == "trailing":
        texto += "\n• El precio bajó desde el máximo más de lo que definiste."

    texto += ("\n\nEste aviso no se repite. Para volver a vigilarlo: "
              f"<code>python gestionar_posiciones.py rearmar {int(evento['evento_id'])}</code>"
              "\n⚠️ La decisión final es tuya; esto no es asesoramiento financiero.")
    return texto

"""
Capa de base de datos SQLite.

- Conexión con `PRAGMA foreign_keys=ON` y timeout de espera.
- Migraciones versionadas con `PRAGMA user_version`. Antes de migrar una DB
  existente se crea un respaldo junto a ella (<db>.respaldo-vN-<fecha>).
- Bloqueo de corrida a nivel de sistema operativo (<db>.lock) para que dos
  procesos (loop, .bat, Task Scheduler) no escriban la misma DB a la vez.
- Escritura de señales, precios y estado por corrida/activo.
- Retención configurable por tabla.

Tablas de mercado:
  - senales_actuales: la "foto del momento" (1 fila por ticker, se pisa).
  - senales_historico: log de todas las corridas (append-only).
  - precios_ohlcv: velas cerradas con indicadores (upsert por ticker+timestamp).
Tablas de operación:
  - corridas: una fila por ejecución (run_id, estado, conteos).
  - resultados_activo: resultado de cada activo en cada corrida.
  - alertas_enviadas / alertas_log: estado y registro de notificaciones.
Tablas privadas (solo locales, nunca en la demo pública):
  - posiciones, eventos_posicion, ripio_balance_snapshot, ripio_cambios_pendientes.
"""

import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import timedelta

import pandas as pd

from tiempo import ahora_utc, local_str, utc_str

SCHEMA_VERSION = 2
TIMEOUT_SQLITE_S = 10

ESTADOS_CORRIDA = ("en_curso", "completa", "parcial", "fallida", "interrumpida")
ESTADOS_ACTIVO = ("valido", "obsoleto", "sin_datos", "historial_insuficiente",
                  "error_proveedor", "dato_invalido")


class CorridaEnCurso(RuntimeError):
    """Otra ejecución tiene tomada la misma base de datos."""


# ============================================================
# Migraciones
# ============================================================

MIGRACION_1 = [
    # Esquema original (compatible con DBs creadas por versiones anteriores).
    """CREATE TABLE IF NOT EXISTS senales_actuales (
        ticker TEXT PRIMARY KEY, tipo TEXT NOT NULL, fuente TEXT NOT NULL,
        timestamp TEXT NOT NULL, precio REAL, señal TEXT, fuerza INTEGER,
        rsi REAL, macd_hist REAL, vol_relativo REAL, ma_corta REAL, ma_larga REAL,
        motivos TEXT)""",
    """CREATE TABLE IF NOT EXISTS senales_historico (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL, tipo TEXT NOT NULL,
        fuente TEXT NOT NULL, timestamp TEXT NOT NULL, precio REAL, señal TEXT,
        fuerza INTEGER, rsi REAL, macd_hist REAL, vol_relativo REAL, ma_corta REAL,
        ma_larga REAL, motivos TEXT)""",
    "CREATE INDEX IF NOT EXISTS idx_hist_ticker_ts ON senales_historico (ticker, timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_hist_señal ON senales_historico (señal)",
    """CREATE TABLE IF NOT EXISTS precios_ohlcv (
        ticker TEXT NOT NULL, fuente TEXT NOT NULL, timestamp TEXT NOT NULL,
        open REAL, high REAL, low REAL, close REAL, volume REAL, rsi REAL, macd REAL,
        macd_señal REAL, macd_hist REAL, ma_corta REAL, ma_larga REAL, vol_relativo REAL,
        PRIMARY KEY (ticker, timestamp))""",
    "CREATE INDEX IF NOT EXISTS idx_ohlcv_ts ON precios_ohlcv (timestamp)",
    """CREATE TABLE IF NOT EXISTS alertas_enviadas (
        ticker TEXT NOT NULL, señal TEXT NOT NULL, timestamp TEXT NOT NULL,
        PRIMARY KEY (ticker, señal))""",
    """CREATE TABLE IF NOT EXISTS posiciones (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL,
        fuente_precio TEXT NOT NULL, fecha_compra TEXT NOT NULL,
        precio_compra REAL NOT NULL, cantidad REAL NOT NULL, notas TEXT,
        stop_loss_pct REAL, take_profit_pct REAL, trailing_pct REAL,
        estado TEXT DEFAULT 'abierta', precio_max REAL, fecha_cierre TEXT,
        precio_cierre REAL, pnl_pct REAL)""",
    "CREATE INDEX IF NOT EXISTS idx_pos_estado ON posiciones (estado)",
    "CREATE INDEX IF NOT EXISTS idx_pos_ticker ON posiciones (ticker)",
    """CREATE TABLE IF NOT EXISTS eventos_posicion (
        id INTEGER PRIMARY KEY AUTOINCREMENT, posicion_id INTEGER NOT NULL,
        timestamp TEXT NOT NULL, tipo TEXT NOT NULL, precio REAL NOT NULL,
        pnl_pct REAL, mensaje TEXT,
        FOREIGN KEY (posicion_id) REFERENCES posiciones(id))""",
    """CREATE TABLE IF NOT EXISTS ripio_balance_snapshot (
        timestamp TEXT NOT NULL, currency TEXT NOT NULL, amount REAL NOT NULL,
        locked_amount REAL, PRIMARY KEY (timestamp, currency))""",
    "CREATE INDEX IF NOT EXISTS idx_ripio_snapshot_currency ON ripio_balance_snapshot (currency)",
    """CREATE TABLE IF NOT EXISTS ripio_cambios_pendientes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
        currency TEXT NOT NULL, tipo TEXT NOT NULL, saldo_anterior REAL,
        saldo_nuevo REAL, diferencia REAL, procesado INTEGER DEFAULT 0)""",
]

COLUMNAS_CORRIDA_SEÑAL = [
    ("run_id", "TEXT"), ("generado_utc", "TEXT"), ("capturado_utc", "TEXT"),
    ("vela_utc", "TEXT"), ("vela_original", "TEXT"), ("timeframe", "TEXT"),
    ("mercado", "TEXT"), ("moneda", "TEXT"), ("estado_dato", "TEXT"),
]

COLUMNAS_NUEVAS_V2 = {
    "senales_actuales": COLUMNAS_CORRIDA_SEÑAL,
    "senales_historico": COLUMNAS_CORRIDA_SEÑAL,
    "precios_ohlcv": [("timestamp_utc", "TEXT"), ("tz_original", "TEXT"), ("timeframe", "TEXT"),
                      ("moneda", "TEXT"), ("ajuste", "TEXT"), ("run_id", "TEXT")],
    "alertas_enviadas": [("timestamp_utc", "TEXT"), ("run_id", "TEXT")],
    "posiciones": [("clave_csv", "TEXT"), ("actualizado_utc", "TEXT")],
    "eventos_posicion": [("run_id", "TEXT"), ("timestamp_utc", "TEXT"),
                         ("notificado", "INTEGER NOT NULL DEFAULT 0"),
                         ("notificado_utc", "TEXT"),
                         ("intentos_notificacion", "INTEGER NOT NULL DEFAULT 0"),
                         ("rearmado_utc", "TEXT"), ("confirmado_utc", "TEXT")],
    "ripio_cambios_pendientes": [("timestamp_utc", "TEXT"), ("run_id", "TEXT"),
                                 ("notificado", "INTEGER NOT NULL DEFAULT 0"),
                                 ("notificado_utc", "TEXT"), ("estado_dato", "TEXT")],
}

MIGRACION_2_TABLAS = [
    f"""CREATE TABLE IF NOT EXISTS corridas (
        run_id TEXT PRIMARY KEY,
        inicio_utc TEXT NOT NULL,
        fin_utc TEXT,
        estado TEXT NOT NULL CHECK (estado IN {ESTADOS_CORRIDA}),
        activos_total INTEGER NOT NULL DEFAULT 0,
        activos_validos INTEGER NOT NULL DEFAULT 0,
        activos_obsoletos INTEGER NOT NULL DEFAULT 0,
        activos_sin_datos INTEGER NOT NULL DEFAULT 0,
        activos_fallidos INTEGER NOT NULL DEFAULT 0,
        detalle TEXT)""",
    "CREATE INDEX IF NOT EXISTS idx_corridas_inicio ON corridas (inicio_utc)",
    f"""CREATE TABLE IF NOT EXISTS resultados_activo (
        run_id TEXT NOT NULL REFERENCES corridas(run_id) ON DELETE CASCADE,
        ticker TEXT NOT NULL,
        tipo TEXT NOT NULL,
        fuente TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        estado TEXT NOT NULL CHECK (estado IN {ESTADOS_ACTIVO}),
        capturado_utc TEXT NOT NULL,
        vela_utc TEXT,
        velas_recibidas INTEGER,
        velas_descartadas INTEGER,
        velas_abiertas INTEGER,
        moneda TEXT,
        detalle TEXT,
        PRIMARY KEY (run_id, ticker))""",
    "CREATE INDEX IF NOT EXISTS idx_resultados_estado ON resultados_activo (estado)",
    """CREATE TABLE IF NOT EXISTS alertas_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT REFERENCES corridas(run_id) ON DELETE SET NULL,
        timestamp_utc TEXT NOT NULL,
        canal TEXT NOT NULL,
        categoria TEXT NOT NULL,
        referencia TEXT,
        resultado TEXT NOT NULL CHECK (resultado IN ('enviada', 'fallida', 'omitida')),
        detalle TEXT)""",
    "CREATE INDEX IF NOT EXISTS idx_alertas_log_ts ON alertas_log (timestamp_utc)",
]

MIGRACION_2_POST = [
    "CREATE INDEX IF NOT EXISTS idx_hist_run ON senales_historico (run_id)",
    "CREATE INDEX IF NOT EXISTS idx_ohlcv_ts_utc ON precios_ohlcv (timestamp_utc)",
    "CREATE INDEX IF NOT EXISTS idx_eventos_gatillo ON eventos_posicion (posicion_id, tipo, rearmado_utc)",
    # Los eventos previos solo se registraban tras un envío exitoso.
    "UPDATE eventos_posicion SET notificado = 1 WHERE notificado = 0 AND run_id IS NULL",
    # Los cambios previos de Ripio ya se notificaban en cada corrida.
    "UPDATE ripio_cambios_pendientes SET notificado = 1 WHERE notificado = 0 AND run_id IS NULL",
]


def _columnas(conn: sqlite3.Connection, tabla: str) -> set:
    return {fila[1] for fila in conn.execute(f'PRAGMA table_info("{tabla}")')}


def _agregar_columnas(conn: sqlite3.Connection, tabla: str, columnas: list) -> None:
    existentes = _columnas(conn, tabla)
    for nombre, tipo in columnas:
        if nombre not in existentes:
            conn.execute(f'ALTER TABLE "{tabla}" ADD COLUMN "{nombre}" {tipo}')


def _migracion_1(conn: sqlite3.Connection) -> None:
    for sql in MIGRACION_1:
        conn.execute(sql)


def _migracion_2(conn: sqlite3.Connection) -> None:
    for sql in MIGRACION_2_TABLAS:
        conn.execute(sql)
    for tabla, columnas in COLUMNAS_NUEVAS_V2.items():
        _agregar_columnas(conn, tabla, columnas)
    for sql in MIGRACION_2_POST:
        conn.execute(sql)
    _completar_claves_posiciones(conn)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_pos_clave_csv "
                 "ON posiciones (clave_csv) WHERE clave_csv IS NOT NULL")


def _completar_claves_posiciones(conn: sqlite3.Connection) -> None:
    """Calcula clave_csv para posiciones existentes (sin duplicar claves)."""
    from posiciones import clave_posicion  # import diferido: evita ciclo

    usadas = {r[0] for r in conn.execute(
        "SELECT clave_csv FROM posiciones WHERE clave_csv IS NOT NULL")}
    filas = conn.execute(
        "SELECT id, ticker, fecha_compra, precio_compra FROM posiciones "
        "WHERE clave_csv IS NULL ORDER BY id").fetchall()
    for pos_id, ticker, fecha, precio in filas:
        clave = clave_posicion(ticker, fecha, precio)
        if clave in usadas:
            clave = f"{clave}#{pos_id}"
        usadas.add(clave)
        conn.execute("UPDATE posiciones SET clave_csv = ? WHERE id = ?", (clave, pos_id))


MIGRACIONES = {1: _migracion_1, 2: _migracion_2}


def version_esquema(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def _tiene_tablas(conn: sqlite3.Connection) -> bool:
    return conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0] > 0


def crear_respaldo(conn: sqlite3.Connection, path_db: str, version: int) -> str:
    """Copia consistente de la DB (API de backup de SQLite) antes de migrar."""
    sello = ahora_utc().strftime("%Y%m%dT%H%M%SZ")
    destino = f"{path_db}.respaldo-v{version}-{sello}"
    copia = sqlite3.connect(destino)
    try:
        conn.backup(copia)
    finally:
        copia.close()
    return destino


def aplicar_migraciones(conn: sqlite3.Connection, path_db: str | None = None) -> list:
    """
    Lleva la DB a SCHEMA_VERSION. Cada migración corre en su propia
    transacción junto con el cambio de user_version (todo o nada).
    Devuelve la lista de versiones aplicadas.
    """
    actual = version_esquema(conn)
    if actual > SCHEMA_VERSION:
        raise RuntimeError(f"La DB tiene esquema v{actual}, más nuevo que el soportado "
                           f"(v{SCHEMA_VERSION}). Actualizá el código.")
    if actual == SCHEMA_VERSION:
        return []

    if path_db and _tiene_tablas(conn):
        crear_respaldo(conn, path_db, actual)

    aplicadas = []
    for version in range(actual + 1, SCHEMA_VERSION + 1):
        conn.execute("BEGIN")
        try:
            MIGRACIONES[version](conn)
            conn.execute(f"PRAGMA user_version = {int(version)}")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        aplicadas.append(version)
    return aplicadas


# ============================================================
# Conexión y bloqueo
# ============================================================

def conectar(path_db: str, *, respaldar: bool = True) -> sqlite3.Connection:
    """Abre conexión, activa claves foráneas y aplica migraciones pendientes."""
    carpeta = os.path.dirname(path_db)
    if carpeta:
        os.makedirs(carpeta, exist_ok=True)
    conn = sqlite3.connect(path_db, timeout=TIMEOUT_SQLITE_S)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        aplicar_migraciones(conn, path_db if respaldar else None)
    except Exception:
        conn.close()
        raise
    return conn


@contextmanager
def abrir(path_db: str, *, respaldar: bool = True):
    """Context manager: la conexión se cierra siempre, incluso ante errores."""
    conn = conectar(path_db, respaldar=respaldar)
    try:
        yield conn
    finally:
        conn.close()


class BloqueoCorrida:
    """
    Lock exclusivo sobre <db>.lock usando primitivas del sistema operativo
    (msvcrt en Windows, fcntl en POSIX). El SO lo libera si el proceso muere,
    así que no quedan locks "huérfanos".
    """

    def __init__(self, path_db: str):
        self.path = f"{path_db}.lock"
        self._archivo = None

    def adquirir(self) -> "BloqueoCorrida":
        carpeta = os.path.dirname(self.path)
        if carpeta:
            os.makedirs(carpeta, exist_ok=True)
        archivo = open(self.path, "a+b")  # noqa: SIM115 - se cierra en liberar()
        try:
            if os.name == "nt":
                import msvcrt
                archivo.seek(0)
                msvcrt.locking(archivo.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(archivo.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            archivo.close()
            raise CorridaEnCurso(
                f"Ya hay una corrida usando {os.path.basename(self.path)[:-5]}. "
                "Esperá a que termine.") from None
        self._archivo = archivo
        return self

    def liberar(self) -> None:
        if self._archivo is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self._archivo.seek(0)
                msvcrt.locking(self._archivo.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self._archivo.close()
            self._archivo = None

    def __enter__(self):
        return self.adquirir()

    def __exit__(self, *exc):
        self.liberar()
        return False


# ============================================================
# Corridas y resultados por activo
# ============================================================

def iniciar_corrida(conn: sqlite3.Connection, run_id: str, inicio_utc) -> None:
    """Registra la corrida como 'en_curso'. Las 'en_curso' previas quedaron
    interrumpidas (el bloqueo garantiza que no hay otra corrida viva)."""
    with conn:
        conn.execute("UPDATE corridas SET estado = 'interrumpida' WHERE estado = 'en_curso'")
        conn.execute("INSERT INTO corridas (run_id, inicio_utc, estado) VALUES (?, ?, 'en_curso')",
                     (run_id, utc_str(inicio_utc)))


def finalizar_corrida(conn: sqlite3.Connection, run_id: str, fin_utc, estado: str,
                      conteos: dict, detalle: str | None = None) -> None:
    with conn:
        conn.execute("""
            UPDATE corridas SET fin_utc = ?, estado = ?, activos_total = ?,
                activos_validos = ?, activos_obsoletos = ?, activos_sin_datos = ?,
                activos_fallidos = ?, detalle = ?
            WHERE run_id = ?
        """, (utc_str(fin_utc), estado, conteos.get("total", 0), conteos.get("valido", 0),
              conteos.get("obsoleto", 0),
              conteos.get("sin_datos", 0) + conteos.get("historial_insuficiente", 0),
              conteos.get("error_proveedor", 0) + conteos.get("dato_invalido", 0),
              detalle, run_id))


def registrar_resultado_activo(conn: sqlite3.Connection, resultado: dict) -> None:
    conn.execute("""
        INSERT INTO resultados_activo
            (run_id, ticker, tipo, fuente, timeframe, estado, capturado_utc, vela_utc,
             velas_recibidas, velas_descartadas, velas_abiertas, moneda, detalle)
        VALUES (:run_id, :ticker, :tipo, :fuente, :timeframe, :estado, :capturado_utc,
                :vela_utc, :velas_recibidas, :velas_descartadas, :velas_abiertas,
                :moneda, :detalle)
    """, resultado)


# ============================================================
# Señales y precios
# ============================================================

COLUMNAS_SEÑAL = [
    "ticker", "tipo", "fuente", "timestamp", "precio", "señal", "fuerza",
    "rsi", "macd_hist", "vol_relativo", "ma_corta", "ma_larga", "motivos",
    "run_id", "generado_utc", "capturado_utc", "vela_utc", "vela_original",
    "timeframe", "mercado", "moneda", "estado_dato",
]


def _fila_señal(fila: dict) -> dict:
    return {c: fila.get(c) for c in COLUMNAS_SEÑAL}


def upsert_señal_actual(conn: sqlite3.Connection, fila: dict) -> None:
    """Inserta o reemplaza la señal actual de un ticker."""
    cols = ", ".join(COLUMNAS_SEÑAL)
    valores = ", ".join(f":{c}" for c in COLUMNAS_SEÑAL)
    actualizar = ", ".join(f"{c} = excluded.{c}" for c in COLUMNAS_SEÑAL if c != "ticker")
    conn.execute(f"""
        INSERT INTO senales_actuales ({cols}) VALUES ({valores})
        ON CONFLICT(ticker) DO UPDATE SET {actualizar}
    """, _fila_señal(fila))


def insertar_señal_historico(conn: sqlite3.Connection, fila: dict) -> None:
    """Append-only al histórico."""
    cols = ", ".join(COLUMNAS_SEÑAL)
    valores = ", ".join(f":{c}" for c in COLUMNAS_SEÑAL)
    conn.execute(f"INSERT INTO senales_historico ({cols}) VALUES ({valores})", _fila_señal(fila))


def formatear_timestamp_vela(serie: pd.Series, intervalo: str) -> pd.Series:
    """
    Formato del timestamp original de la vela (clave de precios_ohlcv).
    Igual al que generaban las versiones anteriores: fecha sola para velas
    diarias/semanales y fecha-hora para intradiarias.
    """
    formato = "%Y-%m-%d" if intervalo in ("1d", "1wk") else "%Y-%m-%d %H:%M:%S"
    return pd.to_datetime(serie).dt.strftime(formato)


COLUMNAS_OHLCV = ["ticker", "fuente", "timestamp", "open", "high", "low", "close",
                  "volume", "rsi", "macd", "macd_señal", "macd_hist",
                  "ma_corta", "ma_larga", "vol_relativo",
                  "timestamp_utc", "tz_original", "timeframe", "moneda", "ajuste", "run_id"]


def upsert_precios(conn: sqlite3.Connection, df: pd.DataFrame, ticker: str, fuente: str,
                   intervalo: str = "1h", run_id: str | None = None) -> int:
    """
    Inserta o actualiza filas OHLCV+indicadores (solo velas cerradas).
    Devuelve cantidad de filas afectadas.
    """
    if df.empty:
        return 0

    df_a_guardar = df.copy()

    # Las MAs tienen nombres dinámicos según config (ma_20, ma_50): corta/larga.
    cols_ma = sorted((c for c in df_a_guardar.columns if re.fullmatch(r"ma_\d+", c)),
                     key=lambda x: int(x.split("_")[1]))
    if len(cols_ma) >= 2:
        df_a_guardar = df_a_guardar.rename(columns={cols_ma[0]: "ma_corta", cols_ma[-1]: "ma_larga"})

    df_a_guardar["ticker"] = ticker
    df_a_guardar["fuente"] = fuente
    df_a_guardar["timeframe"] = intervalo
    df_a_guardar["run_id"] = run_id
    df_a_guardar["timestamp"] = formatear_timestamp_vela(df_a_guardar["timestamp"], intervalo)
    if "timestamp_utc" in df_a_guardar.columns:
        df_a_guardar["timestamp_utc"] = df_a_guardar["timestamp_utc"].map(utc_str)

    cols_finales = [c for c in COLUMNAS_OHLCV if c in df_a_guardar.columns]
    df_a_guardar = df_a_guardar[cols_finales].astype(object)
    df_a_guardar = df_a_guardar.where(pd.notna(df_a_guardar), None)

    placeholders = ", ".join(f":{c}" for c in cols_finales)
    update_str = ", ".join(f"{c} = excluded.{c}" for c in cols_finales
                           if c not in ("ticker", "timestamp"))
    sql = f"""
        INSERT INTO precios_ohlcv ({", ".join(cols_finales)})
        VALUES ({placeholders})
        ON CONFLICT(ticker, timestamp) DO UPDATE SET {update_str}
    """
    registros = df_a_guardar.to_dict(orient="records")
    conn.executemany(sql, registros)
    return len(registros)


# ============================================================
# Retención
# ============================================================

# tabla -> (columna de fecha, base horaria, condición extra)
# Base "local": columnas legacy escritas en hora local del sistema.
REGLAS_RETENCION = {
    "senales_historico": ("timestamp", "local", ""),
    "precios_ohlcv": ("timestamp", "local", ""),
    "corridas": ("inicio_utc", "utc", " AND estado != 'en_curso'"),
    "resultados_activo": ("capturado_utc", "utc", ""),
    "alertas_log": ("timestamp_utc", "utc", ""),
    "ripio_balance_snapshot": ("timestamp", "local", ""),
    # Solo se purgan cambios ya notificados; los pendientes se conservan.
    "ripio_cambios_pendientes": ("timestamp", "local", " AND notificado = 1"),
}


def aplicar_retencion(conn: sqlite3.Connection, retencion_dias: dict, ahora=None) -> dict:
    """
    Borra filas más viejas que la retención de cada tabla.
    Tablas sin regla o con valor None no se purgan (posiciones, eventos,
    estado de alertas). Devuelve {tabla: filas_borradas}. No hace commit.
    """
    ahora = ahora or ahora_utc()
    borradas = {}
    for tabla, dias in retencion_dias.items():
        if dias is None or tabla not in REGLAS_RETENCION:
            continue
        columna, base, extra = REGLAS_RETENCION[tabla]
        limite = ahora - timedelta(days=int(dias))
        corte = utc_str(limite) if base == "utc" else local_str(limite)
        cur = conn.execute(f'DELETE FROM "{tabla}" WHERE "{columna}" < ?{extra}', (corte,))
        borradas[tabla] = cur.rowcount
    return borradas


def estadisticas_db(conn: sqlite3.Connection) -> dict:
    """Devuelve métricas básicas para mostrar al final de cada corrida."""
    stats = {}
    for tabla in ["senales_actuales", "senales_historico", "precios_ohlcv", "corridas"]:
        cur = conn.execute(f"SELECT COUNT(*) FROM {tabla}")
        stats[tabla] = cur.fetchone()[0]
    return stats

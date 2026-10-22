"""
Utilidades de tiempo e identificadores de corrida.

Convención: todo timestamp guardado en columnas *_utc usa el formato
"YYYY-MM-DD HH:MM:SS" en UTC (sin sufijo de zona, la zona la indica el
nombre de la columna). Así se ordena lexicográficamente en SQLite y Power BI
lo interpreta como fecha/hora sin ambigüedad.
"""

import secrets
from datetime import datetime, timezone

import pandas as pd

FORMATO_UTC = "%Y-%m-%d %H:%M:%S"


def ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


def a_datetime_utc(valor) -> datetime:
    """Normaliza datetime/Timestamp (con o sin zona) a datetime UTC con zona."""
    ts = pd.Timestamp(valor)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    return ts.to_pydatetime()


def utc_str(valor) -> str | None:
    """Formatea un instante como texto UTC. None/NaT -> None."""
    if valor is None or (not isinstance(valor, datetime) and pd.isna(valor)):
        return None
    return a_datetime_utc(valor).strftime(FORMATO_UTC)


def local_str(valor) -> str:
    """Hora local del sistema (columna legacy `timestamp`)."""
    return a_datetime_utc(valor).astimezone().strftime(FORMATO_UTC)


def nuevo_run_id(inicio_utc: datetime) -> str:
    """
    Identificador estable de una corrida: el mismo valor se usa en todas las
    filas que esa corrida escribe. Ordenable por fecha y con sufijo aleatorio
    para que dos corridas en el mismo segundo no colisionen.
    """
    return f"{a_datetime_utc(inicio_utc).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"

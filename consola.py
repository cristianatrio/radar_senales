"""Salida de consola robusta en Windows (cp1252) para los scripts de línea de comandos."""

import sys


def configurar_salida_utf8() -> None:
    """
    Fuerza UTF-8 en stdout/stderr. Sin esto, redirigir la salida a un archivo
    o a otro proceso en Windows falla con UnicodeEncodeError (emojis, "≥", "—").
    """
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

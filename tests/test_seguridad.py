"""
Chequeos de publicación: plantillas sin secretos, .gitignore completo y
ningún archivo público con patrones de credenciales. No lee los archivos de
configuración reales (ripio_config.txt, telegram_config.txt).
"""

import os
import re

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Archivos/carpetas locales que el .gitignore excluye y que este test NO abre.
EXCLUIDOS_DIR = {"output", "__pycache__", ".pytest_cache", ".ruff_cache", ".venv", "venv",
                 ".git", "salida"}
EXCLUIDOS_ARCHIVO = {"ripio_config.txt", "telegram_config.txt", "PROMPT_PARA_CLAUDE.md"}
EXTENSIONES_BINARIAS = {".pbix", ".db", ".pyc", ".png", ".jpg"}

PATRONES_SECRETOS = {
    "token de Telegram": re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),
    "clave privada": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "asignación de secreto": re.compile(
        r"(?i)^\s*(API_KEY|SECRET_KEY|TOKEN|CHAT_ID|RIPIO_API_KEY|RIPIO_SECRET_KEY|"
        r"TELEGRAM_TOKEN|TELEGRAM_CHAT_ID)\s*=\s*\S+"),
}


def _archivos_publicos():
    for raiz, dirs, archivos in os.walk(RAIZ):
        dirs[:] = [d for d in dirs if d not in EXCLUIDOS_DIR]
        for nombre in archivos:
            if (nombre in EXCLUIDOS_ARCHIVO or nombre.startswith("AUDITORIA_")
                    or os.path.splitext(nombre)[1].lower() in EXTENSIONES_BINARIAS):
                continue
            yield os.path.join(raiz, nombre)


def test_ningun_archivo_publico_contiene_patrones_de_secretos():
    hallazgos = []
    for ruta in _archivos_publicos():
        with open(ruta, encoding="utf-8", errors="ignore") as f:
            for n, linea in enumerate(f, 1):
                for nombre, patron in PATRONES_SECRETOS.items():
                    # En .py, "api_key = os.environ.get(...)" es legítimo: solo se
                    # buscan asignaciones con valor en archivos de configuración/texto.
                    if nombre == "asignación de secreto" and ruta.endswith(".py"):
                        continue
                    if patron.search(linea):
                        hallazgos.append(f"{os.path.relpath(ruta, RAIZ)}:{n} ({nombre})")
    assert hallazgos == []


def test_plantillas_tienen_valores_vacios():
    for nombre in ("ripio_config.example.txt", "telegram_config.example.txt", ".env.example"):
        with open(os.path.join(RAIZ, nombre), encoding="utf-8") as f:
            for linea in f:
                linea = linea.strip()
                if linea and not linea.startswith("#") and "=" in linea:
                    assert linea.split("=", 1)[1].strip() == "", f"{nombre}: {linea.split('=')[0]}"


def test_gitignore_protege_archivos_locales():
    with open(os.path.join(RAIZ, ".gitignore"), encoding="utf-8") as f:
        reglas = {linea.strip() for linea in f if linea.strip() and not linea.startswith("#")}
    requeridas = {".env", ".env.*", "!.env.example", "ripio_config.txt", "telegram_config.txt",
                  "output/", "*.db", "posiciones*.csv", "*.pbix", "__pycache__/",
                  ".venv/", "AUDITORIA_*.md"}
    assert requeridas <= reglas


def test_codigo_no_imprime_fragmentos_de_credenciales():
    sospechoso = re.compile(r"(api_key|secret_key|token|chat_id)\s*\[\s*-?\d*\s*:", re.I)
    impresion_cruda = re.compile(r"print\(.*json\.dumps\(\s*balance", re.I)
    for ruta in _archivos_publicos():
        if ruta.endswith(".py") and os.sep + "tests" + os.sep not in ruta:
            codigo = open(ruta, encoding="utf-8").read()
            assert not sospechoso.search(codigo), ruta
            assert not impresion_cruda.search(codigo), ruta

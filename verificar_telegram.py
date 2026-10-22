"""
Verificación MANUAL de Telegram (reemplaza al viejo test_telegram.py).
No es un test automático: con --enviar manda un mensaje real al chat configurado.

    python verificar_telegram.py            # solo indica si hay credenciales
    python verificar_telegram.py --enviar   # envía un mensaje de prueba

Nunca imprime el token ni el chat id.
"""

import argparse
import sys

import telegram_alertas
from tiempo import ahora_utc, utc_str
from consola import configurar_salida_utf8


def main(argv=None) -> int:
    configurar_salida_utf8()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--enviar", action="store_true", help="envía un mensaje real de prueba")
    args = parser.parse_args(argv)

    if not telegram_alertas.telegram_configurado():
        print("❌ Faltan TELEGRAM_TOKEN / TELEGRAM_CHAT_ID (ver telegram_config.example.txt).")
        return 1
    print("✔ Credenciales de Telegram presentes (valores no mostrados).")

    if not args.enviar:
        print("Para enviar un mensaje de prueba real: python verificar_telegram.py --enviar")
        return 0

    texto = (
        "🧪 <b>Test del Radar de Señales</b>\n"
        f"<i>{utc_str(ahora_utc())} UTC</i>\n\n"
        "Si recibiste esto, las alertas están funcionando correctamente. ✅"
    )
    if telegram_alertas.enviar_mensaje(texto):
        print("✅ Mensaje enviado. Revisá Telegram.")
        return 0
    print("❌ Falló el envío (ver el código HTTP arriba). Revisá token y chat id.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

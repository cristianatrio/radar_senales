"""
Verificación MANUAL de la conexión con Ripio (reemplaza al viejo test_ripio.py).
No es un test automático: con --consultar hace un request real de solo lectura.

    python verificar_ripio.py              # solo indica si hay credenciales
    python verificar_ripio.py --consultar  # consulta el balance (no muestra montos)

Nunca imprime credenciales, saldos, montos ni la respuesta cruda de la API.
"""

import argparse
import sys

import ripio_api
import ripio_sync
from fuentes.red import ErrorProveedor
from consola import configurar_salida_utf8


def main(argv=None) -> int:
    configurar_salida_utf8()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--consultar", action="store_true",
                        help="hace una consulta real de solo lectura a Ripio")
    args = parser.parse_args(argv)

    if not ripio_api.credenciales_configuradas():
        print("❌ Faltan RIPIO_API_KEY / RIPIO_SECRET_KEY (ver ripio_config.example.txt).")
        return 1
    print("✔ Credenciales de Ripio presentes (valores no mostrados).")

    if not args.consultar:
        print("Para probar la conexión real: python verificar_ripio.py --consultar")
        return 0

    try:
        balance = ripio_api.obtener_balance_wallet()
    except ErrorProveedor as e:
        print(f"❌ Falló la consulta: {e}")
        print("   Posibles causas: credenciales, IP no autorizada u hora del sistema desfasada.")
        return 1

    parseado = ripio_sync.parsear_balance(balance)
    if not parseado["valido"]:
        print(f"⚠  Conexión OK, pero la respuesta no tiene el formato esperado ({parseado['motivo']}).")
        return 1

    estados = {}
    for info in parseado["monedas"].values():
        estados[info["estado"]] = estados.get(info["estado"], 0) + 1
    print("✅ Conexión OK. Monedas informadas por estado (sin montos):")
    for estado, cantidad in sorted(estados.items()):
        print(f"   {estado}: {cantidad}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

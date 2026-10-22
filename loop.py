"""
Modo loop: deja corriendo el radar y lo reejecuta cada X minutos.
Útil si no querés configurar Task Scheduler — simplemente abrís la ventana,
corrés `python loop.py` y la dejás minimizada.

Ejecutar:
    python loop.py

Para parar: Ctrl+C en la ventana.
"""

import time
import traceback
from datetime import datetime

from db import CorridaEnCurso
from main import correr_radar
from consola import configurar_salida_utf8


# === CONFIGURÁ CADA CUÁNTO QUERÉS QUE CORRA ===
INTERVALO_MINUTOS = 60  # cada 1 hora


def main():
    configurar_salida_utf8()
    print(f"\n{'#'*60}")
    print("# RADAR EN MODO LOOP")
    print(f"# Intervalo: cada {INTERVALO_MINUTOS} minutos")
    print("# Para parar: Ctrl+C")
    print(f"{'#'*60}\n")

    intervalo_s = INTERVALO_MINUTOS * 60
    proxima = time.time()
    while True:
        try:
            correr_radar()
        except KeyboardInterrupt:
            print("\n\n[!] Detenido por el usuario. Chau.")
            break
        except CorridaEnCurso as e:
            print(f"\n[!] {e} Salteo esta corrida.")
        except Exception as e:
            # Solo el tipo: el texto de algunas excepciones puede incluir URLs con tokens.
            print(f"\n[!] Error en la corrida ({type(e).__name__}).")
            traceback.print_tb(e.__traceback__, limit=3)  # solo ubicación, sin el mensaje
            print("    Continúo igual con la próxima corrida.\n")

        # Se programa contra el horario planificado: la duración de la corrida
        # no se suma al intervalo (antes el período real era corrida + intervalo).
        proxima += intervalo_s
        while proxima <= time.time():
            proxima += intervalo_s
        proxima_str = datetime.fromtimestamp(proxima).strftime("%H:%M:%S")
        print(f"\n⏰ Próxima corrida a las {proxima_str}\n")

        try:
            time.sleep(max(0.0, proxima - time.time()))
        except KeyboardInterrupt:
            print("\n\n[!] Detenido por el usuario. Chau.")
            break


if __name__ == "__main__":
    main()

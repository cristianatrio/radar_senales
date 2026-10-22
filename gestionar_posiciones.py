"""
Decisiones explícitas sobre posiciones y sus avisos (uso local y privado).

    python gestionar_posiciones.py gatillos             # avisos vigentes
    python gestionar_posiciones.py confirmar EVENTO_ID  # "lo vi", sin rearmar
    python gestionar_posiciones.py rearmar EVENTO_ID    # vuelve a vigilar ese gatillo
    python gestionar_posiciones.py cerrar POSICION_ID --precio 123.45 [--motivo manual]

Un gatillo (stop loss / take profit / trailing) avisa una sola vez. Queda
"vigente" hasta que lo rearmás; el radar nunca cierra posiciones por su cuenta.
"""

import argparse
import os
import sys

import config
import db
import posiciones as pos
from consola import configurar_salida_utf8


def listar_gatillos(conn) -> None:
    filas = conn.execute("""
        SELECT e.id, e.posicion_id, p.ticker, e.tipo, COALESCE(e.timestamp_utc, e.timestamp),
               e.notificado, e.confirmado_utc IS NOT NULL
        FROM eventos_posicion e JOIN posiciones p ON p.id = e.posicion_id
        WHERE e.rearmado_utc IS NULL AND p.estado = 'abierta'
        ORDER BY e.id
    """).fetchall()
    if not filas:
        print("Sin avisos vigentes.")
        return
    print(f"{'EVENTO':>6} {'POS':>4} {'TICKER':10} {'TIPO':12} {'DISPARADO':19} {'NOTIF.':6} CONFIRM.")
    for ev_id, pos_id, ticker, tipo, cuando, notificado, confirmado in filas:
        print(f"{ev_id:>6} {pos_id:>4} {ticker:10} {tipo:12} {cuando:19} "
              f"{'sí' if notificado else 'no':6} {'sí' if confirmado else 'no'}")


def main(argv=None) -> int:
    configurar_salida_utf8()
    parser = argparse.ArgumentParser(description="Gestiona avisos y cierres de posiciones.")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("gatillos", help="lista avisos vigentes")
    for nombre in ("confirmar", "rearmar"):
        p = sub.add_parser(nombre)
        p.add_argument("evento_id", type=int)
    p = sub.add_parser("cerrar", help="cierra una posición por decisión propia")
    p.add_argument("posicion_id", type=int)
    p.add_argument("--precio", type=float, required=True, help="precio real de venta")
    p.add_argument("--motivo", default="manual",
                   choices=["manual", "stop_loss", "take_profit", "trailing"])
    args = parser.parse_args(argv)

    path_db = os.path.join(config.CARPETA_SALIDA, config.ARCHIVO_DB)
    if not os.path.exists(path_db):
        print(f"[!] No existe {path_db}. Corré primero: python main.py")
        return 1

    try:
        with db.BloqueoCorrida(path_db), db.abrir(path_db) as conn:
            if args.comando == "gatillos":
                listar_gatillos(conn)
                return 0
            if args.comando == "confirmar":
                ok = pos.confirmar_evento(conn, args.evento_id)
            elif args.comando == "rearmar":
                ok = pos.rearmar_evento(conn, args.evento_id)
            else:
                ok = pos.cerrar_posicion(conn, args.posicion_id, args.motivo, args.precio)
    except db.CorridaEnCurso as e:
        print(f"[!] {e}")
        return 2
    except ValueError as e:
        print(f"[!] {e}")
        return 1

    print("✔ Hecho." if ok else "[!] No se encontró el evento/posición o ya estaba en ese estado.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

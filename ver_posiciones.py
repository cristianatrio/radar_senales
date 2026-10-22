"""
Ver estado de tus posiciones.
Ejecutar: python ver_posiciones.py
"""

import os
import sqlite3
import pandas as pd
import config
from consola import configurar_salida_utf8


def main():
    configurar_salida_utf8()
    path_db = os.path.join(config.CARPETA_SALIDA, config.ARCHIVO_DB)
    if not os.path.exists(path_db):
        print("[!] No existe la DB. Corré primero: python main.py")
        return

    # Solo lectura. Muestra datos PRIVADOS: no compartas esta salida.
    conn = sqlite3.connect(f"file:{path_db}?mode=ro", uri=True)

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 200)

    print("\n" + "="*70)
    print(" POSICIONES ABIERTAS")
    print("="*70)
    df = pd.read_sql_query("""
        SELECT id, ticker, fecha_compra, precio_compra, cantidad,
               precio_max, stop_loss_pct, take_profit_pct, trailing_pct, notas
        FROM posiciones
        WHERE estado = 'abierta'
        ORDER BY fecha_compra DESC
    """, conn)
    if df.empty:
        print("  (sin posiciones abiertas)")
        print("  Editá output/posiciones.csv con tus compras y volvé a correr main.py")
    else:
        print(df.to_string(index=False))

    print("\n" + "="*70)
    print(" POSICIONES CERRADAS (últimas 20)")
    print("="*70)
    df = pd.read_sql_query("""
        SELECT ticker, fecha_compra, precio_compra,
               fecha_cierre, precio_cierre, pnl_pct, estado
        FROM posiciones
        WHERE estado != 'abierta'
        ORDER BY fecha_cierre DESC
        LIMIT 20
    """, conn)
    if df.empty:
        print("  (sin posiciones cerradas)")
    else:
        print(df.to_string(index=False))

        cerradas = df.dropna(subset=["pnl_pct"])
        if not cerradas.empty:
            print()
            print(f"  Promedio P&L: {cerradas['pnl_pct'].mean():+.2f}%")
            print(f"  Mejor:        {cerradas['pnl_pct'].max():+.2f}%")
            print(f"  Peor:         {cerradas['pnl_pct'].min():+.2f}%")
            print(f"  Win rate:     {(cerradas['pnl_pct'] > 0).sum()}/{len(cerradas)}")

    print("\n" + "="*70)
    print(" ÚLTIMOS EVENTOS (alertas gatilladas)")
    print("="*70)
    df = pd.read_sql_query("""
        SELECT e.timestamp, p.ticker, e.tipo, e.precio, e.pnl_pct, e.mensaje
        FROM eventos_posicion e
        JOIN posiciones p ON p.id = e.posicion_id
        ORDER BY e.timestamp DESC
        LIMIT 10
    """, conn)
    if df.empty:
        print("  (sin eventos aún)")
    else:
        print(df.to_string(index=False))

    conn.close()
    print()


if __name__ == "__main__":
    main()

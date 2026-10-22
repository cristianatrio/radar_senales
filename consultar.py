"""
Consultas rápidas a la base de datos.
Ejecutar: python consultar.py

Útil para chequear el estado del radar sin abrir Power BI.
Modificá las queries de abajo o agregá las tuyas.
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
        print(f"[!] No existe la DB en {path_db}. Corré primero: python main.py")
        return

    # Solo lectura: esta herramienta nunca modifica la DB.
    conn = sqlite3.connect(f"file:{path_db}?mode=ro", uri=True)

    # Mostrar todo más ancho en consola
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 200)
    pd.set_option("display.max_colwidth", 60)

    print("\n" + "="*70)
    print(" SEÑALES ACTUALES (ordenadas por fuerza)")
    print("="*70)
    df = pd.read_sql_query("""
        SELECT ticker, tipo, señal, fuerza, precio, rsi, vol_relativo, motivos
        FROM senales_actuales
        ORDER BY fuerza DESC
    """, conn)
    print(df.to_string(index=False))

    print("\n" + "="*70)
    print(" TICKERS EN COMPRA O VENTA FUERTE")
    print("="*70)
    df = pd.read_sql_query("""
        SELECT ticker, tipo, señal, fuerza, precio, motivos
        FROM senales_actuales
        WHERE señal IN ('COMPRA_FUERTE', 'VENTA_FUERTE', 'RIESGO_ALTO')
        ORDER BY ABS(fuerza) DESC
    """, conn)
    if df.empty:
        print("  (ninguno por el momento)")
    else:
        print(df.to_string(index=False))

    print("\n" + "="*70)
    print(" CANTIDAD DE SEÑALES POR TIPO EN LAS ÚLTIMAS 24 HS")
    print("="*70)
    df = pd.read_sql_query("""
        SELECT señal, COUNT(*) AS cantidad
        FROM senales_historico
        WHERE timestamp >= datetime('now', '-1 day', 'localtime')
        GROUP BY señal
        ORDER BY cantidad DESC
    """, conn)
    print(df.to_string(index=False) if not df.empty else "  (sin datos en últimas 24hs)")

    print("\n" + "="*70)
    print(" TICKERS QUE CAMBIARON DE SEÑAL EN LA ÚLTIMA CORRIDA")
    print("="*70)
    # Compara la última corrida con la anterior
    df = pd.read_sql_query("""
        WITH ultimas AS (
            SELECT ticker, señal, timestamp,
                   ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY timestamp DESC) AS rn
            FROM senales_historico
        )
        SELECT u1.ticker,
               u2.señal AS señal_anterior,
               u1.señal AS señal_actual,
               u1.timestamp AS cuando
        FROM ultimas u1
        JOIN ultimas u2 ON u1.ticker = u2.ticker
        WHERE u1.rn = 1 AND u2.rn = 2 AND u1.señal != u2.señal
        ORDER BY u1.timestamp DESC
    """, conn)
    if df.empty:
        print("  (no hay cambios respecto a la corrida anterior)")
    else:
        print(df.to_string(index=False))

    conn.close()
    print()


if __name__ == "__main__":
    main()

"""
Radar de Señales - Script principal
Ejecutar: python main.py [--sin-integraciones]

Flujo de una corrida (identificada por un run_id único):
1. Toma un bloqueo exclusivo sobre la DB (evita corridas simultáneas).
2. Trae velas de Binance (cripto) y Yahoo (acciones), valida OHLCV y moneda,
   descarta la vela abierta y mide la frescura del último cierre.
3. Calcula indicadores y genera una señal heurística por activo.
4. Guarda señales, precios y el resultado de cada activo en UNA transacción.
5. Opcional: exporta CSVs, alerta por Telegram, evalúa posiciones y Ripio.
6. Registra el estado final de la corrida (completa / parcial / fallida).

Estados por activo: valido, obsoleto, sin_datos, historial_insuficiente,
error_proveedor, dato_invalido. Solo los datos "valido" generan alertas.
"""

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import timedelta

import pandas as pd

import config
import db
from fuentes.binance_api import obtener_velas_binance
from fuentes.normalizacion import filtrar_velas_cerradas, validar_ohlcv
from fuentes.red import ErrorProveedor
from fuentes.yahoo_api import obtener_velas_yahoo
from indicadores import enriquecer_con_indicadores, velas_minimas
from senales import generar_señal
from tiempo import ahora_utc, local_str, nuevo_run_id, utc_str
from consola import configurar_salida_utf8

SEÑALES_DESTACADAS = ["COMPRA_FUERTE", "VENTA_FUERTE", "RIESGO_ALTO"]


@dataclass(frozen=True)
class Activo:
    ticker: str
    tipo: str          # cripto | accion_arg | cedear | accion_us
    fuente: str        # binance | yahoo
    intervalo: str
    mercado: str
    moneda: str
    instrumento: str


def activos_configurados(cfg) -> list:
    """Arma la lista de activos a partir de las listas y metadatos de config."""
    grupos = [("cripto", cfg.CRIPTO), ("accion_arg", cfg.ACCIONES_ARG),
              ("cedear", getattr(cfg, "CEDEARS", [])), ("accion_us", cfg.ACCIONES_US)]
    etfs = getattr(cfg, "ETFS", set())
    activos = []
    for tipo, tickers in grupos:
        meta = cfg.GRUPOS_ACTIVOS[tipo]
        for ticker in tickers:
            activos.append(Activo(
                ticker=ticker, tipo=tipo, fuente=meta["fuente"],
                intervalo=getattr(cfg, meta["intervalo_config"]),
                mercado=meta["mercado"], moneda=meta["moneda"],
                instrumento="ETF" if ticker in etfs else meta["instrumento"],
            ))
    return activos


def proveedores_reales(cfg) -> dict:
    """Funciones Activo -> DataFrame normalizado, por fuente (hacen requests reales)."""
    return {
        "binance": lambda a: obtener_velas_binance(a.ticker, a.intervalo, cfg.VELAS_HISTORIAL),
        "yahoo": lambda a: obtener_velas_yahoo(a.ticker, a.intervalo, periodo=cfg.PERIODO_YAHOO),
    }


# ============================================================
# Evaluación de un activo (nunca lanza: devuelve un estado)
# ============================================================

def evaluar_activo(activo: Activo, obtener, cfg, run_id: str, reloj=ahora_utc) -> dict:
    """
    Trae datos, valida, filtra la vela abierta y genera la señal.
    Devuelve {"resultado": fila para resultados_activo, "fila": señal | None,
              "precios": DataFrame | None}.
    """
    capturado = reloj()
    resultado = {
        "run_id": run_id, "ticker": activo.ticker, "tipo": activo.tipo,
        "fuente": activo.fuente, "timeframe": activo.intervalo, "estado": None,
        "capturado_utc": utc_str(capturado), "vela_utc": None, "velas_recibidas": 0,
        "velas_descartadas": 0, "velas_abiertas": 0, "moneda": None, "detalle": None,
    }

    def salir(estado, detalle=None, fila=None, precios=None):
        resultado.update(estado=estado, detalle=detalle)
        return {"resultado": resultado, "fila": fila, "precios": precios}

    try:
        crudo = obtener(activo)
    except ErrorProveedor as e:
        return salir("error_proveedor", str(e))

    resultado["velas_recibidas"] = len(crudo)
    if crudo.empty:
        return salir("sin_datos", "el proveedor no devolvió velas")

    validas, descartadas = validar_ohlcv(crudo)
    cerradas, abiertas = filtrar_velas_cerradas(validas, pd.Timestamp(capturado))
    resultado.update(velas_descartadas=descartadas, velas_abiertas=abiertas)

    monedas = set(crudo["moneda"].dropna().astype(str)) if "moneda" in crudo.columns else set()
    resultado["moneda"] = ",".join(sorted(monedas)) or None
    if monedas and monedas != {activo.moneda}:
        return salir("dato_invalido", f"moneda informada {resultado['moneda']}, "
                                      f"se esperaba {activo.moneda}")
    if cerradas.empty:
        return salir("sin_datos", "sin velas cerradas válidas")

    ultima = cerradas.iloc[-1]
    resultado["vela_utc"] = utc_str(ultima["timestamp_utc"])

    try:
        enriquecido = enriquecer_con_indicadores(cerradas, cfg)
    except ValueError as e:
        return salir("dato_invalido", str(e))
    señal = generar_señal(enriquecido, cfg)

    if len(cerradas) < velas_minimas(cfg):
        estado = "historial_insuficiente"
    else:
        antiguedad = pd.Timestamp(capturado) - ultima["cierre_utc"]
        limite = timedelta(hours=cfg.MAX_ANTIGUEDAD_HORAS.get(activo.intervalo, 24))
        estado = "obsoleto" if antiguedad > limite else "valido"

    fila = {
        "timestamp": local_str(capturado),   # legacy: hora local de generación
        "ticker": activo.ticker,
        "tipo": activo.tipo,
        "fuente": activo.fuente,
        **{k: señal[k] for k in ("precio", "señal", "fuerza", "rsi", "macd_hist",
                                 "vol_relativo", "ma_corta", "ma_larga", "motivos")},
        "run_id": run_id,
        "generado_utc": None,                # se completa al guardar la corrida
        "capturado_utc": utc_str(capturado),
        "vela_utc": resultado["vela_utc"],
        "vela_original": f"{ultima['timestamp']} ({ultima['tz_original']})",
        "timeframe": activo.intervalo,
        "mercado": activo.mercado,
        "moneda": activo.moneda,
        "estado_dato": estado,
    }
    detalle = f"{descartadas} velas inválidas descartadas" if descartadas else None
    return salir(estado, detalle, fila, enriquecido)


# ============================================================
# Persistencia de la corrida (una transacción)
# ============================================================

def guardar_resultados(conn, evaluaciones: list, cfg, run_id: str, generado) -> None:
    """Escribe señales, precios y resultados por activo. No hace commit."""
    for ev in evaluaciones:
        db.registrar_resultado_activo(conn, ev["resultado"])
        fila = ev["fila"]
        if fila is None:
            continue
        fila["generado_utc"] = utc_str(generado)
        db.upsert_señal_actual(conn, fila)
        db.insertar_señal_historico(conn, fila)
        precios = ev["precios"]
        if cfg.VELAS_A_GUARDAR:
            precios = precios.tail(cfg.VELAS_A_GUARDAR)
        db.upsert_precios(conn, precios, fila["ticker"], fila["fuente"],
                          fila["timeframe"], run_id)


def contar_estados(evaluaciones: list) -> dict:
    conteos = {"total": len(evaluaciones)}
    for ev in evaluaciones:
        estado = ev["resultado"]["estado"]
        conteos[estado] = conteos.get(estado, 0) + 1
    return conteos


def exportar_csvs(conn, evaluaciones: list, cfg) -> None:
    filas = [ev["fila"] for ev in evaluaciones if ev["fila"] is not None]
    carpeta = cfg.CARPETA_SALIDA
    pd.DataFrame(filas).to_csv(os.path.join(carpeta, cfg.ARCHIVO_SEÑALES),
                               index=False, encoding="utf-8-sig")
    df_hist = pd.read_sql_query("SELECT * FROM senales_historico ORDER BY timestamp DESC", conn)
    df_hist.to_csv(os.path.join(carpeta, cfg.ARCHIVO_HISTORICO), index=False, encoding="utf-8-sig")
    precios = [ev["precios"] for ev in evaluaciones if ev["precios"] is not None]
    if precios:
        df_precios = pd.concat(precios, ignore_index=True)
        for col in ("timestamp_utc", "cierre_utc"):
            df_precios[col] = df_precios[col].map(utc_str)
        df_precios.to_csv(os.path.join(carpeta, cfg.ARCHIVO_PRECIOS), index=False, encoding="utf-8-sig")
    print(f"  ✔ CSVs exportados en {carpeta}/ (senales, histórico y precios de esta corrida)")


# ============================================================
# Integraciones opcionales (cada una aislada: un fallo no corta la corrida)
# ============================================================

def correr_alertas(conn, filas: list, cfg, run_id, notificador, reloj) -> str | None:
    import telegram_alertas
    print(f"\n{'=' * 60}\nTELEGRAM\n{'=' * 60}")
    validas = [f for f in filas if f["estado_dato"] == "valido"]
    entregadas, fallidas = telegram_alertas.enviar_alertas_señales(
        conn, validas, modo_resumen=cfg.TELEGRAM_MODO_RESUMEN,
        alertar_solo_cambios=cfg.TELEGRAM_SOLO_CAMBIOS,
        notificador=notificador, run_id=run_id, ahora=reloj())
    print(f"  · {entregadas} alerta(s) entregada(s)"
          + (f", {fallidas} pendiente(s) de reintento" if fallidas else ""))
    return "alertas pendientes de reintento" if fallidas else None


def correr_posiciones(conn, filas: list, cfg, run_id, notificador, reloj) -> list:
    """Importa el CSV, sincroniza Ripio y evalúa gatillos. Devuelve problemas (texto seguro)."""
    import posiciones as pos_mod
    problemas = []
    print(f"\n{'=' * 60}\nPOSICIONES PERSONALES\n{'=' * 60}")

    path_csv = os.path.join(cfg.CARPETA_SALIDA, cfg.ARCHIVO_POSICIONES)
    pos_mod.crear_csv_ejemplo(path_csv)
    try:
        imp = pos_mod.importar_posiciones(conn, path_csv, ahora=reloj())
        print(f"  · CSV: {imp.nuevas} nueva(s), {imp.actualizadas} actualizada(s), "
              f"{imp.sin_cambios} sin cambios, {imp.ejemplo_ignoradas} fila(s) de ejemplo ignorada(s)")
        if imp.cerradas_no_modificadas:
            print(f"  · {imp.cerradas_no_modificadas} fila(s) corresponden a posiciones cerradas: "
                  "no se modifican")
        if imp.ausentes_en_csv:
            print(f"  · {imp.ausentes_en_csv} posición(es) abierta(s) ya no figuran en el CSV: "
                  "no se modifican (cerralas con gestionar_posiciones.py)")
        for error in imp.errores:
            print(f"  [!] CSV posiciones: {error}")
        if imp.errores:
            problemas.append("errores en el CSV de posiciones")
    except pos_mod.ErrorCSVPosiciones as e:
        print(f"  [!] CSV posiciones: {e}")
        problemas.append("CSV de posiciones ilegible")

    if cfg.RIPIO_ACTIVO:
        problemas += correr_ripio(conn, cfg, run_id, notificador, reloj)

    precios = {f["ticker"]: f["precio"] for f in filas
               if f["estado_dato"] == "valido" and f["precio"] is not None}
    with conn:
        nuevos = pos_mod.evaluar_posiciones(conn, precios, run_id=run_id, ahora=reloj())
    for ev in nuevos:
        print(f"  ⚠  Gatillo nuevo: {ev['tipo']} en {ev['ticker']} "
              f"(posición #{ev['posicion_id']}, evento #{ev['evento_id']})")
    if notificador is not None:
        ok, fallidos = pos_mod.notificar_eventos_pendientes(conn, notificador, run_id, reloj())
        print(f"  · Avisos de posición: {ok} enviado(s), {fallidos} pendiente(s) de reintento")
        if fallidos:
            problemas.append("avisos de posición pendientes")
    abiertas = conn.execute("SELECT COUNT(*) FROM posiciones WHERE estado = 'abierta'").fetchone()[0]
    print(f"  · {abiertas} posición(es) abierta(s)")
    return problemas


def correr_ripio(conn, cfg, run_id, notificador, reloj) -> list:
    import ripio_sync
    print("\n  --- Ripio (solo lectura) ---")
    res = ripio_sync.sincronizar(conn, run_id=run_id, ahora=reloj())
    if res["estado"] != "ok":
        print(f"  [!] Ripio: {res['error']} (no se comparan saldos)")
        return [] if res["estado"] == "no_configurado" else [f"Ripio: {res['estado']}"]

    print(f"  ✔ Ripio: {res['monedas_con_saldo']} moneda(s) con saldo significativo")
    for adv in res["advertencias"]:
        print(f"  · {adv['ticker']}: {adv['tipo'].replace('_', ' ')} en la respuesta "
              "(no se asume venta)")
    tipos = sorted({c["tipo"] for c in res["cambios"]})
    if tipos:
        print(f"  ⚠  {len(res['cambios'])} diferencia(s) con posiciones ({', '.join(tipos)}); "
              f"{res['cambios_nuevos']} nueva(s)")
    if notificador is not None:
        _, fallidos = ripio_sync.notificar_cambios_pendientes(conn, notificador, run_id, reloj())
        if fallidos:
            return ["avisos de Ripio pendientes"]
    return []


# ============================================================
# Corrida principal
# ============================================================

def imprimir_activo(ev: dict) -> None:
    r = ev["resultado"]
    if ev["fila"] is None:
        print(f"  → {r['ticker']:10} {r['estado']}: {r['detalle']}")
        return
    fila = ev["fila"]
    marca = "" if r["estado"] == "valido" else f"  [{r['estado']}]"
    print(f"  → {r['ticker']:10} {fila['señal']} (fuerza {fila['fuerza']:+d}){marca}")


def correr_radar(cfg=None, *, proveedores=None, reloj=ahora_utc, path_db=None,
                 notificador="telegram", integraciones=True, exportar=None,
                 generar_run_id=nuevo_run_id) -> dict:
    """
    Ejecuta una corrida completa y devuelve un resumen
    {"run_id", "estado", "conteos", "problemas"}.

    Parámetros inyectables (tests y demo): proveedores (dict fuente -> función),
    reloj (función -> datetime UTC), path_db, notificador (función texto -> bool,
    "telegram" para el real o None para no notificar) y generar_run_id
    (la demo usa uno determinístico para ser reproducible).
    """
    cfg = cfg or config
    proveedores = proveedores or proveedores_reales(cfg)
    path_db = path_db or os.path.join(cfg.CARPETA_SALIDA, cfg.ARCHIVO_DB)
    exportar = cfg.EXPORTAR_CSVS if exportar is None else exportar
    if notificador == "telegram":
        notificador = None
        if cfg.TELEGRAM_ACTIVO and integraciones:
            import telegram_alertas
            if telegram_alertas.telegram_configurado():
                notificador = telegram_alertas.enviar_mensaje
            else:
                print("  · Telegram activo pero sin credenciales: no se envían alertas "
                      "(quedan pendientes).")

    os.makedirs(cfg.CARPETA_SALIDA, exist_ok=True)
    with db.BloqueoCorrida(path_db), db.abrir(path_db) as conn:
        inicio = reloj()
        run_id = generar_run_id(inicio)
        db.iniciar_corrida(conn, run_id, inicio)
        print(f"\n{'=' * 60}\nRADAR DE SEÑALES — corrida {run_id}\n{'=' * 60}")

        estado, conteos, problemas = "fallida", {}, []
        try:
            evaluaciones = []
            for activo in activos_configurados(cfg):
                ev = evaluar_activo(activo, proveedores[activo.fuente], cfg, run_id, reloj)
                imprimir_activo(ev)
                evaluaciones.append(ev)

            with conn:  # una transacción por corrida para los datos de mercado
                guardar_resultados(conn, evaluaciones, cfg, run_id, reloj())
                borradas = db.aplicar_retencion(conn, cfg.RETENCION_DIAS, reloj())
            if sum(borradas.values()):
                print(f"\n  🧹 Retención: {sum(borradas.values())} fila(s) antiguas borradas")

            conteos = contar_estados(evaluaciones)
            filas = [ev["fila"] for ev in evaluaciones if ev["fila"] is not None]
            imprimir_resumen(conteos, filas)
            if exportar and filas:
                try:
                    exportar_csvs(conn, evaluaciones, cfg)
                except OSError as e:  # ej. CSV abierto en Excel/Power BI
                    print(f"  [!] No se pudieron exportar los CSV ({type(e).__name__}); "
                          "los datos ya están en SQLite")
                    problemas.append("CSV no exportados")

            if integraciones:
                problemas += correr_integraciones(conn, filas, cfg, run_id, notificador, reloj)

            no_validos = conteos["total"] - conteos.get("valido", 0)
            if conteos.get("valido", 0) == 0:
                estado = "fallida"
                problemas.append("ningún activo con datos válidos")
            elif no_validos or problemas:
                estado = "parcial"
            else:
                estado = "completa"
        except Exception as e:
            problemas.append(f"error inesperado ({type(e).__name__})")
            raise
        finally:
            db.finalizar_corrida(conn, run_id, reloj(), estado, conteos,
                                 "; ".join(problemas) or None)
            print(f"\n✔ Corrida {run_id}: {estado}"
                  + (f" — {'; '.join(problemas)}" if problemas else "") + "\n")
    return {"run_id": run_id, "estado": estado, "conteos": conteos, "problemas": problemas}


def correr_integraciones(conn, filas, cfg, run_id, notificador, reloj) -> list:
    problemas = []
    if cfg.TELEGRAM_ACTIVO and notificador is not None:
        try:
            problema = correr_alertas(conn, filas, cfg, run_id, notificador, reloj)
            if problema:
                problemas.append(problema)
        except Exception as e:  # noqa: BLE001 - la corrida sigue; se registra el tipo
            conn.rollback()
            print(f"  [!] Error en alertas ({type(e).__name__}); la corrida sigue")
            problemas.append("error en alertas")
    if cfg.POSICIONES_ACTIVO:
        try:
            problemas += correr_posiciones(conn, filas, cfg, run_id, notificador, reloj)
        except Exception as e:  # noqa: BLE001
            conn.rollback()
            print(f"  [!] Error en posiciones ({type(e).__name__}); la corrida sigue")
            problemas.append("error en posiciones")
    return problemas


def imprimir_resumen(conteos: dict, filas: list) -> None:
    print(f"\n{'=' * 60}\nRESUMEN DE LA CORRIDA\n{'=' * 60}")
    estados = ", ".join(f"{k}: {v}" for k, v in sorted(conteos.items()) if k != "total")
    print(f"  Activos: {conteos['total']} ({estados})")
    if not filas:
        return
    df = pd.DataFrame(filas)
    for señal, cantidad in df.groupby("señal").size().sort_values(ascending=False).items():
        print(f"  {señal}: {cantidad}")
    fuertes = df[df["señal"].isin(SEÑALES_DESTACADAS) & (df["estado_dato"] == "valido")]
    if not fuertes.empty:
        print("\n⚠  Señales destacadas (heurísticas, no son recomendación):")
        for _, r in fuertes.iterrows():
            print(f"  [{r['señal']:18}] {r['ticker']:10} fuerza={r['fuerza']:+d}  {r['motivos']}")


def main(argv=None) -> int:
    configurar_salida_utf8()
    parser = argparse.ArgumentParser(description="Radar de señales técnicas (heurístico).")
    parser.add_argument("--sin-integraciones", action="store_true",
                        help="No ejecuta Telegram, posiciones ni Ripio.")
    args = parser.parse_args(argv)
    try:
        resumen = correr_radar(integraciones=not args.sin_integraciones)
    except db.CorridaEnCurso as e:
        print(f"[!] {e}")
        return 2
    return 0 if resumen["estado"] != "fallida" else 1


if __name__ == "__main__":
    sys.exit(main())

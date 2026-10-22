"""Corrida completa con proveedores sintéticos: run_id, UTC, estados y bloqueo."""

import os
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

import db
import main
from datos_sinteticos import ProveedorSintetico, SerieSintetica, generar_ohlcv
from fuentes.red import ErrorProveedor

AHORA = datetime(2026, 3, 10, 15, 30, tzinfo=timezone.utc)


def _preparar(cfg):
    cfg.CRIPTO = ["ALFAUSDT", "VIEJOUSDT", "CORTOUSDT", "VACIOUSDT", "ROTOUSDT"]
    cfg.ACCIONES_US = ["ACME"]
    series = {
        "ALFAUSDT": generar_ohlcv(SerieSintetica("ALFAUSDT", "binance", "USDT", "1h", 50.0, 0.01, 1),
                                  400, AHORA - timedelta(hours=399)),
        # Velas congeladas hace 30 días (como un par deslistado): dato obsoleto.
        "VIEJOUSDT": generar_ohlcv(SerieSintetica("VIEJOUSDT", "binance", "USDT", "1h", 5.0, 0.01, 2),
                                   300, AHORA - timedelta(days=30, hours=300)),
        "CORTOUSDT": generar_ohlcv(SerieSintetica("CORTOUSDT", "binance", "USDT", "1h", 1.0, 0.01, 3),
                                   30, AHORA - timedelta(hours=29)),
        "ACME": generar_ohlcv(SerieSintetica("ACME", "yahoo", "USD", "1d", 20.0, 0.02, 4,
                                             "America/New_York"), 400, AHORA - timedelta(days=500)),
    }
    reloj = lambda: AHORA  # noqa: E731
    sintetico = ProveedorSintetico(series, reloj)

    def binance(activo):
        if activo.ticker == "ROTOUSDT":
            raise ErrorProveedor("binance", "respuesta de error", 400)
        return sintetico(activo)

    return {"binance": binance, "yahoo": sintetico}, reloj


def _correr(cfg, tmp_path, **kwargs):
    proveedores, reloj = _preparar(cfg)
    path = str(tmp_path / "radar.db")
    resumen = main.correr_radar(cfg, proveedores=proveedores, reloj=reloj, path_db=path,
                                notificador=None, **kwargs)
    return resumen, path


def test_corrida_registra_run_id_unico_y_estado_por_activo(cfg, tmp_path):
    resumen, path = _correr(cfg, tmp_path)
    with db.abrir(path) as conn:
        estados = dict(conn.execute("SELECT ticker, estado FROM resultados_activo"))
        corrida = conn.execute("SELECT run_id, estado, activos_total, activos_validos, "
                               "activos_obsoletos, activos_sin_datos, activos_fallidos "
                               "FROM corridas").fetchone()
        run_ids = {r[0] for r in conn.execute("SELECT run_id FROM senales_historico")}
        run_ids |= {r[0] for r in conn.execute("SELECT DISTINCT run_id FROM precios_ohlcv")}

    assert estados == {"ALFAUSDT": "valido", "VIEJOUSDT": "obsoleto",
                       "CORTOUSDT": "historial_insuficiente", "VACIOUSDT": "sin_datos",
                       "ROTOUSDT": "error_proveedor", "ACME": "valido"}
    assert corrida == (resumen["run_id"], "parcial", 6, 2, 1, 2, 1)
    assert run_ids == {resumen["run_id"]}


def test_timestamps_utc_separados_y_sin_vela_abierta(cfg, tmp_path):
    _, path = _correr(cfg, tmp_path)
    with db.abrir(path) as conn:
        fila = conn.execute("SELECT capturado_utc, generado_utc, vela_utc, vela_original, timeframe, "
                            "moneda, mercado FROM senales_actuales WHERE ticker = 'ALFAUSDT'").fetchone()
        accion = conn.execute("SELECT vela_utc, vela_original FROM senales_actuales "
                              "WHERE ticker = 'ACME'").fetchone()
        ultima_ohlcv = conn.execute("SELECT MAX(timestamp_utc) FROM precios_ohlcv "
                                    "WHERE ticker = 'ALFAUSDT'").fetchone()[0]
    capturado, generado, vela, original, timeframe, moneda, mercado = fila
    assert capturado == "2026-03-10 15:30:00" and generado == "2026-03-10 15:30:00"
    # La vela 15:00-16:00 está abierta a las 15:30: la última cerrada empieza 14:00.
    assert vela == "2026-03-10 14:00:00" and ultima_ohlcv == "2026-03-10 14:00:00"
    assert original == "2026-03-10 14:00:00 (UTC)"
    assert (timeframe, moneda, mercado) == ("1h", "USDT", "Binance spot")
    # Acción: el día 10/03 (hora NY) sigue abierto; se usa la vela del 09/03, conservando la hora local.
    assert accion == ("2026-03-09 04:00:00", "2026-03-09 00:00:00 (America/New_York)")


def test_moneda_inesperada_es_dato_invalido(cfg, tmp_path):
    proveedores, reloj = _preparar(cfg)
    cfg.CRIPTO, cfg.ACCIONES_US = [], ["ACME"]
    original = proveedores["yahoo"]
    proveedores["yahoo"] = lambda a: original(a).assign(moneda="EUR")
    path = str(tmp_path / "radar.db")
    resumen = main.correr_radar(cfg, proveedores=proveedores, reloj=reloj, path_db=path,
                                notificador=None)
    assert resumen["estado"] == "fallida"
    with db.abrir(path) as conn:
        assert conn.execute("SELECT estado, detalle FROM resultados_activo").fetchone() == (
            "dato_invalido", "moneda informada EUR, se esperaba USD")
        assert conn.execute("SELECT COUNT(*) FROM senales_actuales").fetchone()[0] == 0


def test_corridas_sucesivas_tienen_run_id_distinto_y_acumulan_historico(cfg, tmp_path):
    r1, path = _correr(cfg, tmp_path)
    r2, _ = _correr(cfg, tmp_path)
    assert r1["run_id"] != r2["run_id"]
    with db.abrir(path) as conn:
        assert conn.execute("SELECT COUNT(DISTINCT run_id) FROM senales_historico").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM senales_actuales").fetchone()[0] == 4


def test_no_se_puede_correr_mientras_otra_corrida_tiene_la_db(cfg, tmp_path):
    proveedores, reloj = _preparar(cfg)
    path = str(tmp_path / "radar.db")
    with db.BloqueoCorrida(path):
        with pytest.raises(db.CorridaEnCurso):
            main.correr_radar(cfg, proveedores=proveedores, reloj=reloj, path_db=path,
                              notificador=None)


def test_excepcion_inesperada_marca_la_corrida_como_fallida(cfg, tmp_path, monkeypatch):
    proveedores, reloj = _preparar(cfg)
    path = str(tmp_path / "radar.db")
    monkeypatch.setattr(main, "guardar_resultados", lambda *a: (_ for _ in ()).throw(KeyError("x")))
    with pytest.raises(KeyError):
        main.correr_radar(cfg, proveedores=proveedores, reloj=reloj, path_db=path, notificador=None)
    with db.abrir(path) as conn:
        assert conn.execute("SELECT estado, detalle FROM corridas").fetchone() == (
            "fallida", "error inesperado (KeyError)")


def test_alertas_solo_con_datos_validos_y_exportacion_csv(cfg, tmp_path, notificador_factory):
    cfg.TELEGRAM_ACTIVO = True
    cfg.EXPORTAR_CSVS = True
    notificador = notificador_factory([True] * 5)
    proveedores, reloj = _preparar(cfg)
    path = str(tmp_path / "radar.db")
    main.correr_radar(cfg, proveedores=proveedores, reloj=reloj, path_db=path,
                      notificador=notificador)
    for texto in notificador.mensajes:
        assert "VIEJOUSDT" not in texto  # obsoleto: nunca se alerta
    señales = pd.read_csv(os.path.join(cfg.CARPETA_SALIDA, cfg.ARCHIVO_SEÑALES))
    assert {"run_id", "vela_utc", "estado_dato"} <= set(señales.columns)


def test_flujo_completo_con_posiciones_y_ripio_simulados(cfg, tmp_path, monkeypatch,
                                                         notificador_factory):
    import ripio_api
    cfg.POSICIONES_ACTIVO = True
    cfg.RIPIO_ACTIVO = True
    cfg.TELEGRAM_ACTIVO = True
    proveedores, reloj = _preparar(cfg)
    os.makedirs(cfg.CARPETA_SALIDA, exist_ok=True)
    # Posición FICTICIA con un stop loss que el precio sintético ya perforó.
    with open(os.path.join(cfg.CARPETA_SALIDA, cfg.ARCHIVO_POSICIONES), "w", encoding="utf-8") as f:
        f.write("ticker,fecha_compra,precio_compra,cantidad,stop_loss_pct,take_profit_pct,trailing_pct,notas\n"
                "ALFAUSDT,2026-01-02,1000,1,5,,,ficticia\n")
    monkeypatch.setattr(ripio_api, "credenciales_configuradas", lambda: True)
    monkeypatch.setattr(ripio_api, "obtener_balance_wallet",
                        lambda: {"wallet": [{"currency": "BTC", "amount": "0.5", "locked_amount": "0"}]})
    notificador = notificador_factory([True] * 20)
    path = str(tmp_path / "radar.db")
    for _ in range(2):
        main.correr_radar(cfg, proveedores=proveedores, reloj=reloj, path_db=path,
                          notificador=notificador)
    with db.abrir(path) as conn:
        assert conn.execute("SELECT COUNT(*), SUM(notificado) FROM eventos_posicion").fetchone() == (1, 1)
        assert conn.execute("SELECT COUNT(*), SUM(notificado) FROM ripio_cambios_pendientes").fetchone() == (1, 1)
        assert conn.execute("SELECT estado FROM posiciones").fetchone()[0] == "abierta"
    avisos = [m for m in notificador.mensajes if "STOP LOSS" in m or "RIPIO" in m]
    assert len(avisos) == 2

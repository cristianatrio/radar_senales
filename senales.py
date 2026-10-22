"""
Motor de señales (versión 2 - mejorada).
Combina indicadores en una señal final con sistema de puntajes Y reglas de veto.

Mejoras vs v1:
- Las señales contradictorias (ej: ruptura de máximos pero RSI 82) se vetan
  en lugar de cancelarse a medias.
- RSI extremo (>80 o <20) no se interpreta como confirmación sino como agotamiento.
- Cuando la fuerza viene mayoritariamente de un solo indicador, se reduce
  para evitar falsas señales fuertes.

Qué es `fuerza`: un puntaje entero entre -9 y +9 que suma familias de
indicadores (RSI, MACD, medias, rupturas). NO es una probabilidad ni una
expectativa de retorno; no fue calibrado contra resultados. Ver docs/SENALES.md
y el backtest (backtest.py) para su evaluación fuera de muestra.

IMPORTANTE: esto es un radar heurístico, no recomendación de inversión.
"""

import pandas as pd
from indicadores import detectar_ruptura, velas_minimas

SEÑALES_POSIBLES = (
    "COMPRA_FUERTE", "COMPRA_PROBABLE", "ESPERAR", "VENTA_PROBABLE",
    "VENTA_FUERTE", "RIESGO_ALTO", "SIN_DATOS",
)


def generar_señal(df: pd.DataFrame, config) -> dict:
    """
    Analiza el último estado del DataFrame con indicadores ya calculados.
    Devuelve dict con señal, fuerza y motivos.
    """
    minimo = velas_minimas(config)
    if df.empty or len(df) < minimo:
        return _resultado_vacio(f"Historial insuficiente ({len(df)} velas cerradas, "
                                f"se requieren {minimo})")

    ultimo = df.iloc[-1]
    anterior = df.iloc[-2] if len(df) >= 2 else ultimo

    rsi = ultimo["rsi"]
    macd = ultimo["macd"]
    macd_señal = ultimo["macd_señal"]
    macd_hist = ultimo["macd_hist"]
    macd_hist_prev = anterior["macd_hist"]
    close = ultimo["close"]
    ma_corta = ultimo[f"ma_{config.MA_CORTA}"]
    ma_larga = ultimo[f"ma_{config.MA_LARGA}"]
    vol_rel = ultimo["vol_relativo"]

    ruptura = detectar_ruptura(df, periodo=20)

    # =====================================================
    # PUNTAJE PARCIAL POR FAMILIA DE INDICADORES
    # =====================================================
    # Cada familia aporta entre -3 y +3 al score total.
    # Esto evita que una sola señal infle artificialmente la fuerza.

    score_rsi = 0
    score_macd = 0
    score_tendencia = 0
    score_ruptura = 0
    motivos = []

    # --- RSI ---
    if pd.notna(rsi):
        if rsi > config.RSI_SOBRECOMPRA_EXTREMA:
            score_rsi = -3
            motivos.append(f"RSI sobrecompra extrema ({rsi:.0f})")
        elif rsi < config.RSI_SOBREVENTA_EXTREMA:
            score_rsi = +3
            motivos.append(f"RSI sobreventa extrema ({rsi:.0f})")
        elif rsi > config.RSI_SOBRECOMPRA:
            score_rsi = -2
            motivos.append(f"RSI sobrecomprado ({rsi:.0f})")
        elif rsi < config.RSI_SOBREVENTA:
            score_rsi = +2
            motivos.append(f"RSI sobrevendido ({rsi:.0f})")
        elif rsi < 40:
            score_rsi = +1
        elif rsi > 60:
            score_rsi = -1

    # --- MACD ---
    if pd.notna(macd) and pd.notna(macd_señal) and pd.notna(macd_hist) and pd.notna(macd_hist_prev):
        if macd_hist_prev <= 0 and macd_hist > 0:
            score_macd = +2
            motivos.append("MACD cruzó al alza")
        elif macd_hist_prev >= 0 and macd_hist < 0:
            score_macd = -2
            motivos.append("MACD cruzó a la baja")
        elif macd > macd_señal:
            score_macd = +1
        elif macd < macd_señal:
            score_macd = -1
        # empate exacto (ej. precio sin cambios): 0, no se cuenta como bajista

    # --- Medias móviles (tendencia) ---
    if pd.notna(ma_corta) and pd.notna(ma_larga):
        if close > ma_corta > ma_larga:
            score_tendencia = +2
            motivos.append(f"Precio sobre MA{config.MA_CORTA} y MA{config.MA_LARGA}")
        elif close < ma_corta < ma_larga:
            score_tendencia = -2
            motivos.append(f"Precio bajo MA{config.MA_CORTA} y MA{config.MA_LARGA}")
        elif close > ma_larga:
            score_tendencia = +1
        elif close < ma_larga:
            score_tendencia = -1
        # precio igual a la MA larga: 0 (antes contaba como bajista)

    # --- Rupturas con/sin volumen ---
    volumen_alto = pd.notna(vol_rel) and vol_rel > 1.5

    if ruptura["ruptura_max"]:
        score_ruptura = +2 if volumen_alto else +1
        nota = "Ruptura de máximo de 20"
        if volumen_alto:
            nota += f" con volumen ({vol_rel:.1f}x)"
        motivos.append(nota)
    elif ruptura["ruptura_min"]:
        score_ruptura = -2 if volumen_alto else -1
        nota = "Ruptura de mínimo de 20"
        if volumen_alto:
            nota += f" con volumen ({vol_rel:.1f}x)"
        motivos.append(nota)

    score_total = score_rsi + score_macd + score_tendencia + score_ruptura

    # =====================================================
    # REGLAS DE VETO (las novedades v2)
    # =====================================================
    # Si el RSI está en extremo opuesto, vetamos la señal aunque la fuerza
    # apunte para el otro lado. Esto evita cosas como "Compra Fuerte con RSI 82".

    if score_total > 0 and pd.notna(rsi) and rsi > config.RSI_SOBRECOMPRA_EXTREMA:
        # Quería ser compra, pero RSI extremo dice "ya subió mucho"
        score_total = min(score_total, 0)  # cap al neutral
        motivos.append("⚠️ Veto: compra cancelada por RSI sobrecompra extrema")

    if score_total < 0 and pd.notna(rsi) and rsi < config.RSI_SOBREVENTA_EXTREMA:
        # Quería ser venta, pero RSI extremo dice "ya cayó mucho"
        score_total = max(score_total, 0)
        motivos.append("⚠️ Veto: venta cancelada por RSI sobreventa extrema")

    # =====================================================
    # PENALIZACIÓN POR FUERZA CONCENTRADA
    # =====================================================
    # Si la fuerza viene 100% de un solo indicador, es menos confiable.
    # Para ser COMPRA_FUERTE / VENTA_FUERTE, queremos al menos 2 familias
    # apuntando en la misma dirección.

    señales_alcistas = sum(1 for s in [score_rsi, score_macd, score_tendencia, score_ruptura] if s > 0)
    señales_bajistas = sum(1 for s in [score_rsi, score_macd, score_tendencia, score_ruptura] if s < 0)

    if abs(score_total) >= 4:
        if score_total > 0 and señales_alcistas < 2:
            score_total = 3  # bajamos a "probable" en lugar de "fuerte"
            motivos.append("Fuerza reducida: viene de un solo indicador")
        elif score_total < 0 and señales_bajistas < 2:
            score_total = -3
            motivos.append("Fuerza reducida: viene de un solo indicador")

    # =====================================================
    # TRADUCCIÓN A SEÑAL FINAL
    # =====================================================
    if score_total >= 4:
        señal = "COMPRA_FUERTE"
    elif score_total >= 2:
        señal = "COMPRA_PROBABLE"
    elif score_total <= -4:
        señal = "VENTA_FUERTE"
    elif score_total <= -2:
        señal = "VENTA_PROBABLE"
    else:
        señal = "ESPERAR"

    # Caso especial: volatilidad muy alta sin dirección clara
    if volumen_alto and (ruptura["ruptura_max"] or ruptura["ruptura_min"]):
        if abs(score_total) < 3:
            señal = "RIESGO_ALTO"

    return {
        "señal": señal,
        "fuerza": score_total,
        "motivos": " | ".join(motivos) if motivos else "Sin condiciones destacadas",
        "rsi": round(rsi, 2) if pd.notna(rsi) else None,
        "macd_hist": round(macd_hist, 4) if pd.notna(macd_hist) else None,
        "vol_relativo": round(vol_rel, 2) if pd.notna(vol_rel) else None,
        "precio": round(close, 4),
        "ma_corta": round(ma_corta, 4) if pd.notna(ma_corta) else None,
        "ma_larga": round(ma_larga, 4) if pd.notna(ma_larga) else None,
    }


def _resultado_vacio(motivo: str) -> dict:
    return {
        "señal": "SIN_DATOS",
        "fuerza": 0,
        "motivos": motivo,
        "rsi": None,
        "macd_hist": None,
        "vol_relativo": None,
        "precio": None,
        "ma_corta": None,
        "ma_larga": None,
    }

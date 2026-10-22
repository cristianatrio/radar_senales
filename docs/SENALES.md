# Qué activa cada señal (y qué NO significa)

> Las señales son **heurísticas**: reglas fijas sobre indicadores técnicos clásicos.
> No son recomendaciones de inversión, no predicen precios y `fuerza` **no es una
> probabilidad**. El backtest (`backtest.py`) existe para medir — fuera de muestra y con
> costos — si estas reglas aportan algo; con los datos disponibles no hay evidencia de
> rentabilidad.

## Datos de entrada

- Solo **velas cerradas** y validadas (precios finitos y positivos, `high`/`low`
  coherentes, sin timestamps duplicados). La vela en curso se descarta.
- Se requieren al menos **50 velas cerradas** (MA50); con menos, la señal es `SIN_DATOS`
  y el activo queda como `historial_insuficiente`.
- Cripto: pares de Binance contra USDT, velas de 1 h, 24/7.
- Acciones: Yahoo Finance, velas de 1 d, precios ajustados por splits y dividendos.
  La vela diaria se considera cerrada a la medianoche local siguiente (criterio
  conservador: la señal del día aparece con hasta ~8 h de demora tras el cierre).
- Si el último cierre es más viejo que `MAX_ANTIGUEDAD_HORAS` (3 h en 1h, 120 h en 1d)
  el dato es `obsoleto`: la señal se guarda marcada y **no se alerta**.

## Puntaje por familia

| Familia | Condición (vela t) | Puntos |
|---|---|---:|
| RSI(14) Wilder | > 80 (sobrecompra extrema) | −3 |
| | < 20 (sobreventa extrema) | +3 |
| | > 70 | −2 |
| | < 30 | +2 |
| | 30–40 | +1 |
| | 60–70 | −1 |
| MACD(12, 26, 9) | histograma cruza de ≤ 0 a > 0 | +2 |
| | histograma cruza de ≥ 0 a < 0 | −2 |
| | MACD > señal / MACD < señal / empate | +1 / −1 / 0 |
| Tendencia (MA20, MA50) | cierre > MA20 > MA50 | +2 |
| | cierre < MA20 < MA50 | −2 |
| | cierre > MA50 / cierre < MA50 / igual | +1 / −1 / 0 |
| Ruptura (20 velas previas) | cierre > máximo previo | +1 (+2 si volumen relativo > 1.5) |
| | cierre < mínimo previo | −1 (−2 si volumen relativo > 1.5) |

- `fuerza` = suma de las cuatro familias (rango −9 a +9).
- Volumen relativo = volumen de la vela / promedio de las **20 velas anteriores** (la vela
  actual no entra en su propio promedio).
- Un indicador sin dato (calentamiento) aporta 0.

## Reglas posteriores

1. **Veto por RSI extremo:** si la fuerza es positiva con RSI > 80, se lleva a 0; si es
   negativa con RSI < 20, se lleva a 0.
2. **Fuerza concentrada:** si |fuerza| ≥ 4 pero menos de dos familias apuntan en esa
   dirección, se recorta a ±3.
3. **Etiqueta:** ≥ 4 `COMPRA_FUERTE`; 2–3 `COMPRA_PROBABLE`; −1 a 1 `ESPERAR`;
   −3 a −2 `VENTA_PROBABLE`; ≤ −4 `VENTA_FUERTE`.
4. **`RIESGO_ALTO`:** ruptura con volumen alto y |fuerza| < 3 (movimiento fuerte sin
   dirección clara). Reemplaza a la etiqueta anterior.

## Falsos positivos y límites conocidos

- **Mezcla de lógicas opuestas:** RSI puntúa reversión a la media (sobreventa = alcista) y
  tendencia/rupturas puntúan continuidad. En tendencias fuertes se cancelan y la señal
  queda en `ESPERAR`; en rangos laterales, las rupturas fallidas generan compras/ventas que
  se revierten.
- **Mismos umbrales para todo:** cripto 1h, acciones de EE. UU. y acciones argentinas
  tienen volatilidad, liquidez y horarios distintos; los umbrales no están calibrados por
  clase de activo.
- **Inflación en ARS:** los precios nominales en pesos tienden a subir por inflación y
  devaluación, lo que sesga la familia de tendencia hacia "alcista" en acciones `.BA`.
- **Baja liquidez:** en papeles poco operados, un único trade grande mueve el cierre y el
  volumen relativo (rupturas "con volumen" poco confiables).
- **Precios ajustados:** el histórico de acciones está ajustado; los precios viejos no
  coinciden con lo que se veía en pantalla en ese momento.
- **Fuente no oficial:** Yahoo Finance puede tener demoras, huecos o correcciones
  retroactivas.
- **Sin calibración:** no hay evidencia de que una fuerza +4 sea "más probable" que una +2.

## Aviso

Este proyecto es una herramienta de monitoreo y aprendizaje. No es asesoramiento
financiero, no ejecuta órdenes y no debe usarse para operar sin criterio propio.

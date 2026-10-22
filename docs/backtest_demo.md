# Backtest de señales del radar

**Origen de datos:** datos SINTÉTICOS generados con semilla fija (no representan mercados reales)

> **Aviso:** resultados históricos/simulados con supuestos de costos. No son una promesa de rentabilidad ni una recomendación. `fuerza` es un puntaje heurístico, no una probabilidad. Los datos sintéticos solo validan la mecánica del backtest.

Reglas: señal al cierre de t, ejecución en la apertura de t+1; long-only; costos por lado según tipo de activo; partición cronológica 60/20/20; parámetros elegidos solo en train; test = fuera de muestra. `regla_radar` = entrar con fuerza ≥ 2 (sin RIESGO_ALTO) y salir con fuerza ≤ −2, sin optimizar.

## cripto 1h

### Train (selección de parámetros) — promedio entre 3 activos

| Regla | Retorno medio | Drawdown medio | Operaciones | Exposición | Activos > comprar y mantener |
|---|---:|---:|---:|---:|---:|
| regla_radar | +26.7% | -26.0% | 132 | 50% | 2/3 |
| regla_elegida | +36.7% | -20.5% | 155 | 41% | 2/3 |
| comprar_y_mantener | -14.8% | -50.3% | 3 | 100% | — |

### Validación — promedio entre 3 activos

| Regla | Retorno medio | Drawdown medio | Operaciones | Exposición | Activos > comprar y mantener |
|---|---:|---:|---:|---:|---:|
| regla_radar | +2.9% | -17.9% | 48 | 50% | 3/3 |
| regla_elegida | -4.1% | -21.3% | 66 | 42% | 2/3 |
| comprar_y_mantener | -4.6% | -28.1% | 3 | 100% | — |

### Test (fuera de muestra) — promedio entre 3 activos

| Regla | Retorno medio | Drawdown medio | Operaciones | Exposición | Activos > comprar y mantener |
|---|---:|---:|---:|---:|---:|
| regla_radar | -10.9% | -23.1% | 47 | 46% | 3/3 |
| regla_elegida | -9.7% | -19.6% | 63 | 33% | 3/3 |
| comprar_y_mantener | -24.8% | -38.1% | 3 | 100% | — |

### Detalle por activo (test)

| Activo | Velas | Huecos | Parámetros (train) | Retorno radar | Acierto | Ops | Retorno elegida | Comprar y mantener | DD radar |
|---|---:|---:|---|---:|---:|---:|---:|---:|---:|
| ALFAUSDT | 4000 | 0 | entrada≥3, salida≤-2 | -18.8% | 31% | 16 | -5.9% | -30.2% | -22.5% |
| BETAUSDT | 4000 | 0 | entrada≥2, salida≤-2 | -16.7% | 19% | 16 | -16.7% | -29.9% | -31.8% |
| GAMAUSDT | 4000 | 0 | entrada≥2, salida≤0 | +2.8% | 47% | 15 | -6.5% | -14.2% | -14.9% |

## acciones 1d

### Train (selección de parámetros) — promedio entre 3 activos

| Regla | Retorno medio | Drawdown medio | Operaciones | Exposición | Activos > comprar y mantener |
|---|---:|---:|---:|---:|---:|
| regla_radar | -12.5% | -45.3% | 41 | 52% | 1/3 |
| regla_elegida | +41.8% | -20.4% | 17 | 20% | 3/3 |
| comprar_y_mantener | -20.8% | -58.9% | 3 | 100% | — |

### Validación — promedio entre 3 activos

| Regla | Retorno medio | Drawdown medio | Operaciones | Exposición | Activos > comprar y mantener |
|---|---:|---:|---:|---:|---:|
| regla_radar | +16.0% | -17.1% | 12 | 50% | 2/3 |
| regla_elegida | +20.9% | -12.1% | 9 | 32% | 3/3 |
| comprar_y_mantener | -2.0% | -34.7% | 3 | 100% | — |

### Test (fuera de muestra) — promedio entre 3 activos

| Regla | Retorno medio | Drawdown medio | Operaciones | Exposición | Activos > comprar y mantener |
|---|---:|---:|---:|---:|---:|
| regla_radar | -11.0% | -23.5% | 13 | 33% | 3/3 |
| regla_elegida | -5.7% | -13.1% | 7 | 13% | 3/3 |
| comprar_y_mantener | -32.4% | -41.9% | 3 | 100% | — |

### Detalle por activo (test)

| Activo | Velas | Huecos | Parámetros (train) | Retorno radar | Acierto | Ops | Retorno elegida | Comprar y mantener | DD radar |
|---|---:|---:|---|---:|---:|---:|---:|---:|---:|
| ACME | 1200 | 0 | entrada≥4, salida≤-2 | +12.1% | 33% | 3 | +9.9% | -12.9% | -8.3% |
| ANDES.BA | 1200 | 0 | entrada≥4, salida≤0 | -33.3% | 0% | 7 | -17.2% | -45.1% | -36.7% |
| GLOBX | 1200 | 0 | entrada≥4, salida≤-2 | -11.7% | 33% | 3 | -9.8% | -39.1% | -25.5% |

## Límites

- Pocas operaciones por segmento implican mucha incertidumbre: no hay test estadístico de significancia.
- Superar a comprar y mantener cuando el mercado cae puede deberse solo a estar menos tiempo expuesto, no a capacidad predictiva: compará también exposición y drawdown.
- Si `regla_elegida` rinde mejor en train que en validación/test, es sobreajuste: la selección se hizo solo en train justamente para poder verlo.
- Costos fijos supuestos; no modela libro de órdenes, gaps extremos, impuestos ni dividendos en efectivo.
- Acciones argentinas: retornos NOMINALES en ARS (incluyen inflación/devaluación); comparalos solo contra su propio comprar y mantener.
- Cripto opera 24/7 en USDT; las acciones solo en días hábiles (la apertura de t+1 incluye el gap nocturno).
- Indicadores calculados sobre toda la historia previa a t (el radar usa las últimas ~200 velas; tras ~100 velas la diferencia de inicialización de RSI/EMA es despreciable).
- Con datos del radar (`--db`) la historia puede tener huecos (PC apagada, fallos de proveedor) y precios no ajustados en filas antiguas.

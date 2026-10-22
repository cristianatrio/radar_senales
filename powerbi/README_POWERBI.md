# Power BI — modelo estrella, medidas y guía de armado

> **Estado de validación (22 de octubre de 2026):** el proyecto `demo_publica/RadarDemo.pbip`
> (modelo TMDL + informe PBIR generado desde `demo_publica/gen_report.py`) se abrió en Power BI
> Desktop 2.159 con los CSV sintéticos; sus 88 medidas (10 de ellas, versiones en inglés de las que producen
> texto) se evaluaron contra el motor local sin errores
> y, sin filtros, devuelven los valores de `valores_esperados.md`. El informe tiene cuatro páginas con
> navegación, panel de filtros, lecturas en texto derivadas de medidas y selector de activo sincronizado
> entre Señales y Mercado; cada página existe en español y en inglés (botón EN/ES). `medidas.dax` se exporta del TMDL con
> `demo_publica/exportar_medidas.py` (las 23 medidas de esta guía más las complementarias).
> Ver [demo_publica/README.md](demo_publica/README.md) para el detalle, las capturas y los límites.
> Los bloques de `consultas_powerquery.pq` y `medidas.dax` siguen siendo la referencia para armar
> el informe a mano.

El PBIX original (`Power bi analisis.pbix`) **no se modificó**: tiene un modelo
embebido con datos reales que no se puede sanear con certeza sin Desktop. Ver
[Qué revisar en el PBIX privado](#qué-revisar-en-el-pbix-privado).

## 1. Origen de datos

| Uso | Carpeta de CSV | Cómo se genera | ¿Publicable? |
|---|---|---|---|
| Demo pública | `powerbi/datos_demo/` | `python demo/generar_demo.py` | Sí: 100% sintético (`dim_activo[es_sintetico] = TRUE`) |
| Uso personal | `output/powerbi/` | `python main.py` y luego `python exportar_powerbi.py` | **No** (`output/` está en `.gitignore`) |

`MANIFIESTO.txt` lista el SHA-256 y la cantidad de filas de cada CSV: la demo es
reproducible (mismas semillas → mismos hashes).

El exportador **nunca** incluye `posiciones`, `eventos_posicion`, `ripio_*` ni
`alertas_*`. Una página de cartera solo puede existir en un PBIX privado aparte,
conectado a la DB local, y nunca en la copia pública.

## 2. Modelo estrella

```
                dim_fecha[fecha]        dim_senal[señal]
                  │   │   │                    │
                  ▼   ▼   ▼                    ▼
dim_activo ──► fact_senales ◄──────────── (señal)
  [ticker] ──► fact_precios
  [ticker] ──► fact_resultados_activo ◄── dim_corrida[run_id] ──► fact_senales
```

Relaciones (todas *muchos a uno*, filtro en **una** dirección, de la dimensión al hecho):

| Desde (hecho) | Hacia (dimensión) |
|---|---|
| `fact_senales[ticker]` | `dim_activo[ticker]` |
| `fact_precios[ticker]` | `dim_activo[ticker]` |
| `fact_resultados_activo[ticker]` | `dim_activo[ticker]` |
| `fact_senales[fecha]` | `dim_fecha[fecha]` |
| `fact_precios[fecha]` | `dim_fecha[fecha]` |
| `fact_resultados_activo[fecha]` | `dim_fecha[fecha]` |
| `fact_senales[señal]` | `dim_senal[señal]` |
| `fact_senales[run_id]` | `dim_corrida[run_id]` |
| `fact_resultados_activo[run_id]` | `dim_corrida[run_id]` |

- **No** relacionar tablas de hechos entre sí (ni `fact_precios` con `fact_senales`).
- Marcar `dim_fecha` como tabla de fechas (columna `fecha`).
- Ordenar `dim_senal[señal]` por `dim_senal[orden]`.
- Desactivar la autodetección de relaciones y la "fecha/hora automática".
- `fecha` en los hechos es la fecha UTC de la vela (`vela_utc`/`timestamp_utc`).
  El timestamp original del mercado se conserva en `fact_precios[timestamp_original]`.

Granos: `fact_senales` = una fila por activo y corrida; `fact_precios` = una fila por
vela cerrada; `fact_resultados_activo` = resultado de cada activo en cada corrida
(`valido`, `obsoleto`, `sin_datos`, `historial_insuficiente`, `error_proveedor`,
`dato_invalido`).

## 3. Pasos en Power BI Desktop

1. Crear el parámetro `CarpetaDatos` y las consultas de `consultas_powerquery.pq`
   (los tipos se aplican con cultura `en-US`: los CSV usan punto decimal).
2. Crear las relaciones de la tabla anterior.
3. Crear la tabla `_Medidas` y pegar `medidas.dax`. Ocultar columnas técnicas
   (`id`, `es_ultima`, `es_ultima_vela`, `cambio_senal`) para evitar sumas implícitas.
4. Poner **Resumir por: No resumir** en `rsi`, `fuerza`, `precio`, `close` y
   `vol_relativo` (evita que vuelva a aparecer un "Suma de rsi").
5. Importar `tema_accesible.json` (Vista → Temas → Buscar temas).
6. Armar las páginas (sección 4) y comparar con `valores_esperados.md` sin filtros.

## 4. Páginas sugeridas (lienzo 1280 × 720, márgenes de 16 px, sin superposiciones)

**Resumen**
- Fila superior de tarjetas: `Activos con señal actual`, `Compras actuales`,
  `Ventas actuales`, `Esperar actuales`, `Estado de actualización`,
  `Última actualización (UTC)`, `Estado última corrida`, `Activos con problema (última corrida)`.
- Barras: eje `dim_senal[señal]` (orden por `orden`), valor `Activos con señal actual`,
  etiqueta de datos con `dim_senal[simbolo]` (no depender solo del color).
- Texto fijo: "Señales heurísticas. `fuerza` es un puntaje, no una probabilidad. No es
  recomendación de inversión."

**Señales** (foto actual)
- Tabla con `dim_activo[ticker]`, `tipo`, `instrumento`, `mercado`, `moneda`,
  `timeframe`, `Símbolo señal actual`, `RSI última vela`, `Último cierre`, y desde
  `fact_senales` (filtrada a `es_ultima = TRUE`) `fuerza`, `vela_utc`, `estado_dato`, `motivos`.
- Segmentadores: `dim_activo[tipo]`, `dim_activo[fuente]`, `dim_activo[timeframe]`, `dim_senal[señal]`.

**Mercado** (historia)
- Segmentadores: `dim_fecha[fecha]` (entre), `dim_activo[ticker]` (selección única),
  `tipo`, `fuente`, `timeframe`.
- Líneas: eje `fact_precios[timestamp_utc]`, valores `Cierre (vela)`, `ma_corta`, `ma_larga`
  (sin resumir). RSI en un gráfico aparte con `RSI (vela)` y líneas de referencia 30 / 70.
- Columnas apiladas: eje `dim_fecha[fecha]`, leyenda `dim_senal[señal]`, valor
  `Activos con la señal en el período`; tarjeta con `Cambios de señal`.

**Calidad de datos**
- Columnas apiladas: eje `dim_fecha[fecha]`, leyenda `fact_resultados_activo[estado]`, valor
  recuento de filas; tarjeta `Tasa de datos válidos`; tabla de la última corrida con
  `ticker`, `estado`, `detalle`.

Accesibilidad: contraste de texto ≥ 4.5:1 (el tema usa azul `#0072B2` y naranja oscuro
`#B34700`, ambos > 5:1 sobre blanco), símbolos ▲ ▼ ■ ⚠ ∅ junto a cada señal, títulos
explícitos en todas las visuales, texto alternativo en cada visual, orden de tabulación
de arriba hacia abajo y de izquierda a derecha.

## 5. Actualización (Desktop / Service)

- **Desktop:** correr `python main.py` (o `demo/generar_demo.py`) y luego
  `python exportar_powerbi.py`; después *Actualizar* en Power BI.
- **Service:** los CSV son archivos locales: requieren una **puerta de enlace de datos
  local** (modo personal alcanza) con acceso a la carpeta, y una actualización programada
  posterior a la tarea del radar. Alternativa sin gateway: subir los CSV a OneDrive/SharePoint
  y usar el conector correspondiente (solo para la demo sintética).
- La medida `Estado de actualización` compara contra `UTCNOW()`: la demo sintética
  (enero de 2026) aparece intencionalmente como "Desactualizado".
- Alternativa ODBC directa a SQLite: posible, pero requiere el driver en cada máquina y
  la DB local; no se recomienda para la copia pública.

## Qué revisar en el PBIX privado

`Power bi analisis.pbix` contiene un `DataModel` embebido (≈ 694 KB) que no se puede
inspeccionar sin Power BI Desktop. **No publicarlo.** Antes de reutilizarlo:

1. Abrirlo en Desktop y revisar en *Vista de modelo* todas las tablas (incluidas las
   ocultas): si aparecen `posiciones`, `eventos_posicion`, `ripio_*` o `alertas_*`,
   el archivo contiene datos personales.
2. *Transformar datos → Configuración de origen de datos*: anotar las rutas (pueden
   incluir tu usuario de Windows) y credenciales guardadas.
3. Visual de tabla con `Sum(precios_ohlcv.rsi)`: suma el RSI de todas las velas del
   ticker (valores sin sentido). Reemplazar por `senales_actuales[rsi]` sin resumir o por
   una medida `IF(HASONEVALUE(senales_actuales[ticker]), MAX(senales_actuales[rsi]))`.
4. Tarjetas `Compras`, `Ventas` y `Esperar` (definidas en la tabla `precios_ohlcv`):
   abrir su DAX y confirmar que cuentan **tickers distintos de `senales_actuales`**, por
   ejemplo `CALCULATE(DISTINCTCOUNT(senales_actuales[ticker]), senales_actuales[señal] IN {"COMPRA_FUERTE","COMPRA_PROBABLE"})`.
   Si usan `COUNTROWS(precios_ohlcv)` cuentan velas, no activos.
5. Revisar relaciones `senales_actuales` ↔ `precios_ohlcv` (relación entre hechos) y
   reemplazarlas por el modelo estrella de esta guía.
6. Corregir superposiciones: según las coordenadas del layout, la tarjeta `Compras`
   (x 9–151) se superpone con `Ventas` (x 133–255), y `Ventas`/`Esperar` invaden el
   gráfico de columnas (y ≥ 248). Agregar títulos a las dos tablas (hoy solo el gráfico
   tiene título explícito) y aprovechar el ancho libre a la derecha del lienzo.
7. Para un informe público: crear un PBIX **nuevo** desde `powerbi/datos_demo/`, no una copia
   del privado (ocultar páginas o columnas no elimina los datos del archivo).

# Radar de Señales

[![CI](https://img.shields.io/badge/CI-GitHub%20Actions-2088FF?logo=githubactions&logoColor=white)](.github/workflows/ci.yml)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![Power BI PBIP](https://img.shields.io/badge/Power%20BI-PBIP%20%2B%20TMDL-F2C811)
![ES / EN](https://img.shields.io/badge/informe-ES%20%2F%20EN-4F46E5)
[![Licencia MIT](https://img.shields.io/badge/licencia-MIT-green)](LICENSE)

**Convierte RSI, MACD, medias y volumen en una señal clara por activo y la explica en palabras
simples**, en un informe Power BI bilingüe que se genera desde código.

Radar técnico **heurístico** para cripto (Binance, 1 h) y acciones de Argentina y EE. UU.
(Yahoo Finance, 1 d): descarga velas, valida los datos, calcula indicadores clásicos, etiqueta
cada activo con una señal de compra, espera o venta y guarda todo en SQLite con trazabilidad por
corrida. Incluye un backtest sin información futura, una demo 100 % sintética y reproducible, y
un proyecto Power BI (PBIP) con modelo estrella, 88 medidas DAX y seis páginas en español e inglés.

[![Informe Power BI de la demo: portada](powerbi/demo_publica/capturas/inicio.png)](powerbi/demo_publica/README.md)

*Portada del informe de la demo sintética. [Más capturas y detalle →](powerbi/demo_publica/README.md)*

| Qué muestra | Cómo está hecho |
|---|---|
| Una fila por activo con su señal, fuerza (−9 a +9), RSI, precio y una **ficha en lenguaje cotidiano** que traduce los motivos técnicos («el precio está por encima de su promedio de las últimas 20 y 50 velas»). | Pipeline Python con reintentos, validación de velas, migraciones de SQLite y bloqueo por corrida; **128 tests offline** (la red está bloqueada) y CI en Ubuntu y Windows. |
| Evolución de cada activo con medias y RSI con zonas sombreadas, calidad del dato por fuente y una guía de lectura con glosario. | Informe **generado desde código** (`gen_report.py`): layout en cuadrícula, tema, marcadores y las doce páginas salen de un diccionario; validado contra el motor de Power BI y con capturas automatizadas. |
| Qué tan confiable es cada dato: activos desactualizados, errores de proveedor y horas sin dato nuevo. | **Sin secretos ni datos personales**: credenciales por variables de entorno, claves de solo lectura, datos reales fuera del repo y tests que lo verifican ([SECURITY.md](SECURITY.md)). |

> **No es un bot de trading ni asesoramiento financiero.** No ejecuta órdenes. Las
> señales son reglas fijas; `fuerza` es un puntaje, **no una probabilidad**. No hay
> evidencia de que generen rentabilidad: el backtest está para medirlo con honestidad.

## Contenido

- [Arquitectura](#arquitectura)
- [Activos, mercados y monedas](#activos-mercados-y-monedas)
- [Instalación reproducible](#instalación-reproducible)
- [Demo segura (sin credenciales)](#demo-segura-sin-credenciales)
- [Uso con datos reales](#uso-con-datos-reales)
- [Configuración segura](#configuración-segura)
- [Datos, corridas y calidad](#datos-corridas-y-calidad)
- [Señales y backtest](#señales-y-backtest)
- [Power BI](#power-bi)
- [Tests y CI](#tests-y-ci)
- [Seguridad](#seguridad)
- [Limitaciones](#limitaciones)
- [Migración desde la versión anterior](#migración-desde-la-versión-anterior)

## Arquitectura

```
 fuentes/binance_api.py ─┐   fuentes/red.py: timeout, reintentos con backoff,
 fuentes/yahoo_api.py ───┤   rate limit y errores redactados (ErrorProveedor)
                         ▼
        fuentes/normalizacion.py  → esquema OHLCV común, UTC + timestamp original,
                         │          validación, descarte de la vela abierta
                         ▼
 indicadores.py → senales.py      → puntaje por familias + etiqueta heurística
                         │
                         ▼
 main.py (una corrida = un run_id, bloqueo exclusivo, una transacción)
   ├─ db.py: SQLite con migraciones versionadas, FK, retención por tabla
   ├─ CSV opcionales (output/)
   └─ integraciones opcionales y aisladas:
        telegram_alertas.py · posiciones.py · ripio_sync.py (solo lectura)

 backtest.py            → evaluación fuera de muestra con costos y benchmarks
 demo/generar_demo.py   → pipeline real con datos sintéticos y reloj simulado
 exportar_powerbi.py    → modelo estrella en CSV (sin tablas privadas)
```

| Módulo | Responsabilidad |
|---|---|
| `config.py` | Activos, parámetros, frescura, retención (sin secretos) |
| `main.py` | Orquesta una corrida y registra su estado |
| `db.py` | Esquema, migraciones, bloqueo, escritura, retención |
| `tiempo.py` | Timestamps UTC y `run_id` |
| `indicadores.py`, `senales.py` | Indicadores causales y motor de señales |
| `fuentes/` | Proveedores de datos y política de red |
| `telegram_alertas.py` | Alertas con estado de entrega y reintento |
| `posiciones.py`, `gestionar_posiciones.py` | Posiciones privadas, gatillos idempotentes |
| `ripio_api.py`, `ripio_sync.py` | Saldos Ripio (solo lectura) con estados explícitos |
| `backtest.py` | Backtest reproducible |
| `datos_sinteticos.py`, `demo/` | Datos ficticios y demo pública |
| `exportar_powerbi.py`, `powerbi/` | Modelo estrella, DAX, Power Query y guía |
| `consultar.py`, `ver_posiciones.py` | Consultas en consola (solo lectura) |
| `verificar_telegram.py`, `verificar_ripio.py` | Verificación **manual** de integraciones reales |

## Activos, mercados y monedas

| Grupo (`tipo`) | Lista en `config.py` | Mercado | Moneda | Timeframe | Fuente |
|---|---|---|---|---|---|
| `cripto` | `CRIPTO` | Binance spot | **USDT** (no USD) | 1 h | Binance |
| `accion_arg` | `ACCIONES_ARG` (`.BA`) | BYMA | ARS | 1 d | Yahoo |
| `cedear` | `CEDEARS` (vacía; ej. `AAPL.BA`) | BYMA | ARS | 1 d | Yahoo |
| `accion_us` | `ACCIONES_US` | NYSE/Nasdaq, cotización **primaria** | USD | 1 d | Yahoo |

Los tickers de `ACCIONES_US` (AAPL, SPY, IBIT…) son acciones/ETFs de EE. UU. en dólares,
**no CEDEARs**. Los ETFs se marcan como `instrumento = ETF`. La moneda informada por el
proveedor se valida contra la esperada; si no coincide, el activo queda `dato_invalido`.
`MATICUSDT` se reemplazó por `POLUSDT` (Binance migró MATIC a POL; el par viejo devolvía
velas congeladas).

## Instalación reproducible

Requiere Python 3.10 o superior (probado en 3.10 / Windows).

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    ·    Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt -c constraints.txt
pip install -r requirements-dev.txt -c constraints.txt   # tests y lint
```

`requirements.txt` fija las dependencias directas y `constraints.txt` las transitivas.
No se agregaron dependencias de ejecución nuevas; las de desarrollo son `pytest` y `ruff`.

## Demo segura (sin credenciales)

Todo esto funciona sin red ni credenciales y no toca `output/`:

```bash
python -m pytest                                        # tests offline (bloquean la red)
python demo/generar_demo.py                             # 7 días de corridas simuladas
python backtest.py --demo --salida docs/backtest_demo.md
```

- `demo/generar_demo.py` corre el **pipeline real** con 7 activos ficticios (`ALFAUSDT`,
  `ACME`, `ANDES.BA`…), un reloj simulado y proveedores sintéticos. Incluye a propósito un
  activo que deja de actualizarse (`obsoleto`) y otro con fallas intermitentes
  (`error_proveedor`). Exporta `powerbi/datos_demo/*.csv` (con `MANIFIESTO.txt` de
  hashes SHA-256) y `powerbi/valores_esperados.md`.
- Mismas semillas → mismos archivos: la demo es verificable.
- No se incluyen capturas de pantalla; si las agregás, generalas solo desde la demo.

## Uso con datos reales

```bash
python main.py                       # una corrida (requiere red: Binance y Yahoo)
python main.py --sin-integraciones   # sin Telegram, posiciones ni Ripio
python consultar.py                  # última corrida, señales y cambios (solo lectura)
python exportar_powerbi.py           # CSV privados en output/powerbi/
python backtest.py --db output/radar.db   # backtest con la historia local acumulada
```

- **Windows Task Scheduler:** programa `python.exe main.py` con "Iniciar en" = carpeta
  del proyecto. Alternativas: `correr_radar.bat` o `python loop.py`.
- Si dos ejecuciones coinciden (loop + tarea programada), la segunda termina con
  "Ya hay una corrida usando…" (código 2) en vez de escribir en paralelo.
- Código de salida de `main.py`: 0 si hubo datos válidos, 1 si la corrida falló.

## Configuración segura

- Las credenciales **no** van en `config.py`. Preferí variables de entorno:
  `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `RIPIO_API_KEY`, `RIPIO_SECRET_KEY`
  (ver `.env.example`). Alternativa local: `telegram_config.txt` / `ripio_config.txt`
  copiados desde los `*.example.txt` (están en `.gitignore`).
- Ripio: usá una API key de **solo lectura**, idealmente restringida por IP.
- Los mensajes de error muestran proveedor, motivo y código HTTP; nunca URLs, tokens,
  saldos ni respuestas crudas. El texto dinámico de Telegram se escapa (HTML).
- `verificar_telegram.py --enviar` y `verificar_ripio.py --consultar` hacen llamadas
  reales: son verificaciones manuales, no tests automáticos.
- **Si una clave estuvo alguna vez en un repositorio, captura o log, revocala y generá
  otra.** Borrar el archivo no invalida una clave expuesta.
- Antes de publicar: `.gitignore` excluye `output/`, bases de datos, CSV de posiciones,
  configuración real, PBIX y auditorías internas. Revisá con `git status --ignored`.

## Datos, corridas y calidad

Cada ejecución tiene un `run_id` (ej. `20261020T130000Z-a1b2c3`) que se repite en todas
las filas que escribe. Columnas de tiempo (UTC, `YYYY-MM-DD HH:MM:SS`):

| Columna | Significado |
|---|---|
| `capturado_utc` | cuándo se descargaron los datos del activo |
| `vela_utc` | inicio de la última vela **cerrada** usada |
| `vela_original` | ese mismo instante en la hora del mercado (ej. `America/New_York`) |
| `generado_utc` | cuándo se guardó la señal |
| `timestamp` | columna heredada: hora local de generación (compatibilidad) |

Estado de cada activo en cada corrida (`resultados_activo`): `valido`, `obsoleto`,
`sin_datos`, `historial_insuficiente`, `error_proveedor`, `dato_invalido`. Estado de la
corrida (`corridas`): `completa`, `parcial`, `fallida`, `interrumpida`. Solo los datos
`valido` generan alertas.

Base de datos: migraciones versionadas (`PRAGMA user_version`) con **respaldo automático**
antes de migrar una DB existente (`output/radar.db.respaldo-v0-…`), `foreign_keys=ON`,
una transacción por corrida y retención por tabla (`RETENCION_DIAS` en `config.py`;
posiciones y eventos nunca se purgan automáticamente).

## Señales y backtest

- Qué activa cada señal, límites y falsos positivos: [docs/SENALES.md](docs/SENALES.md).
- Posiciones y gatillos idempotentes: [docs/POSICIONES.md](docs/POSICIONES.md).
- Backtest (`backtest.py`): señal al cierre de *t*, ejecución en la apertura de *t+1*,
  long-only, comisión + spread/slippage por tipo de activo, partición cronológica
  60/20/20, parámetros elegidos **solo en train**, resultados de test fuera de muestra,
  comparación contra comprar y mantener y contra efectivo. Cripto 1h y acciones 1d se
  evalúan por separado. Reporte de ejemplo con datos sintéticos:
  [docs/backtest_demo.md](docs/backtest_demo.md) (no dice nada sobre mercados reales).

## Power BI

`exportar_powerbi.py` genera un **modelo estrella** en CSV (`dim_activo`, `dim_fecha`, `dim_senal`,
`dim_corrida`, `fact_senales`, `fact_precios`, `fact_resultados_activo`) sin ninguna tabla privada.
La carpeta `powerbi/` trae la guía de armado, las medidas (`medidas.dax`), las consultas Power Query,
el tema y los valores esperados para validar cada medida.

**Informe público listo para abrir**: [powerbi/demo_publica/RadarDemo.pbip](powerbi/demo_publica/README.md),
un proyecto PBIP (modelo TMDL + informe PBIR) alimentado solo por los CSV sintéticos.

| | |
|---|---|
| ![Resumen](powerbi/demo_publica/capturas/resumen.png) | ![Señales](powerbi/demo_publica/capturas/senales.png) |

- **Seis páginas en español y en inglés** (botón EN/ES en la cabecera), en lenguaje de todos los días: portada,
  Resumen, Señales, Mercado, Calidad y una guía de lectura con glosario; 88 medidas DAX documentadas, ninguna suma ni promedia RSI, fuerza ni precios.
- **Generado desde código**: `powerbi/demo_publica/gen_report.py` escribe el informe completo (visuales,
  marcadores, tema) sobre una cuadrícula de 8 px; `exportar_medidas.py` mantiene `medidas.dax` en sincronía
  con el modelo.
- **Validado**: TMDL parseado con TOM, `pbir validate` sin errores, las 88 medidas evaluadas contra el
  motor local de Desktop en tres contextos de filtro, y la interacción (selección, selector sincronizado, portada,
  navegación, panel de filtros, restablecer) probada en Desktop 2.159 con capturas. `tests/test_pbip.py`
  repite los chequeos estáticos en CI sin Desktop.
- El PBIX original no se modificó ni debe publicarse (tiene datos reales embebidos).

## Tests y CI

```bash
python -m pytest          # 128 tests offline: la red está bloqueada en conftest.py
ruff check .              # lint + reglas de seguridad (bandit)
```

Cubren: RSI plano/inicialización, baseline de volumen, velas insuficientes y abiertas,
errores y reintentos de proveedores, UTC y `run_id`, migraciones/transacciones/FK/bloqueo,
reintento de alertas fallidas, gatillos idempotentes, importación CSV, estados de Ripio,
ausencia de lookahead en el backtest, reproducibilidad y privacidad de la demo, patrones
de secretos en archivos públicos y coherencia estática del proyecto Power BI (`test_pbip.py`).
CI: `.github/workflows/ci.yml` (Ubuntu y Windows, Python 3.10 y 3.12) más una auditoría de
dependencias con `pip-audit`; Dependabot propone actualizaciones de paquetes y de acciones.

## Seguridad

Resumen en [SECURITY.md](SECURITY.md): credenciales solo por variables de entorno o archivos ignorados
por git, API de Ripio de solo lectura, datos reales fuera del repositorio, tests que detectan patrones de
secretos, dependencias fijadas y auditadas, CI con permisos mínimos.

## Limitaciones

- Yahoo Finance es una fuente no oficial (demoras, huecos, correcciones).
- Las señales usan los mismos umbrales para todas las clases de activo y no están
  calibradas; ver [docs/SENALES.md](docs/SENALES.md).
- Las acciones argentinas se miden en ARS nominales (inflación/devaluación).
- La historia local depende de que el radar haya corrido: puede tener huecos.
- Velas diarias: se usan a partir de la medianoche local del mercado (demora deliberada).
- El backtest no modela libro de órdenes, impuestos ni dividendos en efectivo.

## Migración desde la versión anterior

Al correr `python main.py` por primera vez con esta versión:

1. Se crea un respaldo de `output/radar.db` y se migra el esquema (sin borrar datos).
2. Los eventos de posición previos quedan marcados como notificados y vigentes: deja de
   repetirse la misma alerta en cada corrida.
3. Las señales se calculan solo con velas cerradas. Las acciones usan precios ajustados:
   cada corrida reescribe (upsert) todas las velas descargadas (≈ 1 año en acciones,
   200 velas en cripto) con `ajuste = split_dividendo`; las filas más antiguas quedan
   como estaban (sin ajustar, `ajuste` vacío).
4. Las alertas de Telegram solo se marcan como entregadas tras un envío confirmado.
5. `test_ripio.py` y `test_telegram.py` se reemplazaron por `verificar_ripio.py` y
   `verificar_telegram.py` (no imprimen credenciales ni saldos).

## Estructura del proyecto

```
radar_senales/
├── main.py, config.py, db.py, tiempo.py, consola.py
├── indicadores.py, senales.py, backtest.py, datos_sinteticos.py
├── telegram_alertas.py, posiciones.py, gestionar_posiciones.py
├── ripio_api.py, ripio_sync.py, verificar_ripio.py, verificar_telegram.py
├── consultar.py, ver_posiciones.py, loop.py, correr_radar.bat, exportar_powerbi.py
├── fuentes/            binance_api.py, yahoo_api.py, normalizacion.py, red.py
├── demo/               generar_demo.py   (demo/salida/ se ignora)
├── powerbi/            README_POWERBI.md, medidas.dax, consultas_powerquery.pq,
│                       tema_accesible.json, valores_esperados.md, datos_demo/
│   └── demo_publica/   RadarDemo.pbip (modelo TMDL + informe PBIR), gen_report.py,
│                       exportar_medidas.py, VALIDACION_MEDIDAS.dax, capturas/
├── docs/               SENALES.md, POSICIONES.md, backtest_demo.md
├── tests/              suite offline
├── *.example.txt, .env.example, posiciones.example.csv   (plantillas sin secretos)
├── requirements*.txt, constraints.txt, pyproject.toml, LICENSE, .github/workflows/ci.yml
└── output/             datos locales y privados (ignorado por git)
```

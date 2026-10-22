"""
Radar de Señales - Configuración
Editá las listas de tickers y los parámetros de los indicadores.
"""

# ============================================================
# ACTIVOS A MONITOREAR
# ============================================================

# Clasificación de cada grupo (ver GRUPOS_ACTIVOS más abajo):
#   CRIPTO        pares spot de Binance cotizados en USDT, velas de 1h.
#   ACCIONES_ARG  acciones argentinas en BYMA (sufijo .BA), en ARS, velas 1d.
#   CEDEARS       certificados de acciones extranjeras en BYMA (sufijo .BA), en ARS.
#   ACCIONES_US   acciones y ETFs con cotización PRIMARIA en EE. UU. (NYSE/Nasdaq),
#                 en USD. No son CEDEARs: el CEDEAR de AAPL sería "AAPL.BA".

# --- CRIPTO (Binance) ---
# Top market cap + cripto líquidas. Comentá las que no te interesen.
CRIPTO = [
    "BTCUSDT",   # Bitcoin
    "ETHUSDT",   # Ethereum
    "SOLUSDT",   # Solana
    "BNBUSDT",   # Binance Coin
    "XRPUSDT",   # Ripple
    "ADAUSDT",   # Cardano
    "DOGEUSDT",  # Dogecoin
    "AVAXUSDT",  # Avalanche
    "DOTUSDT",   # Polkadot
    "LINKUSDT",  # Chainlink
    # "MATICUSDT": Binance migró MATIC a POL en 2024; el par viejo devuelve
    # velas congeladas (el radar las marca como dato "obsoleto").
    "POLUSDT",   # Polygon (POL, ex MATIC)
    "LTCUSDT",   # Litecoin
    # "TRXUSDT",   # Tron
    # "ATOMUSDT",  # Cosmos
    # "ARBUSDT",   # Arbitrum
    # "OPUSDT",    # Optimism
    # "NEARUSDT",  # Near
    # "INJUSDT",   # Injective
    # "TIAUSDT",   # Celestia
    # "SUIUSDT",   # Sui
]

# --- ACCIONES ARGENTINAS (Yahoo, sufijo .BA) ---
# Panel líder + algunas del general más activas.
ACCIONES_ARG = [
    # Bancos
    "GGAL.BA",   # Galicia
    "BMA.BA",    # Banco Macro
    "BBAR.BA",   # BBVA Argentina
    "SUPV.BA",   # Grupo Supervielle
    # Energía
    "YPFD.BA",   # YPF
    "PAMP.BA",   # Pampa Energía
    "CEPU.BA",   # Central Puerto
    "EDN.BA",    # Edenor
    "TGSU2.BA",  # Transportadora Gas del Sur
    "TGNO4.BA",  # Transportadora Gas del Norte
    # Materiales / industria
    "ALUA.BA",   # Aluar
    "TXAR.BA",   # Ternium
    "LOMA.BA",   # Loma Negra
    "MIRG.BA",   # Mirgor
    # Otros
    "CRES.BA",   # Cresud (agro)
    "COME.BA",   # Sociedad Comercial del Plata
    "BYMA.BA",   # Bolsas y Mercados Argentinos
    "TRAN.BA",   # Transener
    # "VALO.BA",   # Grupo Financiero Valores
    # "AGRO.BA",   # Agrometal
    # "HARG.BA",   # Holcim Argentina
    # "PATA.BA",   # Importadora y Exportadora de la Patagonia
]

# --- CEDEARs (Yahoo, sufijo .BA, cotizan en ARS) ---
# Vacío por defecto. Ejemplo: "AAPL.BA", "MELI.BA", "KO.BA".
CEDEARS = [
]

# --- ACCIONES y ETFs de EE. UU., cotización primaria en USD (Yahoo) ---
# Mezcla de mega caps + sectores variados + cripto-stocks.
ACCIONES_US = [
    # Mag 7
    "AAPL",   # Apple
    "MSFT",   # Microsoft
    "NVDA",   # Nvidia
    "GOOGL",  # Alphabet
    "META",   # Meta
    "AMZN",   # Amazon
    "TSLA",   # Tesla
    # Cripto-stocks (proxies de exposición a cripto vía acciones)
    "COIN",   # Coinbase
    "MSTR",   # MicroStrategy (gran tenedor de BTC)
    "MARA",   # Marathon Digital (mining)
    "RIOT",   # Riot Platforms (mining)
    "HOOD",   # Robinhood
    # ETFs de cripto spot
    "IBIT",   # iShares Bitcoin ETF (BlackRock)
    "FBTC",   # Fidelity Bitcoin ETF
    "ETHA",   # iShares Ethereum ETF
    # Otros US destacados
    "AMD",    # AMD
    "NFLX",   # Netflix
    "PLTR",   # Palantir
    "AVGO",   # Broadcom
    "ORCL",   # Oracle
    "JPM",    # JP Morgan
    # ETFs de mercado
    "SPY",    # S&P 500
    "QQQ",    # Nasdaq 100
    "IWM",    # Russell 2000 (small caps)
    # "DIA",    # Dow Jones
    # "GLD",    # Oro ETF
    # "SLV",    # Plata ETF
    # "TLT",    # Bonos del tesoro 20+ años
    # "VIX",    # Indice de volatilidad (no operable directamente)
]

# Tickers de ACCIONES_US que son ETFs (para clasificar el instrumento).
ETFS = {"IBIT", "FBTC", "ETHA", "SPY", "QQQ", "IWM", "DIA", "GLD", "SLV", "TLT"}

# Metadatos por grupo: fuente, mercado, moneda de cotización y timeframe.
# `moneda` se valida contra la que informa el proveedor cuando está disponible.
GRUPOS_ACTIVOS = {
    "cripto": {"fuente": "binance", "mercado": "Binance spot", "moneda": "USDT",
               "intervalo_config": "INTERVALO_CRIPTO", "instrumento": "par cripto/USDT"},
    "accion_arg": {"fuente": "yahoo", "mercado": "BYMA", "moneda": "ARS",
                   "intervalo_config": "INTERVALO_ACCIONES", "instrumento": "acción argentina"},
    "cedear": {"fuente": "yahoo", "mercado": "BYMA", "moneda": "ARS",
               "intervalo_config": "INTERVALO_ACCIONES", "instrumento": "CEDEAR"},
    "accion_us": {"fuente": "yahoo", "mercado": "NYSE/Nasdaq", "moneda": "USD",
                  "intervalo_config": "INTERVALO_ACCIONES", "instrumento": "acción EE. UU."},
}

# ============================================================
# PARÁMETROS DE INDICADORES
# ============================================================

# RSI (Relative Strength Index)
RSI_PERIODO = 14
RSI_SOBRECOMPRA = 70
RSI_SOBREVENTA = 30
RSI_SOBRECOMPRA_EXTREMA = 80   # nuevo: por encima de esto, vetar señales de compra
RSI_SOBREVENTA_EXTREMA = 20    # nuevo: por debajo de esto, vetar señales de venta

# MACD
MACD_RAPIDA = 12
MACD_LENTA = 26
MACD_SEÑAL = 9

# Medias móviles
MA_CORTA = 20
MA_LARGA = 50

# Velas a traer
VELAS_HISTORIAL = 200        # Binance (máx 1000 por request)
PERIODO_YAHOO = "1y"         # Yahoo: período de historia a pedir

# Cuántas velas cerradas guardar por activo en precios_ohlcv en cada corrida.
# None = todas las que se descargaron (acumula historia para el backtest).
VELAS_A_GUARDAR = None

# Intervalos
INTERVALO_CRIPTO = "1h"     # Binance: 1m, 5m, 15m, 1h, 4h, 1d
INTERVALO_ACCIONES = "1d"   # Yahoo: 1m, 5m, 15m, 1h, 1d, 1wk

# Frescura: si la última vela CERRADA terminó hace más de estas horas, el dato
# se marca "obsoleto" (la señal se guarda marcada y NO se alerta).
# 1d tolera fines de semana largos y feriados (ej. carnaval en Argentina).
MAX_ANTIGUEDAD_HORAS = {"1h": 3, "4h": 10, "1d": 120, "1wk": 24 * 10}

# ============================================================
# SALIDA
# ============================================================

CARPETA_SALIDA = "output"

ARCHIVO_DB = "radar.db"
DIAS_RETENCION = 365

# Retención por tabla (días). None = no se borra automáticamente.
# Las tablas de posiciones/eventos son decisiones del usuario: no se purgan.
RETENCION_DIAS = {
    "senales_historico": DIAS_RETENCION,
    "precios_ohlcv": DIAS_RETENCION,
    "corridas": DIAS_RETENCION,          # borra en cascada resultados_activo
    "resultados_activo": 180,
    "alertas_log": 180,
    "ripio_balance_snapshot": DIAS_RETENCION,
    "ripio_cambios_pendientes": DIAS_RETENCION,  # solo los ya notificados
    "posiciones": None,
    "eventos_posicion": None,
}

EXPORTAR_CSVS = True
ARCHIVO_SEÑALES = "senales.csv"
ARCHIVO_HISTORICO = "historico_senales.csv"
ARCHIVO_PRECIOS = "precios.csv"

# ============================================================
# ALERTAS POR TELEGRAM
# ============================================================

# Credenciales: variables de entorno TELEGRAM_TOKEN / TELEGRAM_CHAT_ID
# (preferido) o telegram_config.txt local (ver telegram_config.example.txt).
# Nunca se guardan en este archivo.
TELEGRAM_ACTIVO = True
TELEGRAM_MODO_RESUMEN = True
TELEGRAM_SOLO_CAMBIOS = True

# ============================================================
# SEGUIMIENTO DE POSICIONES PERSONALES
# ============================================================

# Activa la evaluación de tus compras reales contra el último cierre.
# Editás output/posiciones.csv con tus compras y el script te alerta UNA vez
# cuando se gatilla stop loss, take profit o trailing stop. La posición nunca
# se cierra sola: se rearma o se cierra con gestionar_posiciones.py.
POSICIONES_ACTIVO = True

# Archivo CSV donde editás tus compras manualmente.
ARCHIVO_POSICIONES = "posiciones.csv"

# ============================================================
# RIPIO API (sincronización automática de balances)
# ============================================================

# Si está en True, cada corrida consulta tu balance en Ripio y detecta
# cambios (compras nuevas, ventas, etc) para alertarte.
# Requiere RIPIO_API_KEY / RIPIO_SECRET_KEY (variables de entorno, preferido)
# o ripio_config.txt local, con permisos de SOLO LECTURA.
RIPIO_ACTIVO = True

// ============================================================================
// Consultas Power Query (M) para cargar los CSV del modelo estrella.
// NO VALIDADAS en Power BI Desktop desde este repositorio.
//
// 1. Crear un parámetro de texto llamado CarpetaDatos con la ruta a la carpeta
//    de los CSV, terminada en "\". Ejemplos (no uses rutas personales en la
//    copia pública):
//      demo pública:   <carpeta del repo>\powerbi\datos_demo\
//      uso privado:    <carpeta del repo>\output\powerbi\   (python exportar_powerbi.py)
// 2. Crear una consulta en blanco por tabla (Editor avanzado) con el bloque
//    correspondiente. El nombre de la consulta = nombre de la tabla.
//
// Importante: los CSV usan punto decimal y fechas ISO. Por eso los tipos se
// aplican con cultura "en-US"; con la configuración regional es-AR, sin ese
// argumento, "101.6695" se leería mal.
// ============================================================================

// ---------- Función auxiliar: crear una consulta llamada CargarCsv ----------
(archivo as text, tipos as list) as table =>
let
    Origen = Csv.Document(
        File.Contents(CarpetaDatos & archivo),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]
    ),
    Encabezados = Table.PromoteHeaders(Origen, [PromoteAllScalars = true]),
    Tipado = Table.TransformColumnTypes(Encabezados, tipos, "en-US")
in
    Tipado

// ---------- dim_activo ----------
let
    Tabla = CargarCsv("dim_activo.csv", {
        {"ticker", type text}, {"tipo", type text}, {"instrumento", type text},
        {"mercado", type text}, {"moneda", type text}, {"fuente", type text},
        {"timeframe", type text}, {"es_sintetico", type logical}})
in
    Tabla

// ---------- dim_fecha (marcar como tabla de fechas, columna fecha) ----------
let
    Tabla = CargarCsv("dim_fecha.csv", {
        {"fecha", type date}, {"anio", Int64.Type}, {"mes", Int64.Type},
        {"anio_mes", type text}, {"dia", Int64.Type}, {"dia_semana", Int64.Type},
        {"es_habil", type logical}})
in
    Tabla

// ---------- dim_senal (ordenar "señal" por la columna "orden") ----------
let
    Tabla = CargarCsv("dim_senal.csv", {
        {"señal", type text}, {"orden", Int64.Type}, {"simbolo", type text},
        {"descripcion", type text}})
in
    Tabla

// ---------- dim_corrida ----------
let
    Tabla = CargarCsv("dim_corrida.csv", {
        {"run_id", type text}, {"inicio_utc", type datetime}, {"fin_utc", type datetime},
        {"estado", type text}, {"activos_total", Int64.Type}, {"activos_validos", Int64.Type},
        {"activos_obsoletos", Int64.Type}, {"activos_sin_datos", Int64.Type},
        {"activos_fallidos", Int64.Type}, {"detalle", type text},
        {"es_ultima_corrida", type logical}})
in
    Tabla

// ---------- fact_senales ----------
let
    Tabla = CargarCsv("fact_senales.csv", {
        {"id", Int64.Type}, {"run_id", type text}, {"ticker", type text}, {"tipo", type text},
        {"fuente", type text}, {"timeframe", type text}, {"mercado", type text},
        {"moneda", type text}, {"estado_dato", type text}, {"generado_utc", type datetime},
        {"capturado_utc", type datetime}, {"vela_utc", type datetime}, {"precio", type number},
        {"señal", type text}, {"fuerza", Int64.Type}, {"rsi", type number},
        {"macd_hist", type number}, {"vol_relativo", type number}, {"ma_corta", type number},
        {"ma_larga", type number}, {"motivos", type text}, {"es_ultima", type logical},
        {"cambio_senal", type logical}, {"fecha", type date}})
in
    Tabla

// ---------- fact_precios ----------
let
    Tabla = CargarCsv("fact_precios.csv", {
        {"ticker", type text}, {"timeframe", type text}, {"timestamp_utc", type datetime},
        {"timestamp_original", type text}, {"open", type number}, {"high", type number},
        {"low", type number}, {"close", type number}, {"volume", type number},
        {"rsi", type number}, {"macd_hist", type number}, {"ma_corta", type number},
        {"ma_larga", type number}, {"vol_relativo", type number}, {"ajuste", type text},
        {"es_ultima_vela", type logical}, {"fecha", type date}})
in
    Tabla

// ---------- fact_resultados_activo ----------
let
    Tabla = CargarCsv("fact_resultados_activo.csv", {
        {"run_id", type text}, {"ticker", type text}, {"tipo", type text}, {"fuente", type text},
        {"timeframe", type text}, {"estado", type text}, {"capturado_utc", type datetime},
        {"vela_utc", type datetime}, {"velas_recibidas", Int64.Type},
        {"velas_descartadas", Int64.Type}, {"velas_abiertas", Int64.Type},
        {"moneda", type text}, {"detalle", type text}, {"fecha", type date}})
in
    Tabla

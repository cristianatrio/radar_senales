"""Generador del informe PBIR de la demo pública (RadarDemo.Report), bilingüe.

El informe se define en código: cada página es una función que ubica visuales en una
cuadrícula de 1280 x 720 (múltiplos de 8 px, margen 24, separación 16) y escribe los
`visual.json`, `page.json`, marcadores y el tema. Cada página se genera dos veces, en
español y en inglés, a partir del diccionario `EN` (textos de la interfaz), `EN_MEASURES`
(medidas que producen texto) y `EN_COLS` (columnas en palabras); las páginas en inglés
quedan ocultas en la barra de pestañas y se alcanzan con el botón EN/ES de la cabecera.
Se ejecuta con Power BI Desktop cerrado; hace un respaldo del informe anterior en la
carpeta temporal del sistema.

    python powerbi/demo_publica/gen_report.py
"""
import copy
import json
import os
import shutil
import tempfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent
R = str(AQUI / 'RadarDemo.Report')
D = R + os.sep + 'definition'
SCH = 'https://developer.microsoft.com/json-schemas/fabric/item/report/definition/'
VSCH = SCH + 'visualContainer/2.9.0/schema.json'

KEYS = ['ini', 'res', 'sen', 'mer', 'cal', 'guia']
PG = {'es': {'ini': 'a1f3c9e2b7d45068', 'res': '4312130530f2e353', 'sen': '179abaca766ff951', 'mer': '2f53da19923c44ba', 'cal': '8341d05fb21037f6', 'guia': 'c7e2d4a9f1b36025'},
      'en': {'ini': 'e5b7a1c3d9f20461', 'res': 'f0a2c4e6b8d13579', 'sen': '9c1e3a5b7d2f4680', 'mer': 'b3d5f7a9c1e24682', 'cal': 'd7f9b1c3e5a26804', 'guia': '2a4c6e8b0d1f3579'}}
NAMES = {'ini': 'Inicio', 'res': 'Resumen', 'sen': 'Señales', 'mer': 'Mercado', 'cal': 'Calidad', 'guia': 'Guía'}
TITLES = {'res': 'El mercado en un vistazo', 'sen': 'Señales vigentes por activo', 'mer': 'Evolución del activo elegido', 'cal': 'Confiabilidad de los datos', 'guia': 'Cómo leer este radar'}
PAGINAS_VIEJAS = ['89e581505e651c7b']   # tooltip 'Detalle de activo': eliminada (no aportaba; la ficha ya explica el activo)

INK, MUTED, FAINT, PRIMARY = '#1B2430', '#64748B', '#94A3B8', '#4F46E5'
GREEN, RED = '#16A34A', '#DC2626'
NAVY, BORDE = '#0B1F33', '#E6EAF0'

LANG = 'es'          # idioma de la página que se está construyendo
FALTANTES = set()    # textos sin traducción detectados al construir las páginas en inglés

# Medidas que producen texto: nombre en español -> nombre de la versión en inglés (mismo modelo).
EN_MEASURES = {'Lectura del radar': 'Radar reading', 'Detalle del activo seleccionado': 'Selected asset detail', 'Lectura de calidad': 'Data quality reading',
               'Título dinámico': 'Dynamic title', 'Subtítulo filtros': 'Filters subtitle', 'Pie de actualización': 'Footer update',
               'Señal con ícono': 'Signal with icon', 'Estado chip': 'Status chip', 'Título cierre': 'Close chart title', 'Contexto del activo graficado': 'Charted asset context'}
# Columnas en palabras: (tabla, columna en español) -> columna en inglés.
EN_COLS = {('dim_activo', 'Tipo de activo'): 'Asset type', ('dim_activo', 'Fuente de datos'): 'Data source', ('dim_activo', 'Vela'): 'Candle',
           ('fact_senales', 'Estado del dato'): 'Data status', ('fact_senales', 'Día de corrida'): 'Run day',
           ('dim_senal', 'Señal en palabras'): 'Signal', ('dim_senal', 'descripcion'): 'Rule'}
# Textos de la interfaz: español -> inglés. Los símbolos y nombres propios se mapean a sí mismos.
EN = {
    # cabecera, pie, panel
    'RADAR DE SEÑALES · DATOS DE PRUEBA': 'SIGNAL RADAR · TEST DATA', 'Inicio': 'Home', 'Resumen': 'Overview', 'Señales': 'Signals', 'Mercado': 'Market', 'Calidad': 'Quality', 'Guía': 'Guide',
    'El mercado en un vistazo': 'The market at a glance', 'Señales vigentes por activo': 'Current signal by asset', 'Evolución del activo elegido': 'The chosen asset over time',
    'Confiabilidad de los datos': 'How reliable the data is', 'Cómo leer este radar': 'How to read this radar',
    'Ir a la página': 'Go to the', 'página': 'page', 'Restablecer': 'Reset', 'Quita las selecciones de todos los selectores': 'Clears every slicer selection',
    'Filtros': 'Filters', 'Abre el panel de filtros': 'Opens the filter panel', 'Resumen de los filtros activos': 'Summary of the active filters',
    'Ver este informe en inglés': 'View this report in Spanish', 'EN': 'ES',
    'Datos de prueba con fechas simuladas: la fuerza de una señal no es una recomendación de compra ni de venta.': "Test data with simulated dates: a signal's strength is not a recommendation to buy or sell.",
    'Aviso sobre los datos de prueba': 'Notice about the test data', 'Fecha y hora UTC de la última corrida simulada': 'UTC date and time of the last simulated run',
    'Panel de filtros': 'Filter panel', 'Cierra el panel de filtros': 'Closes the filter panel', 'Filtrá por': 'Filter by',
    'Tipo de activo': 'Asset type', 'Fuente del dato': 'Data source', 'Duración de la vela': 'Candle length', 'Señal': 'Signal',
    # Resumen
    'Activos seguidos': 'Assets tracked', 'Señales de compra': 'Buy signals', 'Señales de venta': 'Sell signals', 'En espera': 'On hold', 'Con dato al día': 'With fresh data',
    'Cantidad de activos con una señal vigente': 'Number of assets with a current signal', 'Activos cuya señal vigente es de compra': 'Assets whose current signal is a buy',
    'Activos cuya señal vigente es de venta': 'Assets whose current signal is a sell', 'Activos cuya señal vigente es esperar': 'Assets whose current signal is hold',
    'Porcentaje de activos cuyo último dato es válido': 'Share of assets whose latest data is valid', 'Ver el detalle en la página': 'See the detail on the',
    'Compra': 'Buy', 'Espera': 'Hold', 'Venta': 'Sell', 'Día': 'Day',
    'Cuántos activos estaban en compra, espera o venta cada día': 'How many assets were on buy, hold or sell each day',
    'Al cierre de cada día simulado, cuántos activos tenían señal de compra, de espera o de venta': 'At the close of each simulated day, how many assets had a buy, hold or sell signal',
    'Señales según el tipo de activo': 'Signals by asset type', 'Cuántas señales de compra, espera y venta hay por tipo de activo': 'How many buy, hold and sell signals there are per asset type',
    'Activo': 'Asset', 'Fuerza': 'Strength', 'Fuerza de la señal de cada activo (de −9 a +9)': "Each asset's signal strength (−9 to +9)",
    'Puntaje heurístico de la señal vigente: positivo a favor de comprar, negativo a favor de vender': 'Heuristic score of the current signal: positive favours buying, negative favours selling',
    'Qué dice el radar hoy': 'What the radar says today', 'Lectura en palabras simples de las señales vigentes': 'Plain-language reading of the current signals',
    # Señales
    'Cierre': 'Close', 'Moneda': 'Currency', 'Vela': 'Candle', 'Dato': 'Data', 'Último dato (UTC)': 'Last data (UTC)',
    'Señal actual de cada activo': 'Current signal of each asset', 'Tocá un activo para ver su ficha debajo': 'Tap an asset to see its card below',
    'Ver la ficha de:': 'Show the card for:', 'Elegí un activo para ver su ficha, sin tener que buscarlo en la tabla': 'Pick an asset to see its card without searching the table',
    'Ver su evolución ▸': 'See how it evolved ▸', 'Abre la página Mercado con el activo elegido en el selector': 'Opens the Market page with the asset chosen in the selector',
    'Tocá un activo en la tabla y su ficha aparece debajo en palabras simples. Elegilo arriba y «Ver su evolución» abre la página Mercado con su precio y su RSI.':
        'Tap an asset in the table and its card appears below in plain words. Pick it above and "See how it evolved" opens the Market page with its price and RSI.',
    'Cómo usar esta página': 'How to use this page', 'Ficha del activo elegido': 'Card of the chosen asset',
    'Detalle en palabras simples del activo elegido en la tabla o en el selector': 'Plain-language detail of the asset chosen in the table or the selector',
    # Mercado
    'Activo graficado': 'Charted asset', 'Elegí el activo de los gráficos; solo uno a la vez': 'Pick the asset for the charts; one at a time',
    'Variación del último cierre': 'Last close change', 'Cuánto varió el precio respecto del cierre anterior': 'How much the price moved versus the previous close',
    'RSI actual (0 a 100)': 'Current RSI (0 to 100)', 'Momentum del último dato: por debajo de 30 suele estar barato, por encima de 70 caro': 'Momentum of the latest data: below 30 is usually cheap, above 70 expensive',
    'Último precio de cierre': 'Last closing price', 'Precio de cierre del último dato': 'Closing price of the latest data',
    'Media de 20 periodos': '20-period average', 'Media de 50 periodos': '50-period average',
    'Precio de cierre y sus medias de 20 y 50 periodos; el deslizador de abajo acerca un período': 'Closing price with its 20- and 50-period averages; the slider below zooms into a period',
    'RSI: en la zona roja (más de 70) suele estar caro · en la verde (menos de 30), barato': 'RSI: in the red zone (above 70) it is usually expensive · in the green zone (below 30), cheap',
    'Momentum de 14 periodos con las zonas de 30 y 70 sombreadas': '14-period momentum with the 30 and 70 zones shaded', 'Zona cara': 'Expensive zone', 'Zona barata': 'Cheap zone',
    # Calidad
    'Activos con dato al día': 'Assets with fresh data', 'Activos con dato desactualizado': 'Assets with stale data', 'Activos cuyo último dato llegó hace demasiado tiempo': 'Assets whose latest data arrived too long ago',
    'Horas desde el último dato': 'Hours since the latest data', 'Cuántas horas pasaron desde el último dato recibido': 'How many hours have passed since the latest data received',
    'Estado del dato': 'Data status', 'Estado del último dato': 'Status of the latest data', 'Cuántos activos tienen su último dato válido y cuántos desactualizado': 'How many assets have valid latest data and how many stale',
    'Desactualizado': 'Stale', 'Válido': 'Valid', 'Fuente': 'Source', 'Horas sin dato, por fuente': 'Data age by source (hours)',
    'Cuántas horas pasaron desde el último dato de cada proveedor': 'How many hours since the latest data from each provider',
    'Qué está pasando con los datos': "What's going on with the data", 'Lectura en palabras simples del estado de los datos': 'Plain-language reading of the data status',
    'Horas sin dato nuevo': 'Hours without new data', 'Antigüedad del dato de cada activo': "Age of each asset's data", 'Todos los activos, del dato más viejo al más nuevo': 'Every asset, from the oldest data to the newest',
    # Inicio
    'Panel de presentación': 'Presentation panel', 'RADAR DE SEÑALES': 'SIGNAL RADAR', 'Marca': 'Brand',
    'Señales técnicas para cripto y acciones, en palabras simples': 'Technical signals for crypto and stocks, in plain words', 'Título del informe': 'Report title',
    'Descarga velas de Binance y Yahoo Finance, calcula RSI, MACD, medias y volumen, y resume cada activo en una señal de compra, espera o venta, con su fuerza y sus motivos.':
        'It downloads candles from Binance and Yahoo Finance, computes RSI, MACD, moving averages and volume, and sums up each asset as a buy, hold or sell signal with its strength and reasons.',
    'Qué hace el radar': 'What the radar does', 'DATOS DE PRUEBA · FECHAS SIMULADAS': 'TEST DATA · SIMULATED DATES', 'Aviso: datos de prueba': 'Notice: test data',
    'Proyecto de portfolio con datos sintéticos. Señales heurísticas: la fuerza no es una probabilidad ni una recomendación de inversión.':
        'Portfolio project with synthetic data. Heuristic signals: strength is neither a probability nor investment advice.',
    'Aviso legal': 'Disclaimer', 'HOY EN EL RADAR': 'ON THE RADAR TODAY', 'Sección: hoy en el radar': 'Section: on the radar today', 'Ver la señal de cada activo': 'See the signal of each asset',
    '¿QUÉ QUERÉS VER?': 'WHAT DO YOU WANT TO SEE?', 'Sección: qué querés ver': 'Section: what do you want to see',
    'El mercado en un vistazo ▸': 'The market at a glance ▸', 'Cuántos activos están en compra, espera o venta, y qué dice el radar hoy.': 'How many assets are on buy, hold or sell, and what the radar says today.',
    'La señal de cada activo ▸': 'The signal of each asset ▸', 'Una fila por activo con su fuerza, RSI y precio, y una ficha en palabras simples.': 'One row per asset with its strength, RSI and price, plus a plain-language card.',
    'La evolución de un activo ▸': 'How an asset evolved ▸', 'Precio con medias de 20 y 50 velas y RSI con sus zonas de 30 y 70.': 'Price with 20- and 50-candle averages and RSI with its 30 and 70 zones.',
    'La confiabilidad de los datos ▸': 'How reliable the data is ▸', 'Qué activos tienen el dato al día y cuáles quedaron desactualizados.': 'Which assets have fresh data and which went stale.',
    'Cómo leer este radar ▸': 'How to read this radar ▸', 'Abre la guía de lectura': 'Opens the reading guide',
    # Guía
    'Descarga de precios': 'Price download', 'Velas cerradas de Binance (cripto, cada hora) y Yahoo Finance (acciones, cada día).': 'Closed candles from Binance (crypto, hourly) and Yahoo Finance (stocks, daily).',
    'Indicadores clásicos': 'Classic indicators', 'RSI, MACD, medias de 20 y 50 velas, volumen relativo y rupturas de máximos o mínimos.': 'RSI, MACD, 20- and 50-candle averages, relative volume and breakouts of highs or lows.',
    'Una señal por activo': 'One signal per asset', 'Cada indicador suma o resta puntos. La fuerza va de −9 a +9 y define compra, espera o venta.': 'Each indicator adds or subtracts points. Strength runs from −9 to +9 and sets buy, hold or sell.',
    'Control de calidad': 'Quality control', 'Un dato viejo, con error o incompleto queda marcado y nunca se confunde con una señal válida.': 'Old, failed or incomplete data is flagged and never mistaken for a valid signal.',
    'Paso': 'Step', 'Qué la activa': 'What triggers it', 'Activos hoy': 'Assets today', '% hoy': '% today', 'Qué activa cada señal': 'What triggers each signal',
    'Regla de cada señal y cuántos activos la tienen hoy': 'Rule of each signal and how many assets have it today', 'Qué NO es este radar': 'What this radar is NOT',
    'No es un bot: no ejecuta órdenes ni opera por vos.\nNo es asesoramiento: las señales son reglas fijas sobre indicadores clásicos.\nLa fuerza es un puntaje, no una probabilidad.\nNo hay evidencia de que estas reglas generen rentabilidad: el backtest del proyecto existe para medirlo con honestidad.':
        "It is not a bot: it places no orders and does not trade for you.\nIt is not advice: the signals are fixed rules on classic indicators.\nStrength is a score, not a probability.\nThere is no evidence these rules make money: the project's backtest exists to measure that honestly.",
    'GLOSARIO': 'GLOSSARY', 'Sección: glosario': 'Section: glossary', 'De 0 a 100: por debajo de 30 suele estar barato, por encima de 70 caro.': 'From 0 to 100: below 30 is usually cheap, above 70 expensive.',
    'Cruza al alza: impulso positivo. Cruza a la baja: impulso negativo.': 'Crosses up: positive momentum. Crosses down: negative momentum.', 'Medias de 20 y 50': '20 and 50 averages',
    'Promedio de las últimas 20 y 50 velas. Por encima: tendencia alcista.': 'Average of the last 20 and 50 candles. Price above both: uptrend.', 'Un período de precio: 1 hora en cripto, 1 día en acciones.': 'One price period: 1 hour for crypto, 1 day for stocks.',
}
EN.update({'Ir a la página Inicio': 'Go to the Home page', 'Ir a la página Resumen': 'Go to the Overview page', 'Ir a la página Señales': 'Go to the Signals page',
           'Ir a la página Mercado': 'Go to the Market page', 'Ir a la página Calidad': 'Go to the Quality page', 'Ir a la página Guía': 'Go to the Guide page',
           'Ver el detalle en la página Señales': 'See the detail on the Signals page', 'Ver el detalle en la página Calidad': 'See the detail on the Quality page',
           'Filtrá por Tipo de activo': 'Filter by asset type', 'Filtrá por Fuente del dato': 'Filter by data source', 'Filtrá por Duración de la vela': 'Filter by candle length', 'Filtrá por Señal': 'Filter by signal',
           'Paso 1': 'Step 1', 'Paso 2': 'Step 2', 'Paso 3': 'Step 3', 'Paso 4': 'Step 4'})
for mismo in ('', 'RSI', 'MACD', '✕', '◎', '▲', '▼', '■', '✓', '⚠', '◔', '$', '±', 'Binance', 'Yahoo Finance', 'UTC', '1', '2', '3', '4'):
    EN[mismo] = mismo
EN_VALORES = set(EN.values())


def T(x):
    """Texto de la interfaz en el idioma activo. Registra lo que falta traducir."""
    if LANG == 'es' or not isinstance(x, str):
        return x
    if x in EN:
        return EN[x]
    if x in EN_VALORES:
        return x
    FALTANTES.add(x)
    return x


def mname(m):
    return EN_MEASURES.get(m, m) if LANG == 'en' else m


def cname(ent, prop):
    return EN_COLS.get((ent, prop), prop) if LANG == 'en' else prop


def pid(key):
    return PG[LANG][key]


def L(v):
    return {"expr": {"Literal": {"Value": v}}}


def s(x):
    return L("'" + x.replace("'", "''") + "'")


def n(x):
    return L(f"{x}D")


def b(x):
    return L("true" if x else "false")


def col(c):
    return {"solid": {"color": s(c)}}


def M(m):
    return {"Expression": {"SourceRef": {"Entity": "_Medidas"}}, "Property": mname(m)}


def mcol(m):
    return {"solid": {"color": {"expr": {"Measure": M(m)}}}}


def CF(ent, prop):
    return {"Column": {"Expression": {"SourceRef": {"Entity": ent}}, "Property": cname(ent, prop)}}


def C(ent, prop, disp=None, active=None):
    prop = cname(ent, prop)
    p = {"field": CF(ent, prop), "queryRef": f"{ent}.{prop}", "nativeQueryRef": prop}
    if disp:
        p["displayName"] = T(disp)
    if active:
        p["active"] = True
    return p


def Me(prop, disp=None):
    prop = mname(prop)
    p = {"field": {"Measure": M(prop)}, "queryRef": f"_Medidas.{prop}", "nativeQueryRef": prop}
    if disp:
        p["displayName"] = T(disp)
    return p


def cont(title=None, alt=None, extra=None, subtitle=None):
    if isinstance(title, str):
        title = T(title)
    o = {"title": [{"properties": ({"show": b(True), "text": (title if isinstance(title, dict) else s(title))} if title else {"show": b(False)})}],
         "subTitle": [{"properties": ({"show": b(True), "text": subtitle} if subtitle else {"show": b(False)})}]}
    if alt:
        o["general"] = [{"properties": {"altText": s(T(alt))}}]
    if extra:
        o.update(extra)
    return o


class Page:
    def __init__(self, key):
        self.key = key
        self.pid = pid(key)
        self.vis = []
        self.z = 0

    def add(self, name, x, y, w, h, vtype, query=None, objects=None, container=None, extra=None):
        assert all(v % 8 == 0 for v in (x, y, w, h)), (name, x, y, w, h)
        objects = copy.deepcopy(objects or {})
        container = copy.deepcopy(container or cont())
        if vtype == 'card':
            # Use the supported card visual for narrative text as well as KPIs.
            vtype = 'cardVisual'
            query = copy.deepcopy(query)
            query['queryState']['Data'] = query['queryState'].pop('Values')
            chico = name.startswith(('hdr_', 'ftr_'))
            objects = {
                'label': [{'properties': {'show': b(False)}, 'selector': {'id': 'default'}}],
                'value': [{'properties': {'fontSize': n(13 if name.startswith('hdr_') else 11 if name.startswith('ftr_') else 15),
                                          'fontColor': col(MUTED if chico else INK),
                                          'textWrap': b(True), 'horizontalAlignment': s('right' if name.startswith('ftr_') else 'left')}, 'selector': {'id': 'default'}}]}
        if vtype == 'cardVisual':
            defaults = {
                'outline': {'show': b(False)},
                'layout': {**{k: n(0) for k in ('topOuterMargin', 'bottomOuterMargin', 'leftOuterMargin', 'rightOuterMargin', 'paddingUniform')}},
                'padding': {'paddingSelection': s('Custom'), **{k: n(0) for k in ('topMargin', 'bottomMargin', 'leftMargin', 'rightMargin')}},
                'cardCalloutArea': {'paddingUniform': n(0)},
                'fill': {'show': b(False)},
                'fillCustom': {'show': b(False)},
                'borderCustom': {'show': b(False)},
                'shadowCustom': {'show': b(False)},
            }
            for key, props in defaults.items():
                objects[key] = [{'properties': props, 'selector': {'id': 'default'}}]
            if name.startswith(('hdr_', 'ftr_')):
                container['padding'] = [{'properties': {k: n(0) for k in ('top', 'bottom', 'left', 'right')}}]
                container['border'] = [{'properties': {'show': b(False)}}]
                container['dropShadow'] = [{'properties': {'show': b(False)}}]
            if name.startswith('hdr_'):
                h = 32
        if vtype in ('lineChart', 'areaChart'):
            objects.setdefault('lineStyles', [{'properties': {}}])
            for style in objects['lineStyles']:
                style['properties'].update(showMarker=b(False), strokeShow=b(True))
                style['properties'].setdefault('strokeWidth', n(3))
            objects['labels'] = [{'properties': {'show': b(False)}}]
        if vtype == 'slicer':
            objects['items'] = [{'properties': {'textSize': n(13), 'fontColor': col(INK), 'padding': n(6)}}]
        self.z += 10
        v = {"$schema": VSCH, "name": name,
             "position": {"x": x, "y": y, "z": self.z, "height": h, "width": w, "tabOrder": self.z},
             "visual": {"visualType": vtype, "query": query or {"queryState": {}}, "objects": objects or {},
                        "visualContainerObjects": container, "drillFilterOtherVisuals": True}}
        if extra:
            v.update(extra)
        self.vis.append(v)
        return v

    def text(self, name, x, y, w, h, text, size=10, color=MUTED, bold=False, halign='left', valign='middle', alt=None, fill=None, extra_cont=None, outline=None, radius=12):
        text = T(text)
        tp = {"show": b(True), "text": s(text), "fontSize": n(size), "fontColor": col(color), "bold": b(bold),
              "horizontalAlignment": s(halign), "verticalAlignment": s(valign),
              "leftMargin": n(0), "rightMargin": n(0), "topMargin": n(0), "bottomMargin": n(0)}
        fl = [{"properties": {"show": b(False)}}]
        if fill:
            fl = [{"properties": {"show": b(True), "fillColor": col(fill)}}, {"properties": {"fillColor": col(fill)}, "selector": {"id": "default"}}]
        ol = [{"properties": {"show": b(False)}}]
        if outline:
            ol = [{"properties": {"show": b(True), "lineColor": col(outline), "weight": n(1)}}, {"properties": {"lineColor": col(outline), "weight": n(1)}, "selector": {"id": "default"}}]
        obj = {"fill": fl, "outline": ol,
               "text": [{"properties": tp}, {"properties": tp, "selector": {"id": "default"}}]}
        if fill or outline:
            obj["shape"] = [{"properties": {"rectangleRoundedCurve": n(radius)}}]
        return self.add(name, x, y, w, h, 'shape', objects=obj, container=cont(alt=alt or text, extra=extra_cont))

    def button(self, name, x, y, w, h, text, link, alt, fill='#FFFFFF', fcolor=MUTED, outline=None, size=12, disabled=None, bold=False):
        # disabled: texto que muestra el botón cuando no puede actuar. Estados hover/pressed y glow en los primarios.
        text, alt = T(text), T(alt)
        primario = fill == PRIMARY
        hover = '#4338CA' if primario else '#F1F5F9'
        obj = {"text": [{"properties": {"show": b(True)}}, {"properties": {"text": s(text), "fontSize": n(size), "fontColor": col(fcolor), "bold": b(bold)}, "selector": {"id": "default"}},
                        {"properties": {"text": s(text), "fontSize": n(size), "fontColor": col('#FFFFFF' if primario else INK), "bold": b(True)}, "selector": {"id": "hover"}}]
               + ([{"properties": {"text": s(T(disabled)), "fontSize": n(size), "fontColor": col(MUTED)}, "selector": {"id": "disabled"}}] if disabled else []),
               "fill": [{"properties": {"show": b(True)}}, {"properties": {"fillColor": col(fill)}, "selector": {"id": "default"}},
                        {"properties": {"fillColor": col(hover), "transparency": n(0)}, "selector": {"id": "hover"}},
                        {"properties": {"fillColor": col('#3730A3' if primario else '#E2E8F0')}, "selector": {"id": "pressed"}}]
               + ([{"properties": {"fillColor": col('#E2E8F0')}, "selector": {"id": "disabled"}}] if disabled else []),
               "glow": [{"properties": {"show": b(False)}}] + ([{"properties": {"show": b(True), "color": col(PRIMARY), "transparency": n(60), "shadowBlur": n(12)}, "selector": {"id": "hover"}}] if primario else []),
               "outline": [{"properties": {"show": b(outline is not None)}}] + ([{"properties": {"lineColor": col(outline), "weight": n(1)}, "selector": {"id": "default"}}] if outline else []),
               "shape": [{"properties": {"rectangleRoundedCurve": n(8)}}]}
        # Serialización nativa de Desktop: 'Drillthrough' con t minúscula y showDefaultTooltip.
        # 'DrillThrough' (T mayúscula) rompe el renderizador (getVisualLinkTypeLabel).
        lk = {"show": b(True), "tooltip": s(alt), "showDefaultTooltip": b(True)}
        lk.update(link)
        return self.add(name, x, y, w, h, 'actionButton', objects=obj, container=cont(alt=alt, extra={"visualLink": [{"properties": lk}]}))

    def kpi(self, name, x, y, w, h, title, measure, alt, vcolor=None, size=32, label=None, titled=False, glyph=None, tint=None, gcolor=None):
        # label: texto visible bajo el valor (lenguaje simple). glyph: ícono en un tile de color a la izquierda.
        v = {"fontSize": n(size), "bold": b(True), "labelDisplayUnits": n(1), "horizontalAlignment": s('left')}
        if vcolor:
            v["fontColor"] = vcolor
        lab = {"show": b(label is not None), "fontSize": n(12), "fontColor": col(MUTED), "horizontalAlignment": s('left')}
        if label is not None:
            lab["text"] = s(T(label))
        q = {"queryState": {"Data": {"projections": [Me(measure)]}}}
        c = cont(title if titled else None, alt)
        if glyph:
            # el ícono es una forma superpuesta a la izquierda; la tarjeta deja ese espacio con el margen del contenedor
            c['padding'] = [{'properties': {'top': n(8), 'bottom': n(8), 'left': n(72), 'right': n(8)}}]
        card = self.add(name, x, y, w, h, 'cardVisual', q,
                        {"label": [{"properties": lab, "selector": {"id": "default"}}],
                         "value": [{"properties": v, "selector": {"id": "default"}}],
                         "padding": [{"properties": {"paddingUniform": n(8)}, "selector": {"id": "default"}}],
                         "layout": [{"properties": {"paddingUniform": n(0)}, "selector": {"id": "default"}}],
                         "outline": [{"properties": {"show": b(False)}, "selector": {"id": "default"}}]}, c)
        if glyph:
            self.text(name + '_icono', x + 16, y + (h - 40) // 2, 40, 40, glyph, 18, gcolor or PRIMARY, True, 'center', 'middle', alt=alt, fill=tint or '#E0E7FF', radius=10)
        return card

    def hotspot(self, name, x, y, w, h, link, alt):
        # Botón transparente que cubre una tarjeta: la hace clicable y la resalta (tinte suave + borde) al pasar el mouse.
        alt = T(alt)
        obj = {"text": [{"properties": {"show": b(False)}}],
               "fill": [{"properties": {"show": b(True), "fillColor": col('#FFFFFF'), "transparency": n(100)}},
                        {"properties": {"fillColor": col('#FFFFFF'), "transparency": n(100)}, "selector": {"id": "default"}},
                        {"properties": {"fillColor": col(PRIMARY), "transparency": n(94)}, "selector": {"id": "hover"}}],
               "outline": [{"properties": {"show": b(True), "lineColor": col('#FFFFFF'), "transparency": n(100), "weight": n(2)}},
                           {"properties": {"lineColor": col('#FFFFFF'), "transparency": n(100)}, "selector": {"id": "default"}},
                           {"properties": {"lineColor": col(PRIMARY), "transparency": n(0), "weight": n(2)}, "selector": {"id": "hover"}}],
               "shape": [{"properties": {"rectangleRoundedCurve": n(12)}}]}
        lk = {"show": b(True), "tooltip": s(alt), "showDefaultTooltip": b(True)}
        lk.update(link)
        return self.add(name, x, y, w, h, 'actionButton', objects=obj, container=cont(alt=alt, extra={"visualLink": [{"properties": lk}]}))

    def card_texto(self, name, x, y, w, h, title, body, num=None, size=12, title_size=14):
        # Tarjeta blanca con título y texto estáticos; con num, un tile numerado a la izquierda del título.
        self.text(name, x, y, w, h, '', 10, MUTED, fill='#FFFFFF', outline=BORDE, alt=title)
        tx = x + 16
        if num is not None:
            self.text(name + '_num', x + 16, y + 16, 40, 40, str(num), 16, PRIMARY, True, 'center', 'middle', alt=f'Paso {num}', fill='#E0E7FF', radius=10)
            tx = x + 72
        self.text(name + '_titulo', tx, y + 16, x + w - 16 - tx, 40, title, title_size, INK, True, valign='top', alt=title)
        ty = y + (64 if num is not None else 40)
        self.text(name + '_texto', x + 16, ty, w - 32, y + h - 8 - ty, body, size, MUTED, valign='top', alt=body)

    def narrativa(self, name, x, y, w, h, measure, title, alt, size=13):
        # Texto largo derivado de una medida: cardVisual con textWrap (comprobado en Desktop 2.159, hasta ~6 líneas
        # si la altura alcanza). multiRowCard y shape no sirven: no ajustan línea / no aceptan medida; accentBar deja la tarjeta en blanco.
        q = {"queryState": {"Values": {"projections": [Me(measure)]}}}
        v = self.add(name, x, y, w, h, 'card', q, None, cont(title, alt))
        v['visual']['objects']['value'][0]['properties']['fontSize'] = n(size)
        v['visual']['objects']['value'][0]['properties']['fontColor'] = col('#334155')
        return v


def nav_link(key):
    return {"type": s('PageNavigation'), "navigationSection": s(pid(key))}


def header(p, with_filters=True):
    p.text('hdr_overline', 24, 8, 456, 16, 'RADAR DE SEÑALES · DATOS DE PRUEBA', 11, MUTED, True)
    p.text('hdr_titulo', 24, 24, 456, 40, TITLES[p.key], 26, INK, True)
    # Navegación con botones (no pageNavigator): así cada idioma muestra solo sus páginas y la actual va resaltada.
    for i, key in enumerate(KEYS):
        actual = key == p.key
        p.button(f'nav_{key}', 496 + i * 88, 16, 80, 40, NAMES[key], nav_link(key), f'Ir a la página {NAMES[key]}',
                 fill=PRIMARY if actual else '#FFFFFF', fcolor='#FFFFFF' if actual else MUTED, outline=None if actual else '#E2E8F0', size=12, bold=actual)
    # Cambio de idioma: va a la misma página en el otro idioma.
    otro = {'es': 'en', 'en': 'es'}[LANG]
    p.button('hdr_idioma', 1024, 16, 40, 40, 'EN', {"type": s('PageNavigation'), "navigationSection": s(PG[otro][p.key])}, 'Ver este informe en inglés',
             fill='#FFFFFF', fcolor=PRIMARY, outline=PRIMARY, size=12, bold=True)
    # Acción nativa «Borrar todas las segmentaciones»: un marcador con remove general.filter no limpia selectores sincronizados.
    p.button('hdr_restablecer', 1072, 16, 96, 40, 'Restablecer', {"type": s('ClearAllSlicers')}, 'Quita las selecciones de todos los selectores', fill='#FFFFFF', fcolor=MUTED, outline='#E2E8F0')
    if with_filters:
        p.button('hdr_filtros', 1176, 16, 80, 40, 'Filtros', {"type": s('Bookmark'), "bookmark": s(BM[p.pid][0])}, 'Abre el panel de filtros', fill=PRIMARY, fcolor='#FFFFFF')
    p.add('hdr_subtitulo', 24, 64, 1232, 32, 'card',
          {"queryState": {"Values": {"projections": [Me('Subtítulo filtros')]}}},
          {"labels": [{"properties": {"fontSize": n(13), "color": col(MUTED)}}],
           "categoryLabels": [{"properties": {"show": b(False)}}]},
          cont(alt='Resumen de los filtros activos', extra={"background": [{"properties": {"show": b(False)}}]}))


def footer(p):
    p.text('ftr_disclaimer', 24, 688, 880, 24, 'Datos de prueba con fechas simuladas: la fuerza de una señal no es una recomendación de compra ni de venta.', 11, MUTED, alt='Aviso sobre los datos de prueba')
    p.add('ftr_actualizacion', 920, 688, 336, 24, 'card',
          {"queryState": {"Values": {"projections": [Me('Pie de actualización')]}}}, None,
          cont(alt='Fecha y hora UTC de la última corrida simulada', extra={"background": [{"properties": {"show": b(False)}}]}))


PANEL = ['flt_panel', 'flt_cerrar', 'flt_tipo', 'flt_fuente', 'flt_timeframe', 'flt_senal']


def slicer(p, name, ent, prop, title, y, grp):
    q = {"queryState": {"Values": {"projections": [C(ent, prop, active=True)]}}}
    o = {"data": [{"properties": {"mode": s('Dropdown')}}],
         "header": [{"properties": {"show": b(True), "textSize": n(12),
                                    "fontColor": col(MUTED),
                                    "text": s(T(title))}}]}
    v = p.add(name, 936, y, 304, 64, 'slicer', q, o, cont(None, f'Filtrá por {title}', extra={"background": [{"properties": {"show": b(False)}}]}),
          {"isHidden": True})
    # Los selectores en inglés usan otras columnas: grupo de sincronización propio por idioma.
    v['visual']['syncGroup'] = {"groupName": grp + ('' if LANG == 'es' else '_en'), "fieldChanges": True, "filterChanges": True}


def panel(p):
    p.text('flt_panel', 920, 96, 336, 360, '', 11, MUTED, fill='#FFFFFF', alt='Panel de filtros', outline='#E2E8F0')
    p.button('flt_cerrar', 1208, 104, 40, 24, '✕', {"type": s('Bookmark'), "bookmark": s(BM[p.pid][1])}, 'Cierra el panel de filtros', fill='#FFFFFF', fcolor=MUTED)
    slicer(p, 'flt_tipo', 'dim_activo', 'Tipo de activo', 'Tipo de activo', 152, 'g_tipo')
    slicer(p, 'flt_fuente', 'dim_activo', 'Fuente de datos', 'Fuente del dato', 224, 'g_fuente')
    slicer(p, 'flt_timeframe', 'dim_activo', 'Vela', 'Duración de la vela', 296, 'g_tf')
    slicer(p, 'flt_senal', 'dim_senal', 'Señal en palabras', 'Señal', 368, 'g_senal')
    for v in p.vis:
        if v['name'] in ('flt_panel', 'flt_cerrar'):
            v['isHidden'] = True
        if v['name'] in PANEL:
            v['position']['z'] = 5000 + PANEL.index(v['name'])
            v['position']['tabOrder'] = v['position']['z']


BM = {p: ('bmOpen' + p[:8], 'bmClose' + p[:8]) for lang in PG for p in PG[lang].values()}

SIG = [('Señales compra', GREEN), ('Señales esperar', MUTED), ('Señales venta', RED)]
# Nombres cortos para leyendas en gráficos angostos (sin 'Señales ...' truncado).
SIG_SHORT = {'Señales compra': 'Compra', 'Señales esperar': 'Espera', 'Señales venta': 'Venta'}


def dp_series():
    return [{"properties": {"fill": col(c)}, "selector": {"metadata": f"_Medidas.{m}"}} for m, c in SIG]


def legend_top():
    return {"legend": [{"properties": {"show": b(True), "position": s('Top'), "fontSize": n(13)}}]}


def axes(cat=True, margen=None, ancho_cat=None, size=13):
    # margen: % máximo del ancho para las etiquetas de categoría; ancho_cat: ancho mínimo de cada barra (px).
    c = {"showAxisTitle": b(False), "fontSize": n(size)}
    if margen:
        c["maxMarginFactor"] = n(margen)
    if ancho_cat:
        c.update(preferredCategoryWidth=n(ancho_cat), innerPadding=n(25))
    return {"categoryAxis": [{"properties": c}],
            "valueAxis": [{"properties": {"showAxisTitle": b(False), "fontSize": n(13), "gridlineShow": b(True), "gridlineStyle": s('dotted'), "gridlineColor": col('#E2E8F0')}}]}


def table_obj(extra_values=None, bars=None, size=14, pad=10):
    vals = [{"properties": {"fontSize": n(size), "backColor": col('#FFFFFF'), "backColorPrimary": col('#FFFFFF'), "backColorSecondary": col('#F8FAFC'), "fontColor": col('#334155'), "wordWrap": b(False)}}]
    vals += extra_values or []
    o = {"values": vals,
         "columnHeaders": [{"properties": {"fontSize": n(13), "fontColor": col(MUTED), "backColor": col('#FFFFFF'), "bold": b(True), "autoSizeColumnWidth": b(False), "columnAdjustment": s('growToFit'), "outlineStyle": n(0)}}],
         "grid": [{"properties": {"gridHorizontal": b(True), "gridHorizontalColor": col('#EEF2F7'), "gridHorizontalWeight": n(1), "gridVertical": b(False), "rowPadding": n(pad), "outlineWeight": n(0), "textSize": n(size)}}],
         "total": [{"properties": {"totals": b(False)}}]}
    if bars:
        o["columnFormatting"] = [{"properties": {}}] + [
            {"properties": {"dataBars": {"positiveColor": col(GREEN), "negativeColor": col(RED), "axisColor": col('#CBD5E1'), "reverseDirection": b(False), "hideText": b(False)}},
             "selector": {"metadata": f"_Medidas.{mname(m)}"}} for m in bars]
    return o


def cf(measure_prop, metadata, kind):
    return {"properties": {kind: mcol(measure_prop)}, "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}], "metadata": f"_Medidas.{mname(metadata)}"}}


def interactions(p, slicers, sources, targets):
    out = []
    targets = list(dict.fromkeys(targets + ['hdr_subtitulo']))
    for a in slicers:
        for t in slicers:
            if a != t:
                out.append({"source": a, "target": t, "type": "NoFilter"})
    for a in sources:
        for t in targets:
            if a != t:
                out.append({"source": a, "target": t, "type": "DataFilter"})
    return out


def literal_txt(x):
    return {"Literal": {"Value": "'" + T(x).replace("'", "''") + "'"}}


# ---------------- pages ----------------
def build_resumen():
    p = Page('res')
    header(p)
    kp = [('kpi_activos', 24, 232, 'Activos seguidos', 'Activos monitoreados', 'Cantidad de activos con una señal vigente', None, '◎', '#E0E7FF', PRIMARY),
          ('kpi_compra', 272, 232, 'Señales de compra', 'Señales compra', 'Activos cuya señal vigente es de compra', col(GREEN), '▲', '#DCFCE7', GREEN),
          ('kpi_venta', 520, 232, 'Señales de venta', 'Señales venta', 'Activos cuya señal vigente es de venta', col(RED), '▼', '#FEE2E2', RED),
          ('kpi_espera', 768, 232, 'En espera', 'Señales esperar', 'Activos cuya señal vigente es esperar', None, '■', '#F1F5F9', MUTED),
          ('kpi_validos', 1016, 240, 'Con dato al día', 'Datos válidos %', 'Porcentaje de activos cuyo último dato es válido', None, '✓', '#FEF3C7', '#D97706')]
    for name, x, w, label, m, alt, color, glyph, tint, gcolor in kp:
        p.kpi(name, x, 96, w, 104, label, m, alt, vcolor=color, size=32, label=label, glyph=glyph, tint=tint, gcolor=gcolor)
        destino = 'cal' if name == 'kpi_validos' else 'sen'
        p.hotspot(name + '_ir', x, 96, w, 104, nav_link(destino), f'Ver el detalle en la página {NAMES[destino]}')
    dia_series = [('Activos en compra (día)', 'Compra', GREEN), ('Activos en espera (día)', 'Espera', MUTED), ('Activos en venta (día)', 'Venta', RED)]
    p.add('graf_senales_dia', 24, 216, 816, 208, 'columnChart',
          {"queryState": {"Category": {"projections": [C('fact_senales', 'Día de corrida', 'Día', True)]},
                          "Y": {"projections": [Me(m, d) for m, d, _ in dia_series]}},
           "sortDefinition": {"sort": [{"field": CF('fact_senales', 'Día de corrida'), "direction": "Ascending"}], "isDefaultSort": True}},
          dict(axes(), dataPoint=[{"properties": {"fill": col(c)}, "selector": {"metadata": f"_Medidas.{m}"}} for m, _, c in dia_series],
               labels=[{"properties": {"show": b(True), "fontSize": n(11), "color": col('#FFFFFF')}}], **legend_top()),
          cont('Cuántos activos estaban en compra, espera o venta cada día', 'Al cierre de cada día simulado, cuántos activos tenían señal de compra, de espera o de venta'))
    p.vis[-1]['visual']['objects']['categoryAxis'][0]['properties']['axisType'] = s('Categorical')
    p.add('graf_senales_tipo', 856, 216, 400, 208, 'barChart',
          {"queryState": {"Category": {"projections": [C('dim_activo', 'Tipo de activo', 'Tipo de activo', True)]}, "Y": {"projections": [Me(m, SIG_SHORT[m]) for m, _ in SIG]}}},
          dict(axes(margen=45, size=12), dataPoint=dp_series(), **legend_top()),
          cont('Señales según el tipo de activo', 'Cuántas señales de compra, espera y venta hay por tipo de activo'))
    p.add('graf_fuerza_activo', 24, 440, 608, 248, 'barChart',
          {"queryState": {"Category": {"projections": [C('dim_activo', 'ticker', 'Activo', True)]}, "Y": {"projections": [Me('Fuerza actual', 'Fuerza')]}},
           "sortDefinition": {"sort": [{"field": {"Measure": M('Fuerza actual')}, "direction": "Descending"}], "isDefaultSort": False}},
          dict(axes(ancho_cat=12, size=12), dataPoint=[{"properties": {"fill": mcol('Color fuerza')}, "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}]}}],
               labels=[{"properties": {"show": b(True), "fontSize": n(11), "color": col(INK)}}], legend=[{"properties": {"show": b(False)}}]),
          cont('Fuerza de la señal de cada activo (de −9 a +9)', 'Puntaje heurístico de la señal vigente: positivo a favor de comprar, negativo a favor de vender'))
    p.vis[-1]['visual']['objects']['valueAxis'][0]['properties'].update(start=n(-9), end=n(9), show=b(False), gridlineShow=b(False))
    p.narrativa('card_lectura', 648, 440, 608, 248, 'Lectura del radar', 'Qué dice el radar hoy', 'Lectura en palabras simples de las señales vigentes')
    footer(p)
    panel(p)
    charts = ['graf_senales_dia', 'graf_senales_tipo', 'graf_fuerza_activo']
    kp_names = [k[0] for k in kp]
    return p, interactions(p, PANEL[2:], charts, charts + kp_names + ['card_lectura'])


def build_senales():
    p = Page('sen')
    header(p)
    cols = [C('dim_activo', 'ticker', 'Activo'), Me('Señal con ícono', 'Señal'), Me('Fuerza actual', 'Fuerza'), Me('RSI última vela', 'RSI'),
            Me('Último cierre', 'Cierre'), C('dim_activo', 'moneda', 'Moneda'), C('dim_activo', 'Vela', 'Vela'),
            Me('Estado chip', 'Dato'), Me('Vela actual (UTC)', 'Último dato (UTC)')]
    p.add('tabla_senales', 24, 96, 960, 344, 'tableEx',
          {"queryState": {"Values": {"projections": cols}},
           "sortDefinition": {"sort": [{"field": {"Measure": M('Fuerza actual')}, "direction": "Descending"}], "isDefaultSort": False}},
          table_obj([cf('Fondo señal', 'Señal con ícono', 'backColor'), cf('Color señal', 'Señal con ícono', 'fontColor'),
                     cf('Fondo estado', 'Estado chip', 'backColor'), cf('Color estado', 'Estado chip', 'fontColor')], ['Fuerza actual'], size=13, pad=5),
          cont('Señal actual de cada activo', 'Tocá un activo para ver su ficha debajo'))
    v = p.add('sel_activo', 1000, 96, 256, 88, 'slicer',
          {"queryState": {"Values": {"projections": [C('dim_activo', 'ticker', 'Activo', active=True)]}}},
          {"data": [{"properties": {"mode": s('Dropdown')}}],
           "header": [{"properties": {"show": b(True), "textSize": n(12), "fontColor": col(MUTED),
                                      "text": s(T('Ver la ficha de:'))}}],
           "selection": [{"properties": {"singleSelect": b(True)}}]},
          cont(None, 'Elegí un activo para ver su ficha, sin tener que buscarlo en la tabla'))
    v['visual']['syncGroup'] = {"groupName": 'g_activo', "fieldChanges": True, "filterChanges": True}
    # Navegación simple (no obtención de detalles): el selector 'Ver la ficha de' está sincronizado con el de Mercado,
    # así que el activo elegido se mantiene al cambiar de página y nunca queda un filtro de drillthrough colgado.
    p.button('btn_ir_mercado', 1000, 200, 256, 48, 'Ver su evolución ▸', nav_link('mer'),
             'Abre la página Mercado con el activo elegido en el selector', fill=PRIMARY, fcolor='#FFFFFF')
    p.text('txt_ayuda', 1000, 264, 256, 176, 'Tocá un activo en la tabla y su ficha aparece debajo en palabras simples. Elegilo arriba y «Ver su evolución» abre la página Mercado con su precio y su RSI.', 13, MUTED, valign='top', alt='Cómo usar esta página')
    p.narrativa('card_detalle_activo', 24, 456, 1232, 232, 'Detalle del activo seleccionado', 'Ficha del activo elegido', 'Detalle en palabras simples del activo elegido en la tabla o en el selector')
    footer(p)
    panel(p)
    inter = interactions(p, PANEL[2:], ['tabla_senales', 'sel_activo'], ['card_detalle_activo'])
    inter += [{"source": 'sel_activo', "target": t, "type": "NoFilter"} for t in ['tabla_senales'] + PANEL[2:]]
    return p, inter


def build_mercado():
    p = Page('mer')
    header(p)
    v = p.add('chips_activo', 24, 104, 304, 104, 'slicer',
          {"queryState": {"Values": {"projections": [C('dim_activo', 'ticker', 'Activo', True)]}}},
          {"data": [{"properties": {"mode": s('Dropdown')}}],
           "header": [{"properties": {"show": b(True), "textSize": n(12), "fontColor": col(MUTED),
                                      "text": s(T('Activo graficado'))}}],
           "selection": [{"properties": {"singleSelect": b(True)}}]},
          cont(None, 'Elegí el activo de los gráficos; solo uno a la vez'))
    v['visual']['syncGroup'] = {"groupName": 'g_activo', "fieldChanges": True, "filterChanges": True}
    p.kpi('kpi_var_cierre', 344, 104, 296, 104, 'Variación del último cierre', 'Var % cierre', 'Cuánto varió el precio respecto del cierre anterior', label='Variación del último cierre', glyph='±', tint='#E0E7FF', gcolor=PRIMARY)
    p.kpi('kpi_rsi_ultimo', 656, 104, 288, 104, 'RSI actual (0 a 100)', 'RSI último', 'Momentum del último dato: por debajo de 30 suele estar barato, por encima de 70 caro', label='RSI actual (0 a 100)', glyph='◔', tint='#FEF3C7', gcolor='#D97706')
    p.kpi('kpi_cierre_ultimo', 960, 104, 296, 104, 'Último precio de cierre', 'Cierre último', 'Precio de cierre del último dato', label='Último precio de cierre', glyph='$', tint='#DCFCE7', gcolor=GREEN)
    ts = C('fact_precios', 'timestamp_utc', active=True)
    p.add('graf_cierre', 24, 216, 1232, 256, 'lineChart',
          {"queryState": {"Category": {"projections": [ts]}, "Y": {"projections": [Me('Cierre (vela)', 'Cierre'), Me('MA corta (vela)', 'Media de 20 periodos'), Me('MA larga (vela)', 'Media de 50 periodos')]}},
           "sortDefinition": {"sort": [{"field": CF('fact_precios', 'timestamp_utc'), "direction": "Ascending"}], "isDefaultSort": False}},
          dict(axes(), **legend_top(),
               lineStyles=[{"properties": {"areaShow": b(False)}},
                           {"properties": {"strokeWidth": n(2)}, "selector": {"metadata": "_Medidas.MA corta (vela)"}},
                           {"properties": {"strokeWidth": n(2)}, "selector": {"metadata": "_Medidas.MA larga (vela)"}}],
               zoom=[{"properties": {"show": b(True), "showOnCategoryAxis": b(True), "showOnValueAxis": b(False), "showLabels": b(False), "showTooltip": b(True)}}],
               dataPoint=[{"properties": {"fill": col(color)}, "selector": {"metadata": f"_Medidas.{measure}"}}
                          for measure, color in [('Cierre (vela)', PRIMARY), ('MA corta (vela)', '#0EA5E9'), ('MA larga (vela)', '#94A3B8')]]),
          cont({'expr': {'Measure': M('Título cierre')}}, 'Precio de cierre y sus medias de 20 y 50 periodos; el deslizador de abajo acerca un período', subtitle={'expr': {'Measure': M('Contexto del activo graficado')}}))

    def zona(idx, valor, nombre, color, region):
        return {"properties": {"show": b(True), "value": n(valor), "displayName": s(T(nombre)), "lineColor": col(color), "style": s('dashed'), "width": n(1),
                               "dataLabelShow": b(True), "dataLabelText": s('ValueAndName'), "dataLabelColor": col(color),
                               "shadeShow": b(True), "shadeRegion": s(region), "shadeColor": col(color), "shadeTransparency": n(90)},
                "selector": {"id": str(idx)}}
    p.add('graf_rsi', 24, 480, 1232, 208, 'lineChart',
          {"queryState": {"Category": {"projections": [ts]}, "Y": {"projections": [Me('RSI (vela)', 'RSI')]}},
           "sortDefinition": {"sort": [{"field": CF('fact_precios', 'timestamp_utc'), "direction": "Ascending"}], "isDefaultSort": False}},
          dict(axes(), legend=[{"properties": {"show": b(False)}}], lineStyles=[{"properties": {"areaShow": b(False), "strokeWidth": n(2.5)}}],
               y1AxisReferenceLine=[zona(1, 70, 'Zona cara', RED, 'after'), zona(2, 30, 'Zona barata', GREEN, 'before')],
               dataPoint=[{"properties": {"fill": col(PRIMARY)}, "selector": {"metadata": "_Medidas.RSI (vela)"}}]),
          cont('RSI: en la zona roja (más de 70) suele estar caro · en la verde (menos de 30), barato', 'Momentum de 14 periodos con las zonas de 30 y 70 sombreadas'))
    p.vis[-1]['visual']['objects']['valueAxis'][0]['properties'].update(start=n(0), end=n(100))
    footer(p)
    panel(p)
    return p, interactions(p, PANEL[2:] + ['chips_activo'], ['chips_activo', 'graf_cierre', 'graf_rsi'], ['graf_cierre', 'graf_rsi', 'kpi_var_cierre', 'kpi_rsi_ultimo', 'kpi_cierre_ultimo'])


def build_calidad():
    p = Page('cal')
    header(p)
    p.kpi('kpi_datos_validos', 24, 96, 400, 88, 'Activos con dato al día', 'Datos válidos %', 'Porcentaje de activos cuyo último dato es válido', size=28, label='Activos con dato al día', glyph='✓', tint='#DCFCE7', gcolor=GREEN)
    p.kpi('kpi_activos_obsoletos', 440, 96, 400, 88, 'Activos con dato desactualizado', 'Activos obsoletos', 'Activos cuyo último dato llegó hace demasiado tiempo', size=28, label='Activos con dato desactualizado', glyph='⚠', tint='#FEF3C7', gcolor='#D97706')
    p.kpi('kpi_horas_ultima_vela', 856, 96, 400, 88, 'Horas desde el último dato', 'Horas desde última vela', 'Cuántas horas pasaron desde el último dato recibido', size=28, label='Horas desde el último dato', glyph='◔', tint='#E0E7FF', gcolor=PRIMARY)
    p.add('graf_estado_dato', 24, 200, 312, 192, 'donutChart',
          {"queryState": {"Category": {"projections": [C('fact_senales', 'Estado del dato', 'Estado del dato', True)]}, "Y": {"projections": [Me('Activos monitoreados')]}}},
          {"legend": [{"properties": {"show": b(True), "position": s('Top'), "fontSize": n(12), "showTitle": b(False)}}],
           "labels": [{"properties": {"show": b(True), "fontSize": n(12), "labelStyle": s('Data value, percent of total'), "percentageLabelPrecision": n(0), "color": col(MUTED)}}],
           "dataPoint": [{"properties": {"fill": col(MUTED)}},
                         {"properties": {"fill": col('#F59E0B')}, "selector": {"data": [{"scopeId": {"Comparison": {"ComparisonKind": 0, "Left": CF('fact_senales', 'Estado del dato'), "Right": literal_txt('Desactualizado')}}}]}},
                         {"properties": {"fill": col(GREEN)}, "selector": {"data": [{"scopeId": {"Comparison": {"ComparisonKind": 0, "Left": CF('fact_senales', 'Estado del dato'), "Right": literal_txt('Válido')}}}]}}]},
          cont('Estado del último dato', 'Cuántos activos tienen su último dato válido y cuántos desactualizado'))
    p.add('graf_frescura_fuente', 352, 200, 312, 192, 'barChart',
          {"queryState": {"Category": {"projections": [C('dim_activo', 'Fuente de datos', 'Fuente', True)]}, "Y": {"projections": [Me('Horas desde última vela')]}}},
          dict(axes(margen=55, size=12), dataPoint=[{"properties": {"fill": col(PRIMARY)}}], legend=[{"properties": {"show": b(False)}}],
               labels=[{"properties": {"show": b(True), "fontSize": n(12), "color": col(INK)}}]),
          cont('Horas sin dato, por fuente', 'Cuántas horas pasaron desde el último dato de cada proveedor'))
    p.narrativa('card_lectura_calidad', 680, 200, 576, 192, 'Lectura de calidad', 'Qué está pasando con los datos', 'Lectura en palabras simples del estado de los datos')
    cols = [C('dim_activo', 'ticker', 'Activo'), C('dim_activo', 'Fuente de datos', 'Fuente'), C('dim_activo', 'Vela', 'Vela'),
            Me('Horas desde última vela', 'Horas sin dato nuevo'), Me('Vela actual (UTC)', 'Último dato (UTC)'), Me('Estado chip', 'Dato')]
    p.add('tabla_obsoletos', 24, 408, 1232, 280, 'tableEx',
          {"queryState": {"Values": {"projections": cols}},
           "sortDefinition": {"sort": [{"field": {"Measure": M('Horas desde última vela')}, "direction": "Descending"}], "isDefaultSort": False}},
          table_obj([cf('Fondo estado', 'Estado chip', 'backColor'), cf('Color estado', 'Estado chip', 'fontColor')], size=12, pad=2),
          cont('Antigüedad del dato de cada activo', 'Todos los activos, del dato más viejo al más nuevo'))
    footer(p)
    panel(p)
    ch = ['graf_estado_dato', 'graf_frescura_fuente', 'tabla_obsoletos']
    return p, interactions(p, PANEL[2:], ch, ch + ['kpi_datos_validos', 'kpi_activos_obsoletos', 'kpi_horas_ultima_vela', 'card_lectura_calidad'])


def build_inicio():
    p = Page('ini')
    p.text('ini_panel', 0, 0, 480, 720, '', 10, MUTED, fill=NAVY, radius=0, alt='Panel de presentación')
    p.text('ini_marca', 40, 56, 400, 24, 'RADAR DE SEÑALES', 12, '#93C5FD', True, alt='Marca')
    p.text('ini_titulo', 40, 96, 400, 200, 'Señales técnicas para cripto y acciones, en palabras simples', 28, '#FFFFFF', True, valign='top', alt='Título del informe')
    p.text('ini_bajada', 40, 304, 400, 120, 'Descarga velas de Binance y Yahoo Finance, calcula RSI, MACD, medias y volumen, y resume cada activo en una señal de compra, espera o venta, con su fuerza y sus motivos.', 14, '#CBD5E1', valign='top', alt='Qué hace el radar')
    p.text('ini_badge', 40, 440, 336, 32, 'DATOS DE PRUEBA · FECHAS SIMULADAS', 11, '#93C5FD', True, 'center', fill='#1E3A5F', radius=16, alt='Aviso: datos de prueba')
    otro = {'es': 'en', 'en': 'es'}[LANG]
    p.button('ini_idioma', 40, 496, 160, 40, 'EN', {"type": s('PageNavigation'), "navigationSection": s(PG[otro]['ini'])}, 'Ver este informe en inglés',
             fill='#1E3A5F', fcolor='#FFFFFF', outline='#3B5A80', size=12, bold=True)
    p.text('ini_pie', 40, 608, 400, 80, 'Proyecto de portfolio con datos sintéticos. Señales heurísticas: la fuerza no es una probabilidad ni una recomendación de inversión.', 11, '#94A3B8', valign='top', alt='Aviso legal')
    p.text('ini_hoy', 520, 56, 736, 24, 'HOY EN EL RADAR', 12, MUTED, True, alt='Sección: hoy en el radar')
    p.kpi('ini_kpi_activos', 520, 88, 232, 120, 'Activos seguidos', 'Activos monitoreados', 'Cantidad de activos con una señal vigente', size=36, label='Activos seguidos', glyph='◎', tint='#E0E7FF', gcolor=PRIMARY)
    p.kpi('ini_kpi_compra', 768, 88, 232, 120, 'Señales de compra', 'Señales compra', 'Activos cuya señal vigente es de compra', vcolor=col(GREEN), size=36, label='Señales de compra', glyph='▲', tint='#DCFCE7', gcolor=GREEN)
    p.kpi('ini_kpi_venta', 1016, 88, 240, 120, 'Señales de venta', 'Señales venta', 'Activos cuya señal vigente es de venta', vcolor=col(RED), size=36, label='Señales de venta', glyph='▼', tint='#FEE2E2', gcolor=RED)
    for key, x, w in (('activos', 520, 232), ('compra', 768, 232), ('venta', 1016, 240)):
        p.hotspot(f'ini_kpi_{key}_ir', x, 88, w, 120, nav_link('sen'), 'Ver la señal de cada activo')
    p.text('ini_que', 520, 240, 736, 24, '¿QUÉ QUERÉS VER?', 12, MUTED, True, alt='Sección: qué querés ver')
    tarjetas = [('res', 520, 272, 'El mercado en un vistazo ▸', 'Cuántos activos están en compra, espera o venta, y qué dice el radar hoy.'),
                ('sen', 888, 272, 'La señal de cada activo ▸', 'Una fila por activo con su fuerza, RSI y precio, y una ficha en palabras simples.'),
                ('mer', 520, 400, 'La evolución de un activo ▸', 'Precio con medias de 20 y 50 velas y RSI con sus zonas de 30 y 70.'),
                ('cal', 888, 400, 'La confiabilidad de los datos ▸', 'Qué activos tienen el dato al día y cuáles quedaron desactualizados.')]
    for key, x, y, titulo, texto in tarjetas:
        p.card_texto(f'ini_card_{key}', x, y, 368, 112, titulo, texto, title_size=15)
        p.hotspot(f'ini_ir_{key}', x, y, 368, 112, nav_link(key), f'Ir a la página {NAMES[key]}')
    p.button('ini_guia', 520, 544, 368, 48, 'Cómo leer este radar ▸', nav_link('guia'), 'Abre la guía de lectura', fill=PRIMARY, fcolor='#FFFFFF', size=13)
    p.add('ftr_actualizacion', 904, 552, 352, 32, 'card',
          {"queryState": {"Values": {"projections": [Me('Pie de actualización')]}}}, None,
          cont(alt='Fecha y hora UTC de la última corrida simulada', extra={"background": [{"properties": {"show": b(False)}}]}))
    return p, []


def build_guia():
    p = Page('guia')
    header(p, with_filters=False)
    pasos = [('Descarga de precios', 'Velas cerradas de Binance (cripto, cada hora) y Yahoo Finance (acciones, cada día).'),
             ('Indicadores clásicos', 'RSI, MACD, medias de 20 y 50 velas, volumen relativo y rupturas de máximos o mínimos.'),
             ('Una señal por activo', 'Cada indicador suma o resta puntos. La fuerza va de −9 a +9 y define compra, espera o venta.'),
             ('Control de calidad', 'Un dato viejo, con error o incompleto queda marcado y nunca se confunde con una señal válida.')]
    for i, (titulo, texto) in enumerate(pasos):
        p.card_texto(f'guia_paso_{i + 1}', 24 + i * 312, 96, 296, 144, titulo, texto, num=i + 1)
    cols = [C('dim_senal', 'Señal en palabras', 'Señal'), C('dim_senal', 'descripcion', 'Qué la activa'), Me('Activos con la señal hoy', 'Activos hoy'), Me('% de activos por señal', '% hoy')]
    p.add('tabla_reglas', 24, 256, 760, 288, 'tableEx',
          {"queryState": {"Values": {"projections": cols}},
           "sortDefinition": {"sort": [{"field": CF('dim_senal', 'Señal en palabras'), "direction": "Ascending"}], "isDefaultSort": False}},
          table_obj(size=12, pad=2),
          cont('Qué activa cada señal', 'Regla de cada señal y cuántos activos la tienen hoy'))
    p.card_texto('guia_no', 800, 256, 456, 288, 'Qué NO es este radar',
                 'No es un bot: no ejecuta órdenes ni opera por vos.\nNo es asesoramiento: las señales son reglas fijas sobre indicadores clásicos.\nLa fuerza es un puntaje, no una probabilidad.\nNo hay evidencia de que estas reglas generen rentabilidad: el backtest del proyecto existe para medirlo con honestidad.', size=13)
    p.text('guia_glosario', 24, 552, 600, 24, 'GLOSARIO', 12, MUTED, True, alt='Sección: glosario')
    glosario = [('RSI', 'De 0 a 100: por debajo de 30 suele estar barato, por encima de 70 caro.'),
                ('MACD', 'Cruza al alza: impulso positivo. Cruza a la baja: impulso negativo.'),
                ('Medias de 20 y 50', 'Promedio de las últimas 20 y 50 velas. Por encima: tendencia alcista.'),
                ('Vela', 'Un período de precio: 1 hora en cripto, 1 día en acciones.')]
    for i, (titulo, texto) in enumerate(glosario):
        p.card_texto(f'guia_glos_{i + 1}', 24 + i * 312, 576, 296, 112, titulo, texto)
    footer(p)
    return p, []


def write(p, inter, lang):
    d = os.path.join(D, 'pages', p.pid)
    vd = os.path.join(d, 'visuals')
    target = Path(vd).resolve()
    expected_root = Path(D).resolve()
    if not target.is_relative_to(expected_root) or target.name != 'visuals':
        raise ValueError('La carpeta de visuales está fuera del reporte')
    if target.is_dir():
        shutil.rmtree(target)
    for v in p.vis:
        os.makedirs(os.path.join(vd, v['name']), exist_ok=True)
        json.dump(v, open(os.path.join(vd, v['name'], 'visual.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    pagina = os.path.join(d, 'page.json')
    if not os.path.exists(pagina):
        json.dump({"$schema": SCH + 'page/2.1.0/schema.json', "name": p.pid, "displayName": NAMES[p.key],
                   "displayOption": "FitToPage", "height": 720, "width": 1280}, open(pagina, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    pj = json.load(open(pagina, encoding='utf-8'))
    pj['displayName'] = NAMES[p.key] if lang == 'es' else EN[NAMES[p.key]] + ' (EN)'
    pj.pop('visualInteractions', None)
    pj.pop('visibility', None)
    if inter:
        pj['visualInteractions'] = inter
    if lang == 'en':
        pj['visibility'] = 'HiddenInViewMode'   # se llega con el botón EN; no duplica la barra de pestañas
    json.dump(pj, open(pagina, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)


def bookmarks(pages):
    os.makedirs(os.path.join(D, 'bookmarks'), exist_ok=True)
    items = []
    for p, lang in pages:
        nombre = NAMES[p.key] if lang == 'es' else EN[NAMES[p.key]] + ' (EN)'
        for bid, label, mode in [(BM[p.pid][0], 'Abrir filtros', 'visible'), (BM[p.pid][1], 'Cerrar filtros', 'hidden')]:
            vc = {nm: {"singleVisual": {"visualType": next(v['visual']['visualType'] for v in p.vis if v['name'] == nm), **({} if mode == 'visible' else {"display": {"mode": "hidden"}})}} for nm in PANEL}
            bk = {"$schema": SCH + 'bookmark/1.4.0/schema.json', "displayName": f'{nombre} · {label}', "name": bid,
                  "options": {"targetVisualNames": PANEL, "applyOnlyToTargetVisuals": True, "suppressData": True, "suppressActiveSection": True},
                  "explorationState": {"version": "1.3", "activeSection": p.pid, "sections": {p.pid: {"visualContainers": vc}}}}
            json.dump(bk, open(os.path.join(D, 'bookmarks', bid + '.bookmark.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
            items.append({"name": bid})
    for viejo in Path(os.path.join(D, 'bookmarks')).glob('bmReset*.bookmark.json'):
        viejo.unlink()
    json.dump({"$schema": SCH + 'bookmarksMetadata/1.0.0/schema.json', "items": items}, open(os.path.join(D, 'bookmarks', 'bookmarks.json'), 'w', encoding='utf-8'), indent=2)


def theme():
    # Deliberately small: no inherited visual-specific borders, markers or tiles.
    def fill(c):
        return {"solid": {"color": c}}
    common = {
        "title": [{"show": True, "fontFamily": "Segoe UI Semibold", "fontSize": 16, "fontColor": fill(INK), "alignment": "left", "titleWrap": True}],
        "subTitle": [{"show": False}],
        "background": [{"show": True, "color": fill("#FFFFFF"), "transparency": 0}],
        "border": [{"show": True, "color": fill(BORDE), "radius": 10, "width": 1}],
        "dropShadow": [{"show": True, "color": fill("#0F172A"), "position": "Outer", "preset": "BottomRight", "transparency": 93}],
        "padding": [{"top": 8, "bottom": 8, "left": 12, "right": 12}],
        "visualHeader": [{"show": False}],
        "categoryAxis": [{"showAxisTitle": False, "fontSize": 13, "labelColor": fill(MUTED), "gridlineShow": False}],
        "valueAxis": [{"showAxisTitle": False, "fontSize": 13, "labelColor": fill(MUTED), "gridlineShow": True, "gridlineColor": fill("#E2E8F0"), "gridlineStyle": "dotted"}],
        "legend": [{"show": True, "position": "Top", "fontSize": 13, "labelColor": fill(MUTED)}],
    }
    clean = {"background": [{"show": False}], "border": [{"show": False}], "dropShadow": [{"show": False}],
             "title": [{"show": False}], "padding": [{"top": 0, "bottom": 0, "left": 0, "right": 0}]}
    vs = {"*": {"*": common}, "page": {"*": {"background": [{"color": fill("#F5F7FB"), "transparency": 0}]}}}
    for typ in ("shape", "actionButton", "pageNavigator", "textbox", "image"):
        vs[typ] = {"*": copy.deepcopy(clean)}
    # cardVisual: la etiqueta (label) hace de título; el título de contenedor
    # duplicaría texto y recortaría el valor en alturas compactas (guía oficial
    # Microsoft: cardVisual con label propio lleva title.show = False).
    vs["cardVisual"] = {"*": {"title": [{"show": False}],
                                  "value": [{"fontSize": 32, "fontFamily": "Segoe UI Semibold", "fontColor": fill(INK), "bold": True}],
                                  "label": [{"fontSize": 13, "fontColor": fill(MUTED)}]}}
    for typ in ("lineChart", "areaChart"):
        vs[typ] = {"*": {"lineStyles": [{"showMarker": False, "strokeShow": True, "strokeWidth": 3}], "labels": [{"show": False}]}}
    vs["slicer"] = {"*": {"items": [{"textSize": 13, "fontColor": fill(INK)}], "header": [{"show": False}], "general": [{"responsive": False}]}}
    t = {"name": "RadarTheme", "dataColors": [PRIMARY, GREEN, RED, FAINT, "#0EA5E9", "#F59E0B"],
         "foreground": INK, "background": "#FFFFFF", "tableAccent": PRIMARY,
         "textClasses": {"title": {"fontFace": "Segoe UI Semibold", "fontSize": 16, "color": INK},
                         "label": {"fontFace": "Segoe UI", "fontSize": 13, "color": MUTED},
                         "callout": {"fontFace": "Segoe UI Semibold", "fontSize": 32, "color": INK},
                         "header": {"fontFace": "Segoe UI Semibold", "fontSize": 13, "color": INK}},
         "visualStyles": vs}
    json.dump(t, open(os.path.join(R, 'StaticResources', 'RegisteredResources', 'RadarTheme.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    rp = os.path.join(D, 'report.json')
    r = json.load(open(rp, encoding='utf-8'))
    r['themeCollection']['customTheme']['name'] = 'RadarTheme.json'
    r['resourcePackages'][0]['items'] = [{"name": "RadarTheme.json", "path": "RadarTheme.json", "type": "CustomTheme"}]
    r['settings']['useEnhancedTooltips'] = True
    viejo = os.path.join(R, 'StaticResources', 'RegisteredResources', 'radar_accesible.json')
    if os.path.exists(viejo):
        os.remove(viejo)
    json.dump(r, open(rp, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)


def generar():
    """Construye las páginas en los dos idiomas y escribe el informe. Devuelve la cantidad de visuales."""
    global LANG
    theme()
    built = []
    for lang in ('es', 'en'):
        LANG = lang
        for build in (build_inicio, build_resumen, build_senales, build_mercado, build_calidad, build_guia):
            p, inter = build()
            built.append((p, inter, lang))
    LANG = 'es'
    if FALTANTES:
        raise SystemExit('Textos sin traducción al inglés:\n  ' + '\n  '.join(sorted(FALTANTES)))
    for p, inter, lang in built:
        write(p, inter, lang)
    bookmarks([(p, lang) for p, _, lang in built if any(v['name'] == 'flt_panel' for v in p.vis)])
    vivas = {p.pid for p, _, _ in built}
    for carpeta in Path(os.path.join(D, 'pages')).iterdir():
        if carpeta.is_dir() and carpeta.name not in vivas:
            shutil.rmtree(carpeta)
    pg = os.path.join(D, 'pages', 'pages.json')
    pj = json.load(open(pg, encoding='utf-8'))
    pj['pageOrder'] = [p.pid for p, _, _ in built]
    pj['activePageName'] = PG['es']['ini']
    json.dump(pj, open(pg, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    return sum(len(p.vis) for p, _, _ in built)


if __name__ == '__main__':
    import subprocess
    from datetime import datetime
    powershell = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
    running = subprocess.run([powershell, '-NoProfile', '-Command',  # noqa: S603 - comando fijo, sin entrada externa
                              'if (Get-Process PBIDesktop -ErrorAction SilentlyContinue) { exit 1 }'], check=False)
    if running.returncode:
        raise RuntimeError('Cerrá Power BI Desktop antes de editar el reporte.')
    backup = Path(tempfile.gettempdir()) / 'radar_backups' / ('report_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
    shutil.copytree(R, backup)
    print('Backup:', backup)
    print('ok', generar())

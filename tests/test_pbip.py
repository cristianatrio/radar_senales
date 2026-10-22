"""El proyecto Power BI de la demo (PBIP) es coherente sin abrir Desktop.

Chequeos estáticos sobre `powerbi/demo_publica`: JSON válido, visuales dentro del lienzo y en
cuadrícula de 8 px, campos y medidas referenciados existentes en el modelo TMDL, serialización de
botones que Desktop acepta, y ausencia de datos privados o rutas personales.
"""

import json
import os
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
DEMO = RAIZ / "powerbi" / "demo_publica"
REPORTE = DEMO / "RadarDemo.Report" / "definition"
MODELO = DEMO / "RadarDemo.SemanticModel" / "definition"
PAGINAS_ES = {"a1f3c9e2b7d45068": "Inicio", "4312130530f2e353": "Resumen", "179abaca766ff951": "Señales",
              "2f53da19923c44ba": "Mercado", "8341d05fb21037f6": "Calidad", "c7e2d4a9f1b36025": "Guía"}
PAGINAS_EN = {"e5b7a1c3d9f20461": "Home (EN)", "f0a2c4e6b8d13579": "Overview (EN)", "9c1e3a5b7d2f4680": "Signals (EN)",
              "b3d5f7a9c1e24682": "Market (EN)", "d7f9b1c3e5a26804": "Quality (EN)", "2a4c6e8b0d1f3579": "Guide (EN)"}
PAGINAS = {**PAGINAS_ES, **PAGINAS_EN}
CANVAS = (1280, 720)
TABLAS_PRIVADAS = ("posiciones", "eventos_posicion", "ripio_", "alertas_")


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _visuales():
    return sorted(REPORTE.glob("pages/*/visuals/*/visual.json"))


def _modelo():
    """{tabla: {columnas y medidas}} leído del TMDL."""
    campos = {}
    for archivo in (MODELO / "tables").glob("*.tmdl"):
        texto = archivo.read_text(encoding="utf-8")
        tabla = re.search(r"^table (?:'([^']+)'|(\S+))", texto, re.M)
        nombre = tabla.group(1) or tabla.group(2)
        cols = re.findall(r"^\t(?:column|measure) (?:'((?:[^']|'')+)'|(\S+))", texto, re.M)
        campos[nombre] = {(a or b).replace("''", "'") for a, b in cols}
    return campos


@pytest.fixture(scope="module")
def modelo():
    return _modelo()


def test_todos_los_json_del_informe_parsean():
    archivos = list((DEMO / "RadarDemo.Report").rglob("*.json")) + [DEMO / "RadarDemo.Report" / "definition.pbir"]
    assert len(archivos) > 120
    for archivo in archivos:
        _json(archivo)


def test_paginas_declaradas_en_orden_y_las_inglesas_ocultas():
    paginas = _json(REPORTE / "pages" / "pages.json")
    assert paginas["pageOrder"] == list(PAGINAS)
    assert paginas["activePageName"] == list(PAGINAS)[0]
    for pid, nombre in PAGINAS.items():
        page = _json(REPORTE / "pages" / pid / "page.json")
        assert page["displayName"] == nombre
        assert (page["width"], page["height"]) == CANVAS
        assert page.get("type") is None  # sin tooltips ni drillthrough
        assert page.get("visibility") == ("HiddenInViewMode" if pid in PAGINAS_EN else None)
    assert {p.name for p in (REPORTE / "pages").iterdir() if p.is_dir()} == set(PAGINAS)


def test_cada_pagina_tiene_su_version_en_el_otro_idioma_con_los_mismos_visuales():
    for es, en in zip(PAGINAS_ES, PAGINAS_EN):
        vis_es = {v.name for v in (REPORTE / "pages" / es / "visuals").iterdir()}
        vis_en = {v.name for v in (REPORTE / "pages" / en / "visuals").iterdir()}
        assert vis_es == vis_en, (es, en)
        toggle = _json(REPORTE / "pages" / es / "visuals" / "hdr_idioma" / "visual.json") if es != list(PAGINAS_ES)[0] else _json(REPORTE / "pages" / es / "visuals" / "ini_idioma" / "visual.json")
        link = toggle["visual"]["visualContainerObjects"]["visualLink"][0]["properties"]
        assert link["navigationSection"]["expr"]["Literal"]["Value"].strip("'") == en


def test_las_paginas_en_ingles_no_usan_medidas_ni_columnas_en_espanol_para_el_texto():
    en_espanol = {"Lectura del radar", "Detalle del activo seleccionado", "Lectura de calidad", "Subtítulo filtros", "Pie de actualización",
                  "Señal con ícono", "Estado chip", "Tipo de activo", "Fuente de datos", "Estado del dato", "Señal en palabras"}
    for pid in PAGINAS_EN:
        for archivo in (REPORTE / "pages" / pid / "visuals").glob("*/visual.json"):
            texto = archivo.read_text(encoding="utf-8")
            usados = {m for m in en_espanol if f'"Property": "{m}"' in texto}
            assert not usados, (archivo.parent.name, usados)


def test_visuales_en_cuadricula_y_dentro_del_lienzo():
    ancho, alto = CANVAS
    for archivo in _visuales():
        p = _json(archivo)["position"]
        assert all(p[k] % 8 == 0 for k in ("x", "y", "width", "height")), archivo
        assert 0 <= p["x"] and p["x"] + p["width"] <= ancho, archivo
        assert 0 <= p["y"] and p["y"] + p["height"] <= alto, archivo


def test_campos_y_medidas_existen_en_el_modelo(modelo):
    faltantes = []
    for archivo in _visuales():
        texto = archivo.read_text(encoding="utf-8")
        for entidad, prop in re.findall(r'"Entity": "([^"]+)"\}\}, "Property": "([^"]+)"', texto):
            if prop not in modelo.get(entidad, set()):
                faltantes.append((archivo.parent.name, entidad, prop))
        for ref in re.findall(r'"queryRef": "([^"]+)"', texto):
            entidad, _, prop = ref.partition(".")
            if prop not in modelo.get(entidad, set()):
                faltantes.append((archivo.parent.name, entidad, prop))
    assert not faltantes, faltantes


def test_botones_con_la_serializacion_que_desktop_acepta():
    tipos_validos = {"Bookmark", "PageNavigation", "ClearAllSlicers", "Back"}
    for archivo in _visuales():
        v = _json(archivo)
        vco = v["visual"].get("visualContainerObjects", {})
        assert "visualTooltip" not in vco, archivo  # ya no hay página de tooltip
        for link in vco.get("visualLink", []):
            props = link["properties"]
            assert "showDefaultTooltip" in props, archivo
            tipo = props["type"]["expr"]["Literal"]["Value"].strip("'")
            assert tipo in tipos_validos, (archivo, tipo)
            if tipo == "PageNavigation":
                destino = props["navigationSection"]["expr"]["Literal"]["Value"].strip("'")
                assert destino in PAGINAS, (archivo, destino)


def test_cada_visual_tiene_texto_alternativo_o_es_decorativo():
    sin_alt = []
    for archivo in _visuales():
        v = _json(archivo)
        vco = v["visual"].get("visualContainerObjects", {})
        alt = any("altText" in g.get("properties", {}) for g in vco.get("general", []))
        if not alt and not v.get("isHidden"):
            sin_alt.append(archivo.parent.name)
    assert not sin_alt, sin_alt


def test_modelo_sin_tablas_privadas_ni_rutas_personales():
    nombres = [a.stem for a in (MODELO / "tables").glob("*.tmdl")]
    assert not any(n.startswith(TABLAS_PRIVADAS) for n in nombres), nombres
    for archivo in list(MODELO.rglob("*.tmdl")) + list((DEMO / "RadarDemo.Report").rglob("*.json")):
        texto = archivo.read_text(encoding="utf-8")
        assert "Users\\" not in texto and "/Users/" not in texto, archivo
    expresiones = (MODELO / "expressions.tmdl").read_text(encoding="utf-8")
    assert "datos_demo" in expresiones  # la demo apunta a los CSV sintéticos


def test_medidas_documentadas_coinciden_con_el_modelo(modelo):
    exportadas = re.findall(r"^([^/\s][^=\n]*?) =(?: |\n)", (RAIZ / "powerbi" / "medidas.dax").read_text(encoding="utf-8"), re.M)
    assert set(e.strip() for e in exportadas) == modelo["_Medidas"] - {"Value"}


def test_gitignore_excluye_caches_de_desktop():
    reglas = (RAIZ / ".gitignore").read_text(encoding="utf-8")
    assert "**/.pbi/localSettings.json" in reglas and "**/.pbi/cache.abf" in reglas
    assert "!powerbi/demo_publica/RadarDemo.pbip" in reglas
    assert not os.path.exists(DEMO / "RadarDemo.Report" / "StaticResources" / "RegisteredResources" / "radar_accesible.json")

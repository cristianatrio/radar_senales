"""Exporta las medidas del modelo TMDL de la demo a `powerbi/medidas.dax` (documentación legible).

Lee `RadarDemo.SemanticModel/definition/tables/_Medidas.tmdl` y escribe cada medida con su
descripción, carpeta y formato, en un bloque DAX listo para copiar en Power BI Desktop.

    python powerbi/demo_publica/exportar_medidas.py
"""
import re
from pathlib import Path

AQUI = Path(__file__).resolve().parent
TMDL = AQUI / 'RadarDemo.SemanticModel' / 'definition' / 'tables' / '_Medidas.tmdl'
SALIDA = AQUI.parent / 'medidas.dax'


def leer_medidas(texto):
    """Devuelve [(nombre, expresión, descripción, carpeta, formato)] en el orden del archivo."""
    medidas, doc = [], []
    lineas = texto.splitlines()
    i = 0
    while i < len(lineas):
        linea = lineas[i]
        if linea.startswith('\t/// '):
            doc.append(linea[5:])
        elif linea.startswith("\tmeasure '"):
            m = re.match(r"\tmeasure '((?:[^']|'')+)' =(.*)$", linea)
            nombre, resto = m.group(1).replace("''", "'"), m.group(2).strip()
            cuerpo = [resto] if resto else []
            i += 1
            while i < len(lineas) and lineas[i].startswith('\t\t\t'):
                cuerpo.append('    ' + lineas[i][3:].replace('\t', '    '))
                i += 1
            props = {}
            while i < len(lineas) and lineas[i].startswith('\t\t') and not lineas[i].startswith('\t\t\t'):
                k, _, v = lineas[i].strip().partition(': ')
                props[k] = v
                i += 1
            medidas.append((nombre, '\n'.join(cuerpo), ' '.join(doc), props.get('displayFolder', ''), props.get('formatString', '')))
            doc = []
            continue
        elif linea.startswith('\tcolumn') or linea.startswith('\tpartition'):
            doc = []
        i += 1
    return medidas


def main():
    medidas = leer_medidas(TMDL.read_text(encoding='utf-8'))
    partes = ['// Medidas del modelo RadarDemo (tabla _Medidas), exportadas desde el TMDL por exportar_medidas.py.',
              '// Ninguna suma ni promedia RSI, fuerza o precios: ver powerbi/README_POWERBI.md.',
              f'// Total: {len(medidas)} medidas.', '']
    carpeta_actual = None
    for nombre, expr, doc, carpeta, fmt in medidas:
        if carpeta != carpeta_actual:
            partes += [f'// ===== {carpeta or "Sin carpeta"} =====', '']
            carpeta_actual = carpeta
        if doc:
            partes.append(f'// {doc}')
        if fmt:
            partes.append(f'// Formato: {fmt}')
        partes.append(f'{nombre} =' + (f' {expr}' if '\n' not in expr else '\n' + expr))
        partes.append('')
    SALIDA.write_text('\n'.join(partes), encoding='utf-8', newline='\n')
    print(f'{len(medidas)} medidas -> {SALIDA}')


if __name__ == '__main__':
    main()

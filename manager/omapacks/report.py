"""Editable, signed release prose. It cannot authorize or replace an engine plan."""
from pathlib import Path
from .util import clean,digest,secure_path,Error

SECTIONS=('Resumen','Apps y plugins','Modificaciones')
EMPTY={'Resumen':'Sin resumen del paquete.',
       'Apps y plugins':'No se añadieron nuevos elementos.',
       'Modificaciones':'No se declararon modificaciones.'}

def sections(text):
    """Minimal Markdown: three required sections, optional sections afterwards."""
    rows=[]; title=None; body=[]
    for line in clean(text).splitlines():
        if line.startswith('## '):
            if title: rows.append((title,'\n'.join(body).strip()))
            title=line[3:].strip(); body=[]
        elif title: body.append(line)
    if title: rows.append((title,'\n'.join(body).strip()))
    if [title for title,_ in rows[:3]]!=list(SECTIONS): return None
    if len({t for t,_ in rows})!=len(rows) or len(rows)>10: raise Error('Secciones del reporte repetidas o excesivas')
    return [(title,body or EMPTY.get(title,'Sin novedades.')) for title,body in rows]

def signed_notes(plan):
    expected=plan['meta'].get('files',{}).get('NOTES.md')
    if not expected: return ''
    data=secure_path(Path(plan['stage'])/'content','NOTES.md').read_bytes()
    if digest(data)!=expected: raise Error('El reporte firmado cambió; vuelve a verificar la release','changed')
    return clean(data.decode('utf-8'))

def editorial(plan):
    text=signed_notes(plan); parsed=sections(text)
    if parsed: return parsed
    # Older releases remain readable without claiming that prose is a live diff.
    summary='\n'.join(m['description'] for m in plan['manifest']['modules'])
    apps=[p.get('name',p.get('id','')) for p in plan['packages'] if p['action']!='keep']
    mods=[]
    kinds={c.get('kind') for c in plan['files'] if c['action'] not in ('keep','skip','create')}
    if kinds & {'hypr_include','hypr_detach'}: mods.append('Hyprland: ajustes compartidos de apariencia.')
    if kinds & {'omarchy_shell','omarchy_style','omarchy_menu'}: mods.append('Omarchy: interfaz, menú o paneles compartidos.')
    if 'xdg_defaults' in kinds: mods.append('Aplicaciones predeterminadas: preferencias administradas por claves.')
    if kinds-{'hypr_include','hypr_detach','omarchy_shell','omarchy_style','omarchy_menu','xdg_defaults'}: mods.append('Archivos administrados: consulta los recursos exactos en Detalles.')
    return [('Resumen',summary),('Apps y plugins','\n'.join('- '+n for n in apps) or EMPTY['Apps y plugins']),
            ('Modificaciones','\n'.join(mods) or EMPTY['Modificaciones'])]

def render(plan):
    return '\n\n'.join('## '+title+'\n'+body for title,body in editorial(plan))


def preview(text):
    """Informational publication prose; opening a release verifies signed NOTES."""
    try: parsed=sections(text)
    except Error: parsed=None
    if parsed: return parsed[0][1]
    paragraphs=clean(text).split('\n\n')
    return next((p.strip() for p in paragraphs if p.strip() and not p.lstrip().startswith('#')),'Resumen disponible al abrir esta versión.')

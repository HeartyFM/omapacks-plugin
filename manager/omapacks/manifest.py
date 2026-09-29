"""Strict schema for declarative content. Unknown fields fail closed."""
from __future__ import annotations
import platform, re, tomllib
from pathlib import Path
from . import __version__
from .util import Error, clean, relative, version

ID = r'[a-z][a-z0-9._-]{0,79}'
PKG = r'[a-zA-Z0-9][a-zA-Z0-9@._+:-]{0,150}'
SHA = r'[0-9a-f]{64}'
FORBIDDEN_PACKAGES = re.compile(r'^(linux(?:-|$)|.*(?:firmware|nvidia|bootloader)|grub$|systemd-boot$|cryptsetup$)', re.I)

def fields(obj, allowed, required=()):
    if not isinstance(obj, dict): raise Error('Se esperaba una tabla del manifiesto')
    extra = set(obj) - set(allowed)
    if extra: raise Error('Campos no admitidos: ' + ', '.join(sorted(extra)))
    if set(required) - set(obj): raise Error('Faltan campos: ' + ', '.join(sorted(set(required)-set(obj))))

def string(value, pattern=None):
    if not isinstance(value, str) or not value or len(value) > 2000 or clean(value, False) != value:
        raise Error('Cadena vacía, demasiado larga o con controles')
    if pattern and not re.fullmatch(pattern, value): raise Error('Parámetro inválido: ' + clean(value))
    return value

def strings(value, pattern=None):
    if not isinstance(value, list): raise Error('Se esperaba una lista')
    for v in value: string(v, pattern)
    if len(value) != len(set(value)): raise Error('Valores duplicados')
    return value

def destination(value, scope='user', kind='file'):
    relative(value)
    if scope == 'system':
        if not re.fullmatch(r'etc/omapacks/[a-zA-Z0-9_.-]+\.conf', value):
            raise Error('Sistema: solo etc/omapacks/*.conf está permitido en el esquema 1')
    elif scope == 'user':
        if kind == 'xdg_defaults':
            if value != '.config/mimeapps.list': raise Error('Destino de defaults inválido')
        elif kind == 'omarchy_menu':
            if value != '.config/omarchy/extensions/omarchy-menu.jsonc': raise Error('Destino de menú inválido')
        elif kind == 'omarchy_shell':
            if value != '.config/omarchy/shell.json': raise Error('Destino de shell inválido')
        elif kind == 'omarchy_style':
            if value != '.config/omarchy/shell.toml': raise Error('Destino de estilo inválido')
        elif kind == 'qt_shader':
            if not re.fullmatch(r'\.config/omarchy/plugins/omapacks\.shared\.[a-z0-9_-]+/[A-Za-z0-9_/-]+\.frag\.qsb',value): raise Error('Shader fuera del plugin administrado')
        elif kind == 'hypr_include':
            if value not in ('.config/hypr/hyprland.lua', '.config/hypr/hyprland.conf'): raise Error('Include Hyprland inválido')
        elif not (value.startswith('.config/omapacks-shared/') or value.startswith('.local/share/omapacks-content/') or re.fullmatch(r'\.local/bin/omapacks-[a-z0-9_-]+', value) or re.fullmatch(r'\.config/omarchy/plugins/omapacks\.shared\.[a-z0-9_-]+/[A-Za-z0-9_./-]+',value)):
            raise Error('Destino común fuera del namespace administrado: ' + value)
    else: raise Error('Ámbito inválido')
    return value

def validate(data):
    fields(data, ('schema','id','version','manager_min','compatibility','modules','packages','files','downloads','operations','checks','migrations','recovery','notes','flatpak_remotes','recipes','capture_shortcut'), ('schema','id','version','manager_min','compatibility','modules','recovery'))
    if type(data['schema']) is not int or data['schema'] != 1: raise Error('Esquema de manifiesto no compatible')
    string(data['id'], ID); version(data['version']); version(data['manager_min'])
    if version(data['manager_min']) > version(__version__): raise Error('Esta release requiere actualizar el gestor por separado', 'incompatible')
    if data.get('capture_shortcut') is not None:
        from .capture_shortcut import validate as capture_validate
        capture_validate(data['capture_shortcut'])
        if version(data['manager_min'])<version('0.3.2'): raise Error('Captura tipada requiere manager_min 0.3.2')
        if data['compatibility'].get('hyprland_format')!='lua': raise Error('Captura tipada requiere Hyprland Lua')
        if not any(c.get('kind')=='hyprland' and c.get('required') for c in data.get('checks',[])): raise Error('Captura tipada requiere comprobación Hyprland')
    comp = data['compatibility']; fields(comp, ('architectures','omarchy_min','omarchy_max','hyprland_min','hyprland_max','hyprland_format'), ('architectures',))
    strings(comp['architectures'], r'x86_64|aarch64')
    for name in ('omarchy_min','omarchy_max','hyprland_min','hyprland_max'):
        if name in comp: version(comp[name])
    if comp.get('hyprland_format', 'any') not in ('any','lua','conf'): raise Error('Formato Hyprland inválido')
    modules = data['modules']
    if not isinstance(modules, list) or not modules: raise Error('Se necesita al menos un módulo')
    ids = set()
    for m in modules:
        fields(m, ('id','version','requires','conflicts','description'), ('id','version','description'))
        string(m['id'], ID); version(m['version']); string(m['description'])
        strings(m.get('requires', []), ID); strings(m.get('conflicts', []), ID)
        if m['id'] in ids: raise Error('Módulo duplicado')
        ids.add(m['id'])
    pending = list(modules); done = set()
    while pending:
        ready = [m for m in pending if set(m.get('requires', [])) <= done]
        if not ready: raise Error('Dependencias de módulos ausentes o cíclicas')
        for m in ready:
            if set(m.get('conflicts', [])) & ids: raise Error('Conflicto entre módulos incluidos')
            pending.remove(m); done.add(m['id'])
    for section in ('packages','files','downloads','operations','checks','migrations','flatpak_remotes','recipes'):
        if not isinstance(data.get(section, []), list): raise Error('Lista inválida: ' + section)
    for section in ('packages','files','downloads','operations','checks','recipes'):
        for item in data.get(section, []):
            if item.get('module') not in ids: raise Error('Módulo desconocido en ' + section)
    pkg_ids = set()
    for p in data.get('packages', []):
        fields(p, ('module','provider','name','version','remote','scope','commit','build_dependencies','review','permissions'), ('module','provider','name','version'))
        string(p['name'], PKG); string(p['version'], r'[a-zA-Z0-9][a-zA-Z0-9.:+_~-]*')
        if FORBIDDEN_PACKAGES.search(p['name']): raise Error('Kernel, controladores, firmware y arranque están excluidos')
        provider = p['provider']
        if provider not in ('arch','aur','flatpak'): raise Error('Proveedor no admitido: ' + clean(provider))
        key = (provider, p['name'], p.get('scope','system'))
        if key in pkg_ids: raise Error('Declara una sola dependencia compartida por paquete')
        pkg_ids.add(key)
        if provider == 'aur':
            string(p.get('commit'), r'[0-9a-f]{40}'); string(p.get('review'))
            strings(p.get('build_dependencies', []), PKG)
            if any(FORBIDDEN_PACKAGES.search(n) for n in p.get('build_dependencies', [])): raise Error('Dependencia de compilación excluida')
        if provider == 'flatpak':
            string(p.get('name'), r'[A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z][A-Za-z0-9_-]*){2,}')
            string(p.get('remote'), r'[a-zA-Z][a-zA-Z0-9_-]*')
            if p.get('scope') not in ('user','system'): raise Error('Flatpak requiere ámbito explícito')
            string(p['version'], r'[0-9a-f]{64}'); string(p.get('permissions'))
    paths = set()
    for f in data.get('files', []):
        fields(f, ('module','source','target','scope','mode','kind'), ('module','source','target','scope'))
        relative(f['source'])
        if not f['source'].startswith(('config/','modules/')): raise Error('Origen fuera de config/ o modules/')
        kind = f.get('kind','file')
        if kind not in ('file','hypr_include','omarchy_menu','xdg_defaults','omarchy_shell','omarchy_style','qt_shader'): raise Error('Tipo de archivo no soportado')
        if kind!='file' and f['scope']!='user': raise Error('Este recurso es exclusivamente de usuario')
        destination(f['target'], f['scope'], kind)
        if f['scope']=='system' and f.get('mode',0o644) not in (0o600,0o644): raise Error('Los archivos de sistema no pueden ser ejecutables')
        if f.get('mode', 0o644) not in (0o600,0o644,0o700,0o755): raise Error('Permisos inválidos')
        if kind=='qt_shader' and f.get('mode',0o644)!=0o644: raise Error('Un shader no puede ser ejecutable')
        key = (f['scope'], f['target'])
        if key in paths: raise Error('Destino duplicado')
        paths.add(key)
    for d in data.get('downloads', []):
        fields(d, ('module','id','format','version','architecture','url','sha256','size','target','build','purpose','check','revision','plugin_id'), ('module','id','format','version','architecture','url','sha256','size','purpose'))
        string(d['id'], ID); string(d['version']); string(d['sha256'], SHA); string(d['purpose'])
        from urllib.parse import urlsplit
        u = urlsplit(d['url'])
        if u.scheme != 'https' or not u.hostname or u.username or u.password or u.fragment: raise Error('URL externa inválida')
        if d['architecture'] not in ('x86_64','aarch64'): raise Error('Arquitectura externa inválida')
        if type(d['size']) is not int or not 0 < d['size'] <= 128*1024*1024: raise Error('Tamaño externo inválido')
        if d['format'] not in ('appimage','tar','arch','source-tar','omarchy-plugin'): raise Error('Formato no soportado; no se convierten deb/rpm')
        if d['format']=='omarchy-plugin':
            from .native_plugin import validate as plugin_validate
            plugin_validate(d)
            if version(data['manager_min'])<version('0.3.2'): raise Error('Plugin externo requiere manager_min 0.3.2')
        elif d['format'] != 'arch': destination(d.get('target', ''))
        if d['format'] in ('tar','source-tar') and not d['target'].startswith('.local/share/omapacks-content/'): raise Error('Archivo de aplicación fuera del namespace')
        if d['format'] == 'source-tar':
            string(d.get('revision'),r'[0-9a-f]{40}')
            if d.get('build') not in ('make','cargo'): raise Error('Constructor admitido: make o cargo')
            string(d.get('check'), r'[a-zA-Z0-9_./-]+'); relative(d['check'])
    remote_ids = set()
    for remote in data.get('flatpak_remotes', []):
        fields(remote, ('name','scope','url','sha256','size'), ('name','scope','url','sha256','size'))
        string(remote['name'], r'[a-zA-Z][a-zA-Z0-9_-]*'); string(remote['sha256'], SHA)
        if remote['scope'] not in ('user','system'): raise Error('Ámbito de remote inválido')
        from urllib.parse import urlsplit
        u=urlsplit(remote['url'])
        if u.scheme!='https' or not u.hostname or u.username or u.password: raise Error('Remote requiere HTTPS')
        if type(remote['size']) is not int or not 0<remote['size']<=1024*1024: raise Error('Tamaño del remote inválido')
        identity=(remote['scope'],remote['name'])
        if identity in remote_ids: raise Error('Remote duplicado')
        remote_ids.add(identity)
    for recipe in data.get('recipes', []):
        fields(recipe, ('id','module','kind','prefix','architecture','purpose','condition'), ('id','module','kind','prefix','architecture','purpose','condition'))
        string(recipe['id'], ID); string(recipe['purpose'])
        if recipe['kind']!='wine-prefix-init' or recipe['condition']!='prefix-absent': raise Error('Solucionador no soportado o sin condición específica')
        relative(recipe['prefix'])
        if not re.fullmatch(r'\.local/share/omapacks-data/wine/[a-z0-9_-]+',recipe['prefix']): raise Error('Wine: prefijo nuevo en omapacks-data/wine/')
        if recipe['architecture'] not in ('win32','win64'): raise Error('Arquitectura Wine inválida')
        if not any(p['provider']=='arch' and p['name'] in ('wine','wine-staging') for p in data.get('packages',[])): raise Error('La receta Wine requiere dependencia Arch explícita')
    for op in data.get('operations', []):
        fields(op, ('module','kind','scope','name','action','purpose'), ('module','kind','scope','name','action','purpose'))
        if op['kind'] != 'service': raise Error('Operación excluida: solo servicios explícitos')
        string(op['name'], r'[a-zA-Z0-9][a-zA-Z0-9_.@-]*\.service'); string(op['purpose'])
        if re.search(r'firmware|fwupd|boot|grub|crypt|kernel|kmod|nvidia',op['name'],re.I): raise Error('Servicio relacionado con operaciones excluidas')
        if op['scope'] not in ('user','system') or op['action'] not in ('start','restart','enable'): raise Error('Operación de servicio inválida')
    for c in data.get('checks', []):
        fields(c, ('module','kind','target','scope','sha256','name','required','prefix'), ('module','kind','required'))
        if type(c['required']) is not bool: raise Error('required debe ser booleano')
        if c['kind'] == 'file':
            destination(c.get('target'), c.get('scope','user')); string(c.get('sha256'), SHA)
        elif c['kind'] == 'version':
            string(c.get('name'), r'wine|retroarch|dolphin-emu|python3|git|make|cargo')
        elif c['kind'] == 'hyprland': pass
        elif c['kind'] == 'wine-prefix':
            relative(c.get('prefix')); 
            if not re.fullmatch(r'\.local/share/omapacks-data/wine/[a-z0-9_-]+',c['prefix']): raise Error('Prefijo Wine fuera de su namespace')
        else: raise Error('Comprobación no admitida')
    migration_ids = set()
    for m in data.get('migrations', []):
        fields(m, ('id','from','to','precondition','description'), ('id','from','to','precondition','description'))
        string(m['id'], ID); string(m['from']); string(m['to']); string(m['description'])
        if m['id'] in migration_ids: raise Error('Migración duplicada')
        migration_ids.add(m['id'])
        # Epoch transitions are explicit, non-repeating and have a typed precondition.
        if m['precondition'] not in ('managed-files-clean','no-packages'): raise Error('Precondición de migración no admitida')
    r = data['recovery']; fields(r, ('epoch','limitations','reboot'), ('epoch','limitations','reboot'))
    string(r['epoch']); string(r['limitations'])
    if type(r['reboot']) is not bool: raise Error('reboot debe ser booleano')
    return data

def load(path):
    try: return validate(tomllib.loads(Path(path).read_text()))
    except (tomllib.TOMLDecodeError, UnicodeError, KeyError, TypeError, ValueError) as e: raise Error('Manifiesto inválido: ' + clean(str(e))) from None

def compatibility(manifest, host):
    c = manifest['compatibility']
    if host['architecture'] not in c['architectures']: raise Error('Arquitectura incompatible', 'incompatible')
    for name in ('omarchy','hyprland'):
        if name+'_min' in c or name+'_max' in c:
            actual = host.get(name)
            if not actual: raise Error('No se pudo detectar ' + name, 'incompatible')
            if name+'_min' in c and version(actual) < version(c[name+'_min']): raise Error(name + ' es demasiado antiguo', 'incompatible')
            if name+'_max' in c and version(actual) > version(c[name+'_max']): raise Error(name + ' es demasiado reciente para esta release', 'incompatible')
    if c.get('hyprland_format','any') not in ('any',host.get('hyprland_format')): raise Error('Formato de Hyprland incompatible', 'incompatible')
    for d in manifest.get('downloads', []):
        if d['architecture'] != host['architecture']: raise Error('Entrega externa para otra arquitectura', 'incompatible')

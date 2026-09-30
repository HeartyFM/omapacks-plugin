"""A private Spotify client. Preparation never launches, restarts or kills Spotify."""
from __future__ import annotations
import configparser, hashlib, io, json, os, re, shutil, subprocess, uuid
from pathlib import Path
from .util import Error, Runner, atomic, canonical, digest, lock, read_json, require_user, save_json, secure_path

RES='.local/share/omapacks-content/spotify'
TOOL='.local/share/omapacks-content/spicetify'
MARKET='.local/share/omapacks-content/marketplace/marketplace-dist'
DATA='.local/share/omapacks-data/spotify'
DESKTOP='.local/share/applications/spotify.desktop'
LAUNCHER='.local/bin/omapacks-spotify'
INPUTS=('base.css','omarchy-tiling.js','native-transparency.json')

def validate(manifest):
    value=manifest['spotify']
    if not isinstance(value,dict) or set(value)!={'module','profile'} or value['profile']!='omarchy-glass':
        raise Error('Spotify solo admite el perfil revisado omarchy-glass')
    if value['module'] not in {m['id'] for m in manifest['modules']}: raise Error('Módulo Spotify desconocido')
    if not any(p['name']=='spotify' and p['provider']=='arch' for p in manifest.get('packages',[])):
        raise Error('Spotify requiere su paquete nativo declarado')
    targets={f['target'] for f in manifest.get('files',[])}
    if not {RES+'/'+f for f in INPUTS}<=targets: raise Error('Faltan recursos propios de Spotify')
    external={d['id']:d for d in manifest.get('downloads',[])}
    for name,fmt,target in [('spicetify','tar',TOOL),('marketplace','zip',MARKET.rsplit('/',1)[0])]:
        spec=external.get(name,{})
        if spec.get('format')!=fmt or spec.get('target')!=target: raise Error('Fuente Spotify no declarada: '+name)

def launchers(home):
    # Desktop Entry escaping is different from shell escaping; HOME can contain spaces.
    path=str(Path(home)/LAUNCHER)
    escaped=path.replace('\\','\\\\\\\\').replace('"','\\"').replace('`','\\`').replace('$','\\$').replace('%','%%')
    desktop='[Desktop Entry]\nType=Application\nName=Spotify\nComment=Spotify con OmarchyGlass\nExec="'+escaped+'" %U\nIcon=spotify-client\nTerminal=false\nCategories=Audio;Music;Player;AudioVideo;\nMimeType=x-scheme-handler/spotify;\nStartupWMClass=Spotify\n'
    script='#!/bin/sh\nexec "$HOME/.local/bin/omapacks" spotify-launch "$@"\n'
    return {DESKTOP:(desktop.encode(),0o644),LAUNCHER:(script.encode(),0o755)}

def file_hash(path):
    with Path(path).open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()

def validate_native(text):
    try: spec=json.loads(text)
    except ValueError as e: raise Error('Receta de transparencia inválida') from e
    if set(spec)-{'spotify_version','reference','files'} or set(spec.get('files',{}))!={'spotify','libcef.so'}: raise Error('Receta nativa fuera del perfil Spotify')
    for entry in spec['files'].values():
        if set(entry)!={'original_sha256','glass_sha256','edits'}: raise Error('Campos de parche Spotify inválidos')
        if any(not re.fullmatch(r'[0-9a-f]{64}',str(entry[k])) for k in ('original_sha256','glass_sha256')): raise Error('Hash Spotify inválido')
        if not isinstance(entry['edits'],list) or not 1<=len(entry['edits'])<=64: raise Error('Parche Spotify demasiado amplio')
        for edit in entry['edits']:
            if not isinstance(edit,list) or len(edit)!=3: raise Error('Edición binaria inválida')
            offset,before,after=edit
            if type(offset) is not int or not 0<=offset<512*1024*1024 or not isinstance(before,str) or not isinstance(after,str) or not re.fullmatch(r'(?:[0-9a-f]{2}){1,128}',before) or len(before)!=len(after) or not re.fullmatch(r'[0-9a-f]+',after): raise Error('Parámetros de parche inválidos')
    return spec

def patch_native(client,spec):
    for name,entry in spec['files'].items():
        target=secure_path(client,name)
        if file_hash(target)!=entry['original_sha256']: raise Error('Spotify '+name+': versión sin soporte de cristal; requiere una receta nueva, no se baja ni modifica el paquete del sistema.','incompatible')
        target.chmod(target.stat().st_mode|0o200)
        with target.open('r+b') as stream:
            for offset,before,after in entry['edits']:
                stream.seek(offset); original=bytes.fromhex(before)
                if stream.read(len(original))!=original: raise Error('Spotify: bytes distintos de los revisados','integrity')
                stream.seek(offset); stream.write(bytes.fromhex(after))
            stream.flush(); os.fsync(stream.fileno())
        if file_hash(target)!=entry['glass_sha256']: raise Error('Spotify: resultado del parche no verificado','integrity')

def tree(root):
    result={}; total=0
    for p in sorted(Path(root).rglob('*')):
        name=p.relative_to(root).as_posix(); secure_path(root,name)
        if p.is_dir(): continue
        if not p.is_file() or len(result)>8192: raise Error('Árbol de Spotify no admitido')
        total+=p.stat().st_size
        if total>1024*1024*1024: raise Error('Copia Spotify demasiado grande')
        result[name]={'sha256':file_hash(p),'mode':p.stat().st_mode&0o777}
    return result

def theme(home,base):
    import tomllib
    path=Path(home)/'.local/state/omarchy/current/theme/colors.toml'
    try: palette=tomllib.loads(path.read_text())
    except (OSError,ValueError) as e: raise Error('No se pudo leer la paleta de Omarchy para Spotify') from e
    colors={k:str(palette.get(k,'')) for k in ('accent','foreground','red')}
    if any(not re.fullmatch(r'#[0-9a-fA-F]{6}',v) for v in colors.values()): raise Error('Paleta de Omarchy no reconocida')
    def mix(a,b,w):
        a=a.lstrip('#');b=b.lstrip('#')
        return ''.join(f'{round(int(a[i:i+2],16)*(1-w)+int(b[i:i+2],16)*w):02x}' for i in (0,2,4))
    accent=colors['accent'][1:];foreground=colors['foreground'][1:]
    values={'text':'f2f2f2','subtext':mix(foreground,'ffffff',.55),'main':'000000','main-elevated':'181818',
      'sidebar':'000000','player':'000000','card':'242424','shadow':'000000','highlight':'333333',
      'highlight-elevated':'444444','selected-row':'f2f2f2','button':accent,'button-active':mix(accent,'ffffff',.2),
      'button-disabled':'686868','tab-active':'333333','notification':accent,'notification-error':colors['red'][1:],'misc':mix(foreground,'ffffff',.5)}
    font=Runner().run(['omarchy','font','current']).stdout.strip().replace('\\','\\\\').replace('"','\\"').replace('\n',' ')
    css=base+'\n:root { --om-font: "'+font+'", monospace; --om-accent-text: #'+mix(accent,'ffffff',.48)+'; }\n'
    return css,'[Omarchy]\n'+''.join(k+' = '+v+'\n' for k,v in values.items())

def prepare(home,runner=None,source=Path('/opt/spotify')):
    require_user(); home=Path(home); runner=runner or Runner(); root=secure_path(home,DATA)
    with lock(root):
        assets={name:secure_path(home,RES+'/'+name).read_bytes() for name in INPUTS}
        spec=validate_native(assets['native-transparency.json'])
        for name,entry in spec['files'].items():
            if file_hash(secure_path(source,name))!=entry['original_sha256']:
                raise Error('La versión de Spotify instalada no coincide con la receta de cristal. Actualiza el pack; no se aplican offsets a otra versión.','incompatible')
        css,colors=theme(home,assets['base.css'].decode())
        tool=secure_path(home,TOOL); market=secure_path(home,MARKET)
        inputs={'source':tree(source),'tool':tree(tool),'market':tree(market),'own':{n:digest(b) for n,b in assets.items()},'css':digest(css.encode()),'colors':digest(colors.encode())}
        identity=digest(canonical(inputs)); prior=read_json(secure_path(root,'current.json'),{})
        if prior.get('identity')==identity:
            generation=secure_path(root,prior['generation'])
            if tree(generation/'client')!=prior.get('client'): raise Error('La copia privada de Spotify cambió; revisa el registro antes de reconstruirla','changed')
            return {'identity':identity,'generation':prior['generation'],'status':'reused','launched':False,'path':str(generation/'client/spotify')}
        # Exclusive generation: an interruption cannot destroy a previous usable client.
        name='generation-'+uuid.uuid4().hex; generation=secure_path(root,name); generation.mkdir(mode=0o700)
        client=generation/'client'; spice=generation/'spicetify'
        save_json(generation/'preparation.json',{'status':'preparing','identity':identity,'launch':False})
        try:
            shutil.copytree(source,client)
            if tree(client)!=inputs['source']: raise Error('El cliente Spotify cambió al copiarse','changed')
            theme_dir=spice/'Themes/OmarchyGlass';theme_dir.mkdir(parents=True)
            atomic(theme_dir/'user.css',css.encode()); atomic(theme_dir/'color.ini',colors.encode())
            atomic(spice/'Extensions/omarchy-tiling.js',assets['omarchy-tiling.js'])
            shutil.copytree(market,spice/'CustomApps/marketplace')
            # An empty, private prefs file supports clean machines without opening/login.
            atomic(generation/'prefs',b'')
            config=configparser.ConfigParser(interpolation=None)
            config['Setting']={'spotify_path':str(client),'prefs_path':str(generation/'prefs'),'current_theme':'OmarchyGlass','color_scheme':'Omarchy','inject_css':'1','replace_colors':'1','inject_theme_js':'0','overwrite_assets':'0','check_spicetify_update':'0','always_enable_devtools':'0'}
            config['Preprocesses']={'disable_sentry':'1','disable_ui_logging':'1','remove_rtl_rule':'1','expose_apis':'1'}
            config['AdditionalOptions']={'extensions':'omarchy-tiling.js','custom_apps':'marketplace','sidebar_config':'0','home_config':'1','experimental_features':'0'}
            out=io.StringIO();config.write(out);atomic(spice/'config-xpui.ini',out.getvalue().encode())
            env={k:v for k,v in os.environ.items() if k not in ('OMAPACKS_GITHUB_TOKEN','GITHUB_TOKEN','GH_TOKEN','SSH_AUTH_SOCK','SPICETIFY_CONFIG')}
            env.update(HOME=str(home),SPICETIFY_CONFIG=str(spice))
            result=runner.run([str(tool/'spicetify'),'backup','apply','--no-restart'],env=env,timeout=240)
            atomic(generation/'prepare.log',(result.stdout+'\n'+result.stderr).encode(),0o600)
            if not (client/'Apps/xpui/helper/spicetifyWrapper.js').is_file(): raise Error('Spicetify no produjo el componente requerido','check')
            if not (client/'Apps/xpui/marketplace/index.js').is_file():
                # Spicetify versions can flatten the custom-app bundle.
                if not any('marketplace' in p.name for p in (client/'Apps/xpui').iterdir()): raise Error('Marketplace no se aplicó','check')
            patch_native(client,spec)
            if inputs['source']!=tree(source) or inputs['tool']!=tree(tool) or inputs['market']!=tree(market): raise Error('Fuentes de Spotify cambiaron durante preparación','changed')
            record={'identity':identity,'generation':name,'client':tree(client),'launched':False}
            save_json(root/'current.json',record)
            save_json(generation/'preparation.json',{'status':'complete','identity':identity,'launch':False})
            return {'identity':identity,'generation':name,'status':'prepared','launched':False,'path':str(client/'spotify')}
        except BaseException as e:
            save_json(generation/'preparation.json',{'status':'partial','identity':identity,'launch':False,'error':str(e)})
            raise

def launch(home,args):
    """Only an explicit manual launcher invocation reaches execv."""
    from .engine import Engine
    engine=Engine(home)
    installed=engine.installed()
    if engine.pending() or not installed.get('spotify'): raise Error('Spotify compartido no tiene una instalación completa; revisa OmaPacks.')
    for item in installed['files'].values():
        if item['target'].startswith((RES+'/',TOOL+'/',MARKET.rsplit('/',1)[0]+'/')):
            if engine.files.state(item['target'])!=item['after']: raise Error('Un recurso administrado de Spotify cambió; revisa el conflicto en OmaPacks.','changed')
    result=prepare(home)
    os.execv(result['path'],[result['path'],*args])

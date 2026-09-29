"""Pinned native plugins, owned files and one service membership; no installer scripts."""
import json,os,re
from pathlib import Path
from . import artifact
from .util import Error,digest,relative,clean,secure_path

PREFIX='.config/omarchy/plugins/'

def inventory(home,target):
    root=secure_path(home,target)
    if not root.exists(): return {}
    result={}
    for p in sorted(root.rglob('*')):
        rel=p.relative_to(root).as_posix(); secure_path(root,rel)
        if p.is_dir(): continue
        if not p.is_file() or p.stat().st_size>16*1024*1024 or len(result)>=4096: raise Error('Recurso local de plugin no verificable')
        result[rel]={'sha256':digest(p.read_bytes()),'mode':p.stat().st_mode&0o777}
    return result

def identities(home,plugin):
    """Native manifest locations, without catalog deduplication hiding collisions."""
    user=Path(home)/PREFIX
    system=Path(os.environ.get('OMARCHY_PATH','/usr/share/omarchy'))/'shell/plugins'
    candidates=list(user.glob('*/manifest.json'))
    if system.exists():
        candidates.extend(p for p in system.rglob('*') if len(p.relative_to(system).parts) in (2,3,4) and (p.name=='manifest.json' or p.name.endswith('.manifest.json')))
    matches=[]
    for path in sorted(candidates):
        if path.is_relative_to(user) and path.relative_to(user).parts[0].startswith('.'): continue
        try:
            if path.stat().st_size>1024*1024: raise Error('Manifiesto local de plugin demasiado grande: '+str(path))
            value=json.loads(path.read_text())
            if not isinstance(value,dict): raise ValueError('objeto requerido')
        except (OSError,ValueError) as e: raise Error('No se pudo comprobar el registro de plugins: '+str(path)) from e
        if value.get('id')==plugin: matches.append(str(path))
    return matches

def validate(spec):
    plugin=spec.get('plugin_id','')
    if not re.fullmatch(r'[a-z][a-z0-9_-]*(?:\.[a-z0-9_-]+){2,}',plugin) or plugin.startswith(('omarchy.','omapacks.','heartyfm.omapacks')):
        raise Error('Identificador de plugin externo inválido o reservado')
    revision=spec.get('revision','')
    match=re.fullmatch(r'https://codeload.github.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/tar.gz/([0-9a-f]{40})',spec['url'])
    if not match or match[3]!=revision: raise Error('Plugin nativo requiere un archivo GitHub fijado al commit completo')
    if spec.get('target')!=PREFIX+plugin: raise Error('El plugin solo puede escribir en su directorio declarado')
    return match[2]+'-'+revision+'/'

def resources(spec,stage):
    prefix=validate(spec); data=Path(spec['stage']).read_bytes()
    if len(data)!=spec['size'] or digest(data)!=spec['sha256']: raise Error('Archivo de plugin modificado','integrity')
    modes={}; raw=artifact.unpack(data,Path(stage)/('plugin-source-'+spec['id']),modes=modes)
    files={}; review=[]
    for name,body in raw.items():
        if not name.startswith(prefix): raise Error('Recurso fuera de la raíz del plugin fijado')
        rel=name[len(prefix):]; relative(rel)
        # Do not distribute upstream agent sessions or repository tooling.
        if any(part.startswith('.') for part in rel.split('/')) or rel in ('CLAUDE.md','AGENTS.md','preview.png'): continue
        files[rel]=(body,modes[name])
        if b'\x00' not in body: review.append('--- '+rel+' ---\n'+clean(body.decode('utf-8',errors='replace')))
    try: manifest=json.loads(files['manifest.json'][0])
    except (KeyError,ValueError): raise Error('Plugin sin manifiesto válido')
    if manifest.get('id')!=spec['plugin_id'] or manifest.get('version')!=spec['version'] or manifest.get('schemaVersion')!=1:
        raise Error('Identidad o versión del plugin distinta de la receta')
    if 'service' not in manifest.get('kinds',[]) or not isinstance(manifest.get('entryPoints'),dict):
        raise Error('Este adaptador solo activa plugins con servicio; no cambia la barra')
    for point in manifest['entryPoints'].values():
        relative(point)
        if point not in files: raise Error('Entry point del plugin ausente')
    return files,'\n\n'.join(review)

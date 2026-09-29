"""Signed manager prerequisite; separate trust domain and transaction from packs."""
from __future__ import annotations
import json,os,re,shutil,subprocess,sys,tempfile,uuid
from pathlib import Path
from . import __version__
from .artifact import unpack
from .config import public_identity
from .github import GitHub,pin,repository,published
from .manifest import fields,string,SHA
from .util import Error,atomic,canonical,digest,file_state,lock,read_json,save_json,secure_path,version

OFFICIAL_REPOSITORY='HeartyFM/omapacks-plugin'
ASSETS=('omapacks-manager.json','omapacks-manager.json.sig','omapacks-manager.tar.gz')
NAMESPACE='omapacks-manager-v1'
TOP={'install.py','install.sh','uninstall.sh','publisher.pub','bundle.json','LEEME.md','bin/omapacks'}
REQUIRED=TOP-{'LEEME.md'} | {'omapacks/__init__.py','omapacks/cli.py'}


def allowed(name):
    return name in TOP or bool(re.fullmatch(r'omapacks/[A-Za-z_][A-Za-z0-9_]*\.py',name))


def inventory(root):
    values={}
    for p in sorted(Path(root).rglob('*')):
        if p.is_symlink(): raise Error('Enlace en la copia del gestor; revisar antes de actualizar','changed')
        if p.is_dir(): continue
        if '__pycache__' in p.parts or p.suffix=='.pyc': continue
        values[p.relative_to(root).as_posix()]=file_state(p)
    return values


def policy(config):
    target=secure_path(config.home,'.local/share/omapacks-manager')
    marker=read_json(target/'omapacks-manager.json',{})
    if marker.get('version')!=__version__:
        raise Error('La copia en uso no coincide con el gestor instalado. Cierra y abre OmaPacks desde su acceso instalado.','changed')
    repo=marker.get('manager_repository')
    if not repo: raise Error('Esta instalación no tiene un origen de actualización del gestor. Reinstala el plugin configurado por Diego; se conservan contenido y respaldos.','setup')
    repository(repo)
    key,fingerprint=public_identity(secure_path(target,'publisher.pub'))
    if marker.get('repository')!=config.data.get('repository') or config.trust.read_text().strip()!='omapacks-release namespaces="omapacks-v1" '+key:
        raise Error('El origen o la confianza local no coincide con la entrega del gestor. No se cambia automáticamente.','changed')
    return {'repository':repo,'key':key,'fingerprint':fingerprint,'content_repository':marker['repository']}


def snapshot(config):
    from .engine import Engine
    if Engine(config.home,settings=config.data).pending():
        raise Error('Hay contenido parcialmente aplicado. Revisa su recuperación antes de actualizar el gestor.','partial')
    if read_json(config.state/'manager-update.json',{}).get('status')=='preparing':
        raise Error('Hay una actualización del gestor interrumpida. Conserva sus carpetas y manager-update.json; revisa cuál copia está activa antes de reinstalar.','partial')
    target=secure_path(config.home,'.local/share/omapacks-manager')
    launcher=config.home/'.local/bin/omapacks'
    if not launcher.is_symlink() or launcher.resolve()!=target/'bin/omapacks':
        raise Error('El acceso instalado al gestor cambió; compruébalo antes de actualizar.','changed')
    return {'policy':policy(config),'manager':inventory(target),
            'settings':file_state(secure_path(config.directory,'settings.json')),
            'trust':file_state(secure_path(config.directory,'allowed_signers')),
            'content':file_state(secure_path(config.state,'installed.json'))}


def verify(directory,trust,identity,destination):
    """Verify manager signature independently from the content's signature."""
    directory=Path(directory); destination=Path(destination)
    index=secure_path(directory,ASSETS[0]).read_bytes()
    if len(index)>2*1024*1024: raise Error('Índice de gestor demasiado grande','integrity')
    with tempfile.TemporaryDirectory(prefix='omapacks-manager-trust-') as td:
        signers=Path(td)/'signers'
        signers.write_text('omapacks-manager namespaces="'+NAMESPACE+'" '+trust['key']+'\n')
        r=subprocess.run(['ssh-keygen','-Y','verify','-f',str(signers),'-I','omapacks-manager','-n',NAMESPACE,'-s',str(secure_path(directory,ASSETS[1]))],input=index,capture_output=True)
    if r.returncode: raise Error('Firma del gestor inválida o publicador no autorizado','signature')
    try:
        meta=json.loads(index)
        keys=('schema','repository','tag','version','archive_sha256','files','executables')
        fields(meta,keys,keys)
        if meta['schema']!=1 or type(meta['schema']) is not int: raise Error('Índice de gestor incompatible')
        string(meta['version'],r'\d+\.\d+\.\d+'); version(meta['version'])
        string(meta['archive_sha256'],SHA)
        if meta['repository']!=trust['repository'] or identity['repository']!=trust['repository'] or meta['tag']!=identity['tag'] or meta['tag']!='v'+meta['version']:
            raise Error('El gestor pertenece a otro origen o release','signature')
        if not isinstance(meta['files'],dict) or not REQUIRED<=meta['files'].keys() or any(not allowed(n) for n in meta['files']):
            raise Error('Archivos del gestor fuera del contrato','integrity')
        for value in meta['files'].values(): string(value,SHA)
        if not isinstance(meta['executables'],list) or len(set(meta['executables']))!=len(meta['executables']) or not set(meta['executables'])<=meta['files'].keys() or not {'bin/omapacks','install.sh','uninstall.sh'}<=set(meta['executables']):
            raise Error('Permisos del gestor inválidos','integrity')
        archive=secure_path(directory,ASSETS[2])
        if archive.stat().st_size>64*1024*1024: raise Error('Gestor demasiado grande','integrity')
        payload=archive.read_bytes()
        if digest(payload)!=meta['archive_sha256']: raise Error('Hash del gestor inválido','integrity')
        modes={}; unpack(payload,destination,meta['files'],modes)
        if sorted(n for n,m in modes.items() if m==0o755)!=sorted(meta['executables']):
            raise Error('Permisos distintos del índice firmado','integrity')
        for name,mode in modes.items(): secure_path(destination,name).chmod(mode)
        bundle=read_json(destination/'bundle.json')
        if bundle!={'repository':trust['content_repository'],'manager_version':meta['version'],'manager_repository':trust['repository']}:
            raise Error('La actualización cambiaría el origen o su política','integrity')
        if public_identity(destination/'publisher.pub')[0]!=trust['key']:
            raise Error('La actualización cambiaría la confianza','signature')
        if (destination/'omapacks/__init__.py').read_text().strip() not in ("__version__ = '"+meta['version']+"'", "__version__='"+meta['version']+"'"):
            raise Error('Versión del código distinta del índice','integrity')
        return meta
    except (OSError,ValueError,KeyError,TypeError) as e:
        raise Error('Entrega del gestor inválida ('+type(e).__name__+')','integrity') from e


def prepare(config,required,client=None):
    version(required)
    before=snapshot(config); trust=before['policy']
    client=client or GitHub(trust['repository'],config.cache/'manager',asset_names=ASSETS)
    if client.repo!=trust['repository']: raise Error('Origen de gestor inesperado','changed')
    result=client.releases()
    if result['cached'] or not result['complete']: raise Error('No se puede actualizar el gestor con una consulta incompleta o en caché. Reintenta cuando haya conexión.','network')
    candidates=[]
    for row in result['releases']:
        tag=row['tag_name']
        if row.get('draft') or row.get('prerelease') or published(row.get('published_at'))==float('-inf') or not re.fullmatch(r'v\d+\.\d+\.\d+',tag): continue
        if version(tag)>=version(required) and version(tag)>version(__version__): candidates.append(row)
    if not candidates: raise Error('Todavía no hay una release estable del gestor que cumpla '+required+'. No se ha cambiado nada. Solicita a Diego una entrega compatible.','incompatible')
    row=max(candidates,key=lambda r:version(r['tag_name']))
    identity=pin(trust['repository'],row,ASSETS)
    root=secure_path(config.cache,'manager/staging'); root.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='verified-',dir=root))
    client.download(identity,stage)
    meta=verify(stage,trust,identity,stage/'review')
    if version(meta['version'])<version(required) or version(meta['version'])<=version(__version__): raise Error('El gestor firmado no cumple la versión requerida','incompatible')
    return {'identity':identity,'meta':meta,'stage':str(stage),'before':before,'required':required},client


def apply(config,plan,client,progress=lambda phase:None):
    """Only call after explicit approval. Keep the prior binary, never touch packs."""
    with lock(config.state):
        progress('Revalidar gestor, confianza y release')
        if snapshot(config)!=plan['before']: raise Error('El estado cambió desde el reporte. Vuelve a revisar la actualización.','changed')
        client.verify_pin(plan['identity'])
        target=secure_path(config.home,'.local/share/omapacks-manager')
        backup=secure_path(config.home,'.local/share/omapacks-manager-backups/'+uuid.uuid4().hex)
        backup.parent.mkdir(parents=True,exist_ok=True)
        stage=Path(tempfile.mkdtemp(prefix='.omapacks-update-',dir=target.parent))
        moved=False; activated=False; journal=config.state/'manager-update.json'
        status={'status':'preparing','from':__version__,'to':plan['meta']['version'],'backup':str(backup),'content_changed':False}
        try:
            progress('Verificar firma, archivos y permisos del gestor')
            meta=verify(plan['stage'],plan['before']['policy'],plan['identity'],stage)
            if meta!=plan['meta'] or version(meta['version'])<=version(__version__) or version(meta['version'])<version(plan['required']): raise Error('Cambió la entrega aprobada','changed')
            save_json(stage/'omapacks-manager.json',{'version':meta['version'],'repository':config.data['repository'],'manager_repository':client.repo})
            progress('Comprobar arranque de la nueva versión')
            p=subprocess.run([sys.executable,'-I','-B',str(stage/'bin/omapacks'),'--version'],capture_output=True,text=True,timeout=30)
            if p.returncode or p.stdout.strip()!='OmaPacks gestor '+meta['version']: raise Error('La nueva copia no supera la comprobación de arranque','installer')
            # Revalidate after the executable check and immediately before swapping.
            client.verify_pin(plan['identity'])
            if snapshot(config)!=plan['before']: raise Error('El estado cambió durante la preparación; revisa otro reporte','changed')
            save_json(journal,status)
            progress('Guardar gestor anterior y activar la copia verificada')
            os.rename(target,backup); moved=True
            os.rename(stage,target); activated=True
            save_json(journal,{**status,'status':'complete'})
        except BaseException as e:
            if moved:
                if activated: shutil.rmtree(target)
                os.rename(backup,target)
                save_json(journal,{**status,'status':'failed-restored'})
            elif read_json(journal,{}).get('status')=='preparing':
                save_json(journal,{**status,'status':'failed-before-activation'})
            if isinstance(e,KeyboardInterrupt): raise
            if isinstance(e,Error) and not moved: raise
            raise Error('No se pudo actualizar el gestor. '+('Se restauró la copia anterior. ' if moved else 'La copia anterior sigue activa. ')+
                        'No se aplicó contenido. Conserva el diagnóstico y vuelve a revisar la actualización. Causa: '+type(e).__name__,'installer') from e
        finally:
            if stage.exists(): shutil.rmtree(stage)
        return {**status,'status':'complete'}


def restart(config,release_id):
    # New interpreter, new verified download, new plan and new content approval.
    launcher=config.home/'.local/bin/omapacks'
    discard_input()
    os.execv(str(launcher),['omapacks','--home',str(config.home),'tui','--release-id',str(release_id)])


def discard_input():
    # Input typed while preparing/updating must never approve the new pack plan.
    import termios
    if sys.stdin.isatty(): termios.tcflush(sys.stdin.fileno(),termios.TCIFLUSH)

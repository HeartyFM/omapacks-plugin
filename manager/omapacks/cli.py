from __future__ import annotations
import argparse, json, os, shutil, sys, tempfile
from pathlib import Path
from . import __version__
from .artifact import build, inspect_content, unpack, verify
from .config import Config
from .engine import Engine
from .github import GitHub,pin
from .manifest import load
from .tui import describe
from .util import Error, Runner, atomic, canonical, clean, digest, read_json, require_user, save_json, secure_path

def parser():
    p=argparse.ArgumentParser(prog='omapacks',description='OmaPacks · Configuración compartida')
    p.add_argument('--version',action='version',version='OmaPacks gestor '+__version__)
    p.add_argument('--home',type=Path,help='Hogar explícito para instalación aislada/pruebas')
    sub=p.add_subparsers(dest='command')
    t=sub.add_parser('tui'); t.add_argument('--mode',choices=['install','update'],default='install')
    t.add_argument('--release-id',type=int,help='Abrir un reporte nuevo tras actualizar el gestor; nunca reutiliza un plan')
    sub.add_parser('status'); sub.add_parser('doctor'); sub.add_parser('releases')
    c=sub.add_parser('configure'); c.add_argument('--repo',required=True); c.add_argument('--public-key',required=True); c.add_argument('--yes',action='store_true'); c.add_argument('--system-file',action='append',default=[]); c.add_argument('--service',action='append',default=[])
    f=sub.add_parser('fetch'); f.add_argument('release_id',type=int)
    pplan=sub.add_parser('plan'); pplan.add_argument('stage',type=Path); pplan.add_argument('--decisions',type=Path); pplan.add_argument('--output',type=Path)
    a=sub.add_parser('apply'); a.add_argument('plan',type=Path); a.add_argument('--approve',required=True)
    r=sub.add_parser('restore'); r.add_argument('transaction'); r.add_argument('--yes',action='store_true')
    v=sub.add_parser('validate'); v.add_argument('source',type=Path)
    b=sub.add_parser('pack'); b.add_argument('source',type=Path); b.add_argument('--output',required=True,type=Path); b.add_argument('--repo',required=True); b.add_argument('--tag',required=True); b.add_argument('--key',required=True)
    pub=sub.add_parser('publish'); pub.add_argument('directory',type=Path); pub.add_argument('--commit',required=True); pub.add_argument('--public-key',required=True); pub.add_argument('--yes',action='store_true')
    bt=sub.add_parser('build-tool'); bt.add_argument('stage',type=Path); bt.add_argument('tool_id'); bt.add_argument('--reviewed-sha256',required=True)
    return p

def build_tool(config,args):
    identity=read_json(args.stage/'identity.json'); manifest,meta=verify(args.stage,config.trust,identity)
    d=next((x for x in manifest.get('downloads',[]) if x['id']==args.tool_id and x['format']=='source-tar'),None)
    if not d or args.reviewed_sha256!=d['sha256']: raise Error('Aprueba el hash exacto de la fuente propia revisada')
    from .providers import Providers
    providers=Providers(); actions=providers.plan(manifest,args.stage); a=next(x for x in actions if x.get('id')==d['id'])
    work=args.stage/('build-'+d['id']); unpack(Path(a['stage']).read_bytes(),work)
    # Build recipes are intentionally bounded to fixed builders, never a shell string.
    declared={p['name'] for p in manifest.get('packages',[]) if p['provider']=='arch'}
    tools=['make'] if d['build']=='make' else ['cargo']
    if not set(tools)<=declared: raise Error('Declara herramientas de compilación como dependencias Arch')
    for name in tools:
        if not providers.installed(name): raise Error('Falta herramienta de compilación: '+name)
    argv=['make'] if d['build']=='make' else ['cargo','build','--locked','--release','--offline']
    providers.runner.run(argv,cwd=work,interactive=True,timeout=None)
    output=secure_path(work,d['check'])
    if not output.is_file(): raise Error('La compilación no produjo la salida declarada')
    target=args.stage/('built-'+d['id']); name=Path(d['check']).name
    atomic(target/'output'/name,output.read_bytes(),0o755)
    save_json(target/'build.json',{'source_sha256':d['sha256'],'outputs':{name:digest(output.read_bytes())},'check':'La salida declarada existe; comprobar funciones por separado'})
    return {'built':str(target)}

def publish(args):
    import re
    if not re.fullmatch(r'[0-9a-f]{40}',args.commit): raise Error('Publicación requiere una revisión Git fija de 40 caracteres')
    with tempfile.TemporaryDirectory() as td:
        cfg=Config(td); metadata=read_json(args.directory/'omapacks.json'); cfg.configure(metadata['repository'],args.public_key)
        manifest,meta=verify(args.directory,cfg.trust)
    result={'repository':meta['repository'],'tag':meta['tag'],'commit':args.commit,'assets':[str(args.directory/n) for n in ('omapacks.json','omapacks.json.sig','omapacks.tar.gz')],'published':False}
    if not args.yes: return {**result,'next':'Revisa esta entrega y ejecuta el mismo comando con --yes para crear y publicar la release.'}
    runner=Runner()
    # Never overwrite assets/releases. Upload into a draft; publish only after assets succeed.
    exists=runner.run(['gh','release','view',meta['tag'],'--repo',meta['repository']],check=False)
    if exists.returncode==0: raise Error('La release ya existe; no se reemplaza contenido publicado')
    runner.run(['gh','release','create',meta['tag'],'--repo',meta['repository'],'--target',args.commit,'--draft','--title',meta['tag'],'--notes-file',str(args.directory/'NOTES.md'),*result['assets']],timeout=180)
    runner.run(['gh','release','edit',meta['tag'],'--repo',meta['repository'],'--draft=false'],timeout=60)
    return {**result,'published':True}

def main(argv=None):
    args=parser().parse_args(argv); require_user(); config=Config(args.home)
    cmd=args.command or 'tui'
    if cmd=='configure':
        if not args.yes: raise Error('Cambiar origen/confianza requiere --yes tras revisar el repositorio y clave pública')
        config.configure(args.repo,args.public_key,system_files=args.system_file,services=args.service); result={'configured':str(config.path),'repository':args.repo}
    elif cmd=='validate':
        m,entries=inspect_content(args.source); result={'valid':True,'id':m['id'],'version':m['version'],'files':len(entries),'note':'El escaneo es preventivo; Diego debe revisar el contenido propio antes de publicarlo.'}
    elif cmd=='pack': result=build(args.source,args.output,args.repo,args.tag,args.key)
    elif cmd=='publish': result=publish(args)
    elif cmd=='doctor':
        from .host import detect
        result={'manager':__version__,'host':detect(config.home),'requirements':{name:bool(shutil.which(name)) for name in ('python3','gum','ssh-keygen','omarchy','pacman')},'configured':bool(config.data.get('repository'))}
    elif cmd=='status':
        engine=Engine(config.home,settings=config.data); result={'manager':__version__,'installed':engine.installed(),'pending':[str(p) for p in engine.pending()]}
    elif cmd=='restore': result=Engine(config.home,settings=config.data).restore(args.transaction,args.yes)
    else:
        config.require(); client=GitHub(config.data['repository'],config.cache)
        if cmd=='tui':
            from .tui import run
            return run(config,getattr(args,'mode','install'),release_id=getattr(args,'release_id',None))
        if cmd=='releases': result=client.releases()
        elif cmd=='fetch':
            identity=pin(config.data['repository'],client.release(args.release_id))
            stage=config.cache/'staging'/digest(canonical(identity)); client.download(identity,stage)
            manifest,meta=verify(stage,config.trust,identity); save_json(stage/'identity.json',identity)
            result={'stage':str(stage),'version':manifest['version'],'identity':identity}
        elif cmd=='plan':
            identity=read_json(args.stage/'identity.json')
            if not identity: raise Error('Stage sin identidad de release')
            manifest,meta=verify(args.stage,config.trust,identity)
            plan=Engine(config.home,settings=config.data).plan(args.stage,manifest,meta,identity,decisions=read_json(args.decisions,{}) if args.decisions else {})
            output=args.output or args.stage/'plan.json'; save_json(output,plan)
            print(describe(plan)); print('\nPlan guardado en '+str(output)); return 0
        elif cmd=='apply':
            plan=read_json(args.plan)
            manifest,meta=verify(plan['stage'],config.trust,plan['identity'])
            if manifest!=plan['manifest'] or meta!=plan['meta']: raise Error('El plan no coincide con la entrega firmada')
            # Rebuild all desired operations from authenticated resources. Never execute arbitrary plan JSON.
            engine=Engine(config.home,settings=config.data)
            recomputed=engine.plan(plan['stage'],manifest,meta,plan['identity'],decisions=plan['decisions'])
            if recomputed!=plan: raise Error('El plan dejó de ser válido; revisa uno nuevo', 'changed')
            result=engine.apply(plan,args.approve,progress=lambda s:print(s,file=sys.stderr),verify_remote=client.verify_pin)
        elif cmd=='build-tool': result=build_tool(config,args)
    print(json.dumps(result,indent=2,ensure_ascii=False)); return 0

def entry():
    try: return main()
    except KeyboardInterrupt: print('\nOperación cancelada. Si había cambios en curso, consulta «omapacks status».',file=sys.stderr); return 130
    except (Error,OSError,ValueError,KeyError) as e:
        print('OmaPacks: '+clean(str(e)),file=sys.stderr); return 1
if __name__=='__main__': sys.exit(entry())

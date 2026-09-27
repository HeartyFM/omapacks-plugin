from __future__ import annotations
import base64, copy, datetime as dt, json, os, pwd, re, shutil, tempfile, uuid
from pathlib import Path
from . import artifact, content_menu, preferences, hypr
from .fs import Files
from .host import detect
from .manifest import compatibility, destination
from .providers import Providers
from .util import Error, Runner, atomic, canonical, clean, digest, lock, read_json, require_user, save_json, secure_path

BEGIN='# OmaPacks: begin'; END='# OmaPacks: end'

def key(scope,target): return scope+':'+target

def migration_path(manifest, installed):
    start=installed.get('epoch') if installed else None; end=manifest['recovery']['epoch']
    if start is None or start==end: return []
    queue=[(start,[])]; seen=set()
    while queue:
        node,path=queue.pop(0)
        if node in seen: continue
        seen.add(node)
        for m in manifest.get('migrations',[]):
            if m['from']!=node or m['id'] in installed.get('migrations',[]): continue
            route=path+[m]
            if m['to']==end: return route
            queue.append((m['to'],route))
    raise Error('No existe un camino de migración desde '+str(start)+' hasta '+end+'. No se ejecuta una migración inversa implícita.', 'incompatible')

class Engine:
    def __init__(self, home, state=None, providers=None, host=None, settings=None, system_root='/'):
        self.home=Path(home).absolute(); self.state=Path(state or self.home/'.local/state/omapacks')
        self.providers_is_injected=providers is not None; self.providers=providers or Providers(); self.runner=self.providers.runner
        self.host_is_injected=host is not None; self.host=host or detect(self.home,self.runner); self.settings=settings or {}
        self.system_root=Path(system_root); self.files=Files(self.home); self.system=Files(system_root,0 if system_root=='/' else os.getuid())
    def installed(self): return read_json(self.state/'installed.json',{})
    def pending(self):
        return [p for p in (self.state/'transactions').glob('*/journal.json') if read_json(p,{}).get('status') in ('applying','partial','recovering')]
    def storage(self,scope): return self.files if scope=='user' else self.system
    def content(self,stage,meta):
        for name,sha in meta['files'].items():
            if digest(secure_path(Path(stage)/'content',name).read_bytes())!=sha: raise Error('Contenido cambiado después de verificar', 'changed')

    def plan(self, stage, manifest, meta, identity, *, decisions=None):
        require_user(); compatibility(manifest,self.host); stage=Path(stage).absolute(); self.content(stage,meta)
        installed=self.installed()
        if installed and installed.get('content_id')!=manifest['id']: raise Error('Identidad de contenido distinta de la instalada; revisa una retirada separada')
        if self.pending(): raise Error('Hay una operación incompleta. Revísala o restaura sus archivos antes de instalar otra release.', 'partial')
        route=migration_path(manifest,installed)
        actions=self.providers.plan(manifest,stage)
        wanted={}; code_reviews=[]; builds=[]
        def put(scope,target,data,mode=0o644,kind='file',**extra):
            k=key(scope,target)
            if k in wanted: raise Error('Dos recursos intentan administrar el mismo destino: '+target)
            wanted[k]={'scope':scope,'target':target,'data':base64.b64encode(data).decode(),'after':{'sha256':digest(data),'mode':mode},'kind':kind,**extra}
        for f in manifest.get('files',[]):
            data=secure_path(stage/'content',f['source']).read_bytes()
            if f.get('kind')=='hypr_include':
                fmt=self.host.get('hyprland_format')
                if not fmt or not f['target'].endswith('.'+fmt): raise Error('Include distinto del formato Hyprland detectado')
                if manifest['compatibility'].get('hyprland_format')!=fmt: raise Error('Hyprland necesita compatibilidad de formato explícita')
                if not any(c['kind']=='hyprland' and c['required'] for c in manifest.get('checks',[])): raise Error('Hyprland requiere comprobación posterior obligatoria')
                # Reject hardware/settings that must remain machine-local, plus destructive binding changes.
                text=data.decode()
                if re.search(r'\b(?:monitor|unbind|bind|bind[a-z_]+|exec|dispatch|os\.|io\.|input|device|env|keyword)\b',text,re.I): raise Error('Drop-in Hyprland contiene operaciones de equipo/ejecución fuera del perfil común')
                snippet='.config/omapacks-shared/hyprland.'+fmt
                put('user',snippet,data)
                current=self.files.read(f['target'])
                if current is None: raise Error('Falta configuración principal de Hyprland')
                main=current[0].decode(); begin='-- OmaPacks: begin' if fmt=='lua' else BEGIN; end='-- OmaPacks: end' if fmt=='lua' else END
                line='dofile(os.getenv("HOME") .. "/'+snippet+'")' if fmt=='lua' else 'source = ~/'+snippet
                block=begin+'\n'+line+'\n'+end
                if main.count(begin)!=main.count(end) or main.count(begin)>1: raise Error('Bloque OmaPacks alterado en Hyprland')
                if begin in main: main=re.sub(re.escape(begin)+'.*?'+re.escape(end),lambda _:block,main,flags=re.S)
                else: main=main.rstrip()+'\n\n'+block+'\n'
                put('user',f['target'],main.encode(),current[1],'hypr_include')
                code_reviews.append({'source':f['source'],'content':clean(text),'notice':'Configuración Lua firmada: revisar como código del escritorio; no hay aislamiento.'})
            elif f.get('kind')=='xdg_defaults':
                defaults=preferences.validate(data.decode(),manifest.get('packages',[]))
                for target,values in defaults.items():
                    current=self.files.read(target); original=current[0].decode() if current else ''
                    old=installed.get('files',{}).get(key('user',target),{})
                    merged,conflict,baseline=preferences.merge(original,preferences.PATHS[target],values,old)
                    put('user',target,merged.encode(),current[1] if current else 0o644,'xdg_defaults',owned_values=values,baseline_values=baseline,owned_conflict=conflict,owned_before=preferences.read(original,preferences.PATHS[target]))
            elif f.get('kind')=='omarchy_menu':
                entries=content_menu.validate(data.decode())
                current=self.files.read(f['target'])
                original=current[0].decode() if current else '{}\n'
                old=installed.get('files',{}).get(key('user',f['target']),{})
                merged,conflict=content_menu.merge(original,entries,old.get('menu_entries',{}))
                put('user',f['target'],merged.encode(),current[1] if current else 0o644,'omarchy_menu',menu_entries=entries,owned_conflict=conflict)
            else: put(f['scope'],f['target'],data,f.get('mode',0o644))
        for a in actions:
            if a['provider']!='external' or a['format']=='arch': continue
            if a['format']=='appimage': put('user',a['target'],Path(a['stage']).read_bytes(),0o755)
            elif a['format']=='tar':
                extracted=stage/('external-'+a['id'])
                modes={}; resources=artifact.unpack(Path(a['stage']).read_bytes(),extracted,modes=modes)
                for rel,data in resources.items():
                    target=a['target']+'/'+rel; destination(target)
                    put('user',target,data,modes[rel])
            elif a['format']=='source-tar':
                built=stage/('built-'+a['id']); record=read_json(built/'build.json')
                if not record or record.get('source_sha256')!=a['sha256']:
                    work=stage/('build-'+a['id']); resources=artifact.unpack(Path(a['stage']).read_bytes(),work)
                    review='\n\n'.join('--- '+name+' ---\n'+clean(data.decode('utf-8',errors='replace')) for name,data in sorted(resources.items()))
                    builds.append({**a,'review':review,'resources':{n:digest(b) for n,b in resources.items()}})
                    continue
                for rel,sha in record['outputs'].items():
                    data=secure_path(built/'output',rel).read_bytes()
                    if digest(data)!=sha: raise Error('Salida compilada modificada')
                    put('user',a['target']+'/'+rel,data,0o755)
        decisions=decisions or {}; previous=installed.get('files',{}); changes=[]
        for k in sorted(set(wanted)|set(previous)):
            desired=wanted.get(k); old=previous.get(k); scope,target=k.split(':',1); store=self.storage(scope)
            if scope=='system' and target not in self.settings.get('system_files',[]): raise Error('Destino de sistema requiere permiso administrativo inicial: '+target)
            before=store.state(target); conflict=False
            if desired:
                after=desired['after']; action='keep' if before==after else 'create' if before is None else 'modify'
                conflict=before is not None and before!=after and (not old or before!=old['after'])
                if desired.get('kind') in ('omarchy_menu','xdg_defaults'): conflict=desired['owned_conflict']
                if desired.get('kind')=='hypr_include' and not old and before:
                    original=store.read(target)[0].decode()
                    if 'OmaPacks: begin' not in original: conflict=False
            else:
                after=None; action='remove' if before else 'keep'
                conflict=before is not None and before!=old['after']
                if old.get('kind')=='xdg_defaults' and before:
                    original=store.read(target)
                    merged,conflict,_=preferences.merge(original[0].decode(),preferences.PATHS[target],{},old)
                    desired={'scope':scope,'target':target,'kind':'defaults_detach','data':base64.b64encode(merged.encode()).decode(),'after':{'sha256':digest(merged.encode()),'mode':original[1]}}
                    after=desired['after']; action='keep' if before==after else 'modify'
                if old.get('kind')=='omarchy_menu' and before:
                    original=store.read(target)
                    merged,conflict=content_menu.merge(original[0].decode(),{},old['menu_entries'])
                    desired={'scope':scope,'target':target,'kind':'menu_detach','data':base64.b64encode(merged.encode()).decode(),'after':{'sha256':digest(merged.encode()),'mode':original[1]}}
                    after=desired['after']; action='keep' if before==after else 'modify'
                if old.get('kind')=='hypr_include' and before:
                    original=store.read(target); text=original[0].decode()
                    begin='-- OmaPacks: begin' if target.endswith('.lua') else BEGIN
                    end='-- OmaPacks: end' if target.endswith('.lua') else END
                    if text.count(begin)!=1 or text.count(end)!=1: raise Error('El include Hyprland administrado fue alterado; se conserva la configuración principal')
                    block=re.search(re.escape(begin)+'.*?'+re.escape(end),text,re.S).group(0)
                    expected_line='dofile(os.getenv("HOME") .. "/.config/omapacks-shared/hyprland.lua")' if target.endswith('.lua') else 'source = ~/.config/omapacks-shared/hyprland.conf'
                    if block!=begin+'\n'+expected_line+'\n'+end: raise Error('El bloque Hyprland fue editado; revisa el conflicto antes de retirarlo')
                    stripped=re.sub(re.escape(begin)+'.*?'+re.escape(end)+'\n?', '', text, flags=re.S).encode()
                    desired={'scope':scope,'target':target,'kind':'hypr_detach','data':base64.b64encode(stripped).decode(),'after':{'sha256':digest(stripped),'mode':original[1]}}
                    after=desired['after']; action='modify'; conflict=False

            choice=decisions.get(k)
            if choice not in (None,'keep','skip','replace'): raise Error('Decisión de conflicto inválida')
            if conflict and choice in ('keep','skip'): action=choice
            if conflict and choice=='replace': conflict=False
            change={**(desired or {'scope':scope,'target':target,'kind':old.get('kind','file')}),'key':k,'action':action,'before':before,'after':after,'conflict':conflict,'decision':choice}
            changes.append(change)
        for m in route:
            if m['precondition']=='managed-files-clean' and any(c['conflict'] for c in changes): raise Error('Migración requiere archivos administrados sin modificaciones locales')
            if m['precondition']=='no-packages' and installed.get('packages'): raise Error('Migración requiere estado sin paquetes administrados')
        changes.sort(key=lambda c: (0 if c.get('kind')=='hypr_detach' else 2 if c.get('kind')=='hypr_include' else 1,c['key']))
        recipes=[]
        for recipe in manifest.get('recipes',[]):
            path=secure_path(self.home,recipe['prefix'])
            if path.exists() and not path.is_dir(): raise Error('El prefijo Wine existe como archivo')
            recipes.append({**recipe,'action':'keep' if path.exists() else 'initialize','before_exists':path.exists()})
        hypr_validation=None
        if any(c.get('kind') in ('hypr_include','hypr_detach') for c in changes):
            main=next(c for c in changes if c.get('kind') in ('hypr_include','hypr_detach'))
            snippet=next((c for c in changes if c['target'].startswith('.config/omapacks-shared/hyprland.') and c.get('data')),None)
            syntax=stage/('hypr-validate.'+self.host['hyprland_format'])
            snippet_path=stage/('hypr-dropin.'+self.host['hyprland_format'])
            source=base64.b64decode(main['data']).decode()
            if snippet:
                atomic(snippet_path,base64.b64decode(snippet['data']),0o644)
                source=source.replace('os.getenv("HOME") .. "/'+snippet['target']+'"',json.dumps(str(snippet_path))) if self.host['hyprland_format']=='lua' else source.replace('~/'+snippet['target'],str(snippet_path))
            atomic(syntax,source,0o644)
            bindings=json.loads(self.runner.run(['hyprctl','-j','binds']).stdout)
            essential=hypr.essential(bindings)
            if not essential: raise Error('No se pudieron identificar accesos esenciales; revisar Hyprland antes de instalar')
            hypr_validation={'essential_bindings':essential,'syntax':str(syntax),'syntax_sha256':digest(syntax.read_bytes()),'snippet':str(snippet_path) if snippet else None,'snippet_sha256':digest(snippet_path.read_bytes()) if snippet else None,'syntax_verified':False}
        ops=[]
        for op in manifest.get('operations',[]):
            if op['name'] not in self.settings.get('services',[]): raise Error('Servicio no autorizado durante configuración administrativa: '+op['name'])
            argv=['systemctl']+(['--user'] if op['scope']=='user' else [])
            before={what:self.runner.run(argv+[what,op['name']],check=False).stdout.strip() for what in ('is-active','is-enabled')}
            skip=(op['action']=='enable' and before['is-enabled']=='enabled') or (op['action']=='start' and before['is-active']=='active')
            ops.append({**op,'before':before,'skip':skip})
        changed=[c for c in changes if c['action'] not in ('keep','skip')]
        reloads=[]
        if any(c.get('kind') in ('hypr_include','hypr_detach') or c['target'].startswith('.config/omapacks-shared/hyprland.') for c in changed):
            reloads.append({'component':'hyprland','method':'hyprctl reload','verification':'configerrors y accesos esenciales'})
        if any(c.get('kind') in ('omarchy_menu','menu_detach') for c in changed):
            reloads.append({'component':'omarchy-menu','method':'hot-reload nativo','verification':'JSONC y entradas administradas; no confirma renderizado de la shell'})
        if any(c.get('kind') in ('xdg_defaults','defaults_detach') and c.get('decision') not in ('keep','skip') for c in changes):
            reloads.append({'component':'defaults','method':'lectura nativa al abrir cada aplicación','verification':'asociaciones, terminal y editor escritos; no reinicia aplicaciones abiertas'})
        reloads.sort(key=lambda r:r['component']=='hyprland')
        plan={'schema':1,'stage':str(stage),'identity':identity,'meta':meta,'manifest':manifest,'installed_before':installed,'host':self.host,'packages':actions,'files':changes,'operations':ops,'recipes':recipes,'builds':builds,'hypr_validation':hypr_validation,'reloads':reloads,'migrations':route,'code_reviews':code_reviews,'recovery':manifest['recovery'],'decisions':decisions,'home':str(self.home),'system_root':str(self.system_root)}
        plan['id']=digest(canonical(plan))
        return plan

    def revalidate(self,plan):
        if plan['home']!=str(self.home) or plan['system_root']!=str(self.system_root): raise Error('Plan de otro equipo/directorio')
        body={k:v for k,v in plan.items() if k!='id'}
        if digest(canonical(body))!=plan['id']: raise Error('Plan alterado', 'changed')
        if self.installed()!=plan['installed_before']: raise Error('El estado instalado cambió', 'changed')
        self.content(plan['stage'],plan['meta'])
        if not self.host_is_injected: self.host=detect(self.home,self.runner)
        if self.host!=plan['host']: raise Error('El equipo cambió; recalcula compatibilidad')
        for c in plan['files']:
            if self.storage(c['scope']).state(c['target'])!=c['before']: raise Error('Conflicto nuevo desde la aprobación: '+c['target'], 'changed')
            if c['conflict'] and c['action'] not in ('keep','skip'): raise Error('Conflicto sin resolver: '+c['target'])
        # Re-solve packages to catch material transaction changes BEFORE any mutation.
        if self.providers.plan(plan['manifest'],plan['stage'])!=plan['packages']: raise Error('Dependencias cambiaron desde la aprobación; recalcula el plan', 'changed')
        for recipe in plan.get('recipes',[]):
            if secure_path(self.home,recipe['prefix']).exists()!=recipe['before_exists']: raise Error('La condición del solucionador cambió; recalcula el plan')
        for op in plan['operations']:
            argv=['systemctl']+(['--user'] if op['scope']=='user' else [])
            for what,value in op['before'].items():
                if self.runner.run(argv+[what,op['name']],check=False).stdout.strip()!=value: raise Error('El servicio cambió desde la aprobación', 'changed')

    def mutate(self,c,data,mode,expected):
        if c['scope']=='user' or self.system_root!=Path('/'):
            store=self.storage(c['scope'])
            if data is None: store.remove(c['target'],expected)
            else: store.write(c['target'],data,mode,expected)
        else:
            request={'target':c['target'],'data':base64.b64encode(data).decode() if data is not None else None,'mode':mode,'expected':expected}
            helper=Path(__file__).with_name('privileged.py')
            self.runner.run(['sudo','/usr/bin/python3','-I',str(helper)],input=json.dumps(request),timeout=None)

    def apply(self,plan,approved,*,progress=lambda s:None,verify_remote=None,interrupt_after=None):
        require_user()
        if approved!=plan['id']: raise Error('Falta aprobación del plan exacto')
        with lock(self.state):
            if self.pending(): raise Error('Operación incompleta pendiente', 'partial')
            progress('1/6 · Comprobando identidad y plan')
            if verify_remote: verify_remote(plan['identity'])
            self.revalidate(plan)
            if not self.providers_is_injected and self.home!=Path(pwd.getpwuid(os.getuid()).pw_dir):
                system_effects=bool(plan['operations'] or plan.get('hypr_validation') or any(c['scope']=='system' for c in plan['files']) or any(a['action']!='keep' and (a['provider'] in ('arch','aur','flatpak','flatpak-remote') or a['provider']=='external' and a['format']=='arch') for a in plan['packages']))
                if system_effects: raise Error('Un hogar temporal no aísla pacman, servicios o Hyprland. Usa un entorno desechable real para esas pruebas; esta ejecución no los modificará.')
            if plan.get('hypr_validation'):
                validation=plan['hypr_validation']
                if digest(Path(validation['syntax']).read_bytes())!=validation['syntax_sha256'] or validation['snippet'] and digest(Path(validation['snippet']).read_bytes())!=validation['snippet_sha256']: raise Error('La configuración de validación cambió después de aprobación')
                # Lua is executable code. Only invoke its validator after approval, before activation.
                self.runner.run(['Hyprland','--verify-config','--config',validation['syntax']])
            tx=self.state/'transactions'/uuid.uuid4().hex; tx.mkdir(parents=True,mode=0o700)
            journal={'id':tx.name,'status':'applying','started':dt.datetime.now(dt.timezone.utc).isoformat(),'plan':plan,'files':[],'packages':[],'operations':[],'recipes':[],'checks':[],'reloads':[],'provider_stage':'not-started','error':None}
            def save(): save_json(tx/'journal.json',journal)
            save()
            try:
                progress('2/6 · Respaldos y dependencias')
                # Back up all files before the first external or desktop mutation.
                for c in plan['files']:
                    if c['action'] in ('keep','skip'): continue
                    prev=self.storage(c['scope']).read(c['target'])
                    entry={k:c[k] for k in ('key','scope','target','before','after','action')}; entry['phase']='prepared'
                    if prev:
                        backup=str(len(journal['files']))+'.bak'; atomic(tx/backup,prev[0]); entry['backup']=backup
                    journal['files'].append(entry); save()
                def package_done(a): journal['packages'].append(a); save()
                journal['provider_stage']='running'; save()
                self.providers.execute(plan['packages'],package_done)
                journal['provider_stage']='finished'; save()
                for build in plan.get('builds',[]):
                    self.providers.build_source(build,plan['manifest']); package_done({**build,'action':'built'})
                if plan.get('builds') or any(a['provider']=='preparation' for a in plan['packages']):
                    journal['status']='prepared'; journal['error']='Infraestructura preparada. Debes revisar y confirmar un nuevo plan antes de instalar el contenido.'; save(); return journal
                for a in plan['packages']:
                    if a['provider']=='external' and a['format']=='arch': self.providers.install_external_arch(a); package_done(a)
                progress('3/6 · Aplicando configuración')
                for i,entry in enumerate(journal['files']):
                    c=next(c for c in plan['files'] if c['key']==entry['key'])
                    entry['phase']='writing'; save()
                    data=base64.b64decode(c['data']) if c['action']!='remove' else None
                    self.mutate(c,data,c['after']['mode'] if c['after'] else 0o644,c['before'])
                    entry['phase']='done'; save()
                    if interrupt_after is not None and i+1==interrupt_after: raise InterruptedError('Interrupción de prueba después de escritura')
                for recipe in plan.get('recipes',[]):
                    result=self.run_recipe(recipe); journal['recipes'].append(result); save()
                for op in plan['operations']:
                    if op.get('skip'): continue
                    event={**op,'phase':'starting'}; journal['operations'].append(event); save()
                    argv=(['sudo'] if op['scope']=='system' else [])+['systemctl']+(['--user'] if op['scope']=='user' else [])+[op['action'],op['name']]
                    self.runner.run(argv,interactive=True,timeout=120); event['phase']='done'; save()
                progress('4/6 · Comprobando archivos y aplicaciones')
                checks=list(plan['manifest'].get('checks',[]))
                if plan.get('hypr_validation') and not any(c['kind']=='hyprland' for c in checks): checks.append({'kind':'hyprland','required':True})
                def checked(c):
                    result=self.check(c,plan); journal['checks'].append(result); save()
                    if c['required'] and not result['ok']: raise Error('Comprobación requerida falló: '+result['detail'], 'check')
                for c in checks:
                    if c['kind']!='hyprland': checked(c)
                progress('5/6 · Activando configuración y verificando recargas')
                for reload in plan.get('reloads',[]):
                    event={**reload,'phase':'starting'}; journal['reloads'].append(event); save()
                    if reload['component']=='hyprland': self.runner.run(['hyprctl','reload'])
                    elif reload['component']=='omarchy-menu':
                        current=content_menu.parse(self.files.read(content_menu.TARGET)[0].decode())
                        expected=next(c for c in plan['files'] if c['target']==content_menu.TARGET)
                        planned=content_menu.parse(base64.b64decode(expected['data']).decode())
                        if current!=planned: raise Error('El menú cambió antes de verificar la recarga', 'changed')
                    elif reload['component']=='defaults':
                        for c in plan['files']:
                            if c.get('kind') in ('xdg_defaults','defaults_detach') and c.get('decision') not in ('keep','skip') and c.get('after'):
                                if self.files.state(c['target'])!=c['after']: raise Error('Default modificado antes de verificar', 'changed')
                                env={**os.environ,'HOME':str(self.home),'XDG_CONFIG_HOME':str(self.home/'.config'),'XDG_DATA_HOME':str(self.home/'.local/share'),'XDG_STATE_HOME':str(self.home/'.local/state')}
                                # Effective XDG defaults can be shadowed by desktop-specific files.
                                # A byte-for-byte write alone does not prove the selected app is active.
                                values=preferences.read(self.files.read(c['target'])[0].decode(),preferences.PATHS[c['target']])
                                expected=c.get('owned_values',{})
                                if c['target']==preferences.MIME:
                                    queries=[(['xdg-mime','query','default',mime],value) for mime,value in expected.items()]
                                elif c['target']==preferences.TERMINAL:
                                    queries=[(['xdg-terminal-exec','--print-id'],values.get('value'))] if values.get('value') else []
                                else:
                                    queries=[(['omarchy-default-editor'],values.get('value') or 'nvim')]
                                for argv,value in queries:
                                    actual=self.runner.run(argv,env=env).stdout.strip()
                                    if argv[0]=='xdg-terminal-exec': actual=actual.split(':')[0]
                                    if actual!=value: raise Error('No se activó el default: '+' '.join(argv)+' → '+clean(actual)+' (esperado '+str(value)+'). Puede existir una preferencia específica del escritorio.', 'check')
                    event['phase']='done'; save()
                # Compositor checks run once, after all writes/downloads/services and reload.
                if any(c['kind']=='hyprland' for c in checks):
                    checked({'kind':'hyprland','required':any(c['required'] for c in checks if c['kind']=='hyprland')})
                progress('6/6 · Registrando resultado')
                managed={}
                partial=False
                for c in plan['files']:
                    if c['action'] in ('skip','keep') and c.get('decision') in ('skip','keep'):
                        partial=True
                        if c['key'] in plan['installed_before'].get('files',{}): managed[c['key']]=plan['installed_before']['files'][c['key']]
                    elif c['after'] and c['kind'] not in ('hypr_detach','menu_detach','defaults_detach'):
                        managed[c['key']]={'scope':c['scope'],'target':c['target'],'after':c['after'],'kind':c['kind']}
                        for field in ('menu_entries','owned_values','baseline_values'):
                            if field in c: managed[c['key']][field]=c[field]
                if partial:
                    journal['status']='partial'; journal['error']='Se conservaron/omitieron conflictos; la release completa no se marca instalada.'; save()
                    return journal
                installed={'content_id':plan['manifest']['id'],'version':plan['manifest']['version'],'identity':plan['identity'],'meta':plan['meta'],'modules':plan['manifest']['modules'],'files':managed,'packages':plan['packages'],'epoch':plan['manifest']['recovery']['epoch'],'migrations':plan['installed_before'].get('migrations',[])+[m['id'] for m in plan['migrations']],'transaction':tx.name,'checks':journal['checks'],'recipes':journal['recipes'],'reloads':journal['reloads']}
                save_json(self.state/'installed.json',installed)
                journal['status']='complete'; save(); return journal
            except BaseException as e:
                journal['status']='partial'; journal['error']=clean(str(e)) or type(e).__name__; save(); raise

    def run_recipe(self,recipe):
        path=secure_path(self.home,recipe['prefix'])
        # Condition is evaluated again immediately before attempting repair.
        if path.exists(): return {'id':recipe['id'],'status':'skipped','reason':'La condición prefix-absent no se cumple; prefijo conservado.'}
        if recipe['action']!='initialize': raise Error('La receta cambió desde el plan')
        path.parent.mkdir(parents=True,exist_ok=True)
        path.mkdir(mode=0o700)  # Exclusive: concurrent/personal prefixes cannot be overwritten.
        env={**os.environ,'WINEPREFIX':str(path),'WINEARCH':recipe['architecture']}
        self.runner.run(['wineboot','--init'],env=env,interactive=True,timeout=180)
        ok=(path/'system.reg').is_file() and (path/'drive_c').is_dir()
        if not ok: raise Error('Wine no creó un prefijo verificable; se conserva para diagnóstico', 'check')
        return {'id':recipe['id'],'status':'initialized','prefix':recipe['prefix'],'verified':'estructura básica; aplicaciones Windows sin probar','recovery':'Datos conservados; nunca se elimina automáticamente el prefijo.'}

    def check(self,c,plan):
        try:
            if c['kind']=='file':
                actual=self.storage(c.get('scope','user')).state(c['target'])
                ok=bool(actual and actual['sha256']==c['sha256']); detail=c['target']
            elif c['kind']=='version':
                r=self.runner.run([c['name'],'--version'],check=False); ok=r.returncode==0; detail=clean(r.stdout or r.stderr)[:1000]
            elif c['kind']=='wine-prefix':
                # Read-only diagnosis: never overwrite or implicitly create prefixes/saves.
                p=secure_path(self.home,c['prefix']); ok=(p/'system.reg').is_file() and (p/'drive_c').is_dir(); detail='Estructura del prefijo Wine (no prueba aplicaciones Windows)'
            elif c['kind']=='hyprland':
                r=self.runner.run(['hyprctl','configerrors'],check=False)
                ok=r.returncode==0 and not r.stdout.strip(); detail=clean(r.stdout or r.stderr) or 'Hyprland sin errores reportados'
                if plan.get('hypr_validation'):
                    now=json.loads(self.runner.run(['hyprctl','-j','binds']).stdout)
                    if not hypr.preserved(plan['hypr_validation']['essential_bindings'],now): ok=False; detail='Cambió un acceso esencial de Hyprland; restaura el respaldo.'
            return {'check':c,'ok':ok,'detail':detail}
        except Error as e: return {'check':c,'ok':False,'detail':str(e)}

    def restore(self,transaction,approved=False):
        require_user()
        if not re.fullmatch(r'[0-9a-f]{32}',transaction): raise Error('Identificador de operación inválido')
        tx=self.state/'transactions'/transaction; journal=read_json(tx/'journal.json')
        if not journal: raise Error('Respaldo inexistente')
        if journal['status']=='restored': return journal
        if not approved: raise Error('La restauración requiere confirmación explícita')
        with lock(self.state):
            current=self.installed(); plan=journal['plan']
            if current!=plan['installed_before'] and current.get('transaction')!=transaction: raise Error('Hay una instalación posterior; no se restaura un respaldo antiguo encima')
            journal['status']='recovering'; save_json(tx/'journal.json',journal)
            for entry in reversed(journal['files']):
                actual=self.storage(entry['scope']).state(entry['target'])
                if actual==entry['before']: continue
                if actual!=entry['after']: raise Error('Cambios personales posteriores: no se restaura automáticamente '+entry['target'])
                backup=(tx/entry['backup']).read_bytes() if entry.get('backup') else None
                if backup is not None and digest(backup)!=entry['before']['sha256']: raise Error('Respaldo alterado')
                self.mutate(entry,backup,entry['before']['mode'] if entry['before'] else 0o644,actual)
                entry['phase']='restored'; save_json(tx/'journal.json',journal)
            if plan.get('hypr_validation'):
                self.runner.run(['hyprctl','reload'])
                errors=self.runner.run(['hyprctl','configerrors']).stdout.strip()
                if errors: raise Error('Archivos restaurados, pero Hyprland informa errores: '+clean(errors))
            save_json(self.state/'installed.json',plan['installed_before'])
            journal['status']='restored'; journal['recovery_note']='Archivos restaurados. Paquetes, servicios y efectos de compilación no se revierten automáticamente.'
            save_json(tx/'journal.json',journal); return journal

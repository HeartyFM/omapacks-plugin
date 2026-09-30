"""Explicit providers; all mutation is separated from read-only planning."""
from __future__ import annotations
import configparser, os, re, shutil, tempfile
from pathlib import Path
from .util import Error, Runner, atomic, clean, digest, secure_path, save_json
from .artifact import unpack
from .github import Transport
from .diagnostics import Blocked,issue

class Providers:
    def __init__(self, runner=None, transport=None, package_lock='/var/lib/pacman/db.lck'):
        self.runner = runner or Runner(); self.transport = transport or Transport(); self.package_lock = Path(package_lock)

    def installed(self, name):
        r = self.runner.run(['pacman','-Q','--',name], check=False)
        if r.returncode==0:
            parts=r.stdout.strip().split()
            if len(parts)==2 and parts[0]==name: return parts[1]
        elif r.returncode==1 and re.fullmatch(r"error: package '"+re.escape(name)+r"' was not found\s*",r.stderr):
            return None
        raise Error('No se pudo consultar el paquete instalado '+name+' (pacman -Q). No equivale a paquete ausente.', 'query')

    def repository_info(self,name):
        r=self.runner.run(['pacman','-Si','--',name],check=False)
        if r.returncode:
            if r.returncode==1 and re.fullmatch(r"error: package '"+re.escape(name)+r"' was not found\s*",r.stderr):
                raise Error('Paquete no disponible en repositorios habilitados: '+name+
                            '; no se sustituye por AUR. Revisa el nombre y las bases/repositorios habilitados; no se habilitan automáticamente.', 'package_missing')
            raise Error('Falló la consulta de repositorios para '+name+' (pacman -Si); disponibilidad desconocida. Revisa pacman y sus bases locales.', 'query')
        actual=re.search(r'^Name\s*:\s*(\S+)',r.stdout,re.M)
        candidate=re.search(r'^Version\s*:\s*(\S+)',r.stdout,re.M)
        if not actual or not candidate: raise Error('Respuesta incompleta de pacman -Si para '+name,'query')
        if actual.group(1)!=name:
            raise Error('La receta pide '+name+' pero pacman informa '+actual.group(1)+'. Declara el proveedor concreto tras revisar Provides y restricciones de versión.', 'provider_mismatch')
        return candidate.group(1)

    def compare(self, a, b):
        return int(self.runner.run(['vercmp',a,b]).stdout.strip())

    def observe(self,actions):
        """Read actual state after a partial transaction; never retry its commands."""
        observed=[]
        for a in actions:
            if a['provider']=='preparation': continue
            row={'provider':a['provider'],'name':a.get('name',a.get('id')),
                 'before':a.get('before'),'planned':a.get('version'),'actual':None,'state':'unknown'}
            try:
                if a['provider'] in ('arch','aur','arch-remove') or a['provider']=='external' and a['format']=='arch':
                    row['actual']=self.installed(a['name'])
                elif a['provider']=='flatpak':
                    r=self.runner.run(['flatpak','info','--'+a['scope'],'--show-commit',a['name']],check=False)
                    if r.returncode: raise Error('No se pudo determinar el commit Flatpak instalado','query')
                    row['actual']=r.stdout.strip()
                else:
                    observed.append(row); continue
                expected=None if a['provider']=='arch-remove' else row['planned']
                row['state']='planned' if row['actual']==expected else 'before' if row['actual']==row['before'] else 'different'
            except Error as e: row['diagnostic']=issue(e,row['name'],'recuperación')
            observed.append(row)
        return observed

    def plan(self, manifest, staging):
        # Collect independent Arch blockers before staging AUR/downloads or mutating.
        issues=[]; needed=False
        for p in manifest.get('packages',[]):
            if p['provider']!='arch': continue
            try:
                current=self.installed(p['name'])
                if current and self.compare(current,p['version'])>=0: continue
                needed=True
                candidate=self.repository_info(p['name'])
                if self.compare(candidate,p['version'])<0:
                    raise Error('La base local no satisface '+p['name']+'; revisa una actualización completa con Omarchy','system_update')
            except Error as e: issues.append(issue(e,p['name']))
        if needed:
            if self.package_lock.exists(): issues.append(issue(Error('Pacman está bloqueado por otra operación. No se elimina db.lck.','locked'),'pacman'))
            try:
                updates=self.runner.run(['pacman','-Qu'],check=False)
                if updates.returncode not in (0,1) or updates.stderr.strip(): raise Error('No se pudo consultar actualizaciones de Arch','query')
                if updates.stdout.strip(): raise Error('Hay actualizaciones pendientes de Arch. Ejecuta la ruta normal «omarchy update» con aprobación y vuelve a calcular el plan.','system_update')
            except Error as e: issues.append(issue(e,'pacman -Qu'))
        if issues: raise Blocked(issues)
        return self._plan(manifest,staging)

    def _plan(self, manifest, staging):
        actions = []; packages = sorted(manifest.get('packages', []),key=lambda p: p['provider']=='flatpak')
        deferred=[]; remotes={}
        arch = []; existing = {}
        for p in packages:
            provider = p['provider']; name = p['name']
            if provider == 'flatpak':
                scope = '--' + p['scope']
                try: remote = self.runner.run(['flatpak','remotes',scope,'--columns=name'], check=False)
                except Error: remote = None
                if remote is None or remote.returncode:
                    if not any(dep['provider']=='arch' and dep['name']=='flatpak' for dep in packages): raise Error('Flatpak no está disponible; declara su infraestructura Arch', 'provider')
                    deferred.append(name); continue
                if p['remote'] not in remote.stdout.splitlines():
                    declaration=next((r for r in manifest.get('flatpak_remotes',[]) if r['name']==p['remote'] and r['scope']==p['scope']),None)
                    if not declaration: raise Error('Remote Flatpak ausente: '+p['remote']+'. Declara URL, hash y ámbito para añadirlo explícitamente.', 'provider')
                    remote_key=(p['scope'],p['remote'])
                    if remote_key not in remotes: remotes[remote_key]=self.prepare_remote(declaration,staging)
                    deferred.append(name); continue
                r = self.runner.run(['flatpak','info',scope,'--show-commit',name], check=False)
                current = r.stdout.strip() if r.returncode == 0 else None
                origin = self.runner.run(['flatpak','info',scope,'--show-origin',name], check=False)
                if current and origin.stdout.strip() != p['remote']: raise Error('Flatpak instalado desde otro remote')
                # Pin available commit; never silently resolve latest after approval.
                remote_info = self.runner.run(['flatpak','remote-info',scope,'--show-commit',p['remote'],name])
                if remote_info.stdout.strip() != p['version']: raise Error('El commit Flatpak declarado no es el publicado por el remote; no se cambia silenciosamente')
                permissions = self.runner.run(['flatpak','remote-info',scope,'--show-metadata',p['remote'],name]).stdout
                actions.append({'provider':'flatpak','name':name,'scope':p['scope'],'remote':p['remote'],'version':p['version'],'before':current,'action':'keep' if current == p['version'] else 'install' if not current else 'update','permissions':clean(permissions),'declared_permissions':p['permissions']})
                continue
            current = self.installed(name); existing[name] = current
            if current and self.compare(current,p['version']) >= 0:
                actions.append({'provider':provider,'name':name,'version':current,'before':current,'action':'keep'})
                continue
            if provider == 'arch':
                candidate = self.repository_info(name)
                if self.compare(candidate,p['version']) < 0: raise Error('La base local no satisface '+name+'; revisa una actualización completa con Omarchy', 'system_update')
                arch.append(name+'='+candidate)
            elif provider == 'aur':
                stage = Path(staging)/('aur-'+name)
                if not stage.exists():
                    self.runner.run(['git','-c','core.hooksPath=/dev/null','clone','--no-checkout','--','https://aur.archlinux.org/'+name+'.git',str(stage)],timeout=180)
                    self.runner.run(['git','-c','core.hooksPath=/dev/null','checkout','--detach',p['commit']],cwd=stage)
                actual = self.runner.run(['git','rev-parse','HEAD'],cwd=stage).stdout.strip()
                if actual != p['commit']: raise Error('Revisión AUR distinta de la declarada')
                tracked = self.runner.run(['git','ls-files','-z'],cwd=stage).stdout.split('\0')
                resources = {}
                review = []
                for rel in filter(None, tracked):
                    path = secure_path(stage,rel)
                    if not path.is_file() or path.stat().st_size > 2*1024*1024: raise Error('Recurso AUR no revisable')
                    b = path.read_bytes(); resources[rel] = digest(b)
                    review.append('--- '+rel+' ---\n'+clean(b.decode('utf-8',errors='replace')))
                if 'PKGBUILD' not in resources: raise Error('AUR sin PKGBUILD')
                # AUR can request replacement of another installed app. Require a
                # separate review instead of allowing pacman -U to expand this plan.
                conflicts=[]
                if '.SRCINFO' in resources:
                    for value in re.findall(r'^\s*conflicts(?:_\w+)?\s*=\s*(\S+)\s*$',(stage/'.SRCINFO').read_text(),re.M):
                        conflict=re.split(r'[<>=]',value)[0]
                        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9@._+:-]*',conflict): raise Error('Conflicto AUR inválido')
                        if conflict!=name: conflicts.append(conflict)
                    for conflict in conflicts:
                        if self.installed(conflict): raise Error('AUR '+name+' sustituiría '+conflict+'. Revisa primero esa retirada; no pertenece al plan autorizado.','conflict')
                actions.append({'provider':'aur','name':name,'version':p['version'],'before':current,'action':'build','commit':actual,'stage':str(stage),'resources':resources,'review':'\n\n'.join(review),'review_note':p['review'],'build_dependencies':p.get('build_dependencies',[]),'reproducibility':'La revisión fija no fija fuentes VCS/remotas variables del PKGBUILD.'})
                actions[-1]['conflicts']=conflicts
        if arch:
            if self.package_lock.exists(): raise Error('Pacman está bloqueado por otra operación. No se elimina db.lck.', 'locked')
            updates = self.runner.run(['pacman','-Qu'],check=False)
            if updates.returncode not in (0,1): raise Error('No se pudo consultar actualizaciones de Arch')
            if updates.stdout.strip():
                raise Error('Hay actualizaciones pendientes de Arch. Ejecuta la ruta normal «omarchy update» con aprobación y vuelve a calcular el plan.\n'+clean(updates.stdout), 'system_update')
            resolution=self.runner.run(['pacman','-Sp','--needed','--print-format','%n\t%v','--',*arch],check=False)
            if resolution.returncode:
                raise Error('Dependencias no resolubles para '+', '.join(arch)+'. La consulta transitiva de pacman falló; revisa la receta y el estado de las bases. No se instaló ningún paquete.','resolution')
            solved = resolution.stdout
            for row in solved.splitlines():
                if '\t' not in row: continue
                name,v = row.split('\t',1)
                if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9@._+:-]*',name): raise Error('Resolución de pacman inválida')
                from .manifest import FORBIDDEN_PACKAGES
                if FORBIDDEN_PACKAGES.search(name): raise Error('La transacción incluye una dependencia de sistema excluida: '+name)
                actions.append({'provider':'arch','name':name,'version':v,'before':self.installed(name),'action':'install','requested':any(x.split('=')[0] == name for x in arch)})
            if not any(a['provider']=='arch' and a['action']=='install' for a in actions): raise Error('Pacman no resolvió la transacción')
            missing={spec.split('=')[0] for spec in arch}-{a['name'] for a in actions if a['provider']=='arch'}
            if missing: raise Error('La resolución de pacman omitió paquetes solicitados: '+', '.join(sorted(missing)),'resolution')
        actions.extend(remotes.values())
        if deferred: actions.append({'provider':'preparation','name':', '.join(deferred),'version':'pendiente de resolver','action':'replan','reason':'Después de instalar infraestructura/remotes se mostrará otro plan con aplicaciones, runtimes y permisos resueltos.'})
        for a in actions:
            if a['provider'] == 'aur' and a['action'] == 'build':
                declared = {p['name'] for p in packages}
                if not set(a['build_dependencies']) <= declared: raise Error('Declara las herramientas/dependencias AUR como paquetes explícitos')
        for d in manifest.get('downloads', []):
            target = Path(staging)/('download-'+d['id'])
            if not target.exists():
                data,_ = self.transport.get(d['url'],binary=True,limit=d['size'])
                if len(data) != d['size'] or digest(data) != d['sha256']: raise Error('Entrega externa: integridad inválida', 'integrity')
                atomic(target,data)
            if digest(target.read_bytes()) != d['sha256']: raise Error('Entrega externa modificada', 'integrity')
            if d['format']=='appimage':
                head=target.read_bytes()[:12]
                if not head.startswith(b'\x7fELF') or head[8:11] not in (b'AI\x01',b'AI\x02'): raise Error('El archivo no es un AppImage reconocido')
            a = {**d,'provider':'external','stage':str(target),'action':'install'}
            if d['format']=='arch':
                info = self.runner.run(['pacman','-Qp','--',str(target)]).stdout.strip().split()
                if len(info) != 2: raise Error('Paquete Arch externo inválido')
                a['name'],actual_version = info
                from .manifest import FORBIDDEN_PACKAGES
                if FORBIDDEN_PACKAGES.search(a['name']): raise Error('Paquete Arch externo excluido')
                if actual_version != d['version']: raise Error('Versión Arch externa distinta')
                a['before'] = self.installed(a['name'])
                if a['before'] and self.compare(a['before'],actual_version) > 0: raise Error('No se bajan automáticamente paquetes Arch')
                a['transaction'] = self.runner.run(['pacman','-Up','--print-format','%n\t%v','--',str(target)]).stdout
                a['resolved']=[]
                for line in a['transaction'].splitlines():
                    if '\t' not in line: continue
                    dep,ver=line.split('\t',1)
                    if FORBIDDEN_PACKAGES.search(dep): raise Error('Transacción externa contiene paquete excluido: '+dep)
                    before=self.installed(dep)
                    if before and self.compare(before,ver)>0: raise Error('La transacción externa bajaría un paquete existente')
                    a['resolved'].append({'name':dep,'version':ver,'before':before})
                if not a['resolved']: raise Error('No se pudo resolver el paquete externo')
            actions.append(a)
        if not deferred: actions.extend(self.plan_removals(manifest.get('package_removals',[]),actions))
        return actions

    def plan_removals(self,removals,actions):
        selected=[]
        for entry in removals:
            current=self.installed(entry['name'])
            if current: selected.append({'provider':'arch-remove','name':entry['name'],'before':current,'version':'ausente','action':'remove','reason':entry['reason']})
        if not selected: return []
        if self.package_lock.exists(): raise Error('Pacman bloqueado; no se preparan retiradas','locked')
        names={a['name'] for a in selected}
        if names & {a.get('name') for a in actions if a['provider'] in ('arch','aur')}: raise Error('Un paquete solicitado también está en la retirada')
        query=self.runner.run(['pacman','-Rp','--print-format','%n\t%v','--',*sorted(names)],check=False)
        if query.returncode: raise Error('No se pueden retirar los programas sin romper dependencias: '+clean(query.stderr),'removal')
        rows={line.split('\t',1)[0]:line.split('\t',1)[1] for line in query.stdout.splitlines() if '\t' in line}
        if rows!={a['name']:a['before'] for a in selected}: raise Error('La retirada incluye paquetes adicionales o versiones distintas; se detiene','removal')
        return selected

    def execute(self, actions, callback):
        arch = [a for a in actions if a['provider']=='arch' and a['action']!='keep']
        if arch:
            if self.package_lock.exists(): raise Error('Pacman sigue bloqueado', 'locked')
            argv = ['sudo','pacman','-S','--needed','--',*[a['name']+'='+a['version'] for a in arch]]
            self.runner.run(argv,interactive=True,timeout=None)
            for a in arch:
                if self.installed(a['name']) != a['version']: raise Error('Verificación de paquete falló: '+a['name'], 'provider')
                callback(a)
        for a in actions:
            if a['action']=='keep' or a['provider'] in ('arch','external','preparation','arch-remove'): continue
            if a['provider']=='aur':
                for name,sha in a['resources'].items():
                    if digest(secure_path(a['stage'],name).read_bytes()) != sha: raise Error('Código AUR cambió tras revisión', 'changed')
                for dep in a['build_dependencies']:
                    if not self.installed(dep): raise Error('Falta dependencia de compilación: '+dep)
                # No -s: PKGBUILD must not trigger implicit privileged dependency installs.
                # makepkg is intentionally unsandboxed, reviewed third-party code, normal UID.
                build_env={k:v for k,v in os.environ.items() if k not in ('OMAPACKS_GITHUB_TOKEN','GITHUB_TOKEN','GH_TOKEN','SSH_AUTH_SOCK')}
                self.runner.run(['makepkg','--cleanbuild','--force'],cwd=a['stage'],env=build_env,interactive=True,timeout=None)
                outputs = self.runner.run(['makepkg','--packagelist'],cwd=a['stage']).stdout.splitlines()
                if not outputs: raise Error('La compilación no produjo paquetes')
                selected = []
                for path in outputs:
                    p = Path(path)
                    if p.parent.resolve() != Path(a['stage']).resolve() or p.is_symlink(): raise Error('Salida AUR fuera del staging')
                    info = self.runner.run(['pacman','-Qp','--',str(p)]).stdout.split()
                    if len(info)==2 and info[0]==a['name']:
                        if self.compare(info[1],a['version']) < 0: raise Error('Versión AUR construida insuficiente')
                        selected.append(str(p))
                if len(selected)!=1: raise Error('Revisar paquetes divididos AUR: salida ambigua o ausente')
                for conflict in a.get('conflicts',[]):
                    if self.installed(conflict): raise Error('Apareció un conflicto AUR después del plan: '+conflict,'changed')
                self.runner.run(['sudo','pacman','-U','--',*selected],interactive=True,timeout=None)
                actual=self.installed(a['name'])
                if not actual or self.compare(actual,a['version'])<0: raise Error('AUR no quedó instalado con la versión requerida')
                callback({**a,'installed_version':actual,'built_packages':{Path(p).name:digest(Path(p).read_bytes()) for p in selected}})
                continue
            elif a['provider']=='flatpak-remote':
                if digest(Path(a['stage']).read_bytes())!=a['sha256']: raise Error('El remote cambió después de revisión')
                self.runner.run(['flatpak','remote-add','--'+a['scope'],'--from',a['name'],a['stage']],interactive=True,timeout=None)
            elif a['provider']=='flatpak':
                # Native transaction confirmation remains visible, including runtime/permissions.
                base = ['flatpak','install' if a['action']=='install' else 'update','--'+a['scope']]
                if a['action']=='install':
                    observed=self.runner.run(['flatpak','remote-info','--'+a['scope'],'--show-commit',a['remote'],a['name']]).stdout.strip()
                    if observed!=a['version']: raise Error('El commit Flatpak cambió antes de instalar', 'changed')
                    argv = base+['--no-deploy',a['remote'],a['name']]
                else: argv = base+['--commit='+a['version'],a['name']]
                self.runner.run(argv,interactive=True,timeout=None)
                if a['action']=='install':
                    ref=self.runner.run(['flatpak','remote-info','--'+a['scope'],'--show-ref',a['remote'],a['name']]).stdout.strip()
                    repo=(Path.home()/'.local/share/flatpak/repo') if a['scope']=='user' else Path('/var/lib/flatpak/repo')
                    pulled=self.runner.run(['ostree','--repo='+str(repo),'rev-parse',a['remote']+':'+ref]).stdout.strip()
                    if pulled!=a['version']: raise Error('La descarga Flatpak cambió; no se despliega', 'changed')
                    self.runner.run(['flatpak','install','--'+a['scope'],'--no-pull',a['remote'],a['name']],interactive=True,timeout=None)
                if self.runner.run(['flatpak','info','--'+a['scope'],'--show-commit',a['name']]).stdout.strip()!=a['version']:
                    raise Error('Flatpak cambió durante la operación; estado parcial', 'changed')
            callback(a)
        removals=[a for a in actions if a['provider']=='arch-remove']
        if removals:
            if self.package_lock.exists(): raise Error('Pacman bloqueado antes de retirar','locked')
            declared=[{'name':a['name'],'reason':a['reason']} for a in removals]
            if self.plan_removals(declared,[])!=removals: raise Error('La retirada cambió; se requiere otro plan','changed')
            self.runner.run(['sudo','pacman','-R','--',*sorted(a['name'] for a in removals)],interactive=True,timeout=None)
            for a in removals:
                if self.installed(a['name']) is not None: raise Error('El paquete no se retiró: '+a['name'],'provider')
                callback(a)

    def install_external_arch(self, a):
        if self.package_lock.exists(): raise Error('Pacman bloqueado', 'locked')
        if digest(Path(a['stage']).read_bytes()) != a['sha256']: raise Error('Paquete externo modificado')
        current = self.runner.run(['pacman','-Up','--print-format','%n\t%v','--',a['stage']]).stdout
        if current != a['transaction']: raise Error('Transacción externa cambió; recalcula el plan', 'changed')
        self.runner.run(['sudo','pacman','-U','--',a['stage']],interactive=True,timeout=None)
        for dependency in a['resolved']:
            if self.installed(dependency['name'])!=dependency['version']: raise Error('Dependencia externa no verificada: '+dependency['name'])

    def prepare_remote(self,remote,staging):
        target=Path(staging)/('remote-'+remote['scope']+'-'+remote['name']+'.flatpakrepo')
        if not target.exists():
            data,_=self.transport.get(remote['url'],binary=True,limit=remote['size'])
            if len(data)!=remote['size'] or digest(data)!=remote['sha256']: raise Error('Remote: integridad inválida')
            atomic(target,data)
        data=target.read_bytes()
        if digest(data)!=remote['sha256']: raise Error('Remote alterado')
        parser=configparser.ConfigParser(interpolation=None)
        try:
            parser.read_string(data.decode()); section=parser['Flatpak Repo']
            from urllib.parse import urlsplit
            url=urlsplit(section['Url'])
            if url.scheme!='https' or url.username or url.password or not section.get('GPGKey'): raise Error('El remote requiere HTTPS y clave GPG explícita')
        except (ValueError,KeyError,configparser.Error): raise Error('Archivo .flatpakrepo inválido')
        return {**remote,'provider':'flatpak-remote','stage':str(target),'action':'add','version':remote['sha256'],'definition':clean(data.decode())}

    def build_source(self,a,manifest):
        work=Path(a['stage']).parent/('build-'+a['id'])
        if digest(Path(a['stage']).read_bytes())!=a['sha256']: raise Error('Fuente propia modificada')
        for name,sha in a['resources'].items():
            if digest(secure_path(work,name).read_bytes())!=sha: raise Error('Fuente cambió desde revisión')
        builder=a['build']; declared={p['name'] for p in manifest.get('packages',[]) if p['provider']=='arch'}
        if builder not in declared or not self.installed(builder): raise Error('Constructor no declarado/instalado: '+builder)
        env={k:v for k,v in os.environ.items() if k not in ('OMAPACKS_GITHUB_TOKEN','GITHUB_TOKEN','GH_TOKEN','SSH_AUTH_SOCK')}
        argv=['make'] if builder=='make' else ['cargo','build','--locked','--release','--offline']
        self.runner.run(argv,cwd=work,env=env,interactive=True,timeout=None)
        output=secure_path(work,a['check'])
        if not output.is_file(): raise Error('No se produjo la salida declarada')
        data=output.read_bytes(); target=work.parent/('built-'+a['id']); name=Path(a['check']).name
        atomic(target/'output'/name,data,0o755)
        save_json(target/'build.json',{'source_sha256':a['sha256'],'revision':a['revision'],'outputs':{name:digest(data)}})

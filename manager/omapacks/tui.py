"""Native gum TUI. Remote text is always data, never terminal escapes or shell."""
from __future__ import annotations
import json,shutil,sys
from pathlib import Path
from . import __version__
from .artifact import verify
from .engine import Engine
from .github import GitHub,pin,published,sort_releases
from .util import Error,clean,digest,canonical,read_json,save_json
from .diagnostics import safe,operation_summary
from . import report,capture_shortcut,manager_update
from .artifact import ManagerRequired

from .presentation import header,choose,pager,confirm,message,clip,cells,size,exit_prompt

def manager_details(config):
    installed=read_json(config.home/'.local/share/omapacks-manager/omapacks-manager.json',{})
    bundle=read_json(config.home/'.config/omarchy/plugins/heartyfm.omapacks/manager/bundle.json',{})
    return ('Gestor en uso: '+__version__+'\nGestor instalado: '+installed.get('version','sin registro en este hogar')+
            '\nGestor incluido en el plugin local: '+bundle.get('manager_version','no disponible')+
            '\n\nActualizar el plugin: Setup → Plugin → Update en Omarchy.\n'
            'Después, el bootstrap del plugin ofrece actualizar el gestor con confirmación. '
            'Si se cerró la oferta, abre Instalar.sh en el plugin.\n\n'
            'Instalar contenido: elige aquí una release completa, revisa sus novedades y aprueba su plan.\n'
            'Si un pack requiere un gestor nuevo, su reporte permite actualizarlo desde una release firmada del origen configurado. Se pide autorización y después se calcula un plan nuevo para el contenido.\n'
            'Esto no actualiza el checkout del plugin. La lista no comprueba si el plugin remoto ha cambiado.\n'
            'La actualización del sistema sigue siendo «omarchy update».')

def plan_summary(plan):
    counts={action:sum(c['action']==action for c in plan['files']) for action in ('create','modify','remove','keep','skip')}
    packages=sum(a['action']!='keep' for a in plan['packages'])
    prefs=[c for c in plan['files'] if c.get('owned_values')]
    return ('PLAN DE INSTALACIÓN\n\n'+plan['installed_before'].get('version','Sin instalar')+' → '+plan['manifest']['version']+
            '\nRelease completa: '+plan['identity']['tag']+
            f'\nPaquetes: {packages} acciones; {len(plan["packages"])-packages} conservados.'+
            f'\nArchivos: {counts["create"]} nuevos, {counts["modify"]} modificados, {counts["remove"]} retirados.'+
            f'\nPreferencias: {len(prefs)} recursos administrados por claves.'+
            '\nPermisos: '+('administrador para operaciones concretas; revisar Detalles.' if needs_admin(plan) else 'usuario normal.')+
            ('\n\nPARCIAL: conservar/omitir conflictos impide marcar esta release completa.' if any(c.get('decision') in ('keep','skip') for c in plan['files']) else '')+
            ('\n\nPreparación: habrá que revisar otro plan antes de aplicar el contenido.' if plan.get('builds') or any(a['provider']=='preparation' for a in plan['packages']) else '')+
            '\n\nRespaldos antes de los cambios. Restaurar archivos no revierte paquetes ni servicios.\n'
            'Una release anterior necesita un plan nuevo. Detalles muestra recursos, preferencias y permisos exactos.')

def needs_admin(plan):
    return (any(c['scope']=='system' and c['action'] not in ('keep','skip') for c in plan['files']) or
            any(p['action']!='keep' and (p['provider'] in ('arch','aur') or p['provider']=='external' and p['format']=='arch' or p['provider'] in ('flatpak','flatpak-remote') and p['scope']=='system') for p in plan['packages']) or
            any(op['scope']=='system' and not op.get('skip') for op in plan['operations']))

def describe(plan):
    m=plan['manifest']; old=plan['installed_before']; identity=plan['identity']
    lines=['DETALLES DE LA INSTALACIÓN','',f"{old.get('version','sin instalar')} → {m['version']}",f"Origen: {identity['repository']} · release #{identity['release_id']} · {identity['tag']}",
           '', 'Módulos:']
    previous={x['id']:x['version'] for x in old.get('modules',[])}
    for mod in m['modules']: lines.append(f"  {mod['id']}: {previous.pop(mod['id'],'nuevo')} → {mod['version']}")
    for mod,v in previous.items(): lines.append(f'  {mod}: {v} → retirado')
    lines+=['','Paquetes y aplicaciones:']
    actions={'keep':'conservar','install':'instalar','update':'actualizar','build':'compilar','add':'añadir','replan':'recalcular'}
    for p in plan['packages']:
        lines.append(f"  {p['provider']} · {p.get('name',p.get('id'))} · {actions.get(p['action'],p['action'])} · {p.get('before') or 'ausente'} → {p['version']}")
        for dep in p.get('resolved',[]): lines.append(f"    {dep['name']}: {dep['before'] or 'nuevo'} → {dep['version']}")
        if p.get('permissions'): lines.append('  Permisos Flatpak:\n'+p['permissions'])
        if p.get('reproducibility'): lines.append('  '+p['reproducibility'])
        if p.get('definition'): lines.append('  Nuevo remote (clave GPG incluida):\n'+p['definition'])
        if p.get('reason'): lines.append('  '+p['reason'])
    if not plan['packages']: lines.append('  Ninguno')
    if plan.get('recipes'): lines+=['','Recetas y solucionadores:']
    for recipe in plan.get('recipes',[]): lines.append(f"  {recipe['id']} · {recipe['action']} · {recipe['purpose']} · {recipe['prefix']}")
    lines+=['','Archivos:']
    translations={'create':'crear','modify':'modificar','remove':'retirar','keep':'conservar','skip':'omitir'}
    for c in plan['files']: lines.append(f"  {translations[c['action']]} · {c['scope']} · {c['target']}"+(' · CONFLICTO LOCAL' if c['conflict'] else ''))
    for c in plan['files']:
        if c.get('owned_values') and c.get('kind')=='xdg_defaults':
            lines+=['','Aplicaciones predeterminadas · '+c['target']+':']
            for key,value in c['owned_values'].items(): lines.append('  '+key+': '+str(c.get('owned_before',{}).get(key) or 'sin preferencia explícita')+' → '+value)
        elif c.get('kind')=='omarchy_shell' and 'bar' in c.get('owned_values',{}):
            bar=c['owned_values']['bar']
            positions={'top':'arriba','bottom':'abajo','left':'izquierda','right':'derecha'}
            lines+=['','Menú y barra compartidos:', '  Barra de Diego · posición: '+positions[bar['position']],
                    '  Activar menú compartido y conservar otros plugins y ajustes de bloqueo.']
        elif c.get('kind')=='omarchy_style':
            lines+=['','Apariencia del menú y la barra:', '  Aplicar sus colores, bordes y transparencia; conservar otras secciones.']
        if c.get('menu_entries'):
            lines+=['','Entradas de menú compartidas:']
            for key,value in c['menu_entries'].items(): lines.append('  '+value['label']+' · '+(value.get('action') or 'submenú'))
        for owned,value in c.get('owned_values',{}).items():
            if owned.startswith('plugins:'): lines+=['','Plugin activado como servicio: '+owned.split(':',1)[1], '  Conserva la barra y los otros plugins; acceso desde el lanzador de aplicaciones.']
    if m.get('capture_shortcut'):
        lines+=['','Captura completa: Super+Shift+S → archivo de imagen, sin selector de región.',
                'Atajo previo detectado: '+(', '.join(str(b[-1]) for b in plan.get('capture_bindings') or []) or 'ninguno'),
                'Se sustituye solo este atajo. Retirar la preferencia vuelve a cargar la configuración ajena preservada.']
    lines+=['','Permisos y servicios:']
    for op in plan['operations']: lines.append(f"  {op['scope']} · {op['action']} {op['name']} · {op['purpose']}")
    privileged=needs_admin(plan)
    lines.append('  Requiere elevación para operaciones concretas' if privileged else '  No requiere administrador')
    if plan.get('reloads'): lines+=['','Activación al terminar:']+['  '+r['component']+' · '+r['method']+' · '+r['verification'] for r in plan['reloads']]
    if plan['migrations']: lines+=['','Migraciones:']+[m['id']+': '+m['description'] for m in plan['migrations']]
    lines+=['','Reinicio: '+('necesario' if plan['recovery']['reboot'] else 'no declarado'),
            'Recuperación: respaldos de los archivos que cambia este plan.',
            'Los paquetes, compilaciones, servicios y efectos externos no se revierten automáticamente.',
            plan['recovery']['limitations'],'', 'Comprobaciones:']
    for check in m.get('checks',[]):
        detail={'file':'Integridad de '+check.get('target',''), 'version':'Versión de '+check.get('name',''), 'hyprland':'Configuración y accesos esenciales de Hyprland', 'wine-prefix':'Estructura del prefijo Wine '+check.get('prefix','')}.get(check['kind'],check['kind'])
        lines.append('  '+detail+(' · obligatoria' if check['required'] else ' · opcional'))
    for build in plan.get('builds',[]):
        lines+=['','COMPILACIÓN PROPIA · '+build['id'],build['purpose'],'Revisión: '+build['revision'],'Constructor: '+build['build'],'Código sin aislamiento; se compila como usuario. Después se revisará otro plan con los archivos resultantes.',build['review']]
    if any(p.get('format')=='omarchy-plugin' for p in plan['packages']):
        lines+=['','La vista de código puede abreviarse. Fuentes completas verificadas del plugin:']
        lines += [str(Path(plan['stage'])/('plugin-source-'+p['id'])) for p in plan['packages'] if p.get('format')=='omarchy-plugin']
    for review in plan['code_reviews']: lines+=['',review['notice'],review['source'],review['content']]
    for p in plan['packages']:
        if p['provider']=='aur' and p['action']=='build': lines+=['','REVISIÓN AUR · '+p['commit'],p['review_note'],'Código sin aislamiento, construido como usuario. La firma del pack no garantiza código de terceros.',p['review']]
    lines+=['','Identidad verificada de la operación:', 'Plan: '+plan['id'], 'Artefacto: '+plan['meta']['archive_sha256']]
    return clean('\n'.join(lines))

def release_labels(rows,installed,repository,mode):
    width=min(24,max(10,size().columns//4),max(cells(clean(r['tag_name'],False)) for r in rows))
    labels=[]
    for index,r in enumerate(rows):
        tags=[]
        if r.get('prerelease'): tags.append('Prueba')
        if index==0 and published(r.get('published_at'))!=float('-inf'): tags.append('Más reciente')
        if not r.get('prerelease') and mode=='update' and installed.get('identity') and published(r.get('published_at'))>published(installed['identity'].get('published_at')): tags.append('Nueva publicación')
        if installed.get('identity',{}).get('release_id')==r['id'] and installed.get('identity',{}).get('repository')==repository: tags.insert(0,'Instalada')
        if published(r.get('published_at'))==float('-inf'): tags.append('Sin fecha')
        else: tags.append(str(r['published_at'])[:10])
        try: pin(repository,r)
        except Error: tags.insert(1 if published(r.get('published_at'))!=float('-inf') else 0,'No instalable')
        tag=clip(r['tag_name'],width)
        labels.append(tag+' '*(width-cells(tag)+2)+' · '.join(tags))
    return labels


class Progress:
    """Paint only phase events emitted by the engine, without elapsed estimates."""
    def __init__(self,version): self.version=version; self.previous=None; self.done=[]
    def __call__(self,phase):
        if self.previous: self.done.append(self.previous)
        self.previous=phase
        header(); message('Instalando '+self.version,'strong')
        for completed in self.done: message('✓ '+completed,'muted')
        message('Ahora: '+phase,'accent')
        message(''); message('Las preguntas de permisos aparecerán aquí cuando sean necesarias.','muted')
        message('Ctrl+C interrumpe; puede requerir recuperación.','muted')


def report_text(row,plan,notice=''):
    lines=[report.render(plan),'']
    if notice: lines+=[notice,'']
    lines+=['En este equipo: '+plan['installed_before'].get('version','sin instalar')+' → '+plan['manifest']['version']]
    counts={action:sum(c['action']==action for c in plan['files']) for action in ('create','modify','remove')}
    lines+=[f"{counts['create']} archivos nuevos · {counts['modify']} modificados · {counts['remove']} retirados."]
    lines+=['Permisos: '+('administrador en operaciones concretas; consulta Detalles.' if needs_admin(plan) else 'usuario normal.')]
    if plan['manifest'].get('capture_shortcut'):
        lines+=['Super+Shift+S ahora: '+(', '.join(str(b[-1]) for b in plan.get('capture_bindings') or []) or 'sin asignar')+'.']
    if any(c.get('decision') in ('keep','skip') for c in plan['files']): lines+=['PARCIAL: conservar estos recursos impide completar la release.']
    if plan.get('builds') or any(p['provider']=='preparation' for p in plan['packages']): lines+=['La preparación requerirá revisar y aprobar otro plan.']
    conflicts=[c for c in plan['files'] if c['conflict'] and c.get('decision') not in ('keep','skip')]
    if conflicts: lines+=['',('Hay un conflicto personal.' if len(conflicts)==1 else f'Hay {len(conflicts)} conflictos personales.')+' Instalar permite resolverlos; después revisarás el nuevo reporte.']
    deps=[p.get('name',p.get('id','dependencia')) for p in plan['packages'] if p['action']!='keep']
    lines+=['Dependencias: '+(', '.join(deps[:6])+(' y '+str(len(deps)-6)+' más en Detalles.' if len(deps)>6 else '') if deps else 'ninguna por instalar.')]
    if plan['operations']: lines+=['Servicios: '+', '.join(op['name'] for op in plan['operations'])+'.']
    if any(p.get('format')=='omarchy-plugin' for p in plan['packages']): lines+=['El plugin ejecutará código externo con tus permisos. Se pide revisarlo antes de instalar.']
    activation={'omarchy-shell':'actualizar paneles y plugins','hyprland':'recargar Hyprland','omarchy-menu':'actualizar el menú','defaults':'aplicar preferencias de aplicaciones'}
    if plan.get('reloads'): lines+=['Al terminar: '+', '.join(activation[r['component']] for r in plan['reloads'])+'.']
    if plan['recovery']['reboot']: lines+=['Requiere reiniciar después.']
    lines+=['','Instalar aprueba este plan. Habrá respaldo de los archivos modificados.',
            'Restaurar archivos no revierte paquetes ni servicios. Novedades y recursos exactos en Detalles.']
    return clean('\n'.join(lines))


def recover(engine):
    """Keep recovery inside the selected release; never replay a partial apply."""
    while engine.pending():
        path=engine.pending()[-1]; j=read_json(path)
        action=pager(operation_summary(j),'Instalación parcial',kind='error',actions=('Restaurar archivos','Volver','Detalles'),default=1)
        if action in (None,1): return False
        if action==2: pager(safe(json.dumps(j,indent=2,ensure_ascii=False)),'Registro técnico'); continue
        header()
        if confirm('¿Restaurar los archivos administrados de esta operación? Se comprobarán los respaldos y los cambios posteriores. Los paquetes y servicios permanecen.','Restaurar'):
            try: engine.restore(j['id'],True)
            except (Error,OSError) as e: pager(safe(str(e)),'No se pudo restaurar',kind='error')
    return True


def approval_text(plan,decisions):
    lines=['Se instalará la versión '+plan['manifest']['version']+'.','']
    counts={a:sum(c['action']==a for c in plan['files']) for a in ('create','modify','remove')}
    lines += [f"Archivos: {counts['create']} nuevos, {counts['modify']} modificados, {counts['remove']} retirados."]
    for resource,decision in decisions.items():
        name=('Super+Shift+S: captura completa' if decision=='replace' else 'Super+Shift+S: acción actual') if resource=='user:'+capture_shortcut.MAIN and plan['manifest'].get('capture_shortcut') else resource.split(':',1)[-1]
        lines.append(('Reemplazar · ' if decision=='replace' else 'Conservar · ')+name)
    if any(c.get('decision') in ('keep','skip') for c in plan['files']): lines+=['ATENCIÓN: se conservarán recursos que dejan la instalación parcial.']
    dependencies=[p.get('name',p.get('id','dependencia')) for p in plan['packages'] if p['action']!='keep']
    if dependencies: lines+=['Por instalar: '+', '.join(dependencies)+'.']
    lines+=['','Permisos: '+('se pedirá autorización de administrador para operaciones concretas.' if needs_admin(plan) else 'usuario normal.')]
    if plan.get('builds') or plan['code_reviews'] or any(p['provider']=='aur' and p['action']=='build' for p in plan['packages']):
        lines+=['Al instalar autorizas el código incluido en esta versión, también el de terceros, con tus permisos y sin aislamiento. Puedes consultar las fuentes en Detalles.']
    if plan.get('builds') or any(p['provider']=='preparation' for p in plan['packages']): lines+=['La preparación requerirá revisar otro plan antes de continuar.']
    lines+=['','Se guardarán respaldos de los archivos modificados. Restaurarlos no revierte paquetes ni servicios.']
    return clean('\n'.join(lines))

def material_state(plan):
    # Conflict decisions may alter actions/data, but never hide new host/source state.
    return {k:plan.get(k) for k in ('identity','meta','manifest','packages','installed_before','host','permissions','settings_before','trust_before','capture_bindings','plugin_identities','plugin_inventories','operations','recipes','builds')} | {'before':{c['key']:c['before'] for c in plan['files']}}

def manager_prerequisite(config,row,requirement):
    """Only authenticated prose and a manager requirement, never a content plan."""
    parsed=report.sections(requirement.notes)
    prose='\n\n'.join('## '+title+'\n'+body for title,body in (parsed or [(t,report.EMPTY[t]) for t in report.SECTIONS]))
    warning=('\n\n## Actualización necesaria de OmaPacks\nEste pack requiere el gestor '+requirement.required+
             ' o posterior; tienes '+__version__+'.\nAún no se han calculado los cambios del pack en este equipo. '+
             'Primero se actualizará únicamente el gestor, con tus permisos de usuario. '+
             'Se conservan contenido, configuración y respaldos. Después volverás a este reporte con un plan nuevo para decidir si instalas el pack.')
    while True:
        try:
            header(); message('Verificando actualización necesaria del gestor…','strong')
            plan,client=manager_update.prepare(config,requirement.required)
        except (Error,OSError,ValueError) as e:
            if pager(prose+warning+'\n\n'+safe(str(e)),'Reporte · '+requirement.content_version,kind='error',actions=('Reintentar','Volver'),default=1)!=0: return False
            continue
        text='Este pack requiere actualizar OmaPacks: '+__version__+' → '+plan['meta']['version']+'.\n\n'+prose+warning+'\n\nOrigen: '+client.repo+' · firma verificada.\nActualizar gestor autoriza su código con tus permisos, sin aislamiento. No instala paquetes ni necesita sudo.'
        while True:
            action=pager(text,'Reporte · '+requirement.content_version,actions=('Actualizar gestor','Volver','Detalles'),default=1)
            if action in (None,1): return False
            if action==2:
                pager('Actualización del gestor (separada del contenido)\n\nRepositorio: '+client.repo+
                      '\nRelease: '+plan['identity']['tag']+'\nClave: '+plan['before']['policy']['fingerprint']+
                      '\nSHA-256: '+plan['meta']['archive_sha256']+
                      '\n\nSe guardará la copia anterior del gestor. No se cambia el plugin, el origen ni la confianza. No revierte paquetes ni escritorio.\n'+
                      'Si se interrumpe el cambio de carpetas, conserva ambas copias y el registro manager-update.json; reinstalar el gestor es una operación separada.', 'Detalles del gestor')
                continue
            break
        try:
            manager_update.apply(config,plan,client,Progress('gestor '+plan['meta']['version']))
        except (Error,OSError,ValueError) as e:
            pager(safe(str(e))+'\n\nNo se instaló el pack. Revisa el estado del gestor antes de reintentar.','Actualización detenida',kind='error')
            return False
        try: manager_update.restart(config,row['id'])
        except OSError:
            pager('El gestor se actualizó, pero no pudo reabrirse. Cierra OmaPacks y ábrelo desde el menú. Selecciona de nuevo esta release; todavía no se aplicó su contenido.','Gestor actualizado')
        return True


def release_report(config,client,engine,row,resumed=False):
    decisions={}; plan=None; notice='Gestor actualizado. Revisa los cambios del contenido antes de instalarlo.' if resumed else ''; conservative=resumed; confirm_next=False; previous_plan=None
    while True:
        if engine.pending():
            if not recover(engine): return False
            plan=None; decisions={}; notice='Archivos restaurados. Revisa el nuevo plan antes de instalar.'; conservative=True
        if plan is None:
            try:
                header(); message('Preparando reporte de '+clean(row['tag_name'],False),'strong')
                message('Verificando la release y calculando cambios…','muted')
                if read_json(config.path)!=config.data:
                    raise Error('La configuración o los permisos del gestor cambiaron. Cierra y vuelve a abrir OmaPacks para cargar los valores vigentes.','changed')
                identity=pin(config.data['repository'],row)
                stage=config.cache/'staging'/digest(canonical(identity))
                client.download(identity,stage); manifest,meta=verify(stage,config.trust,identity)
                save_json(stage/'identity.json',identity)
                plan=engine.plan(stage,manifest,meta,identity,decisions=decisions)
                save_json(stage/'plan.json',plan)
                if confirm_next and previous_plan and material_state(plan)!=material_state(previous_plan):
                    confirm_next=False; notice='El estado del equipo o la release cambió además de tus decisiones. Revisa el reporte actualizado.'
            except ManagerRequired as requirement:
                return manager_prerequisite(config,row,requirement)
            except (Error,OSError,ValueError) as e:
                detail=safe(str(e))+'\n\nNo se aplicó contenido en este intento. Revisa el diagnóstico antes de reintentar.'
                action=pager(detail,'Reporte bloqueado · '+clean(row['tag_name'],False),kind='error',actions=('Reintentar','Volver','Detalles'),default=1)
                if action in (None,1): return False
                if action==2: pager(safe(str(e)),'Diagnóstico técnico')
                try: row=client.release(row['id'])
                except (Error,OSError,ValueError) as refresh_error:
                    pager(safe(str(refresh_error)),'No se pudo actualizar la release',kind='error')
                continue
        if resumed: manager_update.discard_input(); resumed=False
        action=0 if confirm_next else pager(report_text(row,plan,notice),'Reporte · '+plan['manifest']['version'],actions=('Instalar','Volver','Detalles'),default=1 if conservative else 0)
        if action in (None,1): return False
        if action==2:
            notes=report.signed_notes(plan) or clean(row.get('body') or 'Sin notas de versión.')
            pager('Novedades de la release:\n'+notes+'\n\n'+describe(plan),'Novedades y detalles del plan'); continue
        conflicts=[c for c in plan['files'] if c['conflict'] and c.get('decision') not in ('keep','skip')]
        if conflicts:
            cancelled=False
            for c in conflicts:
                detail='Hay preferencias personales en:\n'+c['target']+'\n\nReemplazar aplica solo el recurso o las claves administradas y guarda respaldo. Conservar puede impedir completar la release.'
                if c['target']==capture_shortcut.MAIN and plan.get('capture_bindings') is not None:
                    previous=', '.join(str(b[-1]) for b in plan['capture_bindings']) or 'sin asignar'
                    detail='Super+Shift+S ahora: '+previous+'.\n\nReemplazar asigna la captura completa y guarda respaldo de los archivos administrados. Conservar mantiene el atajo actual y deja esta release incompleta.\n\nLos demás atajos y ajustes personales se conservan. Después de decidir podrás confirmar la instalación.'
                choice=pager(detail,'Resolver conflicto',actions=('Conservar','Reemplazar','Volver'),default=2)
                if choice in (None,2): cancelled=True; break
                decisions[c['key']]=('keep','replace')[choice]
            previous_plan=plan; plan=None; conservative=True; confirm_next=not cancelled; notice='Decisiones actualizadas. Revisa los cambios antes de instalar.'
            continue
        # One concise confirmation combines the changed plan and code authorization.
        if confirm_next or plan.get('builds') or plan['code_reviews'] or any(p['provider']=='aur' and p['action']=='build' for p in plan['packages']):
            while True:
                approval=pager(approval_text(plan,decisions),'¿Deseas proceder con la instalación?',actions=('Instalar','Volver','Detalles'),default=1)
                if approval!=2: break
                pager(describe(plan),'Detalles técnicos y fuentes')
            confirm_next=False
            if approval!=0: continue
        try:
            journal=engine.apply(plan,plan['id'],progress=Progress(plan['manifest']['version']),verify_remote=client.verify_pin)
            if journal['status']=='complete':
                reminder='Reinicia el equipo para completar la activación.' if plan['recovery']['reboot'] else ''
                return pager(reminder,'Instalación completada correctamente.',completion=True)=='close'
            if journal['status']=='prepared':
                notice='Preparación terminada. '+safe(journal['error'])+' Revisa y aprueba el nuevo plan.'
                decisions={}; plan=None; conservative=True; continue
            # Partial is rendered by recover() on the next iteration.
            plan=None; conservative=True
        except (Error,OSError,ValueError) as e:
            if not engine.pending():
                action=pager(safe(str(e))+'\n\nNo se aplicó contenido en este intento. Recalcula el reporte y revisa los cambios antes de aprobar.',
                             'Instalación bloqueada',kind='error',actions=('Recalcular reporte','Volver'))
                if action!=0: return False
                try: row=client.release(row['id'])
                except (Error,OSError,ValueError) as refresh_error: pager(safe(str(refresh_error)),'No se pudo actualizar la release',kind='error')
            plan=None; decisions={}; conservative=True
            notice='El plan anterior ya no está aprobado. Revisa los cambios recalculados.'


def run(config,mode='install',client=None,engine=None,release_id=None):
    interactive=sys.stdin.isatty() and sys.stdout.isatty()
    try: return _run(config,mode,client,engine,release_id)
    except KeyboardInterrupt:
        pending=(engine or Engine(config.home,settings=config.data)).pending()
        if pending: pager(operation_summary(read_json(pending[-1])),'Cancelado · hay una operación parcial',kind='error')
        if interactive: exit_prompt(True)
        return 130


def _run(config,mode='install',client=None,engine=None,release_id=None):
    if not shutil.which('gum'): raise Error('Falta gum. El instalador inicial debe comprobar los requisitos.')
    if not sys.stdin.isatty() or not sys.stdout.isatty(): raise Error('La TUI necesita una terminal; usa los subcomandos internos para pruebas.')
    config.require(); client=client or GitHub(config.data['repository'],config.cache)
    engine=engine or Engine(config.home,settings=config.data); selected_id=None
    while True:
        header(config,engine.installed(),mode)
        if engine.pending() and not recover(engine): return 0
        message('Consultando releases publicadas…','muted')
        try: result=client.releases()
        except Error as e:
            if pager(safe(str(e))+'\n\nNo se puede determinar si hay novedades.','No se pudo consultar GitHub',kind='error',actions=('Reintentar','Salir'))!=0: return 0
            continue
        notices=[]
        if result['fetched_at'].startswith('DEMO'): notices.append('DEMO · progreso y resultados de prueba')
        if result['cached']: notices.append('Caché de '+result['fetched_at'])
        if not result['complete']: notices.append('Lista incompleta')
        installed=engine.installed(); header(config,installed,mode,' · '.join(notices))
        if result['cached'] or not result['complete']: message(result['warning'] or 'Consulta incompleta','muted')
        rows=sort_releases(result['releases'])
        if release_id is not None:
            resume=release_id; release_id=None
            row=next((r for r in rows if r['id']==resume),None)
            if row and result['complete'] and not result['cached']:
                selected_id=resume
                if release_report(config,client,engine,row,resumed=True): return 0
                continue
            pager('No se pudo volver a abrir la release solicitada con información vigente. Selecciónala cuando esté disponible. No se aplicó contenido.','Revisar contenido')
        if not rows:
            pager('El repositorio no tiene releases publicadas.' if result['complete'] else 'Consulta incompleta: no se puede concluir que no haya releases.','Releases publicadas'); return 0
        labels=release_labels(rows,installed,config.data['repository'],mode)
        default=next((i for i,r in enumerate(rows) if r['id']==selected_id),None)
        if default is None: default=next((i for i,r in enumerate(rows) if not r.get('prerelease')),len(rows))
        selected=choose(labels+['Gestor y plugin','Salir'],'Selecciona una versión',default,highlights=(0,),previews=[report.preview(r.get('body','')) for r in rows])
        if selected is None or selected==len(rows)+1: return 0
        if selected==len(rows): pager(manager_details(config),'Gestor, plugin y contenido'); continue
        row=rows[selected]; selected_id=row['id']
        if release_report(config,client,engine,row): return 0

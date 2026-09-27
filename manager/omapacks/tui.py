"""Native gum TUI. Remote text is always data, never terminal escapes or shell."""
from __future__ import annotations
import json,shutil,subprocess,sys
from .artifact import verify
from .engine import Engine
from .github import GitHub,pin,published
from .util import Error,clean,digest,canonical,read_json,save_json

from .presentation import header,choose,pager,confirm,message,paint,clip,cells,size,exit_prompt

def describe(plan):
    m=plan['manifest']; old=plan['installed_before']; identity=plan['identity']
    lines=['PLAN DE INSTALACIÓN','',f"{old.get('version','sin instalar')} → {m['version']}",f"Origen: {identity['repository']} · release #{identity['release_id']} · {identity['tag']}",
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
        if c.get('owned_values'):
            lines+=['','Aplicaciones predeterminadas · '+c['target']+':']
            for key,value in c['owned_values'].items(): lines.append('  '+key+': '+str(c.get('owned_before',{}).get(key) or 'sin preferencia explícita')+' → '+value)
        if c.get('menu_entries'):
            lines+=['','Entradas de menú compartidas:']
            for key,value in c['menu_entries'].items(): lines.append('  '+value['label']+' · '+(value.get('action') or 'submenú'))
    lines+=['','Permisos y servicios:']
    for op in plan['operations']: lines.append(f"  {op['scope']} · {op['action']} {op['name']} · {op['purpose']}")
    privileged=any(c['scope']=='system' and c['action'] not in ('keep','skip') for c in plan['files']) or any(p['provider'] in ('arch','aur') and p['action']!='keep' or p['provider']=='external' and p['format']=='arch' or p['provider']=='flatpak' and p['scope']=='system' and p['action']!='keep' for p in plan['packages']) or any(op['scope']=='system' for op in plan['operations'])
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
        if installed.get('identity',{}).get('release_id')==r['id'] and installed.get('identity',{}).get('repository')==repository: tags.append('Instalada')
        if published(r.get('published_at'))==float('-inf'): tags.append('Sin fecha')
        try: pin(repository,r)
        except Error: tags.append('No instalable')
        tag=clip(r['tag_name'],width)
        labels.append(tag+' '*(width-cells(tag)+2)+' · '.join(tags))
    return labels


def run(config,mode='install',client=None):
    interactive=sys.stdin.isatty() and sys.stdout.isatty()
    try: result=_run(config,mode,client)
    except KeyboardInterrupt: result=130
    if interactive: exit_prompt(result==130)
    return result

def _run(config,mode='install',client=None):
    if not shutil.which('gum'): raise Error('Falta gum. El instalador inicial debe comprobar los requisitos.')
    if not sys.stdin.isatty() or not sys.stdout.isatty(): raise Error('La TUI necesita una terminal; usa los subcomandos internos para pruebas.')
    config.require(); client=client or GitHub(config.data['repository'],config.cache)
    engine=Engine(config.home,settings=config.data); selected_id=None
    while True:
        header(config,engine.installed(),mode)
        pending=engine.pending()
        if pending:
            j=read_json(pending[-1]); selection=choose(['Ver operación incompleta','Restaurar archivos del respaldo','Salir'],'Recuperación pendiente')
            if selection in (None,2): return 0
            if selection==0: pager(json.dumps(j,indent=2,ensure_ascii=False),'Operación incompleta'); continue
            pager('Se restaurarán los archivos de '+j['id']+'. Los paquetes/servicios no se revierten. Los cambios personales posteriores bloquean la restauración.','Restaurar un respaldo')
            header()
            if confirm('¿Restaurar esos archivos?','Restaurar'):
                try: engine.restore(j['id'],True)
                except Error as e: pager(str(e),'No se pudo restaurar',kind='error')
            continue
        message('Consultando releases publicadas…','muted')
        try: result=client.releases()
        except Error as e:
            pager(f'{e}\n\nNo se puede determinar si hay novedades.','No se pudo consultar GitHub',kind='error')
            header()
            if choose(['Reintentar','Salir'],'Consulta de releases')!=0: return 0
            continue
        notices=[]
        if result['fetched_at'].startswith('DEMO'): notices.append('DEMOSTRACIÓN LOCAL · datos de prueba')
        if result['cached']: notices.append('Caché de '+result['fetched_at'])
        if not result['complete']: notices.append('Lista incompleta')
        notice=' · '.join(notices)
        installed=engine.installed(); header(config,installed,mode,notice)
        if result['cached'] or not result['complete']: message(result['warning'] or 'Consulta incompleta','muted')
        rows=result['releases']
        if not rows:
            pager('El repositorio no tiene releases publicadas.' if result['complete'] else 'Consulta incompleta: no se puede concluir que no haya releases.','Releases publicadas')
            return 0
        labels=release_labels(rows,installed,config.data['repository'],mode)
        default=next((i for i,r in enumerate(rows) if r['id']==selected_id),None)
        if default is None: default=next((i for i,r in enumerate(rows) if not r.get('prerelease')),len(rows))
        title='Selecciona una versión' if mode=='install' else 'Novedades y versiones anteriores'
        highlights=[i for i,r in enumerate(rows) if i==0 and published(r.get('published_at'))!=float('-inf')]
        selected=choose(labels+['Salir'],title,default,highlights=highlights)
        if selected is None or selected==len(rows): return 0
        row=rows[selected]; selected_id=row['id']
        while True:
            date=str(row.get('published_at') or 'fecha ausente')
            notes=clean(row.get('name') or row['tag_name'])+' · '+clean(row['tag_name'],False)+'\nPublicada: '+date+'\n\n'+clean(row.get('body') or 'Sin notas de versión.')
            action=pager(notes,'Qué hay de nuevo en esta configuración',actions=('Instalar','Retroceder'))
            if action!=0: break
            try:
                identity=pin(config.data['repository'],row)
                stage=config.cache/'staging'/digest(canonical(identity))
                header(); message('Preparando '+clean(row['tag_name'],False),'strong')
                message('Descargando y verificando firma…','muted')
                client.download(identity,stage); manifest,meta=verify(stage,config.trust,identity); save_json(stage/'identity.json',identity)
                decisions={}
                while True:
                    plan=engine.plan(stage,manifest,meta,identity,decisions=decisions)
                    conflicts=[c for c in plan['files'] if c['conflict'] and c['action'] not in ('keep','skip')]
                    if not conflicts: break
                    pager('Hay modificaciones personales en:\n\n'+'\n'.join(c['target'] for c in conflicts),'Conflictos locales')
                    header()
                    choice=choose(['Conservar cambios personales','Omitir recursos en conflicto','Aprobar reemplazo con respaldo','Volver'],'Resolver conflictos del plan')
                    if choice in (None,3): plan=None; break
                    decisions.update({c['key']:('keep','skip','replace')[choice] for c in conflicts})
                if plan is None: continue
                save_json(stage/'plan.json',plan); pager(describe(plan),'Revisar instalación · '+manifest['version'])
                header()
                message(plan['installed_before'].get('version','Sin instalar')+' → '+manifest['version'],'strong')
                changed=sum(f['action'] not in ('keep','skip') for f in plan['files'])
                packages=sum(p['action']!='keep' for p in plan['packages'])
                message(f"{changed} archivos · {packages} acciones de paquetes · {len(plan['operations'])} operaciones",'muted')
                message('Se aplicará el plan que acabas de revisar.'); message('')
                if not confirm('¿Instalar los cambios de este plan?'): continue
                header(); message('Instalando '+manifest['version'],'strong'); message('')
                result=engine.apply(plan,plan['id'],progress=lambda s:message(s,'accent'),verify_remote=client.verify_pin)
                summary='Instalación verificada.' if result['status']=='complete' else ('Preparación terminada: ' if result['status']=='prepared' else 'Estado parcial: ')+result['error']
                if result.get('reloads'): summary+='\n\nActivación final:\n'+'\n'.join(r['component']+' · '+r['method']+' · '+r['phase'] for r in result['reloads'])
                pager(summary+'\n\nVersión: '+manifest['version']+'\n\nRegistro de la operación:\n'+str(engine.state/'transactions'/result['id']/'journal.json'),'Resultado',kind='error' if result['status']=='partial' else 'normal')
                if result['status']=='prepared': continue
                break
            except Error as e:
                pager(f'{e}\n\nConsulta el registro local si la operación había comenzado.','No se pudo instalar',kind='error')
                if e.kind=='system_update':
                    header()
                    if choose(['Volver','Actualizar el sistema con Omarchy'],'Requiere actualización completa')==1:
                        header()
                        if confirm('¿Abrir la actualización oficial de Omarchy? Después se calculará otro plan.'):
                            subprocess.run(['omarchy','update'])
                break

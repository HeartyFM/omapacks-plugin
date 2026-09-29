"""Own one bar and bounded menu enablement; retain every other shell setting."""
import copy,json,re
from .util import Error

TARGET='.config/omarchy/shell.json'
PREFIX='.config/omarchy/plugins/'
OWNED=re.compile(r'omapacks\.shared\.[a-z0-9_-]+')

def parse(text):
    def unique(pairs):
        obj={}
        for key,value in pairs:
            if key in obj: raise Error('Clave duplicada en shell.json: '+key)
            obj[key]=value
        return obj
    try: obj=json.loads(text,object_pairs_hook=unique)
    except ValueError: raise Error('shell.json debe ser JSON válido')
    if not isinstance(obj,dict): raise Error('shell.json debe ser un objeto')
    if 'version' in obj and (type(obj['version']) is not int or obj['version']!=1): raise Error('Versión de shell.json no compatible')
    for field in ('disabledPlugins','cloneSourceRestores'):
        if field in obj and (not isinstance(obj[field],list) or any(not isinstance(x,str) for x in obj[field])): raise Error('Lista de shell inválida: '+field)
    return obj

def validate(text,files):
    obj=parse(text)
    if set(obj)!={'bar','disabledPlugins','cloneSourceRestores'}: raise Error('El pack solo administra la barra y la activación de su menú')
    bar=obj['bar']
    if not isinstance(bar,dict) or set(bar)-{'id','position','transparent','centerAnchor','dynamic','layout'}: raise Error('Configuración de barra no admitida')
    if not OWNED.fullmatch(str(bar.get('id',''))): raise Error('Barra fuera del namespace administrado')
    if bar.get('position') not in ('top','bottom','left','right') or type(bar.get('transparent')) is not bool: raise Error('Posición/transparencia inválida')
    declared={f['target'].split('/')[3] for f in files if f['target'].startswith(PREFIX) and f['target'].endswith('/manifest.json')}
    def plugin_id(value):
        if not isinstance(value,str) or not (re.fullmatch(r'omarchy\.[a-z0-9._-]+',value) or value in declared): raise Error('Referencia a plugin no declarada')
    plugin_id(bar['id'])
    if 'centerAnchor' in bar: plugin_id(bar['centerAnchor'])
    layout=bar.get('layout')
    if not isinstance(layout,dict) or set(layout)!={'left','center','right'}: raise Error('Layout de barra inválido')
    dynamic=bar.get('dynamic')
    if dynamic is not None:
        if not isinstance(dynamic,dict) or set(dynamic)-{'version','enabled','contexts','layouts'} or dynamic.get('version')!=1 or type(dynamic.get('enabled')) is not bool: raise Error('Contextos de barra inválidos')
        contexts=dynamic.get('contexts'); layouts=dynamic.get('layouts')
        if not isinstance(contexts,list) or len(contexts)>10 or not isinstance(layouts,dict): raise Error('Layouts contextuales inválidos')
        context_ids=set()
        for context in contexts:
            if not isinstance(context,dict) or set(context)!={'id','label','match'} or not re.fullmatch(r'[a-z][a-z0-9_-]*',str(context['id'])) or not isinstance(context['label'],str): raise Error('Contexto inválido')
            match=context['match']
            if not isinstance(match,dict) or set(match)!={'appIds'} or not isinstance(match['appIds'],list) or not match['appIds'] or any(not isinstance(x,str) or not re.fullmatch(r'[A-Za-z0-9._-]+',x) for x in match['appIds']): raise Error('Match de contexto inválido')
            if context['id'] in context_ids: raise Error('Contexto duplicado')
            context_ids.add(context['id'])
        if set(layouts)!=context_ids: raise Error('Layout sin contexto correspondiente')
        for value in layouts.values():
            if not isinstance(value,dict) or set(value)-{'left','center','right','centerAnchor','indicatorExpand'}: raise Error('Layout contextual inválido')
            if value.get('indicatorExpand','right') not in ('left','right'): raise Error('Dirección de indicadores inválida')
            if 'centerAnchor' in value: plugin_id(value['centerAnchor'])
            for section in ('left','center','right'):
                if section in value:
                    if not isinstance(value[section],list) or len(value[section])>30: raise Error('Widgets contextuales inválidos')
                    for item in value[section]: plugin_id(item)
    refs=set()
    def walk(value):
        if isinstance(value,dict):
            for k,v in value.items():
                if k in ('id','centerAnchor') and isinstance(v,str) and (v.startswith('omarchy.') or v.startswith('omapacks.shared.')): refs.add(v)
                walk(v)
        elif isinstance(value,list):
            for v in value: walk(v)
        elif isinstance(value,str) and (value.startswith('omarchy.') or value.startswith('omapacks.shared.')): refs.add(value)
    walk(bar)
    if any(not (r.startswith('omarchy.') or r in declared) for r in refs): raise Error('La barra necesita plugins declarados en el pack')
    for section in ('left','center','right'):
        values=layout.get(section)
        if not isinstance(values,list) or len(values)>30: raise Error('Sección de barra inválida')
        for item in values:
            if not isinstance(item,dict) or not isinstance(item.get('id'),str) or item['id'] not in refs: raise Error('Widget de barra inválido')
            if not (item['id'].startswith('omarchy.') or item['id'] in declared): raise Error('Widget externo no declarado')
    if obj['disabledPlugins']!=['omarchy.menu'] or len(obj['cloneSourceRestores'])!=1 or not OWNED.fullmatch(obj['cloneSourceRestores'][0]) or obj['cloneSourceRestores'][0] not in declared: raise Error('Activación de menú fuera del perfil compartido')
    # Store list memberships individually; no ownership over foreign plugins.
    return {'bar':bar,'disabledPlugins:omarchy.menu':True,'cloneSourceRestores:'+obj['cloneSourceRestores'][0]:True}

def read(obj,key):
    if ':' not in key: return copy.deepcopy(obj.get(key))
    field,item=key.split(':',1)
    if field=='plugins':
        entries=obj.get(field,[])
        if not isinstance(entries,list) or any(not isinstance(e,dict) or not isinstance(e.get('id'),str) for e in entries): raise Error('Lista plugins inválida')
        found=[e for e in entries if e['id']==item]
        if len(found)>1: raise Error('Plugin duplicado en shell.json: '+item)
        return copy.deepcopy(found[0]) if found else None
    return item in obj.get(field,[])

def merge(text,new,old):
    obj=parse(text); previous=old.get('owned_values',{}); baseline=old.get('baseline_values',{})
    before={key:read(obj,key) for key in set(new)|set(previous)}
    conflict=False
    for key in set(new)|set(previous):
        empty=None if key.startswith('plugins:') or ':' not in key else False
        desired=new[key] if key in new else baseline.get(key,empty)
        if before[key]!=desired and before[key]!=previous.get(key,empty): conflict=True
        if ':' not in key:
            if desired is None: obj.pop(key,None)
            else: obj[key]=desired
        else:
            field,item=key.split(':',1); values=list(obj.get(field,[]))
            if field=='plugins':
                # Replace only this owned entry, preserving every foreign entry.
                index=next((i for i,e in enumerate(values) if e['id']==item),len(values))
                values=[e for e in values if e['id']!=item]
                if desired is not None: values.insert(index,copy.deepcopy(desired))
            elif desired and item not in values: values.append(item)
            elif not desired: values=[x for x in values if x!=item]
            if values: obj[field]=values
            else: obj.pop(field,None)
    origins={key:baseline.get(key,before[key]) for key in new}
    if new: obj.setdefault('version',1)
    result=text if obj==parse(text) else json.dumps(obj,ensure_ascii=False,indent=2)+'\n'
    return result,conflict,origins

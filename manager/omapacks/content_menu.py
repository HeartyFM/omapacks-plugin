"""A signed pack contributes bounded menu entries, never arbitrary shell."""
import json,re,unicodedata
from .menu import edit,members,strip_jsonc
from .util import Error,clean

TARGET='.config/omarchy/extensions/omarchy-menu.jsonc'
PREFIX='omapacks.shared'

def parse(text):
    spans,_=members(text)
    if len({s[0] for s in spans})!=len(spans): raise Error('Claves duplicadas en el menú')
    stripped=strip_jsonc(text); values={}
    for name,start,stop,_ in spans:
        _,key_end=json.JSONDecoder().raw_decode(stripped,start)
        values[name]=json.loads(stripped[stripped.index(':',key_end)+1:stop])
    if 'items' in values:
        for name,start,stop,_ in spans:
            if name=='items': return parse(text[text.index(':',start)+1:stop])
    return values

def validate(text):
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result: raise Error('Claves duplicadas en recurso de menú')
            result[key]=value
        return result
    try: entries=json.loads(text,object_pairs_hook=unique)
    except ValueError: raise Error('El recurso de menú debe ser JSON válido')
    if not isinstance(entries,dict) or not entries: raise Error('Menú compartido vacío o inválido')
    for key,value in entries.items():
        native=key in ('about','about.system','learn','games') or re.fullmatch(r'apps\.[A-Za-z][A-Za-z0-9_.-]*',key)
        if not native and not re.fullmatch(r'omapacks\.shared(?:\.[a-z][a-z0-9_-]*)*',key): raise Error('Entrada fuera del namespace omapacks.shared')
        if not isinstance(value,dict) or set(value)-{'label','description','icon','parent','title','action','after','aliases'} or not value.get('label'): raise Error('Campos de menú no admitidos')
        for field,text in value.items():
            if field=='aliases':
                if not isinstance(text,list) or len(text)>10 or any(not isinstance(v,str) or len(v)>100 or clean(v,False)!=v for v in text): raise Error('Alias de menú inválido')
                continue
            if not isinstance(text,str) or len(text)>200 or (any(unicodedata.category(c) in ('Cc','Cf','Cs','Cn') for c in text) if field=='icon' else clean(text,False)!=text): raise Error('Texto de menú inválido')
        parent=value.get('parent',key.rsplit('.',1)[0] if '.' in key else 'root')
        if native:
            if parent not in ('root','about','games') or parent==key: raise Error('Jerarquía nativa no admitida')
            if key.startswith('apps.') and (parent!='games' or value.get('action')!='uwsm-app -- gtk-launch '+key[5:]+'.desktop'): raise Error('La organización de juegos solo lanza su propio desktop ID')
            if value.get('after') not in (None,'apps'): raise Error('Posición de menú no admitida')
        elif key==PREFIX:
            if parent!='root': raise Error('El grupo omapacks.shared necesita parent=root explícito')
        elif parent not in entries or parent==key or not key.startswith(parent+'.'):
            raise Error('Jerarquía de menú fuera del namespace')
        action=value.get('action','')
        if action not in ('','omarchy-launch-about','omarchy-launch-terminal') and not re.fullmatch(r'uwsm-app -- gtk-launch [A-Za-z][A-Za-z0-9_.-]*\.desktop',action): raise Error('Acción de menú no admitida; no se ejecuta shell arbitrario')
    return entries

def merge(text,new,previous):
    current=parse(text); keys=set(new)|set(previous)
    conflict=any(current.get(k)!=previous.get(k) and current.get(k)!=new.get(k) for k in keys)
    # Preserve every unowned entry/comment even when replacing an owned conflict.
    if all(current.get(k)==new.get(k) for k in keys): return text,False
    return edit(text,new,keys),conflict

def merge_owned(text,new,old):
    current=parse(text); previous=old.get('menu_entries',{}); baseline=old.get('menu_baseline',{})
    keys=set(new)|set(previous)
    desired={k:new[k] if k in new else baseline.get(k) for k in keys}
    conflict=any(current.get(k)!=previous.get(k) and current.get(k)!=desired[k] for k in keys)
    origins={k:baseline.get(k,None if k in previous else current.get(k)) for k in new}
    if all(current.get(k)==desired[k] for k in keys): return text,False,origins
    return edit(text,{k:v for k,v in desired.items() if v is not None},keys),conflict,origins

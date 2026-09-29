"""Merge flat bar/menu TOML tokens, keeping unrelated sections and comments."""
import json,re,tomllib
from .util import Error

TARGET='.config/omarchy/shell.toml'
TOKENS={'bar':{'background','background-alpha','text','active'},
        'menu':{'background','background-alpha','text','border','border-alpha','border-width','scrim','scrim-alpha','selected-background','selected-background-alpha','selected-text','selected-border','selected-border-alpha','selected-border-width'}}

def parse(text):
    try: obj=tomllib.loads(text)
    except ValueError: raise Error('shell.toml local inválido')
    return obj

def validate(text):
    obj=parse(text); result={}
    if not obj or set(obj)-set(TOKENS): raise Error('El estilo compartido solo puede cambiar bar y menu')
    for section,values in obj.items():
        if not isinstance(values,dict) or set(values)-TOKENS[section]: raise Error('Token de estilo no admitido')
        for key,value in values.items():
            if key.endswith('-alpha'):
                if type(value) not in (int,float) or not 0<=value<=1: raise Error('Alpha inválido')
            elif key.endswith('-width'):
                if type(value) not in (int,float) or not 0<=value<=8: raise Error('Ancho inválido')
            elif not isinstance(value,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}(?: #[0-9a-fA-F]{6} [0-9]{1,3}deg)?',value): raise Error('Color/gradiente inválido')
            result[section+'.'+key]=value
    return result

def patch(text,updates):
    obj=parse(text); current={s+'.'+k:v for s,values in obj.items() if s in TOKENS and isinstance(values,dict) for k,v in values.items()}
    pending={k:v for k,v in updates.items() if current.get(k)!=v}; out=[]; section=''; seen=set()
    def append_section():
        for key in list(pending):
            if key.split('.',1)[0]!=section: continue
            value=pending.pop(key)
            if value is not None: out.append(key.split('.',1)[1]+' = '+json.dumps(value)+'\n')
    for line in text.splitlines(keepends=True):
        header=re.fullmatch(r'\s*\[([a-zA-Z0-9_-]+)\]\s*(?:#.*)?',line.strip())
        if header:
            append_section(); section=header[1]; seen.add(section)
        field=re.match(r'\s*([a-zA-Z0-9_-]+)\s*=',line)
        key=section+'.'+field[1] if field else ''
        if key in pending:
            value=pending.pop(key)
            if value is not None: out.append(field[1]+' = '+json.dumps(value)+'\n')
        else: out.append(line)
    if out and not out[-1].endswith('\n'): out[-1]+='\n'
    append_section()
    for section in sorted({k.split('.',1)[0] for k,v in pending.items() if v is not None}):
        if section in seen: raise Error('Sección TOML compleja; requiere revisión manual')
        out.append('\n['+section+']\n'); append_section()
    result=''.join(out); parse(result); return result

def merge(text,new,old):
    obj=parse(text); current={s+'.'+k:v for s,values in obj.items() if s in TOKENS and isinstance(values,dict) for k,v in values.items()}
    previous=old.get('owned_values',{}); baseline=old.get('baseline_values',{}); updates={}; conflict=False
    for key in set(new)|set(previous):
        value=new[key] if key in new else baseline.get(key)
        if current.get(key)!=value:
            conflict|=current.get(key)!=previous.get(key); updates[key]=value
    origins={k:baseline.get(k,current.get(k)) for k in new}
    return patch(text,updates),conflict,origins

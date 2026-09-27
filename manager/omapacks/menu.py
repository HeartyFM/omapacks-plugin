"""Patch only own top-level JSONC members, preserving all other bytes/comments."""
import json,re,shlex
from pathlib import Path
from .util import Error, atomic, secure_path

KEYS=('install.omapacks','update.omapacks')

def strip_jsonc(text):
    out=[]; i=0; quote=False
    while i<len(text):
        c=text[i]
        if quote:
            out.append(c)
            if c=='\\' and i+1<len(text): i+=1; out.append(text[i])
            elif c=='"': quote=False
        elif c=='"': quote=True; out.append(c)
        elif text[i:i+2]=='//':
            end=text.find('\n',i); end=len(text) if end<0 else end
            out.extend(' '*(end-i)); i=end-1
        elif text[i:i+2]=='/*':
            end=text.find('*/',i+2)
            if end<0: raise Error('Comentario JSONC sin cerrar')
            out.extend(' '*(end+2-i)); i=end+1
        else: out.append(c)
        i+=1
    return ''.join(out)

def members(text):
    stripped=strip_jsonc(text); decoder=json.JSONDecoder(); spans=[]
    i=0
    while i<len(stripped) and stripped[i].isspace(): i+=1
    if i>=len(stripped) or stripped[i]!='{': raise Error('La extensión del menú debe ser un objeto JSONC')
    i+=1
    while True:
        while i<len(stripped) and stripped[i].isspace(): i+=1
        if i<len(stripped) and stripped[i]=='}': return spans,i
        start=i
        try: k,end=decoder.raw_decode(stripped,i)
        except ValueError: raise Error('No se pudo analizar el menú JSONC')
        i=end
        while stripped[i].isspace(): i+=1
        if stripped[i]!=':': raise Error('Menú JSONC inválido')
        i+=1
        while stripped[i].isspace(): i+=1
        try: _,end=decoder.raw_decode(stripped,i)
        except ValueError: raise Error('Valor JSONC no soportado (se conserva el original)')
        i=end
        while stripped[i].isspace(): i+=1
        comma=i if stripped[i]==',' else None
        spans.append((k,start,end,comma))
        if comma is not None: i+=1
        elif stripped[i]!='}': raise Error('Menú JSONC inválido')

def edit(text,entries,keys=KEYS):
    spans,end=members(text)
    for name,start,stop,comma in spans:
        if name=='items':
            stripped=strip_jsonc(text)
            _,key_end=json.JSONDecoder().raw_decode(stripped,start)
            value_start=stripped.index(':',key_end)+1
            while stripped[value_start].isspace(): value_start+=1
            return text[:value_start]+edit(text[value_start:stop],entries,keys)+text[stop:]
    # Remove own entries backwards including one adjacent separator.
    while True:
        spans,end=members(text)
        index=next((i for i in range(len(spans)-1,-1,-1) if spans[i][0] in keys),None)
        if index is None: break
        k,start,stop,comma=spans[index]
        if comma is not None: text=text[:start]+text[comma+1:]
        elif index>0 and spans[index-1][3] is not None:
            prev=spans[index-1][3]; text=text[:prev]+text[prev+1:start]+text[stop:]
        else: text=text[:start]+text[stop:]
    spans,end=members(text)
    if entries:
        insertion=(',' if spans and spans[-1][3] is None else '')+'\n'+',\n'.join('  '+json.dumps(k)+': '+json.dumps(v,ensure_ascii=False) for k,v in entries.items())+'\n'
        text=text[:end]+insertion+text[end:]
    members(text)
    return text

def integrate(home,remove=False):
    home=Path(home); path=secure_path(home,'.config/omarchy/extensions/omarchy-menu.jsonc')
    original=path.read_text() if path.exists() else '{}\n'
    exe=home/'.local/bin/omapacks'
    entries={}
    if not remove:
        for section in ('install','update'):
            # The native presentation helper accepts a command string. Quote each level.
            inner='exec '+shlex.quote(str(exe))+' tui --mode '+section
            entries[section+'.omapacks']={'label':'Configuración compartida','description':'OmaPacks · Releases compartidas de Diego y Rafa','icon':'󰉉','action':'omarchy-launch-floating-terminal-with-presentation '+shlex.quote(inner)}
    changed=edit(original,entries)
    if changed!=original:
        if path.exists() and not remove:
            backup=path.with_name('omapacks-menu.before.jsonc')
            if not backup.exists(): atomic(backup,original,0o600)
        atomic(path,changed,0o644)
    return path

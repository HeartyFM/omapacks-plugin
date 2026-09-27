"""Bounded XDG/Omarchy defaults; merge owned keys and keep unrelated preferences."""
import json,re
from .util import Error,clean

MIME='.config/mimeapps.list'
TERMINAL='.config/xdg-terminals.list'
EDITOR='.local/state/omarchy/defaults/editor'
PATHS={MIME:'mime',TERMINAL:'terminal',EDITOR:'editor'}
APPS={'firefox.desktop':'firefox','zen.desktop':'zen-browser-bin','nvim.desktop':'neovim',
      'org.gnome.Nautilus.desktop':'nautilus','imv.desktop':'imv',
      'org.gnome.Evince.desktop':'evince','mpv.desktop':'mpv','kitty.desktop':'kitty'}

def validate(text,packages):
    try: data=json.loads(text)
    except ValueError: raise Error('Defaults deben ser JSON válido')
    if not isinstance(data,dict) or set(data)-{'mime','terminal','editor'}: raise Error('Defaults no admitidos')
    mime=data.get('mime',{})
    if not isinstance(mime,dict) or len(mime)>100: raise Error('Asociaciones MIME inválidas')
    needed=set()
    for key,desktop in mime.items():
        if not re.fullmatch(r'[a-z][a-z0-9.+-]*/[a-zA-Z0-9.+_-]+',key): raise Error('Tipo MIME inválido')
        if not isinstance(desktop,str) or desktop not in APPS: raise Error('Aplicación predeterminada no soportada: '+clean(desktop))
        needed.add(APPS[desktop])
    if 'terminal' in data:
        if data['terminal']!='kitty.desktop': raise Error('Terminal predeterminado soportado en esta entrega: Kitty')
        needed.add('kitty')
    if 'editor' in data:
        if data['editor']!='nvim': raise Error('Editor predeterminado soportado en esta entrega: Neovim')
        needed.add('neovim')
    declared={p['name'] for p in packages}
    if not needed<=declared: raise Error('Faltan dependencias de aplicaciones predeterminadas: '+', '.join(sorted(needed-declared)))
    result={MIME:mime} if mime else {}
    if 'terminal' in data: result[TERMINAL]={'value':data['terminal']}
    if 'editor' in data: result[EDITOR]={'value':data['editor']}
    if not result: raise Error('Defaults vacíos')
    return result

def read(text,kind):
    result={}; active=kind!='mime'
    for line in text.splitlines():
        stripped=line.strip()
        if not stripped or stripped.startswith(('#',';')): continue
        if kind=='mime':
            if stripped.startswith('['): active=stripped=='[Default Applications]'; continue
            if active:
                if '=' not in stripped: raise Error('Asociación MIME local inválida')
                key,value=stripped.split('=',1); key=key.strip()
                if key in result: raise Error('Asociación MIME local duplicada: '+key)
                result[key]=value.strip().rstrip(';')
        elif kind=='terminal':
            if stripped.startswith('!'): continue
            return {'value':stripped}
        else:
            if result: raise Error('Default editor local ambiguo')
            result={'value':stripped}
    return result

def patch(text,kind,updates):
    if not updates: return text
    if kind!='mime':
        current=read(text,kind).get('value'); desired=updates.get('value')
        if current==desired: return text
        lines=text.splitlines(keepends=True)
        # Change just the preferred entry. Preserve fallback terminals/comments.
        for index,line in enumerate(lines):
            if current and line.strip()==current:
                lines[index]=(desired+'\n') if desired is not None else ''; break
        else:
            if desired is not None: lines.insert(0,desired+'\n')
        return ''.join(lines)
    lines=text.splitlines(keepends=True); out=[]; active=False; found=False; pending=dict(updates)
    def append_pending():
        if out and not out[-1].endswith('\n'): out[-1]+='\n'
        out.extend(k+'='+v+'\n' for k,v in pending.items() if v is not None); pending.clear()
    for line in lines:
        stripped=line.strip()
        if stripped.startswith('['):
            if active: append_pending()
            active=stripped=='[Default Applications]'; found|=active
        if active and not stripped.startswith(('#',';','[')) and '=' in stripped:
            key=stripped.split('=',1)[0].strip()
            if key in updates:
                value=updates[key]; pending.pop(key,None)
                if value is not None: out.append(key+'='+value+'\n')
                continue
        out.append(line)
    if not found:
        if out and not out[-1].endswith('\n'): out[-1]+='\n'
        out.append('[Default Applications]\n')
    append_pending()
    return ''.join(out)

def merge(text,kind,new,old):
    current=read(text,kind); previous=old.get('owned_values',{}); baseline=old.get('baseline_values',{})
    keys=set(new)|set(previous); updates={}; conflict=False
    for key in keys:
        desired=new[key] if key in new else baseline.get(key)
        if current.get(key)!=desired:
            if current.get(key)!=previous.get(key): conflict=True
            updates[key]=desired
    origins={k:baseline[k] if k in baseline else current.get(k) for k in new}
    return patch(text,kind,updates),conflict,origins

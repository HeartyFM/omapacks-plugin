"""Read-only binding identity across conf dispatchers and Lua callbacks."""
from .util import Error

def essential(bindings):
    if not isinstance(bindings,list) or not all(isinstance(b,dict) for b in bindings): raise Error('Respuesta de bindings inválida')
    result=[]
    for b in bindings:
        dispatcher=b.get('dispatcher',''); arg=str(b.get('arg','')).lower()
        description=str(b.get('description','')).lower()
        legacy=dispatcher in ('exit','killactive') or any(word in arg for word in ('terminal','omarchy-menu','omarchy menu'))
        lua=dispatcher=='__lua' and any(word in description for word in ('terminal','omarchy menu','system menu','close window','close active window','cerrar ventana','menú de omarchy'))
        if legacy or lua: result.append(b)
    return result

def identity(binding):
    keys=('modmask','key','keycode','submap','release','longPress','mouse','dispatcher')
    # Numeric callback handles are allocated again on reload. They are not a
    # persistent command identity. Compare the described shortcut instead.
    return tuple(binding.get(k) for k in keys)+(binding.get('description') if binding.get('dispatcher')=='__lua' else binding.get('arg'),)

def preserved(expected,observed):
    return {identity(b) for b in expected}<={identity(b) for b in observed}

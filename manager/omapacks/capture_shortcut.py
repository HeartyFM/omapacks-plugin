"""One typed fullscreen shortcut; never accept a command, arbitrary key or Lua."""
from .util import Error
from . import hypr

MAIN='.config/hypr/hyprland.lua'
SNIPPET='.config/omapacks-shared/hyprland.lua'
DESCRIPTION='OmaPacks: Captura completa'
CODE='\n-- OmaPacks: captura completa\nhl.unbind("SUPER + SHIFT + S")\no.bind("SUPER + SHIFT + S", "'+DESCRIPTION+'", "omarchy-capture-screenshot fullscreen save")\n'

def validate(value):
    if value!={'key':'SUPER + SHIFT + S','mode':'fullscreen','output':'save'}:
        raise Error('La captura tipada solo admite SUPER + SHIFT + S, fullscreen y save')

def bindings(rows):
    if not isinstance(rows,list) or any(not isinstance(b,dict) for b in rows): raise Error('Respuesta de bindings inválida')
    result=[b for b in rows if b.get('modmask')==65 and str(b.get('key','')).lower()=='s']
    if any(b.get('submap') or b.get('mouse') or b.get('release') or b.get('longPress') for b in result):
        raise Error('El atajo tiene variantes o submapas que requieren revisión manual')
    return result

def snapshot(rows): return [list(hypr.identity(b)) for b in bindings(rows)]

def active(rows):
    found=bindings(rows)
    return len(found)==1 and found[0].get('description')==DESCRIPTION

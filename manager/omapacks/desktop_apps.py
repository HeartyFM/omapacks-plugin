"""Bounded desktop-file overrides: hide old shortcuts, never delete app data."""
import configparser, os
from pathlib import Path
from .util import Error, secure_path

HIDE_IDS={n+'.desktop' for n in ('Basecamp','ChatGPT','Discord','Figma','Fizzy','GitHub',
    'Google Contacts','Google Maps','Google Messages','Google Photos','HEY','WhatsApp','X','YouTube','Zoom')}
PREFIX='.local/share/applications/'

def validate_cleanup(value):
    if not isinstance(value,dict) or set(value)!={'hide'} or not isinstance(value['hide'],list):
        raise Error('Limpieza: solo se admite hide con accesos web concretos')
    if any(not isinstance(v,str) or v not in HIDE_IDS for v in value['hide']) or len(set(value['hide']))!=len(value['hide']):
        raise Error('Acceso fuera de la limpieza revisada')
    return value['hide']

def hidden_entry(name):
    return ('[Desktop Entry]\nType=Application\nName='+name.removesuffix('.desktop')+'\nHidden=true\n').encode()

def find(home,name):
    # Follow the desktop-file precedence without starting the application.
    dirs=[Path(home)/PREFIX,Path(home)/'.local/share/flatpak/exports/share/applications']
    dirs += [Path(d)/'applications' for d in os.environ.get('XDG_DATA_DIRS','/usr/local/share:/usr/share').split(':') if d.startswith('/')]
    dirs.append(Path('/var/lib/flatpak/exports/share/applications'))
    for directory in dirs:
        path=directory/name
        if path.is_file(): return path
    raise Error('Falta el acceso instalado: '+name,'check')

def check(home,name,runner):
    path=find(home,name)
    parser=configparser.ConfigParser(interpolation=None,strict=False)
    parser.read_string(path.read_text()); entry=parser['Desktop Entry']
    if entry.get('Hidden','false').lower()=='true' or not entry.get('Exec'):
        raise Error('El acceso está oculto o no tiene lanzador: '+name,'check')
    runner.run(['desktop-file-validate',str(path)])
    return str(path)+' · acceso verificado sin abrir la aplicación'

#!/usr/bin/env python3
"""Standalone install/uninstall: Python stdlib, no pip, Git or source checkout."""
import argparse,json,os,shutil,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from omapacks import __version__
from omapacks.config import Config,public_identity
from omapacks.github import repository
from omapacks.menu import integrate
from omapacks.util import Error,atomic,require_user,secure_path,read_json,save_json

ROOT=Path(__file__).resolve().parent

def preflight(repo,public_key):
    require_user()
    missing=[c for c in ('python3','gum','ssh-keygen','omarchy-launch-floating-terminal-with-presentation') if not shutil.which(c)]
    if sys.version_info<(3,11): missing.append('Python >= 3.11')
    if missing: raise Error('Requisitos ausentes: '+', '.join(missing)+'. No se instalan dependencias sin revisión.')
    repository(repo)
    if public_key is None: raise Error('Falta clave pública inicial')
    return public_identity(public_key)[1]

def install(home,repo,public_key,yes=False):
    fingerprint=preflight(repo,public_key)
    home=Path(home).absolute(); config=Config(home)
    target=secure_path(home,'.local/share/omapacks-manager'); launcher=home/'.local/bin/omapacks'
    if target.exists() and not (target/'omapacks-manager.json').is_file(): raise Error('El destino contiene otro proyecto; no se reemplaza')
    if launcher.exists() or launcher.is_symlink():
        if not launcher.is_symlink() or launcher.resolve()!=target/'bin/omapacks': raise Error('Ya existe un comando omapacks ajeno al instalador')
    print('OmaPacks gestor '+__version__+'\nRepositorio de contenido: '+repo+'\nClave del publicador: '+fingerprint+'\nSe instalará en '+str(target)+'\nSe añadirán Install/Update → Configuración compartida.\nNo se instalan packs ni paquetes durante este paso.')
    if not yes and input('¿Instalar gestor y confiar en la clave pública entregada? [sí/NO] ').strip().lower() not in ('sí','si'): return False
    # Validate menu before making changes.
    from omapacks.menu import members
    menu=secure_path(home,'.config/omarchy/extensions/omarchy-menu.jsonc')
    if menu.exists(): members(menu.read_text())
    parent=target.parent; parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.omapacks-install-',dir=parent))
    old=target.with_name('.omapacks-manager.previous')
    try:
        for name in ('omapacks','bin'):
            shutil.copytree(ROOT/name,stage/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        for name in ('install.py','install.sh','uninstall.sh'):
            shutil.copy2(ROOT/name,stage/name)
        save_json(stage/'omapacks-manager.json',{'version':__version__,'repository':repo})
        if old.exists(): raise Error('Hay una instalación anterior incompleta: '+str(old))
        if target.exists(): os.rename(target,old)
        os.rename(stage,target)
        config.configure(repo,public_key,system_files=config.data.get('system_files',[]),services=config.data.get('services',[]))
        launcher.parent.mkdir(parents=True,exist_ok=True)
        if not launcher.is_symlink(): launcher.symlink_to(target/'bin/omapacks')
        integrate(home)
        if old.exists(): shutil.rmtree(old)
    except BaseException:
        if old.exists():
            if target.exists(): shutil.rmtree(target)
            os.rename(old,target)
        raise
    finally:
        if stage.exists(): shutil.rmtree(stage)
    print('Instalado. Abre Install → Configuración compartida.'); return True

def uninstall(home,yes=False):
    require_user(); home=Path(home).absolute(); target=secure_path(home,'.local/share/omapacks-manager')
    if not (target/'omapacks-manager.json').is_file(): raise Error('Gestor no instalado en ese hogar')
    print('Se retirarán solo el gestor, su comando y sus dos entradas del menú.\nSe conservan configuración compartida, aplicaciones, origen, confianza, registros y respaldos.\nLa retirada del contenido es una decisión separada y requiere revisar un plan.')
    if not yes and input('¿Retirar el gestor? [sí/NO] ').strip().lower() not in ('sí','si'): return False
    integrate(home,True)
    launcher=home/'.local/bin/omapacks'
    if launcher.is_symlink() and launcher.resolve()==target/'bin/omapacks': launcher.unlink()
    shutil.rmtree(target); return True

def main():
    p=argparse.ArgumentParser(); p.add_argument('--home',type=Path,default=Path.home()); p.add_argument('--repo'); p.add_argument('--public-key',type=Path); p.add_argument('--yes',action='store_true'); p.add_argument('--uninstall',action='store_true'); a=p.parse_args()
    try:
        if a.uninstall: uninstall(a.home,a.yes)
        else:
            bundle=read_json(ROOT/'bundle.json',{})
            repo=a.repo or bundle.get('repository'); key=a.public_key or (ROOT/'publisher.pub' if (ROOT/'publisher.pub').is_file() else None)
            if not repo: raise Error('Entrega sin origen de contenido configurado. Diego debe preparar el bundle con --repo y clave pública antes de enviarlo a Rafa.')
            install(a.home,repo,key,a.yes)
    except (Error,OSError,ValueError) as e: print('OmaPacks: '+str(e),file=sys.stderr); return 1
    return 0
if __name__=='__main__': sys.exit(main())

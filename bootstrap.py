#!/usr/bin/env python3
"""One initial offer, then dormant. The installed manager owns future launches."""
import argparse,os,shlex,subprocess,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'manager'))

def main():
    from omapacks.config import Config
    from omapacks.util import Error,read_json,save_json,secure_path,lock
    parser=argparse.ArgumentParser(); parser.add_argument('--interactive',action='store_true'); parser.add_argument('--retry',action='store_true'); args=parser.parse_args()
    home=Path.home(); config=Config(home)
    from omapacks import __version__
    from omapacks.util import version
    installed=read_json(home/'.local/share/omapacks-manager/omapacks-manager.json',{})
    upgrade=bool(installed and version(installed['version'])<version(__version__))
    if not args.interactive:
        marker=secure_path(home,'.local/state/omapacks/plugin-offered.json')
        with lock(home/'.local/state/omapacks-plugin'):
            if not args.retry:
                offered=read_json(marker,{})
                if installed and not upgrade or offered.get('version')==__version__: return 0
            command='exec '+shlex.join(['python3',str(ROOT/'bootstrap.py'),'--interactive'])
            subprocess.run(['omarchy-launch-floating-terminal-with-presentation',command],check=True)
            save_json(marker,{'offered':True,'version':__version__,'retry':'Instalar.sh en la carpeta del plugin'})
        return 0
    from omapacks.presentation import header,message,confirm,exit_prompt,pager
    from install import install,preflight
    try:
        bundle=read_json(ROOT/'manager/bundle.json',{})
        repository=bundle.get('repository')
        public_key=ROOT/'manager/publisher.pub'
        if not repository or not public_key.is_file(): raise Error('Plugin de desarrollo sin origen y confianza listos. Diego debe entregar el plugin configurado; Rafa no tiene que editar código.')
        # Existing installations do not silently change origin or trust on plugin updates.
        if upgrade:
            from omapacks.config import public_identity
            config.require()
            delivered=public_identity(public_key)[0]
            expected='omapacks-release namespaces="omapacks-v1" '+delivered
            if config.data['repository']!=repository or config.trust.read_text().strip()!=expected: raise Error('El plugin tiene otro origen o confianza. Se conserva el gestor instalado; revisa una actualización separada.')
            details='Actualizar gestor OmaPacks '+installed['version']+' → '+__version__+'\n\nIncluye diagnóstico previo, recuperación y revisión del plan.\nSe conservarán el origen, la confianza, los packs instalados y sus respaldos.\nNo aplica configuración del escritorio ni instala aplicaciones durante este paso.'
            if pager(details,'Actualizar gestor',actions=('Continuar','Volver'))!=0:
                exit_prompt(True); return 0
            if not confirm('¿Actualizar el gestor OmaPacks?','Actualizar gestor'):
                exit_prompt(True); return 0
            install(home,repository,public_key,yes=True)
        elif not installed:
            if config.data.get('repository') or config.trust.exists():
                from omapacks.config import public_identity
                config.require()
                expected='omapacks-release namespaces="omapacks-v1" '+public_identity(public_key)[0]
                if config.data['repository']!=repository or config.trust.read_text().strip()!=expected:
                    raise Error('La reinstalación conserva el origen y la confianza existentes. La entrega no coincide; revísala sin reconfigurar ni borrar el estado.')
            fingerprint=preflight(repository,public_key)
            details='Gestor OmaPacks '+__version__+'\nRepositorio de contenido: '+repository+'\n\nSe instalará el gestor en tu carpeta de usuario y se añadirán:\nInstall → Configuración compartida\nUpdate → Configuración compartida\n\nNo requiere administrador ni instala paquetes o configuraciones en este paso.\n\nConfianza inicial del publicador:\n'+fingerprint+'\n\nEsta clave pública verificará las próximas releases. La clave privada nunca se entrega.\n\nRequisitos comprobados. No necesitas descargar el proyecto de desarrollo.'
            if pager(details,'Preparar OmaPacks',actions=('Continuar','Volver'))!=0:
                exit_prompt(True); return 0
            config.data={**config.data,'repository':repository}
            header(config); message('Gestor '+__version__,'strong'); message('Añadir gestor, confianza y accesos Install/Update.')
            message('←→ elegir · Enter confirmar · Esc/Ctrl+C cancelar','muted'); message('')
            if not confirm('¿Instalar OmaPacks y confiar en este publicador?','Instalar gestor'):
                exit_prompt(True); return 0
            install(home,repository,public_key,yes=True)
        config=Config(home); config.require()
        # Run the installed copy, which survives removal of the plugin checkout.
        os.execv(str(home/'.local/bin/omapacks'),['omapacks','tui'])
    except KeyboardInterrupt: exit_prompt(True); return 130
    except (Error,OSError,ValueError) as e:
        pager(str(e),'No se pudo preparar OmaPacks',kind='error'); exit_prompt(); return 1

if __name__=='__main__': sys.exit(main())

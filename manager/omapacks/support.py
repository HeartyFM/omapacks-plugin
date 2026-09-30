"""Shareable read-only inventory; also works as a standalone stdlib script."""
import argparse,datetime,json,os,re,stat,subprocess
from pathlib import Path

def read(path):
    try:
        info=path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size>32*1024*1024:return {'unreadable':True}
        value=json.loads(path.read_text())
        return value if isinstance(value,dict) else {'unreadable':True}
    except FileNotFoundError:return {}
    except (OSError,ValueError):return {'unreadable':True}

def version(argv):
    try:
        result=subprocess.run(argv,capture_output=True,text=True,timeout=10)
        match=re.search(r'(?<!\w)(\d+\.\d+\.\d+(?:-\d+(?:\.\d+)*)?)',result.stdout)
        return match[1] if result.returncode==0 and match else None
    except (OSError,subprocess.TimeoutExpired):return None

def bounded(value,pattern):
    return value if isinstance(value,str) and re.fullmatch(pattern,value) else None

def report(home):
    home=Path(home)
    marker=read(home/'.local/share/omapacks-manager/omapacks-manager.json')
    installed=read(home/'.local/state/omapacks/installed.json')
    settings=read(home/'.config/omapacks/settings.json')
    plugin=read(home/'.config/omarchy/plugins/heartyfm.omapacks/manifest.json')
    pending=[]
    for path in sorted((home/'.local/state/omapacks/transactions').glob('*/journal.json')):
        journal=read(path)
        if journal.get('status') in ('complete','restored','prepared'):continue
        pending.append({'id':bounded(path.parent.name,r'[a-f0-9]{32}'),
                        'status':bounded(journal.get('status'),r'[a-z-]{1,40}') or 'unknown',
                        'files_recorded':len(journal.get('files',[])), 'packages_recorded':len(journal.get('packages',[]))})
    manager_update=read(home/'.local/state/omapacks/manager-update.json')
    return {'report_schema':1,'time_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'omarchy':version(['omarchy','version']),'hyprland':version(['Hyprland','--version']),
            'hyprland_format':'lua' if (home/'.config/hypr/hyprland.lua').is_file() else 'conf' if (home/'.config/hypr/hyprland.conf').is_file() else None,
            'manager':bounded(marker.get('version'),r'\d+\.\d+\.\d+'),
            'plugin':bounded(plugin.get('version'),r'\d+\.\d+\.\d+'),
            'content':bounded(installed.get('version'),r'\d+\.\d+\.\d+'),
            'repository':bounded(settings.get('repository'),r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+'),
            'pending':pending,'manager_update_status':bounded(manager_update.get('status'),r'[a-z-]{1,40}'),
            'state_unreadable':any(v.get('unreadable') for v in (marker,installed,settings,plugin,manager_update)),
            'privacy':'No contiene configuraciones, rutas personales, tokens, cuentas, dispositivos ni diarios completos. No instala ni modifica nada.'}

def main():
    p=argparse.ArgumentParser(description='Comprobación de solo lectura para acompañar a Rafa');p.add_argument('--home',type=Path,default=Path.home());a=p.parse_args()
    print(json.dumps(report(a.home),ensure_ascii=False,indent=2))

if __name__=='__main__':main()

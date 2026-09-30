import os, platform, re
from pathlib import Path
from .util import Runner

def detect(home, runner=None):
    runner=runner or Runner()
    result={'architecture':platform.machine(),'omarchy':None,'hyprland':None,'hyprland_format':None}
    for name,argv in [('omarchy',['omarchy','version']),('hyprland',['Hyprland','--version'])]:
        try:
            r=runner.run(argv,check=False)
            m=re.search(r'\b(\d+\.\d+\.\d+)',r.stdout)
            if m:
                result[name]=m.group(1)
                if name=='omarchy':
                    full=re.search(r'(?<!\S)(\d+\.\d+\.\d+(?:-\d+(?:\.\d+)*)?)(?!\S)',r.stdout.strip())
                    if full: result['omarchy_package']=full[1]
        except Exception: pass
    # Binary version + primary configuration. Coexisting legacy files do not win.
    lua=Path(home)/'.config/hypr/hyprland.lua'; conf=Path(home)/'.config/hypr/hyprland.conf'
    if lua.is_file() and result['hyprland'] and tuple(map(int,result['hyprland'].split('.'))) >= (0,55,0): result['hyprland_format']='lua'
    elif conf.is_file() and not lua.is_file(): result['hyprland_format']='conf'
    return result

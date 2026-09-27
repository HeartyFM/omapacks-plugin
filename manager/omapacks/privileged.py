"""Narrow root writer, invoked for one approved /etc/omapacks file only."""
import base64,json,os,sys
from pathlib import Path
# Script entry: use the installed package, never a manifest-supplied import path.
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from omapacks.fs import Files
from omapacks.manifest import destination, fields
from omapacks.util import Error

def main():
    if os.geteuid()!=0: raise Error('Este helper necesita la elevación de una operación concreta')
    raw=sys.stdin.buffer.read(24*1024*1024+1)
    if len(raw)>24*1024*1024: raise Error('Petición demasiado grande')
    obj=json.loads(raw); fields(obj,('target','data','mode','expected'),('target','data','mode','expected'))
    destination(obj['target'],'system')
    if obj['mode'] not in (0o600,0o644): raise Error('Sistema: solo archivos de datos sin permiso ejecutable')
    fs=Files('/',0)
    if obj['data'] is None: fs.remove(obj['target'],obj['expected'])
    else: fs.write(obj['target'],base64.b64decode(obj['data'],validate=True),obj['mode'],obj['expected'])
if __name__=='__main__':
    try: main()
    except Exception as e: print(str(e),file=sys.stderr); sys.exit(1)

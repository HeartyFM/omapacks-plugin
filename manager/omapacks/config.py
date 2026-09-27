import os,re,shutil,subprocess
from pathlib import Path
from .github import repository
from .util import Error, read_json, save_json, secure_path, atomic

def public_identity(public_key):
    """Validate the initial public key with OpenSSH, before installing anything."""
    key=Path(public_key).read_text().strip().split()
    if len(key)<2 or key[0]!='ssh-ed25519' or not re.fullmatch(r'[A-Za-z0-9+/=]+',key[1]):
        raise Error('Se requiere una clave pública Ed25519 de OpenSSH')
    canonical=key[0]+' '+key[1]
    result=subprocess.run(['ssh-keygen','-lf','-','-E','sha256'],input=canonical+'\n',text=True,capture_output=True,timeout=10)
    fields=result.stdout.split()
    if result.returncode or len(fields)<2 or not fields[1].startswith('SHA256:'):
        raise Error('La clave pública del publicador no es válida')
    return canonical,fields[1]

class Config:
    def __init__(self,home=None):
        self.home=Path(home or Path.home()).absolute()
        self.directory=self.home/'.config/omapacks'; self.path=self.directory/'settings.json'
        self.data=read_json(self.path,{})
    def require(self):
        if not self.data.get('repository'): raise Error('Falta el repositorio de contenido. Diego debe configurar el instalador una sola vez; Rafa no necesita códigos ni enlaces por actualización.', 'setup')
        repository(self.data['repository'])
        trust=secure_path(self.directory,'allowed_signers')
        if not trust.is_file(): raise Error('Falta la confianza inicial del publicador', 'setup')
        return self.data
    @property
    def trust(self): return self.directory/'allowed_signers'
    @property
    def state(self): return self.home/'.local/state/omapacks'
    @property
    def cache(self): return self.home/'.cache/omapacks'
    def configure(self,repo,public_key,*,system_files=None,services=None):
        repository(repo)
        key,_=public_identity(public_key)
        from .manifest import destination,string
        for target in system_files or []: destination(target,'system')
        for name in services or []: string(name,r'[a-zA-Z0-9][a-zA-Z0-9_.@-]*\.service')
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        atomic(secure_path(self.directory,'allowed_signers'),'omapacks-release namespaces="omapacks-v1" '+key+'\n')
        self.data={'schema':1,'repository':repo,'system_files':system_files or [],'services':services or []}
        save_json(secure_path(self.directory,'settings.json'),self.data)

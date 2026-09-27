"""Descriptor-relative filesystem access. No symlink component is followed."""
import contextlib, os, stat, uuid
from pathlib import Path
from .util import Error, digest, relative

class Files:
    def __init__(self, root, uid=None): self.root=Path(root).absolute(); self.uid=os.getuid() if uid is None else uid
    @contextlib.contextmanager
    def parent(self, rel, create=False):
        relative(rel); parts = (self.root/rel).parts
        fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
        try:
            for index, part in enumerate(parts[1:-1], 1):
                try: nextfd=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                except FileNotFoundError:
                    if not create: raise
                    os.mkdir(part,0o755,dir_fd=fd); nextfd=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                st=os.fstat(nextfd)
                # /tmp may be sticky and root-owned; user-controlled ancestors cannot be writable to others.
                within_root = Path(*parts[:index+1]) == self.root or self.root in Path(*parts[:index+1]).parents
                if (within_root and st.st_uid != self.uid) or (st.st_mode & 0o022 and not st.st_mode & stat.S_ISVTX):
                    os.close(nextfd); raise Error('Directorio con propietario/permisos inseguros')
                os.close(fd); fd=nextfd
            yield fd,parts[-1]
        except OSError as e:
            if isinstance(e,FileNotFoundError): raise
            raise Error('Acceso seguro rechazado: '+rel+' ('+e.strerror+')') from e
        finally: os.close(fd)
    def read(self, rel):
        try:
            with self.parent(rel) as (fd,name):
                f=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd)
                try:
                    st=os.fstat(f)
                    if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1 or st.st_uid!=self.uid or st.st_mode & 0o022 or st.st_size>512*1024*1024: raise Error('Archivo inseguro: '+rel)
                    data=b''
                    while chunk:=os.read(f,65536): data+=chunk
                    return data,stat.S_IMODE(st.st_mode)
                finally: os.close(f)
        except FileNotFoundError: return None
    def state(self,rel):
        r=self.read(rel)
        return {'sha256':digest(r[0]),'mode':r[1]} if r else None
    def write(self,rel,data,mode,expected):
        with self.parent(rel,True) as (fd,name):
            if self.state(rel)!=expected: raise Error('Archivo cambió desde la aprobación: '+rel,'changed')
            tmp='.omapacks-'+uuid.uuid4().hex
            out=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode,dir_fd=fd)
            try:
                with os.fdopen(out,'wb') as f: f.write(data); f.flush(); os.fsync(f.fileno()); os.fchmod(f.fileno(),mode)
                # Verify again immediately before rename. The directory descriptor pins the parent.
                if self.state(rel)!=expected: raise Error('Archivo cambió durante la escritura: '+rel,'changed')
                os.replace(tmp,name,src_dir_fd=fd,dst_dir_fd=fd); os.fsync(fd)
            finally:
                try: os.unlink(tmp,dir_fd=fd)
                except FileNotFoundError: pass
    def remove(self,rel,expected):
        with self.parent(rel) as (fd,name):
            if self.state(rel)!=expected: raise Error('Archivo cambió antes de retirarlo: '+rel,'changed')
            os.unlink(name,dir_fd=fd); os.fsync(fd)

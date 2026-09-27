from __future__ import annotations
import io, json, os, re, shutil, subprocess, tarfile, tempfile
from pathlib import Path
from .util import Error, atomic, canonical, digest, relative, secure_path, clean, Runner
from .manifest import load, fields
from .github import repository

MAX_FILES = 4096
MAX_UNPACKED = 128 * 1024 * 1024

def unpack(data, destination, expected=None, modes=None):
    dest = Path(destination); entries = {}; total = 0; seen=set()
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:*') as tar:
            for index,m in enumerate(tar):
                if index>=MAX_FILES: raise Error('Demasiados archivos en el paquete')
                name=m.name.rstrip('/') if m.isdir() else m.name
                relative(name)
                if name in seen or m.mode & 0o7000: raise Error('Archivo de entrega duplicado o privilegiado')
                seen.add(name)
                if m.isdir(): continue
                if not m.isfile(): raise Error('Archivo de entrega no regular')
                if modes is not None: modes[name]=0o755 if m.mode & 0o111 else 0o644
                total += m.size
                if total > MAX_UNPACKED or m.size > 16*1024*1024: raise Error('Contenido extraído demasiado grande')
                content = tar.extractfile(m).read()
                if len(content) != m.size: raise Error('Archivo truncado')
                entries[m.name] = content
    except (tarfile.TarError, EOFError, OSError) as e: raise Error('Archivo comprimido inválido', 'integrity') from e
    if expected is not None and {n:digest(b) for n,b in entries.items()} != expected:
        raise Error('Los recursos no coinciden con el índice firmado', 'integrity')
    for name, content in entries.items(): atomic(secure_path(dest, name), content, 0o644)
    return entries

def verify(directory, allowed_signers, identity=None):
    directory = Path(directory)
    index = (directory / 'omapacks.json').read_bytes()
    if len(index) > 2*1024*1024: raise Error('Índice demasiado grande')
    result = subprocess.run(['ssh-keygen','-Y','verify','-f',str(allowed_signers),'-I','omapacks-release','-n','omapacks-v1','-s',str(directory/'omapacks.json.sig')], input=index, capture_output=True)
    if result.returncode: raise Error('Firma inválida o publicador no autorizado', 'signature')
    try:
        meta = json.loads(index)
        fields(meta, ('schema','repository','tag','content_id','version','archive_sha256','files'), ('schema','repository','tag','content_id','version','archive_sha256','files'))
        if meta['schema'] != 1: raise Error('Índice incompatible')
        repository(meta['repository'])
        if identity and (meta['repository'].lower() != identity['repository'].lower() or meta['tag'] != identity['tag']): raise Error('Firma de otra release o repositorio', 'signature')
        if (directory/'omapacks.tar.gz').stat().st_size>64*1024*1024: raise Error('Entrega comprimida demasiado grande')
        payload = (directory/'omapacks.tar.gz').read_bytes()
        if digest(payload) != meta['archive_sha256']: raise Error('Hash del paquete inválido', 'integrity')
        if not isinstance(meta['files'],dict): raise Error('Índice de recursos inválido')
        dest = directory/'content'
        if dest.exists(): shutil.rmtree(dest)
        unpack(payload, dest, meta['files'])
        manifest = load(dest/'pack.toml')
        if manifest['id'] != meta['content_id'] or manifest['version'] != meta['version']: raise Error('Identidad del manifiesto distinta del índice', 'integrity')
        for f in manifest.get('files', []):
            if f['source'] not in meta['files']: raise Error('Recurso declarado ausente')
        return manifest, meta
    except (KeyError, TypeError, ValueError, OSError) as e: raise Error('Entrega inválida: ' + clean(str(e)), 'integrity') from e

SECRET = re.compile(rb'(-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|(?:password|token|secret)\s*[=:]\s*["\x27]?[A-Za-z0-9_+/=-]{12,})', re.I)
BANNED = {'cookies','history','id_rsa','id_ed25519','.env','prod.keys','title.keys','saves','roms','firmware','bios','node_modules','.git','credentials','documents'}

def inspect_content(source):
    source = Path(source); manifest = load(source/'pack.toml'); entries = {}
    allowed = {'pack.toml','NOTES.md'} | {f['source'] for f in manifest.get('files', [])}
    for p in sorted(source.rglob('*')):
        rel = p.relative_to(source).as_posix()
        if p.is_symlink(): raise Error('No se publican enlaces: ' + rel)
        if any(x.lower() in BANNED for x in p.relative_to(source).parts): raise Error('Posible contenido personal o secreto: ' + rel)
        if p.is_dir(): continue
        if not p.is_file() or p.stat().st_nlink != 1: raise Error('Solo archivos propios regulares')
        if rel not in allowed: raise Error('Archivo no declarado; no se exporta todo el directorio: ' + rel)
        data = p.read_bytes()
        if len(data) > 16*1024*1024 or SECRET.search(data): raise Error('Posible secreto o archivo demasiado grande: ' + rel)
        if b'\x00' in data: raise Error('Contenido binario no admitido en el pack; declara dependencias externas')
        entries[rel] = data
    if not set(f['source'] for f in manifest.get('files', [])) <= set(entries): raise Error('Faltan recursos declarados')
    for f in manifest.get('files',[]):
        if f.get('kind')=='omarchy_menu':
            from .content_menu import validate
            validate(entries[f['source']].decode())
        elif f.get('kind')=='xdg_defaults':
            from .preferences import validate
            validate(entries[f['source']].decode(),manifest.get('packages',[]))
    return manifest, entries

def build(source, output, repo, tag, key):
    repository(repo)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,100}', tag): raise Error('Etiqueta inválida')
    manifest, entries = inspect_content(source)
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        for name, data in sorted(entries.items()):
            info = tarfile.TarInfo(name); info.size=len(data); info.mode=0o644; info.mtime=0
            tar.addfile(info, io.BytesIO(data))
    payload = buf.getvalue()
    meta = {'schema':1,'repository':repo,'tag':tag,'content_id':manifest['id'],'version':manifest['version'],'archive_sha256':digest(payload),'files':{n:digest(b) for n,b in entries.items()}}
    atomic(output/'omapacks.tar.gz', payload, 0o644); atomic(output/'omapacks.json', canonical(meta), 0o644)
    sig = output/'omapacks.json.sig'
    if sig.exists(): sig.unlink()
    Runner().run(['ssh-keygen','-Y','sign','-f',str(Path(key).absolute()),'-n','omapacks-v1',str(output/'omapacks.json')])
    notes = entries.get('NOTES.md', (f"Configuración {manifest['version']}\n").encode())
    atomic(output/'NOTES.md', notes, 0o644)
    return meta

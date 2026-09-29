from __future__ import annotations
import contextlib, fcntl, hashlib, json, os, re, stat, subprocess, tempfile, unicodedata
from pathlib import Path, PurePosixPath

class Error(Exception):
    def __init__(self, message, kind='validation'):
        super().__init__(message)
        self.kind = kind

def clean(value, multiline=True):
    text = str(value or '')[:100000]
    text = re.sub(r'\x1b\][^\x07]*(?:\x07|\x1b\\)', '', text)
    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text)
    return ''.join(c for c in text if (c == '\n' and multiline) or (not unicodedata.category(c).startswith('C') and c not in '\r\t'))

def digest(data): return hashlib.sha256(data).hexdigest()
def canonical(data): return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
def read_json(path, default=None):
    try: return json.loads(Path(path).read_text())
    except FileNotFoundError: return default

def atomic(path, data, mode=0o600):
    # Use the same no-follow descriptor traversal for state, caches and managed files.
    from .fs import Files
    path=Path(path).absolute(); fs=Files(path.parent)
    fs.write(path.name,data if isinstance(data,bytes) else data.encode(),mode,fs.state(path.name))

def save_json(path, value): atomic(path, json.dumps(value, indent=2, ensure_ascii=False) + '\n')
def relative(value):
    if not isinstance(value, str) or not value or '\\' in value or clean(value, False) != value:
        raise Error('Ruta inválida')
    p = PurePosixPath(value)
    if p.is_absolute() or any(x in ('..', '.', '') for x in value.split('/')):
        raise Error('Ruta fuera del ámbito permitido: ' + clean(value))
    return value

def secure_path(root, rel):
    root = Path(root).absolute()
    relative(rel)
    p = root / rel
    # Never follow any component, including a replaced root.
    for parent in [*reversed(p.parents), p]:
        if parent.is_symlink(): raise Error('Enlace simbólico rechazado: ' + str(parent))
    return p

def file_state(path):
    try:
        st = Path(path).lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1: raise Error('Solo archivos regulares sin enlaces: ' + str(path))
        if st.st_uid != os.getuid(): raise Error('Propietario inesperado: ' + str(path))
        if st.st_mode & 0o022: raise Error('Archivo escribible por otros: ' + str(path))
        if st.st_size > 16 * 1024 * 1024: raise Error('Archivo demasiado grande')
        return {'sha256': digest(Path(path).read_bytes()), 'mode': stat.S_IMODE(st.st_mode)}
    except FileNotFoundError: return None

class Runner:
    def run(self, argv, *, input=None, check=True, timeout=60, cwd=None, interactive=False, env=None):
        if any(not isinstance(x, str) or '\x00' in x for x in argv): raise Error('Argumentos inválidos')
        try:
            p = subprocess.run(argv, input=input, text=True, capture_output=not interactive,
                               timeout=timeout, cwd=cwd, env=env if env is not None else {**os.environ, "LC_ALL":"C"})
        except (OSError, subprocess.TimeoutExpired) as e:
            raise Error(f'No se pudo ejecutar {argv[0]} ({type(e).__name__})', 'provider') from e
        if check and p.returncode:
            from .diagnostics import safe
            raise Error(f'{argv[0]} terminó con {p.returncode}: {safe(p.stderr or p.stdout or "cancelado o rechazado")[-2500:]}', 'provider')
        return p

@contextlib.contextmanager
def lock(directory):
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    p = secure_path(directory, 'operation.lock')
    fd = os.open(p, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise Error('Hay otra operación de OmaPacks en curso', 'locked')
        yield
    finally: os.close(fd)

def require_user():
    if os.geteuid() == 0: raise Error('OmaPacks debe ejecutarse como usuario normal; eleva solo operaciones concretas.')

def version(v):
    m = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)(?:[-+][A-Za-z0-9.]+)?', v)
    if not m: raise Error('Versión inválida: ' + clean(v))
    return tuple(map(int, m.groups()))

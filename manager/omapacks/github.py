"""Small GitHub Releases client. No Git, latest resolution or third-party tokens."""
from __future__ import annotations
import datetime as dt, http.client, json, os, re, socket, subprocess, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path
from .util import Error, atomic, canonical, clean, digest, read_json, save_json

ASSETS = ('omapacks.json', 'omapacks.json.sig', 'omapacks.tar.gz')

def repository(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*', value) or '..' in value:
        raise Error('Repositorio esperado: propietario/repositorio')
    return value

def published(value):
    try:
        d = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        return d.timestamp() if d.tzinfo else float('-inf')
    except (ValueError, AttributeError, TypeError): return float('-inf')

def sort_releases(rows):
    return sorted((r for r in rows if not r.get('draft')), key=lambda r: (-published(r.get('published_at')), -int(r['id'])))

def asset_identity(a):
    return {k: a.get(k) for k in ('id', 'name', 'size', 'updated_at', 'digest')}

def pin(repo, release):
    assets=release.get('assets',[])
    if not isinstance(assets,list) or any(not isinstance(a,dict) or not isinstance(a.get('name'),str) for a in assets): raise Error('Release existente con metadata de assets inválida', 'incompatible')
    names = [a['name'] for a in assets]
    if any(names.count(n) != 1 for n in ASSETS):
        raise Error('Release no instalable: requiere exactamente omapacks.json, omapacks.json.sig y omapacks.tar.gz', 'incompatible')
    for a in assets:
        if a['name'] in ASSETS and (type(a.get('id')) is not int or a['id']<=0 or type(a.get('size')) is not int or a['size']<=0): raise Error('Asset sin identidad/tamaño válidos', 'incompatible')
    return {'repository': repo, 'release_id': release['id'], 'tag': release['tag_name'],
            'published_at': release.get('published_at'), 'assets': [asset_identity(next(a for a in release['assets'] if a['name'] == n)) for n in ASSETS]}

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl): return None

class Transport:
    def __init__(self, token=None, timeout=15, attempts=3):
        if token and (len(token)>4096 or not all(33<=ord(c)<=126 for c in token)): raise Error('Credencial con formato inválido; no se muestra su contenido', 'auth')
        self.token, self.timeout, self.attempts = token, timeout, attempts
        self.opener = urllib.request.build_opener(NoRedirect())

    def get(self, url, *, binary=False, limit=16*1024*1024):
        start = time.monotonic(); redirects = 0
        original_host = urllib.parse.urlsplit(url).hostname
        for attempt in range(self.attempts):
            current = url
            while True:
                u = urllib.parse.urlsplit(current)
                if u.scheme != 'https' or u.username or u.password or u.port not in (None, 443):
                    raise Error('Descarga rechazada: se requiere HTTPS sin credenciales en URL', 'network')
                headers = {'User-Agent': 'OmaPacks/0.1', 'Accept': 'application/octet-stream' if binary else 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'}
                # Never attach credentials to redirected domains, nor vendor URLs.
                if self.token and original_host == 'api.github.com' and u.hostname == original_host:
                    headers['Authorization'] = 'Bearer ' + self.token
                try:
                    with self.opener.open(urllib.request.Request(current, headers=headers), timeout=self.timeout) as r:
                        chunks = []; total = 0
                        while True:
                            if time.monotonic() - start > 90: raise Error('Descarga superó el tiempo máximo', 'network')
                            chunk = r.read(min(65536, limit + 1 - total))
                            if not chunk: break
                            total += len(chunk)
                            if total > limit: raise Error('Respuesta demasiado grande', 'network')
                            chunks.append(chunk)
                        data = b''.join(chunks)
                        if r.headers.get('Content-Length') and len(data) != int(r.headers['Content-Length']):
                            raise Error('Descarga interrumpida o incompleta', 'network')
                        return data, dict(r.headers)
                except urllib.error.HTTPError as e:
                    e.close()
                    if e.code in (301,302,303,307,308):
                        redirects += 1
                        if redirects > 5: raise Error('Demasiadas redirecciones', 'network')
                        current = urllib.parse.urljoin(current, e.headers.get('Location', ''))
                        # Cross-domain pagination is never followed by the API client.
                        continue
                    if e.code == 401: raise Error('Autenticación rechazada. Usa acceso propio de lectura.', 'auth') from None
                    if e.code in (403,429):
                        rate = e.code == 429 or e.headers.get('X-RateLimit-Remaining') == '0' or e.headers.get('Retry-After')
                        raise Error('Límite de solicitudes; inténtalo más tarde.' if rate else 'Permisos insuficientes para este repositorio.', 'rate_limit' if rate else 'permissions') from None
                    if e.code == 404: raise Error('Repositorio o asset inexistente o inaccesible (GitHub puede ocultar repositorios privados).', 'not_found') from None
                    if e.code < 500: raise Error(f'GitHub devolvió HTTP {e.code}', 'network') from None
                    break
                except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, http.client.HTTPException): break
            if attempt + 1 < self.attempts: time.sleep(0.2 * 2**attempt)
        raise Error('Fallo de red después de reintentos acotados', 'network')

def own_token():
    token = os.environ.get('OMAPACKS_GITHUB_TOKEN')
    if token: return token
    # Use the local user's own authorized gh session; never export it or log stderr.
    try:
        p = subprocess.run(['gh','auth','token','--hostname','github.com'],capture_output=True,text=True,timeout=5)
        return p.stdout.strip() if p.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired): return None

class GitHub:
    def __init__(self, repo, cache, transport=None, max_pages=100):
        self.repo = repository(repo); self.base = 'https://api.github.com/repos/' + self.repo
        self.cache = Path(cache) / (digest(self.repo.encode()) + '.json')
        self.transport = transport or Transport(own_token())
        self.max_pages = max_pages

    def json(self, url):
        data, headers = self.transport.get(url)
        try: return json.loads(data), headers
        except (ValueError, UnicodeError): raise Error('GitHub devolvió datos inválidos', 'network') from None

    def releases(self):
        rows = []; seen = set(); url = self.base + '/releases?per_page=100&page=1'; error = None
        for page in range(self.max_pages):
            try:
                result, headers = self.json(url)
                if not isinstance(result, list) or any(not isinstance(r, dict) or not isinstance(r.get('id'), int) or not isinstance(r.get('tag_name'), str) for r in result):
                    raise Error('Respuesta de releases inválida', 'network')
                for r in result:
                    if r['id'] not in seen: rows.append(r); seen.add(r['id'])
                links = headers.get('Link', headers.get('link', ''))
                match = re.search(r'<([^>]+)>;\s*rel="next"', links)
                if not match: break
                url = match.group(1)
                u = urllib.parse.urlsplit(url)
                if u.scheme != 'https' or u.netloc != 'api.github.com' or u.path != urllib.parse.urlsplit(self.base).path + '/releases':
                    raise Error('Paginación rechazada: origen o ruta inesperados', 'network')
            except Error as e:
                error = e; break
        else: error = Error('Lista incompleta: límite de paginación alcanzado', 'incomplete')
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        if error and not rows:
            cached = read_json(self.cache)
            if cached and error.kind in ('network', 'rate_limit'):
                return {**cached, 'cached': True, 'warning': str(error), 'error_kind': error.kind}
            raise error
        data = {'releases': sort_releases(rows), 'fetched_at': now, 'complete': error is None, 'cached': False,
                'warning': str(error) if error else None, 'error_kind': error.kind if error else None}
        if not error: save_json(self.cache, data)
        return data

    def release(self, release_id):
        if not isinstance(release_id, int) or release_id <= 0: raise Error('ID de release inválido')
        row, _ = self.json(self.base + '/releases/' + str(release_id))
        if row.get('draft') or row.get('id') != release_id: raise Error('La release ya no está publicada', 'changed')
        return row

    def verify_pin(self, identity):
        if pin(self.repo, self.release(identity['release_id'])) != identity:
            raise Error('La release cambió desde la selección; vuelve a consultar y revisar.', 'changed')

    def download(self, identity, directory):
        self.verify_pin(identity)
        directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
        hashes = {}
        for a in identity['assets']:
            if not isinstance(a['id'], int) or a['size'] is None or a['size'] < 0: raise Error('Asset inválido')
            limit = 64*1024*1024 if a['name'].endswith('.tar.gz') else 2*1024*1024
            if a['size'] > limit: raise Error('Asset supera el límite admitido')
            data, _ = self.transport.get(self.base + '/releases/assets/' + str(a['id']), binary=True, limit=limit)
            if len(data) != a['size']: raise Error('Descarga incompleta; tamaño distinto del asset seleccionado', 'integrity')
            sha = digest(data)
            if a.get('digest') and a['digest'] != 'sha256:' + sha: raise Error('Hash del asset inválido', 'integrity')
            atomic(directory / a['name'], data); hashes[a['name']] = sha
        self.verify_pin(identity)
        return hashes

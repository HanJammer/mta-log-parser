"""
Security helpers for the web app: persistent secret key, CSRF guard, response headers and
in-memory login throttling.
"""
import logging
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional, Tuple

from mlp import settings

log = logging.getLogger(__name__)

SECRET_KEY_FILE = 'secret_key'

#: Methods that change state and therefore need the CSRF headers.
STATE_CHANGING_METHODS = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})
CSRF_HEADER = 'X-Requested-With'
CSRF_HEADER_VALUE = 'mlp'


def _read_key(fpath: str, attempts: int = 50) -> str:
    """Read a key file, waiting a moment if another worker is still writing it."""
    for _ in range(attempts):
        with open(fpath, 'r', encoding='ascii') as fh:
            key = fh.read().strip()
        if key:
            return key
        time.sleep(0.05)
    raise RuntimeError(f'Secret key file {fpath} is empty')


def load_or_create_secret_key(instance_path: str) -> str:
    """
    Return the secret key stored in ``<instance_path>/secret_key``, creating it atomically if it does
    not exist yet. Several hypercorn workers may start at the same time; the key is written to a
    temporary file and hard-linked into place, so exactly one key wins and every worker reads it.
    """
    os.makedirs(instance_path, mode=0o700, exist_ok=True)
    fpath = os.path.join(instance_path, SECRET_KEY_FILE)
    if os.path.exists(fpath):
        return _read_key(fpath)

    key = secrets.token_urlsafe(48)
    tmp = os.path.join(instance_path, f'.{SECRET_KEY_FILE}.{os.getpid()}.{secrets.token_hex(4)}')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='ascii') as fh:
            fh.write(key)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.link(tmp, fpath)          # fails if another worker won the race
        except FileExistsError:
            pass
        except OSError:
            # Filesystems without hard links: exclusive rename (fails on Windows if it exists;
            # on POSIX we re-check existence first, the remaining race is harmless in practice).
            if not os.path.exists(fpath):
                try:
                    os.rename(tmp, fpath)
                except FileExistsError:
                    pass
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return _read_key(fpath)


def resolve_secret_key(configured: Optional[str] = None, instance_path: Optional[str] = None) -> str:
    """
    Return the secret key to sign session cookies with. An empty or well-known default ``SECRET_KEY``
    is never used: a random key is generated and persisted instead (with a loud warning).
    """
    configured = settings.secret_key if configured is None else configured
    instance_path = settings.instance_path if instance_path is None else instance_path
    if configured and configured not in settings.insecure_secret_keys and len(configured) >= 16:
        return configured
    if configured and configured not in settings.insecure_secret_keys:
        log.warning('SECRET_KEY is shorter than 16 characters - ignoring it.')
    key = load_or_create_secret_key(instance_path)
    log.warning(
        '!!! SECRET_KEY is not set (or uses an insecure default). Using the generated key stored in %s. '
        'Set a long random SECRET_KEY in your .env to silence this warning. !!!',
        os.path.join(instance_path, SECRET_KEY_FILE)
    )
    return key


def csrf_ok(method: str, headers, mimetype: str) -> bool:
    """State-changing requests must be JSON and carry ``X-Requested-With: mlp``."""
    if method.upper() not in STATE_CHANGING_METHODS:
        return True
    if headers.get(CSRF_HEADER, '') != CSRF_HEADER_VALUE:
        return False
    return (mimetype or '').lower() == 'application/json'


SECURITY_HEADERS = {
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'Referrer-Policy': 'same-origin',
}

#: Content-Security-Policy sent with every response (the SPA must not need inline scripts or other origins).
SPA_CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
    "connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)


class LoginThrottle:
    """
    Simple sliding-window login throttling, kept in memory (per worker process).

    A login attempt is refused when the (IP, login) pair or the IP alone has too many failures in
    the last ``window`` seconds. A successful login clears the failures of its (IP, login) pair.
    """

    def __init__(self, max_failures: int = None, max_failures_ip: int = None, window: int = None):
        self.max_failures = settings.login_max_failures if max_failures is None else max_failures
        self.max_failures_ip = settings.login_max_failures_ip if max_failures_ip is None else max_failures_ip
        self.window = settings.login_throttle_window if window is None else window
        self._pairs: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)
        self._ips: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, dq: Deque[float], now: float):
        while dq and dq[0] <= now - self.window:
            dq.popleft()

    def retry_after(self, ip: str, login: str) -> int:
        """Seconds until the next attempt is allowed (0 = allowed now)."""
        now = time.monotonic()
        key = (ip or '', (login or '').lower())
        with self._lock:
            waits = []
            for dq, limit in ((self._pairs.get(key), self.max_failures), (self._ips.get(ip or ''), self.max_failures_ip)):
                if dq is None:
                    continue
                self._prune(dq, now)
                if limit > 0 and len(dq) >= limit:
                    waits.append(int(dq[0] + self.window - now) + 1)
            return max(waits) if waits else 0

    def failure(self, ip: str, login: str):
        now = time.monotonic()
        with self._lock:
            self._pairs[(ip or '', (login or '').lower())].append(now)
            self._ips[ip or ''].append(now)
            if len(self._pairs) > 10000:      # bound memory use under a spray attack
                for k in [k for k, dq in self._pairs.items() if not dq or dq[-1] <= now - self.window]:
                    del self._pairs[k]

    def success(self, ip: str, login: str):
        with self._lock:
            self._pairs.pop((ip or '', (login or '').lower()), None)

    def reset(self):
        with self._lock:
            self._pairs.clear()
            self._ips.clear()

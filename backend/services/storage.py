# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
import os
import json
import time
import hmac
import hashlib
import secrets
import logging
import threading
from typing import Any, Optional, Dict

logger = logging.getLogger("storage_service")

# Try importing filelock; fallback to POSIX fcntl if unavailable
try:
    from filelock import FileLock
    HAS_FILELOCK = True
except ImportError:
    HAS_FILELOCK = False
    try:
        import fcntl
        HAS_FCNTL = True
    except ImportError:
        HAS_FCNTL = False


class FallbackFileLock:
    """Fallback file lock using fcntl for POSIX systems when filelock is not installed."""
    def __init__(self, lock_file: str, timeout: float = 15.0):
        self.lock_file = lock_file
        self.timeout = timeout
        self._thread_lock = threading.RLock()
        self._local = threading.local()

    def acquire_lock(self, timeout: Optional[float] = None):
        t = self.timeout if timeout is None else timeout
        start = time.time()
        # 1. Thread-level synchronization
        acquired = self._thread_lock.acquire(timeout=t)
        if not acquired:
            raise TimeoutError(f"Thread timeout acquiring lock on {self.lock_file} after {t}s")

        try:
            depth = getattr(self._local, 'depth', 0)
            if depth > 0:
                self._local.depth = depth + 1
                return self

            os.makedirs(os.path.dirname(os.path.abspath(self.lock_file)), exist_ok=True)
            fd = open(self.lock_file, 'a+')
            self._local.fd = fd
            if HAS_FCNTL:
                while True:
                    try:
                        import fcntl
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        self._local.depth = 1
                        return self
                    except (IOError, OSError):
                        if time.time() - start > t:
                            logger.warning(f"Timeout acquiring FallbackFileLock on {self.lock_file} after {t}s")
                            raise TimeoutError(f"Could not acquire lock on {self.lock_file} within {t}s")
                        time.sleep(0.01)
            self._local.depth = 1
            return self
        except Exception:
            fd = getattr(self._local, 'fd', None)
            if fd:
                try:
                    fd.close()
                except Exception:
                    pass
                self._local.fd = None
            self._thread_lock.release()
            raise

    def __enter__(self):
        return self.acquire_lock(self.timeout)

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            depth = getattr(self._local, 'depth', 0)
            if depth > 1:
                self._local.depth = depth - 1
                return
            
            self._local.depth = 0
            fd = getattr(self._local, 'fd', None)
            try:
                if fd:
                    if HAS_FCNTL:
                        try:
                            import fcntl
                            fcntl.flock(fd, fcntl.LOCK_UN)
                        except Exception:
                            pass
                    try:
                        fd.close()
                    except Exception:
                        pass
                    self._local.fd = None
            except Exception:
                pass
        finally:
            self._thread_lock.release()

    def acquire(self, *args, **kwargs):
        timeout = kwargs.get("timeout")
        return self.acquire_lock(timeout)

    def release(self, *args, **kwargs):
        return self.__exit__(None, None, None)


class TimedFileLock:
    """Wrapper around FileLock to ensure timeout logging, consistent TimeoutError and prevent worker starvation."""
    def __init__(self, base_lock: Any, lock_file: str, timeout: float = 15.0):
        self.base_lock = base_lock
        self.lock_file = lock_file
        self._timeout = timeout

    @property
    def timeout(self) -> float:
        return getattr(self.base_lock, "timeout", self._timeout)

    @timeout.setter
    def timeout(self, val: float):
        self._timeout = val
        if hasattr(self.base_lock, "timeout"):
            self.base_lock.timeout = val

    def __enter__(self):
        try:
            if hasattr(self.base_lock, "acquire_lock"):
                return self.base_lock.acquire_lock(self._timeout)
            return self.base_lock.__enter__()
        except Exception as e:
            logger.warning(f"FileLock acquisition timeout ({self.timeout}s) on {self.lock_file}: {e}")
            if not isinstance(e, TimeoutError):
                raise TimeoutError(f"FileLock acquisition timeout on {self.lock_file} after {self.timeout}s: {e}") from e
            raise

    def __exit__(self, exc_type, exc_val, exc_tb):
        return self.base_lock.__exit__(exc_type, exc_val, exc_tb)

    def acquire(self, *args, **kwargs):
        try:
            if hasattr(self.base_lock, "acquire_lock"):
                timeout = kwargs.get("timeout", self._timeout)
                return self.base_lock.acquire_lock(timeout)
            return self.base_lock.acquire(*args, **kwargs)
        except Exception as e:
            logger.warning(f"FileLock acquire timeout on {self.lock_file}: {e}")
            if not isinstance(e, TimeoutError):
                raise TimeoutError(f"FileLock timed out on {self.lock_file}: {e}") from e
            raise

    def release(self, *args, **kwargs):
        return self.base_lock.release(*args, **kwargs)


_LOCKS_REGISTRY: Dict[str, Any] = {}
_REGISTRY_LOCK = threading.Lock()


def get_file_lock(file_path: str, timeout: float = 15.0):
    """Returns a process-safe file lock object, reusing instances for thread re-entrancy."""
    lock_file = os.path.abspath(f"{file_path}.lock")
    with _REGISTRY_LOCK:
        if lock_file not in _LOCKS_REGISTRY:
            if HAS_FILELOCK:
                _LOCKS_REGISTRY[lock_file] = FileLock(lock_file, timeout=timeout)
            else:
                _LOCKS_REGISTRY[lock_file] = FallbackFileLock(lock_file, timeout=timeout)
        base_lock = _LOCKS_REGISTRY[lock_file]
        base_lock.timeout = timeout
        return TimedFileLock(base_lock, lock_file, timeout=timeout)


def safe_json_write(file_path: str, data: Any, timeout: float = 15.0) -> bool:
    """
    Atomic and Process-Safe JSON write:
    1. Acquires cross-process FileLock to prevent race conditions / lost updates.
    2. Writes data to a unique temporary file with ensure_ascii=False.
    3. Atomically replaces destination file via os.replace.
    """
    temp_file = f"{file_path}.tmp.{os.getpid()}_{int(time.time() * 1000)}"
    target_dir = os.path.dirname(os.path.abspath(file_path))
    if target_dir:
        os.makedirs(target_dir, exist_ok=True)

    try:
        with get_file_lock(file_path, timeout=timeout):
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(temp_file, file_path)
            return True
    except Exception as e:
        logger.warning(f"Error or timeout safe writing {file_path}: {e}")
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass
        return False


def safe_json_read(file_path: str, default: Any = None, timeout: float = 15.0) -> Any:
    """
    Process-safe JSON read under a shared file lock.
    Returns default if file doesn't exist or is corrupted / lock timed out.
    """
    if not os.path.exists(file_path):
        return default

    try:
        with get_file_lock(file_path, timeout=timeout):
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Error or timeout safe reading {file_path}: {e}")
        return default


def is_runtime_json_sync_enabled() -> bool:
    """
    Checks whether continuous runtime JSON dual-writing is enabled.
    Defaults to FALSE (Single Source of Truth: SQLite WAL).
    Only enabled if explicitly set via ENABLE_RUNTIME_JSON_SYNC=true in .env.
    """
    return os.getenv("ENABLE_RUNTIME_JSON_SYNC", "false").lower() in ("true", "1")


# ==========================================
# PIN HASHING & VERIFICATION (OWASP PBKDF2)
# ==========================================
PBKDF2_ITERATIONS = 100000
HASH_PREFIX = "pbkdf2_sha256"


def hash_pin(pin: str) -> str:
    """
    Hash a 4-6 digit staff PIN using PBKDF2-HMAC-SHA256 with cryptographically secure random salt.
    Format: pbkdf2_sha256$100000$<salt_hex>$<hash_hex>
    """
    clean_pin = str(pin).strip()
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        'sha256',
        clean_pin.encode('utf-8'),
        salt.encode('utf-8'),
        PBKDF2_ITERATIONS
    )
    return f"{HASH_PREFIX}${PBKDF2_ITERATIONS}${salt}${key.hex()}"


def verify_pin(plain_pin: str, stored_pin: str) -> bool:
    """
    Verify staff PIN against stored hash or legacy plaintext.
    Uses constant-time comparison to protect against timing attacks.
    """
    if not plain_pin or not stored_pin:
        return False

    clean_plain = str(plain_pin).strip()
    clean_stored = str(stored_pin).strip()

    # Case 1: Stored is PBKDF2 hash
    if clean_stored.startswith(f"{HASH_PREFIX}$"):
        parts = clean_stored.split("$")
        if len(parts) == 4:
            _, iterations_str, salt, target_hash = parts
            try:
                iterations = int(iterations_str)
                computed_key = hashlib.pbkdf2_hmac(
                    'sha256',
                    clean_plain.encode('utf-8'),
                    salt.encode('utf-8'),
                    iterations
                )
                return hmac.compare_digest(computed_key.hex(), target_hash)
            except Exception:
                return False

    # Case 2: Legacy Plaintext PIN (for seamless migration)
    return hmac.compare_digest(clean_plain, clean_stored)


def needs_rehash(stored_pin: str) -> bool:
    """Returns True if the stored PIN is plaintext or outdated hash format."""
    if not stored_pin:
        return False
    return not str(stored_pin).strip().startswith(f"{HASH_PREFIX}$")

# -*- coding: utf-8 -*-
"""
Pytest Master Configuration & Test Sandbox Isolation
Ensures 100% isolation of test execution:
- Pre-configures testing environment variables (JWT_SECRET_KEY, TESTING, MOCK_TELEGRAM)
- Creates a temporary data sandbox for all read/write operations during testing
- Guarantees zero pollution or mutation to git-tracked files in data/
"""

import os
import sys
import shutil
import tempfile
import atexit
import pytest

# 1. Base Project Paths
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_TESTS_DIR)
_BACKEND_DIR = os.path.join(_PROJECT_ROOT, "backend")
_REAL_DATA_DIR = os.path.join(_PROJECT_ROOT, "data")

if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

# 2. Mandatory Test Environment Variables
os.environ["TESTING"] = "1"
os.environ["MOCK_TELEGRAM"] = "1"
if not os.environ.get("JWT_SECRET_KEY"):
    os.environ["JWT_SECRET_KEY"] = "test_secret_key_12345678901234567890_fnbops_secure"
if not os.environ.get("POS_SECRET"):
    os.environ["POS_SECRET"] = "ci_test_super_secure_pos_secret_key_32_characters_long"

# 3. Create Sandbox Data Directory BEFORE any module imports during collection
import glob
for pat in [
    os.path.join(_TESTS_DIR, "mock_*.json*"),
    os.path.join(_TESTS_DIR, "mock_*.lock*"),
    os.path.join(_REAL_DATA_DIR, "*.lock")
]:
    for f in glob.glob(pat):
        try:
            os.remove(f)
        except Exception:
            pass

_SANDBOX_DATA_DIR = tempfile.mkdtemp(prefix="fnbops_test_sandbox_")

_IGNORED_DATA_DIRS = {"backups", "outbox", "zalo_session", "__pycache__"}
_IGNORED_DATA_SUFFIXES = (".lock", ".log", ".db", ".db-wal", ".db-shm", ".db-journal")

if os.path.exists(_REAL_DATA_DIR):
    for item in os.listdir(_REAL_DATA_DIR):
        if item in _IGNORED_DATA_DIRS or item == "vapid_keys.json":
            continue
        if item.endswith(_IGNORED_DATA_SUFFIXES) or ".db." in item or ".bak" in item:
            continue
        src_path = os.path.join(_REAL_DATA_DIR, item)
        dst_path = os.path.join(_SANDBOX_DATA_DIR, item)
        if os.path.isdir(src_path):
            shutil.copytree(src_path, dst_path)
        else:
            shutil.copy2(src_path, dst_path)

os.environ["DATA_DIR"] = _SANDBOX_DATA_DIR
os.environ["DATABASE_PATH"] = os.path.join(_SANDBOX_DATA_DIR, "fnbop.db")
os.environ["AUTH_FILE"] = os.path.join(_SANDBOX_DATA_DIR, "staff_auth.json")
os.environ["APPROVALS_FILE"] = os.path.join(_SANDBOX_DATA_DIR, "shift_approvals.json")
os.environ["ROSTER_FILE"] = os.path.join(_SANDBOX_DATA_DIR, "roster_schedule.json")
os.environ["EVALUATIONS_FILE"] = os.path.join(_SANDBOX_DATA_DIR, "eval_logs.json")
if os.path.exists(os.path.join(_SANDBOX_DATA_DIR, "data.json")):
    os.environ["DATA_FILE"] = os.path.join(_SANDBOX_DATA_DIR, "data.json")
else:
    os.environ["DATA_FILE"] = os.path.join(_PROJECT_ROOT, "data", "data.json")


def _cleanup_sandbox():
    try:
        shutil.rmtree(_SANDBOX_DATA_DIR, ignore_errors=True)
    except Exception:
        pass
    import glob
    for pat in [
        os.path.join(_TESTS_DIR, "mock_*.json*"),
        os.path.join(_TESTS_DIR, "mock_*.lock*"),
        os.path.join(_PROJECT_ROOT, "data", "*.lock")
    ]:
        for f in glob.glob(pat):
            try:
                os.remove(f)
            except Exception:
                pass


atexit.register(_cleanup_sandbox)

_PROTECTED_ENV_KEYS = (
    "DATA_DIR",
    "DATABASE_PATH",
    "AUTH_FILE",
    "APPROVALS_FILE",
    "ROSTER_FILE",
    "EVALUATIONS_FILE",
    "EVAL_LOGS_FILE",
    "DATA_FILE",
    "ENABLE_RUNTIME_JSON_SYNC",
    "TESTING",
    "MOCK_TELEGRAM",
)
_BASELINE_ENV = {k: os.environ.get(k) for k in _PROTECTED_ENV_KEYS}


@pytest.fixture(scope="module", autouse=True)
def _restore_sandbox_env_between_test_modules():
    """Prevent env-var leakage across test modules while preserving class-level setUpClass fixtures."""
    yield
    for k, baseline_val in _BASELINE_ENV.items():
        if baseline_val is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = baseline_val


def pytest_sessionfinish(session, exitstatus):
    """Teardown hook after all tests finish."""
    _cleanup_sandbox()

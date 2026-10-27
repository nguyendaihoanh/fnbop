# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
Database Connection & Management Layer (SQLite WAL Mode)
Provides connection pooling, checkpointing, and safe online backups.
"""

import os
import time
import sqlite3
import logging
import threading
import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger("db_service")

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PROJECT_DIR = os.path.dirname(_BASE_DIR)

if os.getenv("DATABASE_PATH"):
    DEFAULT_DB_PATH = os.getenv("DATABASE_PATH")
elif os.getenv("DATA_DIR"):
    DEFAULT_DB_PATH = os.path.join(os.getenv("DATA_DIR"), "fnbop.db")
elif _PROJECT_DIR and _PROJECT_DIR != "/" and os.path.exists(os.path.join(_PROJECT_DIR, "data")):
    DEFAULT_DB_PATH = os.path.join(_PROJECT_DIR, "data", "fnbop.db")
else:
    DEFAULT_DB_PATH = os.path.join(_BASE_DIR, "data", "fnbop.db")

DEFAULT_TENANT_ID = os.getenv("DEFAULT_TENANT_ID", "default")
DEFAULT_TENANT_NAME = "FnBOps Store Lounge"

_thread_local = threading.local()


def get_db_path() -> str:
    path = os.getenv("DATABASE_PATH") or DEFAULT_DB_PATH
    # Seamless backward compatibility: if target fnbop.db doesn't exist but legacy wfm.db exists, preserve data
    if not os.path.exists(path) and path.endswith("fnbop.db"):
        legacy_path = path[:-8] + "wfm.db"
        if os.path.exists(legacy_path):
            return legacy_path
    return path


def get_db_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """
    Creates and configures a high-performance SQLite connection with:
    - WAL Mode (Write-Ahead Logging) for concurrent reads/writes
    - Busy timeout of 30000ms to eliminate 'database is locked' errors
    - PRAGMA wal_autocheckpoint = 1000 pages for periodic WAL consolidation
    - Foreign key constraints enabled
    - Row factory enabled for dictionary-like access
    """
    path = db_path or get_db_path()
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    except Exception:
        path = os.path.join(_BASE_DIR, "data", "fnbop.db")
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA busy_timeout = 30000;")
    conn.execute("PRAGMA wal_autocheckpoint = 1000;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA temp_store = MEMORY;")
    conn.execute("PRAGMA cache_size = -64000;")
    return conn


def checkpoint_db(db_path: Optional[str] = None, mode: str = "PASSIVE") -> bool:
    """
    Executes PRAGMA wal_checkpoint to consolidate WAL log into main DB file.
    Modes: PASSIVE, FULL, RESTART, TRUNCATE. Default is PASSIVE.
    """
    valid_modes = {"PASSIVE", "FULL", "RESTART", "TRUNCATE"}
    target_mode = mode.upper() if mode and mode.upper() in valid_modes else "PASSIVE"
    try:
        conn = get_db_connection(db_path)
        cur = conn.cursor()
        cur.execute(f"PRAGMA wal_checkpoint({target_mode});")
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Failed to execute SQLite wal_checkpoint({target_mode}): {e}")
        return False


def cleanup_old_backups(backup_dir: str, retention_days: int = 30) -> List[str]:
    """
    Deletes SQLite backup files older than `retention_days` to prevent disk overflow on POS machine.
    Returns list of deleted file paths.
    """
    deleted_files = []
    if not os.path.exists(backup_dir):
        return deleted_files

    now = datetime.datetime.now()
    cutoff_time = now - datetime.timedelta(days=retention_days)

    try:
        for fname in os.listdir(backup_dir):
            if fname.endswith(".db") and "backup" in fname:
                fpath = os.path.join(backup_dir, fname)
                try:
                    file_mtime = datetime.datetime.fromtimestamp(os.path.getmtime(fpath))
                    if file_mtime < cutoff_time:
                        os.remove(fpath)
                        deleted_files.append(fpath)
                        logger.info(f"Cleaned up expired SQLite backup ({file_mtime}): {fpath}")
                except Exception as e:
                    logger.warning(f"Failed to inspect/delete old backup {fpath}: {e}")
    except Exception as e:
        logger.warning(f"Error scanning backup_dir {backup_dir}: {e}")

    return deleted_files


def safe_sqlite_backup(
    src_db_path: Optional[str] = None,
    backup_db_path: Optional[str] = None,
    retention_days: int = 30
) -> str:
    """
    Safely creates an online, atomic backup of SQLite in WAL mode using native sqlite3.Connection.backup API.
    Prevents corruptions and ensures active transactions in .db-wal are safely included without table locks.
    Automatically prunes backup files older than `retention_days`.
    """
    src_path = src_db_path or get_db_path()
    if not backup_db_path:
        backup_dir = os.path.join(os.path.dirname(src_path), "backups")
        os.makedirs(backup_dir, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_db_path = os.path.join(backup_dir, f"fnbops_backup_{timestamp}.db")
    else:
        backup_dir = os.path.dirname(os.path.abspath(backup_db_path))
        os.makedirs(backup_dir, exist_ok=True)

    with sqlite3.connect(src_path, timeout=30.0) as src_conn:
        with sqlite3.connect(backup_db_path, timeout=30.0) as dst_conn:
            src_conn.backup(dst_conn, pages=100, sleep=0.01)

    logger.info(f"SQLite WAL safe backup successfully created at: {backup_db_path}")

    # Prune expired backups according to retention policy
    if backup_dir and os.path.exists(backup_dir):
        cleanup_old_backups(backup_dir, retention_days=retention_days)

    return backup_db_path

# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
import os
import sys
import json
import time
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import ipaddress
from services.storage import safe_json_read, safe_json_write, get_file_lock
from services.roster_service import load_roster_data
from services.send_telegram import send_telegram_alert
from services.auth import normalize_str, load_staff_auth

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROJECT_DIR = os.path.dirname(_BASE_DIR)

if os.getenv("DATA_DIR"):
    DATA_DIR = os.getenv("DATA_DIR")
elif _PROJECT_DIR and _PROJECT_DIR != "/" and os.path.exists(os.path.join(_PROJECT_DIR, "data")):
    DATA_DIR = os.path.join(_PROJECT_DIR, "data")
else:
    DATA_DIR = os.path.join(_BASE_DIR, "data")

try:
    os.makedirs(DATA_DIR, exist_ok=True)
except Exception:
    DATA_DIR = os.path.join(_BASE_DIR, "data")
    os.makedirs(DATA_DIR, exist_ok=True)

HEARTBEAT_FILE = os.path.join(DATA_DIR, "pos_heartbeat.json")
LOGS_FILE = os.path.join(DATA_DIR, "attendance_logs.json")

_cached_cafe_ip = os.getenv("STORE_WIFI_IP", "127.0.0.1")


class AttendanceLogsProcessLock:
    """
    Cross-process and cross-thread lock for attendance_logs.json.
    Ensures complete Read-Modify-Write cycle protection across multiple workers and threads.
    """
    def __init__(self, timeout: float = 20.0):
        self.timeout = timeout
        self._thread_lock = threading.RLock()
        self._local = threading.local()

    def acquire_lock(self, timeout: Optional[float] = None):
        t = self.timeout if timeout is None else timeout
        start = time.time()
        # 1. Thread-level synchronization
        if not self._thread_lock.acquire(timeout=t):
            raise TimeoutError(f"Thread timeout acquiring attendance logs lock after {t}s")
        
        try:
            depth = getattr(self._local, "depth", 0)
            if depth > 0:
                self._local.depth = depth + 1
                return self

            rem_t = max(0.1, t - (time.time() - start))
            target_file = _get_active_logs_file()
            file_lock = get_file_lock(target_file, timeout=rem_t)
            file_lock.__enter__()
            self._local.file_lock = file_lock
            self._local.depth = 1
            return self
        except Exception:
            self._thread_lock.release()
            raise

    def __enter__(self):
        return self.acquire_lock(self.timeout)

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            depth = getattr(self._local, "depth", 0)
            if depth > 1:
                self._local.depth = depth - 1
                return
            
            self._local.depth = 0
            fl = getattr(self._local, "file_lock", None)
            if fl:
                try:
                    fl.__exit__(exc_type, exc_val, exc_tb)
                finally:
                    self._local.file_lock = None
        finally:
            self._thread_lock.release()

    def acquire(self, blocking: bool = True, timeout: Optional[float] = None, *args, **kwargs):
        t = self.timeout if timeout is None or timeout < 0 else timeout
        try:
            self.acquire_lock(t if blocking else 0.001)
            return True
        except Exception:
            return False

    def release(self, *args, **kwargs):
        self.__exit__(None, None, None)


_logs_lock = AttendanceLogsProcessLock(timeout=20.0)


def _get_active_logs_file() -> str:
    env_file = os.getenv("ATTENDANCE_LOGS_FILE")
    if env_file:
        return env_file
    for mod_name in ("backend.routers.attendance", "routers.attendance"):
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, "LOGS_FILE"):
            custom = getattr(mod, "LOGS_FILE")
            if custom and custom != LOGS_FILE:
                return custom
    return LOGS_FILE


def _get_active_heartbeat_file() -> str:
    env_file = os.getenv("HEARTBEAT_FILE")
    if env_file:
        return env_file
    for mod_name in ("backend.routers.attendance", "routers.attendance"):
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, "HEARTBEAT_FILE"):
            custom = getattr(mod, "HEARTBEAT_FILE")
            if custom and custom != HEARTBEAT_FILE:
                return custom
    return HEARTBEAT_FILE


def get_current_cafe_ip() -> str:
    """Read cafe IP from cache, SQLite store_settings, or heartbeat file."""
    global _cached_cafe_ip
    for mod_name in ("backend.routers.attendance", "routers.attendance"):
        mod = sys.modules.get(mod_name)
        if mod:
            if hasattr(mod, "get_current_cafe_ip"):
                fn = getattr(mod, "get_current_cafe_ip")
                if fn is not get_current_cafe_ip and callable(fn):
                    return fn()
            if hasattr(mod, "_cached_cafe_ip"):
                val = getattr(mod, "_cached_cafe_ip")
                if val:
                    _cached_cafe_ip = val

    # Read from SQLite store_settings
    try:
        from services.db import get_store_setting_db
        raw_val = get_store_setting_db("pos_heartbeat_last")
        if raw_val:
            d = json.loads(raw_val)
            ip = d.get("cafe_ip")
            if ip:
                _cached_cafe_ip = ip
                return _cached_cafe_ip
    except Exception:
        pass

    hb_file = _get_active_heartbeat_file()
    if os.path.exists(hb_file):
        try:
            with open(hb_file, "r", encoding="utf-8") as f:
                d = json.load(f)
                ip = d.get("cafe_ip")
                if ip:
                    _cached_cafe_ip = ip
        except Exception:
            pass
    return _cached_cafe_ip


def set_current_cafe_ip(ip: str):
    """Update cafe IP and persist to SQLite and file atomically."""
    global _cached_cafe_ip
    _cached_cafe_ip = ip
    for mod_name in ("backend.routers.attendance", "routers.attendance"):
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, "_cached_cafe_ip"):
            setattr(mod, "_cached_cafe_ip", ip)

    payload = {
        "cafe_ip": ip,
        "last_seen": datetime.now().isoformat(),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    # Persist to SQLite store_settings
    try:
        from services.db import update_store_setting_db
        update_store_setting_db(
            "pos_heartbeat_last",
            json.dumps(payload, ensure_ascii=False, indent=2),
            label="POS Heartbeat",
            description="Last heartbeat recorded from POS store device"
        )
    except Exception:
        pass

    hb_file = _get_active_heartbeat_file()
    safe_json_write(hb_file, payload)


def load_attendance_logs_from_sqlite() -> List[Dict[str, Any]]:
    """
    Primary Source of Truth: Loads all attendance logs directly from SQLite database.
    """
    try:
        from services.db import get_db_connection
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, tenant_id, username, full_name, date, shift,
                   checkin, checkout, duration_mins, status, note,
                   created_at, hourly_rate_snapshot, scheduled_start,
                   scheduled_end, effective_duration_mins, is_hanging_pending
            FROM attendance_logs
            ORDER BY id ASC
        """)
        rows = []
        for r in cur.fetchall():
            d = dict(r)
            d["shift_key"] = d.get("shift") or "sang"
            d["checkin_time"] = d.get("checkin")
            d["checkout_time"] = d.get("checkout")
            d["total_mins"] = d.get("duration_mins")
            d["staff_name"] = d.get("full_name")
            d["display_name"] = d.get("full_name")
            d["is_hanging_pending"] = bool(d.get("is_hanging_pending"))
            rows.append(d)
        conn.close()
        return rows
    except Exception:
        return []


def load_attendance_logs() -> List[Dict[str, Any]]:
    # 0. Test / Custom Isolation: Read isolated file if LOGS_FILE was overridden
    target_file = _get_active_logs_file()
    if target_file != LOGS_FILE:
        if os.path.exists(target_file):
            return safe_json_read(target_file, default=[])
        return []

    # 1. Primary Source of Truth: Read directly from SQLite WAL database
    try:
        from services.db import get_db_path
        db_path = get_db_path()
        if db_path and os.path.exists(db_path):
            return load_attendance_logs_from_sqlite()
    except Exception:
        pass

    db_logs = load_attendance_logs_from_sqlite()
    if db_logs:
        return db_logs

    # 2. First-time initialization ONLY: If SQLite database does not exist yet
    legacy_logs = safe_json_read(target_file, default=[])
    if legacy_logs:
        try:
            sync_attendance_logs_to_sqlite(legacy_logs)
        except Exception:
            pass
    return legacy_logs


def sync_latest_log_to_sqlite(log: Dict[str, Any]):
    """Dong bo ban ghi cham cong vao bang attendance_logs trong SQLite wfm.db."""
    if not log:
        return
    sync_attendance_logs_to_sqlite([log])


def sync_attendance_logs_to_sqlite(logs: List[Dict[str, Any]]):
    """Dong bo danh sach ban ghi cham cong vao bang attendance_logs trong SQLite wfm.db voi BEGIN IMMEDIATE."""
    try:
        from services.db import get_db_connection, get_db_path
        db_path = os.getenv("SQLITE_DB_PATH") or os.getenv("DATABASE_PATH")
        if not db_path:
            try:
                db_path = get_db_path()
            except Exception:
                db_path = None
        if not db_path or not os.path.exists(db_path):
            _data_dir = os.getenv("DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data"))
            for cand in ["fnbop.db", "wfm.db"]:
                fallback_db = os.path.join(_data_dir, cand)
                if os.path.exists(fallback_db):
                    db_path = fallback_db
                    break
                local_db = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", cand)
                if os.path.exists(local_db):
                    db_path = local_db
                    break
        if not db_path or not os.path.exists(db_path):
            return

        conn = get_db_connection(db_path)
        try:
            conn.isolation_level = None
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.cursor()

            if not logs:
                cur.execute("DELETE FROM attendance_logs")
                conn.execute("COMMIT")
                return

            persisted_ids = set()
            for log in logs:
                if not isinstance(log, dict) or not log.get("username"):
                    continue
                log_date = log.get("date")
                if not log_date:
                    c_at = log.get("created_at")
                    if c_at:
                        try:
                            log_date = datetime.fromisoformat(c_at).strftime("%d/%m/%Y")
                        except Exception:
                            log_date = datetime.now().strftime("%d/%m/%Y")
                    else:
                        log_date = datetime.now().strftime("%d/%m/%Y")

                row_id = None
                log_id = log.get("id")
                if log_id is not None and str(log_id).isdigit():
                    cur.execute("SELECT id FROM attendance_logs WHERE id = ?", (int(log_id),))
                    r = cur.fetchone()
                    if r:
                        row_id = r[0]

                if not row_id:
                    cur.execute("""
                        SELECT id FROM attendance_logs 
                        WHERE username = ? AND date = ? AND (shift = ? OR shift = ?)
                        ORDER BY id DESC LIMIT 1
                    """, (
                        log.get("username"),
                        log_date,
                        log.get("shift_name"),
                        log.get("shift_key")
                    ))
                    r = cur.fetchone()
                    if r:
                        row_id = r[0]
                
                if row_id:
                    cur.execute("""
                        UPDATE attendance_logs 
                        SET checkout = ?, duration_mins = ?, status = ?, note = ?,
                            hourly_rate_snapshot = COALESCE(?, hourly_rate_snapshot),
                            effective_duration_mins = ?, is_hanging_pending = ?
                        WHERE id = ?
                    """, (
                        log.get("checkout_time"),
                        log.get("total_mins") or 0,
                        log.get("status", "ON_TIME"),
                        log.get("note"),
                        log.get("hourly_rate_snapshot"),
                        log.get("effective_duration_mins", log.get("total_mins") or 0),
                        1 if log.get("is_hanging_pending") else 0,
                        row_id
                    ))
                    persisted_ids.add(row_id)
                    if not log.get("id"):
                        log["id"] = row_id
                    log["db_id"] = row_id
                else:
                    try:
                        from services.db.schema import DEFAULT_TENANT_ID
                    except ImportError:
                        DEFAULT_TENANT_ID = "default"
                    cur.execute("""
                        INSERT INTO attendance_logs (
                            tenant_id, username, full_name, date, shift, checkin, checkout, 
                            duration_mins, status, note, created_at, hourly_rate_snapshot, 
                            scheduled_start, scheduled_end, effective_duration_mins, is_hanging_pending
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        DEFAULT_TENANT_ID,
                        log.get("username"),
                        log.get("display_name", log.get("staff_name", log.get("username"))),
                        log_date,
                        log.get("shift_name", log.get("shift_key")),
                        log.get("checkin_time"),
                        log.get("checkout_time"),
                        log.get("total_mins") or 0,
                        log.get("status", "ON_TIME"),
                        log.get("note"),
                        log.get("created_at") or datetime.now().isoformat(),
                        int(log.get("hourly_rate_snapshot") or 17000),
                        log.get("scheduled_start") or "",
                        log.get("scheduled_end") or "",
                        log.get("effective_duration_mins", log.get("total_mins") or 0),
                        1 if log.get("is_hanging_pending") else 0
                    ))
                    new_id = cur.lastrowid
                    if new_id:
                        persisted_ids.add(new_id)
                        if not log.get("id"):
                            log["id"] = new_id
                        log["db_id"] = new_id

            if persisted_ids:
                placeholders = ",".join("?" for _ in persisted_ids)
                cur.execute(f"DELETE FROM attendance_logs WHERE id NOT IN ({placeholders})", list(persisted_ids))
            else:
                cur.execute("DELETE FROM attendance_logs")

            conn.execute("COMMIT")
        except Exception as e:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            print(f"[SQLite Sync Warning] Failed to sync logs to SQLite: {e}")
        finally:
            conn.close()
    except Exception as e:
        print(f"[SQLite Sync Warning] Failed to connect for sync: {e}")


def save_attendance_logs(logs: List[Dict[str, Any]]):
    for mod_name in ("backend.routers.attendance", "routers.attendance"):
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, "save_attendance_logs"):
            fn = getattr(mod, "save_attendance_logs")
            if fn is not save_attendance_logs and callable(fn):
                return fn(logs)
    target_file = _get_active_logs_file()
    with _logs_lock:
        # If test isolation override is active, write directly to the isolated file
        if target_file != LOGS_FILE:
            safe_json_write(target_file, logs)

        # Single Source of Truth: Sync directly to SQLite WAL
        if logs:
            sync_attendance_logs_to_sqlite(logs)
        else:
            try:
                from services.db import get_db_connection
                conn = get_db_connection()
                conn.execute("DELETE FROM attendance_logs")
                conn.commit()
                conn.close()
            except Exception:
                pass

        # Decoupled runtime JSON: Only write if ENABLE_RUNTIME_JSON_SYNC=true
        try:
            from services.storage import is_runtime_json_sync_enabled
            if is_runtime_json_sync_enabled():
                safe_json_write(target_file, logs)
        except Exception:
            pass


def calculate_shift_duration_minutes(checkin_date: str, checkin_time: str, checkout_time: str) -> int:
    """Safely calculate working minutes between checkin and checkout."""
    try:
        dt_in = datetime.strptime(f"{checkin_date} {checkin_time}", "%d/%m/%Y %H:%M")
        dt_out = datetime.strptime(f"{checkin_date} {checkout_time}", "%d/%m/%Y %H:%M")
        if dt_out < dt_in:
            dt_out += timedelta(days=1)
        diff = int((dt_out - dt_in).total_seconds() / 60)
        return max(0, diff)
    except Exception:
        return 0


def get_staff_roster_slot(username: str, date_val: Any, shift_key: str) -> Optional[Dict[str, Any]]:
    """
    Look up staff's scheduled shift slot in roster_schedule.json for a given date.
    Returns dict with slot details, or None if no matching roster slot is found.
    """
    try:
        if isinstance(date_val, datetime):
            target_date = date_val.date()
        elif hasattr(date_val, "strftime") and not isinstance(date_val, str):
            target_date = date_val
        elif isinstance(date_val, str):
            try:
                if "/" in date_val:
                    target_date = datetime.strptime(date_val, "%d/%m/%Y").date()
                else:
                    target_date = datetime.strptime(date_val, "%Y-%m-%d").date()
            except Exception:
                target_date = datetime.now().date()
        else:
            target_date = datetime.now().date()

        date_str = target_date.strftime("%Y-%m-%d")
        iso_year, iso_week, _ = target_date.isocalendar()
        week_id = f"{iso_year}-W{iso_week:02d}"

        u_norm = normalize_str(username)
        u_low = (username or "").strip().lower()
        user_ids = {u_norm, u_low}

        try:
            auth_data = load_staff_auth()
            staff_accs = auth_data.get("staff_accounts", {})
            for acc_uname, acc_info in staff_accs.items():
                aliases = [normalize_str(al) for al in acc_info.get("aliases", [])]
                full_name = acc_info.get("full_name", "")
                if full_name:
                    aliases.append(normalize_str(full_name))
                    aliases.append(full_name.lower())
                for sn in acc_info.get("sheet_names", []):
                    aliases.append(normalize_str(sn))
                    aliases.append(sn.lower())
                if (u_low == acc_uname.lower() or u_norm == normalize_str(acc_uname) or 
                    u_norm in aliases or u_low in aliases):
                    user_ids.add(acc_uname.lower())
                    user_ids.add(normalize_str(acc_uname))
                    for al in aliases:
                        user_ids.add(al)
                    break
        except Exception:
            pass

        def is_match(val: Any) -> bool:
            if not val or not isinstance(val, str):
                return False
            v_low = val.strip().lower()
            v_norm = normalize_str(val)
            return (v_low in user_ids or v_norm in user_ids)

        roster_data = load_roster_data()
        weeks = roster_data.get("weeks", {})
        week_entry = weeks.get(week_id, {})
        shifts = week_entry.get("shifts", {})
        day_shift = shifts.get(date_str, {})
        if not day_shift:
            return None

        if shift_key == "sang":
            period_key = "morning"
        elif shift_key == "toi":
            period_key = "evening"
        elif shift_key == "chieu":
            period_key = "afternoon"
        else:
            period_key = shift_key
        period_data = day_shift.get(period_key) or day_shift.get(shift_key) or {}
        if not period_data:
            return None

        if period_key == "evening":
            if is_match(period_data.get("service_18")):
                return {
                    "slot_type": "service_18",
                    "period": "evening",
                    "official_start": "18:00",
                    "tolerance_limit": "18:10",
                    "official_end": "23:00",
                    "standard_checkout": "23:00",
                    "min_checkout": "22:00"
                }
            elif is_match(period_data.get("service_17")):
                return {
                    "slot_type": "service_17",
                    "period": "evening",
                    "official_start": "17:00",
                    "tolerance_limit": "17:10",
                    "official_end": "23:00",
                    "standard_checkout": "23:00",
                    "min_checkout": "22:00"
                }
            elif is_match(period_data.get("barista")):
                return {
                    "slot_type": "barista",
                    "period": "evening",
                    "official_start": "17:00",
                    "tolerance_limit": "17:10",
                    "official_end": "23:00",
                    "standard_checkout": "23:00",
                    "min_checkout": "22:00"
                }
            elif is_match(period_data.get("manager")):
                return {
                    "slot_type": "manager",
                    "period": "evening",
                    "official_start": "17:00",
                    "tolerance_limit": "17:10",
                    "official_end": "23:00",
                    "standard_checkout": "23:00",
                    "min_checkout": "22:00"
                }

            srv_list = period_data.get("service")
            if isinstance(srv_list, list):
                if len(srv_list) > 1 and is_match(srv_list[1]):
                    return {
                        "slot_type": "service_18",
                        "period": "evening",
                        "official_start": "18:00",
                        "tolerance_limit": "18:10",
                        "official_end": "23:00",
                        "standard_checkout": "23:00",
                        "min_checkout": "22:00"
                    }
                elif len(srv_list) > 0 and is_match(srv_list[0]):
                    return {
                        "slot_type": "service_17",
                        "period": "evening",
                        "official_start": "17:00",
                        "tolerance_limit": "17:10",
                        "official_end": "23:00",
                        "standard_checkout": "23:00",
                        "min_checkout": "22:00"
                    }
            return None

        else:
            matched_slot = None
            if is_match(period_data.get("manager")):
                matched_slot = "manager"
            elif is_match(period_data.get("barista")):
                matched_slot = "barista"
            else:
                srv_list = period_data.get("service")
                if isinstance(srv_list, list) and any(is_match(s) for s in srv_list):
                    matched_slot = "service"

            if matched_slot:
                off_start = "06:00"
                tol_limit = "06:10"
                off_end = "11:30"
                min_co = "11:00"
                if period_key != "morning":
                    try:
                        from services.store_config import get_store_config
                        s_cfg = get_store_config().get("shifts", {}).get(shift_key, {})
                        off_start = s_cfg.get("official_start", "12:00")
                        tol_limit = s_cfg.get("tolerance_limit", "12:10")
                        off_end = s_cfg.get("official_end", "17:00")
                        min_co = s_cfg.get("min_checkout", "16:30")
                    except Exception:
                        pass
                return {
                    "slot_type": matched_slot,
                    "period": period_key,
                    "official_start": off_start,
                    "tolerance_limit": tol_limit,
                    "official_end": off_end,
                    "standard_checkout": off_end,
                    "min_checkout": min_co
                }
            return None
    except Exception:
        return None


def auto_close_hanging_shifts_logic() -> Dict[str, Any]:
    """
    Core business logic: Tự động chốt đóng ca sau 180 phút (3 tiếng) quá giờ tan ca chính thức.
    """
    with _logs_lock:
        logs = load_attendance_logs()
        now = datetime.now()
        closed_count = 0

        cutoff_mins = 180
        shifts_cfg = {}
        try:
            from services.store_config import get_store_config, get_auto_close_cutoff_minutes
            cfg = get_store_config()
            shifts_cfg = cfg.get("shifts", {})
            cutoff_mins = get_auto_close_cutoff_minutes(cfg)
        except Exception:
            shifts_cfg = {}
            cutoff_mins = 180
        
        for log in logs:
            if log.get("checkout_time") is None:
                log_date_str = log.get("date")  # DD/MM/YYYY
                shift_key = log.get("shift_key", "sang")

                s_info = shifts_cfg.get(shift_key, {})
                official_end_str = s_info.get("official_end") or ("11:30" if shift_key == "sang" else "23:00")

                should_auto_close = False
                try:
                    if log_date_str:
                        dt_date = datetime.strptime(log_date_str, "%d/%m/%Y").date()
                        end_t = datetime.strptime(official_end_str, "%H:%M").time()
                        end_dt = datetime.combine(dt_date, end_t)
                        cutoff_dt = end_dt + timedelta(minutes=cutoff_mins)
                        if now >= cutoff_dt:
                            should_auto_close = True
                except Exception:
                    pass

                if not should_auto_close:
                    created_at_str = log.get("created_at")
                    if created_at_str:
                        try:
                            dt_created = datetime.fromisoformat(created_at_str)
                            if (now - dt_created).total_seconds() / 3600 >= 24:
                                should_auto_close = True
                        except Exception:
                            pass

                checkout_target = s_info.get("min_checkout") or ("11:00" if shift_key == "sang" else "22:00")
                if should_auto_close:
                    closed_count += 1
                    effective_date = log.get("date")
                    if not effective_date:
                        if log.get("created_at"):
                            try:
                                effective_date = datetime.fromisoformat(log.get("created_at")).strftime("%d/%m/%Y")
                            except Exception:
                                effective_date = now.strftime("%d/%m/%Y")
                        else:
                            effective_date = now.strftime("%d/%m/%Y")
                        log["date"] = effective_date

                    diff_mins = calculate_shift_duration_minutes(
                        effective_date,
                        log.get("checkin_time", "06:00"),
                        checkout_target
                    )
                    log["checkout_time"] = checkout_target
                    log["total_mins"] = diff_mins
                    
                    is_48h = False
                    c_str = log.get("created_at")
                    if c_str:
                        try:
                            if (now - datetime.fromisoformat(c_str)).total_seconds() / 3600 >= 48:
                                is_48h = True
                        except Exception:
                            pass

                    log["closed_by"] = "AUTO_CLOSE_48H" if is_48h else f"AUTO_CLOSE_{cutoff_mins}M"
                    log["auto_closed"] = True
                    log["forgot_checkout"] = True
                    log["updated_at"] = now.isoformat()
                    log["note"] = f"Hệ thống tự động chốt ca sau {cutoff_mins} phút quá giờ tan ca ({official_end_str}) do quên check-out."
        if closed_count > 0:
            save_attendance_logs(logs)
            for l in logs:
                if l.get("auto_closed"):
                    sync_latest_log_to_sqlite(l)
            
        return {
            "status": "success", 
            "closed_count": closed_count,
            "message": f"Đã tự động đóng {closed_count} ca làm việc quá {cutoff_mins} phút sau giờ tan ca."
        }


TRUSTED_PROXIES = {"127.0.0.1", "::1", "localhost", "testclient"}


def is_trusted_proxy(host: str) -> bool:
    if host in TRUSTED_PROXIES:
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback
    except ValueError:
        return False


def is_lan_or_local_ip(ip_str: str) -> bool:
    if not ip_str:
        return False
    if ip_str in ("127.0.0.1", "localhost", "::1", "testclient"):
        return True
    try:
        ip = ipaddress.ip_address(ip_str)
        return (
            ip.is_loopback
            or ip in ipaddress.ip_network("10.0.0.0/8")
            or ip in ipaddress.ip_network("172.16.0.0/12")
            or ip in ipaddress.ip_network("192.168.0.0/16")
        )
    except ValueError:
        return False


def is_matching_cafe_wifi(client_ip: str, cafe_ip: str) -> bool:
    """
    Xác thực IP WiFi FnBOps:
    1. So khớp chính xác 100% IP tĩnh/động của quán.
    2. Fallback Subnet /24: Nếu máy POS tắt/offline > 120 phút và router quán nhận IP động mới trong cùng dải /24.
    """
    on_premise = os.getenv("ON_PREMISE_MODE", "false").lower() in ("true", "1")
    if on_premise and is_lan_or_local_ip(client_ip):
        return True
    if not client_ip or not cafe_ip:
        return False
    c_ip = client_ip.strip()
    target_ip = cafe_ip.strip()
    if c_ip == target_ip:
        return True

    if os.getenv("ALLOW_SUBNET_FALLBACK", "0").lower() in ("1", "true"):
        try:
            hb_file = _get_active_heartbeat_file()
            if os.path.exists(hb_file):
                with open(hb_file, "r", encoding="utf-8") as f:
                    hb = json.load(f)
                last_seen_str = hb.get("last_seen")
                if last_seen_str:
                    dt_seen = datetime.fromisoformat(last_seen_str)
                    age_minutes = (datetime.now() - dt_seen).total_seconds() / 60
                    if age_minutes >= 120:
                        c_parts = c_ip.split(".")
                        t_parts = target_ip.split(".")
                        if len(c_parts) == 4 and len(t_parts) == 4 and c_parts[:3] == t_parts[:3]:
                            set_current_cafe_ip(c_ip)
                            alert_msg = (
                                "[TU DONG DONG BO IP QUAN] FnBOps Store\n"
                                + "May POS offline tu " + str(hb.get("updated_at", "truoc do")) + ".\n"
                                + "Da tu dong cap nhat IP moi (" + c_ip + ") tu nhan vien cham cong cung dai mang Viettel/VNPT."
                            )
                            send_telegram_alert(alert_msg)
                            return True
        except Exception:
            pass

    return False


def detect_current_shift(now: Optional[datetime] = None, username: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Determine current active shift window based on dynamic store operating hours."""
    if now is None:
        now = datetime.now()
    cur_time = now.time()

    shifts_cfg = {}
    try:
        from services.store_config import get_store_config
        cfg = get_store_config()
        shifts_cfg = cfg.get("shifts", {})
    except Exception:
        shifts_cfg = {}

    # 1. Roster matching for scheduled staff
    staff_has_roster_today = False
    if username and shifts_cfg:
        try:
            today_date = now.date()
            for s_key, s_data in shifts_cfg.items():
                slot_info = get_staff_roster_slot(username, today_date, s_key)
                if slot_info:
                    staff_has_roster_today = True
                    off_start = slot_info.get("official_start") or s_data.get("official_start", "06:00")
                    off_end = slot_info.get("official_end") or s_data.get("official_end", "11:30")
                    dt_s = datetime.strptime(off_start, "%H:%M")
                    dt_e = datetime.strptime(off_end, "%H:%M")
                    t_start_buf = (dt_s - timedelta(minutes=45)).time()
                    t_end_buf = (dt_e + timedelta(minutes=90)).time()
                    
                    in_roster_window = False
                    if t_start_buf <= t_end_buf:
                        in_roster_window = (t_start_buf <= cur_time <= t_end_buf)
                    else:
                        in_roster_window = (cur_time >= t_start_buf or cur_time <= t_end_buf)
                        
                    if in_roster_window:
                        tolerance_limit = slot_info.get("tolerance_limit") or s_data.get("tolerance_limit")
                        if not tolerance_limit:
                            tolerance_limit = (dt_s + timedelta(minutes=10)).strftime("%H:%M")
                        min_checkout = s_data.get("min_checkout")
                        if not min_checkout:
                            min_checkout = (dt_e - timedelta(minutes=30)).strftime("%H:%M")
                        return {
                            "key": s_key,
                            "name": s_data.get("name", "Ca Làm"),
                            "official_start": off_start,
                            "official_end": off_end,
                            "tolerance_limit": tolerance_limit,
                            "min_checkout": min_checkout,
                            "slot_type": slot_info.get("slot_type")
                        }
        except Exception:
            pass

    # Nếu nhân sự đã có lịch ca hôm nay nhưng hiện chưa đến giờ hoặc đã qua giờ ca đó,
    # không tự ý match sang ca làm việc khác mà nhân sự không được xếp
    if staff_has_roster_today:
        return None

    # 2. Match against dynamically configured shifts
    matched_candidates = []
    for s_key, s_data in shifts_cfg.items():
        off_start = s_data.get("official_start", "06:00")
        off_end = s_data.get("official_end", "11:30")

        w_cfg = s_data.get("window") or {}
        w_start_str = w_cfg.get("start")
        w_end_str = w_cfg.get("end")

        if not w_start_str:
            try:
                dt_s = datetime.strptime(off_start, "%H:%M")
                w_start_str = (dt_s - timedelta(minutes=30)).strftime("%H:%M")
            except Exception:
                w_start_str = off_start

        if not w_end_str:
            try:
                dt_e = datetime.strptime(off_end, "%H:%M")
                w_end_str = (dt_e + timedelta(minutes=60)).strftime("%H:%M")
            except Exception:
                w_end_str = off_end

        try:
            t_start = datetime.strptime(w_start_str, "%H:%M").time()
            t_end = datetime.strptime(w_end_str, "%H:%M").time()

            in_window = False
            if t_start <= t_end:
                in_window = (t_start <= cur_time <= t_end)
            else:
                in_window = (cur_time >= t_start or cur_time <= t_end)

            if in_window:
                slot_type = None
                official_start = off_start
                tolerance_limit = s_data.get("tolerance_limit")
                if not tolerance_limit:
                    try:
                        tolerance_limit = (datetime.strptime(off_start, "%H:%M") + timedelta(minutes=10)).strftime("%H:%M")
                    except Exception:
                        tolerance_limit = "06:10"

                min_checkout = s_data.get("min_checkout")
                if not min_checkout:
                    try:
                        min_checkout = (datetime.strptime(off_end, "%H:%M") - timedelta(minutes=30)).strftime("%H:%M")
                    except Exception:
                        min_checkout = "11:00"

                if username:
                    try:
                        slot_info = get_staff_roster_slot(username, now.date(), s_key)
                        if slot_info:
                            slot_type = slot_info.get("slot_type")
                            official_start = slot_info.get("official_start", official_start)
                            tolerance_limit = slot_info.get("tolerance_limit", tolerance_limit)
                    except Exception:
                        pass
                res = {
                    "key": s_key,
                    "name": s_data.get("name", "Ca Làm"),
                    "official_start": official_start,
                    "official_end": off_end,
                    "tolerance_limit": tolerance_limit,
                    "min_checkout": min_checkout
                }
                if slot_type:
                    res["slot_type"] = slot_type
                matched_candidates.append(res)
        except Exception:
            pass

    if matched_candidates:
        if len(matched_candidates) == 1:
            return matched_candidates[0]
        def candidate_score(item):
            try:
                dt_now_dummy = datetime.combine(datetime.today(), cur_time)
                dt_start = datetime.combine(datetime.today(), datetime.strptime(item["official_start"], "%H:%M").time())
                dt_end = datetime.combine(datetime.today(), datetime.strptime(item["official_end"], "%H:%M").time())
                
                past_end_penalty = 2000 if dt_now_dummy > dt_end else 0
                dist_start = abs((dt_now_dummy - dt_start).total_seconds()) / 60
                return past_end_penalty + dist_start
            except Exception:
                return 99999

        matched_candidates.sort(key=candidate_score)
        return matched_candidates[0]

    # 3. Static FnBOps Fallback ONLY IF dynamic config is not defined
    if not shifts_cfg:
        t_morn_start = datetime.strptime("05:55", "%H:%M").time()
        t_morn_end = datetime.strptime("13:00", "%H:%M").time()
        t_eve_start = datetime.strptime("16:30", "%H:%M").time()
        t_eve_end = datetime.strptime("23:59", "%H:%M").time()

        if t_morn_start <= cur_time <= t_morn_end:
            slot_type = None
            if username:
                try:
                    slot_info = get_staff_roster_slot(username, now.date(), "sang")
                    if slot_info:
                        slot_type = slot_info.get("slot_type")
                except Exception:
                    pass
            shift_dict = {
                "key": "sang",
                "name": "Ca Sáng",
                "official_start": "06:00",
                "official_end": "11:30",
                "tolerance_limit": "06:10",
                "min_checkout": "11:00"
            }
            if slot_type:
                shift_dict["slot_type"] = slot_type
            return shift_dict
        elif t_eve_start <= cur_time <= t_eve_end:
            official_start = "17:00"
            tolerance_limit = "17:10"
            slot_type = None
            if username:
                try:
                    slot_info = get_staff_roster_slot(username, now.date(), "toi")
                    if slot_info:
                        slot_type = slot_info.get("slot_type")
                        official_start = slot_info.get("official_start", official_start)
                        tolerance_limit = slot_info.get("tolerance_limit", tolerance_limit)
                except Exception:
                    pass

            shift_dict = {
                "key": "toi",
                "name": "Ca Tối",
                "official_start": official_start,
                "official_end": "23:00",
                "tolerance_limit": tolerance_limit,
                "min_checkout": "22:00"
            }
            if slot_type:
                shift_dict["slot_type"] = slot_type
            return shift_dict
    return None


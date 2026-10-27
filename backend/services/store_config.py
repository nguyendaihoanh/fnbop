# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
Store Configuration Service (FnBOps Operations)
Provides dynamic multi-store configuration:
- Operating shifts (hours, standard minutes, late tolerances, staffing slots)
- Gender & workload constraints
- POS integration mode ('pos365' or 'manual')
- Configurable holidays
- Registration window rules
"""

import os
import sys
import json
import logging
import threading
from typing import Dict, Any, List, Optional
from datetime import datetime

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROJECT_DIR = os.path.dirname(_BASE_DIR)

if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)

# Ensure services.store_config and backend.services.store_config share the same module instance and cache
if __name__ in ("backend.services.store_config", "services.store_config"):
    sys.modules["backend.services.store_config"] = sys.modules[__name__]
    sys.modules["services.store_config"] = sys.modules[__name__]

try:
    from backend.services.storage import safe_json_read, safe_json_write
except ImportError:
    from services.storage import safe_json_read, safe_json_write

try:
    from backend.services.db.connection import get_db_connection
    from backend.services.db.schema import _ensure_store_configs_table
except ImportError:
    try:
        from services.db.connection import get_db_connection
        from services.db.schema import _ensure_store_configs_table
    except ImportError:
        get_db_connection = None
        _ensure_store_configs_table = None

logger = logging.getLogger("store_config")

if os.getenv("STORE_CONFIG_FILE"):
    DEFAULT_CONFIG_PATH = os.getenv("STORE_CONFIG_FILE")
elif os.getenv("DATA_DIR"):
    DEFAULT_CONFIG_PATH = os.path.join(os.getenv("DATA_DIR"), "store_config.json")
elif _PROJECT_DIR and _PROJECT_DIR != "/" and os.path.exists(os.path.join(_PROJECT_DIR, "data")):
    DEFAULT_CONFIG_PATH = os.path.join(_PROJECT_DIR, "data", "store_config.json")
else:
    DEFAULT_CONFIG_PATH = os.path.join(_BASE_DIR, "data", "store_config.json")

_config_cache: Dict[str, Dict[str, Any]] = {}
_config_lock = threading.Lock()

DEFAULT_STORE_CONFIG: Dict[str, Any] = {
    "store_id": "default",
    "store_name": "FnBOps Store Lounge",
    "wifi_ssid": "FnBOps_Store_WiFi",
    "timezone": "Asia/Ho_Chi_Minh",
    "pos_mode": "pos365",  # "pos365" | "manual"
    "notifications": {
        "telegram": {
            "enabled": True,
            "bot_token": "",
            "chat_id": ""
        },
        "zalo": {
            "enabled": False,
            "status": "disconnected",
            "gateway_url": "http://127.0.0.1:8177"
        }
    },
    "shifts": {
        "sang": {
            "key": "sang",
            "name": "Ca Sáng",
            "official_start": "06:00",
            "official_end": "11:30",
            "tolerance_limit": "06:10",
            "min_checkout": "11:00",
            "standard_mins": 330,
            "roles": {
                "manager": 1,
                "barista": 1,
                "service": 2
            },
            "weekday_roles": {
                "manager": 1,
                "barista": 1,
                "service": 2
            },
            "weekend_roles": {
                "manager": 1,
                "barista": 2,
                "service": 3
            },
            "window": {
                "start": "05:55",
                "end": "13:00"
            }
        },
        "toi": {
            "key": "toi",
            "name": "Ca Tối",
            "official_start": "17:00",
            "official_end": "23:00",
            "tolerance_limit": "17:10",
            "min_checkout": "22:00",
            "standard_mins": 360,
            "roles": {
                "manager": 1,
                "barista": 0,
                "service": 2
            },
            "weekday_roles": {
                "manager": 1,
                "barista": 0,
                "service": 2
            },
            "weekend_roles": {
                "manager": 1,
                "barista": 1,
                "service": 3
            },
            "staggered_service": [
                {
                    "slot": "service_17",
                    "official_start": "17:00",
                    "official_end": "23:00",
                    "tolerance_limit": "17:10",
                    "standard_mins": 360
                },
                {
                    "slot": "service_18",
                    "official_start": "18:00",
                    "official_end": "23:00",
                    "tolerance_limit": "18:10",
                    "standard_mins": 300
                }
            ],
            "window": {
                "start": "16:30",
                "end": "23:59"
            }
        }
    },
    "roster_rules": {
        "registration_window": {
            "open_iso_day": 1,      # Monday (Thả cửa 24/7)
            "close_iso_day": 7,     # Sunday
            "close_time": "18:00"   # Khóa lúc 18:00 Chủ Nhật
        },
        "gender_constraints": {
            "enabled": True,
            "service_max_female": 1,
            "service_min_male": 1
        },
        "shifts_per_week": {
            "min": 3,
            "max": 10,
            "default_target": 5
        },
        "small_store_mode": False,
        "enable_skill_bitmask": True,
        "allow_solo_shift_coverage": True,
        "relax_gender_constraints_on_deadlock": True
    },
    "holiday_rules": {
        "holidays": ["02/09"],
        "rate_multiplier": 2.0
    },
    "auto_close_rules": {
        "max_unclosed_hours": 24, # Automatically close ca if left open for > 24h
        "daily_cutoff": "23:59"
    },
    "zalo_automation": {
        "enable_auto_payslip": False,
        "enable_auto_shift_reminder": False,
        "enable_auto_checkout_alert": False,
        "reminder_minutes_before_shift": 30,
        "checkout_alert_grace_mins": 15
    },
    "version": 1,
    "shift_valid_from": "2026-01-01T00:00:00",
    "shift_versions": [],
    "payroll_rules": {
        "deduction_cap_percent": 0.50,
        "allow_negative_net": False,
        "carry_forward_debt": True
    }
}


def get_config_file_path() -> str:
    if os.getenv("STORE_CONFIG_FILE"):
        return os.getenv("STORE_CONFIG_FILE")
    if os.getenv("DATA_DIR"):
        return os.path.join(os.getenv("DATA_DIR"), "store_config.json")
    proj_data = os.path.join(_PROJECT_DIR, "data", "store_config.json")
    if os.path.exists(proj_data):
        return proj_data
    base_data = os.path.join(_BASE_DIR, "data", "store_config.json")
    if os.path.exists(base_data):
        return base_data
    return proj_data


def _merge_with_default(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Merges loaded config with DEFAULT_STORE_CONFIG to guarantee all expected keys exist."""
    merged = json.loads(json.dumps(DEFAULT_STORE_CONFIG))
    if not isinstance(cfg, dict):
        return merged
    for k, v in cfg.items():
        if k == "notifications" and isinstance(v, dict):
            if "notifications" not in merged or not isinstance(merged["notifications"], dict):
                merged["notifications"] = {}
            for notif_ch, notif_def in DEFAULT_STORE_CONFIG["notifications"].items():
                if notif_ch in v and isinstance(v[notif_ch], dict):
                    ch_merged = json.loads(json.dumps(notif_def))
                    ch_merged.update(v[notif_ch])
                    merged["notifications"][notif_ch] = ch_merged
                elif notif_ch in v:
                    merged["notifications"][notif_ch] = v[notif_ch]
                else:
                    merged["notifications"][notif_ch] = json.loads(json.dumps(notif_def))
            for extra_k, extra_v in v.items():
                if extra_k not in merged["notifications"]:
                    merged["notifications"][extra_k] = extra_v
        elif k == "roster_rules" and isinstance(v, dict):
            if "roster_rules" not in merged or not isinstance(merged["roster_rules"], dict):
                merged["roster_rules"] = {}
            for rk, rv in DEFAULT_STORE_CONFIG["roster_rules"].items():
                if rk not in v:
                    merged["roster_rules"][rk] = rv
                else:
                    merged["roster_rules"][rk] = v[rk]
            for extra_k, extra_v in v.items():
                merged["roster_rules"][extra_k] = extra_v
        elif k in ("shifts", "holiday_rules", "auto_close_rules", "shift_versions", "payroll_rules", "version", "shift_valid_from"):
            merged[k] = v
        else:
            merged[k] = v
    return merged


def get_store_config(tenant_id: str = "default") -> Dict[str, Any]:
    """
    Loads store configuration safely with multi-tenant database support, in-memory cache, and fallback.
    - If tenant_id exists in cache: returns cached config safely.
    - If tenant_id exists in SQLite store_configs: loads, merges, caches, and returns.
    - If tenant_id not in DB: fallbacks to DEFAULT_STORE_CONFIG and seeds into DB.
    """
    t_id = str(tenant_id).strip() if tenant_id else "default"

    with _config_lock:
        if t_id in _config_cache:
            return json.loads(json.dumps(_config_cache[t_id]))

        # Read from SQLite store_configs
        if get_db_connection:
            try:
                conn = get_db_connection()
                if _ensure_store_configs_table:
                    _ensure_store_configs_table(conn)
                cur = conn.cursor()
                cur.execute("SELECT config_json FROM store_configs WHERE tenant_id = ?", (t_id,))
                row = cur.fetchone()
                if row and row[0]:
                    try:
                        loaded_cfg = json.loads(row[0])
                        merged = _merge_with_default(loaded_cfg)
                        _config_cache[t_id] = merged
                        conn.close()
                        return json.loads(json.dumps(merged))
                    except Exception as e:
                        logger.warning(f"Failed to parse config_json for tenant {t_id}: {e}")

                # If tenant_id not in DB: fallback to DEFAULT_STORE_CONFIG and seed into DB
                seed_cfg = json.loads(json.dumps(DEFAULT_STORE_CONFIG))
                # For default tenant, migrate/preserve legacy disk config if available
                if t_id in ("default", "fnbops_main", "wfm_central"):
                    fpath = get_config_file_path()
                    if os.path.exists(fpath):
                        legacy_cfg = safe_json_read(fpath, default={})
                        if isinstance(legacy_cfg, dict) and legacy_cfg:
                            seed_cfg = _merge_with_default(legacy_cfg)

                config_str = json.dumps(seed_cfg, ensure_ascii=False)
                try:
                    cur.execute("""
                        INSERT INTO store_configs (tenant_id, config_json, version, updated_at)
                        VALUES (?, ?, 1, CURRENT_TIMESTAMP)
                        ON CONFLICT(tenant_id) DO UPDATE SET
                            config_json = excluded.config_json,
                            updated_at = CURRENT_TIMESTAMP;
                    """, (t_id, config_str))
                    conn.commit()
                except Exception as e:
                    logger.warning(f"Failed to seed store_config into DB for tenant {t_id}: {e}")
                finally:
                    conn.close()

                _config_cache[t_id] = seed_cfg
                return json.loads(json.dumps(seed_cfg))
            except Exception as e:
                logger.error(f"Error accessing store_configs in SQLite for tenant {t_id}: {e}")

        # Fallback if DB is unavailable
        seed_cfg = json.loads(json.dumps(DEFAULT_STORE_CONFIG))
        if t_id in ("default", "fnbops_main", "wfm_central"):
            fpath = get_config_file_path()
            if os.path.exists(fpath):
                legacy_cfg = safe_json_read(fpath, default={})
                if isinstance(legacy_cfg, dict) and legacy_cfg:
                    seed_cfg = _merge_with_default(legacy_cfg)
        _config_cache[t_id] = seed_cfg
        return json.loads(json.dumps(seed_cfg))


def save_store_config(config: Optional[Dict[str, Any]] = None, tenant_id: str = "default", **kwargs) -> bool:
    """
    Saves store configuration into SQLite store_configs table and updates thread-safe cache.
    Accepts config either positionally or via config_data keyword argument.
    Implements Immutable Versioning (ADR-007): Automatically archives previous shift configuration
    into shift_versions when shifts are updated.
    """
    cfg = config if config is not None else kwargs.get("config_data")
    if not isinstance(cfg, dict):
        return False
    t_id = str(tenant_id).strip() if tenant_id else "default"

    with _config_lock:
        # Check existing config in cache or DB to detect shift mutations
        existing_cfg = _config_cache.get(t_id)
        if not existing_cfg and get_db_connection:
            try:
                _conn_c = get_db_connection()
                _cur_c = _conn_c.cursor()
                _cur_c.execute("SELECT config_json FROM store_configs WHERE tenant_id = ?", (t_id,))
                _row_c = _cur_c.fetchone()
                if _row_c and _row_c[0]:
                    existing_cfg = json.loads(_row_c[0])
                _conn_c.close()
            except Exception:
                pass

        if existing_cfg and isinstance(existing_cfg, dict):
            old_shifts = existing_cfg.get("shifts")
            new_shifts = cfg.get("shifts")
            if old_shifts and new_shifts and old_shifts != new_shifts:
                shift_versions = list(existing_cfg.get("shift_versions") or [])
                old_ver = existing_cfg.get("version", 1)
                valid_from = existing_cfg.get("shift_valid_from", "2026-01-01T00:00:00")
                now_iso = datetime.now().isoformat()

                # Archive previous shift configuration to prevent historical calculation drift
                shift_versions.append({
                    "version": old_ver,
                    "valid_from": valid_from,
                    "valid_to": now_iso,
                    "shifts": json.loads(json.dumps(old_shifts))
                })
                cfg["shift_versions"] = shift_versions
                cfg["version"] = old_ver + 1
                cfg["shift_valid_from"] = now_iso
            elif "shift_versions" not in cfg and "shift_versions" in existing_cfg:
                cfg["shift_versions"] = existing_cfg["shift_versions"]
                if "version" in existing_cfg:
                    cfg["version"] = existing_cfg["version"]
                if "shift_valid_from" in existing_cfg:
                    cfg["shift_valid_from"] = existing_cfg["shift_valid_from"]

        # Cache in-memory
        _config_cache[t_id] = json.loads(json.dumps(cfg))

        # Backward compatibility: write to disk for default tenant only if enabled or testing
        should_write_file = bool(os.getenv("STORE_CONFIG_FILE"))
        if not should_write_file:
            try:
                from services.storage import is_runtime_json_sync_enabled
                should_write_file = is_runtime_json_sync_enabled()
            except Exception:
                should_write_file = False

        if should_write_file and t_id in ("default", "fnbops_main", "wfm_central"):
            try:
                fpath = get_config_file_path()
                os.makedirs(os.path.dirname(os.path.abspath(fpath)), exist_ok=True)
                safe_json_write(fpath, cfg)
            except Exception as e:
                logger.warning(f"Failed to write legacy store_config.json: {e}")

        # Persist to SQLite store_configs
        if get_db_connection:
            try:
                conn = get_db_connection()
                if _ensure_store_configs_table:
                    _ensure_store_configs_table(conn)
                cur = conn.cursor()
                config_str = json.dumps(cfg, ensure_ascii=False)
                cur.execute("""
                    INSERT INTO store_configs (tenant_id, config_json, version, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(tenant_id) DO UPDATE SET
                        config_json = excluded.config_json,
                        version = excluded.version,
                        updated_at = CURRENT_TIMESTAMP;
                """, (t_id, config_str, int(cfg.get("version", 1))))
                conn.commit()
                conn.close()
                return True
            except Exception as e:
                logger.error(f"Failed to save store_config to SQLite for tenant {t_id}: {e}")
                return False
        return True


def clear_store_config_cache(tenant_id: Optional[str] = None) -> None:
    """Clears in-memory store config cache for a specific tenant or all tenants."""
    with _config_lock:
        if tenant_id:
            _config_cache.pop(str(tenant_id).strip(), None)
        else:
            _config_cache.clear()


def is_configured_holiday(date_str: str, config: Optional[Dict[str, Any]] = None, tenant_id: str = "default") -> bool:
    """Checks if date is a configured holiday."""
    if not date_str:
        return False
    cfg = config or get_store_config(tenant_id)
    holidays = cfg.get("holiday_rules", {}).get("holidays", ["02/09"])
    
    clean_d = str(date_str).strip()
    # Normalize DD/MM
    day_month = ""
    if "/" in clean_d:
        parts = clean_d.split("/")
        if len(parts) >= 2:
            day_month = f"{int(parts[0]):02d}/{int(parts[1]):02d}"
    elif "-" in clean_d:
        parts = clean_d.split("-")
        if len(parts) >= 3:
            day_month = f"{int(parts[2]):02d}/{int(parts[1]):02d}"
            
    return day_month in holidays


def get_auto_close_cutoff_minutes(config: Optional[Dict[str, Any]] = None, tenant_id: str = "default") -> int:
    """
    Returns the cutoff in minutes after shift end before auto-closing an unclosed shift.
    Default is 180 minutes (3 hours).
    """
    cfg = config or get_store_config(tenant_id)
    auto_rules = cfg.get("auto_close_rules", {})
    if "cutoff_minutes" in auto_rules:
        return int(auto_rules["cutoff_minutes"])
    if "auto_close_hours" in auto_rules:
        return int(auto_rules["auto_close_hours"] * 60)
    return 180


def _parse_date_input(d: Any) -> Optional[datetime]:
    """Helper to convert various date formats into a datetime object for range comparison."""
    if not d:
        return None
    if isinstance(d, datetime):
        return d
    if hasattr(d, "year") and hasattr(d, "month") and hasattr(d, "day"):
        return datetime(d.year, d.month, d.day)
    s = str(d).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%d/%m/%Y %H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(s.split(".")[0], fmt)
        except Exception:
            pass
    return None


def get_shift_config_at(
    date_or_dt: Any,
    shift_key: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    tenant_id: str = "default"
) -> Optional[Dict[str, Any]]:
    """
    Retrieves the authoritative shift configuration active at a given date/time (Immutable Versioning - ADR-007).
    If date falls into a historical shift_version [valid_from, valid_to], returns that historical snapshot.
    Otherwise returns active current shift configuration.
    """
    cfg = config or get_store_config(tenant_id)
    if not cfg:
        return None

    target_dt = _parse_date_input(date_or_dt)
    target_shifts = cfg.get("shifts", {})

    # Check historical shift_versions
    if target_dt and "shift_versions" in cfg and isinstance(cfg["shift_versions"], list):
        for hist in cfg["shift_versions"]:
            vf = _parse_date_input(hist.get("valid_from"))
            vt = _parse_date_input(hist.get("valid_to"))
            if vf and vt and vf <= target_dt <= vt:
                target_shifts = hist.get("shifts", target_shifts)
                break
            elif vf and not vt and target_dt >= vf:
                target_shifts = hist.get("shifts", target_shifts)
                break

    if not shift_key:
        return target_shifts

    sub_cfg = {"shifts": target_shifts}
    return get_shift_by_alias(shift_key, config=sub_cfg, tenant_id=tenant_id)


def get_shift_by_alias(
    shift_key: str, 
    config: Optional[Dict[str, Any]] = None, 
    tenant_id: str = "default",
    date_str: Optional[Any] = None
) -> Optional[Dict[str, Any]]:
    """
    Retrieves shift info supporting bidirectional aliases:
    'morning' <-> 'sang', 'evening' <-> 'toi', 'chieu' <-> 'afternoon'.
    If date_str is provided, resolves historical shift config active on that date.
    """
    if not shift_key:
        return None
    if date_str and not config:
        return get_shift_config_at(date_str, shift_key=shift_key, tenant_id=tenant_id)

    cfg = config or get_store_config(tenant_id)
    shifts = cfg.get("shifts", {})

    k = str(shift_key).lower().strip()
    alias_map = {
        "morning": "sang",
        "sang": "sang",
        "sáng": "sang",
        "evening": "toi",
        "toi": "toi",
        "tối": "toi",
        "night": "toi",
        "chieu": "chieu",
        "chiều": "chieu",
        "afternoon": "chieu"
    }
    target_key = alias_map.get(k, k)
    res = shifts.get(target_key) or shifts.get(k)
    if res and isinstance(res, dict) and "key" not in res:
        res["key"] = target_key
    return res


def get_shift_standard_mins(
    shift_name: str,
    checkin_str: Optional[str] = None,
    date_str: Optional[Any] = None,
    tenant_id: str = "default"
) -> int:
    """
    Authoritative standard shift duration resolver supporting historical shift versions.
    """
    s_info = None
    if date_str:
        s_info = get_shift_config_at(date_str, shift_key=shift_name, tenant_id=tenant_id)
    if not s_info:
        s_info = get_shift_by_alias(shift_name, tenant_id=tenant_id)

    if s_info and isinstance(s_info, dict):
        std = s_info.get("standard_mins")
        if std and isinstance(std, (int, float)):
            return int(std)

    # Fallback to defaults
    s_norm = str(shift_name).lower()
    if "sang" in s_norm or "morning" in s_norm:
        return 330
    if "17" in s_norm:
        return 360
    if "18" in s_norm:
        return 300
    return 300


def get_shift_role_requirements(shift_config: Dict[str, Any], is_weekend: bool = False) -> Dict[str, int]:
    """
    Returns role headcount quotas for a shift:
    {"manager": int, "barista": int, "service": int}
    Supports weekday_roles vs weekend_roles with backward-compatible fallback to roles.
    """
    if not shift_config or not isinstance(shift_config, dict):
        return {"manager": 1, "barista": 1, "service": 2}

    base_roles = shift_config.get("weekday_roles") or shift_config.get("roles") or {}
    req = {
        "manager": int(base_roles.get("manager", 1)),
        "barista": int(base_roles.get("barista", 1)),
        "service": int(base_roles.get("service", 2)),
    }

    if is_weekend:
        weekend_roles = shift_config.get("weekend_roles") or {}
        if isinstance(weekend_roles, dict):
            if "manager" in weekend_roles:
                req["manager"] = int(weekend_roles["manager"])
            if "barista" in weekend_roles:
                req["barista"] = int(weekend_roles["barista"])
            if "service" in weekend_roles:
                req["service"] = int(weekend_roles["service"])

    return req




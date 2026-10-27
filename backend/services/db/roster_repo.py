# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
Roster Repository Layer
Handles weekly roster schedule persistence and staff shift registrations in SQLite.
"""

import os
import json
import logging
import datetime
from typing import Optional, Dict, Any, List

from services.db.connection import get_db_connection, DEFAULT_TENANT_ID
from services.db.schema import _ensure_v2_operational_tables

logger = logging.getLogger("db_service")


def upsert_roster_schedule_db(
    week_key: str,
    week_data: Dict[str, Any],
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> bool:
    """
    Upsert a week's roster schedule and registrations into SQLite.
    """
    if not week_key or not isinstance(week_data, dict):
        return False

    clean_key = str(week_key).strip()
    status = str(week_data.get("status") or "DRAFT").strip().upper()
    regs = week_data.get("registrations") or {}
    
    schedule_json = json.dumps(week_data, ensure_ascii=False)
    registrations_json = json.dumps(regs, ensure_ascii=False)
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db_connection(db_path)
    _ensure_v2_operational_tables(conn)
    with conn:
        conn.execute("""
            INSERT INTO roster_schedules (
                week_key, tenant_id, status, schedule_json, registrations_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(week_key, tenant_id) DO UPDATE SET
                status = excluded.status,
                schedule_json = excluded.schedule_json,
                registrations_json = excluded.registrations_json,
                updated_at = excluded.updated_at
        """, (clean_key, tenant_id, status, schedule_json, registrations_json, now_str))
    conn.close()
    return True


def get_roster_schedule_db(
    week_key: str,
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Retrieve a single week's roster schedule from SQLite.
    """
    if not week_key:
        return None
    clean_key = str(week_key).strip()
    conn = get_db_connection(db_path)
    _ensure_v2_operational_tables(conn)
    cur = conn.cursor()
    cur.execute(
        "SELECT schedule_json, registrations_json, status, updated_at FROM roster_schedules WHERE tenant_id = ? AND week_key = ? LIMIT 1",
        (tenant_id, clean_key)
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None

    try:
        data = json.loads(row[0])
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}

    data["status"] = row[2] or data.get("status", "DRAFT")
    data["week_id"] = clean_key
    if row[1] and row[1] != "{}":
        try:
            regs = json.loads(row[1])
            if isinstance(regs, dict) and not data.get("registrations"):
                data["registrations"] = regs
        except Exception:
            pass
    return data


def list_roster_schedules_db(
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    List all week roster schedules keyed by week_key: {week_key: week_dict}.
    """
    conn = get_db_connection(db_path)
    _ensure_v2_operational_tables(conn)
    cur = conn.cursor()
    cur.execute(
        "SELECT week_key, schedule_json, registrations_json, status, updated_at FROM roster_schedules WHERE tenant_id = ? ORDER BY week_key ASC",
        (tenant_id,)
    )
    rows = cur.fetchall()
    conn.close()

    weeks = {}
    for r in rows:
        w_key = str(r[0])
        try:
            w_data = json.loads(r[1])
            if not isinstance(w_data, dict):
                w_data = {}
        except Exception:
            w_data = {}
        w_data["status"] = r[3] or w_data.get("status", "DRAFT")
        w_data["week_id"] = w_key
        if r[2] and r[2] != "{}":
            try:
                regs = json.loads(r[2])
                if isinstance(regs, dict) and not w_data.get("registrations"):
                    w_data["registrations"] = regs
            except Exception:
                pass
        weeks[w_key] = w_data
    return weeks


def migrate_roster_schedules_from_json(
    json_path: Optional[str] = None,
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> int:
    """
    Migrate existing weeks from roster_schedule.json into SQLite table roster_schedules.
    """
    if not json_path:
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        candidates = [
            os.path.join(base_dir, "data", "roster_schedule.json"),
            os.path.join(os.path.dirname(base_dir), "data", "roster_schedule.json"),
        ]
        for c in candidates:
            if os.path.exists(c):
                json_path = c
                break

    if not json_path or not os.path.exists(json_path):
        return 0

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        logger.warning(f"Failed to read roster JSON for migration: {e}")
        return 0

    weeks = raw.get("weeks", {}) if isinstance(raw, dict) else {}
    migrated_count = 0
    for wk, wv in weeks.items():
        if isinstance(wv, dict):
            upsert_roster_schedule_db(wk, wv, tenant_id=tenant_id, db_path=db_path)
            migrated_count += 1
    return migrated_count

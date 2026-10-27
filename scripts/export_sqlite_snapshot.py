#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
FNBOPS - ON-DEMAND SQLITE TO JSON SNAPSHOT EXPORTER
==============================================================================
Trích xuất toàn bộ dữ liệu hiện hành từ SQLite WAL (Single Source of Truth)
ra các tệp JSON snapshot có cấu trúc để phục vụ sao lưu, di trú hoặc đối soát:
- staff_auth.json
- attendance_logs.json
- roster_schedules.json
- daily_closings.json
- evaluations.json
- store_config.json
- so_cai_luong.json
==============================================================================
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
DATA_DIR = PROJECT_ROOT / "data"
SNAPSHOT_DIR = DATA_DIR / "snapshots"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.db import (
    load_staff_auth_from_sqlite,
    list_roster_schedules_db,
    get_daily_closings,
    list_evaluations,
    get_payroll_disbursements_db,
    list_shift_approvals_db,
    get_db_connection
)
from services.attendance_service import load_attendance_logs_from_sqlite
from services.store_config import get_store_config


def export_all_snapshots(target_dir: Path = None):
    out_dir = target_dir or SNAPSHOT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"[*] Bắt đầu xuất snapshot dữ liệu từ SQLite sang: {out_dir}")

    # 1. staff_auth
    staff_auth = load_staff_auth_from_sqlite()
    with open(out_dir / "staff_auth_snapshot.json", "w", encoding="utf-8") as f:
        json.dump(staff_auth, f, ensure_ascii=False, indent=2)
    print(f"  [✓] staff_auth_snapshot.json ({len(staff_auth.get('staff_accounts', {}))} tài khoản)")

    # 2. attendance_logs
    att_logs = load_attendance_logs_from_sqlite()
    with open(out_dir / "attendance_logs_snapshot.json", "w", encoding="utf-8") as f:
        json.dump(att_logs, f, ensure_ascii=False, indent=2)
    print(f"  [✓] attendance_logs_snapshot.json ({len(att_logs)} bản ghi)")

    # 3. roster_schedules
    roster_data = list_roster_schedules_db()
    with open(out_dir / "roster_schedules_snapshot.json", "w", encoding="utf-8") as f:
        json.dump(roster_data, f, ensure_ascii=False, indent=2)
    print(f"  [✓] roster_schedules_snapshot.json ({len(roster_data)} tuần)")

    # 4. daily_closings
    closings = get_daily_closings(limit=1000)
    with open(out_dir / "daily_closings_snapshot.json", "w", encoding="utf-8") as f:
        json.dump(closings, f, ensure_ascii=False, indent=2)
    print(f"  [✓] daily_closings_snapshot.json ({len(closings)} ca kết)")

    # 5. evaluations
    evals = list_evaluations()
    with open(out_dir / "evaluations_snapshot.json", "w", encoding="utf-8") as f:
        json.dump(evals, f, ensure_ascii=False, indent=2)
    print(f"  [✓] evaluations_snapshot.json ({len(evals)} bản ghi)")

    # 6. store_config
    cfg = get_store_config()
    with open(out_dir / "store_config_snapshot.json", "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print(f"  [✓] store_config_snapshot.json (Version: {cfg.get('version', 1)})")

    # 7. so_cai_luong
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM so_cai_luong ORDER BY id ASC")
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        with open(out_dir / "so_cai_luong_snapshot.json", "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        print(f"  [✓] so_cai_luong_snapshot.json ({len(rows)} bút toán)")
    except Exception as e:
        print(f"  [!] Bỏ qua so_cai_luong: {e}")

    # Metadata
    meta = {
        "exported_at": datetime.now().isoformat(),
        "database_source": "data/fnbop.db (SQLite WAL Mode)",
        "generator": "scripts/export_sqlite_snapshot.py"
    }
    with open(out_dir / "snapshot_metadata.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"[V] HOÀN TẤT XUẤT TOÀN BỘ SNAPSHOT VÀO: {out_dir}")


if __name__ == "__main__":
    export_all_snapshots()

# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
SOP (Standard Operating Procedure) Service for FnBOps
Handles loading, caching, and role mapping for staff checklist & operating templates.
"""

import os
import json
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger("sop_service")

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROJECT_DIR = os.path.dirname(_BASE_DIR)

if os.getenv("DATA_DIR"):
    DATA_DIR = os.getenv("DATA_DIR")
elif _PROJECT_DIR and _PROJECT_DIR != "/" and os.path.exists(os.path.join(_PROJECT_DIR, "data")):
    DATA_DIR = os.path.join(_PROJECT_DIR, "data")
else:
    DATA_DIR = os.path.join(_BASE_DIR, "data")

SOP_FILE = os.path.join(DATA_DIR, "sop_templates.json")


def get_sop_file_path() -> Optional[str]:
    sop_candidates = [
        SOP_FILE,
        os.path.join(_PROJECT_DIR, "data", "sop_templates.json"),
        os.path.join(_BASE_DIR, "data", "sop_templates.json"),
        os.path.join(_BASE_DIR, "sop_templates.json")
    ]
    for c in sop_candidates:
        if os.path.exists(c):
            return c
    return None


def load_sop_templates() -> Dict[str, Any]:
    # 1. Primary Source of Truth: Read from SQLite store_settings
    try:
        from services.db import get_store_setting_db
        raw_val = get_store_setting_db("sop_templates")
        if raw_val:
            parsed = json.loads(raw_val)
            if isinstance(parsed, dict) and parsed:
                return parsed
    except Exception as e:
        logger.debug(f"SQLite SOP lookup skipped/fallback: {e}")

    # 2. Seamless Fallback: Read legacy JSON file and bootstrap to SQLite
    target = get_sop_file_path()
    if not target:
        return {}
    try:
        with open(target, "r", encoding="utf-8") as f:
            data = json.load(f)
            if data and isinstance(data, dict):
                try:
                    from services.db import update_store_setting_db
                    update_store_setting_db(
                        "sop_templates",
                        json.dumps(data, ensure_ascii=False, indent=2),
                        label="SOP Templates",
                        description="SOP operational checklist templates"
                    )
                except Exception:
                    pass
            return data
    except Exception as e:
        logger.warning(f"Error loading SOP templates from {target}: {e}")
        return {}


def normalize_sop_role(role: Optional[str], roles_map: Dict[str, Any]) -> str:
    normalized_key = "phuc_vu_trong_nha"
    if not role:
        return normalized_key
    if role in roles_map:
        return role

    r_lower = role.lower()
    if "pha" in r_lower or "barista" in r_lower or "bar" in r_lower:
        return "pha_che"
    elif any(k in r_lower for k in ("ngoai", "ngoài", "san vuon", "sân vườn", "outdoor", "giu xe", "giữ xe")):
        return "phuc_vu_san_vuon"
    elif any(k in r_lower for k in ("thu ngan", "thu ngân", "cashier")):
        return "thu_ngan"
    elif any(k in r_lower for k in ("quan ly", "quản lý", "truong ca", "trưởng ca", "manager")):
        return "truong_ca"
    return "phuc_vu_trong_nha"


def get_sop_by_role(role: Optional[str] = None) -> Dict[str, Any]:
    sop_data = load_sop_templates()
    if not sop_data:
        return {"status": "error", "message": "SOP template file not found"}

    roles_map = sop_data.get("roles", {})
    normalized_key = normalize_sop_role(role, roles_map)
    selected_role_sop = roles_map.get(normalized_key) or roles_map.get("phuc_vu_trong_nha")

    return {
        "status": "success",
        "role_key": normalized_key,
        "sop": selected_role_sop,
        "available_roles": [
            {"key": k, "name": v.get("role_name")} for k, v in roles_map.items()
        ]
    }

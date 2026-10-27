# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
import os
import sys
import json
import logging
import threading
import datetime
from typing import Optional, Dict, Any, Tuple, List

from services.storage import safe_json_write
from services.db import get_store_setting_db

logger = logging.getLogger("roster_service")

_roster_base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_roster_root = os.path.dirname(_roster_base)
DEFAULT_ROSTER_FILE = os.path.join(os.getenv("DATA_DIR", os.path.join(_roster_root, "data")), "roster_schedule.json")
_roster_lock = threading.RLock()


def get_roster_file() -> str:
    if os.getenv("ROSTER_FILE"):
        return os.getenv("ROSTER_FILE")
    if os.getenv("DATA_DIR"):
        return os.path.join(os.getenv("DATA_DIR"), "roster_schedule.json")
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    root_dir = os.path.dirname(base_dir)
    candidates = [
        os.path.join(root_dir, "data", "roster_schedule.json"),
        os.path.join(base_dir, "data", "roster_schedule.json"),
        os.path.join(base_dir, "roster_schedule.json")
    ]
    for p in candidates:
        if os.path.exists(p) and os.path.getsize(p) > 10000:
            return p
    for p in candidates:
        if os.path.exists(p):
            return p
    return os.path.join(root_dir, "data", "roster_schedule.json")


def load_roster_data() -> dict:
    for mod_name in ("routers.roster", "backend.routers.roster", "routers.attendance", "backend.routers.attendance"):
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, "load_roster_data"):
            fn = getattr(mod, "load_roster_data")
            if fn is not load_roster_data and (hasattr(fn, "mock_calls") or hasattr(fn, "return_value")):
                return fn()

    if os.getenv("TESTING") == "1" and os.getenv("ENABLE_RUNTIME_JSON_SYNC") != "false" and os.getenv("ROSTER_FILE"):
        with _roster_lock:
            fpath = os.getenv("ROSTER_FILE")
            if os.path.exists(fpath):
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception:
                    pass

    try:
        from services.db import list_roster_schedules_db, migrate_roster_schedules_from_json
        db_weeks = list_roster_schedules_db()
        if db_weeks:
            return {"weeks": db_weeks}
        migrated = migrate_roster_schedules_from_json()
        if migrated > 0:
            db_weeks = list_roster_schedules_db()
            if db_weeks:
                return {"weeks": db_weeks}
    except Exception as e:
        logger.warning(f"Error loading roster from SQLite: {e}")

    with _roster_lock:
        fpath = get_roster_file()
        if not os.path.exists(fpath):
            return {"weeks": {}}
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading roster file {fpath}: {e}")
            return {"weeks": {}}


def save_roster_data(data: dict) -> bool:
    for mod_name in ("routers.roster", "backend.routers.roster", "routers.attendance", "backend.routers.attendance"):
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, "save_roster_data"):
            fn = getattr(mod, "save_roster_data")
            if fn is not save_roster_data and (hasattr(fn, "mock_calls") or hasattr(fn, "return_value")):
                return fn(data)

    try:
        from services.db import upsert_roster_schedule_db
        weeks = data.get("weeks", {}) if isinstance(data, dict) else {}
        for wk, wv in weeks.items():
            if isinstance(wv, dict):
                upsert_roster_schedule_db(wk, wv)
    except Exception as e:
        logger.warning(f"Error persisting roster data to SQLite: {e}")

    # Test isolation override (only active in TESTING=1 when strict no-json guard is not enforced)
    _real_data_dir = os.path.join(_roster_root, "data")
    roster_env = os.getenv("ROSTER_FILE")
    if (
        os.getenv("TESTING") == "1"
        and os.getenv("ENABLE_RUNTIME_JSON_SYNC") != "false"
        and roster_env
        and not os.path.abspath(roster_env).startswith(_real_data_dir)
    ):
        with _roster_lock:
            os.makedirs(os.path.dirname(roster_env), exist_ok=True)
            return safe_json_write(roster_env, data)

    # Decoupled runtime JSON: Tuyệt đối CẤM GHI file trong data/ trừ khi bật cờ rõ ràng ENABLE_RUNTIME_JSON_SYNC=true
    try:
        from services.storage import is_runtime_json_sync_enabled
        if is_runtime_json_sync_enabled():
            with _roster_lock:
                fpath = get_roster_file()
                os.makedirs(os.path.dirname(fpath), exist_ok=True)
                return safe_json_write(fpath, data)
    except Exception:
        pass

    return True


def get_iso_week_info(target_date: Optional[datetime.date] = None) -> dict:
    d = target_date or datetime.date.today()
    iso_year, iso_week, iso_day = d.isocalendar()
    monday = d - datetime.timedelta(days=iso_day - 1)
    week_id = f"{iso_year}-W{iso_week:02d}"
    days = [(monday + datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
    return {
        "week_id": week_id,
        "year": iso_year,
        "week_num": iso_week,
        "start_date": days[0],
        "end_date": days[6],
        "days": days
    }


def get_active_and_next_week_ids() -> Tuple[dict, dict]:
    now = datetime.datetime.now()
    today = now.date()
    iso_year, iso_week, iso_day = today.isocalendar()

    active_monday = today - datetime.timedelta(days=iso_day - 1)
    next_monday = active_monday + datetime.timedelta(days=7)

    active_info = get_iso_week_info(active_monday)
    next_info = get_iso_week_info(next_monday)
    return active_info, next_info


DAY_KEYS_ISO = ["t2", "t3", "t4", "t5", "t6", "t7", "cn"]

def _extract_day_pref_tags(regs: dict, u: str, d_iso: str, day_idx: int, d_key: str, input_days: Optional[dict] = None) -> List[str]:
    """
    Trích xuất danh sách nhãn đăng ký ca của nhân viên `u` tại ngày `(d_iso, day_idx, d_key)`.
    Hỗ trợ đầy đủ cả chuẩn preferences của roster.py (0..6 / YYYY-MM-DD: MORNING, EVENING_17, EVENING_18, OFF)
    và chuẩn days/shifts (t2..cn: sang, toi, service_17, service_18, barista, service).
    """
    raw_items: List[str] = []
    u_reg = None
    if isinstance(regs, dict):
        u_reg = regs.get(u)
        if u_reg is None:
            for k, v in regs.items():
                if str(k).strip().lower() == u.lower():
                    u_reg = v
                    break
    elif isinstance(regs, list):
        for item in regs:
            if isinstance(item, dict) and str(item.get("username", "")).strip().lower() == u.lower():
                if item.get("date") in [d_iso, d_key] or item.get("day") in [d_iso, d_key, day_idx, str(day_idx)]:
                    if item.get("shift_key"):
                        raw_items.append(str(item.get("shift_key")))
                    if item.get("slot_type"):
                        raw_items.append(str(item.get("slot_type")))
                else:
                    u_reg = item

    if isinstance(u_reg, dict):
        prefs_src = u_reg.get("preferences")
        if not isinstance(prefs_src, dict):
            prefs_src = u_reg.get("availability") if isinstance(u_reg.get("availability"), dict) else (
                u_reg.get("days") if isinstance(u_reg.get("days"), dict) else (
                    u_reg.get("shifts") if isinstance(u_reg.get("shifts"), dict) else u_reg
                )
            )
        p = (
            prefs_src.get(d_iso)
            if d_iso in prefs_src
            else (
                prefs_src.get(d_key)
                if d_key in prefs_src
                else (
                    prefs_src.get(d_key.upper())
                    if d_key.upper() in prefs_src
                    else (
                        prefs_src.get(str(day_idx))
                        if str(day_idx) in prefs_src
                        else prefs_src.get(day_idx, [])
                    )
                )
            )
        )
        if isinstance(p, str):
            raw_items.append(p)
        elif isinstance(p, (list, tuple, set)):
            raw_items.extend([str(x) for x in p])
        elif isinstance(p, dict):
            active_shift_found = False
            for sk, sv in p.items():
                if not sv:
                    continue
                if isinstance(sv, str) and sv.strip().upper() in ["OFF", "NGHI", "NGHỈ", "NONE", "0", "FALSE"]:
                    sk_low = str(sk).strip().lower()
                    if sk_low in ["sang", "morning", "ca_sang", "ca sáng"]:
                        raw_items.append("MORNING_OFF")
                    elif sk_low in ["toi", "evening", "ca_toi", "ca tối", "chieu"]:
                        raw_items.append("EVENING_OFF")
                    continue
                active_shift_found = True
                raw_items.append(str(sk))
                if isinstance(sv, (list, tuple, set)):
                    raw_items.extend([str(x) for x in sv])
                elif isinstance(sv, str) and sv.strip().upper() not in ["PRI", "SUB", "YES", "1", "TRUE"]:
                    raw_items.append(sv)
            if not active_shift_found and p:
                raw_items.append("OFF")

    if isinstance(input_days, dict) and d_key in input_days and isinstance(input_days[d_key], dict):
        d_obj = input_days[d_key]
        for s_k, tag_Out in [("sang", "MORNING"), ("morning", "MORNING"), ("toi", "EVENING"), ("evening", "EVENING")]:
            s_obj = d_obj.get(s_k)
            if isinstance(s_obj, dict):
                s_regs = s_obj.get("registrations") or s_obj.get("candidates") or []
                if isinstance(s_regs, list):
                    for r_item in s_regs:
                        if isinstance(r_item, str) and r_item.strip().lower() == u.lower():
                            raw_items.append(tag_Out)
                        elif isinstance(r_item, dict) and str(r_item.get("username", "")).strip().lower() == u.lower():
                            raw_items.append(tag_Out)
                            if r_item.get("slot_type"):
                                raw_items.append(str(r_item.get("slot_type")))

    norm_tags: List[str] = []
    for item in raw_items:
        t = str(item).strip().upper()
        if not t:
            continue
        if t in ["OFF", "NGHI", "NGHỈ"]:
            norm_tags.append("OFF")
        elif t in ["MORNING", "SANG", "SÁNG", "CA_SANG", "CA SÁNG"]:
            norm_tags.append("MORNING")
        elif t in ["EVENING_17", "SERVICE_17", "TOI_17", "17H", "17:00"]:
            norm_tags.extend(["EVENING", "EVENING_17"])
        elif t in ["EVENING_18", "SERVICE_18", "TOI_18", "18H", "18:00"]:
            norm_tags.extend(["EVENING", "EVENING_18"])
        elif t in ["EVENING", "TOI", "TỐI", "CA_TOI", "CA TỐI", "CHIEU", "CHIỀU"]:
            norm_tags.append("EVENING")
        elif t in ["ALL", "FULL", "BOTH", "CA_NGAY", "CẢ NGÀY"]:
            norm_tags.extend(["MORNING", "EVENING"])
        else:
            norm_tags.append(t)
    return norm_tags


def is_week_registration_open(target_week_id: str, week_entry: Optional[dict] = None) -> Tuple[bool, str]:
    """
    Quy định mở/đóng cổng đăng ký ca tuần mới (FnBOps):
    1. Cổng mở tự do 24/7 cho DUY NHẤT tuần kế tiếp (next_week).
    2. Tự động khóa tuần kế tiếp khi:
       - Chạm mốc 18:00 Chủ Nhật hàng tuần (thời điểm chốt tuần & nhảy lịch).
       - Hoặc Quản lý đã bấm Công bố lịch (status == "PUBLISHED").
    3. Tuần hiện tại (active_week) và các tuần cũ: Luôn KHÓA đối với nhân viên thường.
    """
    if os.getenv("ROSTER_FORCE_REGISTRATION_OPEN") == "1":
        return True, "Cổng mở cưỡng bức theo cấu hình hệ thống"

    if get_store_setting_db("roster_registration_open", "1") == "0":
        return False, "Cổng đăng ký lịch ca tuần mới đang tạm thời bị Quản lý khóa"

    active_info, next_info = get_active_and_next_week_ids()
    active_id = active_info["week_id"]
    next_id = next_info["week_id"]

    # 1. Tuần hiện tại đang chạy hoặc tuần cũ -> Đã khóa
    if target_week_id == active_id:
        return False, f"Tuần {target_week_id} là tuần hiện tại đang diễn ra (đã khóa đăng ký ca)"

    # 2. Tuần ngoài phạm vi tuần kế tiếp
    if target_week_id != next_id:
        return False, f"Cổng chỉ mở đăng ký cho tuần kế tiếp ({next_id})"

    # 3. Đã công bố lịch chính thức
    if week_entry and week_entry.get("status") == "PUBLISHED":
        return False, f"Lịch ca tuần {target_week_id} đã được công bố chính thức (đã khóa đăng ký)"

    # 4. Tự động khóa nộp lịch tuần mới nếu đã qua 18:00 Chủ Nhật hàng tuần
    now = datetime.datetime.now()
    if now.date().isocalendar()[2] == 7 and now.hour >= 18:
        return False, f"Cổng đăng ký ca tuần {target_week_id} đã tự động khóa lúc 18:00 Chủ Nhật để Quản lý chốt ca"

    return True, "Cổng đăng ký đang mở tự do"


def is_registration_window_open(target_week_id: Optional[str] = None, week_entry: Optional[dict] = None) -> bool:
    if not target_week_id:
        _, next_info = get_active_and_next_week_ids()
        target_week_id = next_info["week_id"]
    is_open, _ = is_week_registration_open(target_week_id, week_entry)
    return is_open


def validate_service_gender_pair(
    staff1_uname: Optional[str],
    staff2_uname: Optional[str],
    accounts: dict,
    shift_key: Optional[str] = None,
    allow_relaxation: bool = False
) -> tuple:
    """
    Ràng buộc giới tính & thể lực (nếu quán kích hoạt trong store_config):
    Mỗi ca phục vụ: BẮT BUỘC ÍT NHẤT 1 NAM (nếu ca đó được kích hoạt kiểm tra).
    Nếu cấu hình quán tắt ràng buộc giới tính (enabled: False) hoặc allow_relaxation=True -> cho phép mọi tổ hợp.
    """
    if not staff1_uname or not staff2_uname:
        return True, ""

    try:
        from services.store_config import get_store_config
        cfg = get_store_config()
        g_cfg = cfg.get("roster_rules", {}).get("gender_constraints", {})
        if not g_cfg.get("enabled", True):
            return True, ""
        if shift_key:
            shift_rules = g_cfg.get("shifts")
            if isinstance(shift_rules, dict):
                norm_k = str(shift_key).lower()
                k_match = "sang" if norm_k in ["morning", "sang"] else ("chieu" if norm_k in ["afternoon", "chieu"] else ("toi" if norm_k in ["evening", "toi"] else norm_k))
                if k_match in shift_rules and not shift_rules[k_match]:
                    return True, ""
    except Exception:
        pass
    
    g1 = accounts.get(staff1_uname, {}).get("gender", "NAM").upper()
    g2 = accounts.get(staff2_uname, {}).get("gender", "NAM").upper()

    if g1 == "NU" and g2 == "NU":
        if allow_relaxation:
            return True, "Nới lỏng ràng buộc thể lực (quán nhỏ / thiếu nhân sự nam)"
        name1 = accounts.get(staff1_uname, {}).get("full_name", staff1_uname)
        name2 = accounts.get(staff2_uname, {}).get("full_name", staff2_uname)
        return False, f"Vi phạm quy định thể lực: Ca phục vụ có 2 Nữ ({name1}, {name2}). Bắt buộc phải có ít nhất 1 Nam để dọn dẹp, bưng bê nặng!"
    
    return True, ""


def is_bar_capable(acc: dict) -> bool:
    """
    Kiểm tra nhân sự có đủ năng lực / được cấp quyền làm Bar/Pha chế hay không:
    - Có 'BAR' trong allowed_roles (hoặc roles/skills)
    - Hoặc vị trí (position) là Bar / Pha chế
    - Hoặc primary_role là BAR
    """
    if not isinstance(acc, dict):
        return False
    raw_roles = acc.get("allowed_roles") if acc.get("allowed_roles") is not None else (acc.get("roles") if acc.get("roles") is not None else acc.get("skills"))
    allowed = [str(r).strip().upper() for r in (raw_roles or []) if r]
    if "BAR" in allowed or "BARISTA" in allowed or "PHA_CHE" in allowed or "PHA CHẾ" in allowed:
        return True
    if raw_roles is not None:
        return False
    pos = str(acc.get("position", "")).strip().lower()
    if "pha" in pos or "bar" in pos:
        return True
    primary = str(acc.get("primary_role", "")).strip().upper()
    if primary in ["BAR", "BARISTA"]:
        return True
    role_val = str(acc.get("role", "")).strip().upper()
    if role_val in ["BAR", "BARISTA"]:
        return True
    return False


def is_service_capable(acc: dict) -> bool:
    """
    Kiểm tra nhân sự có đủ năng lực / được cấp quyền làm Phục vụ (Service) hay không:
    - Có 'SERVICE' trong allowed_roles (hoặc roles/skills)
    - Hoặc vị trí không phải Bar chuyên biệt hay Giữ xe
    """
    if not isinstance(acc, dict):
        return False
    raw_roles = acc.get("allowed_roles") if acc.get("allowed_roles") is not None else (acc.get("roles") if acc.get("roles") is not None else acc.get("skills"))
    allowed = [str(r).strip().upper() for r in (raw_roles or []) if r]
    if any(k in allowed for k in ["SERVICE", "PHUC_VU", "PHỤC VỤ", "SERVICE_17", "SERVICE_18"]):
        return True
    if raw_roles is not None:
        return False
    pos = str(acc.get("position", "")).strip().lower()
    if "giu xe" in pos or "giữ xe" in pos or "security" in pos:
        return False
    if ("pha" in pos or "bar" in pos) and "phục vụ" not in pos and "service" not in pos:
        return False
    primary = str(acc.get("primary_role", "")).strip().upper()
    if primary in ["BAR", "BARISTA", "SECURITY"]:
        return False
    role_val = str(acc.get("role", "")).strip().upper()
    if role_val in ["BAR", "BARISTA", "SECURITY"]:
        return False
    return True


def get_primary_role(acc: dict) -> str:
    """
    Xác định vai trò chính của nhân sự: 'BAR' hoặc 'SERVICE'
    """
    if not isinstance(acc, dict):
        return "SERVICE"
    primary = str(acc.get("primary_role", "")).strip().upper()
    if primary in ["BAR", "BARISTA"]:
        return "BAR"
    if primary in ["SERVICE", "PHUC_VU", "PHỤC VỤ"]:
        return "SERVICE"
    pos = str(acc.get("position", "")).strip().lower()
    if "pha" in pos or "bar" in pos:
        return "BAR"
    return "SERVICE"


# ==============================================================================
# ADR-008: SKILL-COVERAGE BITMASK CONSTANTS & HELPERS FOR SMALL STORES (2-5 STAFF)
# ==============================================================================
SKILL_BAR = 1        # 0b0001 (Pha chế / Barista)
SKILL_SERVICE = 2    # 0b0010 (Phục vụ / Service)
SKILL_CASHIER = 4    # 0b0100 (Thu ngân / Cashier)
SKILL_MANAGER = 8    # 0b1000 (Quản lý / Manager)
SKILL_SECURITY = 16  # 0b10000 (Bảo vệ / Giữ xe)

ALL_SKILLS_MAP = {
    "BAR": SKILL_BAR,
    "BARISTA": SKILL_BAR,
    "PHA_CHE": SKILL_BAR,
    "PHA CHẾ": SKILL_BAR,
    "SERVICE": SKILL_SERVICE,
    "PHUC_VU": SKILL_SERVICE,
    "PHỤC VỤ": SKILL_SERVICE,
    "CASHIER": SKILL_CASHIER,
    "THU_NGAN": SKILL_CASHIER,
    "THU NGÂN": SKILL_CASHIER,
    "MANAGER": SKILL_MANAGER,
    "QUAN_LY": SKILL_MANAGER,
    "QUẢN LÝ": SKILL_MANAGER,
    "SECURITY": SKILL_SECURITY,
    "GIU_XE": SKILL_SECURITY,
    "BẢO VỆ": SKILL_SECURITY,
    "BAO_VE": SKILL_SECURITY,
}


def compute_staff_skill_mask(acc: dict) -> int:
    """
    Tính toán 5-bit SkillMask của nhân sự:
    - Bit 0 (1): BAR / Barista
    - Bit 1 (2): SERVICE / Phục vụ
    - Bit 2 (4): CASHIER / Thu ngân
    - Bit 3 (8): MANAGER / Quản lý
    - Bit 4 (16): SECURITY / Giữ xe
    """
    if not isinstance(acc, dict):
        return 0

    if isinstance(acc.get("skill_mask"), int):
        return acc["skill_mask"]

    mask = 0

    # 1. Barista / Pha chế
    if is_bar_capable(acc):
        mask |= SKILL_BAR

    # 2. Phục vụ / Service
    if is_service_capable(acc):
        mask |= SKILL_SERVICE

    # 3. Thu ngân / Cashier
    raw_roles = acc.get("allowed_roles") or acc.get("roles") or acc.get("skills") or []
    allowed = [str(r).strip().upper() for r in raw_roles if r]
    pos = str(acc.get("position", "")).strip().lower()
    if any(k in allowed for k in ["CASHIER", "THU_NGAN", "THU NGÂN"]) or "thu ngân" in pos or "cashier" in pos:
        mask |= SKILL_CASHIER

    # 4. Quản lý / Manager
    role_val = str(acc.get("role", "")).strip().upper()
    if role_val in ["ADMIN", "MANAGER"] or any(k in allowed for k in ["MANAGER", "QUAN_LY", "QUẢN LÝ"]) or "quản lý" in pos:
        mask |= SKILL_MANAGER

    # 5. Bảo vệ / Giữ xe
    if any(k in allowed for k in ["SECURITY", "GIU_XE", "BẢO VỆ", "BAO_VE"]) or "giữ xe" in pos or "bảo vệ" in pos or "security" in pos:
        mask |= SKILL_SECURITY

    # Mặc định nhân viên thường có ít nhất SKILL_SERVICE nếu chưa nhận diện được gì
    if mask == 0 and role_val in ["STAFF", "NHAN_VIEN", ""]:
        mask |= SKILL_SERVICE

    return mask


def check_skill_coverage(assigned_staff_list: List[str], accounts: dict, required_mask: int) -> Tuple[bool, int, float]:
    """
    Kiểm tra độ bao phủ kỹ năng của danh sách nhân sự được xếp trong ca:
    Trả về (is_covered, combined_mask, coverage_ratio):
    - is_covered: True nếu (combined_mask & required_mask) == required_mask
    - combined_mask: Tổng bitmask OR của toàn bộ nhân sự trong ca
    - coverage_ratio: Tỷ lệ hoàn thành (0.0 đến 1.0)
    """
    combined_mask = 0
    for u in assigned_staff_list:
        if u and u in accounts:
            combined_mask |= compute_staff_skill_mask(accounts[u])

    if required_mask == 0:
        return True, combined_mask, 1.0

    covered_bits = combined_mask & required_mask
    req_count = bin(required_mask).count("1")
    cov_count = bin(covered_bits).count("1")
    ratio = round(cov_count / req_count, 2) if req_count > 0 else 1.0
    return (covered_bits == required_mask), combined_mask, ratio


def check_and_auto_publish_roster_deadline(now: Optional[datetime.datetime] = None) -> Optional[dict]:
    """
    Sunday 12:00 PM auto-publish rule:
    If next_week roster is still in DRAFT after Sunday 12:00 PM and auto_publish_enabled is True,
    automatically promote status to PUBLISHED (`SYSTEM_AUTO_DEADLINE_12PM`).
    """
    if now is None:
        now = datetime.datetime.now()

    iso_day = now.date().isocalendar()[2]
    if iso_day == 7 and (now.hour > 12 or (now.hour == 12 and now.minute >= 0)):
        from services.store_config import get_store_config
        cfg = get_store_config()
        r_rules = cfg.get("roster_rules", {})
        pub_cfg = r_rules.get("publishing_deadline", {})
        if pub_cfg.get("auto_publish_enabled", True):
            _, next_info = get_active_and_next_week_ids()
            next_week_id = next_info["week_id"]

            roster_data = load_roster_data()
            weeks = roster_data.get("weeks", {})
            next_entry = weeks.get(next_week_id)
            if next_entry and next_entry.get("status") != "PUBLISHED":
                shifts = next_entry.get("shifts", {})
                if shifts:
                    next_entry["status"] = "PUBLISHED"
                    next_entry["published_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
                    next_entry["published_by"] = "SYSTEM_AUTO_DEADLINE_12PM"
                    save_roster_data(roster_data)
                    return next_entry
    return None





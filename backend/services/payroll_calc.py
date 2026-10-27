# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
Payroll & Penalty Calculation Engine (Server-Side)
FnBOps Lounge / FNBOPS.LOCAL
Enforces Zero-Trust Architecture: Business logic and financial rules live on the server.
"""

from typing import List, Dict, Any, Tuple, Optional
import math
import unicodedata
import re

POLICY_STANDARD_SHIFT_MINS = 300       # 5 hours
POLICY_OT_BUFFER_MINS = 30            # 30 mins buffer
POLICY_EXCESS_THRESHOLD_MINS = 331     # >= 331 mins requires Manager approval

POLICY_LATE_THRESHOLD_WARN = 10        # Mins late to count into progressive counter
POLICY_LATE_THRESHOLD_INSTANT_FINE = 30 # Mins late for instant fine
POLICY_LATE_INSTANT_FINE_AMOUNT = 50000 # 50,000 VND per instant fine

POLICY_LATE_PENALTIES = [
    {"count": 1, "action": "warn", "amount": 0, "label": "Cảnh báo lần 1"},
    {"count": 2, "action": "warn", "amount": 0, "label": "Cảnh báo lần 2"},
    {"count": 3, "action": "fine", "amount": 50000, "label": "Phạt 50,000đ"},
    {"count": 4, "action": "fine", "amount": 150000, "label": "Phạt 150,000đ"},
    {"count": 5, "action": "terminate", "amount": 0, "label": "Cảnh báo đỏ - Cho nghỉ"}
]


def normalize_str(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize('NFD', str(s))
    s = ''.join([c for c in s if unicodedata.category(c) != 'Mn'])
    s = re.sub(r'[^a-zA-Z0-9]', '', s)
    return s.lower()


def calculate_progressive_late_penalties(late_minutes_list: List[int], month: Optional[str] = None) -> Tuple[int, List[str]]:
    """
    Server-side implementation of progressive discipline late deduction.
    Month '8' is exempt from fines per historical agreement.
    """
    if not month:
        import datetime
        month = str(datetime.datetime.now().month)
    enable_penalties = (str(month).strip() != "8")
    if not enable_penalties or not late_minutes_list:
        return 0, []

    total_penalty = 0
    penalty_details = []

    late_over_10_count = sum(1 for m in late_minutes_list if m > POLICY_LATE_THRESHOLD_WARN)
    late_over_30_count = sum(1 for m in late_minutes_list if m > POLICY_LATE_THRESHOLD_INSTANT_FINE)

    # 1. Instant fine for shifts late > 30 minutes
    if late_over_30_count > 0:
        instant_fine = late_over_30_count * POLICY_LATE_INSTANT_FINE_AMOUNT
        total_penalty += instant_fine
        penalty_details.append(f"Trễ >30p: {late_over_30_count} lần × {POLICY_LATE_INSTANT_FINE_AMOUNT:,}đ")

    # 2. Progressive penalties for shifts late > 10 minutes
    for i in range(1, min(late_over_10_count + 1, len(POLICY_LATE_PENALTIES) + 1)):
        rule = POLICY_LATE_PENALTIES[i - 1]
        if rule["action"] == "fine":
            total_penalty += rule["amount"]
            penalty_details.append(f"Lần {i}: Phạt {rule['amount']:,}đ ({rule['label']})")
        elif rule["action"] == "terminate":
            penalty_details.append(f"Lần {i}: CẢNH BÁO ĐỎ - CHO NGHỈ")

    return total_penalty, penalty_details


def parse_shift_duration_minutes(start_time_str: str, end_time_str: str) -> int:
    """Parses HH:MM or HH:MM:SS strings into total worked minutes."""
    try:
        sp = str(start_time_str).strip().split(":")
        ep = str(end_time_str).strip().split(":")
        start_min = int(sp[0]) * 60 + int(sp[1])
        end_min = int(ep[0]) * 60 + int(ep[1])
        if end_min < start_min:
            end_min += 24 * 60
        return max(0, end_min - start_min)
    except Exception:
        return 0


def get_canonical_name(raw_name: str, staff_accounts: Optional[Dict[str, Any]] = None) -> str:
    """
    Chuẩn hóa tên nhân viên đồng bộ với Frontend & SQLite:
    - Tra cứu động 100% từ staff_accounts / aliases / sheet_names.
    - Tuyệt đối không hardcode tên cá nhân.
    """
    if not raw_name:
        return ""
    s = unicodedata.normalize("NFC", str(raw_name).strip().rstrip(":").strip().upper())

    accounts = staff_accounts
    if accounts is None:
        try:
            try:
                from backend.services.db import get_staff_directory_map
            except ImportError:
                from services.db import get_staff_directory_map
            accounts = get_staff_directory_map()
        except Exception:
            accounts = {}
        try:
            try:
                from backend.services.auth import load_staff_auth
            except ImportError:
                from services.auth import load_staff_auth
            auth_data = load_staff_auth()
            auth_accs = auth_data.get("staff_accounts", {}) if isinstance(auth_data, dict) else {}
            if not accounts:
                accounts = auth_accs
            else:
                for u, a_info in auth_accs.items():
                    if isinstance(a_info, dict) and u in accounts:
                        if not accounts[u].get("sheet_names") and a_info.get("sheet_names"):
                            accounts[u]["sheet_names"] = a_info["sheet_names"]
                        if a_info.get("aliases"):
                            curr_al = accounts[u].setdefault("aliases", [])
                            for al in a_info["aliases"]:
                                if al not in curr_al:
                                    curr_al.append(al)
        except Exception:
            pass

    if accounts and isinstance(accounts, dict):
        for uname, acc in accounts.items():
            if not isinstance(acc, dict):
                continue
            eid = str(acc.get("employee_id") or "").strip().upper()
            fn = unicodedata.normalize("NFC", str(acc.get("full_name") or "").strip().upper())
            sheet_names = [unicodedata.normalize("NFC", str(sn).strip().upper()) for sn in (acc.get("sheet_names") or []) if sn]
            aliases = [unicodedata.normalize("NFC", str(al).strip().upper()) for al in (acc.get("aliases") or []) if al]
            canonical_rep = sheet_names[0] if sheet_names else (fn or uname.upper())
            if s == eid and eid:
                return canonical_rep
            if s in sheet_names or s == fn or s == uname.upper() or s in aliases:
                return canonical_rep
    return s


def resolve_employee_id_from_accounts(raw_name: str, staff_accounts: Optional[Dict[str, Any]] = None) -> str:
    """
    Tra cứu mã định danh nhân viên chuẩn (EMP_001, EMP_002...) từ tên ca, username hoặc alias.
    """
    if not raw_name:
        return ""
    target_canon = get_canonical_name(raw_name, staff_accounts)
    target_norm = normalize_str(raw_name)

    accounts = staff_accounts or {}
    if not accounts:
        try:
            try:
                from backend.services.db import get_staff_directory_map
            except ImportError:
                from services.db import get_staff_directory_map
            accounts = get_staff_directory_map()
        except Exception:
            accounts = {}
        try:
            try:
                from backend.services.auth import load_staff_auth
            except ImportError:
                from services.auth import load_staff_auth
            auth_data = load_staff_auth()
            auth_accs = auth_data.get("staff_accounts", {}) if isinstance(auth_data, dict) else {}
            if not accounts:
                accounts = auth_accs
            else:
                for u, a_info in auth_accs.items():
                    if isinstance(a_info, dict) and u in accounts:
                        if not accounts[u].get("sheet_names") and a_info.get("sheet_names"):
                            accounts[u]["sheet_names"] = a_info["sheet_names"]
                        if a_info.get("aliases"):
                            curr_al = accounts[u].setdefault("aliases", [])
                            for al in a_info["aliases"]:
                                if al not in curr_al:
                                    curr_al.append(al)
        except Exception:
            pass

    for idx, (uname, acc) in enumerate(accounts.items(), start=1):
        if not isinstance(acc, dict):
            continue
        eid = str(acc.get("employee_id") or f"EMP_{idx:03d}").strip()
        if eid.upper() == target_canon:
            return eid
        acc_fn = acc.get("full_name") or ""
        sheet_names = acc.get("sheet_names") or []
        aliases = acc.get("aliases") or []
        all_candidates = [uname, acc_fn] + list(sheet_names) + list(aliases)
        for cand in all_candidates:
            if not cand:
                continue
            if get_canonical_name(str(cand), accounts) == target_canon:
                return eid
            # So khớp không dấu an toàn (bảo vệ các tên phân biệt bởi dấu thanh)
            c_up = unicodedata.normalize("NFC", str(cand).strip().upper())
            if normalize_str(str(cand)) == target_norm and target_norm:
                # Nếu cả 2 đều có dấu tiếng Việt mà khác nhau thì không gộp
                has_mark_cand = any(ch in c_up for ch in "ẠẢÃÀÁÂẬẦẤẨẪĂẮẰẲẴẶẸẺẼÈÉÊỆỀẾỂỄỊỈĨÌÍỌỎÕÒÓÔỘỒỐỔỖƠỢỜỚỞỠỤỦŨÙÚƯỰỪỨỬỮỲÝỴỶỸĐ")
                has_mark_target = any(ch in target_canon for ch in "ẠẢÃÀÁÂẬẦẤẨẪĂẮẰẲẴẶẸẺẼÈÉÊỆỀẾỂỄỊỈĨÌÍỌỎÕÒÓÔỘỒỐỔỖƠỢỜỚỞỠỤỦŨÙÚƯỰỪỨỬỮỲÝỴỶỸĐ")
                if has_mark_cand and has_mark_target and c_up != target_canon:
                    continue
                return eid
    return ""


def is_holiday_date(date_str: str) -> bool:
    """
    Xác định ngày lễ được nhân đôi lương (x2.0).
    Ưu tiên đọc cấu hình động từ store_config.json.
    Mặc định: Duy nhất ngày Lễ 2/9.
    """
    if not date_str:
        return False
    try:
        from services.store_config import is_configured_holiday
        return is_configured_holiday(date_str)
    except Exception:
        pass
    d = str(date_str).strip()
    if "/" in d:
        parts = d.split("/")
        return len(parts) >= 2 and int(parts[0]) == 2 and int(parts[1]) == 9
    elif "-" in d:
        parts = d.split("-")
        return len(parts) >= 3 and int(parts[1]) == 9 and int(parts[2]) == 2
    return False


def get_canonical_ledger_category(raw_type: str) -> str:
    t = normalize_str(str(raw_type or ""))
    if "thuong" in t or "bonus" in t:
        return "bonus"
    elif "ung" in t or "advance" in t:
        return "advance"
    elif "phat" in t or "fine" in t or "tru" in t or "deduction" in t or "vi pham" in t:
        return "deduction"
    return "advance"


def get_shift_standard_mins(shift_name: str, checkin_str: Optional[str] = None, date_str: Optional[str] = None) -> int:
    """
    Xác định thời lượng chuẩn của ca (phút):
    - Tự động tra cứu phiên bản cấu hình ca theo ngày làm việc (Immutable Versioning - ADR-007)
    - Ca sáng (06:00 - 11:30): chuẩn 330 phút (5.5h).
    - Ca tối vào từ 17h (17:00 - 23:00): chuẩn 360 phút (6.0h).
    - Ca tối vào từ 18h (18:00 - 23:00): chuẩn 300 phút (5.0h).
    - Mặc định: 300 phút.
    """
    s_norm = normalize_str(shift_name)
    cin_mins = None
    if checkin_str:
        try:
            parts = str(checkin_str).strip().split(":")
            if len(parts) >= 2:
                cin_mins = int(parts[0]) * 60 + int(parts[1])
        except Exception:
            pass

    # 0. Check dynamic store configuration (supporting historical shift versions)
    try:
        try:
            from backend.services.store_config import get_store_config, get_shift_config_at
        except ImportError:
            from services.store_config import get_store_config, get_shift_config_at

        shifts_cfg = None
        if date_str:
            shifts_cfg = get_shift_config_at(date_str)
        if not shifts_cfg:
            cfg = get_store_config()
            shifts_cfg = cfg.get("shifts", {})
        for sk, sdata in shifts_cfg.items():
            # Check staggered service slots first (e.g. 18h vs 17h)
            for stag in sdata.get("staggered_service", []):
                slot_name = stag.get("slot", "")
                if (slot_name in s_norm) or ("18" in s_norm and "18" in slot_name) or ("17" in s_norm and "17" in slot_name):
                    return int(stag.get("standard_mins", 300))
            if sk in s_norm or normalize_str(sdata.get("name", "")) in s_norm:
                # If specific 18h indicator is present in evening shift, defer to staggered 18h
                if "18" in s_norm and ("toi" in s_norm or "evening" in s_norm):
                    return 300
                if cin_mins is not None and cin_mins >= 17 * 60 + 30 and ("toi" in s_norm or "evening" in s_norm):
                    return 300
                std_mins = sdata.get("standard_mins")
                if std_mins and isinstance(std_mins, (int, float)):
                    return int(std_mins)
    except Exception:
        pass

    # 1. Ca sáng (06:00 - 11:30): chuẩn 330 phút (5.5h)
    if "sang" in s_norm or "morning" in s_norm:
        return 330
    if cin_mins is not None and cin_mins < 12 * 60:
        return 330

    # 2. Ca tối
    # Ưu tiên nhận diện từ tên ca nếu có chỉ định 17h hoặc 18h
    if "17" in s_norm:
        return 360
    if "18" in s_norm:
        return 300

    # Nếu tên ca chung (ví dụ: 'Tối', 'Chiều', 'Ca Tối'), dựa vào giờ check-in thực tế:
    # Check-in trước 17:30 -> Ca tối 17h (17:00 - 23:00): chuẩn 360 phút
    # Check-in từ 17:30 trở đi -> Ca tối 18h (18:00 - 23:00): chuẩn 300 phút
    if cin_mins is not None:
        if cin_mins < 17 * 60 + 30:
            return 360
        else:
            return 300

    return POLICY_STANDARD_SHIFT_MINS


def get_configured_role_rates(store_config: Optional[Dict[str, Any]] = None) -> Dict[str, int]:
    """
    Lấy cấu hình giá lương theo vai trò ca:
    - BAR: mặc định 17.000đ/h
    - SERVICE: mặc định 17.000đ/h
    """
    if store_config and "role_rates" in store_config:
        rates = store_config.get("role_rates") or {}
        return {
            "BAR": int(rates.get("BAR", 17000)),
            "SERVICE": int(rates.get("SERVICE", 17000))
        }
    try:
        try:
            from backend.services.store_config import get_role_rates
        except ImportError:
            from services.store_config import get_role_rates
        return get_role_rates(store_config)
    except Exception:
        return {"BAR": 17000, "SERVICE": 17000}


def resolve_shift_role(
    shift_info: Dict[str, Any],
    emp_canonical: str,
    date_str: str,
    shift_name: str
) -> str:
    """
    Xác định vai trò của ca làm việc ('BAR' hoặc 'SERVICE'):
    1. shift_role ghi nhận trực tiếp ('BAR' hoặc 'SERVICE')
    2. roster_slot hoặc slot ('barista' -> BAR; 'service', 'service_17', 'service_18' -> SERVICE)
    3. role field ('barista', 'bar', 'pha che' -> BAR; 'service', 'phuc vu' -> SERVICE)
    4. Tra cứu slot đã xếp trong roster_schedule.json
    5. Ghi chú ca nếu có
    6. Mặc định 'SERVICE' nếu không ghi nhận
    """
    # 1. Trực tiếp từ shift_role
    sr = shift_info.get("shift_role")
    if sr:
        sr_clean = str(sr).strip().upper()
        if sr_clean in ["BAR", "BARISTA"]:
            return "BAR"
        if sr_clean in ["SERVICE", "PHUC VU", "PHỤC VỤ"]:
            return "SERVICE"

    # 2. Từ roster_slot hoặc slot
    r_slot = shift_info.get("roster_slot") or shift_info.get("slot")
    if r_slot:
        rs_clean = str(r_slot).strip().lower()
        if "barista" in rs_clean or rs_clean == "bar":
            return "BAR"
        if any(s in rs_clean for s in ["service", "service_17", "service_18", "phuc vu"]):
            return "SERVICE"

    # 3. Từ role
    r_field = shift_info.get("role")
    if r_field:
        rf_clean = str(r_field).strip().lower()
        rf_norm = normalize_str(rf_clean)
        if "barista" in rf_clean or "bar" in rf_clean or "pha che" in rf_norm:
            return "BAR"
        if "service" in rf_clean or "phuc vu" in rf_norm:
            return "SERVICE"

    # 4. Tra cứu slot từ roster_schedule.json
    try:
        try:
            from services.attendance_service import get_staff_roster_slot
        except ImportError:
            from backend.services.attendance_service import get_staff_roster_slot
        s_norm = normalize_str(shift_name)
        s_key = "sang" if "sang" in s_norm else "toi"
        slot_data = get_staff_roster_slot(emp_canonical, date_str, s_key)
        if slot_data and isinstance(slot_data, dict):
            st = str(slot_data.get("slot_type") or "").strip().lower()
            if "barista" in st or st == "bar":
                return "BAR"
            if any(s in st for s in ["service", "service_17", "service_18"]):
                return "SERVICE"
    except Exception:
        pass

    # 5. Note / Ghi chú
    note = shift_info.get("note") or ""
    if note:
        n_norm = normalize_str(str(note))
        if "barista" in n_norm or "bar" in n_norm or "pha che" in n_norm:
            return "BAR"
        if "service" in n_norm or "phuc vu" in n_norm:
            return "SERVICE"

    # 6. Fallback tương thích ngược
    return "SERVICE"


def calculate_staff_payslip_breakdown(
    staff_name: str,
    month: Optional[str] = None,
    data_json: Optional[Dict[str, Any]] = None,
    shift_approvals: Optional[Dict[str, Any]] = None,
    evaluations: Optional[List[Dict[str, Any]]] = None,
    attendance_logs: Optional[List[Dict[str, Any]]] = None,
    staff_ledgers: Optional[List[Dict[str, Any]]] = None,
    staff_accounts: Optional[Dict[str, Any]] = None,
    store_config: Optional[Dict[str, Any]] = None,
    role_rates: Optional[Dict[str, int]] = None,
    so_cai_luong: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Computes complete, tamper-proof payroll breakdown on Server-side.
    Integrates dynamic accounts (SQLite / staff_auth), static sheets (data.json),
    shift approvals, realtime attendance logs, and server-side SQLite staff ledgers (Sổ Phụ).
    """
    import datetime
    if not month:
        month = str(datetime.datetime.now().month)

    staff_accounts = staff_accounts or {}
    target_canonical = get_canonical_name(staff_name, staff_accounts)
    data_json = data_json or {}
    shift_approvals = shift_approvals or {}
    evaluations = evaluations or []
    attendance_logs = attendance_logs or []
    staff_ledgers = staff_ledgers or []

    # 1. Look up Base Wage: Priority 1: staff_accounts profile (SQLite / Auth), Priority 2: NHÂN VIÊN table
    base_wage = 17000 # default
    full_display_name = staff_name
    found_wage_in_accounts = False

    salary_type = "HOURLY"
    fixed_salary = 0

    for uname, acc in staff_accounts.items():
        acc_fn = acc.get("full_name") or ""
        aliases = acc.get("aliases") or []
        alias_canonicals = [get_canonical_name(al, staff_accounts) for al in aliases]
        if (get_canonical_name(uname, staff_accounts) == target_canonical or
            get_canonical_name(acc_fn, staff_accounts) == target_canonical or
            target_canonical in alias_canonicals):
            full_display_name = acc_fn if acc_fn else staff_name
            salary_type = str(acc.get("salary_type") or "HOURLY").upper()
            fixed_salary = int(acc.get("fixed_salary") or 0)
            rate = acc.get("hourly_rate")
            if rate and int(rate) > 0:
                base_wage = int(rate)
                found_wage_in_accounts = True
                break

    if not found_wage_in_accounts:
        nv_tab = data_json.get("NHÂN VIÊN", [])
        for row in nv_tab[2:]:
            # Col 1: Name, Col 3: Wage/hr
            if len(row) > 1 and get_canonical_name(str(row[1]), staff_accounts) == target_canonical:
                full_display_name = str(row[1]).strip()
                if len(row) > 3 and row[3]:
                    try:
                        w = int(float(str(row[3]).replace(",", "").replace(".", "").strip()))
                        if w > 0:
                            base_wage = w
                    except Exception:
                        pass
                break

    # 1.1 Role-based shift rates & Grandfathered personal wage
    configured_rates = role_rates or get_configured_role_rates(store_config)
    cfg_bar_rate = int(configured_rates.get("BAR", 17000))
    cfg_service_rate = int(configured_rates.get("SERVICE", 17000))

    # Nếu không có cấu hình role_rates riêng biệt, toàn bộ ca tính theo base_wage của nhân sự
    has_custom_role_rates = bool(role_rates or (store_config and "role_rates" in store_config))
    if not has_custom_role_rates:
        role_bar_rate = base_wage
        role_service_rate = base_wage
    else:
        role_bar_rate = max(cfg_bar_rate, base_wage)
        role_service_rate = max(cfg_service_rate, base_wage)

    # 2. Iterate DỮ LIỆU for shifts, hours, OT and late arrivals
    du_lieu = data_json.get("DỮ LIỆU", [])
    total_worked_minutes = 0
    total_standard_cost = 0.0
    total_ot_cost = 0.0
    total_shifts = 0
    late_minutes_list = []
    shift_records = []
    seen_shifts = set()

    count_bar = 0
    hours_bar = 0.0
    count_service = 0
    hours_service = 0.0

    for row in du_lieu[1:]:
        if len(row) < 6:
            continue
        date_str, emp_name, shift_name, checkin, checkout = row[1], row[2], row[3], row[4], row[5]
        if not date_str or not emp_name:
            continue

        emp_canonical = get_canonical_name(emp_name, staff_accounts)
        if emp_canonical != target_canonical:
            continue

        # Check month if specified (e.g. '09' or '9')
        if month and month.lower() != "all":
            row_month = str(row[8]).strip() if len(row) > 8 and str(row[8]).strip() else ""
            if row_month:
                if int(row_month) != int(month):
                    continue
            else:
                try:
                    if "/" in str(date_str):
                        parts = str(date_str).strip().split("/")
                        if len(parts) >= 2 and int(parts[1]) != int(month):
                            continue
                    elif "-" in str(date_str):
                        parts = str(date_str).strip().split("-")
                        if len(parts) >= 2 and int(parts[1]) != int(month):
                            continue
                except Exception:
                    pass

        # Dedup duplicate shifts by (date, name, normalized_shift, start_time)
        s_lower = normalize_str(shift_name)
        if "sang" in s_lower:
            norm_s = "Sáng"
        elif "chieu" in s_lower:
            norm_s = "Chiều"
        elif "toi" in s_lower:
            norm_s = "Tối"
        elif "gay" in s_lower:
            norm_s = "Gãy"
        else:
            norm_s = str(shift_name).strip().title() or "Khác"

        start_time = str(checkin or "").strip()[:5]
        shift_dedup_key = f"{date_str}|{emp_canonical}|{norm_s}|{start_time}"
        if shift_dedup_key in seen_shifts:
            continue
        seen_shifts.add(shift_dedup_key)

        # Parse duration
        raw_mins = 0
        if len(row) > 6 and row[6]:
            try:
                raw_mins = float(str(row[6]).replace(",", "."))
            except Exception:
                raw_mins = parse_shift_duration_minutes(checkin, checkout)
        else:
            raw_mins = parse_shift_duration_minutes(checkin, checkout)

        is_historic = (month and str(month).isdigit() and int(month) < 9)
        shift_approval_key = f"{date_str}|{emp_canonical}|{shift_name}|{checkin}"
        approval = shift_approvals.get(shift_approval_key) or {}

        std_shift_mins = get_shift_standard_mins(shift_name, checkin, date_str=date_str)

        if raw_mins <= std_shift_mins:
            effective_mins = raw_mins
            ot_status = "STANDARD"
        elif raw_mins <= (std_shift_mins + POLICY_OT_BUFFER_MINS):
            effective_mins = raw_mins
            ot_status = "OT_PERF"
        else:
            appr_status = approval.get("status")
            if appr_status == "APPROVE":
                effective_mins = approval.get("approved_mins", raw_mins)
                ot_status = "APPROVED"
            elif appr_status == "CUT":
                effective_mins = approval.get("approved_mins", std_shift_mins)
                ot_status = "CUT"
            elif is_historic:
                effective_mins = raw_mins
                ot_status = "APPROVED"
            else:
                effective_mins = std_shift_mins
                ot_status = "PENDING"

        ot_mins = max(0, effective_mins - std_shift_mins)
        std_mins = effective_mins - ot_mins

        # Determine shift role: BAR vs SERVICE
        row_note = str(row[7]).strip() if len(row) > 7 and row[7] else ""
        shift_data = {
            "shift_name": shift_name,
            "note": row_note,
            "source": "data_json"
        }
        if len(row) > 10 and row[10]:
            shift_data["extra"] = str(row[10])
        shift_role = resolve_shift_role(shift_data, emp_canonical, date_str, shift_name)
        shift_rate = role_bar_rate if shift_role == "BAR" else role_service_rate
        rate_per_min = shift_rate / 60.0

        is_holiday = is_holiday_date(date_str)
        holiday_multiplier = 2.0 if is_holiday else 1.0

        std_cost = std_mins * rate_per_min * holiday_multiplier
        ot_cost = ot_mins * rate_per_min * holiday_multiplier
        shift_total_cost = effective_mins * rate_per_min * holiday_multiplier

        total_standard_cost += std_cost
        total_ot_cost += ot_cost
        total_worked_minutes += effective_mins
        total_shifts += 1

        if shift_role == "BAR":
            count_bar += 1
            hours_bar += effective_mins / 60.0
        else:
            count_service += 1
            hours_service += effective_mins / 60.0

        # Late arrival check from column 9 if available
        late_m = 0
        if len(row) > 9 and row[9]:
            try:
                late_m = float(str(row[9]).replace(",", "."))
            except Exception:
                late_m = 0
        elif checkin:
            try:
                ch, cm = map(int, str(checkin).strip().split(":"))
                cin_mins = ch * 60 + cm
                s_name_norm = normalize_str(shift_name)
                if "sang" in s_name_norm:
                    late_m = max(0, cin_mins - (6 * 60))
                elif "toi" in s_name_norm or "chieu" in s_name_norm:
                    if "17" in s_name_norm:
                        base_start = 17 * 60
                        late_m = max(0, cin_mins - base_start)
                    elif "18" in s_name_norm:
                        base_start = 18 * 60
                        late_m = max(0, cin_mins - base_start)
                    else:
                        # Tên ca chung 'Tối'/'Chiều':
                        # <= 17:00: đến sớm hoặc đúng giờ ca 17h -> trễ = 0
                        # 17:01 - 17:29: trễ ca 17h -> trễ = cin_mins - 17:00
                        # 17:30 - 18:00: đến sớm ca tối 18h -> trễ = 0 (bảo vệ quyền lợi nhân viên đến sớm)
                        # > 18:00: trễ ca tối 18h -> trễ = cin_mins - 18:00
                        if cin_mins <= 17 * 60:
                            late_m = 0
                        elif cin_mins < 17 * 60 + 30:
                            late_m = cin_mins - (17 * 60)
                        elif cin_mins <= 18 * 60:
                            late_m = 0
                        else:
                            late_m = max(0, cin_mins - (18 * 60))
            except Exception:
                pass

        if late_m > 0:
            late_minutes_list.append(late_m)

        shift_records.append({
            "date": date_str,
            "shift": shift_name,
            "role": shift_role,
            "hourly_rate": shift_rate,
            "shift_rate": shift_rate,
            "checkin": checkin,
            "checkout": checkout,
            "minutes": raw_mins,
            "effective_minutes": effective_mins,
            "standard_minutes": std_mins,
            "ot_minutes": ot_mins,
            "standard_shift_minutes": std_shift_mins,
            "is_holiday": is_holiday,
            "ot_status": ot_status,
            "shift_cost": shift_total_cost,
            "source": "data_json"
        })

    # 2.1 Merge Realtime Completed Shifts from attendance_logs.json
    for log in attendance_logs:
        if not isinstance(log, dict):
            continue
        cin = log.get("checkin_time") or log.get("checkin")
        cout = log.get("checkout_time") or log.get("checkout")
        if not cin:
            continue

        is_missing_cout = not cout or str(cout).strip() in ["", "--:--"]
        is_hanging = bool(log.get("is_hanging_pending"))
        tot_mins = log.get("total_mins") or log.get("duration_mins") or 0

        is_valid_quen_checkout = (
            is_hanging
            or log.get("status") in ["QUEN_CHECKOUT", "AUTO_CLOSED", "PENDING"]
            or float(tot_mins) > 0
        )
        if is_missing_cout and not is_valid_quen_checkout:
            continue

        if not (is_hanging or is_valid_quen_checkout) and float(tot_mins) <= 0:
            continue

        # Multi-Tier Identity Matching for SQLite attendance_logs
        log_emp_name = str(log.get("display_name") or log.get("full_name") or "").strip()
        log_username = str(log.get("username") or "").strip()

        is_match = False
        if log_emp_name and get_canonical_name(log_emp_name, staff_accounts) == target_canonical:
            is_match = True
        elif log_username and normalize_str(log_username) == normalize_str(target_canonical):
            is_match = True
        elif staff_accounts and isinstance(staff_accounts, dict):
            acc = staff_accounts.get(log_username) or staff_accounts.get(normalize_str(log_username)) or {}
            acc_fn = str(acc.get("full_name") or acc.get("display_name") or "").strip()
            acc_aliases = [str(a) for a in (acc.get("aliases") or []) if a]
            acc_sheets = [str(sn) for sn in (acc.get("sheet_names") or []) if sn]
            if acc_fn and get_canonical_name(acc_fn, staff_accounts) == target_canonical:
                is_match = True
            elif any(get_canonical_name(al, staff_accounts) == target_canonical for al in acc_aliases + acc_sheets):
                is_match = True
            elif acc_fn and normalize_str(acc_fn) == normalize_str(target_canonical):
                is_match = True

        if not is_match and log_emp_name:
            if normalize_str(log_emp_name) == normalize_str(target_canonical):
                is_match = True

        if not is_match:
            continue

        log_date = str(log.get("date") or "").strip()
        log_month = ""
        try:
            if "/" in log_date:
                parts = log_date.split("/")
                if len(parts) >= 2:
                    log_month = str(int(parts[1]))
            elif "-" in log_date:
                parts = log_date.split("-")
                if len(parts) >= 2:
                    log_month = str(int(parts[1]))
        except Exception:
            pass

        if month and month.lower() != "all" and log_month and log_month != str(int(month)):
            continue

        s_key = log.get("shift_key", "sang")
        s_name = log.get("shift_name") or log.get("shift") or ("Ca Sáng" if "sang" in s_key else "Ca Tối")
        s_lower = normalize_str(s_name)
        if "sang" in s_lower:
            norm_s = "Sáng"
        elif "chieu" in s_lower:
            norm_s = "Chiều"
        elif "toi" in s_lower:
            norm_s = "Tối"
        elif "gay" in s_lower:
            norm_s = "Gãy"
        else:
            norm_s = str(s_name).strip().title() or "Khác"

        start_time = str(cin or "").strip()[:5]
        shift_dedup_key = f"{log_date}|{target_canonical}|{norm_s}|{start_time}"
        if shift_dedup_key in seen_shifts:
            continue
        seen_shifts.add(shift_dedup_key)

        raw_mins = float(tot_mins)
        is_historic = (month and str(month).isdigit() and int(month) < 9)
        shift_approval_key = f"{log_date}|{target_canonical}|{s_name}|{cin}"
        approval = shift_approvals.get(shift_approval_key) or {}

        std_shift_mins = get_shift_standard_mins(s_name, cin)

        if is_hanging and log.get("status") == "QUEN_CHECKOUT" and not is_missing_cout:
            appr_status = approval.get("status")
            if appr_status == "APPROVE":
                effective_mins = float(approval.get("approved_mins", std_shift_mins))
                raw_mins = effective_mins
                ot_status = "APPROVED"
            elif appr_status == "CUT":
                effective_mins = float(approval.get("approved_mins", std_shift_mins))
                raw_mins = effective_mins
                ot_status = "CUT"
            else:
                raw_mins = 0.0
                effective_mins = 0.0
                ot_status = "QUEN_CHECKOUT"
        elif is_missing_cout:
            # Quên check-out: Bảo vệ quyền lợi người lao động, tính tạm thời theo khung chuẩn ca (mặc định 300p = 5.0h)
            std_fallback = float(std_shift_mins) if std_shift_mins > 0 else 300.0
            raw_mins = float(tot_mins) if float(tot_mins) > 0 else std_fallback
            appr_status = approval.get("status")
            if appr_status == "APPROVE":
                effective_mins = approval.get("approved_mins", raw_mins)
                ot_status = "APPROVED"
            elif appr_status == "CUT":
                effective_mins = approval.get("approved_mins", std_shift_mins)
                ot_status = "CUT"
            else:
                effective_mins = raw_mins
                ot_status = "QUEN_CHECKOUT"
            cout = "--:--"
        else:
            eff_val = log.get("effective_duration_mins")
            if eff_val is not None and float(eff_val) > 0 and not is_historic:
                raw_mins = float(eff_val)
            else:
                raw_mins = float(tot_mins) if float(tot_mins) > 0 else float(std_shift_mins)

            # Khóa an toàn trần thời gian (Capped duration safeguard):
            # Không một ca đơn lẻ nào được vượt quá 720 phút (12 tiếng) nếu chưa có Admin duyệt
            if raw_mins > 720 and not is_historic:
                raw_mins = float(std_shift_mins)

            if raw_mins <= std_shift_mins:
                effective_mins = raw_mins
                ot_status = "STANDARD"
            elif raw_mins <= (std_shift_mins + POLICY_OT_BUFFER_MINS):
                effective_mins = raw_mins
                ot_status = "OT_PERF"
            else:
                appr_status = approval.get("status")
                if appr_status == "APPROVE":
                    effective_mins = approval.get("approved_mins", raw_mins)
                    ot_status = "APPROVED"
                elif appr_status == "CUT":
                    effective_mins = approval.get("approved_mins", std_shift_mins)
                    ot_status = "CUT"
                elif is_historic:
                    effective_mins = raw_mins
                    ot_status = "APPROVED"
                else:
                    effective_mins = std_shift_mins
                    ot_status = "PENDING"

        ot_mins = max(0, effective_mins - std_shift_mins)
        std_mins = effective_mins - ot_mins

        shift_role = resolve_shift_role(log, target_canonical, log_date, s_name)
        if log.get("hourly_rate_snapshot") and int(log.get("hourly_rate_snapshot")) > 0:
            shift_rate = int(log.get("hourly_rate_snapshot"))
        else:
            shift_rate = role_bar_rate if shift_role == "BAR" else role_service_rate
        rate_per_min = shift_rate / 60.0

        is_holiday = is_holiday_date(log_date)
        holiday_multiplier = 2.0 if is_holiday else 1.0

        std_cost = std_mins * rate_per_min * holiday_multiplier
        ot_cost = ot_mins * rate_per_min * holiday_multiplier
        shift_total_cost = effective_mins * rate_per_min * holiday_multiplier

        total_standard_cost += std_cost
        total_ot_cost += ot_cost
        total_worked_minutes += effective_mins
        total_shifts += 1

        if shift_role == "BAR":
            count_bar += 1
            hours_bar += effective_mins / 60.0
        else:
            count_service += 1
            hours_service += effective_mins / 60.0

        late_m = float(log.get("late_mins") or 0)
        if late_m > 0:
            late_minutes_list.append(late_m)

        shift_records.append({
            "date": log_date,
            "shift": s_name,
            "role": shift_role,
            "hourly_rate": shift_rate,
            "shift_rate": shift_rate,
            "checkin": cin,
            "checkout": cout,
            "minutes": raw_mins,
            "effective_minutes": effective_mins,
            "standard_minutes": std_mins,
            "ot_minutes": ot_mins,
            "standard_shift_minutes": std_shift_mins,
            "is_holiday": is_holiday,
            "ot_status": ot_status,
            "shift_cost": shift_total_cost,
            "source": "attendance_logs"
        })

    total_hours = round(total_worked_minutes / 60.0, 2)
    if salary_type == "FIXED" and fixed_salary > 0:
        standard_pay = int(round(fixed_salary + total_ot_cost))
    else:
        standard_pay = int(round(total_standard_cost + total_ot_cost))

    # 3. Calculate Progressive Penalties
    late_penalty_total, penalty_violations = calculate_progressive_late_penalties(late_minutes_list, month=month)

    # 4. Integrate Evaluations (Bonus / Deductions)
    eval_bonus = 0
    eval_deductions = 0
    seen_eval_fingerprints = set()

    for ev in evaluations:
        if ev.get("status") not in ["APPROVED", "ACTIVE"]:
            continue
        if get_canonical_name(ev.get("staffName", ""), staff_accounts) != target_canonical:
            continue
        if month and month.lower() != "all" and str(ev.get("month", "")).strip() != str(month).strip():
            continue

        amt = int(ev.get("amount") or 0)
        ev_category = get_canonical_ledger_category(ev.get("type", ""))
        ev_reason = normalize_str(ev.get("reason", ""))
        ev_month = str(ev.get("month", "")).strip()

        fp = f"{target_canonical}_{ev_month}_{amt}_{ev_category}_{ev_reason}"
        seen_eval_fingerprints.add(fp)

        if ev_category == "bonus":
            eval_bonus += amt
        else:
            eval_deductions += amt

    # 5. Integrate SỔ PHỤ (Tạm ứng, Thưởng, Phạt từ data.json) with Anti-Duplicate Safeguard
    so_phu = data_json.get("SỔ PHỤ", [])
    advance_amount = 0
    so_phu_bonus = 0
    so_phu_deductions = 0
    seen_sp_fingerprints = set()

    for row in so_phu[1:]:
        if len(row) > 4 and get_canonical_name(str(row[1]), staff_accounts) == target_canonical:
            row_month = str(row[2]).strip()
            if month and month.lower() != "all":
                try:
                    if row_month.isdigit() and int(row_month) != int(month):
                        continue
                    elif "/" in row_month:
                        parts = row_month.split("/")
                        if len(parts) >= 2 and int(parts[1]) != int(month) and int(parts[0]) != int(month):
                            continue
                except Exception:
                    pass
            try:
                amt = int(float(str(row[4]).replace(",", "").replace(".", "").strip()))
                sp_category = get_canonical_ledger_category(str(row[3])) if len(row) > 3 else "advance"
                sp_reason = normalize_str(str(row[6])) if len(row) > 6 else ""

                # Anti-duplicate check: If this entry was mirrored from evaluations or already seen, skip
                norm_row_month = str(int(row_month)) if row_month.isdigit() else row_month
                fp = f"{target_canonical}_{norm_row_month}_{amt}_{sp_category}_{sp_reason}"
                if fp in seen_eval_fingerprints or fp in seen_sp_fingerprints:
                    continue
                seen_sp_fingerprints.add(fp)

                if sp_category == "bonus":
                    so_phu_bonus += amt
                elif sp_category == "deduction":
                    so_phu_deductions += amt
                else:
                    advance_amount += amt
            except Exception:
                pass

    # 5.1 Integrate Server-side Staff Ledgers (Sổ Phụ SQLite WAL) with Anti-Duplicate Safeguard
    sqlite_bonus = 0
    sqlite_advance = 0
    sqlite_deductions = 0
    for entry in staff_ledgers:
        if get_canonical_name(entry.get("staff_name", ""), staff_accounts) != target_canonical:
            continue
        e_month = str(entry.get("month", "")).strip()
        if not e_month and entry.get("created_at"):
            try:
                parts = str(entry.get("created_at")).split()[0].split("-")
                if len(parts) >= 2:
                    e_month = str(int(parts[1]))
            except Exception:
                pass
        if e_month.isdigit():
            e_month = str(int(e_month))

        if month and month.lower() != "all" and e_month and e_month != str(int(month)):
            continue

        e_category = get_canonical_ledger_category(entry.get("type", ""))
        e_amt = int(entry.get("amount") or 0)
        e_reason = normalize_str(entry.get("reason") or entry.get("ly_do") or entry.get("ghi_chu") or "")

        fp = f"{target_canonical}_{e_month}_{e_amt}_{e_category}_{e_reason}"
        if fp in seen_eval_fingerprints or fp in seen_sp_fingerprints:
            continue
        seen_sp_fingerprints.add(fp)

        if e_category == "bonus":
            sqlite_bonus += e_amt
        elif e_category == "advance":
            sqlite_advance += e_amt
        elif e_category == "deduction":
            sqlite_deductions += e_amt

    eval_bonus += so_phu_bonus + sqlite_bonus
    advance_amount += sqlite_advance
    eval_deductions += so_phu_deductions + sqlite_deductions

    # 5.2 Integrate Immutable Audit Ledger adjustments (so_cai_luong)
    # LƯU Ý BẢO VỆ CHỐNG TÍNH TRÙNG:
    # - DIEU_CHINH_GIO và DOI_MUC_LUONG chỉ là bút toán AUDIT LOG (ghi vết), KHÔNG cộng dồn giờ công
    #   vì giờ công thực tế đã được cập nhật chính xác trong attendance_logs khi Quản lý duyệt.
    # - THUONG: cộng vào eval_bonus.
    # - PHAT: cộng vào eval_deductions (dùng abs() để bảo đảm không bị âm/đảo dấu).
    # - UNG_LUONG: cộng vào advance_amount (dùng abs()).
    # - Đối chiếu fingerprint chống tính trùng giữa staff_ledgers và so_cai_luong.
    so_cai_bonus = 0
    so_cai_advance = 0
    so_cai_deductions = 0
    for sc in (so_cai_luong or []):
        if get_canonical_name(sc.get("staff_name", ""), staff_accounts) != target_canonical:
            continue
        sc_created = sc.get("created_at") or ""
        sc_month = ""
        if sc.get("month"):
            try:
                sc_month = str(int(sc.get("month")))
            except Exception:
                sc_month = str(sc.get("month")).strip()
        elif sc.get("thang"):
            try:
                sc_month = str(int(sc.get("thang")))
            except Exception:
                sc_month = str(sc.get("thang")).strip()
        elif sc_created:
            try:
                parts = sc_created.split()[0].split("-")
                if len(parts) >= 2:
                    sc_month = str(int(parts[1]))
            except Exception:
                pass
        if month and month.lower() != "all" and sc_month and sc_month != str(int(month)):
            continue

        evt = str(sc.get("loai_su_kien") or "").upper()
        amt = int(sc.get("so_tien_thay_doi") or 0)

        # Nhận diện cả sự kiện gốc và bút toán đảo ngược kế toán
        if evt in ["THUONG", "HUY_THUONG"]:
            sc_cat = "bonus"
        elif evt in ["PHAT", "HUY_PHAT"]:
            sc_cat = "deduction"
        elif evt in ["UNG_LUONG", "HUY_UNG_LUONG"]:
            sc_cat = "advance"
        elif evt in ["REVERSAL", "DIEU_CHINH_GIAM"]:
            ref_type = str(sc.get("reference_type") or sc.get("loai_goc") or "").upper()
            if "THUONG" in ref_type:
                sc_cat = "bonus"
            elif "PHAT" in ref_type:
                sc_cat = "deduction"
            elif "UNG" in ref_type:
                sc_cat = "advance"
            else:
                sc_cat = ""
        else:
            sc_cat = ""

        if not sc_cat:
            continue

        entry_id = str(sc.get("id") or sc.get("entry_id") or "")
        sc_reason = normalize_str(sc.get("ly_do") or sc.get("ghi_chu") or sc.get("reason") or "")
        if entry_id:
            fp_sc = f"{target_canonical}_{sc_month}_{entry_id}"
        else:
            fp_sc = f"{target_canonical}_{sc_month}_{abs(amt)}_{sc_cat}_{sc_reason}"

        if fp_sc in seen_sp_fingerprints or fp_sc in seen_eval_fingerprints:
            continue
        seen_sp_fingerprints.add(fp_sc)

        if evt == "THUONG":
            so_cai_bonus += abs(amt)
        elif evt == "HUY_THUONG":
            so_cai_bonus -= abs(amt)
        elif evt == "PHAT":
            so_cai_deductions += abs(amt)
        elif evt == "HUY_PHAT":
            so_cai_deductions -= abs(amt)
        elif evt == "UNG_LUONG":
            so_cai_advance += abs(amt)
        elif evt == "HUY_UNG_LUONG":
            so_cai_advance -= abs(amt)
        elif evt in ["REVERSAL", "DIEU_CHINH_GIAM"]:
            if sc_cat == "bonus":
                so_cai_bonus -= abs(amt)
            elif sc_cat == "deduction":
                so_cai_deductions -= abs(amt)
            elif sc_cat == "advance":
                so_cai_advance -= abs(amt)

    eval_bonus += so_cai_bonus
    advance_amount += so_cai_advance
    eval_deductions += so_cai_deductions

    # 6. Final Net Pay Calculation & Deduction Cap Safeguard (ADR-011)
    gross_salary = standard_pay + eval_bonus
    total_deductions = advance_amount + late_penalty_total + eval_deductions

    payroll_rules = (store_config.get("payroll_rules") if store_config else {}) or {}
    enable_deduction_cap = bool(payroll_rules.get("enable_deduction_cap", False))
    deduction_cap_percent = float(payroll_rules.get("deduction_cap_percent", 0.50))
    allow_negative_net = bool(payroll_rules.get("allow_negative_net", False))

    if enable_deduction_cap and not allow_negative_net:
        if gross_salary > 0:
            max_allowed_deduction = int(round(gross_salary * deduction_cap_percent))
            capped_deductions = min(total_deductions, max_allowed_deduction)
            uncollected_debt = float(max(0, total_deductions - capped_deductions))
            net_pay_raw = float(gross_salary - capped_deductions)
        else:
            capped_deductions = 0
            uncollected_debt = float(total_deductions)
            net_pay_raw = 0.0
        deduction_cap_applied = bool(uncollected_debt > 0)
    else:
        # Standard default mode: full deduction up to gross, net pay cannot be negative
        capped_deductions = total_deductions
        raw_net = gross_salary - total_deductions
        uncollected_debt = float(max(0.0, -raw_net))
        net_pay_raw = float(max(0.0, raw_net))
        deduction_cap_applied = False

    # [CALC-02] Round to nearest 1000 VND for cash payment convenience
    net_pay = int(round(max(0.0, net_pay_raw) / 1000.0)) * 1000
    emp_id = resolve_employee_id_from_accounts(target_canonical, staff_accounts)

    return {
        "staff_name": full_display_name,
        "employee_id": emp_id,
        "month": month,
        "salary_type": salary_type,
        "fixed_salary": fixed_salary,
        "base_wage": fixed_salary if salary_type == "FIXED" and fixed_salary > 0 else base_wage,
        "total_shifts": total_shifts,
        "total_worked_minutes": total_worked_minutes,
        "total_hours": total_hours,
        "standard_pay": standard_pay,
        "role_breakdown": {
            "bar": {
                "shifts": count_bar,
                "hours": round(hours_bar, 2),
                "rate": role_bar_rate,
                "amount": int(round(round(hours_bar, 2) * role_bar_rate))
            },
            "service": {
                "shifts": count_service,
                "hours": round(hours_service, 2),
                "rate": role_service_rate,
                "amount": int(round(round(hours_service, 2) * role_service_rate))
            }
        },
        "eval_bonus": eval_bonus,
        "advance_amount": advance_amount,
        "eval_deductions": eval_deductions,
        "late_penalty_total": late_penalty_total,
        "violations": penalty_violations,
        "gross_salary": gross_salary,
        "total_deductions": total_deductions,
        "capped_deductions": capped_deductions,
        "deduction_cap_applied": deduction_cap_applied,
        "deduction_cap_percent": deduction_cap_percent,
        "net_pay": net_pay,
        "uncollected_debt": uncollected_debt,  # [CALC-01] carry-forward to next month
        "shift_records": shift_records
    }


def compute_all_shift_records_server_side(
    data_json: Optional[Dict[str, Any]] = None,
    shift_approvals: Optional[Dict[str, Any]] = None,
    staff_accounts: Optional[Dict[str, Any]] = None,
    store_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Dict[str, Any]]:
    """
    Single Source of Truth (Phase 2):
    Tính toán sẵn toàn bộ chỉ số giờ chuẩn, giờ hiệu lực, tăng ca (OT), lương ca, trạng thái duyệt
    và mã định danh nhân viên (employee_id) cho từng ca trong DỮ LIỆU để gửi về Frontend qua _meta.computed_shifts.
    """
    data_json = data_json or {}
    shift_approvals = shift_approvals or {}
    staff_accounts = staff_accounts or {}

    # 1. Build base wage lookup map per canonical staff name
    wages_by_canon: Dict[str, int] = {}
    nv_tab = data_json.get("NHÂN VIÊN", [])
    for row in nv_tab[3:]:
        if len(row) > 1 and row[1]:
            c_name = get_canonical_name(str(row[1]), staff_accounts)
            w = 17000
            if len(row) > 3 and row[3]:
                try:
                    parsed = int(float(str(row[3]).replace(",", "").replace(".", "").strip()))
                    if parsed > 0:
                        w = parsed
                except Exception:
                    pass
            if c_name not in wages_by_canon or wages_by_canon[c_name] <= 17000:
                wages_by_canon[c_name] = w

    for uname, acc in staff_accounts.items():
        if not isinstance(acc, dict):
            continue
        c_name = get_canonical_name(acc.get("full_name") or uname, staff_accounts)
        rate = int(acc.get("hourly_rate") or 0)
        if rate > 0 and (c_name not in wages_by_canon or rate > wages_by_canon[c_name]):
            wages_by_canon[c_name] = rate

    # 2. Pre-resolve employee_id per canonical staff name
    emp_id_cache: Dict[str, str] = {}

    du_lieu = data_json.get("DỮ LIỆU", [])
    computed_map: Dict[str, Dict[str, Any]] = {}
    if len(du_lieu) <= 1:
        return computed_map

    for row in du_lieu[1:]:
        if not row or len(row) < 6:
            continue
        date_str = str(row[1] or "").strip()
        raw_name = str(row[2] or "").strip()
        shift_name = str(row[3] or "").strip()
        time_in = str(row[4] or "").strip()
        time_out = str(row[5] or "").strip()
        month_str = str(row[8] or "").strip() if len(row) > 8 else ""
        if not date_str or not raw_name or not month_str:
            continue

        canon_name = get_canonical_name(raw_name, staff_accounts)
        if canon_name not in emp_id_cache:
            emp_id_cache[canon_name] = resolve_employee_id_from_accounts(canon_name, staff_accounts)
        emp_id = emp_id_cache[canon_name]

        raw_mins = 0.0
        if len(row) > 6 and row[6]:
            try:
                raw_mins = float(str(row[6]).replace(",", "."))
            except Exception:
                raw_mins = float(parse_shift_duration_minutes(time_in, time_out))

        late_mins = 0.0
        if len(row) > 9 and row[9]:
            try:
                late_mins = float(str(row[9]).replace(",", "."))
            except Exception:
                late_mins = 0.0

        shift_key = f"{date_str}|{canon_name}|{shift_name}|{time_in}"
        approval = shift_approvals.get(shift_key)
        is_historic = bool(month_str.isdigit() and int(month_str) < 9)
        std_shift_mins = get_shift_standard_mins(shift_name, time_in, date_str=date_str)

        if raw_mins <= std_shift_mins:
            ot_status = "STANDARD"
            effective_mins = raw_mins
        elif raw_mins <= (std_shift_mins + POLICY_OT_BUFFER_MINS):
            ot_status = "OT_PERF"
            effective_mins = raw_mins
        else:
            if approval and approval.get("status") == "APPROVE":
                ot_status = "APPROVED"
                effective_mins = float(approval.get("approved_mins") or raw_mins)
            elif approval and approval.get("status") == "CUT":
                ot_status = "CUT"
                effective_mins = float(approval.get("approved_mins") or std_shift_mins)
            elif is_historic:
                ot_status = "APPROVED"
                effective_mins = raw_mins
            else:
                ot_status = "PENDING"
                effective_mins = float(std_shift_mins)

        ot_mins = max(0.0, effective_mins - std_shift_mins)
        std_mins = effective_mins - ot_mins
        emp_wage = wages_by_canon.get(canon_name, 17000)
        rate_per_min = emp_wage / 60.0

        is_hol = is_holiday_date(date_str)
        hol_mult = 2 if is_hol else 1
        hol_extra = (effective_mins * rate_per_min) if is_hol else 0.0

        computed_map[shift_key] = {
            "employee_id": emp_id,
            "canonical_name": canon_name,
            "mins": raw_mins,
            "effectiveMins": effective_mins,
            "standardMins": std_mins,
            "standardShiftMins": std_shift_mins,
            "overtimeMins": ot_mins,
            "lateMins": late_mins,
            "standardCost": std_mins * rate_per_min * hol_mult,
            "overtimeCost": ot_mins * rate_per_min * hol_mult,
            "totalCost": effective_mins * rate_per_min * hol_mult,
            "isHoliday": is_hol,
            "holidayMultiplier": hol_mult,
            "holidayExtra": hol_extra,
            "otStatus": ot_status,
            "wage": emp_wage
        }

    return computed_map


def check_staff_offboarding_status(
    staff_name: str,
    target_month: Optional[str] = None,
    data_json: Optional[Dict[str, Any]] = None,
    staff_accounts: Optional[Dict[str, Any]] = None,
    so_cai_luong: Optional[List[Dict[str, Any]]] = None,
    store_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Offboarding Gate (ADR-011):
    Kiểm tra tình trạng công nợ và quyết toán của nhân viên trước khi thôi việc hoặc khóa sổ.
    Nếu còn dư nợ (uncollected_debt > 0), cảnh báo cần thanh toán nợ trước khi hoàn tất Final Clearance.
    """
    payslip = calculate_staff_payslip_breakdown(
        staff_name=staff_name,
        month=target_month,
        data_json=data_json,
        staff_accounts=staff_accounts,
        so_cai_luong=so_cai_luong,
        store_config=store_config
    )
    debt = float(payslip.get("uncollected_debt", 0.0))
    can_offboard = bool(debt <= 0.0)

    return {
        "staff_name": payslip.get("staff_name", staff_name),
        "employee_id": payslip.get("employee_id", ""),
        "month": target_month,
        "net_pay": payslip.get("net_pay", 0),
        "uncollected_debt": debt,
        "can_offboard": can_offboard,
        "requires_admin_clearance": not can_offboard,
        "message": "Đủ điều kiện hoàn tất thôi việc (không nợ quán)." if can_offboard else f"Còn dư nợ {int(debt):,} VNĐ cần quyết toán trước khi hoàn tất thôi việc."
    }



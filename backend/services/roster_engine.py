# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
Roster Auto-Assignment & Optimization Engine for FnBOps
Timefold-inspired Greedy + 1-Step Swap Backtracking Solver.
"""

import os
import sys
import copy
import logging
import datetime
from typing import Optional, Dict, Any, List, Tuple

try:
    from backend.services.auth import load_staff_auth, normalize_str
    from backend.services.roster_service import (
        load_roster_data,
        save_roster_data,
        get_active_and_next_week_ids,
        get_iso_week_info,
        is_registration_window_open,
        DAY_KEYS_ISO,
        _extract_day_pref_tags,
        validate_service_gender_pair,
        is_bar_capable,
        is_service_capable,
        get_primary_role,
        SKILL_BAR,
        SKILL_SERVICE,
        SKILL_CASHIER,
        SKILL_MANAGER,
        SKILL_SECURITY,
        compute_staff_skill_mask,
        check_skill_coverage,
    )
    from backend.services.store_config import get_store_config, get_shift_role_requirements
except ImportError:
    from services.auth import load_staff_auth, normalize_str
    from services.roster_service import (
        load_roster_data,
        save_roster_data,
        get_active_and_next_week_ids,
        get_iso_week_info,
        is_registration_window_open,
        DAY_KEYS_ISO,
        _extract_day_pref_tags,
        validate_service_gender_pair,
        is_bar_capable,
        is_service_capable,
        get_primary_role,
        SKILL_BAR,
        SKILL_SERVICE,
        SKILL_CASHIER,
        SKILL_MANAGER,
        SKILL_SECURITY,
        compute_staff_skill_mask,
        check_skill_coverage,
    )
    from services.store_config import get_store_config, get_shift_role_requirements

logger = logging.getLogger("roster_engine")


def auto_assign_week_schedule(
    week_key: Any = None,
    registrations: Optional[dict] = None,
    staff_accounts: Optional[dict] = None,
    **kwargs
) -> dict:
    """
    Timefold-inspired Greedy + 1-Step Swap Backtracking Solver:
    - Cải tiến 1 (Anti-Clopening Rule): Chống xếp Ca Sáng (sang/morning) cho nhân sự vừa làm Ca Tối (toi/evening) ngày liền trước.
      Ưu tiên tuyệt đối ứng viên được nghỉ ngơi (`not is_clopening`), chỉ xếp người bị clopening khi không còn ứng viên hợp lệ nào khác.
    - Cải tiến 2 (1-Step Swap Backtracking): Khi một slot trong ca bị thiếu người (`len(assigned) < needed`) mà vẫn còn ứng viên `cand_u`
      đã đăng ký ca đó nhưng chưa được gán (do kẹt vị trí hoặc do nhân sự đa năng `other_u` đã chiếm mất slot trước đó), tự động tìm
      hoán vị 1 bước: chuyển `other_u` sang slot đang thiếu để nhường slot của `other_u` cho `cand_u`.
    - Ghi nhận thống kê `"solver_meta": {"engine": "Timefold-Greedy-Backtrack-v2", "anti_clopening_enabled": True}`.
    """
    active_info, next_info = get_active_and_next_week_ids()
    passed_week_dict = None
    save_to_disk = kwargs.get("save_to_disk", True)

    if isinstance(week_key, dict):
        if any(k in week_key for k in ["registrations", "days", "shifts", "week_id", "week_key"]):
            passed_week_dict = week_key
            target_week_id = str(week_key.get("week_id") or week_key.get("week_key") or active_info["week_id"])
        else:
            if registrations is None:
                registrations = week_key
            target_week_id = str(kwargs.get("week_id") or active_info["week_id"])
    elif week_key == "next":
        target_week_id = next_info["week_id"]
    elif week_key == "current" or week_key is None:
        target_week_id = active_info["week_id"]
    else:
        target_week_id = str(week_key)

    try:
        if "-W" in target_week_id:
            target_info = get_iso_week_info(datetime.datetime.strptime(target_week_id + "-1", "%G-W%V-%u").date())
        else:
            dt_parsed = datetime.datetime.strptime(target_week_id[:10], "%Y-%m-%d").date()
            target_info = get_iso_week_info(dt_parsed)
    except Exception:
        target_info = next_info if is_registration_window_open() else active_info

    if staff_accounts is None:
        staff_auth = load_staff_auth()
        accounts = dict(staff_auth.get("staff_accounts", {}))
    else:
        accounts = dict(staff_accounts.get("staff_accounts", staff_accounts))

    roster_data = load_roster_data()
    weeks = roster_data.setdefault("weeks", {})
    if passed_week_dict is not None:
        week_entry = passed_week_dict
    else:
        week_entry = weeks.setdefault(target_week_id, {
            "week_id": target_week_id,
            "start_date": target_info["start_date"],
            "end_date": target_info["end_date"],
            "status": "DRAFT",
            "registrations": {},
            "shifts": {},
            "swaps": []
        })

    regs = registrations if registrations is not None else week_entry.get("registrations", {})
    input_days = kwargs.get("days") if isinstance(kwargs.get("days"), dict) else (week_entry.get("days") if isinstance(week_entry.get("days"), dict) else {})
    input_shifts = kwargs.get("shifts") if isinstance(kwargs.get("shifts"), dict) else (week_entry.get("shifts") if isinstance(week_entry.get("shifts"), dict) else {})

    # Bổ sung nhân sự có trong registrations nhưng chưa có trong accounts (phục vụ test độc lập)
    if isinstance(regs, dict):
        for u_k, u_v in regs.items():
            if u_k not in accounts and isinstance(u_v, dict):
                accounts[u_k] = {
                    "full_name": u_v.get("full_name", u_k),
                    "gender": u_v.get("gender", "NAM"),
                    "position": u_v.get("position", u_v.get("role", "SERVICE")),
                    "role": "STAFF",
                    "status": "ACTIVE",
                    "primary_role": u_v.get("primary_role"),
                    "allowed_roles": u_v.get("allowed_roles") or u_v.get("roles") or u_v.get("skills"),
                }

    managers = [
        u for u, a in accounts.items()
        if isinstance(a, dict) and a.get("status", "ACTIVE") != "INACTIVE" and a.get("role") in ["ADMIN", "MANAGER"]
    ]
    default_mgr = managers[0] if managers else None

    all_active_staff = {
        u: a for u, a in accounts.items()
        if isinstance(a, dict)
        and a.get("status", "ACTIVE") != "INACTIVE"
        and a.get("role") not in ["ADMIN", "MANAGER"]
    }

    # BẮT BUỘC: Nếu tuần này có nộp đăng ký ca (registrations), chỉ tự động xếp ca cho nhân sự CÓ đăng ký
    # Không tự ý lấy all_active_staff khi tuần có ít đăng ký (chỉ xếp cho người đã đăng ký, thiếu ca để trống)
    if isinstance(regs, dict) and len(regs) > 0:
        active_staff = {
            u: a for u, a in all_active_staff.items()
            if u in regs
        }
    else:
        active_staff = all_active_staff

    bar_primary = [
        u for u, a in active_staff.items()
        if is_bar_capable(a) and get_primary_role(a) == "BAR"
    ]
    bar_backup = [
        u for u, a in active_staff.items()
        if is_bar_capable(a) and get_primary_role(a) != "BAR"
    ]

    shift_counts = {u: 0 for u in active_staff.keys()}
    shifts = {}
    days_schedule = {}
    clopening_penalties_applied = 0
    backtrack_swaps_count = 0

    try:
        store_cfg = get_store_config()
        g_cfg = store_cfg.get("roster_rules", {}).get("gender_constraints", {})
        gender_constraints_enabled = g_cfg.get("enabled", True)
        min_male = int(g_cfg.get("service_min_male", 1))
        shift_rules = g_cfg.get("shifts", {}) if isinstance(g_cfg.get("shifts"), dict) else {}
        # Ca Sáng và Ca Tối đều phải có ít nhất 1 Nam phục vụ nếu service_min_male >= 1
        require_male_morning = bool(shift_rules.get("sang", g_cfg.get("require_male_morning", min_male >= 1))) if gender_constraints_enabled else False
        require_male_evening = bool(shift_rules.get("toi", g_cfg.get("require_male_evening", min_male >= 1))) if gender_constraints_enabled else False

        shifts_cfg = store_cfg.get("roster_rules", {}).get("shifts_per_week", {})
        min_shifts_quota = int(shifts_cfg.get("min", 3))
        max_shifts_quota = int(shifts_cfg.get("max", 10))
        default_target_shifts = int(shifts_cfg.get("default_target", 5))

        r_rules = store_cfg.get("roster_rules", {})
        is_small_store = (len(active_staff) <= 5) or bool(r_rules.get("small_store_mode", False))
        allow_solo_shift = bool(r_rules.get("allow_solo_shift_coverage", True)) if is_small_store else False
        relax_gender_deadlock = bool(r_rules.get("relax_gender_constraints_on_deadlock", True)) if is_small_store else False
    except Exception:
        gender_constraints_enabled = True
        require_male_morning = True
        require_male_evening = True
        min_shifts_quota = 3
        max_shifts_quota = 10
        default_target_shifts = 5
        is_small_store = (len(active_staff) <= 5)
        allow_solo_shift = is_small_store
        relax_gender_deadlock = is_small_store

    relaxed_constraints_log: List[dict] = []
    dual_role_assignments: List[dict] = []

    # Tính trước các ngày khả dụng và hạn ngạch (Quota) sàn min / trần target cho từng nhân sự
    user_avail_days = {u: set() for u in active_staff.keys()}
    for d_idx_check, d_iso_check in enumerate(target_info["days"]):
        dk_check = DAY_KEYS_ISO[d_idx_check]
        for u in active_staff.keys():
            t = _extract_day_pref_tags(regs, u, d_iso_check, d_idx_check, dk_check, input_days)
            if "OFF" in t:
                continue
            u_r = regs.get(u, {}) if isinstance(regs, dict) else {}
            p_src = u_r.get("preferences") if isinstance(u_r.get("preferences"), dict) else (
                u_r.get("days") if isinstance(u_r.get("days"), dict) else (
                    u_r.get("shifts") if isinstance(u_r.get("shifts"), dict) else None
                )
            )
            if isinstance(p_src, dict):
                day_in_prefs = (
                    dk_check in p_src or 
                    dk_check.upper() in p_src or 
                    str(d_idx_check) in p_src or 
                    d_idx_check in p_src or 
                    d_iso_check in p_src
                )
                if not day_in_prefs or not t:
                    continue
                user_avail_days[u].add(d_idx_check)
            elif t:
                user_avail_days[u].add(d_idx_check)

    user_min_quota = {}
    user_target_quota = {}
    for u in active_staff.keys():
        avail_cnt = len(user_avail_days[u])
        user_min_quota[u] = min(min_shifts_quota, avail_cnt)
        u_tgt = int(regs.get(u, {}).get("target_shifts") or default_target_shifts) if isinstance(regs, dict) else default_target_shifts
        user_target_quota[u] = min(max_shifts_quota, min(avail_cnt, u_tgt))

    prev_evening_staff: set = set()

    for day_idx, d in enumerate(target_info["days"]):
        d_key = DAY_KEYS_ISO[day_idx]
        dt = datetime.datetime.strptime(d, "%Y-%m-%d").date()
        iso_day = dt.isocalendar()[2]
        is_weekend = (iso_day in [6, 7])

        # Kiểm tra xem ngày liền trước trong input_days / input_shifts có sẵn ca tối cố định nào không
        if day_idx > 0:
            prev_d_iso = target_info["days"][day_idx - 1]
            prev_d_key = DAY_KEYS_ISO[day_idx - 1]
            if isinstance(input_days.get(prev_d_key), dict):
                prev_toi = input_days[prev_d_key].get("toi") or input_days[prev_d_key].get("evening") or {}
                if isinstance(prev_toi, dict):
                    for sl_k in ["barista", "service", "service_17", "service_18", "security"]:
                        val = prev_toi.get(sl_k)
                        if isinstance(val, list):
                            prev_evening_staff.update([x for x in val if x])
                        elif isinstance(val, str) and val:
                            prev_evening_staff.add(val)
            if isinstance(input_shifts.get(prev_d_iso), dict):
                prev_ev = input_shifts[prev_d_iso].get("evening") or {}
                if isinstance(prev_ev, dict):
                    for sl_k in ["barista", "service_17", "service_18", "service"]:
                        val = prev_ev.get(sl_k)
                        if isinstance(val, list):
                            prev_evening_staff.update([x for x in val if x])
                        elif isinstance(val, str) and val:
                            prev_evening_staff.add(val)

        sang_cfg = store_cfg.get("shifts", {}).get("sang", {})
        toi_cfg = store_cfg.get("shifts", {}).get("toi", {})
        m_req = get_shift_role_requirements(sang_cfg, is_weekend=is_weekend)
        e_req = get_shift_role_requirements(toi_cfg, is_weekend=is_weekend)
        m_needed_bar = m_req.get("barista", 1)
        m_needed_svc = m_req.get("service", 2)
        e_needed_bar = e_req.get("barista", 1 if is_weekend else 0)
        e_needed_svc = e_req.get("service", 2)

        day_shifts = {
            "morning": {
                "time": f"{sang_cfg.get('official_start', '06:00')} - {sang_cfg.get('official_end', '11:30')}",
                "manager": default_mgr,
                "barista": None,
                "baristas": [],
                "service": [None] * m_needed_svc
            },
            "evening": {
                "time": f"{toi_cfg.get('official_start', '17:00')} - {toi_cfg.get('official_end', '23:00')}",
                "manager": default_mgr,
                "barista": None,
                "baristas": [],
                "service": [None] * e_needed_svc,
                "service_17": None,
                "service_18": None
            }
        }

        def get_user_day_prefs(u: str) -> List[str]:
            return _extract_day_pref_tags(regs, u, d, day_idx, d_key, input_days)

        def is_user_off_today(u: str) -> bool:
            if isinstance(regs, dict) and len(regs) > 0 and u not in regs:
                return True
            tags = get_user_day_prefs(u)
            if "OFF" in tags:
                return True
            if isinstance(regs, dict) and u in regs and isinstance(regs[u], dict):
                u_r = regs[u]
                p_src = u_r.get("preferences") if isinstance(u_r.get("preferences"), dict) else (
                    u_r.get("days") if isinstance(u_r.get("days"), dict) else (
                        u_r.get("shifts") if isinstance(u_r.get("shifts"), dict) else None
                    )
                )
                if isinstance(p_src, dict):
                    day_in_prefs = (
                        d_key in p_src or 
                        d_key.upper() in p_src or 
                        str(day_idx) in p_src or 
                        day_idx in p_src or 
                        d in p_src
                    )
                    if not day_in_prefs or not tags:
                        return True
            return False

        def is_clopening_candidate(u: str) -> bool:
            return day_idx > 0 and (u in prev_evening_staff)

        def get_target_shifts(u: str) -> int:
            return user_target_quota.get(u, default_target_shifts)

        def can_user_work_shift_period(u: str, period_tag: str) -> bool:
            if is_user_off_today(u):
                return False
            tags = get_user_day_prefs(u)
            if not tags:
                return False
            if period_tag == "MORNING":
                return any(k in tags for k in ["MORNING", "MORNING_SANG", "SANG"])
            if period_tag == "EVENING":
                return any(k in tags for k in ["EVENING", "EVENING_17", "EVENING_18", "TOI"])
            return True

        def can_do_ev_17(u: str) -> bool:
            tags = get_user_day_prefs(u)
            if "EVENING_18" in tags and "EVENING_17" not in tags:
                return False
            return any(k in tags for k in ["EVENING", "EVENING_17", "TOI"])

        def can_do_ev_18(u: str) -> bool:
            tags = get_user_day_prefs(u)
            if "EVENING_17" in tags and "EVENING_18" not in tags:
                return False
            return any(k in tags for k in ["EVENING", "EVENING_18", "TOI"])

        assigned_today = set()

        # Preserve pinned slots from existing schedule to protect manual edits
        existing_day_shift = input_shifts.get(d) if isinstance(input_shifts, dict) else None
        pinned_m_bar = None
        pinned_m_svcs = []
        pinned_e_bar = None
        pinned_e_s17 = None
        pinned_e_s18 = None
        if isinstance(existing_day_shift, dict):
            ex_m = existing_day_shift.get("morning") or {}
            pinned_m_bar = ex_m.get("barista")
            if isinstance(ex_m.get("service"), list):
                pinned_m_svcs = [x for x in ex_m["service"] if x]
            
            ex_e = existing_day_shift.get("evening") or {}
            pinned_e_bar = ex_e.get("barista")
            pinned_e_s17 = ex_e.get("service_17")
            pinned_e_s18 = ex_e.get("service_18")

        # ------------------------------------------------------------------
        # A. Barista ca sáng (Áp dụng Anti-Clopening Rule)
        # ------------------------------------------------------------------
        avail_b_prim = [u for u in bar_primary if not is_user_off_today(u) and can_user_work_shift_period(u, "MORNING") and u not in assigned_today]
        avail_b_bk = [u for u in bar_backup if not is_user_off_today(u) and can_user_work_shift_period(u, "MORNING") and u not in assigned_today]

        def morning_bar_sort_key(u: str):
            clopen = 1 if is_clopening_candidate(u) else 0
            future_days = len([x for x in user_avail_days.get(u, set()) if x > day_idx])
            shifts_needed = user_min_quota.get(u, min_shifts_quota) - shift_counts[u]
            urgent_min = 0 if (shifts_needed > 0 and future_days <= shifts_needed) else 1
            under_min = 0 if shift_counts[u] < user_min_quota.get(u, min_shifts_quota) else 1
            tags = get_user_day_prefs(u)
            has_m = 0 if "MORNING" in tags else (1 if not tags else 2)
            over_target = 1 if shift_counts[u] >= get_target_shifts(u) else 0
            # Ưu tiên người chuyên Bar trước người đa năng (Bar + Service) khi bằng điểm để tránh kẹt slot Service
            is_multi = 1 if is_service_capable(active_staff.get(u, {})) else 0
            return (clopen, urgent_min, under_min, over_target, shift_counts[u], has_m, is_multi)

        if any(is_clopening_candidate(u) for u in avail_b_prim + avail_b_bk):
            clopening_penalties_applied += 1

        assigned_b = None
        if pinned_m_bar and pinned_m_bar in active_staff and not is_user_off_today(pinned_m_bar):
            assigned_b = pinned_m_bar
        else:
            non_clopen_prim = [u for u in avail_b_prim if not is_clopening_candidate(u) and can_user_work_shift_period(u, "MORNING")]
            non_clopen_bk_pref = [u for u in avail_b_bk if not is_clopening_candidate(u) and "MORNING" in get_user_day_prefs(u)]
            if non_clopen_prim:
                assigned_b = sorted(non_clopen_prim, key=morning_bar_sort_key)[0]
            elif non_clopen_bk_pref:
                assigned_b = sorted(non_clopen_bk_pref, key=morning_bar_sort_key)[0]
            elif avail_b_prim:
                assigned_b = sorted(avail_b_prim, key=morning_bar_sort_key)[0]
            elif avail_b_bk:
                assigned_b = sorted(avail_b_bk, key=morning_bar_sort_key)[0]

        assigned_m_bars = []
        if assigned_b:
            assigned_m_bars.append(assigned_b)
            day_shifts["morning"]["barista"] = assigned_b
            day_shifts["morning"]["missing_barista"] = False
            shift_counts[assigned_b] += 1
            assigned_today.add(assigned_b)
            if is_clopening_candidate(assigned_b):
                relaxed_constraints_log.append({
                    "day": d, "shift": "morning", "type": "CLOPENING_RELAXED", "user": assigned_b,
                    "note": "Nới lỏng chống clopening vì là nhân sự duy nhất khả dụng cho ca sáng"
                })
        else:
            day_shifts["morning"]["barista"] = None
            day_shifts["morning"]["missing_barista"] = True

        while len(assigned_m_bars) < m_needed_bar:
            avail_b_extra_prim = [u for u in bar_primary if not is_user_off_today(u) and can_user_work_shift_period(u, "MORNING") and u not in assigned_today]
            avail_b_extra_bk = [u for u in bar_backup if not is_user_off_today(u) and can_user_work_shift_period(u, "MORNING") and u not in assigned_today]
            extra_b = None
            if avail_b_extra_prim:
                extra_b = sorted(avail_b_extra_prim, key=morning_bar_sort_key)[0]
            elif avail_b_extra_bk:
                extra_b = sorted(avail_b_extra_bk, key=morning_bar_sort_key)[0]
            if extra_b:
                assigned_m_bars.append(extra_b)
                shift_counts[extra_b] += 1
                assigned_today.add(extra_b)
            else:
                break

        # ------------------------------------------------------------------
        # B. Barista ca tối (T7, CN hoặc khi e_needed_bar > 0)
        # ------------------------------------------------------------------
        assigned_ev_b = None
        if pinned_e_bar and pinned_e_bar in active_staff and not is_user_off_today(pinned_e_bar):
            assigned_ev_b = pinned_e_bar
        elif e_needed_bar > 0 or is_weekend:
            avail_ev_prim = [u for u in bar_primary if not is_user_off_today(u) and can_user_work_shift_period(u, "EVENING") and can_do_ev_17(u) and u not in assigned_today]
            avail_ev_bk = [u for u in bar_backup if not is_user_off_today(u) and can_user_work_shift_period(u, "EVENING") and can_do_ev_17(u) and u not in assigned_today]

            def evening_bar_sort_key(u: str):
                future_days = len([x for x in user_avail_days.get(u, set()) if x > day_idx])
                shifts_needed = user_min_quota.get(u, min_shifts_quota) - shift_counts[u]
                urgent_min = 0 if (shifts_needed > 0 and future_days <= shifts_needed) else 1
                under_min = 0 if shift_counts[u] < user_min_quota.get(u, min_shifts_quota) else 1
                tags = get_user_day_prefs(u)
                has_ev = 0 if any(k in tags for k in ["EVENING", "EVENING_17", "EVENING_18"]) else (1 if not tags else 2)
                over_target = 1 if shift_counts[u] >= get_target_shifts(u) else 0
                is_multi = 1 if is_service_capable(active_staff.get(u, {})) else 0
                return (urgent_min, under_min, over_target, shift_counts[u], has_ev, is_multi)

            if avail_ev_prim:
                assigned_ev_b = sorted(avail_ev_prim, key=evening_bar_sort_key)[0]
            elif avail_ev_bk:
                assigned_ev_b = sorted(avail_ev_bk, key=evening_bar_sort_key)[0]

        assigned_e_bars = []
        if assigned_ev_b:
            assigned_e_bars.append(assigned_ev_b)
            day_shifts["evening"]["barista"] = assigned_ev_b
            day_shifts["evening"]["missing_barista"] = False
            shift_counts[assigned_ev_b] += 1
            assigned_today.add(assigned_ev_b)
        else:
            day_shifts["evening"]["barista"] = None
            day_shifts["evening"]["missing_barista"] = (e_needed_bar > 0)

        while len(assigned_e_bars) < e_needed_bar:
            avail_ev_extra_prim = [u for u in bar_primary if not is_user_off_today(u) and can_user_work_shift_period(u, "EVENING") and u not in assigned_today]
            avail_ev_extra_bk = [u for u in bar_backup if not is_user_off_today(u) and can_user_work_shift_period(u, "EVENING") and u not in assigned_today]
            extra_ev_b = None
            if avail_ev_extra_prim:
                extra_ev_b = sorted(avail_ev_extra_prim, key=evening_bar_sort_key)[0]
            elif avail_ev_extra_bk:
                extra_ev_b = sorted(avail_ev_extra_bk, key=evening_bar_sort_key)[0]
            if extra_ev_b:
                assigned_e_bars.append(extra_ev_b)
                shift_counts[extra_ev_b] += 1
                assigned_today.add(extra_ev_b)
            else:
                break

        # ------------------------------------------------------------------
        # C. Phục vụ ca sáng (2 bạn) - Áp dụng Anti-Clopening + 1-Step Swap Backtracking
        # ------------------------------------------------------------------
        avail_servers_morning = [
            u for u, a in active_staff.items()
            if is_service_capable(a) and not is_user_off_today(u) and can_user_work_shift_period(u, "MORNING") and u not in assigned_today
        ]
        if any(is_clopening_candidate(u) for u in avail_servers_morning):
            clopening_penalties_applied += 1

        def morning_service_sort_key(u: str):
            clopen = 1 if is_clopening_candidate(u) else 0
            future_days = len([x for x in user_avail_days.get(u, set()) if x > day_idx])
            shifts_needed = user_min_quota.get(u, min_shifts_quota) - shift_counts[u]
            urgent_min = 0 if (shifts_needed > 0 and future_days <= shifts_needed) else 1
            under_min = 0 if shift_counts[u] < user_min_quota.get(u, min_shifts_quota) else 1
            pref_tag = 0 if "MORNING" in get_user_day_prefs(u) else (1 if not get_user_day_prefs(u) else 2)
            over_target = 1 if shift_counts[u] >= get_target_shifts(u) else 0
            return (clopen, urgent_min, under_min, over_target, shift_counts[u], pref_tag)

        sorted_s1 = sorted(avail_servers_morning, key=morning_service_sort_key)

        # 1. Check pinned morning service slots
        s1 = pinned_m_svcs[0] if (len(pinned_m_svcs) > 0 and pinned_m_svcs[0] in active_staff and not is_user_off_today(pinned_m_svcs[0]) and pinned_m_svcs[0] not in assigned_today) else None
        s2 = pinned_m_svcs[1] if (len(pinned_m_svcs) > 1 and pinned_m_svcs[1] in active_staff and not is_user_off_today(pinned_m_svcs[1]) and pinned_m_svcs[1] not in assigned_today and pinned_m_svcs[1] != s1) else None

        if s1:
            shift_counts[s1] += 1
            assigned_today.add(s1)
        if s2:
            shift_counts[s2] += 1
            assigned_today.add(s2)

        # 2. Fill s1 if still empty
        if s1 is None:
            avail_s1 = [u for u in sorted_s1 if u not in assigned_today]
            if avail_s1:
                s1 = avail_s1[0]
                shift_counts[s1] += 1
                assigned_today.add(s1)

        # 3. Fill s2 if still empty (enforcing gender constraint strictly)
        if s2 is None and s1:
            g1 = active_staff.get(s1, {}).get("gender", "NAM")
            avail_s2 = [u for u in sorted_s1 if u not in assigned_today]
            if require_male_morning and g1 == "NU":
                rem_males = [u for u in avail_s2 if active_staff.get(u, {}).get("gender") == "NAM"]
                if rem_males:
                    s2 = rem_males[0]
                    shift_counts[s2] += 1
                    assigned_today.add(s2)
                elif (is_small_store or relax_gender_deadlock) and avail_s2:
                    s2 = avail_s2[0]
                    shift_counts[s2] += 1
                    assigned_today.add(s2)
                    relaxed_constraints_log.append({
                        "day": d, "shift": "morning", "type": "GENDER_RELAXED",
                        "note": "Nới lỏng ràng buộc nam ca sáng do quán nhỏ không có nhân sự nam"
                    })
            elif avail_s2:
                s2 = avail_s2[0]
                shift_counts[s2] += 1
                assigned_today.add(s2)

        # C.2: 1-Step Swap Backtracking cho Ca Sáng (sang / morning)
        # Nếu ca sáng còn thiếu người (s1 is None hoặc s2 is None hoặc assigned_b is None)
        # trong khi có ứng viên `cand_u` khả dụng hôm nay nhưng chưa được gán do `other_u` đa năng chiếm slot
        unassigned_morning_cands = [
            u for u in active_staff.keys()
            if not is_user_off_today(u) and "MORNING_OFF" not in get_user_day_prefs(u) and u not in assigned_today and can_user_work_shift_period(u, "MORNING")
        ]
        if (s1 is None or s2 is None) and assigned_b and unassigned_morning_cands:
            # Kiểm tra xem `assigned_b` (other_u) có thể chuyển sang làm Phục vụ ca sáng để nhường Bar cho `cand_u` không
            other_u = assigned_b
            if is_service_capable(active_staff.get(other_u, {})):
                for cand_u in sorted(unassigned_morning_cands, key=morning_bar_sort_key):
                    if is_bar_capable(active_staff.get(cand_u, {})):
                        # Hoán vị 1 bước: other_u -> service, cand_u -> barista
                        assigned_b = cand_u
                        if other_u in assigned_m_bars:
                            idx = assigned_m_bars.index(other_u)
                            assigned_m_bars[idx] = cand_u
                        else:
                            assigned_m_bars.append(cand_u)

                        if s1 is None:
                            s1 = other_u
                        else:
                            s2 = other_u
                        shift_counts[cand_u] += 1
                        assigned_today.add(cand_u)
                        backtrack_swaps_count += 1
                        break
        elif assigned_b is None and unassigned_morning_cands:
            # Nếu thiếu Barista ca sáng mà trong s1/s2 có người đa năng (biết pha chế) và bên ngoài còn người phục vụ `cand_u`
            for cand_u in unassigned_morning_cands:
                if is_service_capable(active_staff.get(cand_u, {})):
                    if s1 and is_bar_capable(active_staff.get(s1, {})):
                        valid_g, _ = validate_service_gender_pair(cand_u, s2, active_staff, allow_relaxation=(is_small_store or relax_gender_deadlock))
                        if not valid_g and s2 is not None:
                            continue
                        other_u = s1
                        assigned_b = other_u
                        day_shifts["morning"]["missing_barista"] = False
                        if not assigned_m_bars:
                            assigned_m_bars.append(other_u)
                        else:
                            assigned_m_bars[0] = other_u
                        s1 = cand_u
                        shift_counts[cand_u] += 1
                        assigned_today.add(cand_u)
                        backtrack_swaps_count += 1
                        break
                    elif s2 and is_bar_capable(active_staff.get(s2, {})):
                        valid_g, _ = validate_service_gender_pair(s1, cand_u, active_staff, allow_relaxation=(is_small_store or relax_gender_deadlock))
                        if not valid_g and s1 is not None:
                            continue
                        other_u = s2
                        assigned_b = other_u
                        day_shifts["morning"]["missing_barista"] = False
                        if not assigned_m_bars:
                            assigned_m_bars.append(other_u)
                        else:
                            assigned_m_bars[0] = other_u
                        s2 = cand_u
                        shift_counts[cand_u] += 1
                        assigned_today.add(cand_u)
                        backtrack_swaps_count += 1
                        break

        # C.3: ADR-008 Skill-Coverage Bitmask & Kiêm nhiệm (Dual-Role / Solo Coverage) cho Ca Sáng quán nhỏ
        if (is_small_store or allow_solo_shift):
            # Tình huống 1: Có Barista (assigned_b) nhưng không có ai làm Phục vụ (s1 is None and s2 is None)
            if assigned_b and not s1 and not s2 and not unassigned_morning_cands:
                b_mask = compute_staff_skill_mask(active_staff.get(assigned_b, {}))
                if (b_mask & SKILL_SERVICE) or is_service_capable(active_staff.get(assigned_b, {})):
                    s1 = assigned_b
                    day_shifts["morning"]["dual_role"] = True
                    day_shifts["morning"]["is_solo_capable"] = True
                    dual_role_assignments.append({
                        "day": d, "shift": "morning", "user": assigned_b, "roles": ["BAR", "SERVICE"]
                    })
                    relaxed_constraints_log.append({
                        "day": d, "shift": "morning", "type": "SOLO_DUAL_ROLE",
                        "user": assigned_b, "note": "Nhân sự kiêm nhiệm đảm nhiệm trọn gói ca sáng"
                    })
            # Tình huống 2: Có Phục vụ (s1 hoặc s2) nhưng không có Barista (assigned_b is None)
            elif not assigned_b and (s1 or s2) and not unassigned_morning_cands:
                solo_cand = s1 or s2
                cand_mask = compute_staff_skill_mask(active_staff.get(solo_cand, {}))
                if (cand_mask & SKILL_BAR) or is_bar_capable(active_staff.get(solo_cand, {})):
                    assigned_b = solo_cand
                    assigned_m_bars = [solo_cand]
                    day_shifts["morning"]["barista"] = solo_cand
                    day_shifts["morning"]["missing_barista"] = False
                    day_shifts["morning"]["dual_role"] = True
                    dual_role_assignments.append({
                        "day": d, "shift": "morning", "user": solo_cand, "roles": ["SERVICE", "BAR"]
                    })
                    relaxed_constraints_log.append({
                        "day": d, "shift": "morning", "type": "SOLO_DUAL_ROLE",
                        "user": solo_cand, "note": "Nhân sự phục vụ kiêm nhiệm pha chế ca sáng"
                    })

        assigned_m_svcs = [s for s in [s1, s2] if s]
        if m_needed_svc > 2:
            avail_extra_svc_m = [
                u for u in sorted_s1
                if u not in assigned_today
                and u not in assigned_m_svcs
                and can_user_work_shift_period(u, "MORNING")
            ]
            for extra_s in avail_extra_svc_m:
                if len(assigned_m_svcs) >= m_needed_svc:
                    break
                assigned_m_svcs.append(extra_s)
                shift_counts[extra_s] += 1
                assigned_today.add(extra_s)

        day_shifts["morning"]["service"] = assigned_m_svcs

        # ------------------------------------------------------------------
        # D. Phục vụ ca tối (Slot 17h & Slot 18h) + 1-Step Swap Backtracking
        # ------------------------------------------------------------------
        avail_servers_evening = [
            u for u, a in active_staff.items()
            if is_service_capable(a)
            and not is_user_off_today(u)
            and can_user_work_shift_period(u, "EVENING")
            and u not in assigned_today
        ]

        def evening_service_sort_key(u: str):
            future_days = len([x for x in user_avail_days.get(u, set()) if x > day_idx])
            shifts_needed = user_min_quota.get(u, min_shifts_quota) - shift_counts[u]
            urgent_min = 0 if (shifts_needed > 0 and future_days <= shifts_needed) else 1
            under_min = 0 if shift_counts[u] < user_min_quota.get(u, min_shifts_quota) else 1
            over_target = 1 if shift_counts[u] >= get_target_shifts(u) else 0
            pref_order = 0 if "EVENING_17" in get_user_day_prefs(u) else (1 if any(k in get_user_day_prefs(u) for k in ["EVENING_18", "EVENING"]) else 2)
            return (urgent_min, under_min, over_target, shift_counts[u], pref_order)

        sorted_17 = sorted(avail_servers_evening, key=evening_service_sort_key)

        # 1. Check pinned evening service slots
        s_17 = pinned_e_s17 if (pinned_e_s17 and pinned_e_s17 in active_staff and not is_user_off_today(pinned_e_s17) and pinned_e_s17 not in assigned_today) else None
        s_18 = pinned_e_s18 if (pinned_e_s18 and pinned_e_s18 in active_staff and not is_user_off_today(pinned_e_s18) and pinned_e_s18 not in assigned_today and pinned_e_s18 != s_17) else None

        if s_17:
            shift_counts[s_17] += 1
            assigned_today.add(s_17)
        if s_18:
            shift_counts[s_18] += 1
            assigned_today.add(s_18)

        # 2. Fill s_17 if still empty
        if s_17 is None:
            avail_17 = [u for u in sorted_17 if can_do_ev_17(u) and u not in assigned_today]
            if avail_17:
                s_17 = avail_17[0]
                shift_counts[s_17] += 1
                assigned_today.add(s_17)

        # 3. Fill s_18 if still empty (enforcing gender constraint strictly)
        if s_18 is None:
            avail_18 = [u for u in sorted_17 if can_do_ev_18(u) and u not in assigned_today]
            if avail_18:
                if require_male_evening and s_17:
                    g17 = active_staff.get(s_17, {}).get("gender", "NAM")
                    if g17 == "NU":
                        rem_males_18 = [u for u in avail_18 if active_staff.get(u, {}).get("gender") == "NAM"]
                        if rem_males_18:
                            s_18 = rem_males_18[0]
                            shift_counts[s_18] += 1
                            assigned_today.add(s_18)
                        elif (is_small_store or relax_gender_deadlock) and avail_18:
                            s_18 = avail_18[0]
                            shift_counts[s_18] += 1
                            assigned_today.add(s_18)
                            relaxed_constraints_log.append({
                                "day": d, "shift": "evening", "type": "GENDER_RELAXED",
                                "note": "Nới lỏng ràng buộc nam ca tối do quán nhỏ không có nhân sự nam"
                            })
                    else:
                        s_18 = avail_18[0]
                        shift_counts[s_18] += 1
                        assigned_today.add(s_18)
                else:
                    s_18 = avail_18[0]
                    shift_counts[s_18] += 1
                    assigned_today.add(s_18)

        # D.2: 1-Step Swap Backtracking cho Ca Tối (giữa Barista ca tối và Service ca tối)
        unassigned_evening_cands = [
            u for u in active_staff.keys()
            if not is_user_off_today(u) and u not in assigned_today and can_user_work_shift_period(u, "EVENING") and shift_counts[u] < get_target_shifts(u)
        ]
        if (s_17 is None or s_18 is None) and assigned_ev_b and unassigned_evening_cands:
            other_u = assigned_ev_b
            if is_service_capable(active_staff.get(other_u, {})):
                for cand_u in unassigned_evening_cands:
                    if is_bar_capable(active_staff.get(cand_u, {})):
                        assigned_ev_b = cand_u
                        if other_u in assigned_e_bars:
                            idx = assigned_e_bars.index(other_u)
                            assigned_e_bars[idx] = cand_u
                        else:
                            assigned_e_bars.append(cand_u)

                        if s_17 is None and can_do_ev_17(other_u):
                            s_17 = other_u
                        elif s_18 is None and can_do_ev_18(other_u):
                            s_18 = other_u
                        else:
                            if other_u in assigned_e_bars:
                                idx = assigned_e_bars.index(cand_u)
                                assigned_e_bars[idx] = other_u
                            else:
                                assigned_e_bars.pop()
                            continue
                        shift_counts[cand_u] += 1
                        assigned_today.add(cand_u)
                        backtrack_swaps_count += 1
                        break
        elif is_weekend and assigned_ev_b is None and unassigned_evening_cands:
            for cand_u in unassigned_evening_cands:
                if is_service_capable(active_staff.get(cand_u, {})):
                    if s_17 and is_bar_capable(active_staff.get(s_17, {})) and can_do_ev_17(cand_u):
                        valid_g, _ = validate_service_gender_pair(cand_u, s_18, active_staff, allow_relaxation=(is_small_store or relax_gender_deadlock))
                        if not valid_g and s_18 is not None:
                            continue
                        other_u = s_17
                        assigned_ev_b = other_u
                        day_shifts["evening"]["missing_barista"] = False
                        if not assigned_e_bars:
                            assigned_e_bars.append(other_u)
                        else:
                            assigned_e_bars[0] = other_u
                        s_17 = cand_u
                        shift_counts[cand_u] += 1
                        assigned_today.add(cand_u)
                        backtrack_swaps_count += 1
                        break
                    elif s_18 and is_bar_capable(active_staff.get(s_18, {})) and can_do_ev_18(cand_u):
                        valid_g, _ = validate_service_gender_pair(s_17, cand_u, active_staff, allow_relaxation=(is_small_store or relax_gender_deadlock))
                        if not valid_g and s_17 is not None:
                            continue
                        other_u = s_18
                        assigned_ev_b = other_u
                        day_shifts["evening"]["missing_barista"] = False
                        if not assigned_e_bars:
                            assigned_e_bars.append(other_u)
                        else:
                            assigned_e_bars[0] = other_u
                        s_18 = cand_u
                        shift_counts[cand_u] += 1
                        assigned_today.add(cand_u)
                        backtrack_swaps_count += 1
                        break

        # D.3: ADR-008 Skill-Coverage Bitmask & Kiêm nhiệm cho Ca Tối quán nhỏ
        if (is_small_store or allow_solo_shift):
            # Tình huống 1: Ca tối cần Barista (cuối tuần hoặc e_needed_bar > 0) mà assigned_ev_b is None
            if (e_needed_bar > 0 or is_weekend) and not assigned_ev_b and (s_17 or s_18):
                for cand_ev in [s_17, s_18]:
                    if cand_ev:
                        cand_mask = compute_staff_skill_mask(active_staff.get(cand_ev, {}))
                        if (cand_mask & SKILL_BAR) or is_bar_capable(active_staff.get(cand_ev, {})):
                            assigned_ev_b = cand_ev
                            assigned_e_bars = [cand_ev]
                            day_shifts["evening"]["barista"] = cand_ev
                            day_shifts["evening"]["missing_barista"] = False
                            day_shifts["evening"]["dual_role"] = True
                            dual_role_assignments.append({
                                "day": d, "shift": "evening", "user": cand_ev, "roles": ["SERVICE", "BAR"]
                            })
                            relaxed_constraints_log.append({
                                "day": d, "shift": "evening", "type": "SOLO_DUAL_ROLE",
                                "user": cand_ev, "note": "Nhân sự phục vụ kiêm nhiệm pha chế ca tối"
                            })
                            break
            # Tình huống 2: Có assigned_ev_b nhưng khuyết slot service_17 hoặc service_18 mà không còn ai khác
            elif assigned_ev_b and (s_17 is None or s_18 is None) and not unassigned_evening_cands:
                b_mask = compute_staff_skill_mask(active_staff.get(assigned_ev_b, {}))
                if (b_mask & SKILL_SERVICE) or is_service_capable(active_staff.get(assigned_ev_b, {})):
                    if s_17 is None and can_do_ev_17(assigned_ev_b):
                        s_17 = assigned_ev_b
                        day_shifts["evening"]["dual_role"] = True
                        dual_role_assignments.append({
                            "day": d, "shift": "evening", "user": assigned_ev_b, "roles": ["BAR", "SERVICE_17"]
                        })
                        relaxed_constraints_log.append({
                            "day": d, "shift": "evening", "type": "SOLO_DUAL_ROLE",
                            "user": assigned_ev_b, "note": "Pha chế kiêm nhiệm phục vụ slot 17h ca tối"
                        })
                    elif s_18 is None and can_do_ev_18(assigned_ev_b):
                        s_18 = assigned_ev_b
                        day_shifts["evening"]["dual_role"] = True
                        dual_role_assignments.append({
                            "day": d, "shift": "evening", "user": assigned_ev_b, "roles": ["BAR", "SERVICE_18"]
                        })
                        relaxed_constraints_log.append({
                            "day": d, "shift": "evening", "type": "SOLO_DUAL_ROLE",
                            "user": assigned_ev_b, "note": "Pha chế kiêm nhiệm phục vụ slot 18h ca tối"
                        })

            # Tình huống 3: Ca tối chỉ có 1 bạn phục vụ solo
            if len([s for s in [s_17, s_18] if s]) == 1:
                day_shifts["evening"]["is_solo_capable"] = True

        assigned_e_svcs = [s for s in [s_17, s_18] if s]
        if e_needed_svc > 2:
            avail_extra = [
                u for u in sorted_17
                if u not in assigned_today
                and u not in assigned_e_svcs
                and can_user_work_shift_period(u, "EVENING")
            ]
            for extra_s in avail_extra:
                if len(assigned_e_svcs) >= e_needed_svc:
                    break
                assigned_e_svcs.append(extra_s)
                shift_counts[extra_s] += 1
                assigned_today.add(extra_s)

        # Tính toán Skill Coverage Metrics cho Ca Sáng & Ca Tối
        m_req_mask = SKILL_BAR | SKILL_SERVICE
        is_cov_m, comb_mask_m, cov_ratio_m = check_skill_coverage(assigned_m_bars + assigned_m_svcs, active_staff, m_req_mask)
        day_shifts["morning"]["barista"] = assigned_m_bars[0] if assigned_m_bars else None
        day_shifts["morning"]["baristas"] = assigned_m_bars
        day_shifts["morning"]["service"] = assigned_m_svcs
        day_shifts["morning"]["skill_mask"] = comb_mask_m
        day_shifts["morning"]["coverage_ratio"] = cov_ratio_m
        day_shifts["morning"]["is_fully_covered"] = is_cov_m
        if is_small_store and is_cov_m:
            day_shifts["morning"]["missing_barista"] = False
        else:
            day_shifts["morning"]["missing_barista"] = len(assigned_m_bars) < m_needed_bar

        e_req_mask = SKILL_SERVICE | (SKILL_BAR if (is_weekend or e_needed_bar > 0) else 0)
        is_cov_e, comb_mask_e, cov_ratio_e = check_skill_coverage(assigned_e_bars + assigned_e_svcs, active_staff, e_req_mask)
        day_shifts["evening"]["barista"] = assigned_e_bars[0] if assigned_e_bars else None
        day_shifts["evening"]["baristas"] = assigned_e_bars
        day_shifts["evening"]["service_17"] = s_17
        day_shifts["evening"]["service_18"] = s_18
        day_shifts["evening"]["service"] = assigned_e_svcs
        day_shifts["evening"]["skill_mask"] = comb_mask_e
        day_shifts["evening"]["coverage_ratio"] = cov_ratio_e
        day_shifts["evening"]["is_fully_covered"] = is_cov_e
        if e_needed_bar == 0:
            day_shifts["evening"]["missing_barista"] = False
        elif is_small_store and is_cov_e:
            day_shifts["evening"]["missing_barista"] = False
        else:
            day_shifts["evening"]["missing_barista"] = len(assigned_e_bars) < e_needed_bar

        shifts[d] = day_shifts
        days_schedule[d_key] = {
            "date": d,
            "sang": {
                "manager": default_mgr,
                "barista": assigned_m_bars,
                "service": assigned_m_svcs,
                "security": [],
                "dual_role": day_shifts["morning"].get("dual_role", False),
                "coverage_ratio": cov_ratio_m,
            },
            "toi": {
                "manager": default_mgr,
                "barista": assigned_e_bars,
                "service_17": [s_17] if s_17 else [],
                "service_18": [s_18] if s_18 else [],
                "service": assigned_e_svcs,
                "security": [],
                "dual_role": day_shifts["evening"].get("dual_role", False),
                "coverage_ratio": cov_ratio_e,
            }
        }

        # Cập nhật danh sách nhân sự làm Ca Tối hôm nay để kiểm tra Anti-Clopening cho Ca Sáng ngày mai
        prev_evening_staff = {u for u in (assigned_e_bars + assigned_e_svcs) if u}

    # ==================================================================
    # PASS 2: FAIR-SHARE BALANCING PASS (CÂN BẰNG PHÂN BỔ ĐẠT SÀN TỐI THIỂU)
    # ==================================================================
    # Nếu còn nhân sự nào chưa đạt user_min_quota (sàn 3 ca):
    # Tìm kiếm hoán vị an toàn với nhân sự đang có số ca dôi dư (> user_min_quota)
    for _ in range(10):
        under_quota_users = [u for u in active_staff.keys() if shift_counts[u] < user_min_quota.get(u, min_shifts_quota)]
        if not under_quota_users:
            break
        swapped_any = False
        for u_need in under_quota_users:
            if shift_counts[u_need] >= user_min_quota.get(u_need, min_shifts_quota):
                continue
            for d_idx, d_str in enumerate(target_info["days"]):
                if d_idx not in user_avail_days.get(u_need, set()):
                    continue
                day_sh = shifts[d_str]
                day_assigned = {day_sh["morning"]["barista"]} | set(day_sh["morning"]["service"]) | {day_sh["evening"]["barista"], day_sh["evening"]["service_17"], day_sh["evening"]["service_18"]}
                if u_need in day_assigned:
                    continue

                u_need_tags = _extract_day_pref_tags(regs, u_need, d_str, d_idx, DAY_KEYS_ISO[d_idx], input_days)

                # 1. Thử thế chỗ Morning Service (BẮT BUỘC có đăng ký MORNING)
                can_morning = "MORNING" in u_need_tags and "OFF" not in u_need_tags and is_service_capable(active_staff.get(u_need, {}))
                prev_ev = set()
                if d_idx > 0:
                    prev_d_str = target_info["days"][d_idx - 1]
                    prev_ev = {shifts[prev_d_str]["evening"]["barista"], shifts[prev_d_str]["evening"]["service_17"], shifts[prev_d_str]["evening"]["service_18"]}
                if can_morning and u_need not in prev_ev:
                    for s_idx, cur_s in enumerate(day_sh["morning"]["service"]):
                        if cur_s and cur_s != u_need and shift_counts[cur_s] > user_min_quota.get(cur_s, min_shifts_quota):
                            other_svcs = [s for j, s in enumerate(day_sh["morning"]["service"]) if j != s_idx and s]
                            other_s = other_svcs[0] if other_svcs else None
                            valid_g, _ = validate_service_gender_pair(u_need, other_s, active_staff, allow_relaxation=(is_small_store or relax_gender_deadlock))
                            if valid_g:
                                day_sh["morning"]["service"][s_idx] = u_need
                                days_schedule[DAY_KEYS_ISO[d_idx]]["sang"]["service"] = [x for x in day_sh["morning"]["service"] if x]
                                shift_counts[cur_s] -= 1
                                shift_counts[u_need] += 1
                                backtrack_swaps_count += 1
                                swapped_any = True
                                break
                    if shift_counts[u_need] >= user_min_quota.get(u_need, min_shifts_quota):
                        break

                # 2. Thử thế chỗ Evening Service (BẮT BUỘC có đăng ký EVENING)
                can_evening = any(k in u_need_tags for k in ["EVENING", "EVENING_17", "EVENING_18", "TOI"]) and "OFF" not in u_need_tags and is_service_capable(active_staff.get(u_need, {}))
                next_morning = set()
                if d_idx < len(target_info["days"]) - 1:
                    next_d_str = target_info["days"][d_idx + 1]
                    next_morning = {shifts[next_d_str]["morning"]["barista"]} | set(shifts[next_d_str]["morning"]["service"])
                if can_evening and u_need not in next_morning:
                    for ev_slot in ["service_17", "service_18"]:
                        if ev_slot == "service_17" and ("EVENING_18" in u_need_tags and "EVENING_17" not in u_need_tags):
                            continue
                        if ev_slot == "service_18" and ("EVENING_17" in u_need_tags and "EVENING_18" not in u_need_tags):
                            continue
                        cur_ev = day_sh["evening"][ev_slot]
                        if cur_ev and cur_ev != u_need and shift_counts[cur_ev] > user_min_quota.get(cur_ev, min_shifts_quota):
                            other_ev = day_sh["evening"]["service_18" if ev_slot == "service_17" else "service_17"]
                            valid_g, _ = validate_service_gender_pair(u_need, other_ev, active_staff, allow_relaxation=(is_small_store or relax_gender_deadlock))
                            if valid_g:
                                day_sh["evening"][ev_slot] = u_need
                                days_schedule[DAY_KEYS_ISO[d_idx]]["toi"][ev_slot] = [u_need]
                                days_schedule[DAY_KEYS_ISO[d_idx]]["toi"]["service"] = [x for x in [day_sh["evening"]["service_17"], day_sh["evening"]["service_18"]] if x]
                                day_sh["evening"]["service"] = [x for x in [day_sh["evening"]["service_17"], day_sh["evening"]["service_18"]] if x]
                                shift_counts[cur_ev] -= 1
                                shift_counts[u_need] += 1
                                backtrack_swaps_count += 1
                                swapped_any = True
                                break
                    if shift_counts[u_need] >= user_min_quota.get(u_need, min_shifts_quota):
                        break
            if swapped_any:
                break
        if not swapped_any:
            break

    solver_meta = {
        "engine": "Timefold-Greedy-Backtrack-v2",
        "anti_clopening_enabled": True,
        "clopening_checks": clopening_penalties_applied,
        "backtrack_swaps": backtrack_swaps_count,
        "small_store_mode": is_small_store,
        "skill_mask_enabled": True,
        "relaxed_constraints": relaxed_constraints_log,
        "dual_role_assignments": dual_role_assignments,
    }

    week_entry["shifts"] = shifts
    week_entry["days"] = days_schedule
    week_entry["solver_meta"] = solver_meta
    week_entry["status"] = "DRAFT"
    week_entry["last_autofill"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if save_to_disk and passed_week_dict is None:
        save_roster_data(roster_data)

    summary = {
        active_staff.get(u, {}).get("full_name", u): count
        for u, count in shift_counts.items()
        if count > 0
    }

    return {
        "success": True,
        "message": f"Đã tự động xếp lịch ca tuần {target_week_id} thành công!",
        "week_id": target_week_id,
        "week_key": target_week_id,
        "workload_summary": summary,
        "assigned_counts": shift_counts,
        "shifts": shifts,
        "days": days_schedule,
        "solver_meta": solver_meta
    }



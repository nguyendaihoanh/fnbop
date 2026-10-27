# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
FnBOps On-Premise Excel Manager
Workstream 1: SQLite Schema & Excel Manager
Export and Import Payroll and Staff Data via openpyxl
Styled with FnBOps Slate Navy (#18222F) & Vibrant Coral (#FF6D3E)
"""

import io
import os
import json
import logging
import datetime
import unicodedata
import re
from typing import Optional, List, Dict, Any, Tuple

try:
    import openpyxl
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False
    openpyxl = None
    Workbook = None
    Font = PatternFill = Alignment = Border = Side = None
    get_column_letter = None

try:
    from services.db import (
        get_db_connection,
        get_db_path,
        list_staff_accounts,
        upsert_staff_account,
        list_evaluations,
        list_staff_ledgers,
        list_so_cai_luong,
        migrate_seed_data_from_json,
        DEFAULT_TENANT_ID
    )
    from services.payroll_calc import (
        calculate_staff_payslip_breakdown,
        get_canonical_name,
        normalize_str
    )
    from services.storage import hash_pin, needs_rehash
    from services.store_config import get_store_config
except ImportError:
    from backend.services.db import (
        get_db_connection,
        get_db_path,
        list_staff_accounts,
        upsert_staff_account,
        list_evaluations,
        list_staff_ledgers,
        list_so_cai_luong,
        migrate_seed_data_from_json,
        DEFAULT_TENANT_ID
    )
    from backend.services.payroll_calc import (
        calculate_staff_payslip_breakdown,
        get_canonical_name,
        normalize_str
    )
    from backend.services.storage import hash_pin, needs_rehash
    from backend.services.store_config import get_store_config

logger = logging.getLogger("excel_manager")

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ROOT_DIR = os.path.dirname(_BASE_DIR)


def _load_data_json() -> Dict[str, Any]:
    """Helper to locate and load data.json."""
    candidates = [
        os.getenv("DATA_FILE"),
        os.path.join(_ROOT_DIR, "frontend", "data.json"),
        os.path.join(_BASE_DIR, "frontend", "data.json"),
        os.path.join(_ROOT_DIR, "data.json"),
        os.path.join(_BASE_DIR, "data.json")
    ]
    for c in candidates:
        if c and os.path.exists(c):
            try:
                with open(c, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read {c}: {e}")
    return {}


def _load_shift_approvals(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Helper to load shift approvals from SQLite with JSON fallback."""
    try:
        from services.db import list_shift_approvals_db
        db_approvals = list_shift_approvals_db(db_path=db_path)
        if db_approvals:
            return db_approvals
    except Exception:
        pass
    candidates = [
        os.path.join(_ROOT_DIR, "data", "shift_approvals.json"),
        os.path.join(_BASE_DIR, "data", "shift_approvals.json"),
        os.path.join(_BASE_DIR, "shift_approvals.json")
    ]
    for c in candidates:
        if c and os.path.exists(c):
            try:
                with open(c, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return {}


def _load_attendance_logs(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Helper to load attendance logs from SQLite (Single Source of Truth) with JSON fallback."""
    try:
        from services.db import get_db_connection
        conn = get_db_connection(db_path)
        cur = conn.cursor()
        cur.execute("SELECT * FROM attendance_logs ORDER BY date DESC, id DESC")
        rows = cur.fetchall()
        conn.close()
        if rows:
            logs = []
            for r in rows:
                r_dict = dict(r)
                log = {
                    "id": f"ATT_SQLITE_{r_dict['id']}",
                    "username": r_dict["username"],
                    "display_name": r_dict["full_name"],
                    "full_name": r_dict["full_name"],
                    "date": r_dict["date"],
                    "shift_name": r_dict["shift"],
                    "shift_key": "sang" if "sang" in str(r_dict["shift"]).lower() else ("toi" if "toi" in str(r_dict["shift"]).lower() else r_dict["shift"]),
                    "checkin_time": r_dict["checkin"],
                    "checkout_time": r_dict["checkout"],
                    "total_mins": r_dict["duration_mins"] or 0,
                    "status": r_dict["status"],
                    "note": r_dict["note"],
                    "created_at": r_dict["created_at"],
                    "hourly_rate_snapshot": r_dict["hourly_rate_snapshot"],
                    "scheduled_start": r_dict["scheduled_start"],
                    "scheduled_end": r_dict["scheduled_end"],
                    "effective_duration_mins": r_dict["effective_duration_mins"],
                    "is_hanging_pending": bool(r_dict["is_hanging_pending"]),
                }
                logs.append(log)
            return logs
    except Exception:
        pass
    candidates = [
        os.path.join(_ROOT_DIR, "data", "attendance_logs.json"),
        os.path.join(_BASE_DIR, "data", "attendance_logs.json")
    ]
    for c in candidates:
        if c and os.path.exists(c):
            try:
                with open(c, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return []


# ==============================================================================
# 1. EXPORT PAYROLL EXCEL
# ==============================================================================

def export_payroll_excel(month_str: str = "9", db_path: Optional[str] = None) -> bytes:
    """
    Exports a professional, branded Excel payroll spreadsheet for the given month.
    - FnBOps Brand Colors: Slate Navy (#18222F) header & white text.
    - Columns: STT, Mã NV, Tên NV, Chức vụ, Tổng ca, Tổng giờ, Lương chuẩn,
               Tiền OT, Phụ cấp ngày lễ, Thưởng, Khấu trừ/Phạt, Ứng lương, Thực lĩnh.
    - Excel Net Pay Formula: =G{row}+H{row}+I{row}+J{row}-K{row}-L{row}
    - Formats: #,##0 "đ", proper alignments, auto-fit column widths.
    """
    clean_month = str(month_str or "9").strip()
    if not HAS_OPENPYXL:
        raise RuntimeError("Thư viện 'openpyxl' chưa được cài đặt trên hệ thống. Vui lòng cài đặt qua 'pip install openpyxl' để kích hoạt tính năng xuất Excel.")

    # 1. Fetch staff accounts from SQLite, or auto-seed from JSON if empty
    staff_list = list_staff_accounts(db_path=db_path)
    if not staff_list:
        migrate_seed_data_from_json(db_path=db_path)
        staff_list = list_staff_accounts(db_path=db_path)

    data_json = _load_data_json()
    approvals = _load_shift_approvals(db_path=db_path)
    evals = list_evaluations(month=clean_month, db_path=db_path)
    attendance_logs = _load_attendance_logs(db_path=db_path)
    ledgers = list_staff_ledgers(month=clean_month, db_path=db_path)
    so_cai_luong = list_so_cai_luong(month=clean_month, db_path=db_path)

    # Detect unreviewed hanging / forgotten checkout shifts in this period
    pending_hanging = []
    for log in attendance_logs:
        if log.get("is_hanging_pending") or log.get("status") == "QUEN_CHECKOUT":
            ld = str(log.get("date") or "")
            lm = ""
            if "/" in ld:
                p = ld.split("/")
                if len(p) >= 2:
                    lm = str(int(p[1]))
            elif "-" in ld:
                p = ld.split("-")
                if len(p) >= 2:
                    lm = str(int(p[1]))
            if not clean_month or clean_month == "all" or lm == str(int(clean_month)):
                pending_hanging.append(log)

    try:
        conn = get_db_connection(db_path)
        cur = conn.cursor()
        cur.execute("""
            SELECT username, full_name, date, shift, status 
            FROM attendance_logs 
            WHERE is_hanging_pending = 1 AND (date LIKE ? OR date LIKE ?)
        """, (f"%/{clean_month.zfill(2)}/%", f"%-{clean_month.zfill(2)}-%"))
        for r in cur.fetchall():
            row_dict = dict(r)
            if not any(p.get("username") == row_dict.get("username") and p.get("date") == row_dict.get("date") for p in pending_hanging):
                pending_hanging.append(row_dict)
        conn.close()
    except Exception:
        pass

    # 2. Filter active staff or staff with worked shifts/ledger in this month
    active_staff = [s for s in staff_list if s.get("is_active", True) or s.get("status") != "INACTIVE"]
    if not active_staff:
        # Fallback to all staff if none explicitly active
        active_staff = staff_list

    # Sort: Managers first, then alphabetically by name
    active_staff.sort(key=lambda s: (0 if "MAN" in s.get("role", "") else 1, s.get("display_name") or s.get("full_name") or s.get("username")))

    # 3. Create openpyxl Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = f"Bảng Lương T{clean_month}"
    ws.views.sheetView[0].showGridLines = True

    # Styling definitions
    font_family = "Segoe UI"
    header_navy = "18222F"
    header_fill = PatternFill(start_color=header_navy, end_color=header_navy, fill_type="solid")
    header_font = Font(name=font_family, size=10, bold=True, color="FFFFFF")

    thin_border = Border(
        left=Side(style="thin", color="CBD5E1"),
        right=Side(style="thin", color="CBD5E1"),
        top=Side(style="thin", color="CBD5E1"),
        bottom=Side(style="thin", color="CBD5E1")
    )
    total_border = Border(
        left=Side(style="thin", color="CBD5E1"),
        right=Side(style="thin", color="CBD5E1"),
        top=Side(style="thin", color="18222F"),
        bottom=Side(style="double", color="18222F")
    )
    total_fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
    zebra_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    white_fill = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")

    currency_fmt = '#,##0 "đ"'
    hours_fmt = '#,##0.00'
    int_fmt = '#,##0'

    # Row 1: Brand Banner
    ws.merge_cells("A1:M1")
    cell_title = ws["A1"]
    store_cfg = get_store_config()
    store_name_upper = str(store_cfg.get("store_name") or "FnBOps Store Lounge").strip().upper()
    cell_title.value = f"{store_name_upper} — BẢNG LƯƠNG CHI TIẾT THÁNG {clean_month}/2026"
    cell_title.font = Font(name=font_family, size=14, bold=True, color="FFFFFF")
    cell_title.fill = header_fill
    cell_title.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 36

    # Row 2: Subtitle / Metadata
    ws.merge_cells("A2:M2")
    cell_sub = ws["A2"]
    now_str = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    cell_sub.value = f"Kỳ đối soát lương: Tháng {clean_month} | Ngày xuất: {now_str} | Chế độ: On-Premise Tự Trị | Đơn vị: VNĐ"
    cell_sub.font = Font(name=font_family, size=9.5, italic=True, color="475569")
    cell_sub.fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    cell_sub.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[2].height = 20

    hanging_unames = {p.get("username") for p in pending_hanging if p.get("username")}
    hanging_names = {get_canonical_name(p.get("full_name") or "") for p in pending_hanging if p.get("full_name")}

    # Row 3 (optional): Warning Banner if hanging shifts exist
    curr_row = 3
    if pending_hanging:
        ws.merge_cells(f"A{curr_row}:M{curr_row}")
        c_warn = ws[f"A{curr_row}"]
        c_warn.value = f"⚠️ CẢNH BÁO QUYẾT TOÁN: Còn {len(pending_hanging)} ca quên check-out (QUEN_CHECKOUT) chưa được Quản lý duyệt! Các ca này hiện đang tạm tính 0đ."
        c_warn.font = Font(name=font_family, size=9.5, bold=True, color="991B1B")
        c_warn.fill = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")
        c_warn.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[curr_row].height = 24
        curr_row += 1

    # Column Headers
    header_row = curr_row
    headers = [
        "STT", "Mã NV", "Tên NV", "Chức vụ", "Tổng ca", "Tổng giờ",
        "Lương chuẩn", "Tiền OT", "Phụ cấp ngày lễ", "Thưởng", "Khấu trừ/Phạt", "Ứng lương", "Thực lĩnh"
    ]
    ws.row_dimensions[header_row].height = 28
    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=header_row, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border

    # Data rows
    first_data_row = header_row + 1
    row_idx = first_data_row
    for i, staff in enumerate(active_staff):
        s_uname = staff.get("username", "")
        s_dname = staff.get("display_name") or staff.get("full_name") or s_uname
        s_role = "Quản Lý" if "MAN" in staff.get("role", "") else (staff.get("position") or "Nhân Viên")

        has_hanging = (s_uname in hanging_unames) or (get_canonical_name(s_dname) in hanging_names)
        display_staff_name = f"{s_dname} ⚠️(Treo)" if has_hanging else s_dname

        # Compute breakdown with alias fallback
        conn = get_db_connection(db_path)
        aliases = [r[0] for r in conn.execute("SELECT alias FROM staff_aliases WHERE username = ?", (s_uname,)).fetchall()]
        conn.close()

        names_to_try = [s_dname, s_uname] + aliases
        breakdown = None
        for n in names_to_try:
            b = calculate_staff_payslip_breakdown(
                n, clean_month, data_json, approvals, evals, attendance_logs, ledgers,
                so_cai_luong=so_cai_luong
            )
            if breakdown is None or b.get("total_shifts", 0) > breakdown.get("total_shifts", 0):
                breakdown = b
            if breakdown and breakdown.get("total_shifts", 0) > 0:
                break

        tot_shifts = breakdown.get("total_shifts", 0)
        tot_hours = breakdown.get("total_hours", 0.0)
        base_w = breakdown.get("base_wage", 17000)
        shift_records = breakdown.get("shift_records", [])

        # Decompose pay components
        std_mins_total = sum(s.get("standard_minutes", 0) for s in shift_records)
        ot_mins_total = sum(s.get("ot_minutes", 0) for s in shift_records)
        hol_mins_total = sum(s.get("effective_minutes", 0) for s in shift_records if s.get("is_holiday", False))

        std_pay = int(round(std_mins_total * (base_w / 60.0)))
        ot_pay = int(round(ot_mins_total * (base_w / 60.0)))
        holiday_pay = int(round(hol_mins_total * (base_w / 60.0)))

        # Balance check against standard_pay to prevent rounding drifts
        calc_std_pay = breakdown.get("standard_pay", 0)
        if (std_pay + ot_pay + holiday_pay) != calc_std_pay:
            std_pay = max(0, calc_std_pay - ot_pay - holiday_pay)

        bonus = int(round(breakdown.get("eval_bonus", 0)))
        deductions = int(round(breakdown.get("eval_deductions", 0) + breakdown.get("late_penalty_total", 0)))
        advance = int(round(breakdown.get("advance_amount", 0)))

        # Row zebra fill
        current_fill = zebra_fill if (i % 2 == 1) else white_fill

        # Write cells
        c_stt = ws.cell(row=row_idx, column=1, value=i + 1)
        c_code = ws.cell(row=row_idx, column=2, value=s_uname)
        c_name = ws.cell(row=row_idx, column=3, value=display_staff_name)
        c_role = ws.cell(row=row_idx, column=4, value=s_role)
        c_shifts = ws.cell(row=row_idx, column=5, value=tot_shifts)
        c_hours = ws.cell(row=row_idx, column=6, value=tot_hours)
        c_std = ws.cell(row=row_idx, column=7, value=std_pay)
        c_ot = ws.cell(row=row_idx, column=8, value=ot_pay)
        c_hol = ws.cell(row=row_idx, column=9, value=holiday_pay)
        c_bonus = ws.cell(row=row_idx, column=10, value=bonus)
        c_deduct = ws.cell(row=row_idx, column=11, value=deductions)
        c_advance = ws.cell(row=row_idx, column=12, value=advance)

        # Excel formula for Net Pay (Thực lĩnh)
        c_net = ws.cell(row=row_idx, column=13, value=f"=G{row_idx}+H{row_idx}+I{row_idx}+J{row_idx}-K{row_idx}-L{row_idx}")

        # Formats and alignments
        c_stt.alignment = Alignment(horizontal="center", vertical="center")
        c_stt.number_format = int_fmt
        c_code.alignment = Alignment(horizontal="center", vertical="center")
        c_name.alignment = Alignment(horizontal="left", vertical="center")
        c_role.alignment = Alignment(horizontal="left", vertical="center")

        c_shifts.alignment = Alignment(horizontal="center", vertical="center")
        c_shifts.number_format = int_fmt

        c_hours.alignment = Alignment(horizontal="right", vertical="center")
        c_hours.number_format = hours_fmt

        for c in [c_std, c_ot, c_hol, c_bonus, c_deduct, c_advance, c_net]:
            c.alignment = Alignment(horizontal="right", vertical="center")
            c.number_format = currency_fmt

        c_net.font = Font(name=font_family, size=10, bold=True, color="0F172A")

        for col_i in range(1, 14):
            c_target = ws.cell(row=row_idx, column=col_i)
            c_target.border = thin_border
            c_target.fill = current_fill
            if col_i != 13:
                c_target.font = Font(name=font_family, size=10)

        ws.row_dimensions[row_idx].height = 22
        row_idx += 1

    # Total Row (TỔNG CỘNG)
    last_data_row = row_idx - 1
    total_row = row_idx
    ws.merge_cells(start_row=total_row, start_column=1, end_row=total_row, end_column=4)
    c_tot_label = ws.cell(row=total_row, column=1, value="TỔNG CỘNG")
    c_tot_label.alignment = Alignment(horizontal="center", vertical="center")
    c_tot_label.font = Font(name=font_family, size=10.5, bold=True, color="18222F")

    # Sum formulas
    c_tot_shifts = ws.cell(row=total_row, column=5, value=f"=SUM(E{first_data_row}:E{last_data_row})")
    c_tot_shifts.number_format = int_fmt
    c_tot_shifts.alignment = Alignment(horizontal="center", vertical="center")

    c_tot_hours = ws.cell(row=total_row, column=6, value=f"=SUM(F{first_data_row}:F{last_data_row})")
    c_tot_hours.number_format = hours_fmt
    c_tot_hours.alignment = Alignment(horizontal="right", vertical="center")

    col_letters = ["G", "H", "I", "J", "K", "L", "M"]
    for idx, col_letter in enumerate(col_letters, 7):
        c_sum = ws.cell(row=total_row, column=idx, value=f"=SUM({col_letter}{first_data_row}:{col_letter}{last_data_row})")
        c_sum.number_format = currency_fmt
        c_sum.alignment = Alignment(horizontal="right", vertical="center")

    for col_i in range(1, 14):
        c_target = ws.cell(row=total_row, column=col_i)
        c_target.border = total_border
        c_target.fill = total_fill
        c_target.font = Font(name=font_family, size=10.5, bold=True, color="18222F")

    ws.row_dimensions[total_row].height = 26

    # Auto-fit column widths (skipping metadata & warning rows)
    for col in ws.columns:
        col_letter = get_column_letter(col[0].column)
        max_len = 0
        for cell in col:
            if cell.row < first_data_row:
                continue
            v = str(cell.value or "")
            if v.startswith("="):
                v = "123,456,789 đ"
            max_len = max(max_len, len(v))
        ws.column_dimensions[col_letter].width = max(max_len + 5, 12)

    # Specific minimum width adjustments
    ws.column_dimensions["A"].width = 7    # STT
    ws.column_dimensions["B"].width = 16   # Mã NV
    ws.column_dimensions["C"].width = 24   # Tên NV
    ws.column_dimensions["D"].width = 14   # Chức vụ
    ws.column_dimensions["F"].width = 13   # Tổng giờ
    ws.column_dimensions["M"].width = 18   # Thực lĩnh

    # Freeze panes below header
    ws.freeze_panes = f"A{first_data_row}"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ==============================================================================
# 2. GENERATE STAFF TEMPLATE
# ==============================================================================

def generate_staff_template() -> bytes:
    """
    Generates a pre-formatted Excel template for importing staff accounts.
    Includes instructions, field validation guidelines, and sample records.
    """
    if not HAS_OPENPYXL:
        raise RuntimeError("Thư viện 'openpyxl' chưa được cài đặt trên hệ thống. Vui lòng cài đặt qua 'pip install openpyxl' để kích hoạt tính năng tải file mẫu.")

    wb = Workbook()
    ws = wb.active
    ws.title = "DanhSachNhanSu"
    ws.views.sheetView[0].showGridLines = True

    font_family = "Segoe UI"
    header_navy = "18222F"
    header_fill = PatternFill(start_color=header_navy, end_color=header_navy, fill_type="solid")
    header_font = Font(name=font_family, size=10, bold=True, color="FFFFFF")

    thin_border = Border(
        left=Side(style="thin", color="CBD5E1"),
        right=Side(style="thin", color="CBD5E1"),
        top=Side(style="thin", color="CBD5E1"),
        bottom=Side(style="thin", color="CBD5E1")
    )

    # Row 1: Title
    ws.merge_cells("A1:I1")
    c_title = ws["A1"]
    store_cfg = get_store_config()
    store_name_upper = str(store_cfg.get("store_name") or "FnBOps Store Lounge").strip().upper()
    c_title.value = f"{store_name_upper} — FILE MẪU NHẬP DANH SÁCH NHÂN SỰ"
    c_title.font = Font(name=font_family, size=13, bold=True, color="FFFFFF")
    c_title.fill = header_fill
    c_title.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 32

    # Row 2: Instructions
    ws.merge_cells("A2:I2")
    c_inst = ws["A2"]
    c_inst.value = (
        "HƯỚNG DẪN: Cột 'Mã NV' (viết thường không dấu) và 'Họ và tên' là bắt buộc. "
        "Mã PIN gồm 4-6 chữ số. Chức vụ: STAFF / MANAGER / ADMIN. "
        "Trạng thái: 1 = Đang làm, 0 = Nghỉ việc."
    )
    c_inst.font = Font(name=font_family, size=9.5, italic=True, color="92400E")
    c_inst.fill = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")
    c_inst.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[2].height = 22

    # Row 3: Headers
    headers = [
        "Mã NV", "Họ và tên", "Chức vụ", "Mã PIN",
        "Email", "Số điện thoại", "Lương/giờ", "Trạng thái", "Vị trí"
    ]
    ws.row_dimensions[3].height = 26
    for idx, h in enumerate(headers, 1):
        cell = ws.cell(row=3, column=idx, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    # Sample rows (Rows 4, 5, 6)
    samples = [
        ("nhanvien01", "Nhân Viên 01", "MANAGER", "1111", "nhanvien01@wfm.local", "0901234567", 17000, 1, "Quản Lý"),
        ("nhanvien02", "Nhân Viên 02", "STAFF", "2468", "nhanvien02@wfm.local", "0907654321", 17000, 1, "Pha Chế"),
        ("nhanvien03", "Nhân Viên 03", "STAFF", "6754", "nhanvien03@wfm.local", "0909876543", 17000, 1, "Phục Vụ")
    ]

    for r_idx, s in enumerate(samples, 4):
        ws.row_dimensions[r_idx].height = 22
        for c_idx, val in enumerate(s, 1):
            c = ws.cell(row=r_idx, column=c_idx, value=val)
            c.font = Font(name=font_family, size=10)
            c.border = thin_border

            # Number formats
            if c_idx == 4:
                c.number_format = "@"  # Text format for PIN so leading zeros are preserved
                c.alignment = Alignment(horizontal="center", vertical="center")
            elif c_idx == 7:
                c.number_format = '#,##0 "đ"'
                c.alignment = Alignment(horizontal="right", vertical="center")
            elif c_idx == 8:
                c.number_format = "0"
                c.alignment = Alignment(horizontal="center", vertical="center")
            elif c_idx in (1, 3):
                c.alignment = Alignment(horizontal="center", vertical="center")
            else:
                c.alignment = Alignment(horizontal="left", vertical="center")

    # Column widths
    ws.column_dimensions["A"].width = 16  # Mã NV
    ws.column_dimensions["B"].width = 24  # Họ và tên
    ws.column_dimensions["C"].width = 14  # Chức vụ
    ws.column_dimensions["D"].width = 12  # Mã PIN
    ws.column_dimensions["E"].width = 24  # Email
    ws.column_dimensions["F"].width = 16  # SĐT
    ws.column_dimensions["G"].width = 15  # Lương/giờ
    ws.column_dimensions["H"].width = 13  # Trạng thái
    ws.column_dimensions["I"].width = 16  # Vị trí

    ws.freeze_panes = "A4"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ==============================================================================
# 3. IMPORT STAFF FROM EXCEL
# ==============================================================================

def import_staff_from_excel(
    file_bytes: bytes,
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Parses an uploaded Excel file and upserts staff records into SQLite `staff_accounts`.
    Returns: { "success": bool, "count": int, "errors": list }
    """
    if not file_bytes:
        return {"success": False, "count": 0, "errors": ["File tải lên trống rỗng."]}

    if not HAS_OPENPYXL:
        return {"success": False, "count": 0, "errors": ["Thư viện 'openpyxl' chưa được cài đặt trên hệ thống. Vui lòng cài đặt 'openpyxl' để sử dụng tính năng này."]}

    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    except Exception as e:
        logger.error(f"Cannot parse Excel workbook: {e}")
        return {"success": False, "count": 0, "errors": [f"File không đúng định dạng Excel: {str(e)}"]}

    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return {"success": False, "count": 0, "errors": ["Bảng tính không có dữ liệu."]}

    # Detect header row (looking for keywords: 'mã', 'username', 'tên', 'họ', 'pin')
    header_row_idx = -1
    col_map = {}

    for idx, row in enumerate(rows[:10]):
        non_empty_cells = [str(c).strip().lower() for c in row if c is not None and str(c).strip()]
        if len(non_empty_cells) < 3:
            continue
        row_str = " ".join(non_empty_cells)
        if any(w in row_str for w in ("hướng dẫn", "lưu ý", "quy định", "bảng lương chi tiết")):
            continue
        if any(k in row_str for k in ("mã nv", "username", "họ và tên", "tên nv", "mã pin", "lương/giờ")):
            header_row_idx = idx
            for c_idx, cell_val in enumerate(row):
                if cell_val is None:
                    continue
                c_clean = str(cell_val).strip().lower()
                if any(k in c_clean for k in ("mã pin", "pin")):
                    col_map["pin"] = c_idx
                elif any(k in c_clean for k in ("mã nv", "username", "tài khoản", "ma nv", "manv")) or c_clean in ("mã", "code"):
                    col_map["username"] = c_idx
                elif any(k in c_clean for k in ("họ và tên", "tên nv", "họ tên", "display_name", "tên")):
                    col_map["name"] = c_idx
                elif any(k in c_clean for k in ("chức vụ", "role", "vai trò")):
                    col_map["role"] = c_idx
                elif any(k in c_clean for k in ("email", "mail")):
                    col_map["email"] = c_idx
                elif any(k in c_clean for k in ("số điện thoại", "sđt", "phone", "điện thoại")):
                    col_map["phone"] = c_idx
                elif any(k in c_clean for k in ("lương/giờ", "lương", "hourly_rate", "rate")):
                    col_map["rate"] = c_idx
                elif any(k in c_clean for k in ("trạng thái", "active", "status")):
                    col_map["is_active"] = c_idx
                elif any(k in c_clean for k in ("vị trí", "position")):
                    col_map["position"] = c_idx
            break

    if header_row_idx == -1:
        # Fallback: assume row 0 is header
        header_row_idx = 0
        col_map = {"username": 0, "name": 1, "role": 2, "pin": 3, "email": 4, "phone": 5, "rate": 6, "is_active": 7, "position": 8}

    imported_count = 0
    errors = []

    for r_num, row in enumerate(rows[header_row_idx + 1:], start=header_row_idx + 2):
        if not row or all(c is None or str(c).strip() == "" for c in row):
            continue

        raw_uname = row[col_map["username"]] if "username" in col_map and col_map["username"] < len(row) else None
        raw_name = row[col_map["name"]] if "name" in col_map and col_map["name"] < len(row) else None

        if not raw_uname and not raw_name:
            continue

        # Username extraction
        if raw_uname:
            username = str(raw_uname).strip().lower()
        else:
            username = normalize_str(str(raw_name))

        display_name = str(raw_name).strip() if raw_name else username

        # Role
        role_raw = row[col_map["role"]] if "role" in col_map and col_map["role"] < len(row) else "STAFF"
        role_str = str(role_raw or "STAFF").strip().upper()
        if "MAN" in role_str:
            role = "MANAGER"
        elif "ADM" in role_str:
            role = "ADMIN"
        else:
            role = "STAFF"

        # PIN & Hash
        pin_raw = row[col_map["pin"]] if "pin" in col_map and col_map["pin"] < len(row) else "1234"
        pin_clean = str(pin_raw or "1234").strip()
        pin_hash = hash_pin(pin_clean) if needs_rehash(pin_clean) else pin_clean

        # Contact
        email = str(row[col_map["email"]]).strip() if "email" in col_map and col_map["email"] < len(row) and row[col_map["email"]] else ""
        phone = str(row[col_map["phone"]]).strip() if "phone" in col_map and col_map["phone"] < len(row) and row[col_map["phone"]] else ""

        # Rate
        rate_val = 17000
        if "rate" in col_map and col_map["rate"] < len(row) and row[col_map["rate"]] is not None:
            try:
                rate_val = int(float(str(row[col_map["rate"]]).replace(",", "").replace(".", "").replace("đ", "").strip()))
            except Exception:
                rate_val = 17000

        # Active
        is_active = True
        if "is_active" in col_map and col_map["is_active"] < len(row) and row[col_map["is_active"]] is not None:
            act_raw = str(row[col_map["is_active"]]).strip().lower()
            if act_raw in ("0", "false", "nghỉ", "inactive", "đã nghỉ"):
                is_active = False

        # Position
        pos = "SERVICE"
        if "position" in col_map and col_map["position"] < len(row) and row[col_map["position"]]:
            pos = str(row[col_map["position"]]).strip().upper()

        try:
            upsert_staff_account(
                username=username,
                full_name=display_name,
                display_name=display_name,
                pin_hash=pin_hash,
                role=role,
                position=pos,
                status="ACTIVE" if is_active else "INACTIVE",
                email=email,
                phone=phone,
                hourly_rate=rate_val,
                is_active=is_active,
                tenant_id=tenant_id,
                db_path=db_path
            )

            # Insert aliases
            conn = get_db_connection(db_path)
            with conn:
                conn.execute(
                    "INSERT OR IGNORE INTO staff_aliases (username, alias, tenant_id) VALUES (?, ?, ?)",
                    (username, display_name, tenant_id)
                )
            conn.close()

            # Mirror to staff_auth.json for immediate webapp authentication sync only if importing to default DB
            if db_path is None:
                try:
                    try:
                        from services.auth import load_staff_auth, save_staff_auth
                    except ImportError:
                        from backend.services.auth import load_staff_auth, save_staff_auth
                    auth_data = load_staff_auth()
                    accs = auth_data.setdefault("staff_accounts", {})
                    if username not in accs or not accs[username].get("pin"):
                        accs[username] = {
                            "full_name": display_name,
                            "sheet_names": [display_name],
                            "pin": pin_clean,
                            "role": role,
                            "gender": "NAM",
                            "position": pos,
                            "status": "ACTIVE" if is_active else "INACTIVE",
                            "aliases": [username, display_name],
                            "hourly_rate": rate_val
                        }
                    else:
                        accs[username]["full_name"] = display_name
                        accs[username]["role"] = role
                        accs[username]["position"] = pos
                        accs[username]["status"] = "ACTIVE" if is_active else "INACTIVE"
                        accs[username]["hourly_rate"] = rate_val
                    save_staff_auth(auth_data)
                except Exception as se:
                    logger.warning(f"Could not mirror staff account {username} to staff_auth.json: {se}")

            imported_count += 1
        except Exception as e:
            logger.error(f"Error importing row {r_num} ({username}): {e}")
            errors.append(f"Dòng {r_num} ({username}): {str(e)}")

    return {
        "success": imported_count > 0 or len(errors) == 0,
        "count": imported_count,
        "errors": errors
    }

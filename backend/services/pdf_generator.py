# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
WFM - Professional PDF Generator Service
Supports Vietnamese diacritics via bundled open-source Inter TTF fonts (SIL OFL-1.1).
Renders Thermal Invoice Payslips (A5/A4) and Shift Evaluation Notices.
Zero external cloud dependency, runs 100% on-premise.
"""

import os
import io
import re
import unicodedata
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, List

try:
    from reportlab.lib.pagesizes import A5, A4
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, KeepTogether
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.fonts import addMapping
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False
    A5 = (419.53, 595.28)
    A4 = (595.28, 841.89)
    colors = None
    SimpleDocTemplate = Paragraph = Spacer = Table = TableStyle = HRFlowable = KeepTogether = None
    getSampleStyleSheet = ParagraphStyle = None
    pdfmetrics = TTFont = addMapping = None


# ---------------------------------------------------------------------------
# Font Registry & Vietnamese Typography Support
# ---------------------------------------------------------------------------

FONT_REGULAR_NAME = "VietFont"
FONT_BOLD_NAME = "VietFont-Bold"
FONT_ITALIC_NAME = "VietFont-Italic"
_FONTS_REGISTERED = False


def _find_font_file(candidates: List[str]) -> Optional[str]:
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


def register_vietnamese_fonts() -> Tuple[str, str, str]:
    """
    Registers TrueType fonts that support complete Vietnamese Unicode diacritics.
    Prioritizes project bundled Inter TTF (SIL OFL-1.1), OS system fonts,
    Linux LiberationSans/DejaVuSans, or standard ReportLab Helvetica.
    """
    global _FONTS_REGISTERED, FONT_REGULAR_NAME, FONT_BOLD_NAME, FONT_ITALIC_NAME
    if not HAS_REPORTLAB or pdfmetrics is None:
        return "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"
    if _FONTS_REGISTERED and FONT_REGULAR_NAME != "Helvetica":
        return FONT_REGULAR_NAME, FONT_BOLD_NAME, FONT_ITALIC_NAME

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bundled_font_dir = os.path.join(base_dir, "assets", "fonts")

    reg_candidates = [
        os.path.join(bundled_font_dir, "Inter-Regular.ttf"),
        "/app/backend/assets/fonts/Inter-Regular.ttf",
        "/app/assets/fonts/Inter-Regular.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
    ]

    bold_candidates = [
        os.path.join(bundled_font_dir, "Inter-Bold.ttf"),
        "/app/backend/assets/fonts/Inter-Bold.ttf",
        "/app/assets/fonts/Inter-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ]

    italic_candidates = [
        os.path.join(bundled_font_dir, "Inter-Italic.ttf"),
        "/app/backend/assets/fonts/Inter-Italic.ttf",
        "/app/assets/fonts/Inter-Italic.ttf",
        "/System/Library/Fonts/Supplemental/Arial Italic.ttf",
        "/Library/Fonts/Arial Italic.ttf",
        "C:/Windows/Fonts/segoeuii.ttf",
        "C:/Windows/Fonts/ariali.ttf",
        "C:\\Windows\\Fonts\\ariali.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Oblique.ttf",
    ]

    reg_path = _find_font_file(reg_candidates)
    bold_path = _find_font_file(bold_candidates)
    italic_path = _find_font_file(italic_candidates)

    registered_names = set(pdfmetrics.getRegisteredFontNames())

    if reg_path:
        try:
            if FONT_REGULAR_NAME not in registered_names:
                pdfmetrics.registerFont(TTFont(FONT_REGULAR_NAME, reg_path))
            
            if bold_path and FONT_BOLD_NAME not in registered_names:
                pdfmetrics.registerFont(TTFont(FONT_BOLD_NAME, bold_path))
            else:
                FONT_BOLD_NAME = FONT_REGULAR_NAME
            
            if italic_path and FONT_ITALIC_NAME not in registered_names:
                pdfmetrics.registerFont(TTFont(FONT_ITALIC_NAME, italic_path))
            else:
                FONT_ITALIC_NAME = FONT_REGULAR_NAME

            addMapping(FONT_REGULAR_NAME, 0, 0, FONT_REGULAR_NAME)
            addMapping(FONT_REGULAR_NAME, 1, 0, FONT_BOLD_NAME)
            addMapping(FONT_REGULAR_NAME, 0, 1, FONT_ITALIC_NAME)
            addMapping(FONT_REGULAR_NAME, 1, 1, FONT_BOLD_NAME)

            # Also register Arial alias if not already registered
            if "Arial" not in registered_names:
                pdfmetrics.registerFont(TTFont("Arial", reg_path))
            if bold_path and "Arial-Bold" not in registered_names:
                pdfmetrics.registerFont(TTFont("Arial-Bold", bold_path))

            _FONTS_REGISTERED = True
            return FONT_REGULAR_NAME, FONT_BOLD_NAME, FONT_ITALIC_NAME
        except Exception as e:
            print(f"Warning registering custom TTF font: {e}")

    # Fallback to standard Helvetica if no TTF font is found
    FONT_REGULAR_NAME = "Helvetica"
    FONT_BOLD_NAME = "Helvetica-Bold"
    FONT_ITALIC_NAME = "Helvetica-Oblique"
    _FONTS_REGISTERED = True
    return FONT_REGULAR_NAME, FONT_BOLD_NAME, FONT_ITALIC_NAME


# ---------------------------------------------------------------------------
# Number to Vietnamese Words Converter (Doc so thanh chu tieng Viet)
# ---------------------------------------------------------------------------

def number_to_vietnamese_words(number: int) -> str:
    """Converts integer VND amounts into formal Vietnamese words for receipt clarity."""
    n = int(round(number))
    if n == 0:
        return "Không đồng"
    if n < 0:
        return f"Âm {number_to_vietnamese_words(abs(n)).lower()}"

    units = ["", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]
    levels = ["", "nghìn", "triệu", "tỷ", "nghìn tỷ", "triệu tỷ"]

    def read_block(b: int, show_zero_hundred: bool = False) -> str:
        h = b // 100
        t = (b % 100) // 10
        u = b % 10
        res = []
        if h > 0 or show_zero_hundred:
            res.append(f"{units[h]} trăm")
        if t == 0:
            if u > 0 and (h > 0 or show_zero_hundred):
                res.append("lẻ")
        elif t == 1:
            res.append("mười")
        else:
            res.append(f"{units[t]} mươi")

        if u == 1:
            if t > 1:
                res.append("mốt")
            else:
                res.append("một")
        elif u == 5:
            if t > 0:
                res.append("lăm")
            else:
                res.append("năm")
        elif u > 0:
            res.append(units[u])
        return " ".join(res)

    blocks = []
    temp = n
    while temp > 0:
        blocks.append(temp % 1000)
        temp //= 1000

    parts = []
    for i in range(len(blocks) - 1, -1, -1):
        b = blocks[i]
        if b > 0:
            show_zero = (i < len(blocks) - 1)
            b_str = read_block(b, show_zero)
            lvl = levels[i]
            if lvl:
                parts.append(f"{b_str} {lvl}")
            else:
                parts.append(b_str)

    text = " ".join(parts).strip().capitalize() + " đồng chẵn"
    return text


def _slugify(text: str) -> str:
    """Helper to generate a clean ASCII filename/id slug."""
    if not text:
        return "unknown"
    s = unicodedata.normalize("NFD", str(text))
    s = "".join([c for c in s if unicodedata.category(c) != "Mn"])
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_")
    return s.lower() or "staff"


# ---------------------------------------------------------------------------
# Thermal Invoice / Payslip PDF Generator
# ---------------------------------------------------------------------------

def render_payslip_pdf(
    staff_name: str,
    month: str,
    breakdown: Optional[Dict[str, Any]] = None,
    pagesize=A5
) -> bytes:
    """
    Renders an elegant, professional Thermal Invoice Payslip in PDF format.
    Default size: A5 (compact invoice receipt style), also compatible with A4.
    
    Includes:
    - Header: FnBOps Cafe & Lounge, Title with Month, Invoice ID & Timestamp.
    - Employee card: Full Name, Role, Date of issue, Month of service.
    - Breakdown table: Standard hours, Shifts, Hourly rate, Standard pay, OT hours & pay,
      Holiday bonus, Performance bonus, Late penalties & infractions, Salary advance.
    - Net Pay Highlight Box: Large, high-contrast, with verbal amount in Vietnamese.
    - Infractions / Notes section (if applicable).
    - Footer: 24h inquiry regulation and dual signature boxes.
    """
    if not HAS_REPORTLAB:
        raise RuntimeError("Thư viện reportlab chưa được cài đặt trên máy chủ.")
    font_reg, font_bold, font_italic = register_vietnamese_fonts()
    breakdown = breakdown or {}

    # Extract metrics safely
    full_name = breakdown.get("staff_name") or staff_name or "Nhân Viên"
    staff_role = breakdown.get("role") or breakdown.get("position") or "Nhân viên Vận hành F&B"
    staff_id = breakdown.get("staff_id") or f"EMP-{_slugify(full_name)[:6].upper()}"
    base_wage = int(breakdown.get("base_wage") or 17000)
    total_shifts = int(breakdown.get("total_shifts") or 0)
    total_hours = float(breakdown.get("total_hours") or 0.0)
    standard_pay = int(breakdown.get("standard_pay") or 0)
    eval_bonus = int(breakdown.get("eval_bonus") or 0)
    advance_amount = int(breakdown.get("advance_amount") or 0)
    eval_deductions = int(breakdown.get("eval_deductions") or 0)
    late_penalty_total = int(breakdown.get("late_penalty_total") or 0)
    violations = breakdown.get("violations") or []
    net_pay = int(breakdown.get("net_pay") or max(0, standard_pay + eval_bonus - (advance_amount + late_penalty_total + eval_deductions)))

    # Compute OT and standard hour decomposition
    shift_records = breakdown.get("shift_records") or []
    ot_minutes_total = sum(float(r.get("ot_minutes") or 0.0) for r in shift_records)
    ot_hours = round(ot_minutes_total / 60.0, 1)
    std_hours = max(0.0, round(total_hours - ot_hours, 1))
    
    # OT pay and Holiday pay estimate from records
    ot_pay = int(round(ot_hours * base_wage))
    holiday_shifts = sum(1 for r in shift_records if r.get("is_holiday"))
    holiday_pay = sum(
        int(round(float(r.get("effective_minutes") or 0) * (base_wage / 60.0)))
        for r in shift_records if r.get("is_holiday")
    )
    # Reconcile so std_pay + ot_pay + holiday_pay == standard_pay exactly
    std_pay = max(0, standard_pay - ot_pay - holiday_pay)

    clean_slug = _slugify(full_name)
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    cur_year = datetime.now().year
    invoice_id = f"PL-{cur_year}{str(month):0>2}-{clean_slug.upper()}"

    # Palette
    color_navy = colors.HexColor("#18222F")
    color_coral = colors.HexColor("#FF6D3E")
    color_slate_bg = colors.HexColor("#F8FAFC")
    color_border = colors.HexColor("#E2E8F0")
    color_muted = colors.HexColor("#64748B")
    color_dark = colors.HexColor("#0F172A")
    color_positive = colors.HexColor("#059669")
    color_negative = colors.HexColor("#DC2626")

    buf = io.BytesIO()
    # A5 margins: 18pt (~6.3mm) to fit comfortably on 1 page
    doc = SimpleDocTemplate(
        buf,
        pagesize=pagesize,
        leftMargin=18,
        rightMargin=18,
        topMargin=15,
        bottomMargin=15
    )

    # Styles
    styles = getSampleStyleSheet()
    style_brand = ParagraphStyle(
        "BrandHeader",
        fontName=font_bold,
        fontSize=13,
        leading=16,
        alignment=1,
        textColor=color_navy
    )
    style_title = ParagraphStyle(
        "InvoiceTitle",
        fontName=font_bold,
        fontSize=10.5,
        leading=13.5,
        alignment=1,
        textColor=color_coral
    )
    style_meta = ParagraphStyle(
        "InvoiceMeta",
        fontName=font_reg,
        fontSize=7.2,
        leading=9.5,
        alignment=1,
        textColor=color_muted
    )
    style_cell = ParagraphStyle(
        "GridCell",
        fontName=font_reg,
        fontSize=7.8,
        leading=10.5,
        textColor=color_dark
    )
    style_cell_b = ParagraphStyle(
        "GridCellBold",
        fontName=font_bold,
        fontSize=7.8,
        leading=10.5,
        textColor=color_dark
    )
    style_cell_r = ParagraphStyle(
        "GridCellRight",
        fontName=font_reg,
        fontSize=7.8,
        leading=10.5,
        alignment=2,
        textColor=color_dark
    )
    style_cell_rb = ParagraphStyle(
        "GridCellRightBold",
        fontName=font_bold,
        fontSize=7.8,
        leading=10.5,
        alignment=2,
        textColor=color_dark
    )
    style_header_col = ParagraphStyle(
        "GridHeaderCol",
        fontName=font_bold,
        fontSize=8.0,
        leading=11.0,
        textColor=colors.white
    )
    style_header_col_r = ParagraphStyle(
        "GridHeaderColRight",
        fontName=font_bold,
        fontSize=8.0,
        leading=11.0,
        alignment=2,
        textColor=colors.white
    )

    story = []

    # 1. Header Section
    store_title = (breakdown.get("store_name") or "FNBOPS STORE").upper()
    story.append(Paragraph(store_title, style_brand))
    story.append(Spacer(1, 2))
    story.append(Paragraph(f"PHIẾU LƯƠNG NHÂN SỰ KỲ LƯƠNG THÁNG {month}", style_title))
    story.append(Spacer(1, 2))
    story.append(Paragraph(f"Mã phiếu: <b>{invoice_id}</b> • Xuất phiếu: {now_str}", style_meta))
    story.append(Spacer(1, 5))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#CBD5E1"), spaceAfter=5))

    # 2. Staff Information Card (Table)
    info_table_data = [
        [
            Paragraph(f"<b>Họ và tên:</b> {full_name}", style_cell),
            Paragraph(f"<b>Mã nhân sự:</b> {staff_id}", style_cell)
        ],
        [
            Paragraph(f"<b>Chức vụ:</b> {staff_role}", style_cell),
            Paragraph(f"<b>Kỳ đối soát:</b> Tháng {month}/{cur_year}", style_cell)
        ]
    ]
    t_info = Table(info_table_data, colWidths=[205, 178])
    t_info.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), color_slate_bg),
        ("BOX", (0, 0), (-1, -1), 0.5, color_border),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, color_border),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t_info)
    story.append(Spacer(1, 6))

    # 3. Detailed Breakdown Table
    breakdown_rows = [
        [
            Paragraph("<b>Hạng mục tính lương &amp; Chỉ số công</b>", style_header_col),
            Paragraph("<b>Định mức / Chỉ số</b>", style_header_col),
            Paragraph("<b>Thành tiền (VNĐ)</b>", style_header_col_r)
        ],
        [
            Paragraph("Giờ làm việc tiêu chuẩn", style_cell),
            Paragraph(f"{std_hours:.1f} giờ", style_cell),
            Paragraph(f"{std_pay:,} đ", style_cell_r)
        ],
        [
            Paragraph("Tổng số ca hoàn thành", style_cell),
            Paragraph(f"{total_shifts} ca", style_cell),
            Paragraph("(Đã tính vào giờ)", style_cell_r)
        ],
        [
            Paragraph("Lương cơ sở theo giờ", style_cell),
            Paragraph(f"{base_wage:,} đ/giờ", style_cell),
            Paragraph("-", style_cell_r)
        ],
        [
            Paragraph("Tăng ca / Ngoài giờ (OT)", style_cell),
            Paragraph(f"{ot_hours:.1f} giờ", style_cell),
            Paragraph(f"{ot_pay:,} đ", style_cell_r)
        ],
        [
            Paragraph("Phụ cấp ngày lễ (Hệ số x2.0)", style_cell),
            Paragraph(f"{holiday_shifts} ca lễ", style_cell),
            Paragraph(f"{holiday_pay:,} đ", style_cell_r)
        ],
        [
            Paragraph("Thưởng nóng &amp; Đánh giá ca (+)", style_cell),
            Paragraph("Thành tích ca trực", style_cell),
            Paragraph(f"<font color='{color_positive.hexval()}'>+{eval_bonus:,} đ</font>", style_cell_rb)
        ],
        [
            Paragraph("Phạt vi phạm &amp; Đi trễ (-)", style_cell),
            Paragraph(f"{len(violations)} khoản vi phạm", style_cell),
            Paragraph(f"<font color='{color_negative.hexval()}'>-{late_penalty_total + eval_deductions:,} đ</font>", style_cell_rb)
        ],
        [
            Paragraph("Tạm ứng lương (Sổ phụ) (-)", style_cell),
            Paragraph("Ứng lương trong kỳ", style_cell),
            Paragraph(f"<font color='{color_negative.hexval()}'>-{advance_amount:,} đ</font>", style_cell_rb)
        ]
    ]

    t_breakdown = Table(breakdown_rows, colWidths=[185, 98, 100])
    t_breakdown.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), color_navy),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
        ("TOPPADDING", (0, 0), (-1, 0), 4),
        ("GRID", (0, 0), (-1, -1), 0.5, color_border),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, color_slate_bg]),
        ("TOPPADDING", (0, 1), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t_breakdown)
    story.append(Spacer(1, 6))

    # 4. Net Pay Highlight Box
    net_pay_words = number_to_vietnamese_words(net_pay)
    style_net_label = ParagraphStyle(
        "NetPayLabel",
        fontName=font_bold,
        fontSize=10,
        leading=12,
        alignment=1,
        textColor=color_coral
    )
    style_net_val = ParagraphStyle(
        "NetPayVal",
        fontName=font_bold,
        fontSize=14.5,
        leading=17.5,
        alignment=1,
        textColor=colors.white
    )
    style_net_words = ParagraphStyle(
        "NetPayWords",
        fontName=font_italic,
        fontSize=7.2,
        leading=9.5,
        alignment=1,
        textColor=colors.HexColor("#E2E8F0")
    )

    net_box_data = [
        [Paragraph("THỰC LĨNH (NET PAY)", style_net_label)],
        [Paragraph(f"{net_pay:,} VNĐ", style_net_val)],
        [Paragraph(f"(Bằng chữ: {net_pay_words})", style_net_words)]
    ]
    t_net = Table(net_box_data, colWidths=[383])
    t_net.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), color_navy),
        ("BOX", (0, 0), (-1, -1), 1.2, color_coral),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    story.append(t_net)
    story.append(Spacer(1, 5))

    # 5. Optional Violations / Details Note
    if violations:
        violation_texts = [f"• {v}" for v in violations[:3]]
        viol_str = "<br/>".join(violation_texts)
        style_viol = ParagraphStyle(
            "ViolNote",
            fontName=font_reg,
            fontSize=6.8,
            leading=8.5,
            textColor=colors.HexColor("#B91C1C")
        )
        story.append(Paragraph(f"<b>Chi tiết ghi chú / chế tài:</b><br/>{viol_str}", style_viol))
        story.append(Spacer(1, 4))

    # 6. Footer Note (24h Window) & Signatures
    style_footer_note = ParagraphStyle(
        "FooterNote",
        fontName=font_italic,
        fontSize=6.8,
        leading=8.5,
        alignment=1,
        textColor=color_muted
    )
    story.append(Paragraph(
        "* Mọi thắc mắc về bảng lương vui lòng phản hồi Quản lý trong vòng 24 giờ kể từ khi nhận phiếu.",
        style_footer_note
    ))
    story.append(Spacer(1, 6))

    signature_rows = [
        [
            Paragraph(
                "<b>NGƯỜI LẬP BIỂU / QUẢN LÝ</b><br/><font size='6' color='#64748B'>(Ký &amp; ghi rõ họ tên)</font>",
                style_cell_b
            ),
            Paragraph(
                "<b>NGƯỜI NHẬN / NHÂN VIÊN</b><br/><font size='6' color='#64748B'>(Ký xác nhận đã nhận đủ)</font>",
                style_cell_rb
            )
        ],
        [
            Paragraph("<br/><br/><br/>", style_cell),
            Paragraph("<br/><br/><br/>", style_cell_r)
        ]
    ]
    t_sig = Table(signature_rows, colWidths=[191, 192])
    t_sig.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    story.append(t_sig)

    doc.build(story)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Shift Evaluation Notice PDF Generator
# ---------------------------------------------------------------------------

def render_eval_notice_pdf(eval_data: Dict[str, Any], pagesize=A5) -> bytes:
    """
    Renders a clear, official Shift Evaluation Notice / Reward or Infraction Notice PDF.
    
    Includes:
    - Header: FnBOps Cafe & Lounge, Title, Protocol Code & Generation Timestamp.
    - Employee & Shift Card: Staff Name, Shift Date, Shift Name, Evaluator.
    - Decision Banner: Reward (+Amount) or Infraction Discipline (-Amount).
    - Detailed Rationale & Ground: Observations, customer feedback, operational rules.
    - Signatures: Manager and Staff acknowledgment.
    """
    if not HAS_REPORTLAB:
        raise RuntimeError("Thư viện reportlab chưa được cài đặt trên máy chủ.")
    font_reg, font_bold, font_italic = register_vietnamese_fonts()
    eval_data = eval_data or {}

    eval_id = str(eval_data.get("id") or eval_data.get("eval_id") or f"EV-{int(datetime.now().timestamp())}")
    staff_name = eval_data.get("staff_name") or eval_data.get("staffName") or "Nhân sự F&B"
    staff_role = eval_data.get("role") or "Nhân viên Phục vụ / Pha chế"
    shift_date = str(eval_data.get("date") or eval_data.get("shift_date") or datetime.now().strftime("%d/%m/%Y"))
    shift_name = str(eval_data.get("shift") or eval_data.get("shift_name") or "Ca làm việc")
    evaluator = str(eval_data.get("evaluator") or eval_data.get("manager_name") or "Quản lý Ca Trực")
    
    raw_type = str(eval_data.get("type") or "BONUS").upper()
    is_bonus = any(k in raw_type for k in ["BONUS", "THUONG", "KHEN", "REWARD"])
    
    amount = int(eval_data.get("amount") or 0)
    reason = str(
        eval_data.get("reason")
        or eval_data.get("note")
        or eval_data.get("description")
        or "Ghi nhận đánh giá vận hành ca trực theo tiêu chuẩn dịch vụ WFM."
    )
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    protocol_code = f"WFM-EVAL-{eval_id}"

    # Theme colors based on Bonus vs Infraction
    color_navy = colors.HexColor("#18222F")
    color_accent = colors.HexColor("#059669") if is_bonus else colors.HexColor("#DC2626")
    color_bg_card = colors.HexColor("#ECFDF5") if is_bonus else colors.HexColor("#FEF2F2")
    color_border = colors.HexColor("#E2E8F0")
    color_slate_bg = colors.HexColor("#F8FAFC")
    color_muted = colors.HexColor("#64748B")
    color_dark = colors.HexColor("#0F172A")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=pagesize,
        leftMargin=18,
        rightMargin=18,
        topMargin=15,
        bottomMargin=15
    )

    styles = getSampleStyleSheet()
    style_brand = ParagraphStyle(
        "EvalBrand",
        fontName=font_bold,
        fontSize=13,
        leading=16,
        alignment=1,
        textColor=color_navy
    )
    style_title = ParagraphStyle(
        "EvalTitle",
        fontName=font_bold,
        fontSize=10,
        leading=13,
        alignment=1,
        textColor=color_accent
    )
    style_meta = ParagraphStyle(
        "EvalMeta",
        fontName=font_reg,
        fontSize=7.2,
        leading=9.5,
        alignment=1,
        textColor=color_muted
    )
    style_cell = ParagraphStyle(
        "EvalCell",
        fontName=font_reg,
        fontSize=7.8,
        leading=10.5,
        textColor=color_dark
    )
    style_cell_b = ParagraphStyle(
        "EvalCellBold",
        fontName=font_bold,
        fontSize=7.8,
        leading=10.5,
        textColor=color_dark
    )
    style_cell_rb = ParagraphStyle(
        "EvalCellRightBold",
        fontName=font_bold,
        fontSize=7.8,
        leading=10.5,
        alignment=2,
        textColor=color_dark
    )

    story = []

    # 1. Header
    eval_store = (eval_data.get("store_name") or "FNBOPS STORE").upper()
    story.append(Paragraph(eval_store, style_brand))
    story.append(Spacer(1, 2))
    notice_title = "BIÊN BẢN ĐÁNH GIÁ CA &amp; QUYẾT ĐỊNH KHEN THƯỞNG" if is_bonus else "BIÊN BẢN ĐÁNH GIÁ CA &amp; QUYẾT ĐỊNH XỬ LÝ VI PHẠM"
    story.append(Paragraph(notice_title, style_title))
    story.append(Spacer(1, 2))
    story.append(Paragraph(f"Số hiệu: <b>{protocol_code}</b> • Lập lúc: {now_str}", style_meta))
    story.append(Spacer(1, 5))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#CBD5E1"), spaceAfter=5))

    # 2. Staff & Shift Information Card
    info_data = [
        [
            Paragraph(f"<b>Nhân sự liên quan:</b> {staff_name}", style_cell),
            Paragraph(f"<b>Chức vụ:</b> {staff_role}", style_cell)
        ],
        [
            Paragraph(f"<b>Ngày ca trực:</b> {shift_date}", style_cell),
            Paragraph(f"<b>Ca làm việc:</b> {shift_name}", style_cell)
        ],
        [
            Paragraph(f"<b>Người đánh giá:</b> {evaluator}", style_cell),
            Paragraph(f"<b>Hình thức:</b> {'Khen thưởng ca' if is_bonus else 'Xử lý vi phạm'}", style_cell)
        ]
    ]
    t_info = Table(info_data, colWidths=[205, 178])
    t_info.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), color_slate_bg),
        ("BOX", (0, 0), (-1, -1), 0.5, color_border),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, color_border),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t_info)
    story.append(Spacer(1, 6))

    # 3. Decision Banner Card
    badge_label = "QUYẾT ĐỊNH KHEN THƯỞNG CA TRỰC" if is_bonus else "QUYẾT ĐỊNH XỬ LÝ VI PHẠM CA TRỰC"
    amount_sign = "+" if is_bonus else "-"
    amount_str = f"{amount_sign}{amount:,} VNĐ" if amount > 0 else "0 VNĐ (Nhắc nhở / Cảnh báo)"
    amount_words = number_to_vietnamese_words(amount) if amount > 0 else "Không áp dụng chế tài tài chính"

    style_dec_badge = ParagraphStyle(
        "DecBadge",
        fontName=font_bold,
        fontSize=10,
        leading=12,
        alignment=1,
        textColor=color_accent
    )
    style_dec_amt = ParagraphStyle(
        "DecAmt",
        fontName=font_bold,
        fontSize=13,
        leading=16,
        alignment=1,
        textColor=color_navy
    )
    style_dec_words = ParagraphStyle(
        "DecWords",
        fontName=font_italic,
        fontSize=7.2,
        leading=9.5,
        alignment=1,
        textColor=colors.HexColor("#475569")
    )

    dec_data = [
        [Paragraph(f"<b>{badge_label}</b>", style_dec_badge)],
        [Paragraph(f"MỨC ĐIỀU CHỈNH: <b>{amount_str}</b>", style_dec_amt)],
        [Paragraph(f"(Bằng chữ: {amount_words})", style_dec_words)]
    ]
    t_dec = Table(dec_data, colWidths=[383])
    t_dec.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), color_bg_card),
        ("BOX", (0, 0), (-1, -1), 1, color_accent),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    story.append(t_dec)
    story.append(Spacer(1, 6))

    # 4. Reason & Rationale Box
    style_reason_header = ParagraphStyle(
        "ReasonHeader",
        fontName=font_bold,
        fontSize=8,
        leading=11,
        textColor=color_navy
    )
    style_reason_text = ParagraphStyle(
        "ReasonText",
        fontName=font_reg,
        fontSize=7.5,
        leading=10.5,
        textColor=color_dark
    )
    reason_rows = [
        [Paragraph("<b>NỘI DUNG ĐÁNH GIÁ CHI TIẾT &amp; CĂN CỨ VẬN HÀNH:</b>", style_reason_header)],
        [Paragraph(reason, style_reason_text)]
    ]
    t_reason = Table(reason_rows, colWidths=[383])
    t_reason.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), color_slate_bg),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(t_reason)
    story.append(Spacer(1, 8))

    # 5. Footer Signatures
    sig_rows = [
        [
            Paragraph(
                "<b>QUẢN LÝ ĐÁNH GIÁ</b><br/><font size='6' color='#64748B'>(Ký &amp; ghi rõ họ tên)</font>",
                style_cell_b
            ),
            Paragraph(
                "<b>NHÂN SỰ XÁC NHẬN</b><br/><font size='6' color='#64748B'>(Ký xác nhận)</font>",
                style_cell_rb
            )
        ],
        [
            Paragraph("<br/><br/><br/>", style_cell),
            Paragraph("<br/><br/><br/>", style_cell_rb)
        ]
    ]
    t_sig = Table(sig_rows, colWidths=[191, 192])
    t_sig.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    story.append(t_sig)

    doc.build(story)
    return buf.getvalue()

# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
WFM - Payslip Image Card Generator (Dark Luxury Edition)
Generates high-resolution PNG image cards (1080x1440) for mobile messaging (Zalo/Telegram).
Supports full Vietnamese typography via bundled open-source Inter TTF fonts (SIL OFL-1.1).
Zero external cloud dependency, runs 100% on-premise.
"""

import os
import io
import base64
from datetime import datetime
from typing import Dict, Any, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont

# Path resolution for bundled SIL OFL-1.1 Inter fonts + OS fallbacks
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_CURRENT_DIR)
_PROJECT_DIR = os.path.dirname(_BACKEND_DIR)

FONT_CANDIDATES = [
    os.path.join(_BACKEND_DIR, "assets", "fonts", "Inter-Regular.ttf"),
    os.path.join(_PROJECT_DIR, "backend", "assets", "fonts", "Inter-Regular.ttf"),
    "/app/assets/fonts/Inter-Regular.ttf",
    "/app/backend/assets/fonts/Inter-Regular.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

BOLD_FONT_CANDIDATES = [
    os.path.join(_BACKEND_DIR, "assets", "fonts", "Inter-Bold.ttf"),
    os.path.join(_PROJECT_DIR, "backend", "assets", "fonts", "Inter-Bold.ttf"),
    "/app/assets/fonts/Inter-Bold.ttf",
    "/app/backend/assets/fonts/Inter-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _get_font(bold: bool = False, size: int = 24) -> ImageFont.ImageFont:
    candidates = BOLD_FONT_CANDIDATES if bold else FONT_CANDIDATES
    for p in candidates:
        if p and os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None


DEFAULT_STORE_NAME = "FnBOps Store Lounge"


def _resolve_store_name() -> str:
    """Return the configured store name, or the default when config is unavailable."""
    try:
        try:
            from services.store_config import get_store_config
        except ImportError:
            from backend.services.store_config import get_store_config
        return str(get_store_config().get("store_name") or DEFAULT_STORE_NAME)
    except Exception:
        return DEFAULT_STORE_NAME


def format_currency(amount: float) -> str:
    amt = int(round(amount or 0))
    return f"{amt:,}".replace(",", ".") + " đ"


def render_payslip_card_png(
    staff_name: str,
    month: str,
    breakdown: Dict[str, Any],
    role_label: str = "Nhân Viên Vận Hành",
    employee_id: str = "WFM_STAFF",
    store_name: Optional[str] = None
) -> bytes:
    """
    Renders a 1080x1440 Dark Luxury Payslip Image Card as PNG bytes.
    The header uses the configured store name (falls back to the default store name).
    """
    store_title = (store_name or _resolve_store_name()).strip().upper()[:32]
    width, height = 1080, 1440
    img = Image.new("RGBA", (width, height), (16, 17, 20, 255)) # Deep Carbon #101114
    draw = ImageDraw.Draw(img)

    # 1. Fonts
    font_brand = _get_font(bold=True, size=38)
    font_sub = _get_font(bold=False, size=20)
    font_badge = _get_font(bold=True, size=22)
    font_title = _get_font(bold=True, size=46)
    font_meta = _get_font(bold=False, size=22)
    font_hero_val = _get_font(bold=True, size=68)
    font_hero_lbl = _get_font(bold=True, size=22)
    font_stat_val = _get_font(bold=True, size=30)
    font_stat_lbl = _get_font(bold=False, size=18)
    font_row_lbl = _get_font(bold=False, size=26)
    font_row_val = _get_font(bold=True, size=26)
    font_footer = _get_font(bold=False, size=19)

    # Colors
    c_card_bg = (24, 25, 29, 255)
    c_card_border = (42, 44, 52, 255)
    c_gold = (212, 175, 55, 255)        # #D4AF37
    c_gold_light = (245, 208, 98, 255)
    c_emerald = (16, 185, 129, 255)     # #10B981
    c_coral = (239, 68, 68, 255)        # #EF4444
    c_white = (255, 255, 255, 255)
    c_text_sec = (156, 163, 175, 255)   # #9CA3AF
    c_text_muted = (107, 114, 128, 255) # #6B7280

    # 2. Main Outer Card Frame (Double Bezel)
    pad = 40
    card_rect = [pad, pad, width - pad, height - pad]
    draw.rounded_rectangle(card_rect, radius=28, fill=c_card_bg, outline=c_card_border, width=2)

    # Top Gold Accent Line
    draw.rounded_rectangle([pad + 20, pad + 1, width - pad - 20, pad + 6], radius=3, fill=c_gold)

    # 3. Brand Header
    y = pad + 45
    draw.text((width // 2, y), store_title, fill=c_gold, font=font_brand, anchor="mt")
    y += 50
    draw.text((width // 2, y), "SYSTEM VERIFIED PAYROLL • POWERED BY FNBOPS", fill=c_text_muted, font=font_sub, anchor="mt")
    y += 40

    # Dashed divider line
    for x in range(pad + 40, width - pad - 40, 16):
        draw.line([(x, y), (x + 8, y)], fill=(55, 58, 68, 255), width=2)
    y += 30

    # 4. Period & Staff Title Section
    month_str = str(month).strip()
    badge_text = f"PHIẾU LƯƠNG THÁNG {month_str.upper()}"
    try:
        measured_badge_w = int(draw.textlength(badge_text, font=font_badge)) + 56
    except Exception:
        measured_badge_w = 360
    badge_w = max(360, min(width - 2 * pad - 80, measured_badge_w))
    badge_rect = [(width - badge_w) // 2, y, (width + badge_w) // 2, y + 42]
    draw.rounded_rectangle(badge_rect, radius=12, fill=(35, 38, 48, 255), outline=c_gold, width=1)
    draw.text((width // 2, y + 21), badge_text, fill=c_gold_light, font=font_badge, anchor="mm")
    y += 65

    # Staff Name (Prominent, auto-fit long Vietnamese full names cleanly)
    title_font_used = font_title
    try:
        if draw.textlength(staff_name, font=title_font_used) > (width - 2 * (pad + 40)):
            title_font_used = _get_font(bold=True, size=38)
    except Exception:
        pass
    draw.text((width // 2, y), staff_name, fill=c_white, font=title_font_used, anchor="mt")
    y += 60

    # Staff Meta Info: Role & ID
    meta_text = f"{role_label.upper()}   •   MÃ NV: {employee_id}"
    draw.text((width // 2, y), meta_text, fill=c_text_sec, font=font_meta, anchor="mt")
    y += 50

    # 5. Hero Amount Box (Net Pay)
    net_pay = breakdown.get("net_pay", 0)
    box_pad = pad + 40
    hero_h = 160
    hero_rect = [box_pad, y, width - box_pad, y + hero_h]
    draw.rounded_rectangle(hero_rect, radius=20, fill=(18, 20, 24, 255), outline=(52, 56, 68, 255), width=1)
    draw.rounded_rectangle([box_pad, y, box_pad + 6, y + hero_h], radius=3, fill=c_emerald)

    draw.text((width // 2, y + 32), "THỰC CHUYỂN KHOẢN (ĐÃ TRỪ TẠM ỨNG & KỶ LUẬT)", fill=c_text_sec, font=font_hero_lbl, anchor="mt")
    draw.text((width // 2, y + 68), format_currency(net_pay), fill=c_emerald, font=font_hero_val, anchor="mt")
    y += hero_h + 35

    # 6. Stats Trio (3 small cards)
    total_shifts = breakdown.get("total_shifts", 0)
    total_hours = breakdown.get("total_hours", 0.0)
    if not total_hours and "total_worked_minutes" in breakdown:
        total_hours = breakdown.get("total_worked_minutes", 0) / 60.0
    base_wage = breakdown.get("base_wage", 0)

    stats = [
        (f"{total_shifts} ca", "TỔNG CA LÀM"),
        (f"{total_hours:.1f}h", "TỔNG GIỜ CÔNG"),
        (f"{format_currency(base_wage)}/h", "ĐƠN GIÁ GIỜ")
    ]
    trio_gap = 16
    trio_w = (width - 2 * box_pad - 2 * trio_gap) // 3
    trio_h = 95

    for i, (val, lbl) in enumerate(stats):
        tx1 = box_pad + i * (trio_w + trio_gap)
        ty1 = y
        tx2 = tx1 + trio_w
        ty2 = ty1 + trio_h
        draw.rounded_rectangle([tx1, ty1, tx2, ty2], radius=14, fill=(28, 30, 36, 255), outline=c_card_border, width=1)
        draw.text((tx1 + trio_w // 2, ty1 + 22), val, fill=c_white, font=font_stat_val, anchor="mt")
        draw.text((tx1 + trio_w // 2, ty1 + 62), lbl, fill=c_text_muted, font=font_stat_lbl, anchor="mt")

    y += trio_h + 40

    # 7. Detailed Items Breakdown Table
    table_rect = [box_pad, y, width - box_pad, y + 360]
    draw.rounded_rectangle(table_rect, radius=16, fill=(20, 21, 26, 255), outline=c_card_border, width=1)

    std_pay = breakdown.get("standard_pay", 0)
    eval_bonus = breakdown.get("eval_bonus", 0)
    advance_amt = breakdown.get("advance_amount", 0)
    late_penalty = breakdown.get("late_penalty_total", 0)
    eval_deduct = breakdown.get("eval_deductions", 0)
    total_penalty = late_penalty + eval_deduct

    rows = [
        ("Lương theo giờ làm thực tế", format_currency(std_pay), c_white),
        ("Thưởng hiệu quả / Phụ cấp ca", f"+{format_currency(eval_bonus)}" if eval_bonus else "0 đ", c_emerald if eval_bonus else c_text_muted),
        ("Tạm ứng đã nhận trong tháng", f"-{format_currency(advance_amt)}" if advance_amt else "0 đ", c_coral if advance_amt else c_text_muted),
        ("Khấu trừ đi trễ & vi phạm", f"-{format_currency(total_penalty)}" if total_penalty else "0 đ", c_coral if total_penalty else c_text_muted),
    ]

    row_y = y + 25
    for idx, (lbl, val, val_col) in enumerate(rows):
        draw.text((box_pad + 25, row_y), lbl, fill=c_text_sec, font=font_row_lbl, anchor="lt")
        draw.text((width - box_pad - 25, row_y), val, fill=val_col, font=font_row_val, anchor="rt")
        row_y += 75
        if idx < len(rows) - 1:
            draw.line([(box_pad + 20, row_y - 20), (width - box_pad - 20, row_y - 20)], fill=(34, 36, 44, 255), width=1)

    y += 385

    # 8. Footer Section
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    draw.text((width // 2, y), "• DỮ LIỆU ĐỐI SOÁT CHÍNH XÁC TỪ HỆ THỐNG POS •", fill=c_emerald, font=font_footer, anchor="mt")
    y += 32
    draw.text((width // 2, y), f"Xuất phiếu tự động lúc {now_str} • FnBOps", fill=c_text_muted, font=font_footer, anchor="mt")

    # Save to buffer
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_payslip_card_base64(
    staff_name: str,
    month: str,
    breakdown: Dict[str, Any],
    role_label: str = "Nhân Viên Vận Hành",
    employee_id: str = "WFM_STAFF"
) -> str:
    """Returns base64 string of the generated payslip card PNG."""
    raw_bytes = render_payslip_card_png(staff_name, month, breakdown, role_label, employee_id)
    return base64.b64encode(raw_bytes).decode("utf-8")

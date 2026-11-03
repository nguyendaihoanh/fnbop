#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
TỰ ĐỘNG QUÉT & ĐÓNG CA CHẤM CÔNG BỊ TREO (FnBOps)
- Ca Sáng: Đóng ca lúc 11:30 nếu sau 14:00 nhân viên vẫn chưa check-out.
- Ca Tối: Đóng ca lúc 23:00 nếu sau 01:00 sáng hôm sau vẫn chưa check-out.
- Cập nhật thời lượng làm việc chuẩn xác, chống mất công cho nhân viên.
- Gửi thông báo Telegram tổng hợp cho Quản lý / Chủ quán.
"""

import sys, os, json, datetime, urllib.request, urllib.parse

_script_dir = os.path.dirname(os.path.abspath(__file__))
_data_dir = os.getenv("DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(_script_dir)), "data"))
LOGS_FILE = os.path.join(_data_dir, "attendance_logs.json")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

def send_telegram(text: str):
    try:
        from backend.services.send_telegram import send_telegram_alert
        send_telegram_alert(text, channel="dev")
    except Exception:
        # Fallback direct request
        test_token = os.getenv("TELEGRAM_DEV_BOT_TOKEN") or os.getenv("TEST_TELEGRAM_BOT_TOKEN") or TELEGRAM_BOT_TOKEN
        if not test_token or not TELEGRAM_CHAT_ID:
            return
        try:
            url = f"https://api.telegram.org/bot{test_token}/sendMessage"
            data = urllib.parse.urlencode({"chat_id": TELEGRAM_CHAT_ID, "text": text}).encode()
            req = urllib.request.Request(url, data=data)
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            print(f"Telegram alert error: {e}")

def parse_date(date_str: str) -> datetime.date:
    try:
        if "/" in date_str:
            return datetime.datetime.strptime(date_str, "%d/%m/%Y").date()
        return datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return datetime.date.today()

def calculate_duration(checkin_date: str, checkin_time: str, checkout_time: str) -> int:
    try:
        dt_in = datetime.datetime.strptime(checkin_date + " " + checkin_time, "%d/%m/%Y %H:%M")
        dt_out = datetime.datetime.strptime(checkin_date + " " + checkout_time, "%d/%m/%Y %H:%M")
        if dt_out < dt_in:
            dt_out += datetime.timedelta(days=1)
        diff = int((dt_out - dt_in).total_seconds() / 60)
        return max(0, diff)
    except Exception:
        return 0

def run_auto_close():
    if not os.path.exists(LOGS_FILE):
        print("Logs file not found.")
        return

    with open(LOGS_FILE, "r", encoding="utf-8") as f:
        try:
            logs = json.load(f)
        except Exception as e:
            print("Failed to read logs:", e)
            return

    now = datetime.datetime.now()
    today = now.date()
    closed_items = []
    modified = False

    for log in logs:
        if log.get("checkout_time") is not None:
            continue

        log_date = parse_date(log.get("date", ""))
        shift_key = log.get("shift_key", "sang")
        should_close = False
        default_checkout = "11:30" if shift_key == "sang" else "23:00"

        # 1. Ca sáng: Quá hạn nếu ca sáng hôm nay đã quá 14:00 HOẶC ca sáng của ngày cũ
        if shift_key == "sang":
            if log_date < today or (log_date == today and now.hour >= 14):
                should_close = True
                default_checkout = "11:30"

        # 2. Ca tối: Quá hạn nếu ca tối thuộc ngày cũ
        elif shift_key == "toi":
            if log_date < today:
                should_close = True
                default_checkout = "23:00"

        if should_close:
            log["checkout_time"] = default_checkout
            c_date = log.get("date", today.strftime("%d/%m/%Y"))
            c_in = log.get("checkin_time", "06:00" if shift_key == "sang" else "17:00")
            dur = calculate_duration(c_date, c_in, default_checkout)
            log["total_mins"] = dur
            log["effective_duration_mins"] = 0
            log["is_hanging_pending"] = True
            log["status"] = "QUEN_CHECKOUT"
            log["closed_by"] = "AUTO_SYSTEM"
            log["note"] = "[Hệ thống] Tự động phát hiện quên check-out, ca chuyển sang trạng thái QUEN_CHECKOUT chờ Quản lý duyệt."
            log["updated_at"] = now.strftime("%Y-%m-%d %H:%M:%S")

            closed_items.append({
                "username": log.get("username"),
                "name": log.get("display_name", log.get("username")),
                "date": log.get("date"),
                "shift": log.get("shift_name", shift_key),
                "in": c_in,
                "out": default_checkout,
                "mins": dur
            })
            modified = True

    if modified:
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if backend_dir not in sys.path:
            sys.path.insert(0, backend_dir)
        try:
            from services.attendance_service import save_attendance_logs
            save_attendance_logs(logs)
        except Exception:
            from services.storage import safe_json_write
            safe_json_write(LOGS_FILE, logs)
        print("Auto-closed", len(closed_items), "hanging shifts.")

        summary_lines = []
        for item in closed_items:
            summary_lines.append("- " + str(item["name"]) + " (@" + str(item["username"]) + "): " + str(item["shift"]) + " ngày " + str(item["date"]) + " (" + str(item["in"]) + " -> " + str(item["out"]) + ", " + str(item["mins"]) + "p)")
        
        msg = (
            "[TỰ ĐỘNG CHỐT CA QUÊN CHECK-OUT]\n"
            "Thời gian quét: " + now.strftime("%d/%m/%Y %H:%M:%S") + "\n"
            "Đã tự động đóng " + str(len(closed_items)) + " ca quá hạn:\n"
            + "\n".join(summary_lines) + "\n"
            "Hệ thống đã tự động tính công theo khung chuẩn để đảm bảo quyền lợi nhân viên."
        )
        send_telegram(msg)
    else:
        print("No hanging shifts found to close.")

    # Tự động sao lưu database SQLite an toàn chuẩn WAL và dọn dẹp file cũ > 30 ngày
    try:
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if backend_dir not in sys.path:
            sys.path.insert(0, backend_dir)
        from services.db import safe_sqlite_backup
        b_path = safe_sqlite_backup()
        print(f"Auto backup completed at: {b_path}")
    except Exception as e:
        print(f"Warning: safe_sqlite_backup failed during auto-close: {e}")

if __name__ == "__main__":
    run_auto_close()

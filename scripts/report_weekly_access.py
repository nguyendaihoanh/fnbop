#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WEEKLY ACCESS & AUDIT REPORT DIGEST
FNBOPS.LOCAL (Workforce Management & POS Operations)

Runs every Sunday at 09:00 AM (via crontab):
0 9 * * 0 python3 /path/to/fnbop/scripts/report_weekly_access.py --send-telegram >> /tmp/weekly_access_report.log 2>&1

Features:
1. Summarizes access events from Monday 00:00:00 to Sunday 09:00:00 (or past N days).
2. Aggregates:
   - Total access counts & active staff count.
   - Operating system & Device distribution (iOS iPhone, Android, Windows, Mac).
   - Geofence analysis: At cafe (WiFi Quán) vs Remote (4G / External).
   - Security alarms: Remote check-in attempts blocked, failed PIN attempts.
   - Per-staff breakdown (Username, Full Name, Hits, Primary Device, Main Actions).
3. Automatically purges audit logs older than 90 days.
4. Sends digest to Telegram with chunking (never exceeds 4000 chars per message).
"""

import os
import sys
import argparse
import logging
import datetime
from typing import Dict, List, Any, Optional, Tuple

# Base paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend"))
sys.path.insert(0, PROJECT_ROOT)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("weekly_access_report")


def load_environment():
    """Load environment variables from standard secret locations."""
    try:
        from dotenv import load_dotenv
        for p in [
            os.path.join(PROJECT_ROOT, ".env"),
            os.path.join(PROJECT_ROOT, "config", ".env"),
            os.path.join(PROJECT_ROOT, "backend", ".env"),
            os.path.expanduser("~/.env.guard")
        ]:
            if os.path.exists(p):
                load_dotenv(p, override=False)
    except ImportError:
        pass


load_environment()

try:
    from backend.services.db import (
        get_access_audit_logs,
        purge_old_access_audit_logs,
        get_db_path,
        init_db
    )
except ImportError:
    try:
        from services.db import (
            get_access_audit_logs,
            purge_old_access_audit_logs,
            get_db_path,
            init_db
        )
    except ImportError:
        logger.error("Could not import db service from backend or root.")
        sys.exit(1)


def get_weekly_window(reference_dt: Optional[datetime.datetime] = None, days_back: Optional[int] = None) -> Tuple[datetime.datetime, datetime.datetime]:
    """
    Calculates window: Monday 00:00:00 to reference_dt (default Sunday 09:00:00).
    If days_back is provided, calculates (reference_dt - days_back) to reference_dt.
    """
    now = reference_dt or datetime.datetime.now()
    if days_back:
        start_dt = (now - datetime.timedelta(days=days_back)).replace(hour=0, minute=0, second=0, microsecond=0)
        return start_dt, now

    # Calculate Monday of the current week (weekday 0 is Monday)
    monday = (now - datetime.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return monday, now


def send_telegram_message(message: str, dry_run: bool = False) -> bool:
    """Sends message to configured Telegram bot/chat."""
    if dry_run:
        logger.info("[DRY-RUN] Would send Telegram message:\n" + message)
        return True

    token = os.getenv("GUARD_TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("GUARD_TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")

    # Fallback to defaults if known
    if not token:
        logger.error("Missing TELEGRAM_BOT_TOKEN in environment.")
        return False
    if not chat_id:
        logger.error("Missing TELEGRAM_CHAT_ID in environment.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}

    try:
        import requests
        res = requests.post(url, data=payload, timeout=15)
        res.raise_for_status()
        logger.info("Telegram digest sent successfully.")
        return True
    except Exception as e:
        # Fallback to urllib
        import urllib.request
        import urllib.parse
        try:
            data = urllib.parse.urlencode(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, method="POST")
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status == 200:
                    logger.info("Telegram digest sent via urllib.")
                    return True
        except Exception as err:
            logger.error(f"Failed to send Telegram message: {err} (original: {e})")
            return False
    return False


def build_weekly_report(start_dt: datetime.datetime, end_dt: datetime.datetime, logs: List[Dict[str, Any]]) -> List[str]:
    """
    Builds one or more Telegram messages (HTML formatted) summarizing the audit logs.
    """
    start_str = start_dt.strftime("%d/%m/%Y")
    end_str = end_dt.strftime("%d/%m/%Y %H:%M")
    total_events = len(logs)

    if total_events == 0:
        msg = (
            f"<b>[BÁO CÁO TUẦN] TRUY CẬP {os.getenv('SYSTEM_NAME', 'FNBOPS.LOCAL')}</b>\n"
            f"<i>Khoảng thời gian: {start_str} - {end_str}</i>\n\n"
            f"Không ghi nhận lượt truy cập nào trong tuần qua."
        )
        return [msg]

    # Aggregations
    user_stats: Dict[str, Dict[str, Any]] = {}
    os_counts: Dict[str, int] = {}
    device_counts: Dict[str, int] = {}
    cafe_wifi_count = 0
    remote_count = 0
    blocked_wifi_attempts: List[Dict[str, Any]] = []
    failed_login_attempts: List[Dict[str, Any]] = []

    for r in logs:
        u = r.get("username") or "unknown"
        fn = r.get("full_name") or u
        action = r.get("action") or "UNKNOWN"
        is_cafe = bool(r.get("is_cafe_wifi"))
        os_name = r.get("os_name") or "Other"
        dev = r.get("device_type") or "Other"

        # Tally WiFi
        if is_cafe:
            cafe_wifi_count += 1
        else:
            remote_count += 1

        # Tally OS & Device
        os_counts[os_name] = os_counts.get(os_name, 0) + 1
        device_counts[dev] = device_counts.get(dev, 0) + 1

        # Special alarms
        if action == "ATTENDANCE_BLOCKED_WIFI":
            blocked_wifi_attempts.append(r)
        elif action in ("LOGIN_FAILED", "LOGIN_LOCKED"):
            failed_login_attempts.append(r)

        # User breakdown
        if u not in user_stats:
            user_stats[u] = {
                "full_name": fn,
                "role": r.get("role") or "STAFF",
                "count": 0,
                "os_map": {},
                "actions": {},
                "cafe_hits": 0,
                "remote_hits": 0
            }
        user_stats[u]["count"] += 1
        user_stats[u]["os_map"][os_name] = user_stats[u]["os_map"].get(os_name, 0) + 1
        user_stats[u]["actions"][action] = user_stats[u]["actions"].get(action, 0) + 1
        if is_cafe:
            user_stats[u]["cafe_hits"] += 1
        else:
            user_stats[u]["remote_hits"] += 1

    # Format Overview Header
    unique_users = len(user_stats)
    os_breakdown = ", ".join([f"{k}: {v} ({v*100//total_events}%)" for k, v in sorted(os_counts.items(), key=lambda x: x[1], reverse=True)])
    
    header = (
        f"<b>[BÁO CÁO TUẦN] TRUY CẬP HỆ THỐNG {os.getenv('SYSTEM_NAME', 'FNBOPS.LOCAL')}</b>\n"
        f"<i>Thời gian: {start_str} - {end_str}</i>\n\n"
        f"<b>1. TỔNG QUAN LƯỢT TRUY CẬP:</b>\n"
        f"• Tổng số lượt thao tác: <b>{total_events}</b> lượt\n"
        f"• Số nhân sự đã đăng nhập: <b>{unique_users}</b> người\n"
        f"• Hệ điều hành: {os_breakdown}\n\n"
        f"<b>2. PHÂN BỐ VỊ TRÍ TRUY CẬP:</b>\n"
        f"• Tại quán (WiFi Quán): <b>{cafe_wifi_count}</b> lượt ({cafe_wifi_count*100//total_events}%)\n"
        f"• Ngoài quán (4G/Internet): <b>{remote_count}</b> lượt ({remote_count*100//total_events}%)\n\n"
    )

    # Security & Anomalies Section
    security_section = "<b>3. CẢNH BÁO AN NINH & BẤT THƯỜNG:</b>\n"
    if blocked_wifi_attempts:
        security_section += f"• ⚠️ <b>{len(blocked_wifi_attempts)} lần</b> cố chấm công ngoài quán bị chặn:\n"
        # Show sample of blocked users
        blocked_users = {}
        for b in blocked_wifi_attempts:
            un = b.get("username")
            blocked_users[un] = blocked_users.get(un, 0) + 1
        for bu, cnt in list(blocked_users.items())[:5]:
            security_section += f"   - <code>{bu}</code>: {cnt} lần thử ngoài WiFi quán\n"
    else:
        security_section += "• Không phát hiện gian lận chấm công từ xa ngoài quán.\n"

    if failed_login_attempts:
        security_section += f"• ⚠️ <b>{len(failed_login_attempts)} lượt</b> đăng nhập sai mã PIN/mật khẩu:\n"
        failed_users = {}
        for f in failed_login_attempts:
            un = f.get("username")
            failed_users[un] = failed_users.get(un, 0) + 1
        for fu, cnt in list(failed_users.items())[:5]:
            security_section += f"   - <code>{fu}</code>: {cnt} lần sai PIN\n"
    else:
        security_section += "• Không có trường hợp dò quét mã PIN bất thường.\n"

    security_section += "\n"

    # User Activity List
    user_section = "<b>4. NHẬT KÝ THAO TÁC THEO NHÂN SỰ:</b>\n"
    sorted_users = sorted(user_stats.items(), key=lambda x: x[1]["count"], reverse=True)
    
    user_lines = []
    for u, data in sorted_users:
        fn = data["full_name"]
        role = data["role"]
        cnt = data["count"]
        # Primary OS
        primary_os = max(data["os_map"].items(), key=lambda x: x[1])[0] if data["os_map"] else "N/A"
        
        # Action summary
        actions_str = []
        if "LOGIN_SUCCESS" in data["actions"]:
            actions_str.append(f"Login ({data['actions']['LOGIN_SUCCESS']})")
        if "ATTENDANCE_CHECKIN" in data["actions"]:
            actions_str.append(f"Vào ca ({data['actions']['ATTENDANCE_CHECKIN']})")
        if "ATTENDANCE_CHECKOUT" in data["actions"]:
            actions_str.append(f"Ra ca ({data['actions']['ATTENDANCE_CHECKOUT']})")
        if "VIEW_DASHBOARD_DATA" in data["actions"]:
            actions_str.append(f"Xem lương/ca ({data['actions']['VIEW_DASHBOARD_DATA']})")
        
        act_summary = ", ".join(actions_str) if actions_str else "Truy cập hệ thống"
        line = f"• <b>{fn}</b> (<code>{u}</code> - {role}): <b>{cnt}</b> lượt\n  - Vị trí: Quán {data['cafe_hits']} | Ngoài {data['remote_hits']} | Thiết bị: {primary_os}\n  - Hoạt động: {act_summary}"
        user_lines.append(line)

    user_section += "\n\n".join(user_lines)

    # Combine into messages with length check (< 3900 chars per part)
    full_text = header + security_section + user_section
    if len(full_text) <= 3900:
        return [full_text]

    # Split: Part 1 = Header + Security; Part 2 = User activity
    part1 = header + security_section
    part2 = "<b>4. NHẬT KÝ THAO TÁC THEO NHÂN SỰ (TIẾP THEO):</b>\n\n" + "\n\n".join(user_lines)
    
    if len(part2) <= 3900:
        return [part1, part2]

    # If user section still too large, chunk user lines
    messages = [part1]
    current_chunk = ["<b>4. NHẬT KÝ THAO TÁC THEO NHÂN SỰ (PHẦN 1):</b>\n"]
    current_len = len(current_chunk[0])

    for line in user_lines:
        line_len = len(line) + 2
        if current_len + line_len > 3500:
            messages.append("\n\n".join(current_chunk))
            current_chunk = [f"<b>4. NHẬT KÝ THEO NHÂN SỰ (TIẾP THEO):</b>\n", line]
            current_len = len(current_chunk[0]) + line_len
        else:
            current_chunk.append(line)
            current_len += line_len

    if current_chunk:
        messages.append("\n\n".join(current_chunk))

    return messages


def run_weekly_digest(
    days: Optional[int] = None,
    send_telegram: bool = False,
    dry_run: bool = False
) -> Dict[str, Any]:
    """Main execution function for weekly access digest."""
    start_dt, end_dt = get_weekly_window(days_back=days)
    start_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
    end_str = end_dt.strftime("%Y-%m-%d %H:%M:%S")

    logger.info(f"Querying audit logs from {start_str} to {end_str}...")
    logs = get_access_audit_logs(start_str, end_str)
    logger.info(f"Retrieved {len(logs)} audit log records.")

    messages = build_weekly_report(start_dt, end_dt, logs)

    delivered = False
    if send_telegram or dry_run:
        all_ok = True
        for idx, msg in enumerate(messages):
            logger.info(f"Dispatching report message part {idx+1}/{len(messages)}...")
            success = send_telegram_message(msg, dry_run=dry_run)
            if not success:
                all_ok = False
        delivered = all_ok

    # Retention cleanup (older than 90 days)
    purged_count = 0
    if not dry_run:
        purged_count = purge_old_access_audit_logs(retention_days=90)
        if purged_count > 0:
            logger.info(f"Purged {purged_count} audit log records older than 90 days.")

    return {
        "start_time": start_str,
        "end_time": end_str,
        "total_records": len(logs),
        "messages_count": len(messages),
        "delivered": delivered,
        "purged_records": purged_count
    }


def main():
    parser = argparse.ArgumentParser(description="Weekly Access & Audit Report Digest - FnBOps")
    parser.add_argument("--days", type=int, default=None, help="Number of days to look back (default: from Monday 00:00 to now)")
    parser.add_argument("--send-telegram", action="store_true", help="Send compiled digest to Telegram")
    parser.add_argument("--dry-run", action="store_true", help="Print digest to console without sending Telegram or purging DB")
    parser.add_argument("--check-now", action="store_true", help="Trigger audit digest generation immediately")

    args = parser.parse_args()

    if not (args.send_telegram or args.dry_run or args.check_now):
        # Default behavior when run via cron
        args.send_telegram = True

    result = run_weekly_digest(
        days=args.days,
        send_telegram=args.send_telegram,
        dry_run=args.dry_run
    )
    print(f"Weekly digest finished: {result['total_records']} records processed, {result['messages_count']} message parts.")


if __name__ == "__main__":
    main()

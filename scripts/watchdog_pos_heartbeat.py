#!/usr/bin/env python3
"""
scripts/watchdog_pos_heartbeat.py
Watchdog daemon / monitor script for WFM POS Heartbeat.
- Checks data/pos_heartbeat.json for the last heartbeat from the POS machine.
- Operates during cafe operating hours: 05:30 to 23:30 daily.
- Alerts if last heartbeat is older than 45 minutes.
- Anti-spam alert throttling: Minimum 60 minutes between alerts.
- CLI flags: --check-now, --dry-run, --test-alert
"""

import os
import sys
import json
import logging
import argparse
from datetime import datetime, time, timezone
from typing import Optional, Tuple, Dict, Any

# Ensure project root is in sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("pos_watchdog")

# Operating hours for FnBOps Store
OPERATING_START = time(5, 30)
OPERATING_END = time(23, 30)

# Default thresholds (in minutes)
DEFAULT_THRESHOLD_MINUTES = 45
DEFAULT_THROTTLE_MINUTES = 60


def load_env_variables():
    """Load environment variables from .env files if available."""
    try:
        from dotenv import load_dotenv
        # Try loading root .env first
        root_env = os.path.join(PROJECT_ROOT, ".env")
        if os.path.exists(root_env):
            load_dotenv(root_env)
        # Try loading config/.env (where Telegram secrets usually reside)
        config_env = os.path.join(PROJECT_ROOT, "config", ".env")
        if os.path.exists(config_env):
            load_dotenv(config_env, override=False)
        # Also check backend/.env
        backend_env = os.path.join(PROJECT_ROOT, "backend", ".env")
        if os.path.exists(backend_env):
            load_dotenv(backend_env, override=False)
        # Check guard env if present (~/.env.guard)
        guard_env = os.path.expanduser("~/.env.guard")
        if os.path.exists(guard_env):
            load_dotenv(guard_env, override=False)
    except ImportError:
        logger.debug("python-dotenv không được cài đặt, sử dụng biến môi trường hiện tại.")


def resolve_heartbeat_path(custom_path: Optional[str] = None) -> str:
    """Find pos_heartbeat.json file location."""
    if custom_path:
        return custom_path

    env_path = os.getenv("HEARTBEAT_FILE")
    if env_path and os.path.exists(env_path):
        return env_path

    # Check data/pos_heartbeat.json at project root
    root_data_path = os.path.join(PROJECT_ROOT, "data", "pos_heartbeat.json")
    if os.path.exists(root_data_path):
        return root_data_path

    # Check backend/data/pos_heartbeat.json
    backend_data_path = os.path.join(PROJECT_ROOT, "backend", "data", "pos_heartbeat.json")
    if os.path.exists(backend_data_path):
        return backend_data_path

    # Fallback to custom_path or root_data_path even if not exists yet
    return custom_path or env_path or root_data_path


def resolve_state_path(custom_path: Optional[str] = None) -> str:
    """Find state file location for throttling."""
    if custom_path:
        return custom_path

    env_path = os.getenv("WATCHDOG_STATE_FILE")
    if env_path:
        return env_path

    # Default to data/last_watchdog_alert.json
    return os.path.join(PROJECT_ROOT, "data", "last_watchdog_alert.json")


def is_within_operating_hours(current_time: Optional[time] = None) -> bool:
    """Check if current time is within operating hours (05:30 - 23:30)."""
    if current_time is None:
        current_time = datetime.now().time()
    return OPERATING_START <= current_time <= OPERATING_END


def parse_last_seen(val: Any) -> Optional[datetime]:
    """Parse last_seen value (ISO string, unix timestamp, or formatted string)."""
    if val is None:
        return None

    if isinstance(val, (int, float)):
        return datetime.fromtimestamp(val)

    if isinstance(val, str):
        val = val.strip()
        if not val:
            return None

        # Check if numeric string timestamp
        try:
            num = float(val)
            return datetime.fromtimestamp(num)
        except ValueError:
            pass

        # Try ISO format
        try:
            clean_val = val.replace("Z", "+00:00") if val.endswith("Z") else val
            return datetime.fromisoformat(clean_val)
        except ValueError:
            pass

        # Try standard string date formats
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y/%m/%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
        ):
            try:
                return datetime.strptime(val, fmt)
            except ValueError:
                pass

    return None


def calculate_diff_minutes(now: datetime, last_seen_dt: datetime) -> float:
    """Calculate difference in minutes between now and last_seen_dt."""
    # Harmonize timezone awareness
    if now.tzinfo is not None and last_seen_dt.tzinfo is None:
        last_seen_dt = last_seen_dt.replace(tzinfo=now.tzinfo)
    elif now.tzinfo is None and last_seen_dt.tzinfo is not None:
        last_seen_dt = last_seen_dt.astimezone().replace(tzinfo=None)

    delta = now - last_seen_dt
    return delta.total_seconds() / 60.0


def read_heartbeat_data(file_path: str) -> Tuple[Optional[datetime], Optional[str], Optional[str]]:
    """
    Read pos_heartbeat.json.
    Returns (last_seen_datetime, cafe_ip, raw_last_seen_str).
    """
    if not os.path.exists(file_path):
        logger.warning(f"File heartbeat không tồn tại: {file_path}")
        return None, None, None

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        raw_last_seen = data.get("last_seen") or data.get("updated_at")
        cafe_ip = data.get("cafe_ip")
        last_seen_dt = parse_last_seen(raw_last_seen)
        return last_seen_dt, cafe_ip, str(raw_last_seen)
    except Exception as e:
        logger.error(f"Lỗi khi đọc file heartbeat {file_path}: {e}")
        return None, None, None


def check_alert_throttling(state_file: str, now: datetime, throttle_minutes: int = DEFAULT_THROTTLE_MINUTES) -> Tuple[bool, Optional[float]]:
    """
    Check if alert should be throttled.
    Returns (is_throttled, elapsed_minutes_since_last_alert).
    """
    if not os.path.exists(state_file):
        return False, None

    try:
        with open(state_file, "r", encoding="utf-8") as f:
            state = json.load(f)

        last_ts = state.get("last_alert_timestamp")
        if last_ts is None:
            last_at_str = state.get("last_alert_at")
            if last_at_str:
                dt = parse_last_seen(last_at_str)
                if dt:
                    last_ts = dt.timestamp()

        if last_ts is not None:
            elapsed_seconds = now.timestamp() - float(last_ts)
            elapsed_minutes = elapsed_seconds / 60.0
            if elapsed_minutes < throttle_minutes:
                return True, elapsed_minutes
            return False, elapsed_minutes
    except Exception as e:
        logger.warning(f"Không thể đọc state file {state_file}: {e}")

    return False, None


def save_alert_state(state_file: str, now: datetime, diff_minutes: float, raw_last_seen: Any, status: str = "alert_sent"):
    """Persist alert state to disk atomically."""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(state_file)), exist_ok=True)
        state = {
            "last_alert_at": now.isoformat(),
            "last_alert_timestamp": now.timestamp(),
            "diff_minutes": round(diff_minutes, 1),
            "last_seen": raw_last_seen,
            "status": status,
            "updated_at": now.strftime("%Y-%m-%d %H:%M:%S")
        }
        temp_file = f"{state_file}.tmp.{os.getpid()}"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        os.replace(temp_file, state_file)
        logger.info(f"Đã lưu trạng thái cảnh báo vào {state_file}")
    except Exception as e:
        logger.error(f"Lỗi khi lưu state file {state_file}: {e}")


def clear_alert_throttle(state_file: str, now: datetime):
    """Mark system as healthy so that any future disconnection alerts immediately."""
    if not os.path.exists(state_file):
        return
    try:
        state = {
            "last_healthy_at": now.isoformat(),
            "status": "healthy",
            "updated_at": now.strftime("%Y-%m-%d %H:%M:%S")
        }
        temp_file = f"{state_file}.tmp.{os.getpid()}"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        os.replace(temp_file, state_file)
        logger.debug("Đã cập nhật trạng thái kết nối bình thường (healthy).")
    except Exception as e:
        logger.warning(f"Không thể cập nhật state file sau khi phục hồi: {e}")


def send_telegram_message(message: str, dry_run: bool = False) -> bool:
    """Send message to Telegram using configured token and chat_id."""
    load_env_variables()

    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("GUARD_TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("GUARD_TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.error("Lỗi cấu hình: Thiếu TELEGRAM_BOT_TOKEN hoặc TELEGRAM_CHAT_ID trong môi trường / config.")
        return False

    if dry_run:
        logger.info("[DRY-RUN] Bỏ qua bước gửi Telegram thực tế. Nội dung tin nhắn:")
        print("----------------------------------------")
        print(message)
        print("----------------------------------------")
        return True

    # Try backend.services.send_telegram first if available
    try:
        from backend.services.send_telegram import send_telegram_alert
        success = send_telegram_alert(message, chat_id=chat_id, token=token)
        if success:
            logger.info("Gửi cảnh báo Telegram thành công qua send_telegram service.")
            return True
    except Exception as e:
        logger.debug(f"Không thể gọi backend.services.send_telegram: {e}. Sử dụng HTTP fallback.")

    # Fallback via direct requests or urllib
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}

    try:
        import requests
        res = requests.post(url, data=payload, timeout=10)
        res.raise_for_status()
        logger.info("Đã gửi cảnh báo Telegram thành công.")
        return True
    except ImportError:
        # Fallback to urllib.request if requests is not installed
        import urllib.request
        import urllib.parse
        try:
            data = urllib.parse.urlencode(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, method="POST")
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    logger.info("Đã gửi cảnh báo Telegram thành công (qua urllib).")
                    return True
        except Exception as err:
            logger.error(f"Lỗi khi gửi Telegram qua urllib: {err}")
            return False
    except Exception as e:
        logger.error(f"Lỗi khi gửi Telegram: {e}")
        return False

    return False


def build_alert_message(diff_minutes: float, last_seen_dt: Optional[datetime], cafe_ip: Optional[str], now: datetime, threshold_minutes: int = DEFAULT_THRESHOLD_MINUTES) -> str:
    """Format emergency alert message for Telegram."""
    last_seen_str = last_seen_dt.strftime("%Y-%m-%d %H:%M:%S") if last_seen_dt else "Không xác định"
    ip_str = cafe_ip or "Không có thông tin"
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    return (
        f"🚨 [BÁO ĐỘNG] MÁY POS WFM MẤT KẾT NỐI\n\n"
        f"• Tình trạng: Quá {int(threshold_minutes)} phút không nhận được tín hiệu Heartbeat từ máy POS\n"
        f"• Thời gian mất kết nối: ~{diff_minutes:.0f} phút\n"
        f"• Ping cuối cùng: {last_seen_str}\n"
        f"• IP ghi nhận gần nhất: {ip_str}\n"
        f"• Thời điểm kiểm tra: {now_str}\n"
        f"• Khung giờ hoạt động: 05:30 - 23:30\n\n"
        f"⚠️ Đề xuất hành động:\n"
        f"1. Kiểm tra nguồn điện và mạng Wi-Fi/LAN máy POS tại quán.\n"
        f"2. Kiểm tra tiến trình wfm_pos_heartbeat trên Task Scheduler máy POS."
    )


def build_test_message(now: datetime) -> str:
    """Format test alert message."""
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"[FnBOps] TEST WATCHDOG POS HEARTBEAT\n\n"
        f"• Trạng thái: Kiểm tra kết nối Telegram Bot thành công\n"
        f"• Kênh cảnh báo: Telegram Alert Bot\n"
        f"• Thời điểm kiểm tra: {now_str}\n"
        f"• Watchdog POS Heartbeat hoạt động bình thường."
    )


def run_watchdog_check(
    heartbeat_file: Optional[str] = None,
    state_file: Optional[str] = None,
    threshold_minutes: int = DEFAULT_THRESHOLD_MINUTES,
    throttle_minutes: int = DEFAULT_THROTTLE_MINUTES,
    dry_run: bool = False,
    now: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    Main watchdog check logic.
    Returns a dict with check result details.
    """
    if now is None:
        now = datetime.now()

    hb_path = resolve_heartbeat_path(heartbeat_file)
    st_path = resolve_state_path(state_file)

    result = {
        "timestamp": now.isoformat(),
        "heartbeat_file": hb_path,
        "state_file": st_path,
        "in_operating_hours": False,
        "is_healthy": True,
        "diff_minutes": None,
        "alert_triggered": False,
        "alert_throttled": False,
        "message": ""
    }

    # Step 1: Check operating hours
    if not is_within_operating_hours(now.time()):
        msg = f"Ngoài khung giờ hoạt động của quán (05:30 - 23:30). Thời gian hiện tại: {now.strftime('%H:%M:%S')}. Bỏ qua kiểm tra."
        logger.info(msg)
        result["message"] = msg
        return result

    result["in_operating_hours"] = True

    # Step 2: Read heartbeat file
    last_seen_dt, cafe_ip, raw_last_seen = read_heartbeat_data(hb_path)

    if last_seen_dt is None:
        diff_minutes = 999999.0
        msg = f"Cảnh báo: Không thể đọc mốc last_seen từ {hb_path}."
        logger.warning(msg)
    else:
        diff_minutes = calculate_diff_minutes(now, last_seen_dt)

    result["diff_minutes"] = round(diff_minutes, 1)

    # Step 3: Evaluate against threshold
    if diff_minutes <= threshold_minutes:
        msg = f"POS heartbeat bình thường. Ping cuối cách đây {diff_minutes:.1f} phút (ngưỡng {threshold_minutes} phút). IP: {cafe_ip}."
        logger.info(msg)
        result["is_healthy"] = True
        result["message"] = msg
        clear_alert_throttle(st_path, now)
        return result

    # POS connection lost > threshold_minutes
    result["is_healthy"] = False
    logger.warning(
        f"Phát hiện mất kết nối POS: ~{diff_minutes:.1f} phút (vượt ngưỡng {threshold_minutes} phút). Ping cuối: {raw_last_seen}."
    )

    # Step 4: Anti-Spam Throttling check
    is_throttled, elapsed_minutes = check_alert_throttling(st_path, now, throttle_minutes=throttle_minutes)
    if is_throttled:
        msg = f"Cảnh báo bị chặn bởi cơ chế Anti-Spam: Đã gửi cảnh báo cách đây {elapsed_minutes:.1f} phút (giãn cách tối thiểu: {throttle_minutes} phút)."
        logger.info(msg)
        result["alert_throttled"] = True
        result["message"] = msg
        return result

    # Step 5: Trigger alert
    alert_msg = build_alert_message(diff_minutes, last_seen_dt, cafe_ip, now, threshold_minutes=threshold_minutes)
    success = send_telegram_message(alert_msg, dry_run=dry_run)

    if success:
        result["alert_triggered"] = True
        msg = f"Đã phát cảnh báo khẩn cấp (gián đoạn {diff_minutes:.1f} phút)."
        result["message"] = msg
        if not dry_run:
            save_alert_state(st_path, now, diff_minutes, raw_last_seen, status="alert_sent")
        else:
            logger.info("[DRY-RUN] Không lưu state file.")
    else:
        msg = "Phát cảnh báo thất bại do lỗi gửi Telegram."
        logger.error(msg)
        result["message"] = msg

    return result


def main():
    parser = argparse.ArgumentParser(description="Watchdog POS Heartbeat Monitor - WFM")
    parser.add_argument("--check-now", action="store_true", help="Kiểm tra trạng thái heartbeat ngay lập tức")
    parser.add_argument("--dry-run", action="store_true", help="Chạy thử nghiệm in ra console mà không gửi Telegram thật")
    parser.add_argument("--test-alert", action="store_true", help="Gửi tin nhắn test qua Telegram để xác nhận token/chat ID")
    parser.add_argument("--heartbeat-file", type=str, default=None, help="Đường dẫn tùy chỉnh tới pos_heartbeat.json")
    parser.add_argument("--state-file", type=str, default=None, help="Đường dẫn tùy chỉnh tới file state cache")
    parser.add_argument("--threshold-minutes", type=int, default=DEFAULT_THRESHOLD_MINUTES, help="Số phút mất kết nối tối đa trước khi cảnh báo (mặc định: 45)")
    parser.add_argument("--throttle-minutes", type=int, default=DEFAULT_THROTTLE_MINUTES, help="Giãn cách giữa 2 lần cảnh báo (mặc định: 60)")

    args = parser.parse_args()

    # Pre-load environment variables
    load_env_variables()

    now = datetime.now()

    if args.test_alert:
        logger.info("Chế độ --test-alert: Gửi tin nhắn thử nghiệm tới Telegram...")
        test_msg = build_test_message(now)
        success = send_telegram_message(test_msg, dry_run=args.dry_run)
        if success:
            logger.info("Tin nhắn test đã được xử lý thành công.")
            sys.exit(0)
        else:
            logger.error("Gửi tin nhắn test thất bại.")
            sys.exit(1)

    # Default action: perform watchdog check
    result = run_watchdog_check(
        heartbeat_file=args.heartbeat_file,
        state_file=args.state_file,
        threshold_minutes=args.threshold_minutes,
        throttle_minutes=args.throttle_minutes,
        dry_run=args.dry_run,
        now=now
    )

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

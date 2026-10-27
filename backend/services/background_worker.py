# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
Background Worker Service (FnBOps On-Premise)
Replaces external n8n CRON jobs with native asyncio background tasks:
1. Periodic auto-close of forgotten shifts (>48h) every 15 minutes.
2. Midnight snapshot backup of SQLite database (wfm.db) to data/backups/ at 23:59.
3. Graceful shutdown using asyncio.Event and task cancellation shields.
"""

import os
import sys
import sqlite3
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

try:
    from backend.services.db import get_db_path
except ImportError:
    from services.db import get_db_path

logger = logging.getLogger("background_worker")


def get_default_backup_dir() -> str:
    """Returns absolute path to data/backups directory."""
    if os.getenv("BACKUP_DIR"):
        return os.getenv("BACKUP_DIR")
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    root_dir = os.path.dirname(base_dir)
    root_backup_dir = os.path.join(root_dir, "data", "backups")
    if os.path.exists(os.path.dirname(root_backup_dir)):
        return root_backup_dir
    return os.path.join(base_dir, "data", "backups")


class BackgroundWorker:
    """
    Autonomous asynchronous worker managing scheduled background maintenance tasks.
    """
    def __init__(
        self,
        auto_close_interval_secs: Optional[int] = None,
        backup_check_interval_secs: Optional[int] = None,
        db_path: Optional[str] = None,
        backup_dir: Optional[str] = None,
        enable_mdns: Optional[bool] = None
    ):
        # 15 minutes = 900s by default
        env_close_interval = int(os.getenv("AUTO_CLOSE_INTERVAL_SECS", "900"))
        self.auto_close_interval_secs = auto_close_interval_secs or env_close_interval
        
        # Check every 30s by default for the 23:59 window
        env_backup_interval = int(os.getenv("BACKUP_CHECK_INTERVAL_SECS", "30"))
        self.backup_check_interval_secs = backup_check_interval_secs or env_backup_interval

        # Check every 60s by default for shift reminders
        env_reminder_interval = int(os.getenv("REMINDER_CHECK_INTERVAL_SECS", "60"))
        self.reminder_check_interval_secs = env_reminder_interval

        self.db_path = db_path
        self.backup_dir = backup_dir
        if enable_mdns is not None:
            self.enable_mdns = enable_mdns
        else:
            self.enable_mdns = (os.getenv("TESTING") != "1") and (os.getenv("ENABLE_MDNS", "0") == "1")

        self._stop_event = asyncio.Event()
        self._tasks: List[asyncio.Task] = []
        self._is_running = False
        self._last_backup_date: Optional[str] = None

        # Telemetry / metrics counters
        self.auto_close_runs = 0
        self.backup_runs = 0
        self.reminder_runs = 0

    @property
    def is_running(self) -> bool:
        return self._is_running

    async def start(self) -> None:
        """Starts all background worker tasks."""
        if self._is_running:
            logger.info("BackgroundWorker already running.")
            return

        self._stop_event.clear()
        self._is_running = True

        task_close = asyncio.create_task(
            self._auto_close_loop(),
            name="worker_shift_auto_close"
        )
        task_backup = asyncio.create_task(
            self._midnight_backup_loop(),
            name="worker_midnight_backup"
        )
        task_reminders = asyncio.create_task(
            self._shift_reminder_loop(),
            name="worker_shift_reminders"
        )
        self._tasks = [task_close, task_backup, task_reminders]

        # Khởi động mDNS broadcaster cho tên miền chamcong.local (chỉ khi không chạy test)
        if self.enable_mdns:
            try:
                try:
                    from backend.services.mdns_service import get_mdns_broadcaster
                except ImportError:
                    from services.mdns_service import get_mdns_broadcaster
                get_mdns_broadcaster().start()
            except Exception as e:
                logger.warning(f"Không thể khởi động mDNS broadcaster: {e}")

        logger.info(
            f"BackgroundWorker started successfully with 3 tasks "
            f"(auto_close_interval={self.auto_close_interval_secs}s, "
            f"backup_check_interval={self.backup_check_interval_secs}s, "
            f"reminder_interval={self.reminder_check_interval_secs}s)."
        )

    async def stop(self) -> None:
        """Gracefully halts all worker tasks."""
        if not self._is_running:
            return

        logger.info("Signaling BackgroundWorker graceful shutdown...")
        self._stop_event.set()

        # Dừng mDNS broadcaster
        if self.enable_mdns:
            try:
                try:
                    from backend.services.mdns_service import get_mdns_broadcaster
                except ImportError:
                    from services.mdns_service import get_mdns_broadcaster
                get_mdns_broadcaster().stop()
            except Exception:
                pass

        try:
            await asyncio.wait_for(
                asyncio.gather(*self._tasks, return_exceptions=True),
                timeout=5.0
            )
        except asyncio.TimeoutError:
            logger.warning("Background tasks did not finish within 5s timeout, forcing cancellation.")
            for t in self._tasks:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)

        self._tasks.clear()
        self._is_running = False
        logger.info("BackgroundWorker has stopped cleanly.")


    def _execute_auto_close(self) -> Dict[str, Any]:
        """Runs auto_close_hanging_shifts_logic() synchronously inside a worker thread."""
        try:
            try:
                from services.attendance_service import auto_close_hanging_shifts_logic
            except ImportError:
                from backend.services.attendance_service import auto_close_hanging_shifts_logic
            res = auto_close_hanging_shifts_logic()
            return res
        except Exception as e:
            logger.warning(f"Error during auto-close shift scan: {e}")
            return {"status": "error", "message": str(e)}

    async def _auto_close_loop(self) -> None:
        """Periodic task: Scans and auto-closes forgotten shifts older than 48h."""
        logger.info("Auto-close shift scheduler task started.")
        while not self._stop_event.is_set():
            try:
                result = await asyncio.to_thread(self._execute_auto_close)
                self.auto_close_runs += 1
                logger.info(f"Auto-close scan cycle #{self.auto_close_runs} finished: {result}")
            except Exception as e:
                logger.error(f"Unexpected error in auto-close loop: {e}")

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.auto_close_interval_secs
                )
            except asyncio.TimeoutError:
                pass

    def perform_db_snapshot(
        self,
        src_path: Optional[str] = None,
        dest_dir: Optional[str] = None
    ) -> Optional[str]:
        """
        Creates an atomic online snapshot of the SQLite database using sqlite3.backup().
        Saves file to destination: data/backups/fnbop_backup_YYYYMMDD_HHMMSS.db
        """
        src = src_path or self.db_path or get_db_path()
        target_dir = dest_dir or self.backup_dir or get_default_backup_dir()
        os.makedirs(target_dir, exist_ok=True)

        if not os.path.exists(src):
            logger.warning(f"Source database not found for snapshot: {src}")
            return None

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest_filename = f"fnbops_backup_{timestamp_str}.db"
        dest_path = os.path.join(target_dir, dest_filename)

        try:
            with sqlite3.connect(src, timeout=30.0) as src_conn:
                with sqlite3.connect(dest_path, timeout=30.0) as dest_conn:
                    src_conn.backup(dest_conn, pages=100, sleep=0.01)
            self.backup_runs += 1
            logger.info(f"SQLite online snapshot successfully created: {dest_path}")
            return dest_path
        except Exception as e:
            logger.error(f"Failed SQLite online backup: {e}, attempting WAL checkpoint fallback.")
            try:
                with sqlite3.connect(src, timeout=30.0) as cp_conn:
                    cp_conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                import shutil
                shutil.copy2(src, dest_path)
                for ext in ["-wal", "-shm"]:
                    src_extra = f"{src}{ext}"
                    dest_extra = f"{dest_path}{ext}"
                    if os.path.exists(src_extra):
                        shutil.copy2(src_extra, dest_extra)
                self.backup_runs += 1
                logger.info(f"SQLite WAL-safe snapshot created via checkpoint fallback: {dest_path}")
                return dest_path
            except Exception as e2:
                logger.error(f"WAL checkpoint copy fallback failed as well: {e2}")
                return None

    async def _midnight_backup_loop(self) -> None:
        """Periodic task: Watches for 23:59 each night and triggers database backup."""
        logger.info("Midnight backup scheduler task started.")
        while not self._stop_event.is_set():
            try:
                now = datetime.now()
                today_str = now.strftime("%Y-%m-%d")
                
                # Check for 23:59 trigger condition
                if now.hour == 23 and now.minute == 59 and self._last_backup_date != today_str:
                    logger.info(f"Midnight trigger detected at {now.isoformat()}. Starting database snapshot...")
                    snapshot_path = await asyncio.to_thread(self.perform_db_snapshot)
                    if snapshot_path:
                        self._last_backup_date = today_str
                        logger.info(f"Completed scheduled midnight backup for {today_str}: {snapshot_path}")
            except Exception as e:
                logger.error(f"Error during midnight backup evaluation: {e}")

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.backup_check_interval_secs
                )
            except asyncio.TimeoutError:
                pass

    def _execute_shift_reminders(self) -> Dict[str, Any]:
        """
        Synchronously runs shift reminders logic inside a worker thread:
        1. Check-in reminder (15 mins prior to shift start)
        2. Check-out reminder (10 mins after shift end if unclosed)
        3. Weekly roster registration reminder (Friday 20:00)
        """
        now = datetime.now()
        today_iso = now.strftime("%Y-%m-%d")
        today_vn = now.strftime("%d/%m/%Y")
        now_hm = now.strftime("%H:%M")

        results = {"checkin_sent": 0, "checkout_sent": 0, "roster_sent": 0}

        try:
            try:
                from backend.services.webpush_service import send_notification_to_user, send_notification_to_all
                from backend.services.db import (
                    has_notification_dispatched_db,
                    record_notification_dispatch_db,
                    save_in_app_reminder_db,
                    get_store_setting_db
                )
                from backend.services.attendance_service import load_attendance_logs
                from backend.services.auth import normalize_str
                from backend.services.roster_service import load_roster_data
            except ImportError:
                from services.webpush_service import send_notification_to_user, send_notification_to_all
                from services.db import (
                    has_notification_dispatched_db,
                    record_notification_dispatch_db,
                    save_in_app_reminder_db,
                    get_store_setting_db
                )
                from services.attendance_service import load_attendance_logs
                from services.auth import normalize_str
                from services.roster_service import load_roster_data

            if get_store_setting_db("auto_remind_shifts", "1") != "1":
                return results

            roster_data = load_roster_data()
            weeks = roster_data.get("weeks", roster_data)
            iso_year, iso_week, _ = now.isocalendar()
            cur_week_id = f"{iso_year}-W{iso_week:02d}"
            cur_week = weeks.get(cur_week_id, {})
            shifts_today = cur_week.get("shifts", {}).get(today_iso, {})

            att_logs = load_attendance_logs()
            today_logs = [l for l in att_logs if l.get("date") == today_vn]
            checked_in_users = {normalize_str(l.get("username", "")) for l in today_logs}

            m_shift = shifts_today.get("morning", {}) if shifts_today else {}
            e_shift = shifts_today.get("evening", {}) if shifts_today else {}

            checkin_msg = "Bạn có ca làm việc hôm nay nhưng chưa thấy Check-in. Vui lòng kết nối WiFi quán để Vào ca nhé! Hỗ trợ nhau chút. Thénnn kìuuu!!!"

            def _send_remind(username: str, remind_type: str, title: str, message: str, dedup_key: str):
                u = normalize_str(username)
                if not u:
                    return
                if not has_notification_dispatched_db(dedup_key):
                    # 1. Trigger in-app popup modal
                    save_in_app_reminder_db(
                        username=u,
                        remind_type=remind_type,
                        title=title,
                        message=message,
                        url="/index.html#attendance"
                    )
                    # 2. Trigger browser web push
                    send_notification_to_user(
                        username=u,
                        title=title,
                        body=message,
                        tag=f"auto-{remind_type.lower()}",
                        url="/index.html#attendance"
                    )
                    # 3. Trigger Zalo Gateway message if auto toggle is enabled
                    try:
                        try:
                            from services.store_config import get_store_config
                        except ImportError:
                            from backend.services.store_config import get_store_config
                        cfg = get_store_config()
                        z_auto = cfg.get("zalo_automation", {})
                        should_send_zalo = (
                            (remind_type == "CHECKIN" and z_auto.get("enable_auto_shift_reminder", False)) or
                            (remind_type == "CHECKOUT" and z_auto.get("enable_auto_checkout_alert", False))
                        )
                        if should_send_zalo:
                            try:
                                from services.auth import load_staff_auth
                            except ImportError:
                                from backend.services.auth import load_staff_auth
                            auth_data = load_staff_auth()
                            accounts = auth_data.get("staff_accounts", {})
                            acc = accounts.get(u, {})
                            phone = str(acc.get("phone") or "").strip()
                            if phone:
                                import requests
                                gateway_url = os.getenv("ZALO_GATEWAY_URL", "http://zalo-gateway:8177").rstrip("/")
                                gw_token = os.getenv("ZALO_GATEWAY_TOKEN", "").strip()
                                gw_headers = {"X-Zalo-Gateway-Token": gw_token} if gw_token else {}
                                custom_template = (
                                    z_auto.get("shift_reminder_message") if remind_type == "CHECKIN"
                                    else z_auto.get("checkout_alert_message")
                                )
                                body_content = custom_template.strip() if (custom_template and custom_template.strip()) else message
                                requests.post(
                                    f"{gateway_url}/api/zalo/send",
                                    json={
                                        "recipient": phone,
                                        "message": f"[{title.upper()}]\nChào bạn,\n{body_content}"
                                    },
                                    headers=gw_headers,
                                    timeout=5
                                )
                    except Exception as z_err:
                        logger.warning(f"Could not dispatch auto Zalo reminder to {u}: {z_err}")

                    # 4. Record deduplication (once per day)
                    record_notification_dispatch_db(
                        dedup_key=dedup_key,
                        notification_type=f"AUTO_{remind_type}_REMIND",
                        username=u,
                        title=title,
                        body=message,
                        status="SENT"
                    )
                    if remind_type == "CHECKIN":
                        results["checkin_sent"] += 1
                    else:
                        results["checkout_sent"] += 1

            # ------------------------------------------------------------------
            # MỐC 1: 05:30 -> 06:15 - NHẮC VÀO CA SÁNG (BẮT ĐẦU 06:00, TRƯỚC 30 PHÚT)
            # ------------------------------------------------------------------
            if "05:30" <= now_hm < "06:15":
                m_users = []
                for role in ["manager", "barista", "service"]:
                    val = m_shift.get(role)
                    if val:
                        m_users.extend(val if isinstance(val, list) else [val])
                for u in m_users:
                    norm_u = normalize_str(u)
                    if norm_u and norm_u not in checked_in_users:
                        _send_remind(
                            username=norm_u,
                            remind_type="CHECKIN",
                            title="WFM - Sắp vào ca làm việc (Ca Sáng 06:00)",
                            message="Bạn có ca làm việc sáng (06:00) hôm nay. Vui lòng chuẩn bị và kết nối WiFi quán để Vào ca đúng giờ nhé!",
                            dedup_key=f"AUTO_CHECKIN_SANG:{today_iso}:{norm_u}"
                        )

            # ------------------------------------------------------------------
            # MỐC 2: 11:45 -> 14:00 - NHẮC CHECK-OUT CA SÁNG (HẾT CA 11:30, SAU 15 PHÚT)
            # ------------------------------------------------------------------
            if "11:45" <= now_hm < "14:00":
                for log in today_logs:
                    if log.get("checkout_time") is None:
                        shift_name = str(log.get("shift_name", "")).lower()
                        c_in = str(log.get("checkin_time", "00:00"))
                        if "sáng" in shift_name or c_in < "12:00":
                            norm_u = normalize_str(log.get("username", ""))
                            if norm_u:
                                _send_remind(
                                    username=norm_u,
                                    remind_type="CHECKOUT",
                                    title="WFM - Nhắc Chốt ca (Ca Sáng)",
                                    message="Ca làm việc sáng (11:30) đã kết thúc. Vui lòng bấm Kết thúc ca trên hệ thống để chốt giờ làm nghen!",
                                    dedup_key=f"AUTO_CHECKOUT_SANG:{today_iso}:{norm_u}"
                                )

            # ------------------------------------------------------------------
            # MỐC 3: 16:30 -> 17:15 - NHẮC VÀO CA TỐI SLOT 17H (TRƯỚC 30 PHÚT)
            # ------------------------------------------------------------------
            if "16:30" <= now_hm < "17:15":
                e_17_users = []
                for role in ["manager", "barista", "service_17"]:
                    val = e_shift.get(role)
                    if val:
                        e_17_users.extend(val if isinstance(val, list) else [val])
                for u in e_17_users:
                    norm_u = normalize_str(u)
                    if norm_u and norm_u not in checked_in_users:
                        _send_remind(
                            username=norm_u,
                            remind_type="CHECKIN",
                            title="WFM - Sắp vào ca làm việc (Ca Tối 17:00)",
                            message="Bạn có ca làm việc tối (17:00) hôm nay. Vui lòng chuẩn bị và kết nối WiFi quán để Vào ca đúng giờ nhé!",
                            dedup_key=f"AUTO_CHECKIN_TOI_17H:{today_iso}:{norm_u}"
                        )

            # ------------------------------------------------------------------
            # MỐC 4: 17:30 -> 18:15 - NHẮC VÀO CA TỐI SLOT 18H (TRƯỚC 30 PHÚT)
            # ------------------------------------------------------------------
            if "17:30" <= now_hm < "18:15":
                e_18_users = []
                val = e_shift.get("service_18")
                if val:
                    e_18_users.extend(val if isinstance(val, list) else [val])
                for u in e_18_users:
                    norm_u = normalize_str(u)
                    if norm_u and norm_u not in checked_in_users:
                        _send_remind(
                            username=norm_u,
                            remind_type="CHECKIN",
                            title="WFM - Sắp vào ca làm việc (Ca Tối 18:00)",
                            message="Bạn có ca làm việc tối (18:00) hôm nay. Vui lòng chuẩn bị và kết nối WiFi quán để Vào ca đúng giờ nhé!",
                            dedup_key=f"AUTO_CHECKIN_TOI_18H:{today_iso}:{norm_u}"
                        )

            # ------------------------------------------------------------------
            # MỐC 5: 23:15 -> 03:00 - NHẮC CHECK-OUT CA TỐI (HẾT CA 23:00, SAU 15 PHÚT)
            # ------------------------------------------------------------------
            if now_hm >= "23:15" or now_hm < "03:00":
                for log in today_logs:
                    if log.get("checkout_time") is None:
                        shift_name = str(log.get("shift_name", "")).lower()
                        c_in = str(log.get("checkin_time", "00:00"))
                        if "tối" in shift_name or c_in >= "15:00":
                            norm_u = normalize_str(log.get("username", ""))
                            if norm_u:
                                _send_remind(
                                    username=norm_u,
                                    remind_type="CHECKOUT",
                                    title="WFM - Nhắc Chốt ca (Ca Tối)",
                                    message="Ca làm việc tối (23:00) đã kết thúc. Vui lòng bấm Kết thúc ca trên hệ thống để chốt giờ làm nghen!",
                                    dedup_key=f"AUTO_CHECKOUT_TOI:{today_iso}:{norm_u}"
                                )

            # ------------------------------------------------------------------
            # 3. SCAN ROSTER REGISTRATION REMINDERS (Friday at 20:00)
            # ------------------------------------------------------------------
            if now.weekday() == 4 and now.hour == 20:
                next_week_id = f"{iso_year}-W{iso_week + 1:02d}"
                dedup_key = f"ROSTER_REGISTER:{next_week_id}"
                if not has_notification_dispatched_db(dedup_key):
                    title = "WFM - Lịch làm việc tuần mới"
                    body = "Cổng đăng ký ca tuần mới đã mở. Vui lòng gửi lịch làm việc tuần trước 12:00 Chủ Nhật!"
                    send_notification_to_all(
                        title=title,
                        body=body,
                        tag="remind-roster-registration",
                        url="/index.html#roster"
                    )
                    record_notification_dispatch_db(
                        dedup_key=dedup_key,
                        notification_type="ROSTER_REGISTER_REMIND",
                        username="ALL_STAFF",
                        title=title,
                        body=body,
                        status="SENT"
                    )
                    results["roster_sent"] += 1

        except Exception as e:
            logger.error(f"Error executing shift reminders scan: {e}")

        return results

    async def _shift_reminder_loop(self) -> None:
        """Periodic task: Watches for shift checkin/checkout/roster conditions every 60s."""
        logger.info("Shift reminders scheduler task started.")
        while not self._stop_event.is_set():
            try:
                res = await asyncio.to_thread(self._execute_shift_reminders)
                self.reminder_runs += 1
                if any(v > 0 for v in res.values()):
                    logger.info(f"Shift reminders cycle #{self.reminder_runs} dispatched: {res}")
            except Exception as e:
                logger.error(f"Error in shift reminders loop: {e}")

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.reminder_check_interval_secs
                )
            except asyncio.TimeoutError:
                pass


_worker_instance: Optional[BackgroundWorker] = None


def get_background_worker() -> BackgroundWorker:
    """Returns singleton instance of BackgroundWorker."""
    global _worker_instance
    if _worker_instance is None:
        _worker_instance = BackgroundWorker()
    return _worker_instance

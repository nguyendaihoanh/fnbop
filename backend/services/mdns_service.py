# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
mDNS Broadcaster Service (FnBOps Standalone)
Tự động quảng bá tên miền nội bộ 'chamcong.local' trỏ về IP mạng LAN của máy POS.
Giúp nhân viên dập thẻ qua http://chamcong.local:8100 ngay cả khi Router đổi IP LAN hoặc mất mạng Internet ngoài.
"""

import os
import sys
import time
import socket
import logging
import threading
from typing import Optional

logger = logging.getLogger("mdns_service")

try:
    from zeroconf import Zeroconf, ServiceInfo, IPVersion
    ZEROCONF_AVAILABLE = True
except ImportError:
    ZEROCONF_AVAILABLE = False
    logger.warning("Thư viện 'zeroconf' chưa được cài đặt. Chức năng mDNS 'chamcong.local' sẽ tạm thời không hoạt động.")


def get_lan_ip() -> str:
    """Lấy IP mạng LAN thực tế của máy POS (192.168.x.x, 10.x.x.x, 172.16.x.x)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Không cần kết nối ra ngoài Internet thật, socket chỉ định tuyến qua gateway mặc định
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


class MDNSBroadcaster:
    """
    Quản lý phát sóng mDNS cho tên miền chamcong.local.
    Tự động cập nhật nếu IP mạng LAN của máy POS bị thay đổi.
    """
    def __init__(self, hostname: str = "chamcong.local", port: int = 8100, check_interval_secs: int = 30):
        self.hostname = hostname.rstrip(".") + "."
        self.port = port
        self.check_interval = check_interval_secs
        self.zc: Optional[Zeroconf] = None
        self.current_info: Optional[ServiceInfo] = None
        self.current_ip: Optional[str] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> bool:
        if not ZEROCONF_AVAILABLE:
            logger.info("[mDNS] Bỏ qua vì không có thư viện zeroconf.")
            return False

        if self._running:
            return True

        self._running = True
        self.zc = Zeroconf(ip_version=IPVersion.V4Only)
        self._register_service()

        # Bật luồng ngầm theo dõi IP thay đổi
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="mdns-monitor")
        self._thread.start()
        logger.info(f"[mDNS] Đã phát sóng tên miền http://{self.hostname}:{self.port} -> {self.current_ip}")
        return True

    def _register_service(self):
        self.current_ip = get_lan_ip()
        service_type = "_http._tcp.local."
        service_name = f"FnBOps Timeclock POS.{service_type}"
        
        self.current_info = ServiceInfo(
            service_type,
            service_name,
            addresses=[socket.inet_aton(self.current_ip)],
            port=self.port,
            properties={"path": "/", "app": "FnBOps"},
            server=self.hostname
        )
        try:
            self.zc.register_service(self.current_info)
        except Exception as e:
            logger.error(f"[mDNS] Lỗi đăng ký service: {e}")

    def _monitor_loop(self):
        while self._running:
            time.sleep(self.check_interval)
            new_ip = get_lan_ip()
            if new_ip != self.current_ip and new_ip != "127.0.0.1":
                logger.info(f"[mDNS] Phát hiện IP LAN thay đổi: {self.current_ip} -> {new_ip}. Đang cập nhật mDNS...")
                try:
                    if self.current_info:
                        self.zc.unregister_service(self.current_info)
                    self._register_service()
                    logger.info(f"[mDNS] Đã cập nhật {self.hostname} trỏ về IP mới: {new_ip}")
                except Exception as e:
                    logger.error(f"[mDNS] Lỗi cập nhật IP mới: {e}")

    def stop(self):
        if not self._running:
            return
        self._running = False
        if self.zc and self.current_info:
            try:
                self.zc.unregister_service(self.current_info)
                self.zc.close()
                logger.info("[mDNS] Đã dừng phát sóng mDNS sạch sẽ.")
            except Exception as e:
                logger.warning(f"[mDNS] Lỗi khi dừng mDNS: {e}")
        self.zc = None
        self.current_info = None


# Global singleton instance
_mdns_broadcaster: Optional[MDNSBroadcaster] = None

def get_mdns_broadcaster() -> MDNSBroadcaster:
    global _mdns_broadcaster
    if _mdns_broadcaster is None:
        _mdns_broadcaster = MDNSBroadcaster()
    return _mdns_broadcaster

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    broadcaster = MDNSBroadcaster()
    broadcaster.start()
    print(f"\n[*] Đang phát sóng mDNS cho tên miền: http://chamcong.local:8100")
    print(f"[*] IP máy POS hiện tại: {broadcaster.current_ip}")
    print("[*] Nhấn Ctrl+C để dừng...\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        broadcaster.stop()
        print("\n[V] Đã dừng mDNS.")

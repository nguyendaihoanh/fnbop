#!/usr/bin/env python3
"""
CLI Script phát sóng mDNS cho máy POS (chamcong.local)
Cách dùng:
    python scripts/pos_mdns_broadcast.py
    python scripts/pos_mdns_broadcast.py --port 8100 --name chamcong.local
"""

import sys
import time
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.mdns_service import MDNSBroadcaster

def main():
    parser = argparse.ArgumentParser(description="Phát sóng tên miền nội bộ mDNS cho máy POS")
    parser.add_argument("--name", default="chamcong.local", help="Tên miền mDNS (mặc định: chamcong.local)")
    parser.add_argument("--port", type=int, default=8100, help="Cổng dịch vụ (mặc định: 8100)")
    parser.add_argument("--interval", type=int, default=30, help="Chu kỳ kiểm tra IP thay đổi (giây)")
    args = parser.parse_args()

    broadcaster = MDNSBroadcaster(hostname=args.name, port=args.port, check_interval_secs=args.interval)
    started = broadcaster.start()

    if not started:
        print("[!] Không thể khởi động mDNS. Vui lòng kiểm tra thư viện 'zeroconf' (pip install zeroconf).")
        sys.exit(1)

    print("=" * 60)
    print(f"[*] Đang phát sóng mDNS: http://{args.name}:{args.port}")
    print(f"[*] IP máy POS hiện tại: {broadcaster.current_ip}")
    print("[*] Nhân viên có thể dập thẻ qua link trên khi chung mạng WiFi.")
    print("[*] Nhấn Ctrl+C để dừng.")
    print("=" * 60)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[*] Đang dừng mDNS...")
        broadcaster.stop()
        print("[V] Đã dừng thành công.")

if __name__ == "__main__":
    main()

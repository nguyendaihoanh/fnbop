#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
FnBOps Core — Native Master Launcher & Process Supervisor (Zero-Docker)
==============================================================================
Dành cho máy khách / máy POS vận hành Native không có Docker / Container:
- Tự động giám sát & phục hồi 2 tiến trình cốt lõi:
    1. FastAPI Core + PWA Frontend Server (Port 8100 hoặc 8100)
    2. Zalo Gateway Microservice zca-js (Port 8177, RAM < 60MB)
- Tự động khởi động lại (Auto-restart Watchdog) nếu Zalo Gateway bị tắt bất ngờ
- Dọn dẹp tiến trình con sạch sẽ (Graceful Shutdown) khi tắt ứng dụng
- Tự động mở trình duyệt Web PWA trên máy POS
==============================================================================
"""

import os
import sys

# Ensure UTF-8 output on all operating systems and Windows console codepages
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import time
import signal
import socket
import webbrowser
import subprocess
from pathlib import Path

# Resolve base directories
_curr = Path(__file__).resolve().parent
if (_curr / "backend").exists():
    ROOT_DIR = _curr
elif (_curr.parent.parent / "backend").exists():
    ROOT_DIR = _curr.parent.parent
elif (_curr.parent / "backend").exists():
    ROOT_DIR = _curr.parent
else:
    ROOT_DIR = _curr
BACKEND_DIR = ROOT_DIR / "backend"
FRONTEND_DIR = ROOT_DIR / "frontend"
ZALO_DIR = BACKEND_DIR / "zalo_gateway"
DATA_DIR = ROOT_DIR / "data"
SESSION_DIR = DATA_DIR / "zalo_session"

APP_PORT = int(os.getenv("FASTAPI_PORT", os.getenv("PORT", "8100")))
ZALO_PORT = int(os.getenv("ZALO_GATEWAY_PORT", "8177"))

# Ensure vital data directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
SESSION_DIR.mkdir(parents=True, exist_ok=True)
(DATA_DIR / "outbox" / "pdf").mkdir(parents=True, exist_ok=True)

class NativeSupervisor:
    def __init__(self):
        self.backend_proc = None
        self.zalo_proc = None
        self.running = True
        self.backend_restart_count = 0
        self.zalo_restart_count = 0

    def is_port_in_use(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex(("127.0.0.1", port)) == 0

    def start_backend(self):
        """Khởi chạy FastAPI Server (tự serve cả PWA Frontend)"""
        print(f"[*] [BACKEND] Dang khoi chay FastAPI Backend tren cong {APP_PORT}...")
        env = os.environ.copy()
        env["FASTAPI_PORT"] = str(APP_PORT)
        env["PORT"] = str(APP_PORT)
        env["ZALO_GATEWAY_URL"] = f"http://127.0.0.1:{ZALO_PORT}"
        env["ON_PREMISE_MODE"] = "true"
        env["DATA_DIR"] = str(DATA_DIR)
        if not env.get("JWT_SECRET_KEY"):
            import secrets
            env["JWT_SECRET_KEY"] = secrets.token_hex(32)

        cmd = [
            sys.executable, "-m", "uvicorn", "main:app",
            "--host", "0.0.0.0",
            "--port", str(APP_PORT),
            "--log-level", "warning"
        ]
        self.backend_proc = subprocess.Popen(
            cmd,
            cwd=str(BACKEND_DIR),
            env=env
        )
        print(f"    [OK] [BACKEND] PID: {self.backend_proc.pid}")

    def start_zalo_gateway(self):
        """Khởi chạy Zalo Gateway microservice (Node.js zca-js) nếu có sẵn Node.js và dependencies"""
        import shutil
        if not shutil.which("node"):
            print("[i] [ZALO] Bo qua Zalo Gateway: Khong tim thay Node.js (Core FastAPI chay doc lap hoan toan).")
            self.zalo_proc = None
            return

        server_js = ZALO_DIR / "server.js"
        if not server_js.exists() or not (ZALO_DIR / "node_modules").exists():
            print("[i] [ZALO] Bo qua Zalo Gateway: Thieu thu muc node_modules.")
            self.zalo_proc = None
            return

        print(f"[*] [ZALO] Dang khoi chay Zalo Gateway tren cong {ZALO_PORT}...")
        env = os.environ.copy()
        env["PORT"] = str(ZALO_PORT)
        env["ZALO_GATEWAY_PORT"] = str(ZALO_PORT)
        env["SESSION_DIR"] = str(SESSION_DIR)

        cmd = ["node", "--max-old-space-size=64", str(server_js)]
        try:
            self.zalo_proc = subprocess.Popen(
                cmd,
                cwd=str(ZALO_DIR),
                env=env
            )
            print(f"    [OK] [ZALO] PID: {self.zalo_proc.pid} (Gioi han RAM: < 60MB)")
        except Exception as e:
            print(f"[!] [ZALO] Khong the khoi chay Zalo Gateway: {e}")
            self.zalo_proc = None

    def shutdown(self, signum=None, frame=None):
        """Dọn dẹp sạch sẽ cả 2 tiến trình khi người dùng tắt"""
        print("\n[*] Dang dung toan bo dich vu an toan...")
        self.running = False

        if self.backend_proc:
            try:
                self.backend_proc.terminate()
                self.backend_proc.wait(timeout=3)
            except Exception:
                try: self.backend_proc.kill()
                except Exception: pass
            print("    [OK] Da dung FastAPI Backend")

        if self.zalo_proc:
            try:
                self.zalo_proc.terminate()
                self.zalo_proc.wait(timeout=3)
            except Exception:
                try: self.zalo_proc.kill()
                except Exception: pass
            print("    [OK] Da dung Zalo Gateway")

        print("[OK] He thong da tat hoan tat.")
        sys.exit(0)

    def run(self):
        print("====================================================================")
        print("    [FnBOps] Core - On-Premise Stack")
        print("====================================================================")
        print(f" * Thu muc goc:    {ROOT_DIR}")
        print(f" * Giao dien Web:   http://localhost:{APP_PORT}")
        print(f" * Zalo Gateway:    http://localhost:{ZALO_PORT}")
        print(f" * Che do:          Native Process Watchdog")
        print("====================================================================\n")

        # Đăng ký signal handler để không bao giờ để lại tiến trình mồ côi
        signal.signal(signal.SIGINT, self.shutdown)
        signal.signal(signal.SIGTERM, self.shutdown)

        # 1. Khởi chạy Zalo Gateway
        self.start_zalo_gateway()
        time.sleep(1)

        # 2. Khởi chạy Backend
        self.start_backend()
        
        # Đợi backend khởi động và bind port thành công (tối đa 20 giây)
        print(f"[*] Dang doi Backend khoi dong tren cong {APP_PORT}...")
        for _ in range(40):
            if self.is_port_in_use(APP_PORT):
                break
            time.sleep(0.5)

        # 3. Mở trình duyệt Web PWA cho chủ quán
        if self.is_port_in_use(APP_PORT):
            print(f"[OK] Backend da san sang tai http://localhost:{APP_PORT}")
            try:
                webbrowser.open(f"http://localhost:{APP_PORT}")
            except Exception:
                pass
        else:
            print(f"[!] Backend chua san sang sau 20 giay. Vui long kiem tra lai.")
            pass

        print(f"\n[OK] HE THONG DA SAN SANG! Dang giam sat...")
        print("    (Bam Ctrl+C bat ky luc nao de dung an toan)\n")

        # 4. Vòng lặp Watchdog giám sát tự phục hồi
        while self.running:
            time.sleep(3)

            # Kiểm tra Zalo Gateway: Giới hạn tối đa 3 lần thử
            if self.zalo_proc and self.zalo_proc.poll() is not None:
                self.zalo_restart_count += 1
                exit_code = self.zalo_proc.returncode
                if self.zalo_restart_count <= 3:
                    print(f"[!] [CANH BAO] Zalo Gateway bi tat (Exit: {exit_code})! Watchdog dang thu khoi dong lai ({self.zalo_restart_count}/3)...")
                    time.sleep(1)
                    self.start_zalo_gateway()
                else:
                    print("[!] [ZALO] Da thu khoi dong lai 3 lan khong thanh cong. Da vo hieu hoa Zalo Gateway.")
                    self.zalo_proc = None

            # Kiểm tra Backend: Nếu chết bất ngờ -> Tự khởi động lại ngay
            if self.backend_proc and self.backend_proc.poll() is not None:
                self.backend_restart_count += 1
                exit_code = self.backend_proc.returncode
                print(f"[!] [CANH BAO] Backend bi tat (Exit: {exit_code})! Watchdog dang tu khoi dong lai lan {self.backend_restart_count}...")
                time.sleep(1)
                self.start_backend()

if __name__ == "__main__":
    supervisor = NativeSupervisor()
    supervisor.run()

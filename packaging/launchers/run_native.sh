#!/usr/bin/env bash
# ==============================================================================
# FnBOps - SCRIPT KHỞI ĐỘNG NATIVE 1-CHẠM (CHO MACOS / LINUX KHÔNG DÙNG DOCKER)
# Khởi chạy FastAPI Backend + Zalo Gateway Microservice kèm Process Watchdog
# ==============================================================================

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "===================================================================="
echo "    ☕ FnBOps Core — On-Premise Stack"
echo "===================================================================="

# 1. Kiểm tra Python
if ! command -v python3 &>/dev/null; then
    echo "[LỖI] Không tìm thấy python3 trên máy tính này!"
    exit 1
fi

# 2. Kiểm tra Node.js
if ! command -v node &>/dev/null; then
    echo "[LỖI] Không tìm thấy node trên máy tính này!"
    exit 1
fi

# 3. Kiểm tra dependencies của Zalo Gateway
if [ ! -d "backend/zalo_gateway/node_modules" ]; then
    echo "[*] Lần đầu chạy: Đang cài đặt thư viện cho Zalo Gateway..."
    (cd backend/zalo_gateway && npm install --omit=dev --no-audit --no-fund)
    echo "[✓] Đã cài xong thư viện Zalo Gateway!"
fi

# 4. Khởi chạy Master Supervisor Watchdog
echo "[*] Đang khởi chạy hệ thống Native kèm bộ giám sát tự phục hồi..."
exec python3 run_native.py

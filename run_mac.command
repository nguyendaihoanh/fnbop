#!/usr/bin/env bash
# ==============================================================================
# FnBOps - Trình Khởi Động 1-Click Dành Cho macOS
# Nhấp đúp chuột vào file này để khởi chạy toàn bộ hệ thống!
# ==============================================================================

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "======================================================="
echo "   FnBOps / WFM — HỆ ĐIỀU HÀNH VẬN HÀNH F&B & WORKFORCE (MÃ NGUỒN MỞ)"
echo "======================================================="
echo "📁 Thư mục làm việc: $DIR"

# 1. Kiểm tra Python 3
if ! command -v python3 &>/dev/null; then
    echo "❌ Lỗi: Máy của bạn chưa cài đặt Python 3."
    echo "Vui lòng mở Terminal và chạy: brew install python@3.12"
    echo "Nhấn phím bất kỳ để thoát..."
    read -n 1
    exit 1
fi

# 2. Khởi tạo hoặc kiểm tra Virtualenv & Dependencies
VENV_DIR="$DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "⚙️ Đang khởi tạo môi trường Python ảo (.venv)..."
    python3 -m venv "$VENV_DIR"
fi

if ! "$VENV_DIR/bin/python3" -c "import fastapi, uvicorn, pydantic" &>/dev/null; then
    echo "📦 Đang cài đặt / đồng bộ thư viện cần thiết..."
    "$VENV_DIR/bin/pip" install --quiet --upgrade pip
    if [ -f "$DIR/requirements.txt" ]; then
        "$VENV_DIR/bin/pip" install --quiet -r "$DIR/requirements.txt"
    elif [ -f "$DIR/backend/requirements.txt" ]; then
        "$VENV_DIR/bin/pip" install --quiet -r "$DIR/backend/requirements.txt"
    fi
fi

# 3. Tạo các thư mục dữ liệu cần thiết
mkdir -p "$DIR/data/logs"
mkdir -p "$DIR/data/backups"
mkdir -p "$DIR/data/outbox/pdf"

# Tự động tạo .env từ .env.example nếu chưa có
if [ ! -f "$DIR/.env" ] && [ -f "$DIR/.env.example" ]; then
    echo "📄 Chưa tìm thấy file .env, tự động khởi tạo từ .env.example..."
    cp "$DIR/.env.example" "$DIR/.env"
fi

# 4. Xác định cổng chạy (mặc định 8100)
PORT=${FASTAPI_PORT:-${PORT:-8100}}

echo "🚀 Đang khởi động FnBOps Server tại http://localhost:$PORT ..."

# Mở trình duyệt web tự động sau 2 giây
(sleep 2 && open "http://localhost:$PORT") &

# Chạy server FastAPI
exec "$VENV_DIR/bin/python3" -m uvicorn backend.main:app --host 0.0.0.0 --port "$PORT"

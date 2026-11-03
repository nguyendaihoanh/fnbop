#!/usr/bin/env bash
# ==============================================================================
# FnBOps On-Premise - macOS 1-Click Installer & Auto-Start Daemon
# Port: 8100 | Target: FnBOps Standalone FOSS Server
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PLIST_NAME="io.fnbops.server.plist"
OLD_PLIST_NAME="com.vnaigc.wfmops.plist"
USER_LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
TARGET_PLIST="$USER_LAUNCH_AGENTS/$PLIST_NAME"
PORT=${FASTAPI_PORT:-${PORT:-8100}}

echo "======================================================="
echo "   FnBOps — BẢN CÀI ĐẶT ON-PREMISE ĐỘC LẬP MACOS"
echo "======================================================="
echo "📁 Thư mục ứng dụng: $APP_DIR"

# 1. Kiểm tra Python 3
if ! command -v python3 &>/dev/null; then
    echo "❌ Lỗi: Không tìm thấy Python 3 trên máy của bạn."
    echo "Vui lòng cài đặt qua: brew install python@3.12"
    exit 1
fi

# 2. Tạo hoặc kiểm tra Virtualenv
VENV_DIR="$APP_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "⚙️ Đang khởi tạo môi trường Python ảo (.venv)..."
    python3 -m venv "$VENV_DIR"
fi

echo "📦 Đang cài đặt thư viện phụ thuộc..."
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
if [ -f "$APP_DIR/requirements.txt" ]; then
    "$VENV_DIR/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
elif [ -f "$APP_DIR/backend/requirements.txt" ]; then
    "$VENV_DIR/bin/pip" install --quiet -r "$APP_DIR/backend/requirements.txt"
fi

# 3. Tạo thư mục data/logs
mkdir -p "$APP_DIR/data/logs"
mkdir -p "$APP_DIR/data/outbox/pdf"
mkdir -p "$APP_DIR/data/backups"

# 4. Sinh file plist với đường dẫn động chính xác theo máy của người dùng
mkdir -p "$USER_LAUNCH_AGENTS"

# Gỡ bỏ plist cũ nếu có
launchctl unload "$USER_LAUNCH_AGENTS/$OLD_PLIST_NAME" 2>/dev/null || true
rm -f "$USER_LAUNCH_AGENTS/$OLD_PLIST_NAME"

cat <<EOF > "$TARGET_PLIST"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>io.fnbops.server</string>

    <key>ProgramArguments</key>
    <array>
        <string>$VENV_DIR/bin/python3</string>
        <string>-m</string>
        <string>uvicorn</string>
        <string>backend.main:app</string>
        <string>--host</string>
        <string>0.0.0.0</string>
        <string>--port</string>
        <string>$PORT</string>
    </array>

    <key>WorkingDirectory</key>
    <string>$APP_DIR</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>$APP_DIR/data/logs/fnbops.log</string>

    <key>StandardErrorPath</key>
    <string>$APP_DIR/data/logs/fnbops_error.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PORT</key>
        <string>$PORT</string>
        <key>FASTAPI_PORT</key>
        <string>$PORT</string>
        <key>HOST</key>
        <string>0.0.0.0</string>
        <key>ON_PREMISE_MODE</key>
        <string>true</string>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
EOF

# 5. Đăng ký LaunchAgent
echo "🚀 Đang kích hoạt tiến trình chạy ngầm cùng macOS..."
launchctl unload "$TARGET_PLIST" 2>/dev/null || true
launchctl load -w "$TARGET_PLIST"

# 6. Lấy địa chỉ IP mạng nội bộ
LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "127.0.0.1")

echo "======================================================="
echo "✅ CÀI ĐẶT THÀNH CÔNG!"
echo "• Dịch vụ tự khởi động cùng macOS khi mở máy."
echo "• Truy cập tại máy quán: http://localhost:$PORT"
echo "• Nhân viên dập thẻ qua WiFi: http://$LOCAL_IP:$PORT"
echo "• File nhật ký theo dõi: $APP_DIR/data/logs/fnbops.log"
echo "======================================================="

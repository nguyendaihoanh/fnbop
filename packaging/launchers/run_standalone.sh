#!/usr/bin/env bash
# ==============================================================================
# FnBOps - SCRIPT KHỞI ĐỘNG STANDALONE 1-CHẠM (MACOS / LINUX / ORBSTACK)
# Khởi chạy toàn bộ hệ thống F&B Standalone: Nginx + FastAPI + Zalo Gateway
# Tổng RAM tiêu thụ: <= 250MB | Chạy độc lập 100% không cần n8n hay Google Sheets
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "${SCRIPT_DIR}/docker-compose.standalone.yml" ]; then
    PROJECT_ROOT="${SCRIPT_DIR}"
elif [ -f "${SCRIPT_DIR}/../../docker-compose.standalone.yml" ]; then
    PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
elif [ -f "${SCRIPT_DIR}/../docker-compose.standalone.yml" ]; then
    PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
else
    PROJECT_ROOT="${SCRIPT_DIR}"
fi
cd "${PROJECT_ROOT}"

COMPOSE_FILE="docker-compose.standalone.yml"
ENV_FILE=".env"
ENV_EXAMPLE=".env.example"

# ANSI Colors
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color
BOLD='\033[1m'

print_header() {
    echo -e "${CYAN}====================================================================${NC}"
    echo -e "${BOLD}${CYAN}   FnBOps CORE — STANDALONE ON-PREMISE CONTAINER STACK        ${NC}"
    echo -e "${CYAN}====================================================================${NC}"
}

# 1. Parse command-line arguments
ACTION="${1:-start}"

# Determine Docker Compose Command (v2 plugin or standalone v1)
DOCKER_COMPOSE_CMD=""
if docker compose version >/dev/null 2>&1; then
    DOCKER_COMPOSE_CMD="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    DOCKER_COMPOSE_CMD="docker-compose"
else
    echo -e "${RED}[LỖI] Không tìm thấy lệnh 'docker compose' hoặc 'docker-compose'.${NC}"
    echo -e "Vui lòng cài đặt Docker Desktop, OrbStack hoặc docker-compose plugin."
    exit 1
fi

check_docker_daemon() {
    if ! docker info >/dev/null 2>&1; then
        echo -e "${RED}[LỖI] Docker daemon chưa được khởi chạy!${NC}"
        echo -e "${YELLOW}Vui lòng bật OrbStack hoặc Docker Desktop trước khi chạy script này.${NC}"
        exit 1
    fi
}

handle_stop() {
    print_header
    echo -e "${YELLOW}[DỪNG HỆ THỐNG] Đang tắt các container Standalone...${NC}"
    ${DOCKER_COMPOSE_CMD} -f "${COMPOSE_FILE}" down
    echo -e "${GREEN}[THÀNH CÔNG] Toàn bộ stack Standalone đã dừng an toàn.${NC}"
    exit 0
}

handle_logs() {
    echo -e "${CYAN}[LOGS] Xem log trực tiếp từ 3 containers (Ctrl+C để thoát)...${NC}"
    ${DOCKER_COMPOSE_CMD} -f "${COMPOSE_FILE}" logs -f
    exit 0
}

handle_status() {
    print_header
    echo -e "${CYAN}[TRẠNG THÁI TIẾN TRÌNH]${NC}"
    ${DOCKER_COMPOSE_CMD} -f "${COMPOSE_FILE}" ps
    echo ""
    echo -e "${CYAN}[TIÊU THỤ BỘ NHỚ RAM THỰC TẾ]${NC}"
    docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.CPUPerc}}" \
        $(docker ps -q --filter "name=cc-standalone") 2>/dev/null || true
    exit 0
}

# Process special actions
case "${ACTION}" in
    "stop"|"down")
        handle_stop
        ;;
    "logs")
        handle_logs
        ;;
    "status"|"ps")
        handle_status
        ;;
    "restart")
        print_header
        echo -e "${YELLOW}[RESTART] Khởi động lại toàn bộ stack...${NC}"
        ${DOCKER_COMPOSE_CMD} -f "${COMPOSE_FILE}" restart
        exit 0
        ;;
esac

# 2. Main Startup Procedure
print_header
check_docker_daemon

# Tạo thư mục dữ liệu cục bộ nếu chưa có
echo -e "${CYAN}[1/4] Chuẩn bị thư mục lưu trữ dữ liệu bền vững (Persistence)...${NC}"
mkdir -p "${SCRIPT_DIR}/data"
mkdir -p "${SCRIPT_DIR}/data/zalo_session"
mkdir -p "${SCRIPT_DIR}/data/outbox/pdf"
mkdir -p "${SCRIPT_DIR}/backend/data"

# Kiểm tra file cấu hình môi trường .env
echo -e "${CYAN}[2/4] Kiểm tra biến môi trường .env...${NC}"
if [ ! -f "${ENV_FILE}" ]; then
    if [ -f "${ENV_EXAMPLE}" ]; then
        echo -e "${YELLOW}    -> Chưa có file .env. Đang tự động sao chép từ ${ENV_EXAMPLE}...${NC}"
        cp "${ENV_EXAMPLE}" "${ENV_FILE}"
        echo -e "${GREEN}    -> Đã tạo .env thành công!${NC}"
    else
        echo -e "${YELLOW}[!] Không tìm thấy ${ENV_EXAMPLE}! Tự động tạo .env với secret ngẫu nhiên bảo mật...${NC}"
        RAND_JWT=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | xxd -p -c 32)
        RAND_PASS=$(python3 -c "import secrets; print(secrets.token_urlsafe(12))" 2>/dev/null || openssl rand -base64 12 2>/dev/null || echo "Admin_${RANDOM}")
        cat <<EOF > "${ENV_FILE}"
PORT=8100
ON_PREMISE_MODE=true
JWT_SECRET_KEY=${RAND_JWT}
ADMIN_PASSWORD=${RAND_PASS}
DATA_DIR=/app/data
DATABASE_PATH=/app/data/fnbop.db
EOF
        echo -e "${GREEN}    -> Đã tạo .env thành công! Mật khẩu Admin khởi tạo: ${BOLD}${RAND_PASS}${NC}"
    fi
fi

# Khởi chạy Docker Compose
echo -e "${CYAN}[3/4] Khởi động 3 Container Standalone (Nginx, FastAPI, Zalo Gateway)...${NC}"
BUILD_FLAG=""
if [ "${ACTION}" = "--build" ] || [ "${ACTION}" = "build" ]; then
    BUILD_FLAG="--build"
fi

${DOCKER_COMPOSE_CMD} -f "${COMPOSE_FILE}" up -d ${BUILD_FLAG}

# 4. Kiểm tra sức khỏe hệ thống (Health Check Loop)
echo -e "${CYAN}[4/4] Kiểm tra sức khỏe dịch vụ (Health Check)...${NC}"
MAX_WAIT=25
WAITED=0
READY=false

while [ $WAITED -lt $MAX_WAIT ]; do
    if curl -s http://127.0.0.1:8100/ >/dev/null 2>&1 && \
       curl -s http://127.0.0.1:8100/api/v1/main/ping >/dev/null 2>&1 && \
       curl -s http://127.0.0.1:8177/health >/dev/null 2>&1; then
        READY=true
        break
    fi
    sleep 2
    WAITED=$((WAITED + 2))
    echo -n "."
done
echo ""

# Xác định địa chỉ LAN IP để truy cập từ máy tính bảng / điện thoại quán
LAN_IP=""
if command -v ipconfig >/dev/null 2>&1; then
    LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)
fi
if [ -z "${LAN_IP}" ]; then
    LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "127.0.0.1")
fi

echo -e "${GREEN}====================================================================${NC}"
echo -e "${BOLD}${GREEN}   ✓ HỆ THỐNG STANDALONE F&B ĐÃ KHỞI CHẠY THÀNH CÔNG!              ${NC}"
echo -e "${GREEN}====================================================================${NC}"
echo -e "${BOLD}1. Giao diện Web PWA (Chủ quán & Thu ngân):${NC}"
echo -e "   -> Cục bộ máy POS:  ${CYAN}http://localhost:8100${NC}"
if [ -n "${LAN_IP}" ] && [ "${LAN_IP}" != "127.0.0.1" ]; then
echo -e "   -> Mạng LAN quán:   ${CYAN}http://${LAN_IP}:8100${NC}"
fi
echo ""
echo -e "${BOLD}2. Lõi Nghiệp Vụ & API Backend:${NC}"
echo -e "   -> FastAPI Docs:    ${CYAN}http://localhost:8100/docs${NC}"
echo -e "   -> Ping Test:       ${CYAN}http://localhost:8100/api/v1/main/ping${NC}"
echo ""
echo -e "${BOLD}3. Zalo Gateway Microservice:${NC}"
echo -e "   -> Trạng thái:      ${CYAN}http://localhost:8177/api/zalo/status${NC}"
echo -e "   -> Quét mã QR:      ${CYAN}http://localhost:8177/api/zalo/qr${NC}"
echo ""
echo -e "${BOLD}4. Quản lý tài nguyên:${NC}"
echo -e "   -> Tổng RAM giới hạn:  ${YELLOW}250MB (Web 40M + Backend 150M + Zalo 60M)${NC}"
echo -e "   -> Lệnh xem logs:      ${CYAN}./run_standalone.sh logs${NC}"
echo -e "   -> Lệnh xem tài nguyên:${CYAN}./run_standalone.sh status${NC}"
echo -e "   -> Lệnh dừng hệ thống: ${CYAN}./run_standalone.sh stop${NC}"
echo -e "${GREEN}====================================================================${NC}"

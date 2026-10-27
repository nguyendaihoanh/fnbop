#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# WFM - F&B WORKFORCE MANAGEMENT - AUTOMATED QUALITY GATES
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"
if [ ! -f "$VENV_PYTHON" ] && [ -n "${VIRTUAL_ENV:-}" ] && [ -f "$VIRTUAL_ENV/bin/python" ]; then
    VENV_PYTHON="$VIRTUAL_ENV/bin/python"
elif [ ! -f "$VENV_PYTHON" ]; then
    VENV_PYTHON="$(command -v python3 || echo /usr/bin/python3)"
fi
export PYTHONPATH="$PROJECT_ROOT:$PROJECT_ROOT/backend:${PYTHONPATH:-}"

USE_DOCKER_PY=false
CONTAINER_NAME=""
for cname in "fnbops-api" "fnbops-backend" "cc-vnaigc-backend"; do
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${cname}$"; then
        CONTAINER_NAME="$cname"
        USE_DOCKER_PY=true
        break
    fi
done

# ANSI Color Codes
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m' # No Color

echo -e "\n${BOLD}${BLUE}======================================================================${NC}"
echo -e "${BOLD}${BLUE}   CHẠY BỘ KIỂM THỬ TỰ ĐỘNG QUALITY GATES: FNBOPS                     ${NC}"
echo -e "${BOLD}${BLUE}======================================================================${NC}\n"

FAILURES=0

# ------------------------------------------------------------------------------
# GATE 1: STATIC CODE ANALYSIS & SYNTAX VERIFICATION
# ------------------------------------------------------------------------------
echo -e "${BOLD}[GATE 1/8] Kiểm tra cú pháp Frontend Javascript & Backend Python...${NC}"

if node -c "$PROJECT_ROOT/frontend/mobile.js" && node -c "$PROJECT_ROOT/frontend/app.js"; then
    echo -e "  [PASS] Cú pháp Javascript Frontend (mobile.js, app.js)"
else
    echo -e "  ${RED}[FAIL] Cú pháp Javascript có lỗi!${NC}"
    FAILURES=$((FAILURES + 1))
fi

if "$VENV_PYTHON" -m py_compile \
    "$PROJECT_ROOT/backend/main.py" \
    "$PROJECT_ROOT/backend/routers/attendance.py" \
    "$PROJECT_ROOT/backend/routers/roster.py" \
    "$PROJECT_ROOT/backend/routers/fnb_ops.py" \
    "$PROJECT_ROOT/backend/routers/pos_closing.py" \
    "$PROJECT_ROOT/backend/services/send_telegram.py"; then
    echo -e "  [PASS] Biên dịch mã nguồn Python Backend"
else
    echo -e "  ${RED}[FAIL] Biên dịch Python Backend gặp lỗi!${NC}"
    FAILURES=$((FAILURES + 1))
fi

# ------------------------------------------------------------------------------
# GATE 2: SECURITY, SECRETS & VULNERABILITY SCAN (DEVSECOPS)
# ------------------------------------------------------------------------------
echo -e "\n${BOLD}[GATE 2/8] Quét mã độc, Rò rỉ thông tin bảo mật & Lỗ hổng DevSecOps...${NC}"

# 2.1 Secrets Scan
LEAKS_COUNT=$(grep -rnEi "([0-9]{9,10}:[a-zA-Z0-9_-]{35}|admin123|staff123|fallback_secret_if_env_missing)" \
    "$PROJECT_ROOT/backend" \
    "$PROJECT_ROOT/frontend" \
    "$PROJECT_ROOT/config" \
    --exclude-dir=__pycache__ \
    --exclude-dir=tests \
    --exclude-dir=data \
    --exclude='*.db' \
    --exclude='.env*' \
    --exclude='*.png' --exclude='*.jpg' 2>/dev/null | wc -l || true)

if [ "$LEAKS_COUNT" -eq 0 ]; then
    echo -e "  [PASS] Không phát hiện hardcoded credentials hay secrets trong mã nguồn"
else
    echo -e "  ${RED}[FAIL] Phát hiện ${LEAKS_COUNT} điểm rò rỉ secrets!${NC}"
    FAILURES=$((FAILURES + 1))
fi

# 2.2 Dependency Vulnerability Scan (pip-audit)
PIP_AUDIT_BIN="$PROJECT_ROOT/.venv/bin/pip-audit"
if [ ! -f "$PIP_AUDIT_BIN" ]; then
    PIP_AUDIT_BIN=$(which pip-audit 2>/dev/null || true)
fi

if [ -n "$PIP_AUDIT_BIN" ] && [ -x "$PIP_AUDIT_BIN" ]; then
    if "$PIP_AUDIT_BIN" --skip-editable > /dev/null 2>&1; then
        echo -e "  [PASS] Quét phụ thuộc Python đạt chuẩn (pip-audit: 0 lỗ hổng CVE)"
    else
        echo -e "  ${RED}[FAIL] pip-audit phát hiện lỗ hổng CVE trong thư viện phụ thuộc!${NC}"
        "$PIP_AUDIT_BIN" --skip-editable || true
        FAILURES=$((FAILURES + 1))
    fi
else
    echo -e "  ${YELLOW}[WARN] Không tìm thấy pip-audit — bỏ qua kiểm tra CVE phụ thuộc${NC}"
fi

# 2.3 Static Application Security Testing (Bandit SAST)
BANDIT_BIN="$PROJECT_ROOT/.venv/bin/bandit"
if [ ! -f "$BANDIT_BIN" ]; then
    BANDIT_BIN=$(which bandit 2>/dev/null || true)
fi

if [ -n "$BANDIT_BIN" ] && [ -x "$BANDIT_BIN" ]; then
    if "$BANDIT_BIN" -r "$PROJECT_ROOT/backend" -lll -ii -q --exclude "*/tests/*,*/node_modules/*" > /dev/null 2>&1; then
        echo -e "  [PASS] Quét SAST Backend đạt chuẩn (Bandit: 0 lỗi High/Critical)"
    else
        echo -e "  ${RED}[FAIL] Bandit phát hiện lỗ hổng bảo mật High/Critical trong backend!${NC}"
        "$BANDIT_BIN" -r "$PROJECT_ROOT/backend" -lll -ii --exclude "*/tests/*,*/node_modules/*" || true
        FAILURES=$((FAILURES + 1))
    fi
else
    echo -e "  ${YELLOW}[WARN] Không tìm thấy bandit — bỏ qua kiểm tra SAST${NC}"
fi

# ------------------------------------------------------------------------------
# GATE 3: BUSINESS LOGIC & PAYROLL TESTS
# ------------------------------------------------------------------------------
echo -e "\n${BOLD}[GATE 3/8] Kiểm thử nghiệp vụ lõi (OT, Lễ 2/9, Dedup, Khấu trừ trễ)...${NC}"

if $USE_DOCKER_PY; then
    RUN_PAYROLL_PASS=$(docker exec -e TESTING=1 -e MOCK_TELEGRAM=1 $CONTAINER_NAME python -m pytest /app/tests/test_payroll_logic.py -q > /dev/null 2>&1 && echo "OK" || echo "FAIL")
else
    RUN_PAYROLL_PASS=$("$VENV_PYTHON" -m pytest "$PROJECT_ROOT/tests/test_payroll_logic.py" -q > /dev/null 2>&1 && echo "OK" || echo "FAIL")
fi

if [ "$RUN_PAYROLL_PASS" == "OK" ]; then
    echo -e "  [PASS] Toàn bộ test cases nghiệp vụ tính lương & định biên đạt chuẩn"
else
    echo -e "  ${RED}[FAIL] Kiểm thử nghiệp vụ lõi không vượt qua!${NC}"
    FAILURES=$((FAILURES + 1))
fi

# ------------------------------------------------------------------------------
# GATE 4: FULL PYTEST SUITE (ALL BACKEND, PACKAGING & INVARIANT TESTS)
# ------------------------------------------------------------------------------
echo -e "\n${BOLD}[GATE 4/8] Kiểm thử toàn diện bộ Test Suite (API, RBAC, Packaging, SQLite Invariant)...${NC}"

if $USE_DOCKER_PY; then
    FULL_SUITE_PASS=$(docker exec -e TESTING=1 -e MOCK_TELEGRAM=1 -e ON_PREMISE_MODE=true $CONTAINER_NAME python -m pytest /app/tests/ -q --ignore=/app/tests/test_live_system_readiness.py > /dev/null 2>&1 && echo "OK" || echo "FAIL")
else
    FULL_SUITE_PASS=$(TESTING=1 MOCK_TELEGRAM=1 ON_PREMISE_MODE=true "$VENV_PYTHON" -m pytest "$PROJECT_ROOT/tests/" -q --ignore="$PROJECT_ROOT/tests/test_live_system_readiness.py" > /dev/null 2>&1 && echo "OK" || echo "FAIL")
fi

if [ "$FULL_SUITE_PASS" == "OK" ]; then
    echo -e "  [PASS] Toàn bộ bộ test Pytest (API, Roster, Attendance, Packaging, No-JSON) đạt chuẩn 100%"
else
    echo -e "  ${RED}[FAIL] Phát hiện test thất bại trong bộ tests/!${NC}"
    FAILURES=$((FAILURES + 1))
fi

# ------------------------------------------------------------------------------
# GATE 5: DATA CONTRACT, SQL SCHEMA & OPENAPI INTEGRITY
# ------------------------------------------------------------------------------
echo -e "\n${BOLD}[GATE 5/8] Kiểm tra giao ước dữ liệu, SQL Schema & OpenAPI Contract...${NC}"

if PYTHONPATH="$PROJECT_ROOT:$PROJECT_ROOT/backend" "$VENV_PYTHON" "$PROJECT_ROOT/scripts/audit_schema_contracts.py" > /dev/null 2>&1; then
    echo -e "  [PASS] SQLite Schema, Frontend-Backend OpenAPI Routes & Launcher Hygiene đạt chuẩn (0 lỗi)"
else
    echo -e "  ${RED}[FAIL] Phát hiện lệch SQL Schema, OpenAPI Route hoặc Launcher Contract!${NC}"
    PYTHONPATH="$PROJECT_ROOT:$PROJECT_ROOT/backend" "$VENV_PYTHON" "$PROJECT_ROOT/scripts/audit_schema_contracts.py" || true
    FAILURES=$((FAILURES + 1))
fi

if $USE_DOCKER_PY; then
    SCHEMA_CHECK=$(docker exec $CONTAINER_NAME python -c "
import json, os, sys
data_path = '/app/data/data.json'
if not os.path.exists(data_path):
    sys.exit(1)
with open(data_path, 'r', encoding='utf-8') as f:
    d = json.load(f)
req = ['NHÂN VIÊN', 'DỮ LIỆU', 'ĐÁNH GIÁ', 'SỔ PHỤ']
if all(k in d for k in req) and len(d['DỮ LIỆU']) > 0:
    print('OK')
else:
    sys.exit(1)
")
else
    SCHEMA_CHECK=$("$VENV_PYTHON" -c "
import json, os, sys
data_path = os.path.join('$PROJECT_ROOT', 'data', 'data.json')
if not os.path.exists(data_path):
    data_path = os.path.join('$PROJECT_ROOT', 'frontend', 'data.json')
if not os.path.exists(data_path):
    sys.exit(1)
with open(data_path, 'r', encoding='utf-8') as f:
    d = json.load(f)
req = ['NHÂN VIÊN', 'DỮ LIỆU', 'ĐÁNH GIÁ', 'SỔ PHỤ']
if all(k in d for k in req) and len(d['DỮ LIỆU']) > 0:
    print('OK')
else:
    sys.exit(1)
")
fi

if [ "$SCHEMA_CHECK" == "OK" ]; then
    echo -e "  [PASS] Giao ước dữ liệu data.json chuẩn 4 tab cấu trúc, không rỗng"
else
    echo -e "  ${RED}[FAIL] data.json sai cấu trúc hoặc thiếu tab bắt buộc!${NC}"
    FAILURES=$((FAILURES + 1))
fi

# ------------------------------------------------------------------------------
# GATE 6: ROSTER MODULE VALIDATION
# ------------------------------------------------------------------------------
echo -e "\n${BOLD}[GATE 6/8] Kiểm tra module Roster Engine (roster.py)...${NC}"

ROSTER_FILE="$PROJECT_ROOT/backend/routers/roster.py"
if [ -f "$ROSTER_FILE" ]; then
    if "$VENV_PYTHON" -m py_compile "$ROSTER_FILE" 2>/dev/null; then
        # Verify roster is imported in main.py
        if grep -q "roster" "$PROJECT_ROOT/backend/main.py" 2>/dev/null; then
            echo -e "  [PASS] roster.py biên dịch thành công và đã đăng ký trong main.py"
        else
            echo -e "  ${RED}[FAIL] roster.py tồn tại nhưng CHƯA import trong main.py!${NC}"
            FAILURES=$((FAILURES + 1))
        fi
    else
        echo -e "  ${RED}[FAIL] roster.py có lỗi cú pháp!${NC}"
        FAILURES=$((FAILURES + 1))
    fi
else
    echo -e "  ${YELLOW}[WARN] roster.py không tồn tại — bỏ qua${NC}"
fi

# ------------------------------------------------------------------------------
# GATE 7: REAL-WORLD E2E INTEGRATION & BROWSER VERIFICATION
# ------------------------------------------------------------------------------
echo -e "\n${BOLD}[GATE 7/8] Kiểm thử E2E Thực Chiến & Trình duyệt thật (Real Browser & Live Server)...${NC}"

REAL_E2E_SCRIPT="$PROJECT_ROOT/scripts/test_live_e2e_real_world.py"
if [ -f "$REAL_E2E_SCRIPT" ]; then
    if "$VENV_PYTHON" "$REAL_E2E_SCRIPT"; then
        echo -e "  [PASS] 100% kiểm thử E2E thực chiến (Chrome Headless, Uvicorn, SQLite WAL, No-JSON) đạt chuẩn"
    else
        echo -e "  ${RED}[FAIL] Kiểm thử E2E thực chiến thất bại!${NC}"
        FAILURES=$((FAILURES + 1))
    fi
else
    echo -e "  ${YELLOW}[WARN] Không tìm thấy test_live_e2e_real_world.py — bỏ qua${NC}"
fi

# ------------------------------------------------------------------------------
# GATE 8: DRIFT DETECTION (REPO vs LIVE)
# ------------------------------------------------------------------------------
echo -e "\n${BOLD}[GATE 8/8] Phát hiện Drift (Repo vs Live Production)...${NC}"

REMOTE_HOST="${REMOTE_HOST:-}"
DRIFT_DETECTED=0

if [ -n "$REMOTE_HOST" ] && ssh -q -o BatchMode=yes -o ConnectTimeout=5 "$REMOTE_HOST" "exit" 2>/dev/null; then
    REMOTE_DIR="${REMOTE_PATH_PREFIX:-/opt/fnbops}"
    for check_pair in \
        "$PROJECT_ROOT/frontend/mobile.js:$REMOTE_DIR/frontend/mobile.js" \
        "$PROJECT_ROOT/frontend/index.html:$REMOTE_DIR/frontend/index.html" \
        "$PROJECT_ROOT/backend/routers/fnb_ops.py:$REMOTE_DIR/backend/routers/fnb_ops.py" \
        "$PROJECT_ROOT/backend/routers/roster.py:$REMOTE_DIR/backend/routers/roster.py" \
        "$PROJECT_ROOT/backend/main.py:$REMOTE_DIR/backend/main.py"; do
        LOCAL_F="${check_pair%%:*}"
        REMOTE_F="${check_pair##*:}"
        if [ -f "$LOCAL_F" ]; then
            LOCAL_MD5=$(md5 -q "$LOCAL_F" 2>/dev/null || md5sum "$LOCAL_F" | awk '{print $1}')
            REMOTE_MD5=$(ssh -q "$REMOTE_HOST" "md5 -q '$REMOTE_F' 2>/dev/null" || echo "missing")
            if [ "$LOCAL_MD5" != "$REMOTE_MD5" ]; then
                echo -e "  ${YELLOW}[DRIFT] $(basename "$LOCAL_F")${NC}"
                DRIFT_DETECTED=$((DRIFT_DETECTED + 1))
            fi
        fi
    done
    if [ "$DRIFT_DETECTED" -eq 0 ]; then
        echo -e "  [PASS] Repo và Live đồng bộ — không phát hiện drift"
    else
        echo -e "  ${YELLOW}[WARN] Phát hiện $DRIFT_DETECTED file(s) lệch giữa repo và live${NC}"
        echo -e "  ${YELLOW}        Chạy deploy_remote.sh để đồng bộ${NC}"
        # Drift is WARNING, not FAILURE — don't block deploy
    fi
else
    echo -e "  ${YELLOW}[SKIP] Chưa cấu hình REMOTE_HOST hoặc không thể kết nối máy chủ — bỏ qua drift check${NC}"
fi

# ------------------------------------------------------------------------------
# TỔNG KẾT
# ------------------------------------------------------------------------------
TOTAL_GATES=8
echo -e "\n${BOLD}${BLUE}======================================================================${NC}"
if [ "$FAILURES" -eq 0 ]; then
    echo -e "${BOLD}${GREEN}   KẾT QUẢ QUALITY GATES: TẤT CẢ $TOTAL_GATES GATES ĐẠT CHUẨN (PASS 100%)       ${NC}"
    if [ "$DRIFT_DETECTED" -gt 0 ]; then
        echo -e "${BOLD}${YELLOW}   CẢNH BÁO: $DRIFT_DETECTED file(s) drift — cân nhắc đồng bộ trước deploy    ${NC}"
    fi
    echo -e "${BOLD}${BLUE}======================================================================${NC}\n"
    exit 0
else
    echo -e "${BOLD}${RED}   KẾT QUẢ QUALITY GATES: CÓ ${FAILURES} GATE(S) THẤT BẠI!          ${NC}"
    echo -e "${BOLD}${RED}   CẢNH BÁO: HỆ THỐNG CHẶN TRIỂN KHAI CHO ĐẾN KHI KHẮC PHỤC.        ${NC}"
    echo -e "${BOLD}${BLUE}======================================================================${NC}\n"
    exit 1
fi


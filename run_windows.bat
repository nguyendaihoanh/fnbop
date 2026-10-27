@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "PYTHONPATH=%~dp0;%~dp0backend"
:: ==============================================================================
:: FnBOps - Trình Khởi Động 1-Click Dành Cho Windows (POS & PC)
:: Nhấp đúp chuột vào file này để khởi chạy toàn bộ hệ thống!
:: ==============================================================================

title FnBOps / WFM - Hệ Điều Hành Vận Hành F&B & Workforce

echo ====================================================================
echo    FnBOps / WFM — HỆ ĐIỀU HÀNH VẬN HÀNH F&B & WORKFORCE (MÃ NGUỒN MỞ 100%%)
echo ====================================================================
echo.

:: 1. Xác định trình thông dịch Python & Môi trường ảo (.venv)
set PYTHON_BIN=python
if exist "python_runtime\python.exe" (
    set "PYTHON_BIN=%~dp0python_runtime\python.exe"
    echo [*] Sử dụng gói Python Portable đính kèm (python_runtime)...
) else if exist "runtime\python.exe" (
    set "PYTHON_BIN=%~dp0runtime\python.exe"
    echo [*] Sử dụng gói Python Portable đính kèm (runtime)...
) else (
    where python >nul 2>nul
    if %ERRORLEVEL% neq 0 (
        echo [LỖI] Máy tính chưa có Python!
        echo Vui lòng cài đặt Python (3.11 hoặc 3.12) từ python.org (nhớ tích chọn 'Add Python to PATH').
        echo Hoặc giải nén gói Python Embedded vào thư mục python_runtime.
        echo.
        pause
        exit /b 1
    )
    if not exist ".venv\Scripts\python.exe" (
        echo [*] Đang khởi tạo môi trường ảo Python (.venv)...
        python -m venv .venv
    )
    if exist ".venv\Scripts\python.exe" (
        set "PYTHON_BIN=%~dp0.venv\Scripts\python.exe"
    )
)

:: Kiểm tra và tự động cài đặt thư viện nếu thiếu
"%PYTHON_BIN%" -c "import fastapi, uvicorn, pydantic" >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [*] Đang cài đặt các thư viện cần thiết từ requirements.txt...
    "%PYTHON_BIN%" -m pip install --quiet --upgrade pip
    if exist "requirements.txt" (
        "%PYTHON_BIN%" -m pip install --quiet -r requirements.txt
    ) else if exist "backend\requirements.txt" (
        "%PYTHON_BIN%" -m pip install --quiet -r backend\requirements.txt
    )
)

:: 2. Tạo các thư mục dữ liệu
if not exist "data\logs" mkdir data\logs
if not exist "data\backups" mkdir data\backups
if not exist "data\outbox\pdf" mkdir data\outbox\pdf

:: Tự động tạo .env từ .env.example nếu chưa có
if not exist ".env" (
    if exist ".env.example" (
        echo [*] Chưa có file .env, tự động khởi tạo từ .env.example...
        copy ".env.example" ".env" >nul
    )
)

:: 3. Thiết lập biến môi trường
if "%FASTAPI_PORT%"=="" set FASTAPI_PORT=8100
set ON_PREMISE_MODE=true

echo [*] Đang khởi động FnBOps Server tại cổng %FASTAPI_PORT%...

:: Tự động mở trình duyệt sau 3 giây
start "" cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:%FASTAPI_PORT%"

:: 4. Khởi chạy FastAPI backend (uvicorn backend.main:app)
"%PYTHON_BIN%" -m uvicorn backend.main:app --host 0.0.0.0 --port %FASTAPI_PORT%

if %ERRORLEVEL% neq 0 (
    echo.
    echo [CẢNH BÁO] Server bị dừng bất ngờ.
    pause
)

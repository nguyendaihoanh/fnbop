@echo off
chcp 65001 >nul
:: ==============================================================================
:: FnBOps - KHỞI ĐỘNG NATIVE 1-CLICK (CHO MÁY POS WINDOWS KHÔNG CÓ DOCKER)
:: Khởi chạy FastAPI Backend + Zalo Gateway Microservice kèm Process Watchdog
:: Tối ưu máy POS Celeron / Core i3, RAM 4GB (Tiêu thụ tối đa 180MB RAM)
:: ==============================================================================

title FnBOps - Khởi Động Native 1-Click

cd /d "%~dp0"
if exist "..\..\backend" cd /d "%~dp0..\.."

echo ====================================================================
echo    FnBOps CORE — NATIVE STANDALONE PROCESS STACK
echo ====================================================================
echo.

:: 1. Kiểm tra Python
where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [LỖI] Không tìm thấy Python trên máy tính này!
    echo Vui lòng cài đặt Python (3.10 trở lên) và tích chọn 'Add Python to PATH'.
    echo.
    pause
    exit /b 1
)

:: 2. Kiểm tra Node.js
where node >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [LỖI] Không tìm thấy Node.js trên máy tính này!
    echo Vui lòng cài đặt Node.js (v18 trở lên) để chạy Zalo Gateway.
    echo.
    pause
    exit /b 1
)

:: 3. Kiểm tra dependencies của Zalo Gateway
if not exist "backend\zalo_gateway\node_modules" (
    echo [*] Lần đầu chạy: Đang cài đặt thư viện cho Zalo Gateway...
    cd backend\zalo_gateway
    call npm install --omit=dev --no-audit --no-fund
    cd ..\..
    echo [✓] Đã cài xong thư viện Zalo Gateway!
)

:: 4. Khởi chạy Master Supervisor Watchdog
echo [*] Đang khởi chạy hệ thống Native kèm bộ giám sát tự phục hồi...
python "%~dp0run_native.py"

pause

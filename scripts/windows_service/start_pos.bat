@echo off
chcp 65001 >nul
title FnBOps — MÁY CHỦ CHẤM CÔNG & QUẢN TRỊ POS

echo ======================================================================
echo          FnBOps Core — On-Premise Stack
echo ======================================================================
echo.

cd /d "%~dp0..\..\"
set "PROJECT_ROOT=%CD%"
echo [*] Thu muc ung dung: %PROJECT_ROOT%

:: 1. Kiem tra Python Portable Runtime hoac Virtualenv
set "PYTHON_CMD="

if exist "%PROJECT_ROOT%\python_runtime\python.exe" (
    set "PYTHON_CMD=%PROJECT_ROOT%\python_runtime\python.exe"
    echo [*] Su dung Python Portable Runtime nhung: python_runtime\python.exe
) else if exist "%PROJECT_ROOT%\.venv\Scripts\python.exe" (
    set "PYTHON_CMD=%PROJECT_ROOT%\.venv\Scripts\python.exe"
    echo [*] Su dung moi truong Python ao: .venv\Scripts\python.exe
) else (
    where python >nul 2>nul
    if %ERRORLEVEL% equ 0 (
        set "PYTHON_CMD=python"
        echo [*] Su dung Python he thong Windows
    )
)

if "%PYTHON_CMD%"=="" (
    echo.
    echo [!] LOI: Khong tim thay Python tren may POS!
    echo     De chay khong can cai Python, vui long giai nen goi:
    echo     'python_runtime' vao thu muc goc cua chuong trinh.
    echo.
    pause
    exit /b 1
)

:: 2. Tao cac thu muc du lieu can thiet
if not exist "%PROJECT_ROOT%\data\logs" mkdir "%PROJECT_ROOT%\data\logs"
if not exist "%PROJECT_ROOT%\data\outbox\pdf" mkdir "%PROJECT_ROOT%\data\outbox\pdf"
if not exist "%PROJECT_ROOT%\data\backups" mkdir "%PROJECT_ROOT%\data\backups"
if not exist "%PROJECT_ROOT%\data\zalo_session" mkdir "%PROJECT_ROOT%\data\zalo_session"

:: 3. Khoi chay Zalo Gateway (Node.js) song song neu co Node.js
where node >nul 2>nul
if %ERRORLEVEL% equ 0 (
    echo [*] Tim thay Node.js - Dang khoi dong Zalo Gateway tren cong 8177...
    start "FnBOps Zalo Gateway" /min cmd /c "node "%PROJECT_ROOT%\backend\zalo_gateway\server.js" > "%PROJECT_ROOT%\data\logs\zalo_gateway.log" 2>&1"
    timeout /t 2 /nobreak >nul
    echo [*] Zalo Gateway da khoi dong.
) else (
    echo [!] CANH BAO: Khong tim thay Node.js - Tinh nang Zalo se khong hoat dong.
    echo     Tai Node.js 18 LTS tai: https://nodejs.org/en/download
)
echo.

:: 4. Khoi chay Web Server Uvicorn tren cong 8100
echo [*] Dang khoi dong may chu chinh tai cong 8100...
echo [*] Link quan tri tai quay: http://localhost:8100
echo [*] Link nhan vien cham cong noi bo: http://chamcong.local:8100
echo.
echo [!] Nhan Ctrl+C de dung may chu.
echo ======================================================================
echo.

:: Mo trinh duyet sau 3 giay
start "" cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:8100"

:: Chay FastAPI Uvicorn
"%PYTHON_CMD%" -m uvicorn backend.main:app --host 0.0.0.0 --port 8100
pause

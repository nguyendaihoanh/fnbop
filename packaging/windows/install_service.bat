@echo off
chcp 65001 >nul
title CÀI ĐẶT DỊCH VỤ WINDOWS 24/7 — FNBOPS POS SERVICE

echo ======================================================================
echo       CÀI ĐẶT FNBOPS CHẠY NGẦM 24/7 BẰNG NSSM (WINDOWS SERVICE)
echo ======================================================================
echo.

:: 1. Kiem tra quyen Administrator
net session >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [!] LOI: Vui long click chuot phai vao file nay va chon:
    echo     "Run as administrator" (Chay voi quyen Quan tri vien).
    echo.
    pause
    exit /b 1
)

cd /d "%~dp0..\..\"
set "PROJECT_ROOT=%CD%"
set "SERVICE_NAME=FnBOpsPOS"

:: 2. Kiem tra file nssm.exe
set "NSSM_EXE=%~dp0nssm.exe"
if not exist "%NSSM_EXE%" (
    where nssm >nul 2>nul
    if %ERRORLEVEL% equ 0 (
        set "NSSM_EXE=nssm"
    ) else (
        echo [!] LOI: Khong tim thay 'nssm.exe' trong thu muc packaging\windows\
        echo     Vui long tai nssm.exe (ban x64) tu https://nssm.cc/download
        echo     va chep vao thu muc packaging\windows\
        echo.
        pause
        exit /b 1
    )
)

:: 3. Kiem tra Python
set "PYTHON_CMD="
if exist "%PROJECT_ROOT%\python_runtime\python.exe" (
    set "PYTHON_CMD=%PROJECT_ROOT%\python_runtime\python.exe"
) else if exist "%PROJECT_ROOT%\.venv\Scripts\python.exe" (
    set "PYTHON_CMD=%PROJECT_ROOT%\.venv\Scripts\python.exe"
) else (
    where python >nul 2>nul
    if %ERRORLEVEL% equ 0 set "PYTHON_CMD=python"
)

if "%PYTHON_CMD%"=="" (
    echo [!] LOI: Khong tim thay Python! Vui long dat thu muc python_runtime vao goc project.
    pause
    exit /b 1
)

:: 4. Tao thu muc log
if not exist "%PROJECT_ROOT%\data\logs" mkdir "%PROJECT_ROOT%\data\logs"

:: 5. Go bo service cu neu ton tai (WFMOpsPOS va FnBOpsPOS)
"%NSSM_EXE%" stop "WFMOpsPOS" >nul 2>&1
"%NSSM_EXE%" remove "WFMOpsPOS" confirm >nul 2>&1
"%NSSM_EXE%" status "%SERVICE_NAME%" >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [*] Dang dung va go bo service cu...
    "%NSSM_EXE%" stop "%SERVICE_NAME%" >nul 2>&1
    "%NSSM_EXE%" remove "%SERVICE_NAME%" confirm >nul 2>&1
)

:: 6. Cai dat service moi
echo [*] Dang dang ky Windows Service '%SERVICE_NAME%'...
"%NSSM_EXE%" install "%SERVICE_NAME%" "%PYTHON_CMD%" "-m uvicorn backend.main:app --host 0.0.0.0 --port 8100"
"%NSSM_EXE%" set "%SERVICE_NAME%" AppDirectory "%PROJECT_ROOT%"
"%NSSM_EXE%" set "%SERVICE_NAME%" DisplayName "FnBOps Standalone POS Service"
"%NSSM_EXE%" set "%SERVICE_NAME%" Description "Hệ điều hành Chấm công, Xếp ca & Bảng lương F&B Mã nguồn mở - FnBOps"
"%NSSM_EXE%" set "%SERVICE_NAME%" Start SERVICE_AUTO_START
"%NSSM_EXE%" set "%SERVICE_NAME%" AppStdout "%PROJECT_ROOT%\data\logs\service_output.log"
"%NSSM_EXE%" set "%SERVICE_NAME%" AppStderr "%PROJECT_ROOT%\data\logs\service_error.log"
"%NSSM_EXE%" set "%SERVICE_NAME%" AppRotateFiles 1
"%NSSM_EXE%" set "%SERVICE_NAME%" AppRotateBytes 10485760

:: 7. Khoi dong service
echo [*] Dang khoi dong service...
"%NSSM_EXE%" start "%SERVICE_NAME%"

echo.
echo ======================================================================
echo [V] DA CAI DAT THANH CONG!
echo     - Dịch vụ '%SERVICE_NAME%' se tu dong chay moi khi bat may POS.
echo     - Khong con hien cua so den CMD tren man hinh thu ngan.
echo     - Nhan vien cham cong qua: http://chamcong.local:8100
echo     - Quan ly truy cap: http://localhost:8100
echo ======================================================================
pause

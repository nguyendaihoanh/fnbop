@echo off
chcp 65001 >nul
title GỠ BỎ DỊCH VỤ — FNBOPS POS SERVICE

echo ======================================================================
echo       GỠ BỎ DỊCH VỤ WINDOWS FNBOPS (NSSM)
echo ======================================================================
echo.

net session >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [!] LOI: Vui long click chuot phai vao file nay va chon "Run as administrator".
    pause
    exit /b 1
)

set "SERVICE_NAME=FnBOpsPOS"
set "NSSM_EXE=%~dp0nssm.exe"
if not exist "%NSSM_EXE%" set "NSSM_EXE=nssm"

echo [*] Dang dung service '%SERVICE_NAME%'...
"%NSSM_EXE%" stop "%SERVICE_NAME%" >nul 2>&1
"%NSSM_EXE%" stop "FnBOpsPOS" >nul 2>&1

echo [*] Dang go bo service '%SERVICE_NAME%' khoi he thong...
"%NSSM_EXE%" remove "%SERVICE_NAME%" confirm >nul 2>&1
"%NSSM_EXE%" remove "FnBOpsPOS" confirm >nul 2>&1

echo.
echo [V] Da go bo service thanh cong!
pause

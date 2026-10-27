@echo off
chcp 65001 >nul
:: ==============================================================================
:: FnBOps - SCRIPT KHỞI ĐỘNG STANDALONE 1-CHẠM (DÀNH CHO MÁY POS WINDOWS)
:: Khởi chạy hệ thống F&B Standalone: Nginx PWA + FastAPI + Zalo Gateway
:: Tối ưu máy POS Celeron / Core i3, RAM 4GB (Tiêu thụ tối đa 250MB RAM)
:: ==============================================================================

title FnBOps - Khởi Động Standalone 1-Chạm

cd /d "%~dp0"
if exist "..\..\docker-compose.standalone.yml" cd /d "%~dp0..\.."

echo ====================================================================
echo    ☕ FnBOps Core — On-Premise Stack
echo ====================================================================
echo.

:: 1. Kiểm tra Docker Engine trên Windows
where docker >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [LỖI] Không tìm thấy Docker trên máy tính này!
    echo Vui lòng cài đặt Docker Desktop cho Windows hoặc liên hệ kỹ thuật.
    echo Tải về tại: https://www.docker.com/products/docker-desktop/
    echo.
    pause
    exit /b 1
)

docker info >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [LỖI] Docker Desktop chưa được bật!
    echo Vui lòng mở ứng dụng Docker Desktop dưới thanh Taskbar và đợi biểu tượng chuyển sang màu xanh.
    echo Sau đó bấm phím bất kỳ để thử lại.
    echo.
    pause
    exit /b 1
)

:: 2. Khởi tạo thư mục dữ liệu cục bộ nếu chưa có
echo [1/3] Đang chuẩn bị thư mục lưu trữ CSDL và Session...
if not exist "data" mkdir "data"
if not exist "data\zalo_session" mkdir "data\zalo_session"
if not exist "data\outbox\pdf" mkdir "data\outbox\pdf"
if not exist "backend\data" mkdir "backend\data"

:: 3. Kiểm tra file cấu hình .env
echo [2/3] Kiểm tra cấu hình môi trường .env...
if not exist ".env" (
    if exist ".env.example" (
        echo     -> Chưa có .env. Đang tự động sao chép từ .env.example...
        copy ".env.example" ".env" >nul
        echo     -> Đã tạo .env thành công!
    )
)

:: 4. Khởi động Docker Compose
echo [3/3] Đang khởi động 3 container Standalone (Nginx, FastAPI, Zalo Gateway)...
docker compose -f docker-compose.standalone.yml up -d
if %ERRORLEVEL% neq 0 (
    echo [THỬ LẠI] Đang thử bằng lệnh docker-compose v1...
    docker-compose -f docker-compose.standalone.yml up -d
    if %ERRORLEVEL% neq 0 (
        echo [LỖI] Không thể khởi động Docker containers!
        pause
        exit /b 1
    )
)

:: 5. Thông báo kết quả và mở trình duyệt
echo.
echo ====================================================================
echo    ✓ HỆ THỐNG STANDALONE F&B ĐÃ SẴN SÀNG TRÊN MÁY POS!
echo ====================================================================
echo.
echo 1. Giao diện Web PWA (Chủ quán & Thu ngân):
echo    -> Truy cập: http://localhost:8100
echo.
echo 2. API Backend & Quản Trị:
echo    -> Swagger:  http://localhost:8100/docs
echo.
echo 3. Zalo Gateway Microservice:
echo    -> Trạng thái: http://localhost:8177/api/zalo/status
echo    -> Quét QR:    http://localhost:8177/api/zalo/qr
echo.
echo 4. Giới hạn RAM tối đa: 250MB (Bảo vệ máy POS không bị giật lag)
echo ====================================================================
echo.
echo Đang tự động mở giao diện Web PWA trên trình duyệt...
timeout /t 3 >nul
start http://localhost:8100

echo.
echo Cửa sổ này có thể đóng lại. Dịch vụ vẫn chạy ngầm trên Docker.
echo Để dừng hệ thống, mở Command Prompt và gõ: docker compose -f docker-compose.standalone.yml down
echo.
pause

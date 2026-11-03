# Manual E2E Puppeteer Scripts

Thư mục này chứa các kịch bản kiểm thử thủ công và thăm dò tương tác giao diện bằng Puppeteer.

> [!NOTE]
> Các kịch bản này yêu cầu môi trường Node.js có cài đặt `puppeteer` và một server FnBOps đang chạy tại `http://localhost:8100`.
> Chúng không chạy tự động trong CI pipeline để đảm bảo tốc độ và tính cô lập của bộ test tự động (Pytest & Jest).

## Danh Sách Kịch Bản:
- `test_live_ui_puppeteer.mjs`: Thăm dò luồng giao diện tổng thể.
- `test_inspect_new_nav_bar.mjs`: Kiểm tra cấu trúc thanh điều hướng.
- `test_manager_admin_nav_rules.mjs`: Xác minh quy tắc phân quyền hiển thị nav giữa Admin và Manager.
- `test_nav_solar_verify.mjs`: Kiểm tra hiển thị icon Solar trên thanh điều hướng.
- `test_tab_switch_nav_persistence.mjs`: Kiểm tra lưu vết trạng thái tab khi chuyển màn hình.
- `test_puppeteer_ui.cjs`: Thử nghiệm giao diện tương thích CommonJS.

## Cách Chạy:
```bash
# 1. Khởi động server backend
.venv/bin/python -m uvicorn backend.main:app --port 8100

# 2. Chạy kịch bản cần kiểm tra
node tests/manual_e2e/test_live_ui_puppeteer.mjs
```

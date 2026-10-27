# HỆ THỐNG KIỂM THỬ FNBOPS (TESTING ARCHITECTURE)

Tài liệu này mô tả cấu trúc phân tầng kiểm thử tự động của dự án FnBOps.

---

## 1. PHÂN TẦNG KIỂM THỬ (TESTING PYRAMID)

| Tầng | Loại kiểm thử | Công cụ / Môi trường | Phạm vi xác minh | Mức độ tin cậy thực tế |
|---|---|---|---|---|
| **TẦNG 1 (VÀNG)** | **Real-World Live E2E** | Python Uvicorn + SQLite WAL + Real Google Chrome Headless (Puppeteer) | Mở trình duyệt thật, tương tác người dùng thật (Đăng nhập PIN, Chấm công, Chốt két, Snapshot), đo đạc Console Errors (=0), kiểm toán không ghi đè JSON. | **100% (Thực tế vận hành tại quầy)** |
| **TẦNG 2** | **Backend API & Payroll Pytest** | Pytest (`tests/*.py`), TestClient | Kiểm tra công thức lương (OT, Lễ, phạt đi trễ), logic phân quyền RBAC, rate-limiting, SQLite repo transactions. | **Cao (Cho phần logic máy chủ)** |
| **TẦNG 3** | **Mock DOM Unit Simulations** | Node.js (`tests/*.js` có `MockElement`) | Giả lập các hàm giao diện cô lập bằng object JS giả lập DOM (`class MockElement`). **KHÔNG PHẢI trình duyệt thật.** | **Thấp (Chỉ dùng kiểm tra logic nhánh cú pháp nhỏ)** |

---

## 2. BÀI TEST THỰC CHIẾN CHỦ LỰC (REAL-WORLD E2E)

- **Đường dẫn**: `scripts/test_live_e2e_real_world.py`
- **Lệnh chạy**:
  ```bash
  ./.venv/bin/python scripts/test_live_e2e_real_world.py
  ```
- **6 Bước kiểm toán bắt buộc**:
  1. **Real Browser Automation**: Khởi động Google Chrome thật (Puppeteer), duyệt qua 3 trang chính (`/`, `/desktop.html`, `/monthly-report.html`), thực hiện đăng nhập thật và click qua tất cả các tabs. **Yêu cầu 0 Console Errors & 0 Unhandled Exceptions.**
  2. **Static Assets Integrity**: Kiểm tra HTTP 200 và MIME types của HTML, JS, JSON.
  3. **Staff Journey**: Đăng nhập nhân viên (PIN 1111) -> Check-in -> Soi trực tiếp bảng SQLite `attendance_logs` -> Check-out -> Soi lại SQLite.
  4. **Manager Journey**: Đăng nhập quản lý (PIN 8888) -> Chốt két ca POS Closing -> Soi trực tiếp bảng SQLite `daily_closings`.
  5. **Admin Journey**: Đăng nhập Admin (PIN 1234) -> Trích xuất JSON Snapshot on-demand -> Kiểm toán số lượng bản ghi SQLite.
  6. **Kiểm toán bất biến "Cấm JSON"**: Đo mã băm SHA256 của toàn bộ file JSON trong `data/` trước và sau khi chạy nghiệp vụ trên server thật, khẳng định 0 byte JSON nào bị ghi đè runtime.

---

## 3. DANH SÁCH MOCK DOM SIMULATION (CẦN LƯU Ý KHI ĐỌC KẾT QUẢ)

Các file sau trong `tests/` sử dụng `MockElement` trong Node.js (không dùng mạng thật, không dùng trình duyệt thật, không render CSS):
- `tests/test_e2e_auth_gate.js`
- `tests/test_e2e_frontend_interactions.js`
- `tests/test_e2e_manager_journey.js`
- `tests/test_e2e_staff_journey.js`
- `tests/test_manager_safeguards_eval.js`
- `tests/test_press_hold_checkout.js`
- `tests/test_responsive_desktop_mode.js`
- `tests/test_roster_teammates_swap.js`
- `tests/test_thermal_receipt_and_swipe_gestures.js`

> **LƯU Ý QUAN TRỌNG**: Kết quả "PASS" của các file trên chỉ phản ánh logic tính toán trong môi trường Node.js cô lập. **Nghiệm thu chất lượng sản phẩm bắt buộc phải căn cứ vào Tầng 1 (`scripts/test_live_e2e_real_world.py`) và Cổng kiểm định Quality Gates.**

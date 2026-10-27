# FnBOps RESTful API v1 Specification / Đặc Tả Giao Thức REST API v1

> **Languages / Ngôn ngữ:** [English](#english) | [Tiếng Việt](#tiếng-việt)

---

<a name="english"></a>
## Part I — English Reference

### 1. Overview & Authentication
`FnBOps` exposes a unified RESTful API powered by FastAPI on default port **`8100`**.
Protected endpoints require an `Authorization` header with an `HS256` JWT Bearer token:
```http
Authorization: Bearer <JWT_ACCESS_TOKEN>
```
Every HTTP response includes strict Zero-CDN `Content-Security-Policy` headers and the copyright attribution header:
`X-FnBOps-License: AGPL-3.0-only; Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>`

---

### 2. Authentication & Session Lifecycle
- **`POST /api/v1/cc/auth/login`**: Authenticate staff, manager, or admin via username and 4-digit PIN.
  - **Body:** `{"username": "admin", "password": "..."}`
  - **Response:** `{"access_token": "...", "token_type": "bearer", "role": "ADMIN|MANAGER|STAFF", "name": "...", "ver": 1}`
  - **Security:** Enforces 3-Tier Progressive Rate Limiting (`login_attempts` table in SQLite WAL) with automatic POS WAN IP exemption so shared store WiFi is never locked out collectively.
- **`POST /api/v1/cc/auth/refresh`**: Sliding-window session renewal (issues a fresh 7-day JWT with the current `token_version`).
- **`GET /api/v1/cc/auth/verify`**: Verify token signature, check `ver >= staff_accounts.token_version` (instant revocation on PIN/role change), and synchronize live RBAC claims from SQLite.
- **`POST /api/v1/cc/auth/logout`**: Revoke active token `jti` in SQLite `revoked_tokens`.

---

### 3. Staff & Access Control (`backend/routers/staff.py`)
- **`GET /api/v1/cc/admin/staff-accounts`**: List staff accounts for Admin/Manager (never exposes raw PIN hashes; returns `has_pin: true|false`).
- **`POST /api/v1/cc/admin/create-staff`**: Create a new staff account with PBKDF2-HMAC-SHA256 (100,000 iterations) PIN hashing and auto-assigned `EMP_xxx` ID.
- **`POST /api/v1/cc/admin/update-staff-profile`**: Update staff profile, hourly rate, fixed shifts, or PIN. Automatically increments `token_version += 1` when PIN or role changes.
- **`POST /api/v1/cc/admin/update-pin`**: Self-service or Admin PIN rotation (`token_version += 1`).
- **`POST /api/v1/cc/admin/toggle-staff-status`**: Activate/deactivate account (`INACTIVE` increments `token_version += 1` to invalidate active sessions immediately).
- **`GET /api/v1/cc/admin/lockouts` & `POST /api/v1/cc/admin/lockouts/unlock`**: Inspect and unlock rate-limited accounts or IPs.

---

### 4. Geofenced Attendance & POS Heartbeat (`backend/routers/attendance.py`)
- **`POST /api/v1/cc/attendance/checkin`**: Record staff clock-in after verifying store WiFi WAN IP / `/24` LAN subnet or Access Point BSSID.
- **`POST /api/v1/cc/attendance/checkout`**: Record clock-out with role checklist and shift duration calculation.
- **`GET /api/v1/cc/attendance/status`**: Retrieve current active shift state for the logged-in user.
- **`GET /api/v1/cc/attendance/manager/auto-close-check`**: Scan and auto-close hanging unclosed shifts.
- **`POST /api/v1/cc/attendance/pos/heartbeat`**: Receive periodic WAN IP beacon from the store POS terminal (includes 120-second replay-attack timestamp validation).

---

### 5. AI Shift Roster & Peer Swap (`backend/routers/roster.py`)
- **`GET /api/v1/cc/roster/week`**: Fetch full weekly shift matrix, registrations, and staff directory from SQLite WAL.
- **`GET /api/v1/cc/roster/my-schedule`**: Fetch personalized shift schedule for the logged-in employee (enforces Sunday 12:00 PM auto-publish deadline and hides `DRAFT` schedules from non-managers).
- **`POST /api/v1/cc/roster/register`**: Submit weekly shift availability preferences.
- **`POST /api/v1/cc/roster/auto-fill`**: Execute the **MRV + Kuhn's Augmenting Path (BFS-4) + 64-bit Bitmask** solver to generate conflict-free weekly schedules in `<50ms`.
- **`POST /api/v1/cc/roster/clone-previous-week`**: Clone previous week's assignments into the target week.
- **`POST /api/v1/cc/roster/update-shift`**: Manually assign or clear a shift slot (protected by re-entrant `threading.RLock()`).
- **`POST /api/v1/cc/roster/publish`**: Lock and publish the weekly schedule.
- **`POST /api/v1/cc/roster/peer-swap` & `POST /api/v1/cc/roster/peer-swap/respond`**: Initiate and accept/reject 2-step peer shift swaps (`GET /api/v1/cc/roster/peer-swaps/pending`).
- **`GET /api/v1/cc/roster/open-shifts` & `POST /api/v1/cc/roster/open-shifts/{shift_id}/claim`**: Open shift marketplace for unclaimed slots.

---

### 6. Immutable Payroll Ledger & Disbursements (`backend/routers/fnb_ops.py` & `disbursement.py`)
- **`GET /api/v1/cc/payroll/summary`**: Compute authoritative monthly integer VND payroll breakdown (`payroll_calc.py`).
- **`POST /api/v1/cc/payroll/ledger`**: Record salary advance, bonus, or deduction into the append-only ledger (`so_cai_luong` with SQLite `BEFORE UPDATE`/`BEFORE DELETE` abort triggers and `idempotency_key` deduplication).
- **`POST /api/v1/cc/payroll/confirm`**: Record employee digital confirmation or dispute of monthly payslip.
- **`GET /api/v1/cc/payroll/disbursements` & `POST /api/v1/cc/payroll/disbursements/toggle`**: Track bank-transfer disbursement status per employee.
- **`GET /api/v1/cc/notifications/preview-payslip-card` & `GET /api/v1/cc/notifications/download-payslip-pdf`**: Render 1080x1440 Retina PNG payslip card (with VietQR) and A5 PDF using bundled open-source `Inter v4.1 (SIL OFL-1.1)` fonts.

---

### 7. POS Cash Closing, Evaluations & License Verification
- **`POST /api/v1/cc/pos/daily-closing`**: Submit shift/daily cash drawer reconciliation (binds `sender_name` to JWT caller for `STAFF` and locks approved closings).
- **`GET /api/v1/cc/pos/closing/latest` & `GET /api/v1/cc/pos/closing/history`**: Query POS cash closing records.
- **`POST /api/v1/cc/evaluations` & `GET /api/v1/cc/evaluations`**: Manage staff reward/penalty evaluations.
- **`GET /health` & `GET /api/v1/main/ping`**: Liveness and readiness probes.
- **`GET /api/v1/license` (alias `/api/v1/cc/license`)**: Public copyright ownership, `AGPL-3.0-only` Section 7(b) & Section 13 compliance verification, and Commercial Dual-Licensing metadata.

---

<a name="tiếng-việt"></a>
## Phần II — Tài Liệu Đặc Tả Tiếng Việt

### 1. Tổng Quan & Cơ Chế Xác Thực
`FnBOps` cung cấp hệ thống RESTful API thống nhất trên cổng mặc định **`8100`**.
Mọi truy vấn cần xác thực sử dụng chuẩn JWT `HS256` qua header:
```http
Authorization: Bearer <JWT_ACCESS_TOKEN>
```

### 2. Bảng Tóm Tắt Các Nhóm Endpoint Chủ Lực

| Phân hệ | Endpoint chính | Mô tả nghiệp vụ & Cơ chế bảo vệ |
| :--- | :--- | :--- |
| **Xác thực & Phiên** | `POST /api/v1/cc/auth/login`<br>`POST /api/v1/cc/auth/refresh`<br>`GET /api/v1/cc/auth/verify` | Đăng nhập mã PIN 4 số (băm `PBKDF2-SHA256` 100.000 vòng), chống dò mật khẩu 3 tầng lũy tiến (tự động miễn trừ khóa IP cho mạng WiFi quán), thu hồi phiên tức thì qua `token_version`. |
| **Quản trị Nhân sự** | `GET /api/v1/cc/admin/staff-accounts`<br>`POST /api/v1/cc/admin/create-staff`<br>`POST /api/v1/cc/admin/update-staff-profile` | Quản lý hồ sơ, lương giờ, ca cố định, đổi mã PIN. Tự động nâng `token_version += 1` khi đổi PIN hoặc khóa tài khoản để vô hiệu hóa toàn bộ token cũ. |
| **Chấm công & Nhịp tim POS** | `POST /api/v1/cc/attendance/checkin`<br>`POST /api/v1/cc/attendance/checkout`<br>`POST /api/v1/cc/attendance/pos/heartbeat` | Kiểm tra Geofence IP WAN của quán / dải mạng `/24` / BSSID trước khi cho phép vào ca; nhận nhịp tim POS định kỳ (chống Replay Attack quá 120 giây). |
| **Xếp ca AI & Đổi ca** | `GET /api/v1/cc/roster/week`<br>`GET /api/v1/cc/roster/my-schedule`<br>`POST /api/v1/cc/roster/auto-fill`<br>`POST /api/v1/cc/roster/peer-swap/respond` | Xếp lịch tuần tự động bằng thuật toán **MRV + Kuhn's Augmenting Path (BFS-4) + Bitmask 64-bit** (`<50ms`), khóa chống Deadlock bằng `threading.RLock()`, tự động chốt lịch lúc 12:00 trưa Chủ Nhật và hỗ trợ đổi ca chéo 2 bước. |
| **Sổ cái Lương & Giải ngân** | `GET /api/v1/cc/payroll/summary`<br>`POST /api/v1/cc/payroll/ledger`<br>`GET /api/v1/cc/notifications/preview-payslip-card` | Tính lương số nguyên VNĐ, ghi sổ cái bất biến `so_cai_luong` (Triggers cấm `UPDATE`/`DELETE`, chống ghi đúp qua `idempotency_key`), xuất thẻ ảnh Retina kèm VietQR và PDF A5 bằng font `Inter v4.1`. |
| **Chốt két POS & Bản quyền** | `POST /api/v1/cc/pos/daily-closing`<br>`GET /api/v1/license`<br>`GET /health` | Đối soát tiền mặt/chuyển khoản/chi phí cuối ca (chống giả mạo người nộp và khóa biên bản đã duyệt); truy vấn thông tin bản quyền pháp lý `AGPL-3.0-only` & `Commercial License`. |

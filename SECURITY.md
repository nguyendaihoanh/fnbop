# Chính Sách An Ninh & Báo Cáo Lỗ Hổng / Security Policy

[English Version Below](#security-policy-english)

---

# Chính Sách An Ninh (Tiếng Việt)

Dự án **FnBOps** cam kết bảo vệ dữ liệu nhân sự, lịch trực ca và giao dịch tài chính lương của các doanh nghiệp và cửa hàng F&B. Chúng tôi xem việc duy trì và nâng cao an ninh thông tin là một trong những ưu tiên hàng đầu của nền tảng.

---

## 1. Các Phiên Bản Được Hỗ Trợ (Supported Versions)

Chúng tôi cung cấp các bản vá an ninh chủ động và liên tục cho các phiên bản phát hành sau:

| Phiên Bản | Hỗ Trợ An Ninh | Ghi Chú |
| :--- | :---: | :--- |
| **1.0.x (Hiện tại)** | :white_check_mark: Có | Bản phát hành chính thức, nhận các bản vá an ninh khẩn cấp |
| **< 1.0** | :x: Không | Bản thử nghiệm nội bộ |

---

## 2. Báo Cáo Lỗ Hổng An Ninh (Reporting a Vulnerability)

Nếu bạn phát hiện bất kỳ lỗ hổng an ninh tiềm ẩn nào trong dự án FnBOps, **xin vui lòng KHÔNG mở issue công khai trên GitHub**.

Hãy báo cáo qua một trong hai kênh bảo mật bảo mật bí mật sau:

1. **GitHub Private Security Advisory**:
   - Truy cập tab **Security** trên repository của dự án.
   - Nhấn **Report a vulnerability** để mở kênh trao đổi mã hóa trực tiếp với đội ngũ phát triển nòng cốt.

2. **Email Bảo Mật Trực Tiếp**:
   - Gửi thông tin chi tiết tới: `hoanh@vnaigc.com`.
   - Tiêu đề thư: `[VULNERABILITY REPORT] FnBOps - <Mô tả ngắn>`

### Quy trình và Cam kết phản hồi (SLA)
- **48 giờ**: Chúng tôi sẽ phản hồi xác nhận đã nhận được báo cáo và bắt đầu quá trình đánh giá tác động kỹ thuật.
- **7 ngày**: Chúng tôi sẽ cung cấp báo cáo thẩm định ban đầu cùng với kế hoạch khắc phục / phát hành bản vá.
- **Quy trình công bố có trách nhiệm (Coordinated Vulnerability Disclosure)**: Chúng tôi yêu cầu người báo cáo giữ bí mật thông tin về lỗ hổng trong tối thiểu **30 đến 60 ngày** kể từ ngày báo cáo để đội ngũ kịp thời kiểm tra, viết test case và phát hành bản vá bảo vệ người dùng đang vận hành.

---

## 3. Các Tiêu Chuẩn & Cơ Chế An Ninh Được Áp Dụng (Security Safeguards)

FnBOps được thiết kế theo nguyên tắc "Bảo Mật Từ Thiết Kế" (Secure-by-Design) với các lớp phòng thủ chuyên sâu:

1. **Băm Mã PIN PBKDF2 (PBKDF2 PIN Hashing)**:
   - Toàn bộ mã PIN của nhân viên và quản lý được băm bằng thuật toán `PBKDF2-HMAC-SHA256` với `100,000` vòng lặp và muối ngẫu nhiên (salt) 32-byte duy nhất cho từng tài khoản.
   - Không lưu trữ bất kỳ mã PIN hoặc mật khẩu dưới dạng văn bản thuần (plain text).

2. **Khóa Lũy Tiến & Chống Dò Quét Zero-Trust (Tiered Rate Limiting & Brute-Force Shield)**:
   - Hệ thống áp dụng bộ khóa lũy tiến 3 tầng trên IP và tài khoản: Sau 5 lần nhập sai liên tiếp, khóa 60 giây; tái phạm khóa 300 giây và 3600 giây.
   - Chặn đứng hoàn toàn các cuộc tấn công Brute-force và từ chối dịch vụ (DoS) tại tầng Middleware.

3. **Lá Chắn Phân Quyền Vai Trò Nghiêm Ngặt (RBAC Shield)**:
   - Phân cấp 3 vai trò rõ rệt: `ADMIN`, `MANAGER`, `STAFF`.
   - **Bảo mật tiền lương**: Quản lý (`MANAGER`) chỉ được xem số tiền lương của chính mình. Khi kiểm tra nhân viên, giao diện và API ẩn hoàn toàn trường tiền lương VNĐ của nhân sự khác (chỉ hiển thị số ca, giờ làm và trạng thái thanh toán).
   - Khóa sổ kỳ lương cấp Server (`HTTP 423 LOCKED`) ngăn chặn mọi hành vi thay đổi số liệu sau khi kỳ lương đã được quyết toán.

4. **Sổ Cái Bất Biến & Chống Giả Mạo (Anti-Tamper Immutable Ledgers)**:
   - Toàn bộ thao tác ghi nhận công, đổi ca, tạm ứng và chốt két được lưu trữ theo nguyên tắc hạch toán kép (double-entry ledger audit trail).
   - Cơ chế Soft-Delete có kiểm toán: Không cho phép xóa cứng dữ liệu giao dịch; mọi điều chỉnh đều tạo bút toán đảo chiều kèm định danh người thực hiện và mốc thời gian ISO 8601.

5. **Lá Chắn Mạng & Chống Giả Mạo DNS (Ingress & DNS Rebinding Shield)**:
   - Kiểm tra nghiêm ngặt `Host` header và chặn đứng các truy cập từ tên miền lạ (DNS rebinding attack).
   - Chặn tải trực tiếp các tệp cơ sở dữ liệu (`fnbop.db`, `staff_auth.json`, `data.json`) qua Middleware và cấu hình reverse proxy Nginx.

---
---

# Security Policy (English)

The **FnBOps** project is committed to safeguarding employee workforce data, operational schedules, and payroll financial transactions for food and beverage enterprises. Maintaining and continuously hardening our security posture is a foundational priority.

---

## 1. Supported Versions

Active security updates and critical patches are provided for the following releases:

| Version | Supported | Notes |
| :--- | :---: | :--- |
| **1.0.x (Current)** | :white_check_mark: Yes | Official production release; actively maintained |
| **< 1.0** | :x: No | Internal prototypes |

---

## 2. Reporting a Vulnerability

If you discover a security vulnerability in FnBOps, **please DO NOT create a public GitHub issue**.

Please report vulnerabilities using one of our private, encrypted channels:

1. **GitHub Private Security Advisory**:
   - Navigate to the **Security** tab of this repository.
   - Click **Report a vulnerability** to open an encrypted communication channel with the core maintainers.

2. **Direct Security Email**:
   - Send full technical details to: `hoanh@vnaigc.com`.
   - Subject: `[VULNERABILITY REPORT] FnBOps - <Brief description>`

### SLA & Disclosure Timeline
- **48 Hours**: Initial acknowledgment of report receipt and triage initiation.
- **7 Days**: Comprehensive technical impact assessment and proposed remediation plan.
- **Responsible Disclosure**: We respectfully request that reporters observe a **30 to 60 day** embargo period from the initial report date to allow sufficient time for patch authoring, verification, and deployment to production deployments.

---

## 3. Implemented Security Controls & Safeguards

FnBOps is engineered under strict Secure-by-Design principles, featuring multi-tiered defensive controls:

1. **PBKDF2 PIN Hashing**:
   - All employee and manager PINs are hashed using `PBKDF2-HMAC-SHA256` with `100,000` iterations and per-account 32-byte cryptographic salts.
   - Plaintext credentials and predictable fallback passwords are strictly prohibited.

2. **Tiered Rate Limiting & Brute-Force Shield**:
   - Autonomous progressive lockouts on both IP and account dimensions: 5 consecutive failed attempts trigger a 60-second lockout, escalating to 300 seconds and 3600 seconds on repeated failures.
   - Middleware-level ingress protection prevents brute-force credential stuffing and micro-burst DoS attempts.

3. **Role-Based Access Control (RBAC Shield)**:
   - Granular separation across three distinct roles: `ADMIN`, `MANAGER`, `STAFF`.
   - **Wage Privacy**: Managers can only view their own wage numbers. When reviewing staff rosters and attendance, compensation amounts (VNĐ) for other employees are strictly redacted from both API payloads and DOM elements.
   - Authoritative payroll locking (`HTTP 423 LOCKED`) halts mutations once a monthly pay period is closed.

4. **Anti-Tamper Immutable Ledgers**:
   - Attendance events, shift modifications, cash register closings, and advances are stored with double-entry audit trails.
   - Audited Soft-Deletes: Direct destructive operations are blocked; adjustments generate immutable offsetting audit entries with cryptographic actor timestamps.

5. **Ingress & DNS Rebinding Shield**:
   - Strict `Host` header whitelisting prevents DNS rebinding exploits on local networks.
   - Sensitive database artifacts (`fnbop.db`, `staff_auth.json`, `data.json`) are blocked from static file delivery at both the FastAPI middleware and Nginx reverse proxy tiers.

# Hướng Dẫn Đóng Góp Mã Nguồn / Contributing Guide

[English Version Below](#contributing-guide-english)

---

# Hướng Dẫn Đóng Góp Mã Nguồn (Tiếng Việt)

Cảm ơn bạn đã quan tâm đến việc đóng góp cho dự án **FnBOps**! Chúng tôi hoan nghênh mọi đóng góp từ cộng đồng nhằm xây dựng một nền tảng vận hành và quản lý nhân sự F&B mã nguồn mở, mạnh mẽ, an toàn và chuẩn quốc tế.

Dự án được phát hành theo mô hình **Cấp phép Kép (Dual-Licensing)**: mã nguồn mở cộng đồng theo giấy phép [GNU Affero General Public License v3.0 only (`AGPL-3.0-only`)](LICENSE) và giấy phép Thương mại / Doanh nghiệp (`Commercial License` qua `hoanh@vnaigc.com`).

### Thỏa Thuận Đóng Góp Mã Nguồn (Contributor License Agreement — CLA)
Khi gửi Pull Request, bản vá hoặc bất kỳ đóng góp nào vào dự án `FnBOps`, bạn xác nhận và đồng ý với các điều khoản sau:
1. **Quyền sở hữu gốc (Developer Certificate of Origin):** Đóng góp là tác phẩm gốc do chính bạn tạo ra (hoặc bạn có đầy đủ thẩm quyền pháp lý từ tổ chức/công ty chủ quản để đóng góp), và không xâm phạm bản quyền, bằng sáng chế hay bí mật thương mại của bất kỳ bên thứ ba nào.
2. **Giữ quyền tác giả & Cấp phép song song (CLA Grant):** Bạn vẫn giữ nguyên quyền tác giả đối với phần đóng góp của mình; đồng thời bạn cấp cho chủ sở hữu dự án — **Nguyen Dai Hoanh (VNAIGC)** (`hoanh@vnaigc.com`) — một giấy phép vĩnh viễn, trên phạm vi toàn cầu, không độc quyền, miễn phí bản quyền (royalty-free), không thể hủy ngang trên quyền tác giả và bằng sáng chế liên quan để sử dụng, sửa đổi, phân phối lại và cấp phép lại phần đóng góp đó dưới cả giấy phép mã nguồn mở **`AGPL-3.0-only`** lẫn các **Giấy phép Thương mại / OEM** của dự án, với cam kết phiên bản cộng đồng của `FnBOps` luôn được duy trì mã nguồn mở.

---

## 1. Kiến Trúc Mã Nguồn (Code Architecture)

Hệ thống FnBOps được thiết kế theo nguyên tắc phân tầng rõ ràng (Layered Architecture), tối ưu hóa cho môi trường F&B yêu cầu khả năng tự trị cao, tốc độ phản hồi mili-giây và độ tin cậy tuyệt đối:

- **Backend (FastAPI & Python 3.11+)**:
  - `backend/main.py`: Entrypoint API Gateway (cổng 8100), thiết lập Middleware (CORS, Static Shield, Security Headers, Rate Limiting).
  - `backend/routers/`: Tách biệt các router nghiệp vụ (`fnb_ops.py`, `attendance.py`, `roster.py`, `excel_routes.py`, `notification_routes.py`, `push_routes.py`).
  - `backend/services/`: Lớp logic xử lý chuyên sâu (`payroll_calc.py`, `db/`, `background_worker.py`, `payslip_card_generator.py`, `store_config.py`).
  - **Dữ liệu & CSDL**: SQLite ở chế độ WAL (`Write-Ahead Logging`) đặt tại `data/fnbop.db`. Kiểm soát đồng thời bằng `FileLock` và `threading.RLock` để bảo đảm giao dịch ACID.
- **Frontend (Modular PWA & Vanilla JavaScript ES Modules)**:
  - `frontend/src/`: Cấu trúc module hóa (`api/`, `modules/`, `store/`, `utils/`).
  - `frontend/mobile.js` & `frontend/app.js`: Entrypoints tương ứng cho Mobile PWA và Desktop Web.
  - `frontend/build.js`: Pipeline đóng gói bằng `esbuild`, tạo bundle tối ưu `< 800KB`, tự động kiểm tra Zero-Trust leak.
  - Hỗ trợ đầy đủ Light/Dark Theme và đa ngôn ngữ i18n (VI, EN, TH, ZH, RU).
- **Zalo Gateway Microservice**:
  - `backend/zalo_gateway/`: Node.js 18+ REST server quản lý phiên Zalo Web và webhook gửi tin nhắn/ảnh bảng lương tự động.

---

## 2. Thiết Lập Môi Trường Phát Triển Cục Bộ (Local Setup)

### Yêu cầu tiên quyết (Prerequisites)
- **Python**: Phiên bản `3.11` trở lên (Khuyến nghị `3.11` hoặc `3.12`).
- **Node.js**: Phiên bản `18.x` hoặc `20.x` LTS.
- **Git**: Đã cài đặt trên máy.
- **Docker & Docker Compose** *(Tùy chọn nếu muốn chạy container hóa)*.

### Các bước cài đặt chi tiết
1. **Clone repository về máy**:
   ```bash
   git clone https://github.com/nguyendaihoanh/fnbop.git
   cd fnbop
   ```

2. **Cấu hình môi trường ảo Python**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install --upgrade pip
   pip install -e ".[dev]"
   ```

3. **Cài đặt thư viện Frontend**:
   ```bash
   cd frontend
   npm install
   cd ..
   ```

4. **Khởi tạo file cấu hình môi trường & Git Pre-Push Hook**:
   ```bash
   cp .env.example .env
   bash scripts/install_git_hooks.sh
   ```
   *Lưu ý: Hệ thống tự động sinh `JWT_SECRET_KEY` 256-bit ngẫu nhiên ở lần chạy đầu tiên nếu chưa cấu hình.*

5. **Đóng gói Frontend lần đầu**:
   ```bash
   node frontend/build.js
   ```

6. **Khởi chạy máy chủ Backend**:
   ```bash
   python3 backend/main.py
   ```
   - Giao diện người dùng: `http://localhost:8100` (hoặc `http://localhost:8080`)
   - Tài liệu API (Swagger UI): `http://localhost:8100/docs`

---

## 3. Quy Chuẩn Lập Trình (Coding Standards)

- **Ngôn ngữ trong mã nguồn**:
  - Mã nguồn (tên biến, hàm, lớp, commit message): **100% Tiếng Anh**.
  - Chú thích (comments) và tài liệu nội bộ: Tiếng Anh hoặc song ngữ VI/EN.
- **Quy chuẩn Python**:
  - Tuân thủ nghiêm ngặt **PEP 8**.
  - Sử dụng Type Hints (`typing`) cho tham số và giá trị trả về của hàm.
  - Sử dụng Pydantic v2 schemas cho mọi request/response payload.
- **Quy chuẩn Frontend / JavaScript**:
  - Chuẩn ES2020+ Modules, cú pháp `async/await`.
  - Không chèn inline JavaScript không an toàn vào DOM (`innerHTML` với dữ liệu chưa được làm sạch).
  - Không hardcode các chuỗi văn bản giao diện (phải sử dụng i18n bundle).
- **Quy định an toàn tuyệt đối về Bí Mật (Zero-Secrets Policy)**:
  - **TUYỆT ĐỐI KHÔNG** commit file cấu hình thực tế, mật khẩu, JWT secret key, API key hoặc token vào Git.
  - Mọi bí mật bắt buộc phải nạp qua biến môi trường (`os.getenv`).
- **Quy định về Emoji**:
  - **TUYỆT ĐỐI KHÔNG** dùng emoji trong logic code (tên biến, chuỗi log, exception messages, tên hàm). Emoji chỉ được phép xuất hiện trong UI templates khi cần thiết.

---

## 4. Quy Chuẩn Kiểm Thử (Testing Standards)

Trước khi gửi bất kỳ đóng góp nào, bạn phải đảm bảo toàn bộ bộ kiểm thử chạy thành công 100%:

### Kiểm thử Backend (Pytest)
Hệ thống bao gồm hơn 380 bài kiểm thử tự động bao quát logic chấm công, tính lương, phân ca và an ninh:
```bash
JWT_SECRET_KEY=test_secret_key_12345678901234567890 PYTHONPATH=.:backend pytest tests/
```

### Đóng gói & Kiểm tra an ninh Frontend (Zero-Trust Leak Check)
Chạy script đóng gói frontend để kiểm tra cú pháp và khẳng định không có secret nào bị lọt vào file dist:
```bash
node frontend/build.js
```
Kết quả mong đợi:
```text
✓ mobile.bundle.js compiled successfully.
✓ app.min.js compiled successfully.
✓ Zero-Trust Verification passed: 0 secret keys present in dist artifacts.
```

### Yêu cầu viết test cho tính năng mới
- Mọi tính năng mới hoặc sửa lỗi (bugfix) đều phải đi kèm ít nhất một test case trong thư mục `tests/`.
- Test case phải cô lập trạng thái, sử dụng cơ sở dữ liệu tạm thời (in-memory hoặc temp file) và dọn dẹp sau khi chạy.

---

## 5. Quy Chuẩn Git Commit & Pull Request

### Định dạng Commit (Conventional Commits)
Thông điệp commit phải tuân thủ chuẩn Conventional Commits:
```text
<loại>(<phạm vi>): <mô tả ngắn bằng tiếng Anh>

[nội dung chi tiết nếu có]
```
Các tiền tố hợp lệ:
- `feat`: Tính năng mới (ví dụ: `feat(roster): add dynamic barista shift constraint`)
- `fix`: Sửa lỗi (ví dụ: `fix(payroll): prevent double deduction on hanging shift`)
- `refactor`: Tái cấu trúc mã nguồn mà không đổi hành vi
- `perf`: Cải thiện hiệu năng xử lý hoặc tối ưu dung lượng bundle
- `test`: Thêm hoặc chỉnh sửa bộ kiểm thử
- `docs`: Cập nhật tài liệu kỹ thuật hoặc hướng dẫn
- `chore`: Thay đổi quy trình build, package config hoặc CI workflow

### Quy trình gửi Pull Request (PR Workflow)
1. Fork repository và tạo nhánh mới từ `develop` hoặc `main`:
   ```bash
   git checkout -b feat/ten-tinh-nang-moi
   ```
2. Thực hiện các chỉnh sửa, bổ sung kiểm thử và xác nhận chất lượng.
3. Chạy toàn bộ test suite và build frontend để kiểm tra.
4. Đẩy nhánh lên fork của bạn và mở Pull Request hướng về nhánh đích.
5. Điền đầy đủ thông tin vào mẫu [Pull Request Template](.github/pull_request_template.md).

---
---

# Contributing Guide (English)

Thank you for your interest in contributing to **FnBOps**! We welcome all contributions to make this open-source F&B operations, intelligent scheduling, and automated payroll management platform robust, secure, and production-ready.

This project is published under a **Dual-Licensing** model: community open-source under the [GNU Affero General Public License v3.0 only (`AGPL-3.0-only`)](LICENSE) and Commercial / Enterprise licensing (`hoanh@vnaigc.com`).

### Contributor License Agreement (CLA)
By submitting a Pull Request, patch, or other contribution to `FnBOps`, you certify and agree that:
1. **Developer Certificate of Origin:** Your contribution is your original creation (or you have full legal authority from your employer to submit it) and does not infringe any third-party copyright, patent, or trade secret.
2. **Copyright Retention & Dual-Licensing Grant:** You retain ownership of your copyright while granting the project copyright holder — **Nguyen Dai Hoanh (VNAIGC)** (`hoanh@vnaigc.com`) — a perpetual, worldwide, non-exclusive, royalty-free, irrevocable copyright and patent license to reproduce, modify, redistribute, and relicense your contribution under both **`AGPL-3.0-only`** and commercial/enterprise licenses, with the commitment that the community edition of `FnBOps` remains open-source.

---

## 1. Code Architecture

FnBOps follows a clean, layered architectural pattern engineered for high autonomy, millisecond response times, and bulletproof offline resilience:

- **Backend (FastAPI & Python 3.11+)**:
  - `backend/main.py`: Core API Gateway entrypoint (port 8100), configuring Middleware (CORS, Static Shield, Security Headers, Rate Limiting).
  - `backend/routers/`: Domain-driven API routing (`fnb_ops.py`, `attendance.py`, `roster.py`, `excel_routes.py`, `notification_routes.py`, `push_routes.py`).
  - `backend/services/`: Authoritative business logic (`payroll_calc.py`, `db/`, `background_worker.py`, `payslip_card_generator.py`, `store_config.py`).
  - **Storage & Database**: SQLite WAL mode (`Write-Ahead Logging`) located at `data/fnbop.db`. Concurrency controlled via `FileLock` and `threading.RLock` ensuring ACID transactions.
- **Frontend (Modular PWA & Vanilla JavaScript ES Modules)**:
  - `frontend/src/`: Modular architecture (`api/`, `modules/`, `store/`, `utils/`).
  - `frontend/mobile.js` & `frontend/app.js`: Entrypoints for Mobile PWA and Desktop Admin interfaces.
  - `frontend/build.js`: `esbuild` bundling pipeline with sub-800KB bundle footprint and automated Zero-Trust leak assertions.
  - Full support for Light/Dark mode and runtime i18n localization (VI, EN, TH, ZH, RU).
- **Zalo Gateway Microservice**:
  - `backend/zalo_gateway/`: Node.js 18+ service managing encrypted Zalo Web sessions and automated payslip card deliveries.

---

## 2. Local Development Setup

### Prerequisites
- **Python**: Version `3.11` or higher (Recommended: `3.11` or `3.12`).
- **Node.js**: Version `18.x` or `20.x` LTS.
- **Git**: Installed and configured.
- **Docker & Docker Compose** *(Optional for containerized runtimes)*.

### Setup Steps
1. **Clone the repository**:
   ```bash
   git clone https://github.com/nguyendaihoanh/fnbop.git
   cd fnbop
   ```

2. **Configure Python Virtual Environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install --upgrade pip
   pip install -e ".[dev]"
   ```

3. **Install Frontend Dependencies**:
   ```bash
   cd frontend
   npm install
   cd ..
   ```

4. **Initialize Environment Configuration & Git Pre-Push Hook**:
   ```bash
   cp .env.example .env
   bash scripts/install_git_hooks.sh
   ```
   *Note: FnBOps automatically bootstraps a cryptographically random 256-bit `JWT_SECRET_KEY` on first startup if omitted.*

5. **Build the Frontend**:
   ```bash
   node frontend/build.js
   ```

6. **Start the Backend Server**:
   ```bash
   python3 backend/main.py
   ```
   - Application Web UI: `http://localhost:8100` (or `http://localhost:8080`)
   - Interactive API Docs: `http://localhost:8100/docs`

---

## 3. Coding Standards

- **Code Language**:
  - Code (identifiers, variable names, functions, commit messages): **100% English**.
  - Comments & Documentation: English or bilingual (VI/EN).
- **Python Guidelines**:
  - Strict compliance with **PEP 8**.
  - Explicit Type Annotations (`typing`) on public methods and functions.
  - Pydantic v2 schemas for all incoming and outgoing API contracts.
- **Frontend Guidelines**:
  - ES2020+ Modules, pure `async/await` patterns.
  - Never inject unsanitized HTML into the DOM.
  - Never hardcode user-facing strings; use i18n resource dictionaries.
- **Security & Secret Management (Zero-Secrets Policy)**:
  - **NEVER** commit real secrets, private keys, passwords, or production tokens.
  - All credentials must be read from environment variables via `os.getenv`.
- **Emoji Usage**:
  - **NEVER** use emojis inside code logic (function names, variables, logs, error exceptions). Emojis are reserved exclusively for UI presentation layers.

---

## 4. Testing Standards

All pull requests must pass the full test suite before consideration:

### Running Backend Tests
Execute over 380 unit and integration tests covering attendance, payroll, scheduling, and security:
```bash
JWT_SECRET_KEY=test_secret_key_12345678901234567890 PYTHONPATH=.:backend pytest tests/
```

### Frontend Build & Zero-Trust Leak Verification
```bash
node frontend/build.js
```
Expected output:
```text
✓ mobile.bundle.js compiled successfully.
✓ app.min.js compiled successfully.
✓ Zero-Trust Verification passed: 0 secret keys present in dist artifacts.
```

### Writing Tests for New Code
- Every new feature or bugfix requires corresponding automated tests in `tests/`.
- Tests must use isolated temporary resources (mock databases or in-memory tables) and clean up afterwards.

---

## 5. Git Commit & Pull Request Guidelines

### Conventional Commits
Commit messages must follow the Conventional Commits specification:
```text
<type>(<scope>): <short summary in imperative mood>

[optional body providing technical context]
```
Valid prefixes:
- `feat`: New user-facing or architectural feature
- `fix`: Bug fix
- `refactor`: Code reorganization without functional changes
- `perf`: Performance improvement or bundle size reduction
- `test`: Adding or modifying automated tests
- `docs`: Updating documentation or operational guides
- `chore`: Tooling, build pipeline, or CI adjustments

### Pull Request Workflow
1. Fork the repository and create your feature branch from `main` or `develop`:
   ```bash
   git checkout -b feat/your-feature-name
   ```
2. Implement your changes, adhere to coding standards, and include unit tests.
3. Verify that all tests pass and frontend builds cleanly.
4. Push your branch to GitHub and open a Pull Request.
5. Complete the checklist in the [Pull Request Template](.github/pull_request_template.md).

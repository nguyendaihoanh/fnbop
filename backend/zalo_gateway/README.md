# Zalo Gateway Microservice

Microservice xử lý kết nối và gửi thông báo qua Zalo cho hệ thống F&B Standalone On-Premise.

## 1. Đặc Tính Kỹ Thuật
- **Ngôn ngữ:** Node.js (Express, CORS, QRCode, Dotenv).
- **Dung lượng bộ nhớ (Memory Footprint):** < 60MB RAM (Heap ~10MB, cờ V8 `--max-old-space-size=64`).
- **Cổng mặc định:** `8177`.
- **Cơ chế lưu trữ:** Tự động tạo và lưu trữ session tại `data/zalo_session/session.json`.
- **Vận hành độc lập:** Chạy cục bộ độc lập trên máy chủ hoặc máy POS tại cửa hàng.

## 2. Danh Sách Endpoint

| Phương thức | Đường dẫn | Chức năng | Phản hồi mẫu |
|-------------|-----------|-----------|--------------|
| `GET` | `/health` | Kiểm tra tình trạng dịch vụ & RAM | `{"status":"ok","service":"zalo-gateway","memory":{...}}` |
| `GET` | `/api/zalo/status` | Lấy trạng thái phiên hiện tại | `{"status":"ready"|"waiting_qr"|"disconnected","connected":true}` |
| `GET` | `/api/zalo/qr` | Sinh mã QR Base64 quét đăng nhập | `{"success":true,"status":"waiting_qr","qr_code":"data:image/png;base64,..."}` |
| `POST` | `/api/zalo/send` | Gửi tin nhắn / phiếu lương | `{"success":true,"msg_id":"zalo_msg_...","status":"delivered"}` |
| `POST` | `/api/zalo/logout` | Xóa phiên và đưa về trạng thái ngắt kết nối | `{"success":true,"status":"disconnected","connected":false}` |
| `POST` | `/api/zalo/confirm-qr` | Xác thực quét QR (Dành cho Webhook / Test) | `{"success":true,"status":"ready","connected":true}` |

## 3. Khởi Chạy

### Chạy trực tiếp qua Node.js:
```bash
npm install
npm start
```

### Chạy kiểm thử tự động:
```bash
npm test
```

### Chạy qua Docker Container (Chỉ mở trên Loopback nội bộ):
```bash
docker build -t cc-zalo-gateway .
docker run -p 127.0.0.1:8177:8177 -v $(pwd)/data/zalo_session:/app/data/zalo_session cc-zalo-gateway
```

## 4. Bảo Mật Nội Bộ, Giấy Phép `AGPL-3.0-only` & Tuyên Bố Pháp Lý

- **Cơ chế bảo mật Zero-Trust:**
  - Khi chạy trực tiếp trên máy chủ/máy POS (ngoài Docker), dịch vụ mặc định chỉ lắng nghe trên giao diện nội bộ `127.0.0.1:8177` (có thể ghi đè qua `ZALO_GATEWAY_HOST`), chặn truy cập trái phép từ mạng WiFi khách.
  - Hỗ trợ xác thực khóa nội bộ qua biến môi trường `ZALO_GATEWAY_TOKEN` (Header `X-Zalo-Gateway-Token`).
  - Thư mục phiên `data/zalo_session/` được thiết lập quyền hạn chế `0700` và tệp `session.json` ở mức `0600`.
- **Giấy phép & Ranh giới Tích hợp Bên Thứ 3 (`AGPL-3.0-only` + IPC Boundary):**
  - Mã nguồn `backend/zalo_gateway/` thuộc bản quyền `Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC)` và phát hành theo giấy phép **`AGPL-3.0-only`** (hoặc Giấy phép Thương mại qua `hoanh@vnaigc.com`). Mọi hành vi sửa đổi trực tiếp `server.js` để cung cấp dịch vụ mạng phải công khai mã nguồn theo Điều 13 `AGPL-3.0`.
  - **Ranh giới Adapter độc lập:** `FnBOps` Core giao tiếp với cổng nhắn tin hoàn toàn qua giao thức chuẩn HTTP JSON (`ZALO_GATEWAY_URL`). Nếu bên thứ ba tự xây dựng độc lập từ đầu một dịch vụ Zalo Official Account (OA) / Zalo Cloud ZNS riêng và kết nối qua HTTP JSON mà không sao chép hay sửa đổi mã nguồn `FnBOps`, dịch vụ độc lập đó không bị ràng buộc bởi `AGPL-3.0`.
- **Miễn trừ Trách nhiệm Nền tảng, Nhãn hiệu & Dữ liệu Cá nhân:**
  - **"Zalo"** là nhãn hiệu đã đăng ký của **Công ty Cổ phần VNG (VNG Corporation)**. Dự án `FnBOps` và `VNAIGC` hoàn toàn độc lập, không có sự liên kết, tài trợ hay chứng thực từ VNG/Zalo.
  - Module này được **tắt mặc định (Disabled-by-Default)**. Thư viện cộng đồng `zca-js` (`MIT`) sử dụng phiên Zalo Web cá nhân thay vì cổng ZNS/OA thương mại chính thức; người vận hành tự quyết định kích hoạt và chịu hoàn toàn trách nhiệm tuân thủ Điều khoản Sử dụng (ToS) của Zalo cũng như nghĩa vụ bảo vệ dữ liệu cá nhân của người lao động theo **Nghị định 13/2023/NĐ-CP**. Với hệ thống chuỗi quy mô lớn, khuyến nghị sử dụng cổng **Zalo Cloud ZNS / Zalo OA API** chính thức.


# SOP: Xử Lý Sự Cố Kỹ Thuật & POS Heartbeat

## 1. Mất Kết Nối Wi-Fi / Internet
- **Hiện tượng:** Không thể check-in trên webapp, máy POS báo offline.
- **Xử lý nhanh:**
  1. Kiểm tra nguồn modem Wi-Fi chính và Router phụ.
  2. Khởi động lại Router nếu đèn Internet nhấp nháy đỏ quá 2 phút.
  3. Trong thời gian chờ mạng, ghi nhận giờ vào ca thủ công vào sổ giao ca giấy.

## 2. Cảnh Báo Treo Ca / POS Mất Kết Nối Heartbeat
- **Hiện tượng:** Bot Telegram FnBOps bắn cảnh báo `POS Heartbeat Lost` hoặc `Ca chưa đóng sau 23:00`.
- **Xử lý nhanh:**
  1. Kiểm tra màn hình POS xem tiến trình `wfm_pos_heartbeat.ps1` có bị tắt không.
  2. Bật lại script heartbeat hoặc thông báo Quản lý kỹ thuật để khởi động lại dịch vụ từ xa.

## 3. Máy In Hóa Đơn Bị Kẹt / Hết Giấy
- Mở nắp máy in, gạt chốt cắt giấy, kiểm tra cuộn giấy nhiệt K80 đúng chiều. Đóng chặt nắp đến khi nghe tiếng click.

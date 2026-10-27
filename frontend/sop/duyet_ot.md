# SOP: Quy Trình Duyệt Giờ Làm & Tăng Ca (OT)

## 1. Định Nghĩa Ca Tăng Ca (OT)
- Thời gian làm thêm phát sinh khi cửa hàng quá tải khách, sự kiện đột xuất, hoặc thay ca cho đồng nghiệp vắng mặt.
- Mọi giờ làm thêm chỉ được tính là OT hợp lệ khi có **sự phê duyệt trước hoặc xác nhận trong ca** của Quản lý ca trực (Shift Leader).

## 2. Tiêu Chuẩn Tính Lương Tăng Ca
- **OT ngày thường:** Tính theo hệ số 1.0x hoặc 1.2x (tùy vị trí và thỏa thuận ca gãy).
- **OT ngày Lễ/Tết:** Tính theo hệ số 2.0x - 3.0x theo quy chế vận hành chung của hệ thống.
- Hệ thống **FnBOps** tự động tính lũy kế quỹ lương OT hiển thị minh bạch tại màn hình Admin.

## 3. Luồng Phê Duyệt OT Trên Hệ Thống
1. **Ghi nhận:** Khi ra ca muộn hơn giờ kết thúc ca chính thức trên 30 phút, hệ thống tự động gắn cờ `OT Pending`.
2. **Kiểm tra:** Quản lý đăng nhập vào cổng Quản Trị Chấm Công, kiểm tra lý do tăng ca thực tế.
3. **Phê duyệt:** Bấm nút **Duyệt OT** trước kỳ chốt lương tuần (Thứ Hai hàng tuần). Các giờ OT chưa duyệt sẽ được giữ ở trạng thái chờ đối soát.

# Commercial License & Copyright Policy / Giấy phép thương mại & Chính sách bản quyền

> **Languages:** [Tiếng Việt](#tiếng-việt) | [English](#english)
>
> This document explains how FnBOps is licensed. It does not modify [LICENSE](LICENSE) (AGPL-3.0-only, verbatim). The additional terms permitted by AGPL-3.0 Section 7 are stated in [NOTICE](NOTICE); brand use is covered by [TRADEMARKS.md](TRADEMARKS.md).

---

<a name="tiếng-việt"></a>
## Phần I — Tiếng Việt

### 1. Chủ sở hữu quyền tác giả

| Thông tin | Chi tiết |
| :--- | :--- |
| Tác giả, chủ sở hữu quyền tác giả | **Nguyễn Đại Hoành** |
| Pháp nhân cấp phép thương mại | **Công ty TNHH Thiết bị bay và Công nghệ VNAIGC**, MST **4101699631** |
| Địa chỉ | 1032 Trần Hưng Đạo, Phường Quy Nhơn, Tỉnh Gia Lai, Việt Nam |
| Liên hệ cấp phép, pháp chế | **hoanh@vnaigc.com** |
| Kho mã nguồn chính thức | https://github.com/nguyendaihoanh/fnbop |

FnBOps là chương trình máy tính, được bảo hộ quyền tác giả theo Luật Sở hữu trí tuệ Việt Nam (Luật số 50/2005/QH11, sửa đổi, bổ sung các năm 2009, 2019 và 2022) cùng Nghị định 17/2023/NĐ-CP, và được bảo hộ quốc tế theo Công ước Berne.

### 2. Mô hình cấp phép kép

**Lựa chọn A — AGPL-3.0-only (miễn phí).** Phù hợp cho:
- Chủ cửa hàng tự cài đặt và vận hành nội bộ.
- Lập trình viên nghiên cứu, cải tiến và chia sẻ lại cho cộng đồng.
- Đơn vị IT thu phí cài đặt, cấu hình, bảo trì, miễn là bàn giao đầy đủ mã nguồn và giữ nguyên ghi công tác giả.

Nghĩa vụ chính khi dùng theo AGPL-3.0-only:
1. **Điều 13 — Sử dụng qua mạng:** nếu bạn *sửa đổi* FnBOps rồi cho người khác dùng qua mạng (Internet, cloud hoặc LAN), bạn phải cung cấp mã nguồn tương ứng của bản đã sửa cho chính những người dùng đó, theo cùng giấy phép.
2. **Điều 4–6 — Phân phối:** khi chuyển giao bản sao (nguyên bản hoặc đã sửa), phải kèm giấy phép và mã nguồn, đồng thời giữ nguyên các thông báo bản quyền.
3. **Điều khoản bổ sung theo Điều 7 (xem [NOTICE](NOTICE)):** giữ dòng ghi công "Powered by FnBOps - Nguyen Dai Hoanh (VNAIGC)" trên giao diện; đánh dấu rõ bản đã sửa đổi; không được dùng tên và logo FnBOps làm thương hiệu (xem [TRADEMARKS.md](TRADEMARKS.md)).

**Lựa chọn B — Giấy phép thương mại (ký hợp đồng bằng văn bản).** Cần thiết khi bạn muốn làm các việc mà AGPL-3.0 không cho phép, hoặc không muốn chịu nghĩa vụ công khai mã nguồn:
- Vận hành dịch vụ SaaS hoặc multi-tenant thu phí mà không công bố mã nguồn đã sửa đổi.
- Đóng gói FnBOps vào phần mềm hoặc thiết bị POS mã nguồn đóng (OEM, bundling).
- Phân phối dưới thương hiệu riêng (white-label) có dùng tên hoặc logo FnBOps, hoặc cần miễn trừ nghĩa vụ ghi công.

### 3. Tình huống thường gặp

| Tình huống | Theo AGPL-3.0-only | Có cần giấy phép thương mại? |
| :--- | :--- | :--- |
| Quán tự cài, dùng nội bộ, không sửa code | Được phép | Không |
| Fork, thêm tính năng, công khai mã nguồn theo AGPL | Được phép (giữ ghi công, đánh dấu bản sửa đổi, đặt tên riêng nếu phân phối) | Không |
| Đơn vị IT cài đặt có thu phí, bàn giao đủ mã nguồn | Được phép | Không |
| Sửa code rồi chạy SaaS cho nhiều quán nhưng giữ kín code | Vi phạm Điều 13 | Có |
| Xóa tên tác giả, gắn tên/logo riêng để bán | Vi phạm Điều 7(b), 7(c), 7(e); xâm phạm quyền nhân thân của tác giả | Có (và vẫn phải tôn trọng quyền nhân thân) |

### 4. Khi xảy ra vi phạm

1. **Chấm dứt giấy phép (Điều 8 AGPL-3.0):** vi phạm làm chấm dứt các quyền đã được cấp theo AGPL. Quyền có thể được khôi phục nếu bên vi phạm chấm dứt hành vi và khắc phục theo đúng thời hạn quy định tại Điều 8 (khôi phục tạm thời ngay khi dừng vi phạm, và trở thành vĩnh viễn nếu không bị thông báo trong 60 ngày; hoặc khắc phục trong 30 ngày kể từ lần đầu nhận thông báo). Tiếp tục sử dụng hay phân phối sau khi giấy phép đã chấm dứt là sử dụng không có giấy phép.
2. **Bằng chứng:** header SPDX trong mã nguồn, header HTTP `X-FnBOps-License`, endpoint `/api/v1/license`, lịch sử commit công khai trên GitHub.
3. **Biện pháp theo pháp luật Việt Nam:** yêu cầu chấm dứt hành vi và gỡ bỏ nội dung (kể cả gửi yêu cầu gỡ bỏ tới GitHub và nhà cung cấp hosting); đề nghị xử phạt hành chính theo Nghị định 17/2023/NĐ-CP; khởi kiện dân sự đòi bồi thường thiệt hại theo các Điều 198, 202, 204, 205 Luật Sở hữu trí tuệ; với hành vi ở quy mô thương mại, có thể đề nghị xem xét trách nhiệm hình sự theo Điều 225 Bộ luật Hình sự.

### 5. Liên hệ
Cấp phép thương mại, hợp tác OEM hoặc câu hỏi pháp lý: **hoanh@vnaigc.com**.

---

<a name="english"></a>
## Part II — English

### 1. Copyright holder
FnBOps is Copyright (C) 2026 **Nguyen Dai Hoanh**. Commercial licenses are granted through **VNAIGC Drone & Tech Co., Ltd** (Tax ID **4101699631**). Contact: **hoanh@vnaigc.com**. Official source: https://github.com/nguyendaihoanh/fnbop.

### 2. Dual licensing
**Option A — AGPL-3.0-only (free of charge).** Use, study, modify, and share FnBOps under the [GNU Affero General Public License v3.0 only](LICENSE), plus the Section 7 additional terms in [NOTICE](NOTICE):
- **Section 13:** if you modify FnBOps and let users interact with it over a network, you must offer those users the Corresponding Source of your modified version.
- **Sections 4–6:** when you convey copies, include the license and the source, and keep all notices intact.
- **Section 7 additional terms:** keep the "Powered by FnBOps - Nguyen Dai Hoanh (VNAIGC)" attribution in the UI, mark modified versions as changed, and do not use the FnBOps name or logo as your own brand ([TRADEMARKS.md](TRADEMARKS.md)).

**Option B — Commercial license (written agreement).** For use cases that AGPL-3.0 does not allow, or where you prefer not to publish source:
- Hosted SaaS or multi-tenant services that keep modifications private.
- Closed-source POS software or hardware bundles (OEM).
- White-label distribution that uses the FnBOps brand, or that needs an exception to the attribution requirement.

### 3. Termination (Section 8)
A violation terminates your rights under AGPL-3.0. As provided in Section 8, rights are reinstated if you stop the violation and cure it within the stated periods (provisional reinstatement on cessation, made permanent if you are not notified within 60 days; or cure within 30 days after a first notice). Continuing to use or distribute after termination is unlicensed use.

### 4. Contact
Commercial licensing, OEM partnerships, and legal questions: **hoanh@vnaigc.com**.

---

*This document summarizes the license for convenience. If it conflicts with [LICENSE](LICENSE) or [NOTICE](NOTICE), the LICENSE and NOTICE texts prevail. It is not legal advice.*

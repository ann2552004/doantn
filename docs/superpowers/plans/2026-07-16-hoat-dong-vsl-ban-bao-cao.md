# Hoạt động VSL – bản báo cáo đọc rõ Implementation Plan

> **For agentic workers:** Execute this plan task-by-task with visual checkpoints; the workspace is a standalone Windows folder and has no Git repository/worktree.

**Goal:** Tạo bộ `BAN_DAY_DU` giữ toàn bộ H2.26–H2.30 và bộ `BAN_BAO_CAO` chia panel ngang, font Times New Roman lớn, crop sát và đọc được khi chèn Word rộng 24,5–25,5 cm.

**Architecture:** Dùng một bộ dựng Python tạo phần tử Excalidraw độc lập, renderer SVG vector và renderer PNG. Bộ full dùng các flow hiện có; bộ báo cáo dựng panel riêng theo các phân đoạn nghiệp vụ, dùng connector A/B/C giữa panel thay cho đường nối xuyên trang.

**Tech Stack:** Python 3, Pillow, JSON Excalidraw v2, SVG thủ công với font Times New Roman, CLI `mcp-excalidraw-server` để import/screenshot kiểm tra canvas.

## Global Constraints

- Thư mục mới: `C:\do an\bieu_do_hoat_dong_vsl_ban_doc_ro_trong_bao_cao\`.
- Mỗi panel có `.excalidraw`, `.svg`, `.png`; bản báo cáo PNG rộng 3000–3800 px.
- Font title 38–44 px, lane/nhóm 30–34 px, activity 28–32 px, decision 27–30 px, guard 25–28 px.
- Không có phần tử raster/image trong Excalidraw; mọi khối, connector, nhãn và connector A/B/C chỉnh sửa được.
- Panel tối đa 12–16 khối hoạt động, 4–6 quyết định; tỷ lệ ưu tiên ngang 1,25:1–1,65:1 và crop lề 45–70 px.
- SVG có viewBox theo bounds; nền trắng; không dùng font viết tay.

### Task 1: Xây thư mục và mô hình panel

**Files:**
- Create: `C:\do an\build_activity_vsl_report_panels.py`
- Create: `C:\do an\bieu_do_hoat_dong_vsl_ban_doc_ro_trong_bao_cao\BAN_BAO_CAO\EXCALIDRAW\`
- Create: `C:\do an\bieu_do_hoat_dong_vsl_ban_doc_ro_trong_bao_cao\BAN_BAO_CAO\SVG\`
- Create: `C:\do an\bieu_do_hoat_dong_vsl_ban_doc_ro_trong_bao_cao\BAN_BAO_CAO\PNG\`
- Create: `C:\do an\bieu_do_hoat_dong_vsl_ban_doc_ro_trong_bao_cao\BAN_DAY_DU\EXCALIDRAW\`
- Create: `C:\do an\bieu_do_hoat_dong_vsl_ban_doc_ro_trong_bao_cao\BAN_DAY_DU\SVG\`
- Create: `C:\do an\bieu_do_hoat_dong_vsl_ban_doc_ro_trong_bao_cao\BAN_DAY_DU\PNG\`

- [ ] Định nghĩa Node/Diagram với start, final, activity, decision, connector, guard và connector A/B/C.
- [ ] Xuất Excalidraw v2, SVG và PNG từ cùng dữ liệu phần tử; không dùng ảnh nền.
- [ ] Dùng crop bounds và thêm lề 60 px; đặt font tối thiểu theo constraint.

### Task 2: Dựng bộ báo cáo H2.26–H2.30

**Files:**
- Modify: `C:\do an\build_activity_vsl_report_panels.py`

- [ ] Tạo H2.26a/b/c theo ba phân đoạn khởi tạo–frame, từng phương tiện, tổng hợp–VSL; cuối panel dùng connector A/B.
- [ ] Tạo H2.27a/b theo chọn–điều chỉnh và kiểm tra–lưu; connector A.
- [ ] Tạo H2.28a/b theo ghi thời điểm và tính–kiểm tra–lưu; công thức ở khối riêng; connector A.
- [ ] Tạo H2.29a/b/c theo chuẩn hóa dữ liệu, điều chỉnh điều kiện và thủ công–gửi biển báo; connector A/B.
- [ ] Tạo H2.30a/b theo xác định bối cảnh và kết hợp–cập nhật VSL; connector A.
- [ ] Mỗi panel giữ đúng nội dung nghiệp vụ, không nối bằng đường dài giữa panel.

### Task 3: Tạo bản đầy đủ

**Files:**
- Modify: `C:\do an\build_activity_vsl_report_panels.py`

- [ ] Dùng lại toàn bộ flow H2.26–H2.30 trong một file Excalidraw riêng cho từng hình ở `BAN_DAY_DU`.
- [ ] Giữ title, ký pháp UML, các nhánh và vòng lặp; bản full không dùng làm ảnh Word chính.

### Task 4: Tạo tài liệu và contact sheet

**Files:**
- Create: `C:\do an\bieu_do_hoat_dong_vsl_ban_doc_ro_trong_bao_cao\BAO_CAO_KIEM_TRA_DO_RO.md`
- Create: `C:\do an\bieu_do_hoat_dong_vsl_ban_doc_ro_trong_bao_cao\HUONG_DAN_CHEN_WORD.md`
- Create: `C:\do an\bieu_do_hoat_dong_vsl_ban_doc_ro_trong_bao_cao\CONTACT_SHEET_BAN_BAO_CAO.png`

- [ ] Ghi bảng từng panel: số khối, số quyết định, kích thước SVG/PNG, font nhỏ nhất, kích thước Word quy đổi và kết quả kiểm tra.
- [ ] Hướng dẫn A4 ngang, lề 1,5 cm, SVG rộng 24,5–25,5 cm, một panel/trang khi cần.
- [ ] Tạo contact sheet chỉ để rà soát, không dùng làm hình báo cáo.

### Task 5: Kiểm tra trực tiếp

**Files:**
- Read: toàn bộ `.excalidraw`, `.svg`, `.png` trong thư mục đầu ra.

- [ ] Kiểm tra PNG từng panel rộng 3000–3800 px, tỷ lệ ngang không quá 1,35 lần chiều cao.
- [ ] Kiểm tra Excalidraw không có phần tử image và mọi chữ chức năng từ 25 px trở lên.
- [ ] Kiểm tra SVG có viewBox tight, đủ dấu tiếng Việt và không có vùng trắng lớn.
- [ ] Import ít nhất một panel và một bản full vào canvas Excalidraw, chụp screenshot kiểm tra trực quan.
- [ ] Chỉ báo hoàn thành khi tất cả tệp tồn tại và các kiểm tra trên trả về hợp lệ.

# Chương 4 VSL viết lại Implementation Plan

> **For agentic workers:** This plan is for producing a standalone Word chapter artifact and verifying its layout before delivery.

**Goal:** Viết lại đầy đủ Chương 4 và phần Kết luận chung cho đề tài giám sát giao thông thông minh và đề xuất VSL dựa trên thị giác máy tính.

**Architecture:** Giữ phạm vi hệ thống mô phỏng trên máy tính cá nhân như tài liệu gốc, trình bày theo luồng đăng nhập, nhận dữ liệu, nhận diện YOLO, ROI, đo A/B, tính VSL, thử nghiệm và đánh giá. Nội dung được xuất thành một file DOCX riêng để người dùng dễ sao chép vào đồ án.

**Tech Stack:** Tiếng Việt học thuật; Python-docx; Times New Roman; OpenCV; YOLO; PyQt5; NumPy; SQLite; CSV/HTML Report; MQTT.

## Global Constraints

- Giữ đúng bố cục mục 4.1 đến 4.7 và phần KẾT LUẬN CHUNG.
- Gộp quy trình thử nghiệm và kết quả vào mục “4.3. Kịch bản thử nghiệm và kết quả đạt được”.
- Dùng đúng các dữ liệu 9 kịch bản chính và 20 kịch bản mô phỏng do người dùng cung cấp.
- Không tạo ảnh thật; chỉ chèn placeholder `[CHÈN HÌNH 4.X TẠI ĐÂY]` cùng chú thích và mô tả nội dung ảnh.
- Văn phong tự nhiên, chi tiết, bám vào hệ thống Python/OpenCV/YOLO/PyQt5/SQLite/CSV/HTML/MQTT.

### Task 1: Soạn nội dung

**Files:**
- Read: `C:\do an\CHƯƠNG 1.docx`
- Create: `C:\do an\CHUONG_4_VSL_viet_lai.docx`

- [ ] Viết lại 4.1, 4.2, 4.3 theo luồng xử lý hệ thống và chèn placeholder Hình 4.1–4.8.
- [ ] Viết 4.4–4.7, chèn bảng đề xuất vị trí biển và placeholder Hình 4.9–4.10.
- [ ] Viết KẾT LUẬN CHUNG, kiểm tra đủ hạn chế và hướng phát triển.

### Task 2: Tạo bố cục Word

**Files:**
- Create: `C:\do an\CHUONG_4_VSL_viet_lai.docx`

- [ ] Thiết lập khổ A4, lề 1 inch, Times New Roman, cỡ chữ nội dung 13.
- [ ] Định dạng tiêu đề, đề mục, công thức, placeholder hình và các bảng có tiêu đề rõ ràng.
- [ ] Cho phép các hàng trong bảng tự giãn để không cắt chữ.

### Task 3: Kiểm tra

**Files:**
- Inspect: `C:\do an\CHUONG_4_VSL_viet_lai.docx`

- [ ] Kiểm tra đủ Hình 4.1 đến Hình 4.10 và đủ 20 dòng mô phỏng.
- [ ] Render DOCX thành ảnh trang và kiểm tra lỗi tràn, cắt bảng, lỗi ký tự tiếng Việt.
- [ ] Sửa bố cục nếu cần và bàn giao file cuối cùng.

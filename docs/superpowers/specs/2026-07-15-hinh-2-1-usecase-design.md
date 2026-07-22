# Thiết kế bản xem tạm Hình 2.1

## Mục tiêu

Dựng lại Hình 2.1 — biểu đồ use-case tổng quát hệ thống VSL — trên canvas Excalidraw tạm thời để người dùng xem và chỉnh sửa, không thay đổi file SVG gốc.

## Phong cách

- Canvas logic: 1800×1250.
- Nền trắng, nét đen/xám, bố cục UML tối giản.
- Chữ sans-serif tương đương DejaVu Sans; tiêu đề 25px đậm, tên hệ thống 22px đậm, nội dung 18px.
- Actor/ngoại vi dùng hình người dạng nét; use-case dùng ellipse trắng viền đen.
- Khung hệ thống dùng hình chữ nhật trắng viền đen; quan hệ include dùng nét đứt màu xám.

## Nội dung và bố cục

- Tiêu đề ở trên cùng và khung hệ thống ở trung tâm.
- Bên trái: Quản trị viên, Người vận hành, Người kiểm thử.
- Bên phải: Camera/Video, Mô hình AI, Biển báo điện tử giả lập.
- Bên trong khung: 16 use-case theo lưới dọc 3 cột, giữ nguyên nhãn tiếng Việt và vị trí tương đối của SVG gốc.
- Giữ các liên kết actor/use-case và hai quan hệ `<<include>>` như file mẫu.

## Kiểm tra

Sau khi dựng, xem screenshot canvas để kiểm tra: chữ không bị cắt, không có ellipse chồng nhau, đường nối không đi xuyên qua use-case không liên quan, và các nhãn `<<include>>` vẫn đọc được.

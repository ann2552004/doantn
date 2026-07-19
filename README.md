\# Hệ thống giám sát biển báo tốc độ linh hoạt VSL ứng dụng Computer Vision trong ITS



\## 1. Giới thiệu



Đây là mã nguồn đồ án tốt nghiệp với chủ đề ứng dụng Computer Vision trong Hệ thống Giao thông Thông minh (ITS). Hệ thống sử dụng YOLO để nhận diện phương tiện trong video giao thông, lọc phương tiện trong vùng ROI, phân loại phương tiện, đo tốc độ qua hai vạch A/B và tính toán tốc độ giới hạn linh hoạt VSL.



\## 2. Chức năng chính



\- Chọn và chạy video giao thông.

\- Nhận diện phương tiện bằng YOLO.

\- Phân loại phương tiện: car, motorcycle, bus, truck, bicycle.

\- Lọc phương tiện trong vùng ROI.

\- Hiển thị bounding box, ROI, làn đường và vùng giám sát.

\- Đo tốc độ phương tiện qua hai vạch A/B.

\- Tính mật độ giao thông, trạng thái giao thông và VSL.

\- Xét điều kiện thời tiết và sự cố.

\- Lưu ảnh sự kiện, log, CSV và báo cáo.

\- Mô phỏng gửi tốc độ VSL xuống biển báo điện tử qua MQTT.



\## 3. Cấu trúc thư mục



```text

.

├── fix\_viet\_hoa\_full.py

├── README.md

├── requirements.txt

├── setup\_env.bat

├── run\_demo.bat

├── .gitignore

├── video/

├── trong\_so/

├── data\_v5/

└── docs/




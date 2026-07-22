import re

# from matplotlib import scale  # removed: unused import, caused startup failure when matplotlib is absent

import importlib

# Optional libraries: dùng import động để VS Code/Pylance không báo lỗi thiếu package.
# Nếu máy có cài easyocr hoặc paho-mqtt thì hệ thống vẫn tự dùng bình thường.
try:
    easyocr = importlib.import_module("easyocr")
except Exception:
    easyocr = None
import json

try:
    mqtt = importlib.import_module("paho.mqtt.client")
except Exception:
    mqtt = None
import sys
import os
import time
import csv
import html
import shutil
import sqlite3
import hashlib
import traceback
import platform
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from collections import deque
import cv2
import numpy as np



try:
    import torch
except Exception:
    torch = None

try:
    from ultralytics import YOLO
except Exception:
    YOLO = None

from PyQt5 import QtCore, QtGui, QtWidgets


# =========================================================
# PATHS / CONSTANTS
# =========================================================
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data_v5"
OUTPUT_DIR = BASE_DIR / "outputs_v5"
AUTH_DB = DATA_DIR / "auth.sqlite3"
MODEL_WEIGHTS = str(BASE_DIR / "trong_so" / "yolov8s.pt")
VEHICLE_CLASSES = ["car", "motorcycle", "bus", "truck", "bicycle"]
CUDA_AVAILABLE = bool(torch and torch.cuda.is_available())
PLATE_MODEL_WEIGHTS = str(BASE_DIR / "trong_so" / "bien_so_yolov8.pt")

# =========================================================
# LOGGING / STABILITY
# =========================================================
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
APP_LOG = LOG_DIR / "app.log"


def ghi_log(message: str):
    """Ghi log lỗi/hệ thống ra file logs/app.log để dễ debug khi chạy đồ án."""
    try:
        with open(APP_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")
    except Exception:
        try:
            print(message)
        except Exception:
            pass
# =========================================================
# CẤU HÌNH ĐO TỐC ĐỘ TỪNG XE
# =========================================================
SPEED_LINE_A_RATIO = 0.43
SPEED_LINE_B_RATIO = 0.70
SPEED_DISTANCE_METERS = 50.0

SPEED_MIN_FRAMES_BETWEEN_LINES = 6
SPEED_MIN_KMH = 5.0
SPEED_MAX_KMH = 160.0

SPEED_TRACK_TTL = 60
SPEED_IOU_MATCH_TH = 0.15
SPEED_CENTER_MATCH_PX = 130

SPEED_CONFIG_FILE = DATA_DIR / "speed_profiles.json"


# =========================================================
# CẤU HÌNH ROI / DẢI PHÂN CÁCH THEO TỪNG VIDEO
# =========================================================
# Các giá trị bên dưới là TỶ LỆ theo chiều rộng/cao của khung hình.
# Muốn chỉnh dải phân cách tím cho khớp video test, sửa file:
#   data_v5/roi_road_config.json
# Không cần mò trong 11 nghìn dòng code nữa, đời đã đủ mệt rồi.
ROI_ROAD_CONFIG_FILE = DATA_DIR / "roi_road_config.json"
DEFAULT_ROI_ROAD_CONFIG = {
    "y_top": 0.36,
    "y_bot": 0.92,
    "left_road": {
        "top_left_x": 0.04,
        "top_right_x": 0.490,
        "bottom_right_x": 0.430,
        "bottom_left_x": 0.000,
    },
    "right_road": {
        "top_left_x": 0.595,
        "top_right_x": 0.985,
        "bottom_right_x": 1.000,
        "bottom_left_x": 0.570,
    },
    "median": {
        "top_left_x": 0.490,
        "top_right_x": 0.595,
        "bottom_right_x": 0.570,
        "bottom_left_x": 0.430,
    }
}


def _clamp_ratio(value, minv=0.0, maxv=1.0):
    try:
        return max(minv, min(maxv, float(value)))
    except Exception:
        return minv


def doc_cau_hinh_roi_duong():
    """Đọc cấu hình ROI/dải phân cách từ JSON, tự tạo file mẫu nếu chưa có."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not ROI_ROAD_CONFIG_FILE.exists():
        try:
            with open(ROI_ROAD_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_ROI_ROAD_CONFIG, f, ensure_ascii=False, indent=2)
        except Exception as e:
            ghi_log(f"Lỗi tạo roi_road_config.json: {e}")
            return DEFAULT_ROI_ROAD_CONFIG

    try:
        with open(ROI_ROAD_CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Merge nhẹ để thiếu key nào vẫn dùng mặc định key đó.
        cfg = json.loads(json.dumps(DEFAULT_ROI_ROAD_CONFIG))
        for key, value in data.items():
            if isinstance(value, dict) and isinstance(cfg.get(key), dict):
                cfg[key].update(value)
            else:
                cfg[key] = value
        return cfg
    except Exception as e:
        ghi_log(f"Lỗi đọc roi_road_config.json, dùng mặc định: {e}")
        return DEFAULT_ROI_ROAD_CONFIG


def _speed_video_key(video_path: str) -> str:
    """Tạo khóa cấu hình tốc độ theo đường dẫn video, tránh trùng tên file."""
    try:
        p = Path(str(video_path))
        raw = str(p.resolve()) if p.exists() else str(p)
        return hashlib.md5(raw.encode("utf-8")).hexdigest()
    except Exception as e:
        ghi_log(f"Lỗi tạo speed video key: {e}")
        return "default"


def doc_cau_hinh_toc_do_video(video_path: str):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    default_cfg = {
        "line_a": SPEED_LINE_A_RATIO,
        "line_b": SPEED_LINE_B_RATIO,
        "distance_m": SPEED_DISTANCE_METERS,
    }

    try:
        if not SPEED_CONFIG_FILE.exists():
            return default_cfg

        with open(SPEED_CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        key = _speed_video_key(video_path)
        cfg = data.get(key) or data.get("default") or default_cfg

        return {
            "line_a": float(cfg.get("line_a", default_cfg["line_a"])),
            "line_b": float(cfg.get("line_b", default_cfg["line_b"])),
            "distance_m": float(cfg.get("distance_m", default_cfg["distance_m"])),
        }
    except Exception:
        return default_cfg


def luu_cau_hinh_toc_do_video(video_path: str, line_a: float, line_b: float, distance_m: float):
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    try:
        if SPEED_CONFIG_FILE.exists():
            with open(SPEED_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {}

        key = _speed_video_key(video_path)
        data[key] = {
            "line_a": float(line_a),
            "line_b": float(line_b),
            "distance_m": float(distance_m),
        }

        with open(SPEED_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return True
    except Exception:
        return False

def chuan_hoa_ten_xe(raw_name):
    raw_name = str(raw_name).lower().strip()

    alias = {
        "car": "car",
        "cars": "car",
        "auto": "car",
        "automobile": "car",
        "vehicle": "car",
        "van": "car",
        "suv": "car",
        "sedan": "car",
        "ô tô": "car",
        "oto": "car",
        "xe con": "car",

        "truck": "truck",
        "lorry": "truck",
        "xe tải": "truck",

        "bus": "bus",
        "coach": "bus",
        "xe khách": "bus",
        "xe buýt": "bus",

        "motorcycle": "motorcycle",
        "motorbike": "motorcycle",
        "bike": "motorcycle",
        "xe máy": "motorcycle",
        "moto": "motorcycle",

        "bicycle": "bicycle",
        "cycle": "bicycle",
        "xe đạp": "bicycle",
    }

    return alias.get(raw_name)
# =========================================================
# CẤU HÌNH MÔ HÌNH
# =========================================================
@dataclass
class CauHinhNhanDien:
    # Cấu hình mặc định đã tối ưu hơn cho demo đồ án:
    # - conf_th cao hơn để giảm nhận nhầm
    # - frame_stride > 1 để giảm tải xử lý
    # - imgsz 960 cân bằng giữa độ chính xác và tốc độ
    conf_th: float = 0.30
    frame_stride: int = 2
    imgsz: int = 960
    use_gpu: bool = CUDA_AVAILABLE


@dataclass
class CauHinhROI:
    top_center_x: float = 0.55
    bottom_center_x: float = 0.62
    bottom_width: float = 0.75
    top_width: float = 0.22
    height: float = 0.48
    bottom_y: float = 0.96


@dataclass
class CauHinhLanDuong:
    roi_mode: str = "ROI thủ công"
    lane_count: int = 3
    include_shoulder: bool = True
    draw_lanes: bool = True


@dataclass
class CauHinhVSL:
    vsl_min: int = 40
    vsl_max: int = 100
    scale_max: int = 20
    smoothing_window: int = 30
    weather: str = "Trời quang"
    incident: str = "Không"
    control_mode: str = "Tự động"
    manual_vsl: int = 80
@dataclass
class CauHinhHienThi:
    show_roi: bool = True
    show_boxes: bool = True
    show_hud: bool = False
    show_heatmap: bool = False


@dataclass
class CauHinhHeThong:
    detection: CauHinhNhanDien
    roi: CauHinhROI
    lane: CauHinhLanDuong
    vsl: CauHinhVSL
    display: CauHinhHienThi
@dataclass
class CauHinhCamera:
    camera_id: str
    ten_camera: str
    duong_dan_video: str
    vi_tri: str = ""
    kich_hoat: bool = True


class QuanLyCamera:

    def __init__(self):
        self.config_path = DATA_DIR / "cameras.json"
        self.danh_sach_camera = self._doc_camera_tu_file()

    def _camera_mac_dinh(self):
        return [
            {
                "camera_id": "CAM_01",
                "ten_camera": "Camera KM10",
                "duong_dan_video": str(BASE_DIR / "video" / "video_1.mp4"),
                "vi_tri": "KM10",
                "kich_hoat": True,
            },
            {
                "camera_id": "CAM_02",
                "ten_camera": "Camera KM15",
                "duong_dan_video": str(BASE_DIR / "video" / "recording.mp4"),
                "vi_tri": "KM15",
                "kich_hoat": True,
            },
            {
                "camera_id": "CAM_03",
                "ten_camera": "Camera KM20",
                "duong_dan_video": str(BASE_DIR / "video" / "video_1.mp4"),
                "vi_tri": "KM20",
                "kich_hoat": True,
            },
        ]

    def _doc_camera_tu_file(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not self.config_path.exists():
            try:
                with open(self.config_path, "w", encoding="utf-8") as f:
                    json.dump(self._camera_mac_dinh(), f, ensure_ascii=False, indent=2)
            except Exception as e:
                ghi_log(f"Lỗi tạo cameras.json: {e}")

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            ds = []
            for item in data:
                src = item.get("duong_dan_video", "")
                p = Path(str(src))
                if src and not p.is_absolute():
                    src = str(BASE_DIR / src)
                ds.append(CauHinhCamera(
                    camera_id=item.get("camera_id", "CAM_UNKNOWN"),
                    ten_camera=item.get("ten_camera", "Camera"),
                    duong_dan_video=src,
                    vi_tri=item.get("vi_tri", ""),
                    kich_hoat=bool(item.get("kich_hoat", True)),
                ))
            return ds
        except Exception as e:
            ghi_log(f"Lỗi đọc cameras.json, dùng cấu hình mặc định: {e}")
            return [
                CauHinhCamera(d["camera_id"], d["ten_camera"], d["duong_dan_video"], d["vi_tri"], d["kich_hoat"])
                for d in self._camera_mac_dinh()
            ]

    def lay_tat_ca(self):
        return self.danh_sach_camera

    def lay_camera_dang_bat(self):
        return [cam for cam in self.danh_sach_camera if cam.kich_hoat]

    def lay_camera_theo_id(self, camera_id):
        for cam in self.danh_sach_camera:
            if cam.camera_id == camera_id:
                return cam
        return None
class TruyenBienChiDan:
    def __init__(self):
        self.che_do = "MQTT"
        self.mqtt_host = os.getenv("VSL_MQTT_HOST", "broker.hivemq.com")
        self.mqtt_port = int(os.getenv("VSL_MQTT_PORT", "1883"))
        self.topic = os.getenv("VSL_MQTT_TOPIC", "do_an/vsl/bien_chi_dan")
        self.client = None
        self.da_ket_noi = False

    def ket_noi(self):
        if mqtt is None:
            return False, "Chưa cài paho-mqtt"

        try:
            self.client = mqtt.Client()
            self.client.connect(self.mqtt_host, self.mqtt_port, 60)
            self.client.loop_start()
            self.da_ket_noi = True
            return True, "Đã kết nối MQTT"
        except Exception as e:
            self.da_ket_noi = False
            return False, str(e)

    def gui_toc_do(self, toc_do, camera_id="CAM_00", ly_do=""):
        if not self.da_ket_noi:
            ok, msg = self.ket_noi()
            if not ok:
                return False, msg

        data = {
            "camera_id": camera_id,
            "toc_do_vsl": int(toc_do),
            "ly_do": ly_do,
            "thoi_gian": time.strftime("%Y-%m-%d %H:%M:%S"),
            "lenh": "CAP_NHAT_BIEN_BAO"
        }

        try:
            self.client.publish(
                self.topic,
                json.dumps(data, ensure_ascii=False)
            )
            return True, f"Đã gửi VSL {toc_do} km/h xuống biển chỉ dẫn"
        except Exception as e:
            return False, str(e)
class BienBaoDienTu:
    def __init__(self):
        self.host = os.getenv("VSL_SIGN_MQTT_HOST", "broker.hivemq.com")
        self.port = int(os.getenv("VSL_SIGN_MQTT_PORT", "1883"))
        self.topic = os.getenv("VSL_SIGN_MQTT_TOPIC", "vsl/bien_bao")

        self.client = None
        self.connected = False

    def ket_noi(self):
        if mqtt is None:
            return False

        try:
            self.client = mqtt.Client()
            self.client.connect(
                self.host,
                self.port,
                60
            )

            self.client.loop_start()
            self.connected = True
            return True

        except Exception:
            self.connected = False
            return False

    def gui_lenh(
        self,
        camera_id,
        toc_do,
        mat_do,
        trang_thai
    ):
        if not self.connected:
            self.ket_noi()

        if not self.connected:
            return

        data = {
            "camera_id": camera_id,
            "toc_do": int(toc_do),
            "mat_do": mat_do,
            "trang_thai": trang_thai,
            "thoi_gian": time.strftime("%H:%M:%S")
        }

        try:
            self.client.publish(
                self.topic,
                json.dumps(data, ensure_ascii=False)
            )
        except Exception as e:
            ghi_log(f"Lỗi gửi MQTT biển báo: {e}")        
# =========================================================
# QUẢN LÝ TÀI KHOẢN
# =========================================================
class QuanLyTaiKhoan:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        return sqlite3.connect(str(self.db_path))

    def _init_db(self):
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    full_name TEXT NOT NULL,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'operator',
                    created_at TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS login_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    login_time TEXT NOT NULL
                )
            """)
            conn.commit()

    @staticmethod
    def bam_mat_khau(password: str) -> str:
        # Salt nhẹ để tránh hash mật khẩu quá thô bằng SHA-256 thuần.
        # Với triển khai thực tế nên thay bằng bcrypt/passlib.
        salt = "vsl_do_an_2026"
        return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()

    def kiem_tra_co_nguoi_dung(self) -> bool:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM users")
            return (cur.fetchone() or [0])[0] > 0

    def kiem_tra_ton_tai_tai_khoan(self, username: str) -> bool:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM users WHERE username = ?", (username.strip(),))
            return cur.fetchone() is not None

    def tao_tai_khoan(self, full_name: str, username: str, password: str, role: str = "vận hành viên"):
        full_name = full_name.strip()
        username = username.strip()

        if len(full_name) < 2:
            return False, "Họ tên quá ngắn."
        if len(username) < 3:
            return False, "Tên đăng nhập phải từ 3 ký tự."
        if len(password) < 4:
            return False, "Mật khẩu phải từ 4 ký tự."
        if self.kiem_tra_ton_tai_tai_khoan(username):
            return False, "Tên đăng nhập đã tồn tại."

        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO users(full_name, username, password_hash, role, created_at) VALUES(?,?,?,?,?)",
                (
                    full_name,
                    username,
                    self.bam_mat_khau(password),
                    role,
                    time.strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
            conn.commit()
        return True, "Tạo tài khoản thành công."

    def dang_nhap(self, username: str, password: str):
        username = username.strip()
        pw_hash = self.bam_mat_khau(password)
        legacy_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()

        with self._connect() as conn:
            cur = conn.cursor()

            # Tương thích ngược: tài khoản cũ dùng SHA-256 thuần vẫn đăng nhập được.
            cur.execute(
                "SELECT full_name, username, role FROM users WHERE username = ? AND password_hash IN (?, ?)",
                (username, pw_hash, legacy_hash),
            )
            row = cur.fetchone()
            if not row:
                return False, "Sai tên đăng nhập hoặc mật khẩu.", None

            # Nếu đăng nhập bằng hash cũ, tự nâng cấp sang hash có salt.
            try:
                cur.execute(
                    "UPDATE users SET password_hash = ? WHERE username = ? AND password_hash = ?",
                    (pw_hash, username, legacy_hash),
                )
            except Exception as e:
                ghi_log(f"Không thể nâng cấp password hash cho {username}: {e}")

            cur.execute(
                "INSERT INTO login_history(username, login_time) VALUES (?, ?)",
                (username, time.strftime("%Y-%m-%d %H:%M:%S")),
            )
            conn.commit()
        user = {"full_name": row[0], "username": row[1], "role": row[2]}
        return True, "Đăng nhập thành công.", user


class TaoQuanTriVienDauTien(QtWidgets.QDialog):
    def __init__(self, auth_manager: QuanLyTaiKhoan, parent=None):
        super().__init__(parent)
        self.auth_manager = auth_manager
        self.setWindowTitle("Thiết lập quản trị viên đầu tiên")
        self.resize(560, 360)
        self.setModal(True)
        self.setStyleSheet('\n            QDialog { background:#eef4fb; }\n            QFrame#Card { background:white; border:1px solid #d9e6f3; border-radius:20px; }\n            QLabel#Title { font-size:22px; font-weight:800; color:#0f172a; }\n            QLabel#Sub { font-size:12px; color:#64748b; }\n            QLineEdit {\n                background:white; border:1px solid #d1dbe8; border-radius:12px; padding:10px 12px; min-height:20px;\n            }\n            QPushButton {\n                background:#2563eb; color:white; border:none; border-radius:12px; padding:10px 16px; font-weight:700;\n            }\n        ')

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)

        card = QtWidgets.QFrame()
        card.setObjectName('Card')
        lay = QtWidgets.QVBoxLayout(card)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(12)

        t = QtWidgets.QLabel("Thiết lập tài khoản admin")
        t.setObjectName("Title")
        s = QtWidgets.QLabel("Lần chạy đầu tiên cần tạo một tài khoản quản trị. Tài khoản này sẽ dùng để đăng nhập hệ thống.")
        s.setObjectName("Sub")
        s.setWordWrap(True)

        self.ed_full = QtWidgets.QLineEdit()
        self.ed_full.setPlaceholderText("Họ và tên")
        self.ed_user = QtWidgets.QLineEdit()
        self.ed_user.setPlaceholderText("Tên đăng nhập")
        self.ed_pass = QtWidgets.QLineEdit()
        self.ed_pass.setPlaceholderText("Mật khẩu")
        self.ed_pass.setEchoMode(QtWidgets.QLineEdit.Password)
        self.ed_pass2 = QtWidgets.QLineEdit()
        self.ed_pass2.setPlaceholderText("Nhập lại mật khẩu")
        self.ed_pass2.setEchoMode(QtWidgets.QLineEdit.Password)

        self.msg = QtWidgets.QLabel("")
        self.msg.setStyleSheet("color:#dc2626;")

        btn = QtWidgets.QPushButton("Tạo admin")
        btn.clicked.connect(self.xu_ly_tao_tai_khoan)

        lay.addWidget(t)
        lay.addWidget(s)
        lay.addSpacing(4)
        lay.addWidget(self.ed_full)
        lay.addWidget(self.ed_user)
        lay.addWidget(self.ed_pass)
        lay.addWidget(self.ed_pass2)
        lay.addWidget(self.msg)
        lay.addWidget(btn)

        root.addWidget(card)

    def xu_ly_tao_tai_khoan(self):
        if self.ed_pass.text() != self.ed_pass2.text():
            self.msg.setText("Mật khẩu nhập lại không khớp.")
            return
        ok, msg = self.auth_manager.tao_tai_khoan(
            self.ed_full.text(),
            self.ed_user.text(),
            self.ed_pass.text(),
            role="quản trị viên",
        )
        self.msg.setText(msg)
        self.msg.setStyleSheet("color:#16a34a;" if ok else "color:#dc2626;")
        if ok:
            QtCore.QTimer.singleShot(500, self.accept)


# =========================================================
# HÀM TIỆN ÍCH CHUNG
# =========================================================
def mo_duong_dan_an_toan(path: str):
    if not path or not os.path.exists(path):
        return
    try:
        if os.name == "nt":
            os.startfile(path)
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", path])
        else:
              subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


def tao_da_giac_roi(
    width: int,
    height: int,
    top_center_x: float = 0.55,
    bottom_center_x: float = 0.62,
    bottom_width: float = 0.75,
    top_width: float = 0.22,
    roi_height: float = 0.48,
    bottom_y: float = 0.96,
):
    top_center_x = np.clip(top_center_x, 0.05, 0.95)
    bottom_center_x = np.clip(bottom_center_x, 0.05, 0.95)
    bottom_width = np.clip(bottom_width, 0.10, 0.98)
    top_width = np.clip(top_width, 0.05, 0.90)
    roi_height = np.clip(roi_height, 0.10, 0.95)
    bottom_y = np.clip(bottom_y, 0.50, 0.99)

    top_cx_px = int(top_center_x * width)
    bot_cx_px = int(bottom_center_x * width)
    half_bw = int((bottom_width * width) / 2)
    half_tw = int((top_width * width) / 2)
    y_bottom = int(bottom_y * height)
    y_top = max(0, int((bottom_y - roi_height) * height))

    return np.array(
        [
            [top_cx_px - half_tw, y_top],
            [top_cx_px + half_tw, y_top],
            [bot_cx_px + half_bw, y_bottom],
            [bot_cx_px - half_bw, y_bottom],
        ],
        dtype=np.int32,
    )


def kiem_tra_diem_trong_da_giac(point, poly) -> bool:
    return cv2.pointPolygonTest(poly.astype(np.float32), (float(point[0]), float(point[1])), False) >= 0


def ve_vung_giam_sat(frame, poly, alpha=0.16, edge=(255, 191, 0)):
    overlay = frame.copy()
    cv2.fillPoly(overlay, [poly], (255, 191, 0))
    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)
    cv2.polylines(frame, [poly], True, edge, 2)
    x_min = int(np.min(poly[:, 0]))
    y_min = int(np.min(poly[:, 1]))
    cv2.putText(frame, "VSL ROI", (x_min + 10, max(28, y_min + 28)), cv2.FONT_HERSHEY_SIMPLEX, 0.75, edge, 2, cv2.LINE_AA)


def _noi_suy_diem(p0, p1, t: float):
    return np.array([
        int(round(p0[0] + (p1[0] - p0[0]) * t)),
        int(round(p0[1] + (p1[1] - p0[1]) * t)),
    ], dtype=np.int32)


def tao_lan_duong_tu_roi(poly: np.ndarray, lane_count: int = 3, include_shoulder: bool = True):
    lane_count = max(1, int(lane_count))
    top_left, top_right, bot_right, bot_left = [np.array(p, dtype=np.int32) for p in poly]
    total_segments = lane_count + (2 if include_shoulder else 0)

    if total_segments <= 0:
        return []

    left_points = [_noi_suy_diem(top_left, bot_left, i / total_segments) for i in range(total_segments + 1)]
    right_points = [_noi_suy_diem(top_right, bot_right, i / total_segments) for i in range(total_segments + 1)]

    lane_polys = []
    labels = []
    for i in range(total_segments):
        quad = np.array([
            left_points[i],
            right_points[i],
            right_points[i + 1],
            left_points[i + 1],
        ], dtype=np.int32)
        lane_polys.append(quad)
        if include_shoulder and i == 0:
            labels.append('EMERGENCY LANE')
        elif include_shoulder and i == total_segments - 1:
            labels.append('EMERGENCY LANE')
        else:
            lane_idx = i if not include_shoulder else i
            labels.append(f"Lane {lane_idx}")
    return list(zip(labels, lane_polys))


def kiem_tra_diem_trong_lan_duong(point, lane_items):
    for label, poly in lane_items:
        if kiem_tra_diem_trong_da_giac(point, poly):
            return True, label
    return False, None


def ve_lan_duong(frame, lane_items, alpha=0.10):
    overlay = frame.copy()
    colors = [
        (0, 200, 255),
        (255, 170, 0),
        (120, 255, 120),
        (255, 120, 220),
        (120, 220, 255),
        (255, 220, 120),
    ]
    for idx, (label, poly) in enumerate(lane_items):
        color = colors[idx % len(colors)]
        cv2.fillPoly(overlay, [poly], color)
        cv2.polylines(frame, [poly], True, color, 2)
        cxy = np.mean(poly, axis=0).astype(int)
        cv2.putText(frame, label, (int(cxy[0]) - 20, int(cxy[1])), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)
    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)


def phan_loai_mat_do(avg_count: int) -> str:
    if avg_count <= 5:
        return "THẤP"
    if avg_count <= 12:
        return "TRUNG BÌNH"
    return "CAO"


def phan_loai_trang_thai_giao_thong(avg_count: int, truck_ratio: float) -> str:
    if avg_count <= 4:
        return "Lưu thông tốt"
    if avg_count <= 8:
        return "Lưu thông ổn định"
    if avg_count <= 14:
        return "Mật độ cao"
    return "Nguy cơ ùn tắc"
def tinh_vsl_co_ban(vehicle_count_now: int, vsl_min=40, vsl_max=100, scale_max=20):
    clamped = min(vehicle_count_now, scale_max)
    speed = vsl_max - (clamped * ((vsl_max - vsl_min) / max(1, scale_max)))
    return round(max(vsl_min, min(vsl_max, speed)))



# =========================================================
# PHÂN VÙNG ĐIỀU KIỆN THỜI TIẾT CHO VSL
# =========================================================
# Nguyên tắc: thời tiết được chia theo mức ảnh hưởng an toàn.
# - Mưa: chia theo cường độ mưa tương đối (mm/h) để giảm tốc độ theo độ trơn mặt đường.
# - Sương mù: chia theo tầm nhìn ngang (km) để giảm tốc độ theo khả năng quan sát.
# Các ngưỡng dưới đây dùng cho mô hình đồ án/mô phỏng; khi triển khai thực tế có thể hiệu chỉnh theo dữ liệu cảm biến/API thời tiết.
THOI_TIET_HO_SO = {
    "Trời quang": {
        "nhom": "Bình thường",
        "muc": "Trời quang",
        "tam_nhin_km": "> 5 km",
        "cuong_do_mua": "0 mm/h",
        "giam_vsl": 0,
        "diem_rui_ro": 0,
        "mo_ta": "trời quang, tầm nhìn tốt",
    },
    "Mưa nhỏ": {
        "nhom": "Mưa",
        "muc": "Mưa nhỏ",
        "tam_nhin_km": "2 - 5 km",
        "cuong_do_mua": "< 2.5 mm/h",
        "giam_vsl": 5,
        "diem_rui_ro": 1,
        "mo_ta": "mưa nhỏ, mặt đường bắt đầu giảm độ bám",
    },
    "Mưa vừa": {
        "nhom": "Mưa",
        "muc": "Mưa vừa",
        "tam_nhin_km": "1 - 2 km",
        "cuong_do_mua": "2.5 - 7.6 mm/h",
        "giam_vsl": 10,
        "diem_rui_ro": 2,
        "mo_ta": "mưa vừa, mặt đường trơn và quãng đường phanh tăng",
    },
    "Mưa to": {
        "nhom": "Mưa",
        "muc": "Mưa to",
        "tam_nhin_km": "0.5 - 1 km",
        "cuong_do_mua": "> 7.6 mm/h",
        "giam_vsl": 15,
        "diem_rui_ro": 3,
        "mo_ta": "mưa to, tầm nhìn giảm và nguy cơ trượt bánh cao",
    },
    "Sương mù mỏng": {
        "nhom": "Sương mù",
        "muc": "Sương mù mỏng",
        "tam_nhin_km": "> 1 km",
        "cuong_do_mua": "0 mm/h",
        "giam_vsl": 10,
        "diem_rui_ro": 2,
        "mo_ta": "sương mù mỏng, tầm nhìn còn tương đối nhưng cần giảm tốc",
    },
    "Sương mù vừa": {
        "nhom": "Sương mù",
        "muc": "Sương mù vừa",
        "tam_nhin_km": "0.5 - 1 km",
        "cuong_do_mua": "0 mm/h",
        "giam_vsl": 20,
        "diem_rui_ro": 3,
        "mo_ta": "sương mù vừa, tầm nhìn hạn chế rõ rệt",
    },
    "Sương mù dày": {
        "nhom": "Sương mù",
        "muc": "Sương mù dày",
        "tam_nhin_km": "< 0.5 km",
        "cuong_do_mua": "0 mm/h",
        "giam_vsl": 30,
        "diem_rui_ro": 4,
        "mo_ta": "sương mù dày, tầm nhìn rất thấp, cần giảm tốc mạnh",
    },
    # Tương thích với lựa chọn cũ trong các phiên bản trước.
    "Mưa": {
        "nhom": "Mưa",
        "muc": "Mưa vừa",
        "tam_nhin_km": "1 - 2 km",
        "cuong_do_mua": "2.5 - 7.6 mm/h",
        "giam_vsl": 10,
        "diem_rui_ro": 2,
        "mo_ta": "mưa mức trung bình, mặt đường trơn và quãng đường phanh tăng",
    },
    "Sương mù": {
        "nhom": "Sương mù",
        "muc": "Sương mù vừa",
        "tam_nhin_km": "0.5 - 1 km",
        "cuong_do_mua": "0 mm/h",
        "giam_vsl": 20,
        "diem_rui_ro": 3,
        "mo_ta": "sương mù mức trung bình, tầm nhìn hạn chế rõ rệt",
    },
}

DANH_SACH_THOI_TIET_VI = [
    "Trời quang",
    "Mưa nhỏ",
    "Mưa vừa",
    "Mưa to",
    "Sương mù mỏng",
    "Sương mù vừa",
    "Sương mù dày",
]


def lay_ho_so_thoi_tiet(weather: str) -> dict:
    """Trả về hồ sơ thời tiết phục vụ tính VSL và báo cáo."""
    return THOI_TIET_HO_SO.get(str(weather).strip(), THOI_TIET_HO_SO["Trời quang"])


def giam_toc_do_do_thoi_tiet(weather: str) -> int:
    return int(lay_ho_so_thoi_tiet(weather).get("giam_vsl", 0))


def diem_rui_ro_thoi_tiet(weather: str) -> int:
    return int(lay_ho_so_thoi_tiet(weather).get("diem_rui_ro", 0))


def mo_ta_thoi_tiet_chi_tiet(weather: str) -> str:
    p = lay_ho_so_thoi_tiet(weather)
    if p.get("nhom") == "Mưa":
        return f"{p['muc']} | cường độ {p['cuong_do_mua']} | tầm nhìn {p['tam_nhin_km']}"
    if p.get("nhom") == "Sương mù":
        return f"{p['muc']} | tầm nhìn {p['tam_nhin_km']}"
    return f"{p['muc']} | tầm nhìn {p['tam_nhin_km']}"


def tinh_vsl_theo_ngu_canh(avg_vehicles: int, class_counts: dict, cfg: CauHinhVSL):
    total = max(1, sum(class_counts.values()))
    heavy = class_counts.get("truck", 0) + class_counts.get("bus", 0)
    truck_ratio = heavy / total

    density = phan_loai_mat_do(avg_vehicles)
    traffic_state = phan_loai_trang_thai_giao_thong(avg_vehicles, truck_ratio)
    speed = tinh_vsl_co_ban(avg_vehicles, cfg.vsl_min, cfg.vsl_max, cfg.scale_max)
    reasons = [f"mật độ={density.lower()}"]

    if truck_ratio >= 0.35:
        speed -= 8
        reasons.append("tỷ lệ xe nặng cao")
    elif truck_ratio >= 0.20:
        speed -= 4
        reasons.append("tỷ lệ xe nặng trung bình")

    weather_profile = lay_ho_so_thoi_tiet(cfg.weather)
    weather_penalty = int(weather_profile.get("giam_vsl", 0))
    if weather_penalty > 0:
        speed -= weather_penalty
        reasons.append(f"{weather_profile.get('muc', cfg.weather).lower()} - giảm {weather_penalty} km/h ({weather_profile.get('mo_ta', '')})")

    if cfg.incident == "Nhẹ":
        speed -= 15
        reasons.append("sự cố nhẹ")
    elif cfg.incident == "Nghiêm trọng":
        speed -= 30
        reasons.append("sự cố nghiêm trọng")

    if traffic_state == "Mật độ cao":
        speed -= 5
        reasons.append("giao thông mật độ cao")
    elif traffic_state == "Nguy cơ ùn tắc":
        speed -= 12
        reasons.append("nguy cơ ùn tắc")

    speed = round(max(cfg.vsl_min, min(cfg.vsl_max, speed)))
    if cfg.control_mode == "Thủ công":
        speed = cfg.manual_vsl
        reasons = [f"can thiệp thủ công={cfg.manual_vsl}"]

    return density, speed, traffic_state, " | ".join(reasons)


def tinh_muc_do_uu_tien(density: str, traffic_state: str, weather: str, incident: str, sudden_increase: bool, vsl_speed: int) -> str:
    score = 0
    if density == "TRUNG BÌNH":
        score += 1
    elif density == "CAO":
        score += 2
    if traffic_state == "Mật độ cao":
        score += 2
    elif traffic_state == "Nguy cơ ùn tắc":
        score += 4

    # Điểm rủi ro thời tiết được chia theo mức phân vùng:
    # mưa nhỏ/vừa/to hoặc sương mù mỏng/vừa/dày.
    score += diem_rui_ro_thoi_tiet(weather)

    if incident == "Nhẹ":
        score += 3
    elif incident == "Nghiêm trọng":
        score += 5
    if sudden_increase:
        score += 2
    if vsl_speed <= 50:
        score += 2
    elif vsl_speed <= 65:
        score += 1

    if score <= 1:
        return "Bình thường"
    if score <= 4:
        return "Theo dõi"
    if score <= 8:
        return "Cần can thiệp"
    return "Khẩn cấp"


def chuyen_bgr_sang_qimage(frame_bgr: np.ndarray) -> QtGui.QImage:
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb.shape
    qimg = QtGui.QImage(rgb.data, w, h, ch * w, QtGui.QImage.Format_RGB888)
    return qimg.copy()


# =========================================================
# THÀNH PHẦN GIAO DIỆN
# =========================================================
class TheThongKeDong(QtWidgets.QFrame):
    def __init__(self, title: str, value: str = "-", accent: str = "#3b82f6", parent=None):
        super().__init__(parent)
        self.setObjectName('StatCard')
        self._shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(22)
        self._shadow.setOffset(0, 8)
        self._shadow.setColor(QtGui.QColor(37, 99, 235, 30))
        self.setGraphicsEffect(self._shadow)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)

        self.title_label = QtWidgets.QLabel(title)
        self.title_label.setObjectName('StatCardTitle')
        self.value_label = QtWidgets.QLabel(value)
        self.value_label.setObjectName('StatCardValue')
        self.sub_label = QtWidgets.QLabel("")
        self.sub_label.setObjectName('StatCardSub')
        self.sub_label.setWordWrap(True)

        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.sub_label)
        self.dat_mau_nhan(accent)

    def nhap_nhay(self):
        anim = QtCore.QPropertyAnimation(self._shadow, b"blurRadius", self)
        anim.setDuration(380)
        anim.setStartValue(18)
        anim.setKeyValueAt(0.5, 36)
        anim.setEndValue(22)
        anim.start(QtCore.QAbstractAnimation.DeleteWhenStopped)

    def dat_gia_tri(self, text: str):
        if self.value_label.text() != text:
            self.value_label.setText(text)
            self.nhap_nhay()

    def dat_mo_ta(self, text: str):
        self.sub_label.setText(text)

    def dat_mau_nhan(self, color: str):
        self.setStyleSheet(f"""
            QFrame#StatCard {{
                background:qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ffffff, stop:1 #f8fbff);
                border:1px solid #dbe5f2;
                border-left:5px solid {color};
                border-radius:16px;
            }}
            QLabel#StatCardTitle {{ color:#64748b; font-size:11px; font-weight:600; }}
            QLabel#StatCardValue {{ color:#0f172a; font-size:26px; font-weight:800; }}
            QLabel#StatCardSub {{ color:#475569; font-size:10px; }}
        """)


class NutDieuHuong(QtWidgets.QPushButton):
    def __init__(self, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setObjectName("NavButton")
        self.setMinimumHeight(72)
        wrap = QtWidgets.QVBoxLayout(self)
        wrap.setContentsMargins(14, 10, 14, 10)
        wrap.setSpacing(2)
        self.lb_title = QtWidgets.QLabel(title)
        self.lb_title.setObjectName("NavTitle")
        self.lb_sub = QtWidgets.QLabel(subtitle)
        self.lb_sub.setObjectName("NavSub")
        self.lb_sub.setWordWrap(True)
        wrap.addWidget(self.lb_title)
        wrap.addWidget(self.lb_sub)


class KhungNoiDung(QtWidgets.QGroupBox):
    def __init__(self, title: str, hint: str = "", parent=None):
        super().__init__(title, parent)
        self.setObjectName('CardSection')
        self.lay = QtWidgets.QVBoxLayout(self)
        self.lay.setContentsMargins(16, 18, 16, 16)
        self.lay.setSpacing(10)
        if hint:
            lab = QtWidgets.QLabel(hint)
            lab.setObjectName("SectionHint")
            lab.setWordWrap(True)
            self.lay.addWidget(lab)


class TrangChucNang(QtWidgets.QWidget):
    def __init__(self, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        header = QtWidgets.QFrame()
        header.setObjectName("ModuleHeader")
        h = QtWidgets.QVBoxLayout(header)
        h.setContentsMargins(18, 16, 18, 16)
        h.setSpacing(4)
        self.title_label = QtWidgets.QLabel(title)
        self.title_label.setObjectName("ModuleTitle")
        self.subtitle_label = QtWidgets.QLabel(subtitle)
        self.subtitle_label.setObjectName("ModuleSubtitle")
        self.subtitle_label.setWordWrap(True)
        h.addWidget(self.title_label)
        h.addWidget(self.subtitle_label)

        self.content = QtWidgets.QVBoxLayout()
        self.content.setSpacing(12)

        layout.addWidget(header)
        layout.addLayout(self.content)
        layout.addStretch()


class ThanhTruotCoNhan(QtWidgets.QWidget):
    valueChanged = QtCore.pyqtSignal(int)

    def __init__(self, text: str, minv: int, maxv: int, value: int, step: int = 1):
        super().__init__()
        self.label_prefix = text
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.label = QtWidgets.QLabel()
        self.label.setObjectName("MetricLabel")
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.setMinimum(minv)
        self.slider.setMaximum(maxv)
        self.slider.setSingleStep(step)
        self.slider.setValue(value)
        self.slider.valueChanged.connect(self._phat_tin_hieu)
        lay.addWidget(self.label)
        lay.addWidget(self.slider)
        self.dat_chu_gia_tri(value)

    def _phat_tin_hieu(self, v):
        self.dat_chu_gia_tri(v)
        self.valueChanged.emit(v)

    def dat_chu_gia_tri(self, v: int):
        self.label.setText(f"{self.label_prefix}: {v}")

    def setValue(self, value: int):
        blocker = QtCore.QSignalBlocker(self.slider)
        self.slider.setValue(value)
        self.dat_chu_gia_tri(value)

    def setEnabled(self, enabled: bool):
        super().setEnabled(enabled)
        self.label.setEnabled(enabled)
        self.slider.setEnabled(enabled)



def _bbox_iou(box_a, box_b):
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    area_a = max(1, (ax2 - ax1) * (ay2 - ay1))
    area_b = max(1, (bx2 - bx1) * (by2 - by1))
    return inter / float(area_a + area_b - inter + 1e-6)


class BoDoTocDoHaiVach:
    def __init__(self):
        self.next_id = 1
        self.tracks = {}

    def reset(self):
        self.next_id = 1
        self.tracks.clear()

    def _match_track(self, box, center, lane_label, name):
        best_id = None
        best_score = -1.0

        for tid, tr in self.tracks.items():
            if tr.get("name") != name:
                continue

            same_lane = (
                lane_label is None or
                tr.get("lane_label") is None or
                tr.get("lane_label") == lane_label
            )
            if not same_lane:
                continue

            iou = _bbox_iou(box, tr["box"])
            px, py = tr["center"]
            cx, cy = center
            dist = ((cx - px) ** 2 + (cy - py) ** 2) ** 0.5
            score = iou * 2.0 + max(0.0, 1.0 - dist / max(1.0, SPEED_CENTER_MATCH_PX))

            if iou >= SPEED_IOU_MATCH_TH or dist <= SPEED_CENTER_MATCH_PX:
                if score > best_score:
                    best_score = score
                    best_id = tid

        return best_id

    def cap_nhat(self, frame_h, detections, frame_idx, fps_video, line_a=None, line_b=None, distance_m=None):
        line_a = SPEED_LINE_A_RATIO if line_a is None else float(line_a)
        line_b = SPEED_LINE_B_RATIO if line_b is None else float(line_b)
        distance_m = SPEED_DISTANCE_METERS if distance_m is None else float(distance_m)

        y_a = int(frame_h * line_a)
        y_b = int(frame_h * line_b)

        for tid in list(self.tracks.keys()):
            self.tracks[tid]["ttl"] -= 1
            if self.tracks[tid]["ttl"] <= 0:
                del self.tracks[tid]

        measured = []

        for det in detections:
            x1, y1, x2, y2, name, confv, color, cx, cy, in_roi, lane_label = det[:11]
            if not in_roi:
                continue

            box = (int(x1), int(y1), int(x2), int(y2))
            center = (int(cx), int(cy))
            tid = self._match_track(box, center, lane_label, name)

            if tid is None:
                tid = self.next_id
                self.next_id += 1
                self.tracks[tid] = {
                    "box": box,
                    "center": center,
                    "name": name,
                    "lane_label": lane_label,
                    "ttl": SPEED_TRACK_TTL,
                    "line_a_frame": None,
                    "line_b_frame": None,
                    "speed_kmh": None,
                }

            tr = self.tracks[tid]
            prev_cx, prev_cy = tr["center"]
            cur_cx, cur_cy = center

            cross_a = (prev_cy < y_a <= cur_cy) or (prev_cy > y_a >= cur_cy)
            cross_b = (prev_cy < y_b <= cur_cy) or (prev_cy > y_b >= cur_cy)

            if cross_a and tr["line_a_frame"] is None:
                tr["line_a_frame"] = frame_idx
            if cross_b and tr["line_b_frame"] is None:
                tr["line_b_frame"] = frame_idx

            if tr["line_a_frame"] is not None and tr["line_b_frame"] is not None and tr["speed_kmh"] is None:
                df = abs(tr["line_b_frame"] - tr["line_a_frame"])
                if df >= SPEED_MIN_FRAMES_BETWEEN_LINES:
                    dt = df / max(1.0, float(fps_video))
                    speed = distance_m / dt * 3.6
                    if SPEED_MIN_KMH <= speed <= SPEED_MAX_KMH:
                        tr["speed_kmh"] = round(float(speed), 1)

            tr["center"] = center
            tr["box"] = box
            tr["name"] = name
            tr["lane_label"] = lane_label
            tr["ttl"] = SPEED_TRACK_TTL

            measured.append((tid, tr.get("speed_kmh"), box, lane_label))

        return measured

    def lay_toc_do(self):
        speeds = [tr["speed_kmh"] for tr in self.tracks.values() if tr.get("speed_kmh") is not None]
        return speeds[-20:]

# =========================================================
# LUỒNG XỬ LÝ VIDEO
# =========================================================
class XuLyVideo(QtCore.QThread):
    frameReady = QtCore.pyqtSignal(QtGui.QImage)
    statsReady = QtCore.pyqtSignal(dict)
    statusReady = QtCore.pyqtSignal(str)
    logReady = QtCore.pyqtSignal(str)
    errorReady = QtCore.pyqtSignal(str)
    finishedCleanly = QtCore.pyqtSignal(dict)

    def __init__(self, video_path: str, config: CauHinhHeThong, session_user: dict, camera_id="VIDEO_THU_CONG", parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self.config = config
        self.session_user = session_user or {}
        self.camera_id = camera_id
        self.stop_requested = False
        self.pause_requested = False
        self.cap = None
        self.model = None
        self.name_map = {}
        self.frame_idx = 0
        self.fps_video = 25.0
        self.fps_est = 0.0
        self.fps_counter = 0
        self.fps_last_time = time.time()
        self.vehicle_history = deque(maxlen=max(1, config.vsl.smoothing_window))
        self.prev_avg_vehicles = 0
        self.sudden_increase_threshold = 4
        self.last_inference_boxes = []
        self.heatmap_accumulator = None
        self.last_frame_bgr = None

        self.event_timeline = []
        self.event_count = 0
        self.warning_count = 0
        self.snapshot_count = 0
        self.last_state = None
        self.last_vsl = None
        self.last_priority = None
        self.last_stats = {}
        self.speed_tracker = BoDoTocDoHaiVach()
        _speed_cfg = doc_cau_hinh_toc_do_video(self.video_path)
        self.speed_line_a_ratio = float(_speed_cfg.get("line_a", SPEED_LINE_A_RATIO))
        self.speed_line_b_ratio = float(_speed_cfg.get("line_b", SPEED_LINE_B_RATIO))
        self.speed_distance_m = float(_speed_cfg.get("distance_m", SPEED_DISTANCE_METERS))

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        session_name = f"session_{time.strftime('%Y%m%d_%H%M%S')}_{self.session_user.get('username', 'guest')}"
        self.outputs_dir = OUTPUT_DIR / session_name
        self.snapshots_dir = self.outputs_dir / "snapshots"
        self.csv_path = self.outputs_dir / "traffic_log.csv"
        self.summary_json_path = self.outputs_dir / "summary_report.json"
        self.summary_txt_path = self.outputs_dir / "summary_report.txt"
        self.summary_html_path = self.outputs_dir / "summary_report.html"
        self.timeline_txt_path = self.outputs_dir / "event_timeline.txt"
        self.heatmap_img_path = self.outputs_dir / "heatmap.png"
        self.archive_path = self.outputs_dir / "report_bundle.zip"
        self.last_csv_write_time = 0.0
        self.csv_write_interval = 1.0

    def yeu_cau_dung(self):
        self.stop_requested = True

    def dat_tam_dung(self, paused: bool):
        self.pause_requested = paused

    def them_nhat_ky(self, text: str):
        self.logReady.emit(text)

    def them_su_kien(self, event_type: str, message: str, t_sec: float):
        self.event_count += 1
        line = f"[{self.event_count:03d}] t={t_sec:.1f}s | {event_type} | {message}"
        self.event_timeline.append(line)
        self.them_nhat_ky(line)

    def tai_mo_hinh(self):
        if YOLO is None:
            self.them_nhat_ky("[LỖI] Chưa cài ultralytics. Chạy: pip install ultralytics")
            self.model = None
            self.name_map = {}
            return

        candidates = [
            str(BASE_DIR / "trong_so" / "yolov8s.pt"),
            str(BASE_DIR / "trong_so" / "yolov8n.pt"),
            "yolov8s.pt",
            "yolov8n.pt",
        ]

        last_error = None
        for weight_path in candidates:
            try:
                if os.path.isabs(weight_path) and not os.path.exists(weight_path):
                    self.them_nhat_ky(f"[MODEL] Bỏ qua vì không thấy file: {weight_path}")
                    continue

                self.model = YOLO(weight_path)
                device = "cuda:0" if self.config.detection.use_gpu and CUDA_AVAILABLE else "cpu"
                try:
                    self.model.to(device)
                except Exception:
                    pass

                self.name_map = getattr(self.model, "names", {}) or getattr(self.model.model, "names", {})
                self.them_nhat_ky(f"[OK] Đã tải model: {weight_path}")
                self.them_nhat_ky(f"[OK] Classes YOLO: {self.name_map}")
                self.them_nhat_ky(f"[OK] Device: {device}")
                return

            except Exception as e:
                last_error = e
                self.them_nhat_ky(f"[MODEL] Không tải được {weight_path}: {e}")

        self.model = None
        self.name_map = {}
        self.them_nhat_ky(f"[LỖI] Không tải được bất kỳ YOLO model nào. Lỗi cuối: {last_error}")

    def luu_anh_su_kien(self, frame, tag: str, t_sec: float):
        try:
            self.snapshots_dir.mkdir(parents=True, exist_ok=True)
            self.snapshot_count += 1
            path = self.snapshots_dir / f"snapshot_{self.snapshot_count:03d}_{tag}_t{t_sec:.1f}s.jpg"
            cv2.imwrite(str(path), frame)
        except Exception:
            pass

    def luu_ban_do_nhiet(self):
        try:
            if self.heatmap_accumulator is None or self.last_frame_bgr is None:
                return
            if np.max(self.heatmap_accumulator) <= 0:
                return
            heat_norm = cv2.normalize(self.heatmap_accumulator, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
            heat_color = cv2.applyColorMap(heat_norm, cv2.COLORMAP_JET)
            overlay = cv2.addWeighted(self.last_frame_bgr.copy(), 0.65, heat_color, 0.35, 0)
            cv2.imwrite(str(self.heatmap_img_path), overlay)
        except Exception:
            pass

    def tao_tom_tat(self):
        elapsed_sec = self.frame_idx / self.fps_video if self.fps_video > 0 else 0.0
        return {
            "video_name": Path(self.video_path).name if self.video_path else "N/A",
            "video_path": self.video_path,
            "elapsed_sec": round(elapsed_sec, 2),
            "processed_frames": self.frame_idx,
            "weather": self.config.vsl.weather,
            "weather_detail": mo_ta_thoi_tiet_chi_tiet(self.config.vsl.weather),
            "incident": self.config.vsl.incident,
            "mode": self.config.vsl.control_mode,
            "final_density": self.last_stats.get("density", "THẤP"),
            "final_traffic_state": self.last_stats.get("traffic_state", "Lưu thông tốt"),
            "final_vsl": self.last_stats.get("suggested_vsl", self.config.vsl.vsl_max),
            "final_priority": self.last_stats.get("priority", "Bình thường"),
            "warning_count": self.warning_count,
            "snapshot_count": self.snapshot_count,
            "event_count": self.event_count,
            "class_counts": self.last_stats.get("class_counts", {k: 0 for k in VEHICLE_CLASSES}),
            "reason": self.last_stats.get("reason", "hệ thống đã khởi tạo"),
            "fps_est": self.last_stats.get("fps_est", 0.0),
            "operator_name": self.session_user.get("full_name", "Unknown"),
            "operator_username": self.session_user.get("username", "unknown"),
            "operator_role": self.session_user.get("role", "vận hành viên"),
            "summary_html_path": str(self.summary_html_path),
        }

    def ghi_bao_cao(self, summary: dict):
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

        with open(self.summary_json_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        with open(self.timeline_txt_path, "w", encoding="utf-8") as f:
            f.write("=== DÒNG THỜI GIAN SỰ KIỆN ===\n")
            for line in self.event_timeline:
                f.write(line + "\n")

        with open(self.summary_txt_path, "w", encoding="utf-8") as f:
            f.write("=== BÁO CÁO TỔNG HỢP HỆ THỐNG VSL ===\n")
            for k, v in summary.items():
                f.write(f"{k}: {v}\n")

        cc = summary.get("class_counts", {})
        timeline_html = "".join(f"<li>{html.escape(line)}</li>" for line in self.event_timeline[-120:])
        heatmap_block = ""
        if self.heatmap_img_path.exists():
            heatmap_block = f'<h2>Bản đồ nhiệt</h2><div class="card"><img src="{html.escape(self.heatmap_img_path.name)}" style="max-width:100%; border-radius:14px;"></div>'

        html_text = f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="UTF-8"><title>VSL Summary Report</title>
<style>
body {{ font-family: Arial, Helvetica, sans-serif; background:#f4f8fc; color:#0f172a; margin:0; padding:24px; }}
.wrap {{ max-width:1100px; margin:0 auto; }}
.hero {{ background:linear-gradient(135deg,#0f172a,#1d4ed8,#06b6d4); color:white; padding:24px; border-radius:18px; margin-bottom:20px; }}
.grid {{ display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:16px; margin-bottom:20px; }}
.card {{ background:white; border:1px solid #dbe5f2; border-radius:16px; padding:18px; }}
.title {{ font-size:14px; color:#64748b; margin-bottom:8px; font-weight:bold; }}
.value {{ font-size:28px; font-weight:800; margin-bottom:6px; }}
table {{ width:100%; border-collapse:collapse; background:white; }}
th, td {{ border:1px solid #e2e8f0; padding:10px 12px; text-align:left; }}
th {{ background:#eff6ff; }}
ul {{ background:white; border:1px solid #dbe5f2; border-radius:16px; padding:18px 28px; }}
.small {{ font-size:13px; color:#475569; }}
</style></head><body>
<div class="wrap">
<div class="hero">
<h1>BÁO CÁO TỔNG HỢP HỆ THỐNG VSL</h1>
<div class="small">Người vận hành: {html.escape(summary["operator_name"])} ({html.escape(summary["operator_role"])})</div>
</div>
<div class="grid">
<div class="card"><div class="title">Video</div><div class="value">{html.escape(summary["video_name"])}</div><div class="small">Số khung hình: {summary["processed_frames"]}</div></div>
<div class="card"><div class="title">Tốc độ VSL cuối cùng</div><div class="value">{summary["final_vsl"]} km/h</div><div class="small">Chế độ: {html.escape(summary["mode"])}</div></div>
<div class="card"><div class="title">Trạng thái giao thông</div><div class="value">{html.escape(summary["final_traffic_state"])}</div><div class="small">Mật độ: {html.escape(summary["final_density"])}</div></div>
<div class="card"><div class="title">Mức ưu tiên</div><div class="value">{html.escape(summary["final_priority"])}</div><div class="small">Cảnh báo: {summary["warning_count"]}</div></div>
</div>
<table>
<tr><th>Thời gian xử lý</th><td>{summary["elapsed_sec"]} s</td></tr>
<tr><th>Thời tiết</th><td>{html.escape(summary["weather"])}</td></tr>
<tr><th>Phân vùng thời tiết</th><td>{html.escape(summary.get("weather_detail", "-"))}</td></tr>
<tr><th>Sự cố</th><td>{html.escape(summary["incident"])}</td></tr>
<tr><th>Lý do</th><td>{html.escape(summary["reason"])}</td></tr>
<tr><th>Ảnh chụp</th><td>{summary["snapshot_count"]}</td></tr>
<tr><th>Sự kiện</th><td>{summary["event_count"]}</td></tr>
</table>
<h2>Phân loại phương tiện</h2>
<table>
<tr><th>Ô tô</th><th>Xe máy</th><th>Xe khách</th><th>Xe tải</th><th>Xe đạp</th></tr>
<tr><td>{cc.get("car",0)}</td><td>{cc.get("motorcycle",0)}</td><td>{cc.get("bus",0)}</td><td>{cc.get("truck",0)}</td><td>{cc.get("bicycle",0)}</td></tr>
</table>
{heatmap_block}
<h2>Dòng thời gian sự kiện</h2>
<ul>{timeline_html if timeline_html else "<li>Không có sự kiện nào được ghi nhận.</li>"}</ul>
</div></body></html>"""

        with open(self.summary_html_path, "w", encoding="utf-8") as f:
            f.write(html_text)

        try:
            base = self.archive_path.with_suffix("")
            shutil.make_archive(str(base), "zip", root_dir=self.outputs_dir)
        except Exception:
            pass

    def run(self):
        try:
            self.outputs_dir.mkdir(parents=True, exist_ok=True)
            with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "frame", "time_sec", "vehicles_in_roi", "avg_vehicles", "density",
                    "traffic_state", "weather", "incident", "mode", "suggested_vsl",
                    "priority", "sudden_increase", "car", "motorcycle", "bus", "truck",
                    "bicycle", "reason"
                ])

            self.tai_mo_hinh()
            self.cap = cv2.VideoCapture(self.video_path)
            if not self.cap.isOpened():
                raise RuntimeError("Không mở được video.")

            width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self.fps_video = self.cap.get(cv2.CAP_PROP_FPS) or 25.0
            self.heatmap_accumulator = np.zeros((height, width), dtype=np.float32)

            self.statusReady.emit(f"Đang phân tích • {width}x{height} • {self.fps_video:.1f} FPS video")
            self.them_su_kien("SYSTEM", f"Bắt đầu phiên: {Path(self.video_path).name}", 0.0)

            while not self.stop_requested:
                if self.pause_requested:
                    self.statusReady.emit("Đã tạm dừng.")
                    self.msleep(100)
                    continue

                ok, frame = self.cap.read()
                if not ok:
                    self.them_su_kien("SYSTEM", "Video đã kết thúc", self.frame_idx / self.fps_video if self.fps_video > 0 else 0.0)
                    break

                self.frame_idx += 1
                self.fps_counter += 1
                frame = self.xu_ly_khung_hinh(frame)
                self.last_frame_bgr = frame.copy()
                self.frameReady.emit(chuyen_bgr_sang_qimage(frame))

                now = time.time()
                dt = now - self.fps_last_time
                if dt >= 1.0:
                    self.fps_est = self.fps_counter / dt
                    self.fps_counter = 0
                    self.fps_last_time = now

                self.msleep(5)

            self.luu_ban_do_nhiet()
            self.ghi_bao_cao(self.tao_tom_tat())

        except Exception:
            self.errorReady.emit(traceback.format_exc())
        finally:
            try:
                if self.cap is not None:
                    self.cap.release()
                    self.cap = None
            except Exception:
                pass
            self.finishedCleanly.emit(self.tao_tom_tat())

    def xu_ly_khung_hinh(self, frame):
        h, w = frame.shape[:2]
        rc = self.config.roi
        poly = tao_da_giac_roi(w, h, rc.top_center_x, rc.bottom_center_x, rc.bottom_width, rc.top_width, rc.height, rc.bottom_y)
        lane_items = []
        if self.config.lane.roi_mode != "ROI thủ công":
            lane_items = tao_lan_duong_tu_roi(
                poly,
                lane_count=self.config.lane.lane_count,
                include_shoulder=self.config.lane.include_shoulder,
            )
        total_in_roi = 0
        class_counts = {name: 0 for name in VEHICLE_CLASSES}
        lane_counts = {label: 0 for label, _ in lane_items}
        t_sec = self.frame_idx / self.fps_video if self.fps_video > 0 else 0.0
        speed_by_box = {}
        so_xe_da_do_toc_do = 0
        so_xe_dang_do_toc_do = 0
        toc_do_tb = 0.0
        toc_do_max = 0.0
        toc_do_text = "Tốc độ xe: chờ xe cắt đủ 2 vạch A/B"
        danh_sach_toc_do = []
        should_infer = (self.frame_idx % max(1, self.config.detection.frame_stride)) == 0
        if should_infer:
            self.last_inference_boxes = []
            if self.model is not None:
                try:
                    device = "cuda:0" if self.config.detection.use_gpu and CUDA_AVAILABLE else "cpu"
                    res = self.model.predict(
                        frame,
                        imgsz=self.config.detection.imgsz,
                        conf=self.config.detection.conf_th,
                        device=device,
                        half=bool(self.config.detection.use_gpu and CUDA_AVAILABLE),
                        verbose=False,
                    )[0]
                    if res.boxes is not None and res.boxes.xyxy is not None:
                        xyxy = res.boxes.xyxy.cpu().numpy()
                        cls = res.boxes.cls.cpu().numpy()
                        confs = res.boxes.conf.cpu().numpy()
                        for box, cls_id, confv in zip(xyxy, cls, confs):
                            raw_name = self.name_map.get(int(cls_id), str(cls_id))
                            name = chuan_hoa_ten_xe(raw_name)
                            if name is None:
                               continue
                            x1, y1, x2, y2 = map(int, box) 
                            cx = (x1 + x2) // 2
                            cy = int(y2 - 0.08 * (y2 - y1))
                            lane_label = None
                            if lane_items:
                                in_roi, lane_label = kiem_tra_diem_trong_lan_duong((cx, cy), lane_items)
                            else:
                                in_roi = kiem_tra_diem_trong_da_giac((cx, cy), poly)
                            if in_roi:
                                total_in_roi += 1
                                class_counts[name] += 1
                                if lane_label is not None:
                                    lane_counts[lane_label] = lane_counts.get(lane_label, 0) + 1
                                if self.heatmap_accumulator is not None:
                                    cv2.circle(self.heatmap_accumulator, (cx, cy), 14, 1.0, -1)
                                color = (0, 255, 102)
                            else:
                                color = (130, 130, 130)
                            self.last_inference_boxes.append((x1, y1, x2, y2, name, float(confv), color, cx, cy, in_roi, lane_label))
                except Exception as e:
                    self.them_nhat_ky(f"[WARN] Lỗi dự đoán YOLO: {e}")

        self.vehicle_history.append(total_in_roi)
        avg_vehicles = round(sum(self.vehicle_history) / max(1, len(self.vehicle_history))) if self.vehicle_history else 0
        density, vsl_speed, traffic_state, reason = tinh_vsl_theo_ngu_canh(avg_vehicles, class_counts, self.config.vsl)
        sudden_increase = (avg_vehicles - self.prev_avg_vehicles) >= self.sudden_increase_threshold
        self.prev_avg_vehicles = avg_vehicles
        priority = tinh_muc_do_uu_tien(density, traffic_state, self.config.vsl.weather, self.config.vsl.incident, sudden_increase, vsl_speed)

        if sudden_increase:
            self.warning_count += 1
            self.them_su_kien("ALERT", f"Mật độ tăng đột biến: trung bình={avg_vehicles}", t_sec)
            self.luu_anh_su_kien(frame, "sudden_density", t_sec)

        if self.last_state != traffic_state:
            self.them_su_kien("STATE", f"Trạng thái giao thông chuyển thành {traffic_state}", t_sec)
            self.luu_anh_su_kien(frame, f"state_{traffic_state.lower().replace(' ', '_')}", t_sec)
            self.last_state = traffic_state

        if self.last_vsl is None:
            self.last_vsl = vsl_speed
        elif abs(vsl_speed - self.last_vsl) >= 10:
            self.them_su_kien("VSL", f"VSL thay đổi từ {self.last_vsl} đến {vsl_speed}", t_sec)
            self.luu_anh_su_kien(frame, f"vsl_{vsl_speed}", t_sec)
            self.last_vsl = vsl_speed

        if self.last_priority != priority:
            self.them_su_kien("PRIORITY", f"Mức ưu tiên chuyển thành {priority}", t_sec)
            if priority in ("Cần can thiệp", "Khẩn cấp"):
                self.luu_anh_su_kien(frame, f"priority_{priority.lower().replace(' ', '_')}", t_sec)
            self.last_priority = priority

        if self.config.display.show_heatmap and self.heatmap_accumulator is not None and np.max(self.heatmap_accumulator) > 0:
            heat_norm = cv2.normalize(self.heatmap_accumulator, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
            heat_color = cv2.applyColorMap(heat_norm, cv2.COLORMAP_JET)
            frame = cv2.addWeighted(frame, 0.75, heat_color, 0.25, 0)

        if self.config.display.show_roi:
            if lane_items and self.config.lane.draw_lanes:
                ve_lan_duong(frame, lane_items, alpha=0.10)
                cv2.polylines(frame, [poly], True, (255, 191, 0), 2)
            else:
                ve_vung_giam_sat(frame, poly)


        # Đo tốc độ bằng hai vạch A/B sau khi đã có box và ROI.
        measured_speed_items = []
        try:
            measured_speed_items = self.speed_tracker.cap_nhat(
                frame_h=h,
                detections=self.last_inference_boxes,
                frame_idx=self.frame_idx,
                fps_video=self.fps_video,
                line_a=self.speed_line_a_ratio,
                line_b=self.speed_line_b_ratio,
                distance_m=self.speed_distance_m,
            )
            speed_values = self.speed_tracker.lay_toc_do()
        except Exception as e:
            speed_values = []
            self.them_nhat_ky(f"[WARN] Lỗi đo tốc độ: {e}")

        # Ghép tốc độ theo đúng box để vẽ cạnh đúng ID xe.
        for item_speed in measured_speed_items:
            try:
                speed_id, speed_kmh, box_speed, lane_speed = item_speed
                box_key = tuple(int(v) for v in box_speed)
                speed_by_box[box_key] = {
                    "id": speed_id,
                    "speed_kmh": speed_kmh,
                    "lane_label": lane_speed,
                }
            except Exception:
                continue

        so_xe_da_do_toc_do = sum(
            1 for item in speed_by_box.values()
            if item.get("speed_kmh") is not None
        )
        so_xe_dang_do_toc_do = max(0, len(speed_by_box) - so_xe_da_do_toc_do)

        if speed_values:
            toc_do_tb = round(sum(speed_values) / len(speed_values), 1)
            toc_do_max = round(max(speed_values), 1)
            toc_do_text = f"Tốc độ xe TB: {toc_do_tb:.1f} km/h | Max: {toc_do_max:.1f} km/h"
        else:
            toc_do_tb = 0.0
            toc_do_max = 0.0
            toc_do_text = "Tốc độ xe: chờ xe cắt đủ 2 vạch A/B"

        y_line_a = int(h * self.speed_line_a_ratio)
        y_line_b = int(h * self.speed_line_b_ratio)
        cv2.line(frame, (0, y_line_a), (w, y_line_a), (255, 255, 0), 2)
        cv2.line(frame, (0, y_line_b), (w, y_line_b), (0, 255, 255), 2)
        cv2.putText(frame, "SPEED LINE A", (24, max(28, y_line_a - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 0), 2, cv2.LINE_AA)
        cv2.putText(frame, f"SPEED LINE B | {self.speed_distance_m:.0f}m",
                    (24, max(28, y_line_b - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2, cv2.LINE_AA)

        for speed_id, speed_kmh, box, lane_label in measured_speed_items:
            if speed_kmh is None:
                continue
            x1s, y1s, x2s, y2s = box
            cv2.putText(frame, f"ID {speed_id} | {speed_kmh:.1f} km/h",
                        (x1s, min(h - 8, y2s + 22)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 255, 0), 2, cv2.LINE_AA)

        if self.config.display.show_boxes:
            try:
                current_vsl = int(float(vsl_speed))
            except Exception:
                current_vsl = 0
            tolerance = 5
            frame_idx = int(getattr(self, "frame_idx", 0))
            violation_saved = getattr(self, "violation_saved", None)
            if not isinstance(violation_saved, dict):
                violation_saved = {}
                self.violation_saved = violation_saved

            for x1, y1, x2, y2, name, confv, color, cx, cy, in_roi, lane_label in self.last_inference_boxes:
                box_key = (int(x1), int(y1), int(x2), int(y2))
                speed_info = speed_by_box.get(box_key, {})
                speed_id = speed_info.get("id")
                speed_kmh = speed_info.get("speed_kmh")

                try:
                    speed_value = float(speed_kmh) if speed_kmh is not None else None
                except Exception:
                    speed_value = None

                is_valid_speed = speed_value is not None and speed_value > 0
                is_violation = bool(
                    is_valid_speed
                    and current_vsl > 0
                    and speed_value > current_vsl + tolerance
                )
                box_color = (0, 0, 255) if is_violation else color
                thickness = 3 if is_violation else (2 if in_roi else 1)

                cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, thickness)
                cv2.circle(
                    frame,
                    (cx, cy),
                    4 if in_roi else 2,
                    (0, 255, 255) if in_roi else box_color,
                    -1,
                )

                label_text = f"{name} {confv:.2f}"
                if speed_id is not None:
                    label_text += f" | ID {speed_id}"

                if not is_valid_speed:
                    label_text += " | dang do toc do..."
                elif is_violation:
                    label_text += f" | VI PHAM | {speed_value:.1f}>{current_vsl} km/h"
                else:
                    label_text += f" | {speed_value:.1f} km/h"

                if lane_label:
                    label_text += f" | {lane_label}"

                label_y = max(24, y1 - 8)
                cv2.putText(
                    frame,
                    label_text,
                    (x1, label_y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (255, 255, 255) if is_violation else box_color,
                    2,
                    cv2.LINE_AA,
                )

                if is_valid_speed:
                    cv2.putText(
                        frame,
                        f"{speed_value:.1f} km/h",
                        (x1, min(h - 8, y2 + 22)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.62,
                        (0, 0, 255) if is_violation else (0, 255, 255),
                        2,
                        cv2.LINE_AA,
                    )

                if is_violation:
                    vsl_text_y = min(h - 8, y2 + 42)
                    cv2.putText(
                        frame,
                        f"VSL: {current_vsl} km/h",
                        (x1, vsl_text_y),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.50,
                        (255, 255, 255),
                        2,
                        cv2.LINE_AA,
                    )

                    key = f"{speed_id}_{current_vsl}"
                    now = time.time()
                    last_save = float(violation_saved.get(key, 0.0) or 0.0)
                    if now - last_save >= 5.0:
                        try:
                            snapshot_root = Path(
                                getattr(self, "snapshots_dir", Path(OUTPUT_DIR) / "snapshots")
                            )
                            violation_dir = snapshot_root / "violations"
                            violation_dir.mkdir(parents=True, exist_ok=True)
                            speed_text = f"{speed_value:.1f}".replace("/", "_")
                            stamp = time.strftime("%Y%m%d_%H%M%S")
                            image_path = violation_dir / (
                                f"vi_pham_ID{speed_id}_speed{speed_text}_"
                                f"vsl{current_vsl}_frame{frame_idx}_{stamp}.jpg"
                            )
                            if cv2.imwrite(str(image_path), frame):
                                violation_saved[key] = now
                                self.snapshot_count += 1
                                if hasattr(self, "warning_count"):
                                    self.warning_count += 1
                                message = (
                                    f"Xe ID {speed_id} vuot VSL: "
                                    f"{speed_value:.1f} km/h > {current_vsl} km/h"
                                )
                                try:
                                    self.them_su_kien("VIOLATION", message, t_sec)
                                except Exception:
                                    try:
                                        self.them_nhat_ky(message)
                                    except Exception:
                                        pass
                        except Exception as exc:
                            try:
                                self.them_nhat_ky(f"Loi luu anh vi pham: {exc}")
                            except Exception:
                                pass

        lane_text = " | ".join([f"{k}:{v}" for k, v in lane_counts.items()]) if lane_counts else "ROI thủ công"
        self.last_stats = {
            "vehicles_in_roi": total_in_roi,
            "avg_vehicles": avg_vehicles,
            "density": density,
            "traffic_state": traffic_state,
            "suggested_vsl": vsl_speed,
            "priority": priority,
            "sudden_increase": sudden_increase,
            "reason": f"{reason} | chế độ={self.config.lane.roi_mode} | làn={lane_text}",
            "class_counts": class_counts,
            "lane_counts": lane_counts,
            "fps_est": round(self.fps_est, 1),
            "toc_do_tb_kmh": toc_do_tb,
            "toc_do_cao_nhat_kmh": toc_do_max,
            "toc_do_text": toc_do_text,
            "so_xe_da_do_toc_do": so_xe_da_do_toc_do,
            "so_xe_dang_do_toc_do": so_xe_dang_do_toc_do,
            "warning_count": self.warning_count,
            "snapshot_count": self.snapshot_count,
            "event_count": self.event_count,
            "summary_html_path": str(self.summary_html_path),
            "camera_id": self.camera_id,
        }
        self.statsReady.emit(self.last_stats)

        now_csv = time.time()
        if now_csv - getattr(self, "last_csv_write_time", 0.0) >= getattr(self, "csv_write_interval", 1.0):
            self.last_csv_write_time = now_csv
            try:
                with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        self.frame_idx, round(t_sec, 2), total_in_roi, avg_vehicles, density,
                        traffic_state, self.config.vsl.weather, self.config.vsl.incident,
                        self.config.vsl.control_mode, vsl_speed, priority, sudden_increase,
                        class_counts.get("car", 0), class_counts.get("motorcycle", 0),
                        class_counts.get("bus", 0), class_counts.get("truck", 0),
                        class_counts.get("bicycle", 0), reason
                    ])
            except Exception as e:
                ghi_log(f"Lỗi ghi CSV: {e}")

        return frame

    def ve_bang_thong_tin(self, frame, total_in_roi, avg_vehicles, density, traffic_state, vsl_speed, priority):
        lines = [
            f"ROI Vehicles: {total_in_roi}",
            f"Avg Vehicles: {avg_vehicles}",
            f"Mật độ: {density}",
            f"State: {traffic_state}",
            f"Tốc độ đề xuất: {vsl_speed} km/h",
            f"Mức ưu tiên: {priority}",
            f"Thời tiết: {self.config.vsl.weather}",
            f"Sự cố: {self.config.vsl.incident}",
            f"Tốc độ xử lý: {self.fps_est:.1f}",
        ]
        overlay = frame.copy()
        cv2.rectangle(overlay, (16, 16), (370, 238), (15, 23, 42), -1)
        cv2.addWeighted(overlay, 0.30, frame, 0.70, 0, frame)
        y = 42
        for line in lines:
            color = (255, 255, 255)
            if "VSL" in line:
                color = (0, 255, 153)
            elif "Mức độ ưu tiên" in line and ("Urgent" in line or "Intervention" in line):
                color = (0, 153, 255)
            cv2.putText(frame, line, (28, y), cv2.FONT_HERSHEY_SIMPLEX, 0.60, color, 2, cv2.LINE_AA)
            y += 22
class MultiCameraWorker(QtCore.QObject):
    frameCameraReady = QtCore.pyqtSignal(str, QtGui.QImage)
    statsCameraReady = QtCore.pyqtSignal(str, dict)
    logCameraReady = QtCore.pyqtSignal(str)

    def __init__(self, danh_sach_camera, config, session_user, parent=None):
        super().__init__(parent)
        self.danh_sach_camera = danh_sach_camera
        self.config = config
        self.session_user = session_user
        self.workers = {}

    def bat_dau(self):
        for cam in self.danh_sach_camera:
            self.logCameraReady.emit(f"[DEBUG] Mở camera: {cam.camera_id} | {cam.duong_dan_video}")

            if not os.path.exists(cam.duong_dan_video):
                self.logCameraReady.emit(f"[LỖI] Không thấy video: {cam.duong_dan_video}")
                continue

            try:
                worker = XuLyVideo(
                    video_path=cam.duong_dan_video,
                    config=self.config,
                    session_user=self.session_user,
                    camera_id=cam.camera_id,
                )
            except TypeError:
                worker = XuLyVideo(
                    cam.duong_dan_video,
                    self.config,
                    self.session_user,
                )
                worker.camera_id = cam.camera_id

            worker.frameReady.connect(
                lambda qimg, cid=cam.camera_id: self.frameCameraReady.emit(cid, qimg)
            )
            worker.statsReady.connect(
                lambda stats, cid=cam.camera_id: self.statsCameraReady.emit(cid, stats)
            )
            worker.logReady.connect(
                lambda text, cid=cam.camera_id: self.logCameraReady.emit(f"[{cid}] {text}")
            )
            worker.errorReady.connect(
                lambda err, cid=cam.camera_id: self.logCameraReady.emit(f"[{cid}] LỖI: {err}")
            )

            worker.start()
            self.workers[cam.camera_id] = worker
            self.logCameraReady.emit(f"[DEBUG] Đã start worker: {cam.camera_id}")
    def dung(self):
        for worker in self.workers.values():
            try:
                worker.yeu_cau_dung()
                worker.dat_tam_dung(False)
            except Exception:
                pass

        for worker in self.workers.values():
            try:
                worker.wait(2000)
            except Exception:
                pass

        self.workers.clear()

    def dang_chay(self):
        return any(worker.isRunning() for worker in self.workers.values())
class GiaoDienChinh(QtWidgets.QMainWindow):
    def __init__(self, session_user: dict):
        super().__init__()
        self.session_user = session_user
        self.worker = None
        self.video_path = None
        self.quan_ly_camera = QuanLyCamera()
        self.camera_hien_tai = None
        self.multi_worker = None
        self.camera_stats = {}
        self.camera_frames = {}
        self.camera_labels = {}
        self.log_lines_max = 320
        self.che_do_chay = "SINGLE"
        self.bo_truyen_bien_chi_dan = TruyenBienChiDan()
        self.bien_bao = BienBaoDienTu()
        self.vsl_da_gui_gan_nhat = None
        self.vsl_gui_gan_nhat = None
        self.config = CauHinhHeThong(
            detection=CauHinhNhanDien(),
            roi=CauHinhROI(),
            lane=CauHinhLanDuong(),
            vsl=CauHinhVSL(),
            display=CauHinhHienThi(),
        )

        self.setWindowTitle("HỆ THỐNG GIÁM SÁT BIỂN BÁO TỐC ĐỘ LINH HOẠT")
        self.resize(1760, 1000)
        self.setMinimumSize(1500, 880)

        self._khoi_tao_giao_dien()
        self._xay_dung_giao_dien()
        self._gan_trang_thai_ban_dau()
        self.update_ui_from_stats({
            "vehicles_in_roi": 0,
            "avg_vehicles": 0,
            "density": "THẤP",
            "traffic_state": "Lưu thông tốt",
            "suggested_vsl": 100,
            "priority": "Bình thường",
            "reason": "hệ thống đã khởi tạo",
            "class_counts": {k: 0 for k in VEHICLE_CLASSES},
            "fps_est": 0.0,
            "warning_count": 0,
            "snapshot_count": 0,
            "event_count": 0,
        })

    def _khoi_tao_giao_dien(self):
        QtWidgets.QApplication.setStyle("Fusion")
        self.setFont(QtGui.QFont("Segoe UI", 10))
        palette = QtGui.QPalette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor("#eef4fb"))
        palette.setColor(QtGui.QPalette.WindowText, QtGui.QColor("#0f172a"))
        palette.setColor(QtGui.QPalette.Base, QtGui.QColor("#ffffff"))
        palette.setColor(QtGui.QPalette.Button, QtGui.QColor("#ffffff"))
        palette.setColor(QtGui.QPalette.ButtonText, QtGui.QColor("#0f172a"))
        palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor("#2563eb"))
        palette.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor("#ffffff"))
        self.setPalette(palette)

        self.setStyleSheet('\n            QMainWindow { background-color:#eef4fb; }\n            QWidget { color:#0f172a; }\n            QFrame#HeroHeader {\n                background:qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #0f172a, stop:0.40 #1d4ed8, stop:1 #06b6d4);\n                border:none; border-radius:24px;\n            }\n            QLabel#HeroTitle { color:white; font-size:24px; font-weight:800; }\n            QLabel#HeroSubtitle { color:rgba(255,255,255,0.88); font-size:11px; font-weight:500; }\n            QLabel#HeroBadge {\n                color:#dbeafe; background-color:rgba(255,255,255,0.14);\n                border:1px solid rgba(255,255,255,0.20); border-radius:14px;\n                padding:6px 12px; font-size:11px; font-weight:700;\n            }\n            QFrame#NavRail { background:rgba(255,255,255,0.94); border:1px solid #d9e6f3; border-radius:20px; }\n            QPushButton#NavButton { background:transparent; border:1px solid transparent; border-radius:16px; text-align:left; }\n            QPushButton#NavButton:hover { background:#f8fbff; border:1px solid #dbe5f2; }\n            QPushButton#NavButton:checked { background:qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #eff6ff, stop:1 #dbeafe); border:1px solid #bfdbfe; }\n            QLabel#NavTitle { font-size:13px; font-weight:800; color:#0f172a; }\n            QLabel#NavSub { font-size:10px; font-weight:600; color:#64748b; }\n            QFrame#ModuleHeader { background:#ffffff; border:1px solid #d9e6f3; border-radius:18px; }\n            QLabel#ModuleTitle { color:#0f172a; font-size:18px; font-weight:800; }\n            QLabel#ModuleSubtitle { color:#64748b; font-size:11px; font-weight:600; }\n            QGroupBox#CardSection { background:rgba(255,255,255,0.97); border:1px solid #d9e6f3; border-radius:18px; margin-top:18px; padding-top:16px; font-weight:800; color:#0f172a; }\n            QGroupBox#CardSection::title { subcontrol-origin:margin; left:14px; top:4px; padding:0 8px; color:#0f172a; background:#eef4fb; border-radius:8px; }\n            QLabel#SectionHint { color:#64748b; font-size:11px; font-weight:500; }\n            QLabel#MetricLabel { color:#334155; font-size:13px; font-weight:700; padding:4px 0; }\n            QPushButton { background-color:#2563eb; color:white; border:none; border-radius:12px; padding:10px 16px; font-weight:700; min-height:18px; }\n            QPushButton:hover { background-color:#1d4ed8; }\n            QPushButton:disabled { background-color:#cbd5e1; color:#ffffff; border:none; }\n            QPushButton#SecondaryBtn { background-color:#ffffff; color:#0f172a; border:1px solid #cbd5e1; }\n            QPushButton#SecondaryBtn:hover { background-color:#f8fafc; }\n            QPushButton#SecondaryBtn:disabled { background-color:#ffffff; color:#64748b; border:1px solid #cbd5e1; }\n            QPushButton#WarningBtn { background-color:#facc15; color:#111827; border:none; }\n            QPushButton#WarningBtn:hover { background-color:#eab308; }\n            QPushButton#WarningBtn:disabled { background-color:#fde68a; color:#78350f; border:none; }\n            QPushButton#DangerBtn { background-color:#ef4444; color:white; border:none; }\n            QPushButton#DangerBtn:hover { background-color:#dc2626; }\n            QPushButton#DangerBtn:disabled { background-color:#fecaca; color:#991b1b; border:none; }\n            QPushButton#SuccessBtn { background-color:#10b981; color:white; border:none; }\n            QPushButton#SuccessBtn:hover { background-color:#059669; }\n            QPushButton#SuccessBtn:disabled { background-color:#bbf7d0; color:#166534; border:none; }\n            QComboBox, QLineEdit { background-color:#ffffff; border:1px solid #d1dbe8; border-radius:10px; padding:8px 10px; min-height:20px; }\n            QCheckBox { spacing:8px; font-weight:600; color:#334155; }\n            QSlider::groove:horizontal { border:none; height:7px; background:#dbe5f0; border-radius:4px; }\n            QSlider::sub-page:horizontal { background:#60a5fa; border-radius:4px; }\n            QSlider::handle:horizontal { background:white; width:18px; margin:-6px 0; border-radius:9px; border:2px solid #2563eb; }\n            QPlainTextEdit { background-color:#fbfdff; border:1px solid #d8e3ef; border-radius:14px; padding:8px; font-family:Consolas; }\n            QFrame#VideoPanel { background:#ffffff; border:1px solid #d9e6f3; border-radius:22px; }\n            QLabel#PanelTitle { color:#0f172a; font-size:16px; font-weight:800; }\n            QLabel#PanelSubTitle { color:#64748b; font-size:11px; font-weight:600; }\n            QLabel#BadgeBlue { background:#dbeafe; color:#1d4ed8; border-radius:10px; padding:8px 12px; font-weight:800; }\n            QLabel#BadgeGreen { background:#dcfce7; color:#15803d; border-radius:10px; padding:8px 12px; font-weight:800; }\n            QLabel#BadgeAmber { background:#fef3c7; color:#b45309; border-radius:10px; padding:8px 12px; font-weight:800; }\n            QLabel#BadgeRed { background:#fee2e2; color:#b91c1c; border-radius:10px; padding:8px 12px; font-weight:800; }\n            QFrame#InsightPanel { background:#ffffff; border:1px solid #d9e6f3; border-radius:18px; }\n            QLabel#InsightTitle { color:#0f172a; font-size:13px; font-weight:800; }\n            QLabel#InsightText { color:#334155; font-size:12px; font-weight:600; }\n            QLabel#StatusLine { color:#2563eb; font-weight:800; font-size:12px; padding:6px 10px; background:#e0ecff; border-radius:10px; }\n            QLabel#ReportPathLabel { color:#0f172a; background:#f8fbff; border:1px solid #d8e3ef; border-radius:12px; padding:10px 12px; font-size:11px; font-weight:600; }\n        ')

    def tao_nhan_trang_thai(self, text="", style="BadgeBlue"):
        lb = QtWidgets.QLabel(text)
        lb.setObjectName(style)
        lb.setAlignment(QtCore.Qt.AlignCenter)
        return lb

    def _xay_dung_giao_dien(self):
        central = QtWidgets.QWidget()
        main = QtWidgets.QVBoxLayout(central)
        main.setContentsMargins(12, 12, 12, 12)
        main.setSpacing(12)
        main.addWidget(self.tao_khu_tieu_de())

        body = QtWidgets.QHBoxLayout()
        body.setSpacing(14)

        module_stack_widget = self.tao_chong_trang_chuc_nang()
        navigation_widget = self.tao_thanh_dieu_huong()
        monitoring_widget = self.tao_khu_giam_sat()

        self.nav_group.buttonClicked[int].connect(self.hieu_ung_chuyen_trang)

        body.addWidget(navigation_widget, 1)
        body.addWidget(module_stack_widget, 2)
        body.addWidget(monitoring_widget, 4)

        main.addLayout(body)
        self.setCentralWidget(central)

    def tao_khu_tieu_de(self):
        hero = QtWidgets.QFrame()
        hero.setObjectName("HeroHeader")
        hero_layout = QtWidgets.QHBoxLayout(hero)
        hero_layout.setContentsMargins(24, 20, 24, 20)
        hero_layout.setSpacing(16)
        left = QtWidgets.QVBoxLayout()
        title = QtWidgets.QLabel("HỆ THỐNG GIÁM SÁT BIỂN BÁO TỐC ĐỘ LINH HOẠT")
        title.setObjectName("HeroTitle")
        subtitle = QtWidgets.QLabel(
            "Giám sát giao thông thông minh • Điều khiển tốc độ linh hoạt • Phân tích thời gian thực"
    )
        subtitle.setObjectName("HeroSubtitle")
        subtitle.setWordWrap(True)

        left.addWidget(title)
        left.addWidget(subtitle)
        right = QtWidgets.QHBoxLayout()
        right.setSpacing(10)

        self.hero_badge_mode = QtWidgets.QLabel("CHẾ ĐỘ: TỰ ĐỘNG")
        self.hero_badge_mode.setObjectName("HeroBadge")
        self.hero_badge_device = QtWidgets.QLabel(
        "THIẾT BỊ: GPU" if self.config.detection.use_gpu else "THIẾT BỊ: CPU"
    )
        self.hero_badge_device.setObjectName("HeroBadge")

        self.hero_badge_status = QtWidgets.QLabel("TRẠNG THÁI: SẴN SÀNG")
        self.hero_badge_status.setObjectName("HeroBadge")

        self.hero_badge_vsl = QtWidgets.QLabel("BIỂN BÁO: 100 km/h")
        self.hero_badge_vsl.setObjectName("HeroBadge")

        self.hero_badge_user = QtWidgets.QLabel(
        f"NGƯỜI DÙNG: {self.session_user.get('username', 'guest').upper()}"
    )
        self.hero_badge_user.setObjectName("HeroBadge")

        right.addStretch()
        right.addWidget(self.hero_badge_mode)
        right.addWidget(self.hero_badge_device)
        right.addWidget(self.hero_badge_status)
        right.addWidget(self.hero_badge_vsl)
        right.addWidget(self.hero_badge_user)

        hero_layout.addLayout(left, 4)
        hero_layout.addLayout(right, 4)

        return hero
    def tao_thanh_dieu_huong(self):
        rail = QtWidgets.QFrame()
        rail.setObjectName("NavRail")
        rail.setMinimumWidth(245)
        rail.setMaximumWidth(285)
        lay = QtWidgets.QVBoxLayout(rail)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(10)

        logo = QtWidgets.QLabel("DANH MỤC")
        logo.setObjectName("MetricLabel")
        lay.addWidget(logo)

        self.nav_group = QtWidgets.QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons = []

        nav_defs = [
            ("Khởi động nhanh", "quy trình nhanh • cấu hình mẫu"),
            ("Phiên làm việc", "video • chạy • báo cáo"),
            ("Nhận diện phương tiện", "độ nhạy AI • hiệu năng"),
            ("Khu vực giám sát", "hình học • vùng theo dõi"),
            ("Điều khiển tốc độ", "quy tắc tốc độ • bối cảnh"),
            ("Báo cáo và lịch sử", "hiển thị • nhật ký • báo cáo"),
        ]
        for idx, (title, sub) in enumerate(nav_defs):
            btn = NutDieuHuong(title, sub)
            self.nav_group.addButton(btn, idx)
            self.nav_buttons.append(btn)
            lay.addWidget(btn)

        user_card = QtWidgets.QFrame()
        user_card.setStyleSheet("background:#f8fbff; border:1px solid #d8e3ef; border-radius:14px;")
        u = QtWidgets.QVBoxLayout(user_card)
        u.setContentsMargins(12, 12, 12, 12)
        u.addWidget(QtWidgets.QLabel(f"Người dùng: {self.session_user.get('full_name', '-') }"))
        u.addWidget(QtWidgets.QLabel(f"Tài khoản: {self.session_user.get('username', '-') }"))
        u.addWidget(QtWidgets.QLabel(f"Vai trò: {self.session_user.get('role', '-') }"))
        self.btn_logout = QtWidgets.QPushButton("Đăng xuất")
        self.btn_logout.setObjectName("SecondaryBtn")
        u.addWidget(self.btn_logout)

        lay.addStretch()
        lay.addWidget(user_card)
        self.nav_buttons[0].setChecked(True)
        return rail

    def tao_chong_trang_chuc_nang(self):
        wrap = QtWidgets.QWidget()
        out = QtWidgets.QVBoxLayout(wrap)
        out.setContentsMargins(0, 0, 0, 0)
        out.setSpacing(0)
        self.stack = QtWidgets.QStackedWidget()
        for page in [
            self.tao_trang_khoi_dong_nhanh(),
            self.tao_trang_phien_lam_viec(),
            self.tao_trang_nhan_dien(),
            self.tao_trang_roi(),
            self.tao_trang_vsl(),
            self.tao_trang_bao_cao(),
        ]:
            self.stack.addWidget(page)
        out.addWidget(self.stack)
        return wrap

    def tao_khu_giam_sat(self):
        right = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(right)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        cards = QtWidgets.QHBoxLayout()
        cards.setSpacing(12)
        self.card_roi = TheThongKeDong("Số xe trong vùng giám sát", "0", "#0ea5e9")
        self.card_vsl = TheThongKeDong("Tốc độ đề xuất", "100 km/h", "#10b981")
        self.card_state = TheThongKeDong("Trạng thái giao thông", "Lưu thông tốt", "#f59e0b")
        self.card_priority = TheThongKeDong("Mức độ ưu tiên", "Bình thường", "#ef4444")
        for card in [self.card_roi, self.card_vsl, self.card_state, self.card_priority]:
            cards.addWidget(card)

        video_panel = QtWidgets.QFrame()
        video_panel.setObjectName("VideoPanel")
        vlay = QtWidgets.QVBoxLayout(video_panel)
        vlay.setContentsMargins(18, 16, 18, 18)
        vlay.setSpacing(12)

        top = QtWidgets.QHBoxLayout()
        left = QtWidgets.QVBoxLayout()
        title = QtWidgets.QLabel("Giám sát giao thông thời gian thực")
        title.setObjectName("PanelTitle")
        sub = QtWidgets.QLabel("Hiển thị video, phương tiện, làn đường, vùng giám sát và biển báo tốc độ đề xuất.")
        sub.setObjectName("PanelSubTitle")
        sub.setWordWrap(True)
        left.addWidget(title)
        left.addWidget(sub)

        badge_box = QtWidgets.QHBoxLayout()
        self.badge_live = self.tao_nhan_trang_thai("TRỰC TUYẾN: TẮT", "BadgeRed")
        self.badge_weather = self.tao_nhan_trang_thai("THỜI TIẾT: TRỜI QUANG", "BadgeBlue")
        self.badge_incident = self.tao_nhan_trang_thai("SỰ CỐ: KHÔNG", "BadgeAmber")
        self.badge_mode = self.tao_nhan_trang_thai("Chế độ: Tự động", "BadgeGreen")
        badge_box.addWidget(self.badge_live)
        badge_box.addWidget(self.badge_weather)
        badge_box.addWidget(self.badge_incident)
        badge_box.addWidget(self.badge_mode)

        top.addLayout(left, 3)
        top.addLayout(badge_box, 3)
        self.video_grid_widget = QtWidgets.QWidget()
        self.video_grid = QtWidgets.QGridLayout(self.video_grid_widget)
        self.video_grid.setContentsMargins(0, 0, 0, 0)
        self.video_grid.setSpacing(10)

        self.video_label = QtWidgets.QLabel("Video giám sát sẽ hiển thị tại đây")
        self.video_label.setAlignment(QtCore.Qt.AlignCenter)
        self.video_label.setMinimumSize(980, 580)
        self.video_label.setStyleSheet(
             "background-color:#081120; border:1px solid #d9e6f3; "
             "border-radius:18px; color:#cbd5e1; font-weight:700;"
)

        self.video_grid.addWidget(self.video_label, 0, 0)

        vlay.addLayout(top)
        vlay.addWidget(self.video_grid_widget)
        insight = QtWidgets.QFrame()
        insight.setObjectName("InsightPanel")
        grid = QtWidgets.QGridLayout(insight)
        grid.setContentsMargins(18, 16, 18, 16)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)

        title2 = QtWidgets.QLabel("Phân tích giao thông")
        title2.setObjectName("InsightTitle")
        grid.addWidget(title2, 0, 0, 1, 2)

        self.lbl_avg = QtWidgets.QLabel("Số xe trung bình: 0")
        self.lbl_density = QtWidgets.QLabel("Mật độ: THẤP")
        self.lbl_state = QtWidgets.QLabel("Trạng thái giao thông: Lưu thông tốt")
        self.lbl_vsl = QtWidgets.QLabel("Tốc độ đề xuất: 100 km/h")
        self.lbl_mode = QtWidgets.QLabel("Chế độ: Tự động")
        self.lbl_weather = QtWidgets.QLabel("Thời tiết: Trời quang | Sự cố: Không")
        self.lbl_priority = QtWidgets.QLabel("Mức ưu tiên: Bình thường")
        self.lbl_alert = QtWidgets.QLabel("Cảnh báo tăng đột biến: Không")
        self.lbl_fps = QtWidgets.QLabel('Tốc độ xử lý: 0.0 Tốc độ xử lý')
        self.lbl_classes = QtWidgets.QLabel("Ô tô: 0 | Xe máy: 0 | Xe khách: 0 | Xe tải: 0 | Xe đạp: 0")
        self.lbl_reason = QtWidgets.QLabel("Lý do: hệ thống đã khởi tạo")
        self.lbl_reason.setWordWrap(True)
        self.lbl_counts = QtWidgets.QLabel("Cảnh báo: 0 | Ảnh chụp: 0 | Sự kiện: 0")
        self.lbl_lane_counts = QtWidgets.QLabel("Số xe theo làn: -")
        self.lbl_action = QtWidgets.QLabel("Khuyến nghị điều hành: Tiếp tục giám sát")

        for lb in [self.lbl_avg, self.lbl_density, self.lbl_state, self.lbl_vsl, self.lbl_mode, self.lbl_weather,
                   self.lbl_priority, self.lbl_alert, self.lbl_fps, self.lbl_classes, self.lbl_reason, self.lbl_counts, self.lbl_lane_counts, self.lbl_action]:
            lb.setObjectName("InsightText")

        grid.addWidget(self.lbl_avg, 1, 0)
        grid.addWidget(self.lbl_density, 1, 1)
        grid.addWidget(self.lbl_state, 2, 0)
        grid.addWidget(self.lbl_vsl, 2, 1)
        grid.addWidget(self.lbl_mode, 3, 0)
        grid.addWidget(self.lbl_weather, 3, 1)
        grid.addWidget(self.lbl_priority, 4, 0)
        grid.addWidget(self.lbl_alert, 4, 1)
        grid.addWidget(self.lbl_fps, 5, 0)
        grid.addWidget(self.lbl_classes, 5, 1)
        grid.addWidget(self.lbl_counts, 6, 0)
        grid.addWidget(self.lbl_action, 6, 1)
        grid.addWidget(self.lbl_lane_counts, 7, 0, 1, 2)
        grid.addWidget(self.lbl_reason, 8, 0, 1, 2)

        layout.addLayout(cards)
        layout.addWidget(video_panel, stretch=8)
        layout.addWidget(insight, stretch=2)
        return right

    def tao_trang_khoi_dong_nhanh(self):
        page = TrangChucNang("Khởi động nhanh", "Luồng thao tác nhanh cho người vận hành.")
        c1 = KhungNoiDung("Quy trình vận hành", "Đi theo 5 bước để chạy nhanh mà không bị rối.")
        for text in [
            "1. Chọn video đầu vào",
            "2. Chọn preset phù hợp",
            "3. Kiểm tra ROI cơ bản",
            "4. Bấm Bắt đầu phân tích",
            "5. Xem cảnh báo và xuất báo cáo",
        ]:
            c1.lay.addWidget(QtWidgets.QLabel(text))
        c2 = KhungNoiDung("Chế độ đơn giản", "Ẩn bớt điều chỉnh nâng cao để giao diện dễ dùng hơn.")
        self.chk_basic_mode = QtWidgets.QCheckBox("Bật chế độ đơn giản")
        self.chk_basic_mode.setChecked(False)
        c2.lay.addWidget(self.chk_basic_mode)
        page.content.addWidget(c1)
        page.content.addWidget(c2)
        return page

    def tao_trang_phien_lam_viec(self):
        page = TrangChucNang("Phiên làm việc", "Điều khiển nguồn video, trạng thái thiết bị và phiên chạy.")
        c1 = KhungNoiDung("Nguồn video", "Bắt đầu từ đây: chọn video, kiểm tra thông tin file.")
        self.cbo_camera = QtWidgets.QComboBox()
        self.cbo_camera.addItem("Video thủ công", None)
        for cam in self.quan_ly_camera.lay_tat_ca():
         self.cbo_camera.addItem(f"{cam.ten_camera} - {cam.vi_tri}", cam.camera_id)
        c1.lay.addWidget(QtWidgets.QLabel("Nguồn camera"))
        c1.lay.addWidget(self.cbo_camera)
        self.btn_open_video = QtWidgets.QPushButton("Chọn video")
        self.btn_open_video.setObjectName("SecondaryBtn")
        self.lbl_video_name = QtWidgets.QLabel("Video: (chưa chọn)")
        self.lbl_video_name.setObjectName("MetricLabel")
        self.lbl_video_res = QtWidgets.QLabel("Độ phân giải: - x -")
        self.lbl_video_res.setObjectName("MetricLabel")
        c1.lay.addWidget(self.btn_open_video)
        c1.lay.addWidget(self.lbl_video_name)
        c1.lay.addWidget(self.lbl_video_res)

        c2 = KhungNoiDung("Phiên chạy", "Điều khiển phân tích và trạng thái runtime.")
        row = QtWidgets.QHBoxLayout()
        self.btn_start = QtWidgets.QPushButton("Bắt đầu phân tích")
        self.btn_start.setObjectName("WarningBtn")
        self.btn_pause = QtWidgets.QPushButton("Tạm dừng")
        self.btn_pause.setObjectName("SecondaryBtn")
        self.btn_stop = QtWidgets.QPushButton("Dừng hệ thống")
        self.btn_stop.setObjectName("DangerBtn")
        row.addWidget(self.btn_start)
        row.addWidget(self.btn_pause)
        row.addWidget(self.btn_stop)
        c2.lay.addLayout(row)

        row2 = QtWidgets.QHBoxLayout()
        self.btn_export = QtWidgets.QPushButton("Lưu ảnh sự kiện")
        self.btn_export.setObjectName("SuccessBtn")
        self.btn_open_output = QtWidgets.QPushButton("Mở thư mục kết quả")
        self.btn_open_output.setObjectName("SecondaryBtn")
        self.btn_open_latest = QtWidgets.QPushButton("Mở báo cáo mới nhất")
        self.btn_open_latest.setObjectName("SecondaryBtn")
        row2.addWidget(self.btn_export)
        row2.addWidget(self.btn_open_output)
        row2.addWidget(self.btn_open_latest)
        self.btn_start_multi = QtWidgets.QPushButton("Chạy tất cả camera")
        self.btn_start_multi.setObjectName("SuccessBtn")
        c2.lay.addWidget(self.btn_start_multi)
        self.btn_start_multi = QtWidgets.QPushButton("Chạy tất cả camera")
        c2.lay.addLayout(row2)
        self.btn_start_multi = QtWidgets.QPushButton("Chạy tất cả camera")
        self.btn_start_multi.setObjectName("SuccessBtn")
        c2.lay.addWidget(self.btn_start_multi)
        self.lbl_device = QtWidgets.QLabel("Thiết bị: GPU" if self.config.detection.use_gpu else "Thiết bị: CPU")
        self.lbl_device.setObjectName("MetricLabel")
        self.chk_gpu = QtWidgets.QCheckBox("Sử dụng tăng tốc GPU")
        self.chk_gpu.setChecked(self.config.detection.use_gpu and CUDA_AVAILABLE)
        self.chk_gpu.setEnabled(CUDA_AVAILABLE and self.session_user.get("role") == "quản trị viên")
        self.lbl_status = QtWidgets.QLabel("Sẵn sàng.")
        self.lbl_status.setObjectName("StatusLine")
        c2.lay.addWidget(self.lbl_device)
        c2.lay.addWidget(self.chk_gpu)
        c2.lay.addWidget(self.lbl_status)

        page.content.addWidget(c1)
        page.content.addWidget(c2)
        return page

    def tao_trang_nhan_dien(self):
        page = TrangChucNang("Nhận diện phương tiện", "Tinh chỉnh độ nhạy AI và hiệu năng xử lý.")
        c1 = KhungNoiDung("Cấu hình mẫu", "Gói cấu hình nhanh cho từng nhu cầu.")
        self.cbo_preset = QtWidgets.QComboBox()
        self.cbo_preset.addItems(["Cân bằng", "Demo nhanh", "Độ chính xác cao"])
        c1.lay.addWidget(self.cbo_preset)

        c2 = KhungNoiDung("Cấu hình nhận diện", "Cân bằng giữa độ chính xác và tốc độ.")
        self.sld_conf = ThanhTruotCoNhan("Độ tin cậy (%)", 10, 90, int(self.config.detection.conf_th * 100))
        self.sld_stride = ThanhTruotCoNhan("Bước nhảy khung hình", 1, 6, self.config.detection.frame_stride)
        self.sld_imgsz = ThanhTruotCoNhan("Kích thước ảnh", 416, 1024, self.config.detection.imgsz, step=32)
        c2.lay.addWidget(self.sld_conf)
        c2.lay.addWidget(self.sld_stride)
        c2.lay.addWidget(self.sld_imgsz)
        page.content.addWidget(c1)
        page.content.addWidget(c2)
        return page

    def tao_trang_roi(self):
        page = TrangChucNang("Khu vực giám sát", "Điều chỉnh vùng mặt đường để phân tích làn và dòng xe.")
        c0 = KhungNoiDung("Hỗ trợ làn đường", "Bổ sung chế độ gán làn mà không làm mất ROI thủ công hiện có.")
        self.cbo_roi_mode = QtWidgets.QComboBox()
        self.cbo_roi_mode.addItems(["ROI thủ công", "Làn bán tự động", "Tự động chia làn từ ROI"])
        self.cbo_roi_mode.setCurrentText(self.config.lane.roi_mode)
        self.sld_lane_count = ThanhTruotCoNhan("Số làn chính", 2, 5, self.config.lane.lane_count)
        self.chk_include_shoulder = QtWidgets.QCheckBox("Tính cả làn khẩn cấp")
        self.chk_include_shoulder.setChecked(self.config.lane.include_shoulder)
        self.chk_draw_lanes = QtWidgets.QCheckBox("Vẽ vùng làn đường")
        self.chk_draw_lanes.setChecked(self.config.lane.draw_lanes)
        c0.lay.addWidget(QtWidgets.QLabel("Chế độ ROI"))
        c0.lay.addWidget(self.cbo_roi_mode)
        c0.lay.addWidget(self.sld_lane_count)
        c0.lay.addWidget(self.chk_include_shoulder)
        c0.lay.addWidget(self.chk_draw_lanes)

        c1 = KhungNoiDung("Vùng ROI hình thang", "Tinh chỉnh vùng hình thang theo phối cảnh thực tế.")
        self.sld_top_cx = ThanhTruotCoNhan("Tâm trên X (%)", 10, 90, int(self.config.roi.top_center_x * 100))
        self.sld_bot_cx = ThanhTruotCoNhan("Tâm dưới X (%)", 10, 90, int(self.config.roi.bottom_center_x * 100))
        self.sld_bot_w = ThanhTruotCoNhan("Độ rộng đáy (%)", 10, 95, int(self.config.roi.bottom_width * 100))
        self.sld_top_w = ThanhTruotCoNhan("Độ rộng đỉnh (%)", 5, 70, int(self.config.roi.top_width * 100))
        self.sld_height = ThanhTruotCoNhan("Chiều cao (%)", 10, 80, int(self.config.roi.height * 100))
        self.sld_bottom_y = ThanhTruotCoNhan("Vị trí đáy Y (%)", 60, 99, int(self.config.roi.bottom_y * 100))
        for widget in [self.sld_top_cx, self.sld_bot_cx, self.sld_bot_w, self.sld_top_w, self.sld_height, self.sld_bottom_y]:
            c1.lay.addWidget(widget)
        c2 = KhungNoiDung("Thao tác nhanh", "Tác vụ nhanh để reset cấu hình ROI.")
        self.btn_reset_roi = QtWidgets.QPushButton("Đặt lại ROI")
        self.btn_reset_roi.setObjectName("SecondaryBtn")
        c2.lay.addWidget(self.btn_reset_roi)
        page.content.addWidget(c0)
        page.content.addWidget(c1)
        page.content.addWidget(c2)
        return page

    def tao_trang_vsl(self):
        page = TrangChucNang("Điều khiển tốc độ", "Cấu hình logic điều chỉnh tốc độ theo mật độ và bối cảnh.")
        c1 = KhungNoiDung("Chính sách tốc độ", "Giới hạn tốc độ và độ mượt của hệ thống.")
        self.sld_vmin = ThanhTruotCoNhan("Tốc độ tối thiểu", 20, 80, self.config.vsl.vsl_min)
        self.sld_vmax = ThanhTruotCoNhan("Tốc độ tối đa", 60, 120, self.config.vsl.vsl_max)
        self.sld_scale_max = ThanhTruotCoNhan("Ngưỡng quy đổi số xe", 5, 50, self.config.vsl.scale_max)
        self.sld_smoothing = ThanhTruotCoNhan("Cửa sổ làm mượt", 5, 120, self.config.vsl.smoothing_window)
        for widget in [self.sld_vmin, self.sld_vmax, self.sld_scale_max, self.sld_smoothing]:
            c1.lay.addWidget(widget)

        c2 = KhungNoiDung("Bối cảnh vận hành", "Bối cảnh thời tiết, sự cố và chế độ điều khiển.")
        self.cbo_weather = QtWidgets.QComboBox()
        self.cbo_weather.addItems(DANH_SACH_THOI_TIET_VI)
        self.cbo_incident = QtWidgets.QComboBox()
        self.cbo_incident.addItems(["Không", "Nhẹ", "Nghiêm trọng"])
        self.cbo_mode = QtWidgets.QComboBox()
        self.cbo_mode.addItems(["Tự động", "Thủ công"])
        self.sld_manual_vsl = ThanhTruotCoNhan("Tốc độ thủ công", 40, 100, self.config.vsl.manual_vsl)
        c2.lay.addWidget(QtWidgets.QLabel("Thời tiết"))
        c2.lay.addWidget(self.cbo_weather)
        c2.lay.addWidget(QtWidgets.QLabel("Sự cố"))
        c2.lay.addWidget(self.cbo_incident)
        c2.lay.addWidget(QtWidgets.QLabel("Chế độ điều khiển"))
        c2.lay.addWidget(self.cbo_mode)
        c2.lay.addWidget(self.sld_manual_vsl)
        page.content.addWidget(c1)
        page.content.addWidget(c2)
        return page

    def tao_trang_bao_cao(self):
        page = TrangChucNang("Báo cáo và lịch sử", "Tùy chọn hiển thị, log và truy cập báo cáo.")
        c1 = KhungNoiDung("Lớp hiển thị", "Bật / tắt các lớp hiển thị để phù hợp với mục tiêu demo.")
        self.chk_show_roi = QtWidgets.QCheckBox("Hiển thị ROI")
        self.chk_show_boxes = QtWidgets.QCheckBox("Hiển thị khung nhận diện")
        self.chk_show_hud = QtWidgets.QCheckBox("Hiển thị HUD")
        self.chk_show_heatmap = QtWidgets.QCheckBox("Hiển thị bản đồ nhiệt")
        self.chk_show_roi.setChecked(self.config.display.show_roi)
        self.chk_show_boxes.setChecked(self.config.display.show_boxes)
        self.chk_show_hud.setChecked(self.config.display.show_hud)
        self.chk_show_heatmap.setChecked(self.config.display.show_heatmap)
        for widget in [self.chk_show_roi, self.chk_show_boxes, self.chk_show_hud, self.chk_show_heatmap]:
            c1.lay.addWidget(widget)

        c2 = KhungNoiDung("Nhật ký phân tích", "Nhật ký phiên phân tích.")
        self.log_view = QtWidgets.QPlainTextEdit()
        self.log_view.setReadOnly(True)
        c2.lay.addWidget(self.log_view)

        c3 = KhungNoiDung("Báo cáo", "Đường dẫn báo cáo và output.")
        self.lbl_report = QtWidgets.QLabel("Báo cáo mới nhất: chưa có báo cáo nào được xuất")
        self.lbl_report.setObjectName("ReportPathLabel")
        self.lbl_report.setWordWrap(True)
        c3.lay.addWidget(self.lbl_report)
        page.content.addWidget(c1)
        page.content.addWidget(c2)
        page.content.addWidget(c3)
        return page

    def _gan_trang_thai_ban_dau(self):
        self.btn_open_video.clicked.connect(self.on_open_video)
        self.cbo_camera.currentIndexChanged.connect(self.on_chon_camera)
        if hasattr(self, "btn_start_multi"):
           self.btn_start_multi.clicked.connect(self.on_start_multi_camera)
        self.btn_start.clicked.connect(self.on_start)
        self.btn_pause.clicked.connect(self.on_pause_resume)
        self.btn_stop.clicked.connect(self.on_stop)
        self.btn_export.clicked.connect(self.on_export_report)
        self.btn_open_output.clicked.connect(lambda: mo_duong_dan_an_toan(str(OUTPUT_DIR)))
        self.btn_open_latest.clicked.connect(self.open_latest_report)
        self.btn_logout.clicked.connect(self.close)

        self.chk_basic_mode.stateChanged.connect(self.xu_ly_che_do_don_gian)

        self.chk_gpu.stateChanged.connect(self.xu_ly_bat_tat_gpu)
        self.cbo_preset.currentTextChanged.connect(self.xu_ly_doi_cau_hinh_mau)

        self.sld_conf.valueChanged.connect(lambda v: setattr(self.config.detection, "conf_th", v / 100.0))
        self.sld_stride.valueChanged.connect(lambda v: setattr(self.config.detection, "frame_stride", max(1, int(v))))
        self.sld_imgsz.valueChanged.connect(self.xu_ly_doi_kich_thuoc_anh)

        self.sld_top_cx.valueChanged.connect(lambda v: setattr(self.config.roi, "top_center_x", v / 100.0))
        self.sld_bot_cx.valueChanged.connect(lambda v: setattr(self.config.roi, "bottom_center_x", v / 100.0))
        self.sld_bot_w.valueChanged.connect(lambda v: setattr(self.config.roi, "bottom_width", v / 100.0))
        self.sld_top_w.valueChanged.connect(lambda v: setattr(self.config.roi, "top_width", v / 100.0))
        self.sld_height.valueChanged.connect(lambda v: setattr(self.config.roi, "height", v / 100.0))
        self.sld_bottom_y.valueChanged.connect(lambda v: setattr(self.config.roi, "bottom_y", v / 100.0))
        self.btn_reset_roi.clicked.connect(self.xu_ly_dat_lai_roi)
        self.cbo_roi_mode.currentTextChanged.connect(lambda t: setattr(self.config.lane, "roi_mode", t))
        self.sld_lane_count.valueChanged.connect(lambda v: setattr(self.config.lane, "lane_count", int(v)))
        self.chk_include_shoulder.stateChanged.connect(lambda s: setattr(self.config.lane, "include_shoulder", s == QtCore.Qt.Checked))
        self.chk_draw_lanes.stateChanged.connect(lambda s: setattr(self.config.lane, "draw_lanes", s == QtCore.Qt.Checked))

        self.sld_vmin.valueChanged.connect(self.xu_ly_doi_vsl_toi_thieu)
        self.sld_vmax.valueChanged.connect(self.xu_ly_doi_vsl_toi_da)
        self.sld_scale_max.valueChanged.connect(lambda v: setattr(self.config.vsl, "scale_max", max(1, int(v))))
        self.sld_smoothing.valueChanged.connect(lambda v: setattr(self.config.vsl, "smoothing_window", max(1, int(v))))
        self.cbo_weather.currentTextChanged.connect(self.xu_ly_doi_thoi_tiet)
        self.cbo_incident.currentTextChanged.connect(self.xu_ly_doi_su_co)
        self.cbo_mode.currentTextChanged.connect(self.xu_ly_doi_che_do)
        self.sld_manual_vsl.valueChanged.connect(lambda v: setattr(self.config.vsl, "manual_vsl", int(v)))

        self.chk_show_roi.stateChanged.connect(lambda s: setattr(self.config.display, "show_roi", s == QtCore.Qt.Checked))
        self.chk_show_boxes.stateChanged.connect(lambda s: setattr(self.config.display, "show_boxes", s == QtCore.Qt.Checked))
        self.chk_show_heatmap.stateChanged.connect(lambda s: setattr(self.config.display, "show_heatmap", s == QtCore.Qt.Checked))

        self.dong_bo_giao_dien_che_do()
        self.dong_bo_trang_thai_chay(False)
        self.xu_ly_che_do_don_gian(QtCore.Qt.Unchecked)


    def hieu_ung_chuyen_trang(self, index: int):
        self.stack.setCurrentIndex(index)
        effect = QtWidgets.QGraphicsOpacityEffect(self.stack.currentWidget())
        self.stack.currentWidget().setGraphicsEffect(effect)
        anim = QtCore.QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(220)
        anim.setStartValue(0.35)
        anim.setEndValue(1.0)
        anim.start(QtCore.QAbstractAnimation.DeleteWhenStopped)

    def xu_ly_che_do_don_gian(self, state):
        basic = state == QtCore.Qt.Checked
        advanced_indices = [2, 4]
        for idx in advanced_indices:
            self.nav_buttons[idx].setVisible(not basic)
        if basic and self.stack.currentIndex() in advanced_indices:
            self.nav_buttons[0].setChecked(True)
            self.stack.setCurrentIndex(0)

    def xu_ly_doi_kich_thuoc_anh(self, v):
        v32 = int(round(v / 32.0) * 32)
        v32 = int(np.clip(v32, 320, 1280))
        self.config.detection.imgsz = v32
        self.sld_imgsz.setValue(v32)

    def xu_ly_dat_lai_roi(self):
        self.config.roi = CauHinhROI()
        self.config.lane = CauHinhLanDuong()
        self.sld_top_cx.setValue(int(self.config.roi.top_center_x * 100))
        self.sld_bot_cx.setValue(int(self.config.roi.bottom_center_x * 100))
        self.sld_bot_w.setValue(int(self.config.roi.bottom_width * 100))
        self.sld_top_w.setValue(int(self.config.roi.top_width * 100))
        self.sld_height.setValue(int(self.config.roi.height * 100))
        self.sld_bottom_y.setValue(int(self.config.roi.bottom_y * 100))
        self.cbo_roi_mode.setCurrentText(self.config.lane.roi_mode)
        self.sld_lane_count.setValue(self.config.lane.lane_count)
        self.chk_include_shoulder.setChecked(self.config.lane.include_shoulder)
        self.chk_draw_lanes.setChecked(self.config.lane.draw_lanes)

    def xu_ly_doi_vsl_toi_thieu(self, v):
        self.config.vsl.vsl_min = min(v, self.config.vsl.vsl_max - 1)
        if self.config.vsl.vsl_min != v:
            self.sld_vmin.setValue(self.config.vsl.vsl_min)

    def xu_ly_doi_vsl_toi_da(self, v):
        self.config.vsl.vsl_max = max(v, self.config.vsl.vsl_min + 1)
        if self.config.vsl.vsl_max != v:
            self.sld_vmax.setValue(self.config.vsl.vsl_max)

    def xu_ly_doi_thoi_tiet(self, text):
        self.config.vsl.weather = text
        self.badge_weather.setText(f"Thời tiết: {text}")
        self.lbl_weather.setText(f"Thời tiết: {self.config.vsl.weather} ({mo_ta_thoi_tiet_chi_tiet(self.config.vsl.weather)}) | Sự cố: {self.config.vsl.incident}")

    def xu_ly_doi_su_co(self, text):
        self.config.vsl.incident = text
        self.badge_incident.setText(f"Sự cố: {text}")
        self.lbl_weather.setText(f"Thời tiết: {self.config.vsl.weather} ({mo_ta_thoi_tiet_chi_tiet(self.config.vsl.weather)}) | Sự cố: {self.config.vsl.incident}")

    def xu_ly_doi_che_do(self, text):
        self.config.vsl.control_mode = text
        self.badge_mode.setText(f"Chế độ: {text}")
        self.hero_badge_mode.setText(f"MODE: {text.upper()}")
        self.lbl_mode.setText(f"Chế độ: {text}")
        self.dong_bo_giao_dien_che_do()

    def dong_bo_giao_dien_che_do(self):
        self.sld_manual_vsl.setEnabled(self.config.vsl.control_mode == "Thủ công")

    def xu_ly_bat_tat_gpu(self, state):
        if self.dang_chay():
            QtWidgets.QMessageBox.warning(self, "Thông báo", 'Không đổi CPU/GPU khi đang chạy. Hãy Dừng trước.')
            self.chk_gpu.blockSignals(True)
            self.chk_gpu.setChecked(self.config.detection.use_gpu)
            self.chk_gpu.blockSignals(False)
            return
        self.config.detection.use_gpu = bool(state == QtCore.Qt.Checked and CUDA_AVAILABLE)
        self.lbl_device.setText("Thiết bị: GPU" if self.config.detection.use_gpu else "Thiết bị: CPU")
        self.hero_badge_device.setText("THIẾT BỊ: GPU" if self.config.detection.use_gpu else "THIẾT BỊ: CPU")

    def xu_ly_doi_cau_hinh_mau(self, text):
        if text == "Demo nhanh":
            self.config.detection.conf_th = 0.35
            self.config.detection.frame_stride = 3
            self.config.detection.imgsz = 512
        elif text == "Độ chính xác cao":
            self.config.detection.conf_th = 0.45
            self.config.detection.frame_stride = 1
            self.config.detection.imgsz = 832
        else:
            self.config.detection.conf_th = 0.40
            self.config.detection.frame_stride = 2
            self.config.detection.imgsz = 640
        self.sld_conf.setValue(int(self.config.detection.conf_th * 100))
        self.sld_stride.setValue(self.config.detection.frame_stride)
        self.sld_imgsz.setValue(self.config.detection.imgsz)

    def bat_tat_dieu_khien_khi_chay(self, running: bool):
        controls = [
            self.cbo_preset, self.sld_imgsz, self.sld_conf, self.sld_stride,
            self.sld_top_cx, self.sld_bot_cx, self.sld_bot_w, self.sld_top_w, self.sld_height,
            self.sld_bottom_y, self.btn_reset_roi, self.sld_vmin, self.sld_vmax, self.sld_scale_max,
            self.sld_smoothing, self.cbo_weather, self.cbo_incident, self.cbo_mode, self.sld_manual_vsl
        ]
        for w in controls:
            w.setEnabled(True)

    def dong_bo_trang_thai_chay(self, running: bool):
        self.btn_open_video.setEnabled(True)
        self.btn_start.setEnabled(not running and bool(self.video_path))
        self.btn_pause.setEnabled(running)
        self.btn_stop.setEnabled(running)
        self.chk_gpu.setEnabled((not running) and CUDA_AVAILABLE and self.session_user.get("role") == "quản trị viên")
        self.bat_tat_dieu_khien_khi_chay(running)

        self.lbl_status.setText("Đang chạy..." if running else "Sẵn sàng." if not self.video_path else "Sẵn sàng chạy.")
        self.hero_badge_status.setText("TRẠNG THÁI: ĐANG CHẠY" if running else "TRẠNG THÁI: SẴN SÀNG" if not self.video_path else "TRẠNG THÁI: ĐÃ CHỌN VIDEO")

        self.badge_live.setText("TRỰC TUYẾN: BẬT" if running else "TRỰC TUYẾN: TẮT")
        self.badge_live.setObjectName("BadgeGreen" if running else "BadgeRed")
        self.badge_live.style().unpolish(self.badge_live)
        self.badge_live.style().polish(self.badge_live)

    def dang_chay(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

def dung_luong_xu_ly_an_toan(self, timeout_ms=3000):
    if self.worker is None:
        return True

    try:
        if self.worker.isRunning():
            self.worker.yeu_cau_dung()
            self.worker.dat_tam_dung(False)

            deadline = time.time() + (timeout_ms / 1000.0)
            while self.worker.isRunning() and time.time() < deadline:
                QtWidgets.QApplication.processEvents()
                self.worker.wait(50)

        if self.worker is not None and not self.worker.isRunning():
            self.worker = None
            return True
    except Exception:
        pass

        return False
    def _finalize_worker_ui(self):
        self.dong_bo_trang_thai_chay(False)
        self.btn_pause.setText("Tạm dừng")
        self.worker = None
        self.badge_live.setText("TRỰC TUYẾN: TẮT")
        self.badge_live.setObjectName("BadgeRed")
        self.badge_live.style().unpolish(self.badge_live)
        self.badge_live.style().polish(self.badge_live)
        if self.video_path:
            self.hero_badge_status.setText("TRẠNG THÁI: ĐÃ CHỌN VIDEO")
        else:
            self.hero_badge_status.setText("TRẠNG THÁI: SẴN SÀNG")
        self.lbl_status.setText("Sẵn sàng chạy." if self.video_path else "Sẵn sàng.")

    def dung_luong_xu_ly_an_toan(self, timeout_ms=4000, force_terminate=True):
        if self.worker is None:
            self._finalize_worker_ui()
            return True

        try:
            self.worker.yeu_cau_dung()
            self.worker.dat_tam_dung(False)

            if self.worker.isRunning():
                deadline = time.time() + (timeout_ms / 1000.0)
                while self.worker.isRunning() and time.time() < deadline:
                    QtWidgets.QApplication.processEvents()
                    self.worker.wait(50)

            if self.worker is not None and self.worker.isRunning() and force_terminate:
                self.append_log('[CẢNH BÁO] Worker stop timeout. Force terminating worker...')
                try:
                    self.worker.terminate()
                    self.worker.wait(1000)
                except Exception:
                    pass

            stopped = (self.worker is None) or (not self.worker.isRunning())
            if stopped:
                self._finalize_worker_ui()
                return True
        except Exception as e:
            self.append_log(f"[ERROR] stop_worker_blocking failed: {e}")

        return False


    def tao_nhom_hieu_chinh_toc_do(self):
        group = KhungNoiDung(
            "Hiệu chỉnh vạch đo tốc độ",
            "Mỗi video có góc quay khác nhau. Chỉnh A/B và khoảng cách thật rồi bấm Lưu cấu hình tốc độ."
        )

        self.sld_speed_a = ThanhTruotCoNhan("Vạch A (%)", 10, 85, int(SPEED_LINE_A_RATIO * 100))
        self.sld_speed_b = ThanhTruotCoNhan("Vạch B (%)", 15, 95, int(SPEED_LINE_B_RATIO * 100))
        self.sld_speed_dist = ThanhTruotCoNhan("Khoảng cách A-B (m)", 5, 150, int(SPEED_DISTANCE_METERS))

        self.sld_speed_a.valueChanged.connect(self.cap_nhat_cau_hinh_toc_do_tu_slider)
        self.sld_speed_b.valueChanged.connect(self.cap_nhat_cau_hinh_toc_do_tu_slider)
        self.sld_speed_dist.valueChanged.connect(self.cap_nhat_cau_hinh_toc_do_tu_slider)

        self.btn_save_speed_profile = QtWidgets.QPushButton("Lưu vạch cho video này")
        self.btn_save_speed_profile.clicked.connect(self.luu_cau_hinh_toc_do_hien_tai)

        self.lbl_speed_profile = QtWidgets.QLabel("Cấu hình tốc độ: mặc định")
        self.lbl_speed_profile.setWordWrap(True)

        group.lay.addWidget(self.sld_speed_a)
        group.lay.addWidget(self.sld_speed_b)
        group.lay.addWidget(self.sld_speed_dist)
        group.lay.addWidget(self.btn_save_speed_profile)
        group.lay.addWidget(self.lbl_speed_profile)

        return group

    def nap_cau_hinh_toc_do_cho_video(self, video_path=None):
        video_path = video_path or self.video_path
        cfg = doc_cau_hinh_toc_do_video(video_path or "")

        try:
            self.sld_speed_a.setValue(int(float(cfg["line_a"]) * 100))
            self.sld_speed_b.setValue(int(float(cfg["line_b"]) * 100))
            self.sld_speed_dist.setValue(int(float(cfg["distance_m"])))
            self.lbl_speed_profile.setText(
                f"Vạch A: {float(cfg['line_a']):.2f} | "
                f"Vạch B: {float(cfg['line_b']):.2f} | "
                f"Khoảng cách: {float(cfg['distance_m']):.1f} m"
            )
        except Exception:
            pass

    def cap_nhat_cau_hinh_toc_do_tu_slider(self):
        try:
            a = self.sld_speed_a.slider.value() / 100.0
            b = self.sld_speed_b.slider.value() / 100.0
            d = float(self.sld_speed_dist.slider.value())

            if b <= a + 0.05:
                b = min(0.95, a + 0.05)
                self.sld_speed_b.setValue(int(b * 100))

            if self.worker is not None:
                self.worker.speed_line_a_ratio = a
                self.worker.speed_line_b_ratio = b
                self.worker.speed_distance_m = d
                try:
                    self.worker.speed_tracker.reset()
                except Exception:
                    pass

            self.lbl_speed_profile.setText(
                f"Vạch A: {a:.2f} | Vạch B: {b:.2f} | Khoảng cách: {d:.1f} m"
            )
        except Exception:
            pass

    def luu_cau_hinh_toc_do_hien_tai(self):
        if not self.video_path:
            QtWidgets.QMessageBox.warning(self, "Tốc độ", "Chưa chọn video.")
            return

        a = self.sld_speed_a.slider.value() / 100.0
        b = self.sld_speed_b.slider.value() / 100.0
        d = float(self.sld_speed_dist.slider.value())

        if b <= a + 0.05:
            QtWidgets.QMessageBox.warning(self, "Tốc độ", "Vạch B phải thấp hơn vạch A ít nhất 5%.")
            return

        ok = luu_cau_hinh_toc_do_video(self.video_path, a, b, d)
        if ok:
            QtWidgets.QMessageBox.information(self, "Tốc độ", "Đã lưu vạch đo tốc độ cho video này.")
            self.nap_cau_hinh_toc_do_cho_video(self.video_path)
        else:
            QtWidgets.QMessageBox.warning(self, "Tốc độ", "Không lưu được cấu hình tốc độ.")

    def on_open_video(self):
        if self.che_do_chay == "MULTI":
            QtWidgets.QMessageBox.warning(
                self,
                "Đang chạy đa camera",
                "Hãy bấm Dừng hệ thống trước khi chọn video thủ công."
            )
            return

        fn, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Chọn video",
            "",
            "Video files (*.mp4 *.avi *.mkv *.mov);;All files (*)"
        )

        if not fn:
            return

        self.camera_hien_tai = None
        self.video_path = fn

        if hasattr(self, "cbo_camera"):
            self.cbo_camera.blockSignals(True)
            self.cbo_camera.setCurrentIndex(0)
            self.cbo_camera.blockSignals(False)

        self.lbl_video_name.setText(f"Video: {Path(fn).name}")

        cap = cv2.VideoCapture(fn)
        if cap.isOpened():
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self.lbl_video_res.setText(f"Resolution: {w} x {h}")
        cap.release()

        self.video_label.clear()
        self.video_label.setText("Video đã chọn. Bấm Bắt đầu phân tích.")
        self.dong_bo_trang_thai_chay(False)
        self.nap_cau_hinh_toc_do_cho_video(fn)
        self.append_log(f"[SYSTEM] Video selected: {Path(fn).name}")

    def on_start(self):
        self.che_do_chay = "SINGLE"

        if self.multi_worker is not None:
            self.multi_worker.dung()
            self.multi_worker = None
            self.camera_frames = {}
            self.camera_stats = {}
            self.append_log("[MULTI-CAMERA] Đã dừng đa camera để chạy chế độ đơn")

        self.btn_open_video.setEnabled(True)
        self.btn_start.setEnabled(True)
        self.cbo_camera.setEnabled(True)

        if self.dang_chay():
            return

        if self.worker is not None and not self.dang_chay():
            self.dung_luong_xu_ly_an_toan(
                timeout_ms=500,
                force_terminate=False
            )

        if not self.video_path or not os.path.isfile(self.video_path):
            QtWidgets.QMessageBox.warning(
                self,
                "Lỗi",
                "Chưa chọn video hoặc đường dẫn không hợp lệ."
            )
            return

        self.log_view.clear()

        camera_id = (
            self.camera_hien_tai.camera_id
            if self.camera_hien_tai
            else "VIDEO_THU_CONG"
        )

        self.video_label.show()

        self.worker = XuLyVideo(
            self.video_path,
            self.config,
            self.session_user,
            camera_id=camera_id,
        )

        self.worker.frameReady.connect(self.show_frame)
        self.worker.statsReady.connect(self.update_ui_from_stats)
        self.worker.statusReady.connect(self.on_worker_status)
        self.worker.logReady.connect(self.append_log)
        self.worker.errorReady.connect(self.on_worker_error)
        self.worker.finishedCleanly.connect(self.on_worker_finished)

        self.worker.start()

        self.btn_pause.setText("Tạm dừng")
        self.dong_bo_trang_thai_chay(True)
        self.hero_badge_status.setText("TRẠNG THÁI: ĐANG CHẠY")
        self.lbl_status.setText("Đang phân tích video...")

    def on_pause_resume(self):
        if self.worker is None:
            return
        if self.btn_pause.text() == "Tạm dừng":
            self.worker.dat_tam_dung(True)
            self.btn_pause.setText("Tiếp tục")
            self.hero_badge_status.setText("TRẠNG THÁI: TẠM DỪNG")
            self.lbl_status.setText("Đã tạm dừng.")
            self.badge_live.setText("TRỰC TUYẾN: TẠM DỪNG")
            self.badge_live.setObjectName("BadgeAmber")
        else:
            self.worker.dat_tam_dung(False)
            self.btn_pause.setText("Tạm dừng")
            self.hero_badge_status.setText("TRẠNG THÁI: ĐANG CHẠY")
            self.lbl_status.setText("Đang chạy...")
            self.badge_live.setText("TRỰC TUYẾN: BẬT")
            self.badge_live.setObjectName("BadgeGreen")
            self.badge_live.style().unpolish(self.badge_live)
            self.badge_live.style().polish(self.badge_live)

    def on_stop(self):
        if self.multi_worker is not None:
            self.multi_worker.dung()
            self.multi_worker = None
            self.camera_frames = {}
            self.append_log("[MULTI-CAMERA] Đã dừng tất cả camera")
    if self.multi_worker is not None:
            self.multi_worker.dung()
            self.multi_worker = None
            self.append_log("[MULTI-CAMERA] Đã dừng tất cả camera")
    if self.worker is not None:
            try:
                self.worker.yeu_cau_dung()
                self.worker.dat_tam_dung(False)
            except Exception:
                pass
            self.lbl_status.setText("Đang dừng...")
            self.hero_badge_status.setText("TRẠNG THÁI: ĐANG DỪNG")
            self.badge_live.setText("TRỰC TUYẾN: ĐANG DỪNG")
            self.badge_live.setObjectName("BadgeAmber")
            self.badge_live.style().unpolish(self.badge_live)
            self.badge_live.style().polish(self.badge_live)
            QtCore.QTimer.singleShot(4500, lambda: self.dung_luong_xu_ly_an_toan(timeout_ms=100, force_terminate=True) if self.worker is not None else None)
            self.che_do_chay = "SINGLE"
            self.btn_open_video.setEnabled(True)
            self.btn_start.setEnabled(True)
            self.cbo_camera.setEnabled(True)
            self.video_label.clear()
            self.video_label.setText("Video giám sát sẽ hiển thị tại đây")
    def open_latest_report(self):
        text = self.lbl_report.text().replace("Báo cáo mới nhất: ", "").strip()
        if text and os.path.exists(text):
            mo_duong_dan_an_toan(text)
        else:
            mo_duong_dan_an_toan(str(OUTPUT_DIR))

    def on_export_report(self):
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        snapshot = {
            "config": asdict(self.config),
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "video_path": self.video_path,
            "session_user": self.session_user,
        }
        path = OUTPUT_DIR / "manual_export_snapshot.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
        self.lbl_report.setText(f"Latest report: {path}")
        self.append_log(f"[REPORT] Exported manual snapshot: {path}")
        QtWidgets.QMessageBox.information(self, "Xuất báo cáo", f"Đã lưu snapshot config tại:\n{path}")

    def on_worker_status(self, text: str):
        self.lbl_status.setText(text)

    def on_worker_error(self, err: str):
        self.dong_bo_trang_thai_chay(False)
        self.append_log("[LỖI] Bộ xử lý video gặp sự cố")
        self.hero_badge_status.setText("TRẠNG THÁI: LỖI")
        QtWidgets.QMessageBox.critical(self, "Lỗi khi chạy", err)

    def on_worker_finished(self, summary: dict):
        self.dong_bo_trang_thai_chay(False)
        self.btn_pause.setText("Tạm dừng")
        self.worker = None
        html_path = summary.get("summary_html_path", "")
        if html_path and os.path.exists(html_path):
            self.lbl_report.setText(f"Latest report: {html_path}")
        self.append_log("[HỆ THỐNG] Phiên phân tích đã kết thúc")
        self.hero_badge_status.setText("TRẠNG THÁI: HOÀN THÀNH")

    def append_log(self, text: str):
        current = self.log_view.toPlainText().splitlines()
        current.append(text)
        current = current[-self.log_lines_max:]
        self.log_view.setPlainText("\n".join(current))
        self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())

    def update_ui_from_stats(self, stats: dict):
        vehicles_in_roi = stats.get("vehicles_in_roi", 0)
        avg_vehicles = stats.get("avg_vehicles", 0)
        density = stats.get("density", "THẤP")
        traffic_state = stats.get("traffic_state", "Lưu thông tốt")
        vsl = stats.get("suggested_vsl", 100)
        camera_id = stats.get(
              "camera_id",
              "CAM_01"
                       )

        density = stats.get(
              "density",
              "THẤP"  )

        traffic_state = stats.get(
              "traffic_state",
              "Bình thường"
)

        if self.vsl_gui_gan_nhat != vsl:
           self.bien_bao.gui_lenh(
               camera_id,
               vsl,
              density,
              traffic_state
    )

           self.vsl_gui_gan_nhat = vsl
           self.append_log(f"[BIỂN BÁO] Đã gửi {vsl} km/h")
        priority = stats.get("priority", "Bình thường")
        reason = stats.get("reason", "hệ thống đã khởi tạo")
        camera_id = stats.get("camera_id", "CAM_00")
        if self.vsl_da_gui_gan_nhat != vsl:
           ok, msg = self.bo_truyen_bien_chi_dan.gui_toc_do(
               toc_do=vsl,
               camera_id=camera_id,
               ly_do=reason
            )
        self.vsl_da_gui_gan_nhat = vsl
        if ok:
            self.append_log(f"[BIỂN CHỈ DẪN] {msg}")
        else:
            self.append_log(f"[BIỂN CHỈ DẪN] Lỗi gửi: {msg}")
        classes = stats.get("class_counts", {k: 0 for k in VEHICLE_CLASSES})
        fps_est = stats.get("fps_est", 0.0) 
        vehicles = stats.get("vehicles_in_roi", 0)
        avg_vehicles = stats.get("avg_vehicles", 0)
        class_counts = stats.get("class_counts", {})
        tong_xe_phan_loai = sum(class_counts.values()) if isinstance(class_counts, dict) else 0
        diem = 70
        if vehicles > 0:
            diem += 10 
        if avg_vehicles > 0:
           diem += 10

        if tong_xe_phan_loai > 0:
           diem += 8

        if fps_est >= 5:
           diem += 2

        do_tin_cay_ai = max(0, min(99, diem))
        sudden = stats.get("sudden_increase", False)
        warnings = stats.get("warning_count", 0)
        snapshots = stats.get("snapshot_count", 0)
        events = stats.get("event_count", 0)
        lane_counts = stats.get("lane_counts", {})

        self.card_roi.dat_gia_tri(str(vehicles_in_roi))
        self.card_roi.dat_mo_ta(f"Trung bình trong cửa sổ: {avg_vehicles}")
        self.card_vsl.dat_gia_tri(f"{vsl} km/h")
        self.card_vsl.dat_mo_ta(reason)
        self.card_state.dat_gia_tri(traffic_state)
        self.card_state.dat_mo_ta(f"Mật độ: {density}")
        self.card_priority.dat_gia_tri(priority)
        self.card_priority.dat_mo_ta(f"Thời tiết: {self.config.vsl.weather}")

        if priority == "Bình thường":
            self.lbl_action.setText("Khuyến nghị điều hành: Tiếp tục giám sát")
        elif priority == "Theo dõi":
            self.lbl_action.setText("Khuyến nghị điều hành: Theo dõi sát tình hình giao thông")
        elif priority == "Cần can thiệp":
            self.lbl_action.setText("Khuyến nghị điều hành: Cân nhắc can thiệp VSL")
        else:
            self.lbl_action.setText("Khuyến nghị điều hành: Cần người vận hành xử lý ngay")

        self.lbl_avg.setText(f"Số xe trung bình: {avg_vehicles}")
        self.lbl_density.setText(f"Mật độ: {density}")
        self.lbl_state.setText(f"Trạng thái giao thông: {traffic_state}")
        self.lbl_vsl.setText(f"Tốc độ đề xuất: {vsl} km/h")
        self.lbl_mode.setText(f"Chế độ: {self.config.vsl.control_mode}")
        self.lbl_weather.setText(f"Thời tiết: {self.config.vsl.weather} ({mo_ta_thoi_tiet_chi_tiet(self.config.vsl.weather)}) | Sự cố: {self.config.vsl.incident}")
        self.lbl_priority.setText(f"Mức ưu tiên: {priority}")
        self.lbl_alert.setText(f"Cảnh báo tăng đột biến: {'Có' if sudden else 'Không'}")
        if do_tin_cay_ai >= 90:
            muc_tin_cay = "CAO"
        elif do_tin_cay_ai >= 80:
             muc_tin_cay = "KHÁ"
        else:
             muc_tin_cay = "TRUNG BÌNH"

        self.lbl_fps.setText( f"Tốc độ xử lý: {fps_est:.1f} | Độ tin cậy AI: {do_tin_cay_ai:.1f}%")
        self.lbl_classes.setText(
            f"Ô tô: {classes.get('car',0)} | Xe máy: {classes.get('motorcycle',0)} | Bus: {classes.get('bus',0)} | Xe tải: {classes.get('truck',0)} | Xe đạp: {classes.get('bicycle',0)}"
        )
        self.lbl_counts.setText(f"Cảnh báo: {warnings} | Ảnh chụp: {snapshots} | Sự kiện: {events}")
        if lane_counts:
            self.lbl_lane_counts.setText("Số xe theo làn: " + " | ".join([f"{k}:{v}" for k, v in lane_counts.items()]))
        else:
            self.lbl_lane_counts.setText('Số xe theo làn: ROI thủ công')
        self.lbl_reason.setText(f"Lý do: {reason}")

        html_path = stats.get("summary_html_path")
        if html_path:
            self.lbl_report.setText(f"Latest report: {html_path}")
        def show_frame(self, qimg: QtGui.QImage):
             self.video_label.show()
             pix: QtGui.QPixmap = QtGui.QPixmap.fromImage(qimg)
             scaled = pix.scaled(
            self.video_label.size(),
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation,
        )  
        self.video_label.setPixmap(scaled)
    def on_chon_camera(self):
        if self.che_do_chay == "MULTI":
            return

        camera_id = self.cbo_camera.currentData()

        if not camera_id:
            self.camera_hien_tai = None
            self.video_path = None
            self.lbl_video_name.setText("Video: (chưa chọn)")
            self.lbl_video_res.setText("Độ phân giải: - x -")
            return

        cam = self.quan_ly_camera.lay_camera_theo_id(camera_id)

        if cam is None:
            return

        self.camera_hien_tai = cam
        self.video_path = cam.duong_dan_video

        self.lbl_video_name.setText(f"Camera: {cam.ten_camera}")
        self.lbl_video_res.setText(f"Vị trí: {cam.vi_tri}")
        self.video_label.clear()
        self.video_label.setText("Camera đã chọn. Bấm Bắt đầu phân tích.")

        self.append_log(f"[CAMERA] Đã chọn {cam.ten_camera} - {cam.vi_tri}")
        self.dong_bo_trang_thai_chay(False)

    def tao_o_camera(self, camera_id):
        if camera_id in self.camera_labels:
            return self.camera_labels[camera_id]

        label = QtWidgets.QLabel(f"{camera_id}")
        label.setAlignment(QtCore.Qt.AlignCenter)
        label.setMinimumSize(430, 260)
        label.setStyleSheet(
            "background-color:#081120; border:1px solid #38bdf8; "
            "border-radius:14px; color:white; font-weight:700;"
        )

        index = len(self.camera_labels)
        row = index // 2
        col = index % 2

        self.video_grid.addWidget(label, row + 1, col)
        self.camera_labels[camera_id] = label

        return label
    def on_start_multi_camera(self):
        self.che_do_chay = "MULTI"

        if self.worker is not None:
            try:
                self.worker.yeu_cau_dung()
                self.worker.dat_tam_dung(False)
                self.worker.wait(1500)
            except Exception:
                pass
            self.worker = None

        if self.multi_worker is not None and self.multi_worker.dang_chay():
            QtWidgets.QMessageBox.information(
                self,
                "Đa camera",
                "Hệ thống đa camera đang chạy."
            )
            return

        danh_sach_camera = self.quan_ly_camera.lay_camera_dang_bat()

        if not danh_sach_camera:
            QtWidgets.QMessageBox.warning(
                self,
                "Lỗi",
                "Không có camera nào được bật."
            )
            self.che_do_chay = "SINGLE"
            return

        self.btn_open_video.setEnabled(False)
        self.btn_start.setEnabled(False)
        self.cbo_camera.setEnabled(False)

        self.camera_stats = {}
        self.camera_frames = {}

        self.video_label.show()
        self.video_label.clear()
        self.video_label.setText("Đang chạy đa camera...")

        self.multi_worker = MultiCameraWorker(
            danh_sach_camera=danh_sach_camera,
            config=self.config,
            session_user=self.session_user,
        )

        self.multi_worker.frameCameraReady.connect(self.on_multi_camera_frame)
        self.multi_worker.statsCameraReady.connect(self.on_multi_camera_stats)
        self.multi_worker.logCameraReady.connect(self.append_log)

        self.multi_worker.bat_dau()

        self.lbl_status.setText("Đang chạy đa camera...")
        self.hero_badge_status.setText("TRẠNG THÁI: ĐA CAMERA")
        self.badge_live.setText("TRỰC TUYẾN: ĐA CAMERA")
        self.badge_live.setObjectName("BadgeGreen")
        self.badge_live.style().unpolish(self.badge_live)
        self.badge_live.style().polish(self.badge_live)
        self.append_log("[MULTI-CAMERA] Đã chạy tất cả camera")
    def on_multi_camera_frame(self, camera_id, qimg):
        print("NHAN FRAME TU:", camera_id)
        self.append_log(f"[FRAME] Nhận frame từ {camera_id}")
        self.camera_frames[camera_id] = qimg
        items = list(self.camera_frames.items())
        if hasattr(self, "hero_badge_vsl"):
            self.hero_badge_vsl.setText("BIỂN BÁO: ĐA CAMERA")
        if not items:
            return

        cell_w = 520
        cell_h = 300

        canvas_w = cell_w * 2
        canvas_h = cell_h * 2

        mosaic = QtGui.QPixmap(canvas_w, canvas_h)
        mosaic.fill(QtGui.QColor("#081120"))

        painter = QtGui.QPainter(mosaic)

        for index, (cid, img) in enumerate(items[:4]):
            row = index // 2
            col = index % 2

            x0 = col * cell_w
            y0 = row * cell_h

            pix = QtGui.QPixmap.fromImage(img)
            pix = pix.scaled(
                cell_w,
                cell_h,
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation,
            )

            px = x0 + (cell_w - pix.width()) // 2
            py = y0 + (cell_h - pix.height()) // 2

            painter.fillRect(x0, y0, cell_w, cell_h, QtGui.QColor("#081120"))
            painter.drawPixmap(px, py, pix)

            painter.setPen(QtGui.QColor("#ffffff"))
            painter.setFont(QtGui.QFont("Segoe UI", 12, QtGui.QFont.Bold))
            painter.drawText(x0 + 12, y0 + 28, cid)

            painter.setPen(QtGui.QColor("#38bdf8"))
            painter.drawRect(x0, y0, cell_w - 1, cell_h - 1)

        painter.end()
        scaled = mosaic.scaled(
            self.video_label.size(),
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation,
        )

        self.video_label.setPixmap(scaled)

    def on_multi_camera_stats(self, camera_id, stats):
        self.camera_stats[camera_id] = stats

        tong_xe = sum(
            s.get("vehicles_in_roi", 0)
            for s in self.camera_stats.values()
        )

        vsl_min = min(
            [s.get("suggested_vsl", 100) for s in self.camera_stats.values()] or [100]
        )

        tong_canh_bao = sum(
            s.get("warning_count", 0)
            for s in self.camera_stats.values()
        )

        tong_su_kien = sum(
            s.get("event_count", 0)
            for s in self.camera_stats.values()
        )

        stats_tong = dict(stats)
        stats_tong["vehicles_in_roi"] = tong_xe
        stats_tong["suggested_vsl"] = vsl_min
        stats_tong["warning_count"] = tong_canh_bao
        stats_tong["event_count"] = tong_su_kien
        stats_tong["reason"] = f"Tổng hợp đa camera | Camera hiện tại: {camera_id}"

        self.update_ui_from_stats(stats_tong)
    def closeEvent(self, event: QtGui.QCloseEvent):
        try:
            if self.worker is not None and self.worker.isRunning():
                self.worker.yeu_cau_dung()
                self.worker.wait(2500)
        except Exception:
            pass
        event.accept()

# =========================================================
# AUTH WINDOW + SPLASH
# =========================================================
class ManHinhKhoiDong(QtWidgets.QWidget):
    finished = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint)
        self.setFixedSize(760, 420)
        self.setStyleSheet("""
            QWidget {
                background:qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #0f172a, stop:0.45 #1d4ed8, stop:1 #06b6d4);
                border-radius:24px; color:white;
            }
            QLabel#Title { font-size:28px; font-weight:800; }
            QLabel#Sub { font-size:12px; color:rgba(255,255,255,0.88); }
            QProgressBar {
                border:1px solid rgba(255,255,255,0.18); border-radius:8px; background:rgba(255,255,255,0.12);
                text-align:center; color:white; min-height:16px;
            }
            QProgressBar::chunk { border-radius:8px; background:#bfdbfe; }
        """)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(42, 42, 42, 42)
        lay.addStretch()
        t = QtWidgets.QLabel("Hệ thống biển báo tốc độ linh hoạt")
        t.setObjectName("Title")
        s = QtWidgets.QLabel("Đang tải giao diện điều hành • tài khoản • phân tích • báo cáo")
        s.setObjectName("Sub")
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        lay.addWidget(t)
        lay.addWidget(s)
        lay.addSpacing(18)
        lay.addWidget(self.progress)
        lay.addStretch()

        self._value = 0
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.dem_nguoc)
        self.timer.start(18)

    def dem_nguoc(self):
        self._value += 2
        self.progress.setValue(self._value)
        if self._value >= 100:
            self.timer.stop()
            self.finished.emit()
            self.close()


class CuaSoDangNhap(QtWidgets.QStackedWidget):
    loginSuccess = QtCore.pyqtSignal(dict)

    def __init__(self, auth_manager: QuanLyTaiKhoan):
        super().__init__()
        self.auth_manager = auth_manager
        self.setWindowTitle("Đăng nhập • Hệ thống biển báo tốc độ linh hoạt")
        self.resize(980, 620)
        self.setMinimumSize(880, 580)
        self.setStyleSheet('\n            QStackedWidget { background:#eef4fb; }\n            QFrame#AuthCard { background:rgba(255,255,255,0.97); border:1px solid #d9e6f3; border-radius:24px; }\n            QLabel#AuthTitle { font-size:26px; font-weight:800; color:#0f172a; }\n            QLabel#AuthSub { font-size:12px; color:#64748b; }\n            QPushButton { background:#2563eb; color:white; border:none; border-radius:12px; padding:10px 16px; font-weight:700; min-height:20px; }\n            QPushButton:hover { background:#1d4ed8; }\n            QPushButton#SecondaryBtn { background:#ffffff; color:#0f172a; border:1px solid #cbd5e1; }\n            QLineEdit, QComboBox { background:white; border:1px solid #d1dbe8; border-radius:12px; padding:10px 12px; min-height:20px; }\n            QLabel#Hint { color:#475569; font-size:11px; }\n        ')
        self.addWidget(self.tao_trang_dang_nhap())
        self.addWidget(self.tao_trang_dang_ky())
        self.setCurrentIndex(0)

    def tao_khung_ben(self):
        side = QtWidgets.QFrame()
        side.setStyleSheet("""
            QFrame {
                background:qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #0f172a, stop:0.45 #1d4ed8, stop:1 #06b6d4);
                border-radius:24px;
            }
            QLabel { color:white; }
            QLabel#Big { font-size:28px; font-weight:800; }
            QLabel#Small { font-size:12px; color:rgba(255,255,255,0.88); }
        """)
        lay = QtWidgets.QVBoxLayout(side)
        lay.setContentsMargins(28, 28, 28, 28)
        big = QtWidgets.QLabel("Giao diện điều hành VSL")
        big.setObjectName("Big")
        small = QtWidgets.QLabel(
            "Hệ thống hỗ trợ giám sát giao thông từ video camera.\n\n"
            "• Theo dõi mật độ phương tiện\n"
            "• Gợi ý VSL theo ngữ cảnh\n"
            "• Cảnh báo sự kiện và xuất báo cáo\n\n"
            "Không hiển thị sẵn tài khoản/mật khẩu trên giao diện."
        )
        small.setObjectName("Small")
        small.setWordWrap(True)
        lay.addWidget(big)
        lay.addWidget(small)
        lay.addStretch()
        return side

    def tao_trang_dang_nhap(self):
        page = QtWidgets.QWidget()
        root = QtWidgets.QHBoxLayout(page)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(18)

        root.addWidget(self.tao_khung_ben(), 4)

        card = QtWidgets.QFrame()
        card.setObjectName('AuthCard')
        c = QtWidgets.QVBoxLayout(card)
        c.setContentsMargins(28, 28, 28, 28)
        c.setSpacing(12)

        title = QtWidgets.QLabel("Đăng nhập hệ thống")
        title.setObjectName("AuthTitle")
        sub = QtWidgets.QLabel("Đăng nhập để sử dụng hệ thống giám sát.")
        sub.setObjectName("AuthSub")
        self.login_user = QtWidgets.QLineEdit()
        self.login_user.setPlaceholderText("Tên đăng nhập")
        self.login_pass = QtWidgets.QLineEdit()
        self.login_pass.setPlaceholderText("Mật khẩu")
        self.login_pass.setEchoMode(QtWidgets.QLineEdit.Password)
        self.login_msg = QtWidgets.QLabel("")
        self.login_msg.setObjectName("Hint")

        btn_login = QtWidgets.QPushButton("Đăng nhập")
        btn_to_register = QtWidgets.QPushButton("Tạo tài khoản")
        btn_to_register.setObjectName("SecondaryBtn")
        btn_login.clicked.connect(self.xu_ly_dang_nhap)
        btn_to_register.clicked.connect(lambda: self.setCurrentIndex(1))

        c.addWidget(title)
        c.addWidget(sub)
        c.addSpacing(8)
        c.addWidget(self.login_user)
        c.addWidget(self.login_pass)
        c.addWidget(self.login_msg)
        c.addWidget(btn_login)
        c.addWidget(btn_to_register)
        c.addStretch()

        root.addWidget(card, 5)
        return page

    def tao_trang_dang_ky(self):
        page = QtWidgets.QWidget()
        root = QtWidgets.QHBoxLayout(page)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(18)

        root.addWidget(self.tao_khung_ben(), 4)

        card = QtWidgets.QFrame()
        card.setObjectName('AuthCard')
        c = QtWidgets.QVBoxLayout(card)
        c.setContentsMargins(28, 28, 28, 28)
        c.setSpacing(12)

        title = QtWidgets.QLabel("Tạo tài khoản")
        title.setObjectName("AuthTitle")
        sub = QtWidgets.QLabel("Tài khoản operator sẽ dùng để đăng nhập và chạy hệ thống.")
        sub.setObjectName("AuthSub")

        self.reg_fullname = QtWidgets.QLineEdit()
        self.reg_fullname.setPlaceholderText("Họ và tên")
        self.reg_username = QtWidgets.QLineEdit()
        self.reg_username.setPlaceholderText("Tên đăng nhập")
        self.reg_password = QtWidgets.QLineEdit()
        self.reg_password.setPlaceholderText("Mật khẩu")
        self.reg_password.setEchoMode(QtWidgets.QLineEdit.Password)
        self.reg_role = QtWidgets.QComboBox()
        self.reg_role.addItems(["vận hành viên", "quản trị viên"])
        self.reg_msg = QtWidgets.QLabel("")
        self.reg_msg.setObjectName("Hint")

        btn_register = QtWidgets.QPushButton("Đăng ký")
        btn_back = QtWidgets.QPushButton("Quay lại đăng nhập")
        btn_back.setObjectName("SecondaryBtn")
        btn_register.clicked.connect(self.xu_ly_dang_ky)
        btn_back.clicked.connect(lambda: self.setCurrentIndex(0))

        c.addWidget(title)
        c.addWidget(sub)
        c.addSpacing(8)
        c.addWidget(self.reg_fullname)
        c.addWidget(self.reg_username)
        c.addWidget(self.reg_password)
        c.addWidget(self.reg_role)
        c.addWidget(self.reg_msg)
        c.addWidget(btn_register)
        c.addWidget(btn_back)
        c.addStretch()

        root.addWidget(card, 5)
        return page

    def xu_ly_dang_nhap(self):
        ok, msg, user = self.auth_manager.dang_nhap(self.login_user.text(), self.login_pass.text())
        self.login_msg.setText(msg)
        self.login_msg.setStyleSheet("color:#16a34a;" if ok else "color:#dc2626;")
        if ok and user:
            self.loginSuccess.emit(user)

    def xu_ly_dang_ky(self):
        ok, msg = self.auth_manager.tao_tai_khoan(
            self.reg_fullname.text(),
            self.reg_username.text(),
            self.reg_password.text(),
            self.reg_role.currentText(),
        )
        self.reg_msg.setText(msg)
        self.reg_msg.setStyleSheet("color:#16a34a;" if ok else "color:#dc2626;")
        if ok:
            self.setCurrentIndex(0)


# =========================================================
# BOOT
# =========================================================

# =========================================================
# HOTFIX: bind missing VSLApp methods runly
# =========================================================
def _vslapp_finalize_worker_ui(self):
    try:
        self.dong_bo_trang_thai_chay(False)
    except Exception:
        pass
    try:
        self.btn_pause.setText("Tạm dừng")
    except Exception:
        pass
    self.worker = None
    try:
        self.badge_live.setText("TRỰC TUYẾN: TẮT")
        self.badge_live.setObjectName("BadgeRed")
        self.badge_live.style().unpolish(self.badge_live)
        self.badge_live.style().polish(self.badge_live)
    except Exception:
        pass
    try:
        if getattr(self, "video_path", None):
            self.hero_badge_status.setText("TRẠNG THÁI: ĐÃ CHỌN VIDEO")
            self.lbl_status.setText("Sẵn sàng chạy.")
        else:
            self.hero_badge_status.setText("TRẠNG THÁI: SẴN SÀNG")
            self.lbl_status.setText("Sẵn sàng.")
    except Exception:
        pass


def _vslapp_stop_worker_blocking(self, timeout_ms=4000, force_terminate=True):
    if getattr(self, "worker", None) is None:
        _vslapp_finalize_worker_ui(self)
        return True

    try:
        self.worker.yeu_cau_dung()
        self.worker.dat_tam_dung(False)

        if self.worker.isRunning():
            deadline = time.time() + (timeout_ms / 1000.0)
            while self.worker.isRunning() and time.time() < deadline:
                QtWidgets.QApplication.processEvents()
                self.worker.wait(50)

        if self.worker is not None and self.worker.isRunning() and force_terminate:
            try:
                self.append_log('[CẢNH BÁO] Worker stop timeout. Force terminating worker...')
            except Exception:
                pass
            try:
                self.worker.terminate()
                self.worker.wait(1000)
            except Exception:
                pass

        stopped = (self.worker is None) or (not self.worker.isRunning())
        if stopped:
            _vslapp_finalize_worker_ui(self)
            return True
    except Exception as e:
        try:
            self.append_log(f"[ERROR] stop_worker_blocking failed: {e}")
        except Exception:
            pass

    return False


def _vslapp_on_open_video(self):
    if getattr(self, "worker", None) is not None:
        reply = QtWidgets.QMessageBox.question(
            self,
            "Đổi video",
            "Nếu phiên hiện tại còn đang chạy hoặc đang dừng, hệ thống sẽ dừng hẳn rồi mới mở video mới. Bạn có muốn tiếp tục không?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return

        ok = self.dung_luong_xu_ly_an_toan(timeout_ms=4000, force_terminate=True)
        if not ok:
            QtWidgets.QMessageBox.warning(
                self,
                "Chưa thể đổi video",
                "Worker chưa dừng hoàn toàn. Hãy thử lại sau vài giây."
            )
            return

    fn, _ = QtWidgets.QFileDialog.getOpenFileName(
        self,
        "Chọn video",
        "",
        "Video files (*.mp4 *.avi *.mkv *.mov);;All files (*)"
    )
    if not fn:
        return

    self.video_path = fn
    self.lbl_video_name.setText(f"Video: {Path(fn).name}")

    cap = cv2.VideoCapture(fn)
    if cap.isOpened():
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.lbl_video_res.setText(f"Resolution: {w} x {h}")
    cap.release()

    try:
        self.video_label.clear()
        self.video_label.setText("Video giám sát sẽ hiển thị tại đây")
    except Exception:
        pass

    self.dong_bo_trang_thai_chay(False)
    try:
        self.hero_badge_status.setText("TRẠNG THÁI: ĐÃ CHỌN VIDEO")
    except Exception:
        pass
    try:
        self.append_log(f"[SYSTEM] Video selected: {Path(fn).name}")
    except Exception:
        pass


# bind hotfix methods onto class, overriding any malformed definitions
GiaoDienChinh._finalize_worker_ui = _vslapp_finalize_worker_ui
GiaoDienChinh.dung_luong_xu_ly_an_toan = _vslapp_stop_worker_blocking
GiaoDienChinh.on_open_video = _vslapp_on_open_video



# =========================================================
# HOTFIX 2: Rebind malformed VSLApp methods completely
# =========================================================
def _vslapp_is_running(self):
    return self.worker is not None and self.worker.isRunning()

def _vslapp_finalize_worker_ui(self):
    try:
        self.dong_bo_trang_thai_chay(False)
    except Exception:
        pass
    try:
        self.btn_pause.setText("Tạm dừng")
    except Exception:
        pass
    self.worker = None
    try:
        self.badge_live.setText("TRỰC TUYẾN: TẮT")
        self.badge_live.setObjectName("BadgeRed")
        self.badge_live.style().unpolish(self.badge_live)
        self.badge_live.style().polish(self.badge_live)
    except Exception:
        pass
    try:
        if getattr(self, "video_path", None):
            self.hero_badge_status.setText("TRẠNG THÁI: ĐÃ CHỌN VIDEO")
            self.lbl_status.setText("Sẵn sàng chạy.")
        else:
            self.hero_badge_status.setText("TRẠNG THÁI: SẴN SÀNG")
            self.lbl_status.setText("Sẵn sàng.")
    except Exception:
        pass

def _vslapp_stop_worker_blocking(self, timeout_ms=4000, force_terminate=True):
    if getattr(self, "worker", None) is None:
        _vslapp_finalize_worker_ui(self)
        return True

    try:
        self.worker.yeu_cau_dung()
        self.worker.dat_tam_dung(False)

        if self.worker.isRunning():
            deadline = time.time() + (timeout_ms / 1000.0)
            while self.worker.isRunning() and time.time() < deadline:
                QtWidgets.QApplication.processEvents()
                self.worker.wait(50)

        if self.worker is not None and self.worker.isRunning() and force_terminate:
            try:
                self.append_log('[CẢNH BÁO] Worker stop timeout. Force terminating worker...')
            except Exception:
                pass
            try:
                self.worker.terminate()
                self.worker.wait(1000)
            except Exception:
                pass

        stopped = (self.worker is None) or (not self.worker.isRunning())
        if stopped:
            _vslapp_finalize_worker_ui(self)
            return True
    except Exception as e:
        try:
            self.append_log(f"[ERROR] stop_worker_blocking failed: {e}")
        except Exception:
            pass

    return False

def _vslapp_on_open_video(self):
    if getattr(self, "worker", None) is not None:
        reply = QtWidgets.QMessageBox.question(
            self,
            "Đổi video",
            "Nếu phiên hiện tại còn đang chạy hoặc đang dừng, hệ thống sẽ dừng hẳn rồi mới mở video mới. Bạn có muốn tiếp tục không?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return

        ok = self.dung_luong_xu_ly_an_toan(timeout_ms=4000, force_terminate=True)
        if not ok:
            QtWidgets.QMessageBox.warning(
                self,
                "Chưa thể đổi video",
                "Worker chưa dừng hoàn toàn. Hãy thử lại sau vài giây."
            )
            return

    fn, _ = QtWidgets.QFileDialog.getOpenFileName(
        self,
        "Chọn video",
        "",
        "Video files (*.mp4 *.avi *.mkv *.mov);;All files (*)"
    )
    if not fn:
        return

    self.video_path = fn
    self.lbl_video_name.setText(f"Video: {Path(fn).name}")

    cap = cv2.VideoCapture(fn)
    if cap.isOpened():
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.lbl_video_res.setText(f"Resolution: {w} x {h}")
    cap.release()

    try:
        self.video_label.clear()
        self.video_label.setText("Video giám sát sẽ hiển thị tại đây")
    except Exception:
        pass

    self.dong_bo_trang_thai_chay(False)
    try:
        self.hero_badge_status.setText("TRẠNG THÁI: ĐÃ CHỌN VIDEO")
    except Exception:
        pass
    try:
        self.append_log(f"[SYSTEM] Video selected: {Path(fn).name}")
    except Exception:
        pass

def _vslapp_on_start(self):
    if self.dang_chay():
        return

    if self.worker is not None and not self.dang_chay():
        self.dung_luong_xu_ly_an_toan(timeout_ms=500, force_terminate=False)

    if not getattr(self, "video_path", None) or not os.path.isfile(self.video_path):
        QtWidgets.QMessageBox.warning(self, "Lỗi", "Chưa chọn video hoặc đường dẫn không hợp lệ.")
        return

    self.log_view.clear()
    camera_id = self.camera_hien_tai.camera_id if self.camera_hien_tai else "VIDEO_THU_CONG"

    self.worker = XuLyVideo(
    self.video_path,
    self.config,
    self.session_user,
    camera_id=camera_id,
)
    self.worker.frameReady.connect(self.show_frame)
    self.worker.statsReady.connect(self.update_ui_from_stats)
    self.worker.statusReady.connect(self.on_worker_status)
    self.worker.logReady.connect(self.append_log)
    self.worker.errorReady.connect(self.on_worker_error)
    self.worker.finishedCleanly.connect(self.on_worker_finished)
    self.worker.start()

    self.btn_pause.setText("Tạm dừng")
    self.dong_bo_trang_thai_chay(True)

def _vslapp_on_pause_resume(self):
    if self.worker is None:
        return
    if self.btn_pause.text() == "Tạm dừng":
        self.worker.dat_tam_dung(True)
        self.btn_pause.setText("Tiếp tục")
        self.hero_badge_status.setText("TRẠNG THÁI: TẠM DỪNG")
        self.lbl_status.setText("Đã tạm dừng.")
        self.badge_live.setText("TRỰC TUYẾN: TẠM DỪNG")
        self.badge_live.setObjectName("BadgeAmber")
    else:
        self.worker.dat_tam_dung(False)
        self.btn_pause.setText("Tạm dừng")
        self.hero_badge_status.setText("TRẠNG THÁI: ĐANG CHẠY")
        self.lbl_status.setText("Đang chạy...")
        self.badge_live.setText("TRỰC TUYẾN: BẬT")
        self.badge_live.setObjectName("BadgeGreen")
    self.badge_live.style().unpolish(self.badge_live)
    self.badge_live.style().polish(self.badge_live)

def _vslapp_on_stop(self):
    if self.worker is not None:
        try:
            self.worker.yeu_cau_dung()
            self.worker.dat_tam_dung(False)
        except Exception:
            pass
        self.lbl_status.setText("Đang dừng...")
        self.hero_badge_status.setText("TRẠNG THÁI: ĐANG DỪNG")
        self.badge_live.setText("TRỰC TUYẾN: ĐANG DỪNG")
        self.badge_live.setObjectName("BadgeAmber")
        self.badge_live.style().unpolish(self.badge_live)
        self.badge_live.style().polish(self.badge_live)
        QtCore.QTimer.singleShot(4500, lambda: self.dung_luong_xu_ly_an_toan(timeout_ms=100, force_terminate=True) if self.worker is not None else None)

def _vslapp_open_latest_report(self):
    text = self.lbl_report.text().replace("Báo cáo mới nhất: ", "").strip()
    if text and os.path.exists(text):
        mo_duong_dan_an_toan(text)
    else:
        mo_duong_dan_an_toan(str(OUTPUT_DIR))

def _vslapp_on_export_report(self):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "config": asdict(self.config),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "video_path": self.video_path,
        "session_user": self.session_user,
    }
    path = OUTPUT_DIR / "manual_export_snapshot.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    self.lbl_report.setText(f"Latest report: {path}")
    self.append_log(f"[REPORT] Exported manual snapshot: {path}")
    QtWidgets.QMessageBox.information(self, "Xuất báo cáo", f"Đã lưu snapshot config tại:\n{path}")

def _vslapp_on_worker_status(self, text):
    self.lbl_status.setText(text)

def _vslapp_on_worker_error(self, err):
    self.dong_bo_trang_thai_chay(False)
    self.append_log("[LỖI] Bộ xử lý video gặp sự cố")
    self.hero_badge_status.setText("TRẠNG THÁI: LỖI")
    QtWidgets.QMessageBox.critical(self, "Lỗi khi chạy", err)

def _vslapp_on_worker_finished(self, summary):
    html_path = summary.get("summary_html_path", "")
    if html_path and os.path.exists(html_path):
        self.lbl_report.setText(f"Latest report: {html_path}")
    self.append_log("[HỆ THỐNG] Phiên phân tích đã kết thúc")
    self._finalize_worker_ui()
    self.hero_badge_status.setText("TRẠNG THÁI: HOÀN THÀNH" if html_path or self.video_path else "TRẠNG THÁI: SẴN SÀNG")

def _vslapp_append_log(self, text):
    current = self.log_view.toPlainText().splitlines()
    current.append(text)
    current = current[-self.log_lines_max:]
    self.log_view.setPlainText("\n".join(current))
    self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())

def _vslapp_update_ui_from_stats(self, stats):
    vehicles_in_roi = stats.get("vehicles_in_roi", 0)
    avg_vehicles = stats.get("avg_vehicles", 0)
    density = stats.get("density", "THẤP")
    traffic_state = stats.get("traffic_state", "Lưu thông tốt")
    vsl = stats.get("suggested_vsl", 100)
    if hasattr(self, "hero_badge_vsl"):
       self.hero_badge_vsl.setText(
        f"BIỂN BÁO: {vsl} km/h"
        f"BIỂN BÁO: {vsl} km/h"
    )
    priority = stats.get("priority", "Bình thường")
    reason = stats.get("reason", "hệ thống đã khởi tạo")
    classes = stats.get("class_counts", {k: 0 for k in VEHICLE_CLASSES})
    fps_est = stats.get("fps_est", 0.0)
    sudden = stats.get("sudden_increase", False)
    warnings = stats.get("warning_count", 0)
    snapshots = stats.get("snapshot_count", 0)
    events = stats.get("event_count", 0)

    self.card_roi.dat_gia_tri(str(vehicles_in_roi))
    self.card_roi.dat_mo_ta(f"Trung bình trong cửa sổ: {avg_vehicles}")
    self.card_vsl.dat_gia_tri(f"{vsl} km/h")
    self.card_vsl.dat_mo_ta(reason)
    self.card_state.dat_gia_tri(traffic_state)
    self.card_state.dat_mo_ta(f"Mật độ: {density}")
    self.card_priority.dat_gia_tri(priority)
    self.card_priority.dat_mo_ta(f"Thời tiết: {self.config.vsl.weather}")

    if priority == "Bình thường":
        self.lbl_action.setText("Khuyến nghị điều hành: Tiếp tục giám sát")
    elif priority == "Theo dõi":
        self.lbl_action.setText("Khuyến nghị điều hành: Theo dõi sát tình hình giao thông")
    elif priority == "Cần can thiệp":
        self.lbl_action.setText("Khuyến nghị điều hành: Cân nhắc can thiệp VSL")
    else:
        self.lbl_action.setText("Khuyến nghị điều hành: Cần người vận hành xử lý ngay")

    self.lbl_avg.setText(f"Số xe trung bình: {avg_vehicles}")
    self.lbl_density.setText(f"Mật độ: {density}")
    self.lbl_state.setText(f"Trạng thái giao thông: {traffic_state}")
    self.lbl_vsl.setText(f"Tốc độ đề xuất: {vsl} km/h")
    self.lbl_mode.setText(f"Chế độ: {self.config.vsl.control_mode}")
    self.lbl_weather.setText(f"Thời tiết: {self.config.vsl.weather} ({mo_ta_thoi_tiet_chi_tiet(self.config.vsl.weather)}) | Sự cố: {self.config.vsl.incident}")
    self.lbl_priority.setText(f"Mức ưu tiên: {priority}")
    self.lbl_alert.setText(f"Cảnh báo tăng đột biến: {'Có' if sudden else 'Không'}")
    self.lbl_fps.setText(f"Tốc độ xử lý: {fps_est:.1f}")
    self.lbl_classes.setText(
        f"Ô tô: {classes.get('car',0)} | Xe máy: {classes.get('motorcycle',0)} | Bus: {classes.get('bus',0)} | Xe tải: {classes.get('truck',0)} | Xe đạp: {classes.get('bicycle',0)}"
    )
    self.lbl_counts.setText(f"Cảnh báo: {warnings} | Ảnh chụp: {snapshots} | Sự kiện: {events}")
    self.lbl_reason.setText(f"Lý do: {reason}")

    html_path = stats.get("summary_html_path")
    if html_path:
        self.lbl_report.setText(f"Latest report: {html_path}")

def _vslapp_show_frame(self, qimg):
    pix = QtGui.QPixmap.fromImage(qimg)
    scaled = pix.scaled(self.video_label.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
    self.video_label.setPixmap(scaled)

def _vslapp_closeEvent(self, event):
    try:
        if self.worker is not None and self.worker.isRunning():
            self.worker.yeu_cau_dung()
            self.worker.wait(2500)
    except Exception:
        pass
    event.accept()

GiaoDienChinh.dang_chay = _vslapp_is_running
GiaoDienChinh._finalize_worker_ui = _vslapp_finalize_worker_ui
GiaoDienChinh.dung_luong_xu_ly_an_toan = _vslapp_stop_worker_blocking
GiaoDienChinh.on_open_video = _vslapp_on_open_video
GiaoDienChinh.on_start = _vslapp_on_start
GiaoDienChinh.on_pause_resume = _vslapp_on_pause_resume
GiaoDienChinh.on_stop = _vslapp_on_stop
GiaoDienChinh.open_latest_report = _vslapp_open_latest_report
GiaoDienChinh.on_export_report = _vslapp_on_export_report
GiaoDienChinh.on_worker_status = _vslapp_on_worker_status
GiaoDienChinh.on_worker_error = _vslapp_on_worker_error
GiaoDienChinh.on_worker_finished = _vslapp_on_worker_finished
GiaoDienChinh.append_log = _vslapp_append_log
GiaoDienChinh.update_ui_from_stats = _vslapp_update_ui_from_stats
GiaoDienChinh.show_frame = _vslapp_show_frame
GiaoDienChinh.closeEvent = _vslapp_closeEvent



# =========================================================
# LANE ASSIST V3 HOTFIX
# Fix lane geometry so lanes follow the road direction instead of horizontal slices.
# =========================================================
def _v3_line_x_at_y(x1, y1, x2, y2, yq):
    if y2 == y1:
        return None
    t = (yq - y1) / float(y2 - y1)
    return x1 + t * (x2 - x1)


def build_lane_polygons_from_roi_v3(poly: np.ndarray, lane_count: int = 3, include_shoulder: bool = True):
    lane_count = max(1, int(lane_count))
    total_segments = lane_count + (2 if include_shoulder else 0)
    if total_segments <= 0:
        return []

    top_left, top_right, bot_right, bot_left = [np.array(p, dtype=np.float32) for p in poly]

    top_bounds = [top_left + (top_right - top_left) * (i / total_segments) for i in range(total_segments + 1)]
    bottom_bounds = [bot_left + (bot_right - bot_left) * (i / total_segments) for i in range(total_segments + 1)]

    items = []
    for i in range(total_segments):
        quad = np.array([
            top_bounds[i],
            top_bounds[i + 1],
            bottom_bounds[i + 1],
            bottom_bounds[i],
        ], dtype=np.int32)
        if include_shoulder and i == 0:
            label = 'Làn khẩn cấp trái'
        elif include_shoulder and i == total_segments - 1:
            label = 'Làn khẩn cấp phải'
        else:
            label = f"Lane {i if not include_shoulder else i}"
        items.append((label, quad))
    return items


def build_lane_polygons_smart_v3(frame: np.ndarray, poly: np.ndarray, lane_count: int = 3, include_shoulder: bool = True):
    lane_count = max(1, int(lane_count))
    total_segments = lane_count + (2 if include_shoulder else 0)
    if total_segments <= 0:
        return []

    top_left, top_right, bot_right, bot_left = [np.array(p, dtype=np.float32) for p in poly]
    y_top = int(min(top_left[1], top_right[1]))
    y_bottom = int(max(bot_left[1], bot_right[1]))

    top_bounds = [float((top_left + (top_right - top_left) * (i / total_segments))[0]) for i in range(total_segments + 1)]
    bottom_bounds = [float((bot_left + (bot_right - bot_left) * (i / total_segments))[0]) for i in range(total_segments + 1)]

    mask = np.zeros(frame.shape[:2], dtype=np.uint8)
    cv2.fillPoly(mask, [poly.astype(np.int32)], 255)

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)

    roi_gray = cv2.bitwise_and(gray, gray, mask=mask)
    edges = cv2.Canny(roi_gray, 60, 150)

    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=40,
        minLineLength=max(35, int((y_bottom - y_top) * 0.22)),
        maxLineGap=35,
    )

    candidates = []
    if lines is not None:
        for line in lines[:, 0]:
            x1, y1, x2, y2 = map(int, line.tolist())
            dx = x2 - x1
            dy = y2 - y1
            length = (dx * dx + dy * dy) ** 0.5
            if length < 30:
                continue
            if abs(dy) < max(25, abs(dx) * 1.2):
                continue

            xt = _v3_line_x_at_y(x1, y1, x2, y2, y_top)
            xb = _v3_line_x_at_y(x1, y1, x2, y2, y_bottom)
            if xt is None or xb is None:
                continue

            road_left_bottom = min(bot_left[0], bot_right[0]) - 20
            road_right_bottom = max(bot_left[0], bot_right[0]) + 20
            if xb < road_left_bottom or xb > road_right_bottom:
                continue

            candidates.append((float(xt), float(xb), float(length)))

    # refine only internal boundaries, keep outer edges from ROI
    road_width_bottom = max(1.0, float(abs(bot_right[0] - bot_left[0])))
    tolerance = max(22.0, road_width_bottom / (total_segments * 2.8))

    for i in range(1, total_segments):
        pred_bottom = bottom_bounds[i]
        local = [c for c in candidates if abs(c[1] - pred_bottom) <= tolerance]
        if not local:
            continue
        weights = np.array([c[2] for c in local], dtype=np.float32)
        top_vals = np.array([c[0] for c in local], dtype=np.float32)
        bot_vals = np.array([c[1] for c in local], dtype=np.float32)
        top_bounds[i] = float(np.average(top_vals, weights=weights))
        bottom_bounds[i] = float(np.average(bot_vals, weights=weights))

    items = []
    for i in range(total_segments):
        quad = np.array([
            [top_bounds[i], y_top],
            [top_bounds[i + 1], y_top],
            [bottom_bounds[i + 1], y_bottom],
            [bottom_bounds[i], y_bottom],
        ], dtype=np.int32)
        quad[:, 0] = np.clip(quad[:, 0], 0, frame.shape[1] - 1)
        quad[:, 1] = np.clip(quad[:, 1], 0, frame.shape[0] - 1)

        if include_shoulder and i == 0:
            label = 'Làn khẩn cấp trái'
        elif include_shoulder and i == total_segments - 1:
            label = 'Làn khẩn cấp phải'
        else:
            label = f"Lane {i if not include_shoulder else i}"
        items.append((label, quad))

    return items


def _videoworker_process_frame_v3(self, frame):
    h, w = frame.shape[:2]
    rc = self.config.roi
    poly = tao_da_giac_roi(w, h, rc.top_center_x, rc.bottom_center_x, rc.bottom_width, rc.top_width, rc.height, rc.bottom_y)

    lane_items = []
    lane_engine = "ROI thủ công"
    if self.config.lane.roi_mode == "Làn bán tự động":
        lane_items = build_lane_polygons_smart_v3(
            frame, poly,
            lane_count=self.config.lane.lane_count,
            include_shoulder=self.config.lane.include_shoulder,
        )
        lane_engine = "smart-semi-auto"
    elif self.config.lane.roi_mode == "Tự động chia làn từ ROI":
        lane_items = build_lane_polygons_smart_v3(
            frame, poly,
            lane_count=self.config.lane.lane_count,
            include_shoulder=self.config.lane.include_shoulder,
        )
        if lane_items:
            lane_engine = "smart-auto"
        else:
            lane_items = build_lane_polygons_from_roi_v3(
                poly,
                lane_count=self.config.lane.lane_count,
                include_shoulder=self.config.lane.include_shoulder,
            )
            lane_engine = "roi-split-v3"

    total_in_roi = 0
    class_counts = {name: 0 for name in VEHICLE_CLASSES}
    lane_counts = {label: 0 for label, _ in lane_items}
    t_sec = self.frame_idx / self.fps_video if self.fps_video > 0 else 0.0

    should_infer = (self.frame_idx % max(1, self.config.detection.frame_stride)) == 0
    if should_infer:
        self.last_inference_boxes = []
        if self.model is not None:
            try:
                device = "cuda:0" if self.config.detection.use_gpu and CUDA_AVAILABLE else "cpu"
                res = self.model.predict(
                    frame,
                    imgsz=self.config.detection.imgsz,
                    conf=self.config.detection.conf_th,
                    device=device,
                    half=bool(self.config.detection.use_gpu and CUDA_AVAILABLE),
                    verbose=False,
                )[0]
                if res.boxes is not None and res.boxes.xyxy is not None:
                    xyxy = res.boxes.xyxy.cpu().numpy()
                    cls = res.boxes.cls.cpu().numpy()
                    confs = res.boxes.conf.cpu().numpy()
                    self.them_nhat_ky(f"[YOLO DEBUG] raw boxes = {len(xyxy)}")

                    for box, cls_id, confv in zip(xyxy, cls, confs):
                        raw_name = self.name_map.get(int(cls_id), str(cls_id))
                        name = chuan_hoa_ten_xe(raw_name)

                        self.them_nhat_ky(
                            f"[YOLO DEBUG] cls_id={int(cls_id)} raw={raw_name} name={name} conf={float(confv):.2f}"
        )

                        if name is None:
                            continue

                        x1, y1, x2, y2 = map(int, box)

                        cx = (x1 + x2) // 2
                        cy = int(y2 - 0.08 * (y2 - y1))

                        lane_label = None

                        if lane_items:
                            in_roi, lane_label = kiem_tra_diem_trong_lan_duong((cx, cy), lane_items)
                        else:
                            in_roi = kiem_tra_diem_trong_da_giac((cx, cy), poly)

                        total_in_roi += 1
                        class_counts[name] += 1

                        if lane_label is not None:
                            lane_counts[lane_label] = lane_counts.get(lane_label, 0) + 1

                        if self.heatmap_accumulator is not None:
                            cv2.circle(self.heatmap_accumulator, (cx, cy), 14, 1.0, -1)

                        color = (0, 255, 102) if in_roi else (0, 180, 255)

                        self.last_inference_boxes.append(
                           (x1, y1, x2, y2, name, float(confv), color, cx, cy, in_roi, lane_label)
         )
                    else:
                            self.them_nhat_ky("[YOLO DEBUG] res.boxes rỗng")

            except Exception as e:
                  self.them_nhat_ky(f"[WARN] Lỗi dự đoán YOLO: {e}")

    self.vehicle_history.append(total_in_roi)
    avg_vehicles = round(sum(self.vehicle_history) / max(1, len(self.vehicle_history))) if self.vehicle_history else 0
    density, vsl_speed, traffic_state, reason = tinh_vsl_theo_ngu_canh(avg_vehicles, class_counts, self.config.vsl)
    sudden_increase = (avg_vehicles - self.prev_avg_vehicles) >= self.sudden_increase_threshold
    self.prev_avg_vehicles = avg_vehicles
    priority = tinh_muc_do_uu_tien(density, traffic_state, self.config.vsl.weather, self.config.vsl.incident, sudden_increase, vsl_speed)

    if sudden_increase:
        self.warning_count += 1
        self.them_su_kien("ALERT", f"Mật độ tăng đột biến: trung bình={avg_vehicles}", t_sec)
        self.luu_anh_su_kien(frame, "sudden_density", t_sec)

    if self.last_state != traffic_state:
        self.them_su_kien("STATE", f"Trạng thái giao thông chuyển thành {traffic_state}", t_sec)
        self.luu_anh_su_kien(frame, f"state_{traffic_state.lower().replace(' ', '_')}", t_sec)
        self.last_state = traffic_state

    if self.last_vsl is None:
        self.last_vsl = vsl_speed
    elif abs(vsl_speed - self.last_vsl) >= 10:
        self.them_su_kien("VSL", f"VSL thay đổi từ {self.last_vsl} đến {vsl_speed}", t_sec)
        self.luu_anh_su_kien(frame, f"vsl_{vsl_speed}", t_sec)
        self.last_vsl = vsl_speed

    if self.last_priority != priority:
        self.them_su_kien("PRIORITY", f"Mức ưu tiên chuyển thành {priority}", t_sec)
        if priority in ("Cần can thiệp", "Khẩn cấp"):
            self.luu_anh_su_kien(frame, f"priority_{priority.lower().replace(' ', '_')}", t_sec)
        self.last_priority = priority

    if self.config.display.show_heatmap and self.heatmap_accumulator is not None and np.max(self.heatmap_accumulator) > 0:
        heat_norm = cv2.normalize(self.heatmap_accumulator, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        heat_color = cv2.applyColorMap(heat_norm, cv2.COLORMAP_JET)
        frame = cv2.addWeighted(frame, 0.75, heat_color, 0.25, 0)

    if self.config.display.show_roi:
        ve_vung_giam_sat(frame, poly)

    if lane_items and self.config.lane.draw_lanes:
        ve_lan_duong(frame, lane_items, alpha=0.12)

    if self.config.display.show_boxes:
        for x1, y1, x2, y2, name, confv, color, cx, cy, in_roi, lane_label in self.last_inference_boxes:
            thickness = 2 if in_roi else 1
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
            cv2.circle(frame, (cx, cy), 4 if in_roi else 2, (0, 255, 255) if in_roi else color, -1)
            label_text = f"{name} {confv:.2f}"
            if lane_label:
                label_text += f" | {lane_label}"
            cv2.putText(frame, label_text, (x1, max(24, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.58, color, 2, cv2.LINE_AA)

    lane_counts_text = " | ".join([f"{k}:{v}" for k, v in lane_counts.items()]) if lane_counts else "-"
    self.last_stats = {
        "vehicles_in_roi": total_in_roi,
        "avg_vehicles": avg_vehicles,
        "density": density,
        "traffic_state": traffic_state,
        "suggested_vsl": vsl_speed,
        "priority": priority,
        "sudden_increase": sudden_increase,
        "reason": f"mật độ={density.lower()} | chế độ={self.config.lane.roi_mode} | làn={lane_engine}",
        "class_counts": class_counts,
        "lane_counts_text": lane_counts_text,
        "fps_est": round(self.fps_est, 1),
        "warning_count": self.warning_count,
        "snapshot_count": self.snapshot_count,
        "event_count": self.event_count,
        "summary_html_path": str(self.summary_html_path),
    }
    self.statsReady.emit(self.last_stats)

    now_csv = time.time()
    if now_csv - getattr(self, "last_csv_write_time", 0.0) >= getattr(self, "csv_write_interval", 1.0):
        self.last_csv_write_time = now_csv
        try:
            with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    self.frame_idx, round(t_sec, 2), total_in_roi, avg_vehicles, density,
                    traffic_state, self.config.vsl.weather, self.config.vsl.incident,
                    self.config.vsl.control_mode, vsl_speed, priority, sudden_increase,
                    class_counts.get("car", 0), class_counts.get("motorcycle", 0),
                    class_counts.get("bus", 0), class_counts.get("truck", 0),
                    class_counts.get("bicycle", 0), reason
                ])
        except Exception as e:
            ghi_log(f"Lỗi ghi CSV: {e}")

    return frame


# override old implementations
tao_lan_duong_tu_roi = build_lane_polygons_from_roi_v3
build_lane_polygons_smart = build_lane_polygons_smart_v3
XuLyVideo.xu_ly_khung_hinh = _videoworker_process_frame_v3



# =========================================================
# LANE ASSIST V4 HOTFIX
# Goals:
# - make lane polygons stick to the road more stably
# - reduce visual clutter
# - smooth lane geometry across frames
# =========================================================
def _lane_short_label(label: str) -> str:
    if label == 'Làn khẩn cấp trái':
        return "Shoulder L"
    if label == 'Làn khẩn cấp phải':
        return "Shoulder R"
    if label.startswith('Làn '):
        return "L" + label.split()[-1]
    return label


def _enforce_monotonic_bounds(bounds, left_edge, right_edge, min_gap):
    vals = list(bounds)
    vals[0] = max(left_edge, min(vals[0], right_edge))
    vals[-1] = min(right_edge, max(vals[-1], left_edge))
    for i in range(1, len(vals)):
        vals[i] = max(vals[i], vals[i - 1] + min_gap)
    for i in range(len(vals) - 2, -1, -1):
        vals[i] = min(vals[i], vals[i + 1] - min_gap)
    vals[0] = max(left_edge, vals[0])
    vals[-1] = min(right_edge, vals[-1])
    return vals


def build_lane_polygons_smart_v4(frame: np.ndarray, poly: np.ndarray, lane_count: int = 3, include_shoulder: bool = True):
    lane_count = max(1, int(lane_count))
    total_segments = lane_count + (2 if include_shoulder else 0)
    if total_segments <= 0:
        return []

    top_left, top_right, bot_right, bot_left = [np.array(p, dtype=np.float32) for p in poly]
    y_top = int(min(top_left[1], top_right[1]))
    y_bottom = int(max(bot_left[1], bot_right[1]))

    # Start with perspective-correct interpolation between the top and bottom road edges.
    top_bounds = [float((top_left + (top_right - top_left) * (i / total_segments))[0]) for i in range(total_segments + 1)]
    bottom_bounds = [float((bot_left + (bot_right - bot_left) * (i / total_segments))[0]) for i in range(total_segments + 1)]

    mask = np.zeros(frame.shape[:2], dtype=np.uint8)
    cv2.fillPoly(mask, [poly.astype(np.int32)], 255)

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)

    roi_gray = cv2.bitwise_and(gray, gray, mask=mask)
    edges = cv2.Canny(roi_gray, 55, 145)

    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=38,
        minLineLength=max(32, int((y_bottom - y_top) * 0.24)),
        maxLineGap=28,
    )

    candidates = []
    if lines is not None:
        for line in lines[:, 0]:
            x1, y1, x2, y2 = map(int, line.tolist())
            dx = x2 - x1
            dy = y2 - y1
            length = (dx * dx + dy * dy) ** 0.5
            if length < 28:
                continue
            # Prefer lane-like lines: strong vertical component in perspective view.
            if abs(dy) < max(35, abs(dx) * 1.35):
                continue

            xt = _v3_line_x_at_y(x1, y1, x2, y2, y_top)
            xb = _v3_line_x_at_y(x1, y1, x2, y2, y_bottom)
            if xt is None or xb is None:
                continue

            left_b = float(min(bot_left[0], bot_right[0]))
            right_b = float(max(bot_left[0], bot_right[0]))
            left_t = float(min(top_left[0], top_right[0]))
            right_t = float(max(top_left[0], top_right[0]))

            if xb < left_b - 18 or xb > right_b + 18:
                continue
            if xt < left_t - 35 or xt > right_t + 35:
                continue

            candidates.append((float(xt), float(xb), float(length)))

    road_width_bottom = max(1.0, float(abs(bot_right[0] - bot_left[0])))
    tol = max(24.0, road_width_bottom / (total_segments * 2.6))

    # Refine only inner boundaries, keep road outer edges stable.
    for i in range(1, total_segments):
        pred_bottom = bottom_bounds[i]
        local = [c for c in candidates if abs(c[1] - pred_bottom) <= tol]
        if not local:
            continue
        weights = np.array([c[2] for c in local], dtype=np.float32)
        top_vals = np.array([c[0] for c in local], dtype=np.float32)
        bot_vals = np.array([c[1] for c in local], dtype=np.float32)
        top_bounds[i] = float(np.average(top_vals, weights=weights))
        bottom_bounds[i] = float(np.average(bot_vals, weights=weights))

    min_gap_top = max(8.0, abs(float(top_right[0] - top_left[0])) / (total_segments * 1.8))
    min_gap_bottom = max(14.0, road_width_bottom / (total_segments * 1.8))
    top_bounds = _enforce_monotonic_bounds(top_bounds, float(top_left[0]), float(top_right[0]), min_gap_top)
    bottom_bounds = _enforce_monotonic_bounds(bottom_bounds, float(bot_left[0]), float(bot_right[0]), min_gap_bottom)

    items = []
    for i in range(total_segments):
        quad = np.array([
            [top_bounds[i], y_top],
            [top_bounds[i + 1], y_top],
            [bottom_bounds[i + 1], y_bottom],
            [bottom_bounds[i], y_bottom],
        ], dtype=np.int32)
        quad[:, 0] = np.clip(quad[:, 0], 0, frame.shape[1] - 1)
        quad[:, 1] = np.clip(quad[:, 1], 0, frame.shape[0] - 1)

        if include_shoulder and i == 0:
            label = 'Làn khẩn cấp trái'
        elif include_shoulder and i == total_segments - 1:
            label = 'Làn khẩn cấp phải'
        else:
            label = f"Lane {i if not include_shoulder else i}"
        items.append((label, quad))
    return items


def smooth_lane_items(prev_items, new_items, alpha=0.78):
    if not prev_items or not new_items or len(prev_items) != len(new_items):
        return new_items
    out = []
    for (plabel, ppoly), (nlabel, npoly) in zip(prev_items, new_items):
        if plabel != nlabel or ppoly.shape != npoly.shape:
            return new_items
        smoothed = (alpha * ppoly.astype(np.float32) + (1.0 - alpha) * npoly.astype(np.float32)).astype(np.int32)
        out.append((nlabel, smoothed))
    return out


def draw_lane_polygons_clean(frame, lane_items, alpha=0.05):
    overlay = frame.copy()
    colors = [
        (0, 200, 255),
        (255, 170, 0),
        (120, 255, 120),
        (255, 120, 220),
        (120, 220, 255),
        (255, 220, 120),
    ]
    h, w = frame.shape[:2]
    for idx, (label, poly) in enumerate(lane_items):
        color = colors[idx % len(colors)]
        cv2.fillPoly(overlay, [poly], color)
        cv2.polylines(frame, [poly], True, color, 2)
        # Put a single label near the bottom of each lane to reduce clutter.
        bottom_mid = ((poly[2].astype(np.float32) + poly[3].astype(np.float32)) / 2.0).astype(int)
        tx = int(np.clip(bottom_mid[0] - 26, 5, w - 90))
        ty = int(np.clip(bottom_mid[1] - 12, 20, h - 10))
        cv2.putText(frame, _lane_short_label(label), (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.52, color, 2, cv2.LINE_AA)
    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)


def _videoworker_process_frame_v4(self, frame):
    h, w = frame.shape[:2]
    rc = self.config.roi
    poly = tao_da_giac_roi(w, h, rc.top_center_x, rc.bottom_center_x, rc.bottom_width, rc.top_width, rc.height, rc.bottom_y)

    lane_items = []
    lane_engine = "ROI thủ công"
    if self.config.lane.roi_mode == "Làn bán tự động":
        lane_items = build_lane_polygons_smart_v4(
            frame, poly,
            lane_count=self.config.lane.lane_count,
            include_shoulder=self.config.lane.include_shoulder,
        )
        lane_engine = "smart-semi-auto-v4"
    elif self.config.lane.roi_mode == "Tự động chia làn từ ROI":
        lane_items = build_lane_polygons_smart_v4(
            frame, poly,
            lane_count=self.config.lane.lane_count,
            include_shoulder=self.config.lane.include_shoulder,
        )
        if lane_items:
            lane_engine = "smart-auto-v4"
        else:
            lane_items = build_lane_polygons_from_roi_v3(
                poly,
                lane_count=self.config.lane.lane_count,
                include_shoulder=self.config.lane.include_shoulder,
            )
            lane_engine = "roi-split-v3"

    prev_cache = getattr(self, "_lane_items_cache", None)
    if lane_items:
        lane_items = smooth_lane_items(prev_cache, lane_items, alpha=0.80)
    self._lane_items_cache = lane_items

    total_in_roi = 0
    class_counts = {name: 0 for name in VEHICLE_CLASSES}
    lane_counts = {label: 0 for label, _ in lane_items}
    t_sec = self.frame_idx / self.fps_video if self.fps_video > 0 else 0.0

    should_infer = (self.frame_idx % max(1, self.config.detection.frame_stride)) == 0
    if should_infer:
        self.last_inference_boxes = []
        if self.model is not None:
            try:
                device = "cuda:0" if self.config.detection.use_gpu and CUDA_AVAILABLE else "cpu"
                res = self.model.predict(
                    frame,
                    imgsz=self.config.detection.imgsz,
                    conf=self.config.detection.conf_th,
                    device=device,
                    half=bool(self.config.detection.use_gpu and CUDA_AVAILABLE),
                    verbose=False,
                )[0]
                if res.boxes is not None and res.boxes.xyxy is not None:
                    xyxy = res.boxes.xyxy.cpu().numpy()
                    cls = res.boxes.cls.cpu().numpy()
                    confs = res.boxes.conf.cpu().numpy()
                    for box, cls_id, confv in zip(xyxy, cls, confs):
                        raw_name = self.name_map.get(int(cls_id), str(cls_id))
                        name = chuan_hoa_ten_xe(raw_name)
                        if name is None:
                            continue
                        x1, y1, x2, y2 = map(int, box)
                        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                        lane_label = None
                        if lane_items:
                            in_roi, lane_label = kiem_tra_diem_trong_lan_duong((cx, cy), lane_items)
                        else:
                            in_roi = kiem_tra_diem_trong_da_giac((cx, cy), poly)

                        if in_roi:
                            total_in_roi += 1
                            class_counts[name] += 1
                            if lane_label is not None:
                                lane_counts[lane_label] = lane_counts.get(lane_label, 0) + 1
                            if self.heatmap_accumulator is not None:
                                cv2.circle(self.heatmap_accumulator, (cx, cy), 14, 1.0, -1)
                            color = (0, 255, 102)
                        else:
                            color = (130, 130, 130)
                        self.last_inference_boxes.append((x1, y1, x2, y2, name, float(confv), color, cx, cy, in_roi, lane_label))
            except Exception as e:
                self.them_nhat_ky(f"[WARN] Lỗi dự đoán YOLO: {e}")

    self.vehicle_history.append(total_in_roi)
    avg_vehicles = round(sum(self.vehicle_history) / max(1, len(self.vehicle_history))) if self.vehicle_history else 0
    density, vsl_speed, traffic_state, reason = tinh_vsl_theo_ngu_canh(avg_vehicles, class_counts, self.config.vsl)
    sudden_increase = (avg_vehicles - self.prev_avg_vehicles) >= self.sudden_increase_threshold
    self.prev_avg_vehicles = avg_vehicles
    priority = tinh_muc_do_uu_tien(density, traffic_state, self.config.vsl.weather, self.config.vsl.incident, sudden_increase, vsl_speed)

    if sudden_increase:
        self.warning_count += 1
        self.them_su_kien("ALERT", f"Mật độ tăng đột biến: trung bình={avg_vehicles}", t_sec)
        self.luu_anh_su_kien(frame, "sudden_density", t_sec)

    if self.last_state != traffic_state:
        self.them_su_kien("STATE", f"Trạng thái giao thông chuyển thành {traffic_state}", t_sec)
        self.luu_anh_su_kien(frame, f"state_{traffic_state.lower().replace(' ', '_')}", t_sec)
        self.last_state = traffic_state

    if self.last_vsl is None:
        self.last_vsl = vsl_speed
    elif abs(vsl_speed - self.last_vsl) >= 10:
        self.them_su_kien("VSL", f"VSL thay đổi từ {self.last_vsl} đến {vsl_speed}", t_sec)
        self.luu_anh_su_kien(frame, f"vsl_{vsl_speed}", t_sec)
        self.last_vsl = vsl_speed

    if self.last_priority != priority:
        self.them_su_kien("PRIORITY", f"Mức ưu tiên chuyển thành {priority}", t_sec)
        if priority in ("Cần can thiệp", "Khẩn cấp"):
            self.luu_anh_su_kien(frame, f"priority_{priority.lower().replace(' ', '_')}", t_sec)
        self.last_priority = priority

    if self.config.display.show_heatmap and self.heatmap_accumulator is not None and np.max(self.heatmap_accumulator) > 0:
        heat_norm = cv2.normalize(self.heatmap_accumulator, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        heat_color = cv2.applyColorMap(heat_norm, cv2.COLORMAP_JET)
        frame = cv2.addWeighted(frame, 0.80, heat_color, 0.20, 0)

    if self.config.display.show_roi:
        ve_vung_giam_sat(frame, poly, alpha=0.06)

    if lane_items and self.config.lane.draw_lanes:
        draw_lane_polygons_clean(frame, lane_items, alpha=0.045)

    if self.config.display.show_boxes:
        for x1, y1, x2, y2, name, confv, color, cx, cy, in_roi, lane_label in self.last_inference_boxes:
            thickness = 2 if in_roi else 1
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
            cv2.circle(frame, (cx, cy), 4 if in_roi else 2, (0, 255, 255) if in_roi else color, -1)
            # Keep the box label cleaner; do not append full lane text on every vehicle.
            cv2.putText(frame, f"{name} {confv:.2f}", (x1, max(24, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)

    lane_counts_text = " | ".join([f"{_lane_short_label(k)}:{v}" for k, v in lane_counts.items()]) if lane_counts else "-"
    self.last_stats = {
        "vehicles_in_roi": total_in_roi,
        "avg_vehicles": avg_vehicles,
        "density": density,
        "traffic_state": traffic_state,
        "suggested_vsl": vsl_speed,
        "priority": priority,
        "sudden_increase": sudden_increase,
        "reason": f"mật độ={density.lower()} | chế độ={self.config.lane.roi_mode} | làn={lane_engine}",
        "class_counts": class_counts,
        "lane_counts_text": lane_counts_text,
        "fps_est": round(self.fps_est, 1),
        "warning_count": self.warning_count,
        "snapshot_count": self.snapshot_count,
        "event_count": self.event_count,
        "summary_html_path": str(self.summary_html_path),
    }
    self.statsReady.emit(self.last_stats)

    now_csv = time.time()
    if now_csv - getattr(self, "last_csv_write_time", 0.0) >= getattr(self, "csv_write_interval", 1.0):
        self.last_csv_write_time = now_csv
        try:
            with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    self.frame_idx, round(t_sec, 2), total_in_roi, avg_vehicles, density,
                    traffic_state, self.config.vsl.weather, self.config.vsl.incident,
                    self.config.vsl.control_mode, vsl_speed, priority, sudden_increase,
                    class_counts.get("car", 0), class_counts.get("motorcycle", 0),
                    class_counts.get("bus", 0), class_counts.get("truck", 0),
                    class_counts.get("bicycle", 0), reason
                ])
        except Exception as e:
            ghi_log(f"Lỗi ghi CSV: {e}")

    return frame


# override with cleaner, stickier version
build_lane_polygons_smart = build_lane_polygons_smart_v4
XuLyVideo.xu_ly_khung_hinh = _videoworker_process_frame_v4


# =========================================================
# V6 PROFESSIONAL ROAD PATCH
# =========================================================

def _v6_bottom_anchor_point(x1, y1, x2, y2, lift_px=4):
    ax = int((x1 + x2) * 0.5)
    ay = int(y2 - lift_px)
    return ax, ay


def _v6_mask_from_poly(shape_hw, poly):
    h, w = shape_hw[:2]
    mask = np.zeros((h, w), dtype=np.uint8)
    if poly is not None and len(poly) >= 3:
        cv2.fillPoly(mask, [poly.astype(np.int32)], 255)
    return mask


def _v6_smooth_poly(prev_poly, new_poly, alpha=0.84):
    if prev_poly is None:
        return new_poly.astype(np.int32)
    prev_poly = prev_poly.astype(np.float32)
    new_poly = new_poly.astype(np.float32)
    out = prev_poly * alpha + new_poly * (1.0 - alpha)
    return out.astype(np.int32)


def _v6_row_lr_from_mask(mask, y, pad=3):
    h, w = mask.shape[:2]
    y0 = max(0, y - pad)
    y1 = min(h, y + pad + 1)
    band = mask[y0:y1, :]
    xs = np.where(np.any(band > 0, axis=0))[0]
    if len(xs) < 10:
        return None
    return int(xs[0]), int(xs[-1])


def _v6_largest_contour(mask, min_area=8000):
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cnts = [c for c in cnts if cv2.contourArea(c) >= min_area]
    if not cnts:
        return None
    cnts.sort(key=cv2.contourArea, reverse=True)
    return cnts[0]


def _v6_auto_road_mask(frame):
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    gray = cv2.GaussianBlur(gray, (7, 7), 0)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    hch, sch, vch = cv2.split(hsv)

    lower_roi = np.zeros((h, w), dtype=np.uint8)
    lower_roi[int(h * 0.34):, :] = 255

    sat_low = cv2.inRange(sch, 0, 150)
    val_mid = cv2.inRange(vch, 35, 235)
    road_tone = cv2.bitwise_and(sat_low, val_mid)

    edges = cv2.Canny(gray, 45, 135)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)

    mix = cv2.bitwise_or(road_tone, edges)
    mix = cv2.bitwise_and(mix, lower_roi)

    kernel_close = cv2.getStructuringElement(cv2.MORPH_RECT, (19, 19))
    kernel_open = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    mix = cv2.morphologyEx(mix, cv2.MORPH_CLOSE, kernel_close, iterations=1)
    mix = cv2.morphologyEx(mix, cv2.MORPH_OPEN, kernel_open, iterations=1)

    cnt = _v6_largest_contour(mix, min_area=max(7000, int(h * w * 0.02)))
    if cnt is None:
        return None, None, 0.18

    filled = np.zeros((h, w), dtype=np.uint8)
    cv2.drawContours(filled, [cnt], -1, 255, thickness=cv2.FILLED)
    filled[:int(h * 0.32), :] = 0

    area_ratio = cv2.contourArea(cnt) / max(1.0, float(h * w))
    ys = np.where(np.any(filled > 0, axis=1))[0]
    row_score = min(1.0, len(ys) / max(1.0, h * 0.52))
    conf = np.clip(0.30 + area_ratio * 2.4 + row_score * 0.35, 0.0, 0.98)
    return filled, cnt, float(conf)


def _v6_auto_road_polygon_from_frame(frame, prev_poly=None):
    h, w = frame.shape[:2]
    mask, cnt, conf = _v6_auto_road_mask(frame)
    if mask is None:
        return prev_poly, None, float(conf), False

    ys = np.where(np.any(mask > 0, axis=1))[0]
    if len(ys) < 20:
        return prev_poly, mask, float(conf), False

    y_bottom = int(np.percentile(ys, 98))
    y_top = int(np.percentile(ys, 24))
    y_top = max(int(h * 0.40), y_top)
    y_bottom = min(h - 2, y_bottom)

    top_lr = _v6_row_lr_from_mask(mask, y_top, pad=4)
    bot_lr = _v6_row_lr_from_mask(mask, y_bottom, pad=5)
    if top_lr is None or bot_lr is None:
        return prev_poly, mask, float(conf), False

    lx_top, rx_top = top_lr
    lx_bot, rx_bot = bot_lr
    if (rx_bot - lx_bot) < int(w * 0.18):
        return prev_poly, mask, float(conf), False

    poly = np.array([
        [lx_top, y_top],
        [rx_top, y_top],
        [rx_bot, y_bottom],
        [lx_bot, y_bottom],
    ], dtype=np.int32)
    poly = _v6_smooth_poly(prev_poly, poly, alpha=0.84)
    return poly, mask, float(conf), True


def _v6_confidence_label(score: float) -> str:
    if score >= 0.78:
        return 'CAO'
    if score >= 0.52:
        return 'TRUNG BÌNH'
    return 'THẤP'


def _v6_draw_road_mask(frame, road_mask, alpha=0.14):
    if road_mask is None:
        return
    overlay = frame.copy()
    green = np.zeros_like(frame)
    green[:, :, 1] = road_mask
    cv2.addWeighted(green, alpha, overlay, 1.0, 0.0, overlay)
    frame[:] = overlay


def _v6_draw_lane_polygons(frame, lane_items, overlay_mode='Trình chiếu'):
    if not lane_items:
        return
    if overlay_mode == 'Trình chiếu':
        colors = [(0, 214, 255), (255, 208, 0), (92, 226, 126), (193, 132, 255), (120, 220, 255)]
        for idx, (label, poly) in enumerate(lane_items):
            color = colors[idx % len(colors)]
            cv2.polylines(frame, [poly], True, color, 2, cv2.LINE_AA)
    else:
        draw_lane_polygons_clean(frame, lane_items, alpha=0.055)


def _v6_draw_chip(frame, text, xy, bg, fg=(255, 255, 255)):
    x, y = xy
    font = cv2.FONT_HERSHEY_SIMPLEX
    thickness = 2
    (tw, th), _ = cv2.getTextSize(text, font, max(0.7, min(1.6, frame.shape[1] / 1280.0)), thickness)
    cv2.rectangle(frame, (x, y - th - 10), (x + tw + 16, y + 6), bg, -1)
    cv2.rectangle(frame, (x, y - th - 10), (x + tw + 16, y + 6), (255, 255, 255), 1)
    cv2.putText(frame, text, (x + 8, y - 4), font, max(0.7, min(1.6, frame.shape[1] / 1280.0)), fg, thickness, cv2.LINE_AA)


def _v6_badge_style_text(label_widget, level_text):
    text = str(level_text or '').upper()
    if 'CAO' in text or 'KHÓA' in text or 'LOCKED' in text or 'AUTO OK' in text:
        label_widget.setStyleSheet('background:#dcfce7; color:#166534; border:1px solid #86efac; border-radius:10px; padding:8px 12px; font-weight:800;')
    elif 'TRUNG BÌNH' in text or 'ĐANG' in text or 'HỖ TRỢ' in text or 'RECOVER' in text or 'ASSIST' in text:
        label_widget.setStyleSheet('background:#fef3c7; color:#92400e; border:1px solid #fcd34d; border-radius:10px; padding:8px 12px; font-weight:800;')
    else:
        label_widget.setStyleSheet('background:#fee2e2; color:#991b1b; border:1px solid #fca5a5; border-radius:10px; padding:8px 12px; font-weight:800;')


def _videoworker_process_frame_v6(self, frame):
    h, w = frame.shape[:2]
    if not hasattr(self, '_auto_poly_prev'):
        self._auto_poly_prev = None
    if not hasattr(self, '_auto_fail_count'):
        self._auto_fail_count = 0

    show_road_mask = bool(getattr(self.config.display, 'show_road_mask', True))
    overlay_mode = str(getattr(self.config.display, 'overlay_mode', 'Trình chiếu'))
    minimal_labels = bool(getattr(self.config.display, 'minimal_labels', True))

    rc = self.config.roi
    fallback_poly = tao_da_giac_roi(w, h, rc.top_center_x, rc.bottom_center_x, rc.bottom_width, rc.top_width, rc.height, rc.bottom_y)
    roi_mode = str(getattr(self.config.lane, 'roi_mode', 'Tự nhận dạng mặt đường'))

    lane_items = []
    road_mask = None
    poly = fallback_poly
    road_conf_score = 0.32
    geometry_status = 'ROI THỦ CÔNG'
    lane_engine = 'ROI thủ công'
    auto_success = False

    if roi_mode == 'Tự nhận dạng mặt đường':
        auto_poly, road_mask, road_conf_score, auto_success = _v6_auto_road_polygon_from_frame(frame, self._auto_poly_prev)
        if auto_success and auto_poly is not None:
            poly = auto_poly
            self._auto_poly_prev = auto_poly.copy()
            self._auto_fail_count = 0
            geometry_status = 'ĐÃ KHÓA LÀN'
            lane_engine = 'auto-road-v6'
        else:
            self._auto_fail_count += 1
            if self._auto_poly_prev is not None and self._auto_fail_count <= 18:
                poly = self._auto_poly_prev.copy()
                geometry_status = 'ĐANG KHÔI PHỤC'
                lane_engine = 'recover-last-geometry'
            else:
                poly = fallback_poly
                geometry_status = 'ROI DỰ PHÒNG'
                lane_engine = 'fallback-roi'
        lane_items = build_lane_polygons_smart_v4(
            frame,
            poly,
            lane_count=max(2, int(self.config.lane.lane_count)),
            include_shoulder=False,
        )
        if road_mask is None:
            road_mask = _v6_mask_from_poly(frame.shape, poly)
    elif roi_mode == 'Làn bán tự động':
        poly = fallback_poly
        road_mask = _v6_mask_from_poly(frame.shape, poly)
        road_conf_score = 0.55
        geometry_status = 'HỖ TRỢ ROI'
        lane_engine = 'sticky-lane-v4'
        lane_items = build_lane_polygons_smart_v4(
            frame,
            poly,
            lane_count=max(2, int(self.config.lane.lane_count)),
            include_shoulder=bool(self.config.lane.include_shoulder),
        )
    elif roi_mode == 'Tự động chia làn từ ROI':
        poly = fallback_poly
        road_mask = _v6_mask_from_poly(frame.shape, poly)
        road_conf_score = 0.42
        geometry_status = 'CHIA ROI'
        lane_engine = 'roi-split'
        lane_items = tao_lan_duong_tu_roi(
            poly,
            lane_count=max(2, int(self.config.lane.lane_count)),
            include_shoulder=bool(self.config.lane.include_shoulder),
        )
    else:
        poly = fallback_poly
        road_mask = _v6_mask_from_poly(frame.shape, poly)
        road_conf_score = 0.30
        geometry_status = 'ROI THỦ CÔNG'
        lane_engine = 'ROI thủ công'
        lane_items = []

    road_confidence = _v6_confidence_label(float(road_conf_score))
    total_in_roi = 0
    class_counts = {name: 0 for name in VEHICLE_CLASSES}
    lane_counts = {label: 0 for label, _ in lane_items}
    t_sec = self.frame_idx / self.fps_video if self.fps_video > 0 else 0.0

    should_infer = (self.frame_idx % max(1, self.config.detection.frame_stride)) == 0
    if should_infer:
        self.last_inference_boxes = []
        if self.model is not None:
            try:
                device = 'cuda:0' if self.config.detection.use_gpu and CUDA_AVAILABLE else 'cpu'
                res = self.model.predict(
                    frame,
                    imgsz=self.config.detection.imgsz,
                    conf=self.config.detection.conf_th,
                    device=device,
                    half=bool(self.config.detection.use_gpu and CUDA_AVAILABLE),
                    verbose=False,
                )[0]
                if res.boxes is not None and res.boxes.xyxy is not None:
                    xyxy = res.boxes.xyxy.cpu().numpy()
                    cls = res.boxes.cls.cpu().numpy()
                    confs = res.boxes.conf.cpu().numpy()
                    for box, cls_id, confv in zip(xyxy, cls, confs):
                        raw_name = self.name_map.get(int(cls_id), str(cls_id))
                        name = chuan_hoa_ten_xe(raw_name)
                        if name is None:
                            continue
                        x1, y1, x2, y2 = map(int, box)
                        ax, ay = _v6_bottom_anchor_point(x1, y1, x2, y2, lift_px=4)
                        lane_label = None
                        if lane_items:
                            in_roi, lane_label = kiem_tra_diem_trong_lan_duong((ax, ay), lane_items)
                        else:
                            in_roi = kiem_tra_diem_trong_da_giac((ax, ay), poly)
                        if in_roi:
                            total_in_roi += 1
                            class_counts[name] += 1
                            if lane_label is not None:
                                lane_counts[lane_label] = lane_counts.get(lane_label, 0) + 1
                            if self.heatmap_accumulator is not None:
                                cv2.circle(self.heatmap_accumulator, (ax, ay), 12, 1.0, -1)
                            color = (0, 255, 102)
                        else:
                            color = (130, 130, 130)
                        self.last_inference_boxes.append((x1, y1, x2, y2, name, float(confv), color, ax, ay, in_roi, lane_label))
            except Exception as e:
                self.them_nhat_ky(f'[WARN] Lỗi dự đoán YOLO: {e}')

    self.vehicle_history.append(total_in_roi)
    avg_vehicles = round(sum(self.vehicle_history) / max(1, len(self.vehicle_history))) if self.vehicle_history else 0
    density, vsl_speed, traffic_state, reason = tinh_vsl_theo_ngu_canh(avg_vehicles, class_counts, self.config.vsl)
    sudden_increase = (avg_vehicles - self.prev_avg_vehicles) >= self.sudden_increase_threshold
    self.prev_avg_vehicles = avg_vehicles
    priority = tinh_muc_do_uu_tien(density, traffic_state, self.config.vsl.weather, self.config.vsl.incident, sudden_increase, vsl_speed)

    if sudden_increase:
        self.warning_count += 1
        self.them_su_kien('ALERT', f'Mật độ tăng đột biến: trung bình={avg_vehicles}', t_sec)
        self.luu_anh_su_kien(frame, 'sudden_density', t_sec)

    if self.last_state != traffic_state:
        self.them_su_kien('STATE', f'Trạng thái giao thông chuyển thành {traffic_state}', t_sec)
        self.luu_anh_su_kien(frame, f'state_{traffic_state.lower().replace(" ", "_")}', t_sec)
        self.last_state = traffic_state

    if self.last_vsl is None:
        self.last_vsl = vsl_speed
    elif abs(vsl_speed - self.last_vsl) >= 10:
        self.them_su_kien('VSL', f'VSL thay đổi từ {self.last_vsl} đến {vsl_speed}', t_sec)
        self.luu_anh_su_kien(frame, f'vsl_{vsl_speed}', t_sec)
        self.last_vsl = vsl_speed

    if self.last_priority != priority:
        self.them_su_kien('PRIORITY', f'Mức ưu tiên chuyển thành {priority}', t_sec)
        if priority in ('Cần can thiệp', 'Khẩn cấp'):
            self.luu_anh_su_kien(frame, f'priority_{priority.lower().replace(" ", "_")}', t_sec)
        self.last_priority = priority

    if self.config.display.show_heatmap and self.heatmap_accumulator is not None and np.max(self.heatmap_accumulator) > 0:
        heat_norm = cv2.normalize(self.heatmap_accumulator, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        heat_color = cv2.applyColorMap(heat_norm, cv2.COLORMAP_JET)
        frame = cv2.addWeighted(frame, 0.82, heat_color, 0.18, 0)

    if show_road_mask and road_mask is not None:
        _v6_draw_road_mask(frame, road_mask, alpha=0.15 if overlay_mode == 'Trình chiếu' else 0.10)

    if self.config.display.show_roi:
        if overlay_mode == 'Gỡ lỗi':
            ve_vung_giam_sat(frame, poly, alpha=0.05 if show_road_mask else 0.12)
        else:
            cv2.polylines(frame, [poly.astype(np.int32)], True, (0, 214, 255), 2, cv2.LINE_AA)

    if lane_items and self.config.lane.draw_lanes:
        _v6_draw_lane_polygons(frame, lane_items, overlay_mode=overlay_mode)

    if self.config.display.show_boxes:
        for x1, y1, x2, y2, name, confv, color, ax, ay, in_roi, lane_label in self.last_inference_boxes:
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2 if in_roi else 1)
            cv2.circle(frame, (ax, ay), 4 if in_roi else 2, (0, 255, 255) if in_roi else color, -1)
            label = f'{name} {confv:.2f}'
            if not minimal_labels and lane_label:
                label += f' | {_lane_short_label(lane_label)}'
            cv2.putText(frame, label, (x1, max(24, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)

    if overlay_mode == 'Trinh chieu':
        _v6_draw_chip(frame, f'ROAD {road_confidence}', (18, 40), (22, 163, 74) if road_confidence == 'CAO' else ((217, 119, 6) if road_confidence == 'TRUNG BÌNH' else (220, 38, 38)))
        _v6_draw_chip(frame, geometry_status, (180, 40), (37, 99, 235) if 'LOCKED' in geometry_status else ((217, 119, 6) if 'RECOVER' in geometry_status or 'ASSIST' in geometry_status else (220, 38, 38)))
    else:
        _v6_draw_chip(frame, f'ROAD CONFIDENCE: {road_confidence}', (18, 40), (15, 118, 110))
        _v6_draw_chip(frame, f'GEOMETRY: {geometry_status}', (260, 40), (59, 130, 246))
        _v6_draw_chip(frame, f'ENGINE: {lane_engine}', (18, 82), (88, 28, 135))

    lane_counts_text = ' | '.join([f'{_lane_short_label(k)}:{v}' for k, v in lane_counts.items()]) if lane_counts else '-'
    self.last_stats = {
        'vehicles_in_roi': total_in_roi,
        'avg_vehicles': avg_vehicles,
        'density': density,
        'traffic_state': traffic_state,
        'suggested_vsl': vsl_speed,
        'priority': priority,
        'sudden_increase': sudden_increase,
        'reason': f'{reason} | chế độ={roi_mode} | engine={lane_engine}',
        'class_counts': class_counts,
        'lane_counts': lane_counts,
        'lane_counts_text': lane_counts_text,
        'fps_est': round(self.fps_est, 1),
        'warning_count': self.warning_count,
        'snapshot_count': self.snapshot_count,
        'event_count': self.event_count,
        'summary_html_path': str(self.summary_html_path),
        'road_confidence': road_confidence,
        'geometry_status': geometry_status,
        'lane_engine': lane_engine,
        'overlay_mode': overlay_mode,
        'road_conf_score': round(float(road_conf_score), 2),
    }
    self.statsReady.emit(self.last_stats)

    try:
        with open(self.csv_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                self.frame_idx, round(t_sec, 2), total_in_roi, avg_vehicles, density,
                traffic_state, self.config.vsl.weather, self.config.vsl.incident,
                self.config.vsl.control_mode, vsl_speed, priority, sudden_increase,
                class_counts.get('car', 0), class_counts.get('motorcycle', 0),
                class_counts.get('bus', 0), class_counts.get('truck', 0),
                class_counts.get('bicycle', 0), reason
            ])
    except Exception:
        pass

    return frame


_orig_build_roi_page_v6 = GiaoDienChinh.tao_trang_roi
_orig_build_view_page_v6 = GiaoDienChinh.tao_trang_bao_cao
_orig_build_monitoring_area_v6 = GiaoDienChinh.tao_khu_giam_sat
_orig_bind_initial_state_v6 = GiaoDienChinh._gan_trang_thai_ban_dau
_orig_on_reset_roi_v6 = GiaoDienChinh.xu_ly_dat_lai_roi
_orig_set_controls_enabled_for_runtime_v6 = GiaoDienChinh.bat_tat_dieu_khien_khi_chay
_orig_update_ui_from_stats_v6 = GiaoDienChinh.update_ui_from_stats


def _v6_build_roi_page(self):
    page = _orig_build_roi_page_v6(self)
    items = ['ROI thủ công', 'Làn bán tự động', 'Tự động chia làn từ ROI', 'Tự nhận dạng mặt đường']
    current = getattr(self.config.lane, 'roi_mode', 'Tự nhận dạng mặt đường')
    if current == 'ROI thủ công':
        current = 'Tự nhận dạng mặt đường'
    self.cbo_roi_mode.blockSignals(True)
    self.cbo_roi_mode.clear()
    self.cbo_roi_mode.addItems(items)
    self.cbo_roi_mode.setCurrentText(current if current in items else 'Tự nhận dạng mặt đường')
    self.cbo_roi_mode.blockSignals(False)
    self.config.lane.roi_mode = self.cbo_roi_mode.currentText() or 'Tự nhận dạng mặt đường'

    info = KhungNoiDung('Tự động Geometry', 'Chế độ mới ưu tiên tự nhận vùng mặt đường, hiển thị confidence và fallback status để demo chuyên nghiệp hơn.')
    tip = QtWidgets.QLabel('Khuyên dùng: Tự động Road Geometry + Presentation mode + Road Mask Overlay để giao diện sạch, tự tin và ít phải chỉnh tay.')
    tip.setWordWrap(True)
    tip.setObjectName('SectionHint')
    info.lay.addWidget(tip)
    page.content.insertWidget(1, info)
    return page


def _v6_build_view_page(self):
    page = _orig_build_view_page_v6(self)
    if not hasattr(self.config.display, 'show_road_mask'):
        self.config.display.show_road_mask = True
    if not hasattr(self.config.display, 'overlay_mode'):
        self.config.display.overlay_mode = 'Trình chiếu'
    if not hasattr(self.config.display, 'minimal_labels'):
        self.config.display.minimal_labels = True

    c_extra = KhungNoiDung('Chế độ hiển thị chuyên nghiệp', 'Bộ tùy chọn để chuyển nhanh giữa kiểu demo sạch và kiểu debug kỹ thuật.')
    self.chk_show_road_mask = QtWidgets.QCheckBox('Hiển thị lớp mặt đường')
    self.chk_show_road_mask.setChecked(bool(getattr(self.config.display, 'show_road_mask', True)))
    self.chk_minimal_labels = QtWidgets.QCheckBox('Rút gọn nhãn phương tiện')
    self.chk_minimal_labels.setChecked(bool(getattr(self.config.display, 'minimal_labels', True)))
    self.cbo_overlay_mode = QtWidgets.QComboBox()
    self.cbo_overlay_mode.addItems(['Trình chiếu', 'Gỡ lỗi'])
    self.cbo_overlay_mode.setCurrentText(str(getattr(self.config.display, 'overlay_mode', 'Trình chiếu')))
    c_extra.lay.addWidget(QtWidgets.QLabel('Overlay Chế độ'))
    c_extra.lay.addWidget(self.cbo_overlay_mode)
    c_extra.lay.addWidget(self.chk_show_road_mask)
    c_extra.lay.addWidget(self.chk_minimal_labels)
    page.content.insertWidget(1, c_extra)
    return page


def _v6_build_monitoring_area(self):
    right = _orig_build_monitoring_area_v6(self)
    try:
        video_panel = right.layout().itemAt(1).widget()
        top_layout = video_panel.layout().itemAt(0).layout()
        badge_layout = top_layout.itemAt(1).layout()
        self.badge_geom = self.tao_nhan_trang_thai('Road: LOCKING', 'BadgeBlue')
        badge_layout.addWidget(self.badge_geom)
    except Exception:
        self.badge_geom = None

    try:
        insight = right.layout().itemAt(2).widget()
        grid = insight.layout()
        self.lbl_road_conf = QtWidgets.QLabel('Road Confidence: -')
        self.lbl_geometry_status = QtWidgets.QLabel('Geometry Status: -')
        for lb in [self.lbl_road_conf, self.lbl_geometry_status]:
            lb.setObjectName('InsightText')
        grid.addWidget(self.lbl_road_conf, 9, 0)
        grid.addWidget(self.lbl_geometry_status, 9, 1)
    except Exception:
        self.lbl_road_conf = None
        self.lbl_geometry_status = None
    return right


def _v6_bind_initial_state(self):
    _orig_bind_initial_state_v6(self)
    self.chk_show_hud.stateChanged.connect(lambda s: setattr(self.config.display, 'show_hud', s == QtCore.Qt.Checked))
    if hasattr(self, 'chk_show_road_mask'):
        self.chk_show_road_mask.stateChanged.connect(lambda s: setattr(self.config.display, 'show_road_mask', s == QtCore.Qt.Checked))
    if hasattr(self, 'chk_minimal_labels'):
        self.chk_minimal_labels.stateChanged.connect(lambda s: setattr(self.config.display, 'minimal_labels', s == QtCore.Qt.Checked))
    if hasattr(self, 'cbo_overlay_mode'):
        self.cbo_overlay_mode.currentTextChanged.connect(lambda t: setattr(self.config.display, 'overlay_mode', t))
    if hasattr(self, 'cbo_roi_mode') and self.cbo_roi_mode.findText('Tự nhận dạng mặt đường') >= 0 and not self.cbo_roi_mode.currentText():
        self.cbo_roi_mode.setCurrentText('Tự nhận dạng mặt đường')


def _v6_on_reset_roi(self):
    _orig_on_reset_roi_v6(self)
    if hasattr(self, 'cbo_roi_mode') and self.cbo_roi_mode.findText('Tự nhận dạng mặt đường') >= 0:
        self.cbo_roi_mode.setCurrentText('Tự nhận dạng mặt đường')
        self.config.lane.roi_mode = 'Tự nhận dạng mặt đường'


def _v6_set_controls_enabled_for_runtime(self, running: bool):
    _orig_set_controls_enabled_for_runtime_v6(self, running)
    extra = []
    for name in ('chk_show_road_mask', 'chk_minimal_labels', 'cbo_overlay_mode'):
        if hasattr(self, name):
            extra.append(getattr(self, name))
    for w in extra:
        w.setEnabled(True)


def _v6_update_ui_from_stats(self, stats: dict):
    _orig_update_ui_from_stats_v6(self, stats)
    road_conf = stats.get('road_confidence', '-')
    geometry_status = stats.get('geometry_status', '-')
    lane_engine = stats.get('lane_engine', '-')
    lane_counts_text = stats.get('lane_counts_text', '-')

    if hasattr(self, 'lbl_lane_counts'):
        self.lbl_lane_counts.setText(f'Số xe theo làn: {lane_counts_text}')
    if hasattr(self, 'lbl_road_conf') and self.lbl_road_conf is not None:
        self.lbl_road_conf.setText(f'Road Confidence: {road_conf} ({stats.get("road_conf_score", 0):.2f})')
    if hasattr(self, 'lbl_geometry_status') and self.lbl_geometry_status is not None:
        self.lbl_geometry_status.setText(f'Geometry Status: {geometry_status} | Engine: {lane_engine}')
    if hasattr(self, 'lbl_reason'):
        base_reason = stats.get('reason', 'hệ thống đã khởi tạo')
        self.lbl_reason.setText(f'Lý do: {base_reason} | overlay={stats.get("overlay_mode", "Presentation")}')
    if hasattr(self, 'badge_geom') and self.badge_geom is not None:
        self.badge_geom.setText(f'Road: {geometry_status}')
        _v6_badge_style_text(self.badge_geom, geometry_status)


GiaoDienChinh.tao_trang_roi = _v6_build_roi_page
GiaoDienChinh.tao_trang_bao_cao = _v6_build_view_page
GiaoDienChinh.tao_khu_giam_sat = _v6_build_monitoring_area
GiaoDienChinh._gan_trang_thai_ban_dau = _v6_bind_initial_state
GiaoDienChinh.xu_ly_dat_lai_roi = _v6_on_reset_roi
GiaoDienChinh.bat_tat_dieu_khien_khi_chay = _v6_set_controls_enabled_for_runtime
GiaoDienChinh.update_ui_from_stats = _v6_update_ui_from_stats
XuLyVideo.xu_ly_khung_hinh = _videoworker_process_frame_v6


def main():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)

    auth_manager = QuanLyTaiKhoan(AUTH_DB)

    if not auth_manager.kiem_tra_co_nguoi_dung():
        dlg = TaoQuanTriVienDauTien(auth_manager)
        dlg.exec_()

    splash = ManHinhKhoiDong()
    auth = CuaSoDangNhap(auth_manager)
    holder = {"main": None}

    def show_auth():
        auth.show()

    def on_login_success(user):
        auth.close()
        win = GiaoDienChinh(user)
        holder["main"] = win
        win.show()

    splash.finished.connect(show_auth)
    auth.loginSuccess.connect(on_login_success)

    splash.show()
    app.exec_()

# =========================================================
# V6.1 UI SCROLL + ROI PAGE SPACING HOTFIX
# =========================================================
_orig_labeled_slider_init_v61 = ThanhTruotCoNhan.__init__
_orig_build_module_stack_v61 = GiaoDienChinh.tao_chong_trang_chuc_nang
_orig_build_roi_page_v61 = GiaoDienChinh.tao_trang_roi


def _v61_labeled_slider_init(self, text: str, minv: int, maxv: int, value: int, step: int = 1):
    _orig_labeled_slider_init_v61(self, text, minv, maxv, value, step)
    try:
        self.setMinimumHeight(58)
        self.label.setMinimumHeight(20)
        self.slider.setMinimumHeight(22)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
    except Exception:
        pass


def _v61_wrap_scroll_page(page: QtWidgets.QWidget):
    try:
        page.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
        if page.layout() is not None:
            page.layout().setSizeConstmưat(QtWidgets.QLayout.SetMinimumSize)
        page.adjustSize()
        page.setMinimumHeight(page.sizeHint().height() + 12)
    except Exception:
        pass

    host = QtWidgets.QWidget()
    host_layout = QtWidgets.QVBoxLayout(host)
    host_layout.setContentsMargins(0, 0, 0, 0)
    host_layout.setSpacing(0)
    host_layout.addWidget(page)
    host_layout.addStretch(1)
    host.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)

    scroll = QtWidgets.QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
    scroll.setWidget(host)
    return scroll


def _v61_build_module_stack(self):
    wrap = QtWidgets.QWidget()
    out = QtWidgets.QVBoxLayout(wrap)
    out.setContentsMargins(0, 0, 0, 0)
    out.setSpacing(0)
    self.stack = QtWidgets.QStackedWidget()
    pages = [
        self.tao_trang_khoi_dong_nhanh(),
        self.tao_trang_phien_lam_viec(),
        self.tao_trang_nhan_dien(),
        self.tao_trang_roi(),
        self.tao_trang_vsl(),
        self.tao_trang_bao_cao(),
    ]
    for page in pages:
        self.stack.addWidget(_v61_wrap_scroll_page(page))
    out.addWidget(self.stack)
    return wrap


def _v61_build_roi_page(self):
    page = _orig_build_roi_page_v61(self)
    try:
        page.content.setSpacing(16)
    except Exception:
        pass

    widgets_to_tune = [
        getattr(self, 'cbo_roi_mode', None),
        getattr(self, 'sld_lane_count', None),
        getattr(self, 'chk_include_shoulder', None),
        getattr(self, 'chk_draw_lanes', None),
        getattr(self, 'sld_top_cx', None),
        getattr(self, 'sld_bot_cx', None),
        getattr(self, 'sld_bot_w', None),
        getattr(self, 'sld_top_w', None),
        getattr(self, 'sld_height', None),
        getattr(self, 'sld_bottom_y', None),
        getattr(self, 'btn_reset_roi', None),
    ]
    for w in widgets_to_tune:
        if w is None:
            continue
        try:
            if isinstance(w, QtWidgets.QComboBox):
                w.setMinimumHeight(40)
            elif isinstance(w, QtWidgets.QPushButton):
                w.setMinimumHeight(42)
            elif isinstance(w, QtWidgets.QCheckBox):
                w.setMinimumHeight(28)
            elif isinstance(w, ThanhTruotCoNhan):
                w.setMinimumHeight(58)
        except Exception:
            pass

    try:
        for sec in page.findChildren(QtWidgets.QGroupBox):
            sec.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
            sec.adjustSize()
            sec.setMinimumHeight(sec.sizeHint().height() + 8)
    except Exception:
        pass

    return page


ThanhTruotCoNhan.__init__ = _v61_labeled_slider_init
GiaoDienChinh.tao_trang_roi = _v61_build_roi_page
GiaoDienChinh.tao_chong_trang_chuc_nang = _v61_build_module_stack

if False and __name__ == "__main__":
    main()


# =========================================================
# V6.2 PERFORMANCE + SAFE PAGE SWITCH HOTFIX
# =========================================================
_orig_animate_page_change_v62 = GiaoDienChinh.hieu_ung_chuyen_trang
_orig_show_frame_v62 = GiaoDienChinh.show_frame
_orig_update_ui_from_stats_v62 = GiaoDienChinh.update_ui_from_stats
_orig_append_log_v62 = GiaoDienChinh.append_log


def _v62_clear_widget_effects(widget):
    if widget is None:
        return
    try:
        widget.setGraphicsEffect(None)
    except Exception:
        pass
    try:
        if isinstance(widget, QtWidgets.QScrollArea):
            widget.viewport().setGraphicsEffect(None)
            inner = widget.widget()
            if inner is not None:
                inner.setGraphicsEffect(None)
    except Exception:
        pass


def _v62_animate_page_change(self, index: int):
    if not hasattr(self, 'stack') or self.stack is None or self.stack.count() <= 0:
        return

    index = max(0, min(int(index), self.stack.count() - 1))

    try:
        self.stack.setUpdatesEnabled(False)
        for i in range(self.stack.count()):
            _v62_clear_widget_effects(self.stack.widget(i))

        self.stack.setCurrentIndex(index)
        current = self.stack.currentWidget()
        _v62_clear_widget_effects(current)

        if isinstance(current, QtWidgets.QScrollArea):
            try:
                current.verticalScrollBar().setValue(0)
            except Exception:
                pass
            try:
                current.viewport().update()
            except Exception:
                pass
        elif current is not None:
            current.update()
    finally:
        try:
            self.stack.setUpdatesEnabled(True)
            self.stack.update()
        except Exception:
            pass


def _v62_show_frame(self, qimg: QtGui.QImage):
    now = time.perf_counter()
    last_ts = getattr(self, '_last_frame_render_ts', 0.0)
    # cap UI repaint rate to reduce lag when worker is fast
    if (now - last_ts) < (1.0 / 15.0):
        return
    self._last_frame_render_ts = now

    try:
        pix = QtGui.QPixmap.fromImage(qimg)
        scaled = pix.scaled(self.video_label.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.FastTransformation)
        self.video_label.setPixmap(scaled)
    except Exception:
        _orig_show_frame_v62(self, qimg)


def _v62_update_ui_from_stats(self, stats: dict):
    now = time.perf_counter()
    last_ts = getattr(self, '_last_stats_ui_ts', 0.0)
    # throttle heavy label/card updates
    if (now - last_ts) < 0.18:
        return
    self._last_stats_ui_ts = now
    _orig_update_ui_from_stats_v62(self, stats)


def _v62_append_log(self, text: str):
    try:
        self.log_view.appendPlainText(text)
        doc = self.log_view.document()
        extra = doc.blockCount() - self.log_lines_max
        if extra > 0:
            cursor = self.log_view.textCursor()
            cursor.movePosition(QtGui.QTextCursor.Start)
            for _ in range(extra):
                cursor.select(QtGui.QTextCursor.LineUnderCursor)
                cursor.removeSelectedText()
                cursor.deleteChar()
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())
    except Exception:
        _orig_append_log_v62(self, text)


GiaoDienChinh.hieu_ung_chuyen_trang = _v62_animate_page_change
GiaoDienChinh.show_frame = _v62_show_frame
GiaoDienChinh.update_ui_from_stats = _v62_update_ui_from_stats
GiaoDienChinh.append_log = _v62_append_log


# =========================================================
# V6.3 FINAL STARTUP ORDER + OPAQUE STACK / NO-GHOST HOTFIX
# Root cause fixed: previous hotfixes were defined AFTER main() had already
# started the Qt event loop, so they never took effect at runtime.
# =========================================================
_orig_build_module_stack_v63 = GiaoDienChinh.tao_chong_trang_chuc_nang
_orig_animate_page_change_v63 = GiaoDienChinh.hieu_ung_chuyen_trang
_orig_show_frame_v63 = GiaoDienChinh.show_frame
_orig_update_ui_from_stats_v63 = GiaoDienChinh.update_ui_from_stats


def _v63_apply_bg(widget, color="#eef4fb"):
    if widget is None:
        return
    try:
        widget.setAttribute(QtCore.Qt.WA_StyledBackground, True)
    except Exception:
        pass
    try:
        widget.setAutoFillBackground(True)
        pal = widget.palette()
        pal.setColor(QtGui.QPalette.Window, QtGui.QColor(color))
        widget.setPalette(pal)
    except Exception:
        pass


def _v63_wrap_scroll_page(page: QtWidgets.QWidget):
    try:
        _v63_apply_bg(page, "#eef4fb")
        page.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
        if page.layout() is not None:
            page.layout().setSizeConstmưat(QtWidgets.QLayout.SetMinimumSize)
        page.adjustSize()
        page.setMinimumHeight(page.sizeHint().height() + 20)
    except Exception:
        pass

    host = QtWidgets.QWidget()
    _v63_apply_bg(host, "#eef4fb")
    host_layout = QtWidgets.QVBoxLayout(host)
    host_layout.setContentsMargins(0, 0, 0, 0)
    host_layout.setSpacing(0)
    host_layout.addWidget(page)
    host_layout.addStretch(1)
    host.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)

    scroll = QtWidgets.QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
    scroll.setWidget(host)
    _v63_apply_bg(scroll, "#eef4fb")
    try:
        _v63_apply_bg(scroll.viewport(), "#eef4fb")
    except Exception:
        pass
    try:
        scroll.viewport().setAttribute(QtCore.Qt.WA_OpaquePaintEvent, True)
    except Exception:
        pass
    return scroll


def _v63_build_module_stack(self):
    wrap = QtWidgets.QWidget()
    _v63_apply_bg(wrap, "#eef4fb")
    out = QtWidgets.QVBoxLayout(wrap)
    out.setContentsMargins(0, 0, 0, 0)
    out.setSpacing(0)

    self.stack = QtWidgets.QStackedWidget()
    _v63_apply_bg(self.stack, "#eef4fb")
    try:
        self.stack.setContentsMargins(0, 0, 0, 0)
    except Exception:
        pass

    pages = [
        self.tao_trang_khoi_dong_nhanh(),
        self.tao_trang_phien_lam_viec(),
        self.tao_trang_nhan_dien(),
        self.tao_trang_roi(),
        self.tao_trang_vsl(),
        self.tao_trang_bao_cao(),
    ]
    for page in pages:
        self.stack.addWidget(_v63_wrap_scroll_page(page))
    out.addWidget(self.stack)
    return wrap


def _v63_clear_all_effects(widget):
    if widget is None:
        return
    try:
        widget.setGraphicsEffect(None)
    except Exception:
        pass
    try:
        for child in widget.findChildren(QtWidgets.QWidget):
            try:
                child.setGraphicsEffect(None)
            except Exception:
                pass
    except Exception:
        pass


def _v63_animate_page_change(self, index: int):
    if not hasattr(self, 'stack') or self.stack is None or self.stack.count() <= 0:
        return
    index = max(0, min(int(index), self.stack.count() - 1))

    self.stack.setUpdatesEnabled(False)
    try:
        for i in range(self.stack.count()):
            _v63_clear_all_effects(self.stack.widget(i))
        self.stack.setCurrentIndex(index)
        current = self.stack.currentWidget()
        _v63_clear_all_effects(current)
        if isinstance(current, QtWidgets.QScrollArea):
            try:
                current.verticalScrollBar().setValue(0)
            except Exception:
                pass
            try:
                current.viewport().repaint()
            except Exception:
                pass
        elif current is not None:
            try:
                current.repaint()
            except Exception:
                pass
    finally:
        self.stack.setUpdatesEnabled(True)
        try:
            self.stack.repaint()
        except Exception:
            pass


def _v63_show_frame(self, qimg: QtGui.QImage):
    now = time.perf_counter()
    last_ts = getattr(self, '_last_frame_render_ts_v63', 0.0)
    if (now - last_ts) < (1.0 / 12.0):
        return
    self._last_frame_render_ts_v63 = now
    try:
        pix = QtGui.QPixmap.fromImage(qimg)
        scaled = pix.scaled(self.video_label.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.FastTransformation)
        self.video_label.setPixmap(scaled)
    except Exception:
        _orig_show_frame_v63(self, qimg)


def _v63_update_ui_from_stats(self, stats: dict):
    now = time.perf_counter()
    last_ts = getattr(self, '_last_stats_ui_ts_v63', 0.0)
    if (now - last_ts) < 0.22:
        return
    self._last_stats_ui_ts_v63 = now
    _orig_update_ui_from_stats_v63(self, stats)


GiaoDienChinh.tao_chong_trang_chuc_nang = _v63_build_module_stack
GiaoDienChinh.hieu_ung_chuyen_trang = _v63_animate_page_change
GiaoDienChinh.show_frame = _v63_show_frame
GiaoDienChinh.update_ui_from_stats = _v63_update_ui_from_stats


# =========================================================
# V9 LANE INTELLIGENCE PATCH
# Adds:
# - Lane-wise average speed (estimated)
# - Stopped / abnormal slow vehicle alerts
# - Lane color state on canvas
# =========================================================
_orig_build_view_page_v9 = GiaoDienChinh.tao_trang_bao_cao
_orig_build_monitoring_area_v9 = GiaoDienChinh.tao_khu_giam_sat
_orig_bind_initial_state_v9 = GiaoDienChinh._gan_trang_thai_ban_dau
_orig_set_controls_enabled_for_runtime_v9 = GiaoDienChinh.bat_tat_dieu_khien_khi_chay
_orig_update_ui_from_stats_v9 = GiaoDienChinh.update_ui_from_stats


def _v9_parse_lane_index(label: str) -> int:
    m = re.search(r'(\d+)', str(label or ''))
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass
    if 'left' in str(label).lower():
        return -1
    if 'right' in str(label).lower():
        return 999
    return 999


def _v9_sorted_lane_labels(labels):
    return sorted(labels, key=_v9_parse_lane_index)


def _v9_lane_speed_text(speed_map: dict) -> str:
    if not speed_map:
        return '-'
    parts = []
    for k in _v9_sorted_lane_labels(speed_map.keys()):
        v = speed_map.get(k)
        if v is None:
            continue
        parts.append(f'{_lane_short_label(k)}:{int(round(v))} km/h')
    return ' | '.join(parts) if parts else '-'


def _v9_lane_state_from_metrics(count: int, avg_speed: float | None) -> str:
    c = int(count or 0)
    s = None if avg_speed is None else float(avg_speed)
    if c <= 0:
        return 'THẤP'
    if s is not None and s < 10:
        return 'CAO'
    if c >= 5:
        return 'CAO'
    if c >= 3:
        return 'TRUNG BÌNH'
    if s is not None and s < 18:
        return 'TRUNG BÌNH'
    return 'THẤP'


def _v9_lane_state_text(lane_counts: dict, speed_map: dict) -> str:
    labels = set(lane_counts.keys()) | set(speed_map.keys())
    if not labels:
        return '-'
    parts = []
    for k in _v9_sorted_lane_labels(labels):
        state = _v9_lane_state_from_metrics(lane_counts.get(k, 0), speed_map.get(k))
        parts.append(f'{_lane_short_label(k)}:{state}')
    return ' | '.join(parts)


def _v9_color_for_lane_state(state: str):
    state = str(state or '').upper()
    if state == 'CAO':
        return (64, 64, 255)
    if state == 'TRUNG BÌNH':
        return (0, 200, 255)
    return (80, 220, 120)


def _v9_draw_lane_state_polygons(frame, lane_items, lane_counts, speed_map, overlay_mode='Trình chiếu'):
    if not lane_items:
        return
    overlay = frame.copy()
    alpha = 0.10 if overlay_mode == 'Trình chiếu' else 0.06
    for label, poly in lane_items:
        state = _v9_lane_state_from_metrics(lane_counts.get(label, 0), speed_map.get(label))
        color = _v9_color_for_lane_state(state)
        if overlay_mode == 'Gỡ lỗi':
            cv2.fillPoly(overlay, [poly], color)
        cv2.polylines(frame, [poly], True, color, 2, cv2.LINE_AA)
        bottom_mid = ((poly[2].astype(np.float32) + poly[3].astype(np.float32)) / 2.0).astype(int)
        tx = int(np.clip(bottom_mid[0] - 34, 5, frame.shape[1] - 110))
        ty = int(np.clip(bottom_mid[1] - 14, 20, frame.shape[0] - 10))
        text = f'{_lane_short_label(label)} {state}'
        cv2.putText(frame, text, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.52, color, 2, cv2.LINE_AA)
    if overlay_mode == 'Gỡ lỗi':
        cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)


def _v9_est_speed_kmh(prev_pt, pt, dt, frame_h: int) -> float:
    if dt <= 1e-6:
        return 0.0
    dx = float(pt[0] - prev_pt[0])
    dy = float(pt[1] - prev_pt[1])
    disp = float((dx * dx + dy * dy) ** 0.5)
    speed_pxps = disp / dt
    y_norm = float(np.clip(pt[1] / max(1.0, frame_h), 0.0, 1.0))
    perspective_factor = float(np.clip(1.0 + 1.8 * (1.0 - y_norm), 1.0, 2.6))
    return float(np.clip(speed_pxps * 0.28 * perspective_factor, 0.0, 140.0))


def _v9_init_lane_runtime(self):
    if not hasattr(self, '_lane_tracks_v9'):
        self._lane_tracks_v9 = {}
    if not hasattr(self, '_next_track_id_v9'):
        self._next_track_id_v9 = 1


def _v9_update_tracks(self, detections, t_sec: float, frame_shape):
    _v9_init_lane_runtime(self)
    h, w = frame_shape[:2]
    tracks = self._lane_tracks_v9
    stale_cutoff = 1.3
    for tid in list(tracks.keys()):
        if (t_sec - tracks[tid].get('t', t_sec)) > stale_cutoff:
            tracks.pop(tid, None)

    unmatched_tracks = set(tracks.keys())
    active_alerts = []

    for det in detections:
        if not det.get('in_roi'):
            continue
        pt = (int(det['ax']), int(det['ay']))
        lane_label = det.get('lane_label')
        best_tid = None
        best_dist = 1e9
        for tid in list(unmatched_tracks):
            tr = tracks.get(tid)
            if tr is None:
                continue
            prev_pt = tr.get('pt', pt)
            dist = float(np.hypot(pt[0] - prev_pt[0], pt[1] - prev_pt[1]))
            max_dist = 54.0 if lane_label and tr.get('lane') == lane_label else 38.0
            if dist <= max_dist and dist < best_dist:
                best_tid = tid
                best_dist = dist
        if best_tid is None:
            best_tid = self._next_track_id_v9
            self._next_track_id_v9 += 1
            tracks[best_tid] = {
                'pt': pt,
                't': t_sec,
                'lane': lane_label,
                'speed': 0.0,
                'slow_s': 0.0,
                'alerted': False,
                'last_alert_t': -999.0,
                'history': deque(maxlen=16),
            }
        else:
            unmatched_tracks.discard(best_tid)

        tr = tracks[best_tid]
        prev_pt = tr.get('pt', pt)
        prev_t = tr.get('t', t_sec)
        dt = max(1e-3, t_sec - prev_t)
        inst_speed = _v9_est_speed_kmh(prev_pt, pt, dt, h, lane_label)
        old_speed = float(tr.get('speed', inst_speed))
        if inst_speed <= 0:
           smoothed_speed = old_speed * 0.90
        else:
            smoothed_speed = 0.78 * old_speed + 0.22 * inst_speed
        tr['pt'] = pt
        tr['t'] = t_sec
        tr['lane'] = lane_label or tr.get('lane')
        tr['speed'] = smoothed_speed
        tr['history'].append(pt)

        if pt[1] >= int(h * 0.42) and smoothed_speed < 8.0:
            tr['slow_s'] = float(tr.get('slow_s', 0.0)) + dt
        else:
            tr['slow_s'] = max(0.0, float(tr.get('slow_s', 0.0)) - dt * 0.5)

        if tr['slow_s'] >= 1.8:
            active_alerts.append(best_tid)
            if (t_sec - float(tr.get('last_alert_t', -999.0))) > 4.0:
                self.warning_count += 1
                lane_note = _lane_short_label(tr.get('lane') or '-')
                self.them_su_kien('STHẤP VEHICLE', f'Possible stopped / very slow vehicle at {lane_note}', t_sec)
                self.luu_anh_su_kien(self.last_frame_bgr if self.last_frame_bgr is not None else np.zeros((h,w,3), dtype=np.uint8), 'slow_vehicle', t_sec)
                tr['last_alert_t'] = t_sec
            tr['alerted'] = True
        else:
            tr['alerted'] = False

        det['track_id'] = best_tid
        det['speed_kmh'] = smoothed_speed
        det['history'] = list(tr['history'])
        det['slow_alert'] = bool(tr['alerted'])

    active_speed_by_lane = {}
    active_count_by_lane = {}
    for tid, tr in tracks.items():
        if (t_sec - tr.get('t', t_sec)) > 0.8:
            continue
        lane = tr.get('lane')
        if not lane:
            continue
        speed = float(tr.get('speed', 0.0))
        if speed <= 0.5:
            continue
        active_speed_by_lane[lane] = active_speed_by_lane.get(lane, 0.0) + speed
        active_count_by_lane[lane] = active_count_by_lane.get(lane, 0) + 1

    lane_speed_map = {}
    for lane, total_speed in active_speed_by_lane.items():
        lane_speed_map[lane] = total_speed / max(1, active_count_by_lane.get(lane, 1))

    return lane_speed_map, len(set(active_alerts))


def _v9_draw_trails(frame, detections):
    for det in detections:
        if not det.get('in_roi'):
            continue
        hist = det.get('history') or []
        if len(hist) < 2:
            continue
        pts = np.array(hist[-12:], dtype=np.int32).reshape((-1, 1, 2))
        color = (0, 255, 255) if det.get('slow_alert') else (59, 130, 246)
        cv2.polylines(frame, [pts], False, color, 2, cv2.LINE_AA)


def _v9_build_view_page(self):
    page = _orig_build_view_page_v9(self)
    for attr, default in (
        ('show_lane_speed', True),
        ('show_slow_alerts', True),
        ('show_lane_color_state', True),
        ('show_vehicle_trails', True),
    ):
        if not hasattr(self.config.display, attr):
            setattr(self.config.display, attr, default)

    c_lane = KhungNoiDung('Phân tích làn đường thông minh', 'Hiển thị tốc độ ước lượng theo làn, cảnh báo xe chậm/dừng và tô màu làn theo tải.')
    self.chk_show_lane_speed = QtWidgets.QCheckBox('Hiển thị tốc độ trung bình theo làn')
    self.chk_show_lane_speed.setChecked(bool(getattr(self.config.display, 'show_lane_speed', True)))
    self.chk_show_slow_alerts = QtWidgets.QCheckBox('Cảnh báo xe chậm/dừng')
    self.chk_show_slow_alerts.setChecked(bool(getattr(self.config.display, 'show_slow_alerts', True)))
    self.chk_show_lane_color_state = QtWidgets.QCheckBox('Tô màu trạng thái làn')
    self.chk_show_lane_color_state.setChecked(bool(getattr(self.config.display, 'show_lane_color_state', True)))
    self.chk_show_vehicle_trails = QtWidgets.QCheckBox('Hiển thị vệt di chuyển phương tiện')
    self.chk_show_vehicle_trails.setChecked(bool(getattr(self.config.display, 'show_vehicle_trails', True)))
    for w in (self.chk_show_lane_speed, self.chk_show_slow_alerts, self.chk_show_lane_color_state, self.chk_show_vehicle_trails):
        c_lane.lay.addWidget(w)
    page.content.insertWidget(2, c_lane)
    return page


def _v9_build_monitoring_area(self):
    right = _orig_build_monitoring_area_v9(self)
    try:
        insight = right.layout().itemAt(2).widget()
        grid = insight.layout()
        self.lbl_lane_speed = QtWidgets.QLabel('Tốc độ TB theo làn (ước lượng): -')
        self.lbl_lane_state = QtWidgets.QLabel('Trạng thái làn: -')
        self.lbl_slow_alerts = QtWidgets.QLabel('Cảnh báo xe chậm/dừng: -')
        for lb in (self.lbl_lane_speed, self.lbl_lane_state, self.lbl_slow_alerts):
            lb.setObjectName('InsightText')
        grid.addWidget(self.lbl_lane_speed, 10, 0, 1, 2)
        grid.addWidget(self.lbl_lane_state, 11, 0, 1, 2)
        grid.addWidget(self.lbl_slow_alerts, 12, 0, 1, 2)
    except Exception:
        self.lbl_lane_speed = None
        self.lbl_lane_state = None
        self.lbl_slow_alerts = None
    return right


def _v9_bind_initial_state(self):
    _orig_bind_initial_state_v9(self)
    if hasattr(self, 'chk_show_lane_speed'):
        self.chk_show_lane_speed.stateChanged.connect(lambda s: setattr(self.config.display, 'show_lane_speed', s == QtCore.Qt.Checked))
    if hasattr(self, 'chk_show_slow_alerts'):
        self.chk_show_slow_alerts.stateChanged.connect(lambda s: setattr(self.config.display, 'show_slow_alerts', s == QtCore.Qt.Checked))
    if hasattr(self, 'chk_show_lane_color_state'):
        self.chk_show_lane_color_state.stateChanged.connect(lambda s: setattr(self.config.display, 'show_lane_color_state', s == QtCore.Qt.Checked))
    if hasattr(self, 'chk_show_vehicle_trails'):
        self.chk_show_vehicle_trails.stateChanged.connect(lambda s: setattr(self.config.display, 'show_vehicle_trails', s == QtCore.Qt.Checked))


def _v9_set_controls_enabled_for_runtime(self, running: bool):
    _orig_set_controls_enabled_for_runtime_v9(self, running)
    for name in ('chk_show_lane_speed', 'chk_show_slow_alerts', 'chk_show_lane_color_state', 'chk_show_vehicle_trails'):
        if hasattr(self, name):
            getattr(self, name).setEnabled(True)


def _v9_update_ui_from_stats(self, stats: dict):
    _orig_update_ui_from_stats_v9(self, stats)
    if hasattr(self, 'lbl_lane_speed') and self.lbl_lane_speed is not None:
        self.lbl_lane_speed.setText(f"Lane Avg Speed (est.): {stats.get('lane_speed_text', '-')}")
    if hasattr(self, 'lbl_lane_state') and self.lbl_lane_state is not None:
        self.lbl_lane_state.setText(f"Lane State: {stats.get('lane_state_text', '-')}")
    if hasattr(self, 'lbl_slow_alerts') and self.lbl_slow_alerts is not None:
        self.lbl_slow_alerts.setText(f"Slow / Stopped Alerts: {stats.get('slow_alert_text', '-')}")


def _videoworker_process_frame_v9(self, frame):
    h, w = frame.shape[:2]
    if not hasattr(self, '_auto_poly_prev'):
        self._auto_poly_prev = None
    if not hasattr(self, '_auto_fail_count'):
        self._auto_fail_count = 0

    show_road_mask = bool(getattr(self.config.display, 'show_road_mask', True))
    overlay_mode = str(getattr(self.config.display, 'overlay_mode', 'Trình chiếu'))
    minimal_labels = bool(getattr(self.config.display, 'minimal_labels', True))
    show_lane_speed = bool(getattr(self.config.display, 'show_lane_speed', True))
    show_slow_alerts = bool(getattr(self.config.display, 'show_slow_alerts', True))
    show_lane_color_state = bool(getattr(self.config.display, 'show_lane_color_state', True))
    show_vehicle_trails = bool(getattr(self.config.display, 'show_vehicle_trails', True))

    rc = self.config.roi
    fallback_poly = tao_da_giac_roi(w, h, rc.top_center_x, rc.bottom_center_x, rc.bottom_width, rc.top_width, rc.height, rc.bottom_y)
    roi_mode = str(getattr(self.config.lane, 'roi_mode', 'Tự nhận dạng mặt đường'))

    lane_items = []
    road_mask = None
    poly = fallback_poly
    road_conf_score = 0.32
    geometry_status = 'ROI THỦ CÔNG'
    lane_engine = 'ROI thủ công'

    if roi_mode == 'Tự nhận dạng mặt đường':
        auto_poly, road_mask, road_conf_score, auto_success = _v6_auto_road_polygon_from_frame(frame, self._auto_poly_prev)
        if auto_success and auto_poly is not None:
            poly = auto_poly
            self._auto_poly_prev = auto_poly.copy()
            self._auto_fail_count = 0
            geometry_status = 'ĐÃ KHÓA LÀN'
            lane_engine = 'auto-road-v9'
        else:
            self._auto_fail_count += 1
            if self._auto_poly_prev is not None and self._auto_fail_count <= 18:
                poly = self._auto_poly_prev.copy()
                geometry_status = 'ĐANG KHÔI PHỤC'
                lane_engine = 'recover-last-geometry'
            else:
                poly = fallback_poly
                geometry_status = 'ROI DỰ PHÒNG'
                lane_engine = 'fallback-roi'
        lane_items = build_lane_polygons_smart_v4(frame, poly, lane_count=max(2, int(self.config.lane.lane_count)), include_shoulder=False)
        if road_mask is None:
            road_mask = _v6_mask_from_poly(frame.shape, poly)
    elif roi_mode == 'Làn bán tự động':
        poly = fallback_poly
        road_mask = _v6_mask_from_poly(frame.shape, poly)
        road_conf_score = 0.55
        geometry_status = 'HỖ TRỢ ROI'
        lane_engine = 'sticky-lane-v4'
        lane_items = build_lane_polygons_smart_v4(frame, poly, lane_count=max(2, int(self.config.lane.lane_count)), include_shoulder=bool(self.config.lane.include_shoulder))
    elif roi_mode == 'Tự động chia làn từ ROI':
        poly = fallback_poly
        road_mask = _v6_mask_from_poly(frame.shape, poly)
        road_conf_score = 0.42
        geometry_status = 'CHIA ROI'
        lane_engine = 'roi-split'
        lane_items = tao_lan_duong_tu_roi(poly, lane_count=max(2, int(self.config.lane.lane_count)), include_shoulder=bool(self.config.lane.include_shoulder))
    else:
        poly = fallback_poly
        road_mask = _v6_mask_from_poly(frame.shape, poly)
        road_conf_score = 0.30
        geometry_status = 'ROI THỦ CÔNG'
        lane_engine = 'ROI thủ công'
        lane_items = []

    road_confidence = _v6_confidence_label(float(road_conf_score))
    total_in_roi = 0
    class_counts = {name: 0 for name in VEHICLE_CLASSES}
    lane_counts = {label: 0 for label, _ in lane_items}
    detections = []
    t_sec = self.frame_idx / self.fps_video if self.fps_video > 0 else 0.0

    should_infer = (self.frame_idx % max(1, self.config.detection.frame_stride)) == 0
    if should_infer:
        self.last_inference_boxes = []
        if self.model is not None:
            try:
                device = 'cuda:0' if self.config.detection.use_gpu and CUDA_AVAILABLE else 'cpu'
                res = self.model.predict(frame, imgsz=self.config.detection.imgsz, conf=self.config.detection.conf_th, device=device, half=bool(self.config.detection.use_gpu and CUDA_AVAILABLE), verbose=False)[0]
                if res.boxes is not None and res.boxes.xyxy is not None:
                    xyxy = res.boxes.xyxy.cpu().numpy()
                    cls = res.boxes.cls.cpu().numpy()
                    confs = res.boxes.conf.cpu().numpy()
                    for box, cls_id, confv in zip(xyxy, cls, confs):
                        raw_name = self.name_map.get(int(cls_id), str(cls_id))
                        name = chuan_hoa_ten_xe(raw_name)
                        if name is None:
                            continue
                        x1, y1, x2, y2 = map(int, box)
                        ax, ay = _v6_bottom_anchor_point(x1, y1, x2, y2, lift_px=4)
                        lane_label = None
                        if lane_items:
                            in_roi, lane_label = kiem_tra_diem_trong_lan_duong((ax, ay), lane_items)
                        else:
                            in_roi = kiem_tra_diem_trong_da_giac((ax, ay), poly)
                        if in_roi:
                            total_in_roi += 1
                            class_counts[name] += 1
                            if lane_label is not None:
                                lane_counts[lane_label] = lane_counts.get(lane_label, 0) + 1
                            if self.heatmap_accumulator is not None:
                                cv2.circle(self.heatmap_accumulator, (ax, ay), 12, 1.0, -1)
                        detections.append({
                            'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2,
                            'name': name, 'confv': float(confv), 'ax': ax, 'ay': ay,
                            'in_roi': in_roi, 'lane_label': lane_label,
                        })
            except Exception as e:
                self.them_nhat_ky(f'[WARN] Lỗi dự đoán YOLO: {e}')

    lane_speed_map, slow_alert_count = _v9_update_tracks(self, detections, t_sec, frame.shape)

    self.last_inference_boxes = []
    for det in detections:
        color = (0, 255, 102) if det.get('in_roi') else (130, 130, 130)
        if det.get('slow_alert'):
            color = (64, 64, 255)
        self.last_inference_boxes.append((
            det['x1'], det['y1'], det['x2'], det['y2'], det['name'], det['confv'], color,
            det['ax'], det['ay'], det['in_roi'], det.get('lane_label'), det.get('speed_kmh', 0.0),
            det.get('slow_alert', False), det.get('history', [])
        ))

    self.vehicle_history.append(total_in_roi)
    avg_vehicles = round(sum(self.vehicle_history) / max(1, len(self.vehicle_history))) if self.vehicle_history else 0
    density, vsl_speed, traffic_state, reason = tinh_vsl_theo_ngu_canh(avg_vehicles, class_counts, self.config.vsl)
    sudden_increase = (avg_vehicles - self.prev_avg_vehicles) >= self.sudden_increase_threshold
    self.prev_avg_vehicles = avg_vehicles
    priority = tinh_muc_do_uu_tien(density, traffic_state, self.config.vsl.weather, self.config.vsl.incident, sudden_increase, vsl_speed)

    if sudden_increase:
        self.warning_count += 1
        self.them_su_kien('ALERT', f'Mật độ tăng đột biến: trung bình={avg_vehicles}', t_sec)
        self.luu_anh_su_kien(frame, 'sudden_density', t_sec)

    if self.last_state != traffic_state:
        self.them_su_kien('STATE', f'Trạng thái giao thông chuyển thành {traffic_state}', t_sec)
        self.luu_anh_su_kien(frame, f'state_{traffic_state.lower().replace(" ", "_")}', t_sec)
        self.last_state = traffic_state

    if self.last_vsl is None:
        self.last_vsl = vsl_speed
    elif abs(vsl_speed - self.last_vsl) >= 10:
        self.them_su_kien('VSL', f'VSL thay đổi từ {self.last_vsl} đến {vsl_speed}', t_sec)
        self.luu_anh_su_kien(frame, f'vsl_{vsl_speed}', t_sec)
        self.last_vsl = vsl_speed

    if self.last_priority != priority:
        self.them_su_kien('PRIORITY', f'Mức ưu tiên chuyển thành {priority}', t_sec)
        if priority in ('Cần can thiệp', 'Khẩn cấp'):
            self.luu_anh_su_kien(frame, f'priority_{priority.lower().replace(" ", "_")}', t_sec)
        self.last_priority = priority

    if self.config.display.show_heatmap and self.heatmap_accumulator is not None and np.max(self.heatmap_accumulator) > 0:
        heat_norm = cv2.normalize(self.heatmap_accumulator, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        heat_color = cv2.applyColorMap(heat_norm, cv2.COLORMAP_JET)
        frame = cv2.addWeighted(frame, 0.82, heat_color, 0.18, 0)

    if show_road_mask and road_mask is not None:
        _v6_draw_road_mask(frame, road_mask, alpha=0.15 if overlay_mode == 'Trình chiếu' else 0.10)

    if self.config.display.show_roi:
        if overlay_mode == 'Gỡ lỗi':
            ve_vung_giam_sat(frame, poly, alpha=0.05 if show_road_mask else 0.12)
        else:
            cv2.polylines(frame, [poly.astype(np.int32)], True, (0, 214, 255), 2, cv2.LINE_AA)

    if lane_items and self.config.lane.draw_lanes:
        if show_lane_color_state:
            _v9_draw_lane_state_polygons(frame, lane_items, lane_counts, lane_speed_map, overlay_mode=overlay_mode)
        else:
            _v6_draw_lane_polygons(frame, lane_items, overlay_mode=overlay_mode)

    if show_vehicle_trails:
        _v9_draw_trails(frame, detections)

    if self.config.display.show_boxes:
        for x1, y1, x2, y2, name, confv, color, ax, ay, in_roi, lane_label, speed_kmh, slow_alert, history in self.last_inference_boxes:
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2 if in_roi else 1)
            cv2.circle(frame, (ax, ay), 4 if in_roi else 2, (0, 255, 255) if in_roi else color, -1)
            label = f'{name} {confv:.2f}'
            if show_lane_speed and speed_kmh > 1.0:
                label += f' | {int(round(speed_kmh))}km/h'
            if slow_alert:
                label += ' | STHẤP'
            elif (not minimal_labels) and lane_label:
                label += f' | {_lane_short_label(lane_label)}'
            cv2.putText(frame, label, (x1, max(24, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)

    lane_speed_text = _v9_lane_speed_text(lane_speed_map)
    lane_state_text = _v9_lane_state_text(lane_counts, lane_speed_map)

    if overlay_mode == 'Trình chiếu':
        _v6_draw_chip(frame, f'ROAD {road_confidence}', (18, 40), (22, 163, 74) if road_confidence == 'CAO' else ((217, 119, 6) if road_confidence == 'TRUNG BÌNH' else (220, 38, 38)))
        _v6_draw_chip(frame, geometry_status, (180, 40), (37, 99, 235) if 'LOCKED' in geometry_status else ((217, 119, 6) if 'RECOVER' in geometry_status or 'ASSIST' in geometry_status else (220, 38, 38)))
        if show_slow_alerts and slow_alert_count > 0:
            _v6_draw_chip(frame, f'SLOW ALERTS {slow_alert_count}', (360, 40), (220, 38, 38))
    else:
        _v6_draw_chip(frame, f'ROAD CONFIDENCE: {road_confidence}', (18, 40), (15, 118, 110))
        _v6_draw_chip(frame, f'GEOMETRY: {geometry_status}', (260, 40), (59, 130, 246))
        _v6_draw_chip(frame, f'ENGINE: {lane_engine}', (18, 82), (88, 28, 135))
        if show_lane_speed and lane_speed_text != '-':
            _v6_draw_chip(frame, f'LANE SPEED {lane_speed_text}', (18, 124), (22, 163, 74))
        if show_slow_alerts and slow_alert_count > 0:
            _v6_draw_chip(frame, f'SLOW ALERTS {slow_alert_count}', (18, 166), (220, 38, 38))

    lane_counts_text = ' | '.join([f'{_lane_short_label(k)}:{v}' for k, v in lane_counts.items()]) if lane_counts else '-'
    slow_alert_text = f'{slow_alert_count} active' if slow_alert_count > 0 else 'Không'
    self.last_stats = {
        'vehicles_in_roi': total_in_roi,
        'avg_vehicles': avg_vehicles,
        'density': density,
        'traffic_state': traffic_state,
        'suggested_vsl': vsl_speed,
        'priority': priority,
        'sudden_increase': sudden_increase,
        'reason': f'{reason} | chế độ={roi_mode} | engine={lane_engine}',
        'class_counts': class_counts,
        'lane_counts': lane_counts,
        'lane_counts_text': lane_counts_text,
        'lane_speed_text': lane_speed_text,
        'lane_state_text': lane_state_text,
        'slow_alert_count': slow_alert_count,
        'slow_alert_text': slow_alert_text,
        'fps_est': round(self.fps_est, 1),
        'warning_count': self.warning_count,
        'snapshot_count': self.snapshot_count,
        'event_count': self.event_count,
        'summary_html_path': str(self.summary_html_path),
        'road_confidence': road_confidence,
        'geometry_status': geometry_status,
        'lane_engine': lane_engine,
        'overlay_mode': overlay_mode,
        'road_conf_score': round(float(road_conf_score), 2),
    }
    self.statsReady.emit(self.last_stats)

    try:
        with open(self.csv_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                self.frame_idx, round(t_sec, 2), total_in_roi, avg_vehicles, density,
                traffic_state, self.config.vsl.weather, self.config.vsl.incident,
                self.config.vsl.control_mode, vsl_speed, priority, sudden_increase,
                class_counts.get('car', 0), class_counts.get('motorcycle', 0),
                class_counts.get('bus', 0), class_counts.get('truck', 0),
                class_counts.get('bicycle', 0), reason
            ])
    except Exception:
        pass

    return frame


GiaoDienChinh.tao_trang_bao_cao = _v9_build_view_page
GiaoDienChinh.tao_khu_giam_sat = _v9_build_monitoring_area
GiaoDienChinh._gan_trang_thai_ban_dau = _v9_bind_initial_state
GiaoDienChinh.bat_tat_dieu_khien_khi_chay = _v9_set_controls_enabled_for_runtime
GiaoDienChinh.update_ui_from_stats = _v9_update_ui_from_stats
XuLyVideo.xu_ly_khung_hinh = _videoworker_process_frame_v9




# =========================================================
# V9.1 RUNTIME + PREVIEW FIX
# - Fix missing `re` import for lane sorting helpers
# - Replace ugly black empty preview with neutral placeholder
# - Keep preview dark only when real frames are shown
# =========================================================

def _v91_set_preview_placeholder(self, message=None):
    try:
        if message is None:
            if getattr(self, 'video_path', None):
                message = 'Video đã được chọn. Nhấn Bắt đầu phân tích để bắt đầu xem preview.'
            else:
                message = 'Canvas preview sẽ hiển thị tại đây sau khi chọn video và chạy phân tích.'
        self.video_label.clear()
        self.video_label.setText(message)
        self.video_label.setAlignment(QtCore.Qt.AlignCenter)
        self.video_label.setStyleSheet(
            'background:qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #f8fbff, stop:1 #eef4fb); '
            'border:1px solid #d9e6f3; border-radius:18px; color:#64748b; font-weight:700; '
            'padding:24px;'
        )
    except Exception:
        pass


def _v91_set_preview_live_style(self):
    try:
        self.video_label.setStyleSheet(
            'background-color:#081120; border:1px solid #d9e6f3; border-radius:18px; '
            'color:#cbd5e1; font-weight:700;'
        )
    except Exception:
        pass


_orig_v91_build_monitoring_area = GiaoDienChinh.tao_khu_giam_sat
_orig_v91_bind_initial_state = GiaoDienChinh._gan_trang_thai_ban_dau
_orig_v91_finalize_worker_ui = getattr(GiaoDienChinh, '_finalize_worker_ui', None)
_orig_v91_on_open_video = getattr(GiaoDienChinh, 'on_open_video', None)
_orig_v91_show_frame = GiaoDienChinh.show_frame


def _v91_build_monitoring_area(self):
    right = _orig_v91_build_monitoring_area(self)
    try:
        _v91_set_preview_placeholder(self)
    except Exception:
        pass
    return right


def _v91_bind_initial_state(self):
    _orig_v91_bind_initial_state(self)
    try:
        _v91_set_preview_placeholder(self)
    except Exception:
        pass


def _v91_finalize_worker_ui(self):
    if callable(_orig_v91_finalize_worker_ui):
        _orig_v91_finalize_worker_ui(self)
    try:
        _v91_set_preview_placeholder(self)
    except Exception:
        pass


def _v91_on_open_video(self):
    if callable(_orig_v91_on_open_video):
        _orig_v91_on_open_video(self)
    try:
        _v91_set_preview_placeholder(self)
    except Exception:
        pass


def _v91_show_frame(self, qimg: QtGui.QImage):
    try:
        _v91_set_preview_live_style(self)
    except Exception:
        pass
    return _orig_v91_show_frame(self, qimg)


GiaoDienChinh.tao_khu_giam_sat = _v91_build_monitoring_area
GiaoDienChinh._gan_trang_thai_ban_dau = _v91_bind_initial_state
GiaoDienChinh._finalize_worker_ui = _v91_finalize_worker_ui
GiaoDienChinh.on_open_video = _v91_on_open_video
GiaoDienChinh.show_frame = _v91_show_frame



# =========================================================
# V9.2 LAYOUT / VIDEO CANVAS CLEANUP PATCH
# Goals:
# - remove black empty area in center/module and around preview
# - keep video area readable and system insight below it
# - make right monitoring column scroll runly on shorter screens
# =========================================================
_orig_build_module_stack_v92 = GiaoDienChinh.tao_chong_trang_chuc_nang
_orig_build_monitoring_area_v92 = GiaoDienChinh.tao_khu_giam_sat
_orig_show_frame_v92 = GiaoDienChinh.show_frame


def _v92_apply_light_bg(widget, color="#eef4fb"):
    if widget is None:
        return
    try:
        widget.setAttribute(QtCore.Qt.WA_StyledBackground, True)
    except Exception:
        pass
    try:
        widget.setStyleSheet((widget.styleSheet() or "") + f"; background:{color};")
    except Exception:
        pass
    try:
        pal = widget.palette()
        pal.setColor(QtGui.QPalette.Window, QtGui.QColor(color))
        widget.setPalette(pal)
        widget.setAutoFillBackground(True)
    except Exception:
        pass


def _v92_wrap_page(page: QtWidgets.QWidget, use_scroll: bool = True):
    host = QtWidgets.QWidget()
    _v92_apply_light_bg(host, "#eef4fb")
    host_layout = QtWidgets.QVBoxLayout(host)
    host_layout.setContentsMargins(0, 0, 0, 0)
    host_layout.setSpacing(0)
    _v92_apply_light_bg(page, "#eef4fb")
    try:
        if page.layout() is not None:
            page.layout().setSizeConstmưat(QtWidgets.QLayout.SetMinimumSize)
    except Exception:
        pass
    host_layout.addWidget(page)
    filler = QtWidgets.QWidget()
    filler.setMinimumHeight(12)
    _v92_apply_light_bg(filler, "#eef4fb")
    host_layout.addWidget(filler)
    host_layout.addStretch(1)

    if not use_scroll:
        return host

    scroll = QtWidgets.QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
    scroll.setStyleSheet(
        "QScrollArea { background:#eef4fb; border:none; } "
        "QScrollArea > QWidget > QWidget { background:#eef4fb; }"
    )
    _v92_apply_light_bg(scroll.viewport(), "#eef4fb")
    scroll.setWidget(host)
    return scroll


def _v92_build_module_stack(self):
    wrap = QtWidgets.QWidget()
    _v92_apply_light_bg(wrap, "#eef4fb")
    out = QtWidgets.QVBoxLayout(wrap)
    out.setContentsMargins(0, 0, 0, 0)
    out.setSpacing(0)
    self.stack = QtWidgets.QStackedWidget()
    _v92_apply_light_bg(self.stack, "#eef4fb")
    pages = [
        self.tao_trang_khoi_dong_nhanh(),
        self.tao_trang_phien_lam_viec(),
        self.tao_trang_nhan_dien(),
        self.tao_trang_roi(),
        self.tao_trang_vsl(),
        self.tao_trang_bao_cao(),
    ]
    # short pages: avoid unnecessary scroll viewport artifacts
    short_page_indices = {0, 1, 2}
    for idx, page in enumerate(pages):
        self.stack.addWidget(_v92_wrap_page(page, use_scroll=(idx not in short_page_indices)))
    out.addWidget(self.stack)
    return wrap


def _v92_build_monitoring_area(self):
    content = _orig_build_monitoring_area_v92(self)
    _v92_apply_light_bg(content, "#eef4fb")
    try:
        content.layout().setSpacing(18)
    except Exception:
        pass

    # make preview canvas visually lighter outside the actual video image
    try:
        self.video_label.setAlignment(QtCore.Qt.AlignCenter)
        self.video_label.setMinimumHeight(420)
        self.video_label.setMaximumHeight(620)
        self.video_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.video_label.setStyleSheet(
            'background:#eef4fb; border:1px solid #d9e6f3; border-radius:18px; color:#64748b; font-weight:700;'
        )
    except Exception:
        pass

    # separate the insight panel from the video panel so it never looks like it covers the frame
    try:
        lay = content.layout()
        if lay is not None and lay.count() >= 3:
            video_panel = lay.itemAt(1).widget()
            insight = lay.itemAt(2).widget()
            if video_panel is not None:
                video_panel.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Maximum)
            if insight is not None:
                insight.setContentsMargins(0, 10, 0, 0)
                insight.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Maximum)
                try:
                    g = insight.layout()
                    if g is not None:
                        g.setContentsMargins(18, 18, 18, 16)
                        g.setVerticalSpacing(12)
                except Exception:
                    pass
    except Exception:
        pass

    # wrap the whole right column in a scroll area so short screens do not compress the video section
    scroll = QtWidgets.QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
    scroll.setStyleSheet(
        "QScrollArea { background:#eef4fb; border:none; } "
        "QScrollArea > QWidget > QWidget { background:#eef4fb; }"
    )
    _v92_apply_light_bg(scroll.viewport(), "#eef4fb")
    scroll.setWidget(content)
    return scroll


def _v92_show_frame(self, qimg: QtGui.QImage):
    try:
        pix = QtGui.QPixmap.fromImage(qimg)
        if pix.isNull():
            return
        # keep the canvas background light to avoid ugly black empty bars around the scaled video
        self.video_label.setStyleSheet(
            'background:#eef4fb; border:1px solid #d9e6f3; border-radius:18px; color:#64748b; font-weight:700;'
        )
    except Exception:
        pass
    return _orig_show_frame_v92(self, qimg)


GiaoDienChinh.tao_chong_trang_chuc_nang = _v92_build_module_stack
GiaoDienChinh.tao_khu_giam_sat = _v92_build_monitoring_area
GiaoDienChinh.show_frame = _v92_show_frame



# =========================================================
# V10 BUTTON COLOR RESTORE + SAFE LIGHT LAYOUT PATCH
# - Keep the light layout without black voids
# - Restore explicit button colors for session controls
# - Avoid parent stylesheet background leakage into child buttons
# =========================================================

_orig_v10_build_session_page = GiaoDienChinh.tao_trang_phien_lam_viec
_orig_v10_sync_running_state = GiaoDienChinh.dong_bo_trang_thai_chay
_orig_v10_build_module_stack = GiaoDienChinh.tao_chong_trang_chuc_nang
_orig_v10_build_monitoring_area = GiaoDienChinh.tao_khu_giam_sat
_orig_v10_show_frame = GiaoDienChinh.show_frame


def _v10_palette_fill(widget, color="#eef4fb"):
    if widget is None:
        return
    try:
        widget.setAttribute(QtCore.Qt.WA_StyledBackground, False)
    except Exception:
        pass
    try:
        pal = widget.palette()
        pal.setColor(QtGui.QPalette.Window, QtGui.QColor(color))
        pal.setColor(QtGui.QPalette.Base, QtGui.QColor(color))
        widget.setPalette(pal)
        widget.setAutoFillBackground(True)
    except Exception:
        pass


def _v10_button_styles():
    return {
        "secondary": """
            QPushButton {
                background:#ffffff;
                color:#0f172a;
                border:1px solid #cbd5e1;
                border-radius:12px;
                padding:10px 16px;
                font-weight:700;
                min-height:18px;
            }
            QPushButton:hover { background:#f8fafc; }
            QPushButton:disabled {
                background:#ffffff;
                color:#94a3b8;
                border:1px solid #d1d5db;
            }
        """,
        "warning": """
            QPushButton {
                background:#facc15;
                color:#111827;
                border:none;
                border-radius:12px;
                padding:10px 16px;
                font-weight:800;
                min-height:18px;
            }
            QPushButton:hover { background:#eab308; }
            QPushButton:disabled {
                background:#fde68a;
                color:#92400e;
                border:none;
            }
        """,
        "danger": """
            QPushButton {
                background:#ef4444;
                color:white;
                border:none;
                border-radius:12px;
                padding:10px 16px;
                font-weight:800;
                min-height:18px;
            }
            QPushButton:hover { background:#dc2626; }
            QPushButton:disabled {
                background:#fecaca;
                color:#991b1b;
                border:none;
            }
        """,
        "success": """
            QPushButton {
                background:#10b981;
                color:white;
                border:none;
                border-radius:12px;
                padding:10px 16px;
                font-weight:800;
                min-height:18px;
            }
            QPushButton:hover { background:#059669; }
            QPushButton:disabled {
                background:#bbf7d0;
                color:#166534;
                border:none;
            }
        """,
    }


def _v10_apply_session_button_styles(self):
    styles = _v10_button_styles()
    button_specs = [
        (getattr(self, 'btn_open_video', None), 'SecondaryBtn', styles['secondary']),
        (getattr(self, 'btn_pause', None), 'SecondaryBtn', styles['secondary']),
        (getattr(self, 'btn_open_output', None), 'SecondaryBtn', styles['secondary']),
        (getattr(self, 'btn_open_latest', None), 'SecondaryBtn', styles['secondary']),
        (getattr(self, 'btn_logout', None), 'SecondaryBtn', styles['secondary']),
        (getattr(self, 'btn_start', None), 'WarningBtn', styles['warning']),
        (getattr(self, 'btn_stop', None), 'DangerBtn', styles['danger']),
        (getattr(self, 'btn_export', None), 'SuccessBtn', styles['success']),
    ]
    for btn, obj_name, style in button_specs:
        if btn is None:
            continue
        try:
            btn.setObjectName(obj_name)
        except Exception:
            pass
        try:
            btn.setStyleSheet(style)
        except Exception:
            pass
        try:
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.update()
        except Exception:
            pass


def _v10_build_session_page(self):
    page = _orig_v10_build_session_page(self)
    _v10_apply_session_button_styles(self)
    return page


def _v10_sync_running_state(self, running: bool):
    _orig_v10_sync_running_state(self, running)
    _v10_apply_session_button_styles(self)


def _v10_wrap_page(page: QtWidgets.QWidget, use_scroll=True):
    host = QtWidgets.QWidget()
    host.setObjectName('V10PageHost')
    _v10_palette_fill(host, '#eef4fb')
    lay = QtWidgets.QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    _v10_palette_fill(page, '#eef4fb')
    lay.addWidget(page)
    filler = QtWidgets.QWidget()
    filler.setFixedHeight(12)
    _v10_palette_fill(filler, '#eef4fb')
    lay.addWidget(filler)
    lay.addStretch(1)
    if not use_scroll:
        return host
    scroll = QtWidgets.QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
    _v10_palette_fill(scroll, '#eef4fb')
    _v10_palette_fill(scroll.viewport(), '#eef4fb')
    scroll.setWidget(host)
    return scroll


def _v10_build_module_stack(self):
    wrap = QtWidgets.QWidget()
    _v10_palette_fill(wrap, '#eef4fb')
    out = QtWidgets.QVBoxLayout(wrap)
    out.setContentsMargins(0, 0, 0, 0)
    out.setSpacing(0)
    self.stack = QtWidgets.QStackedWidget()
    _v10_palette_fill(self.stack, '#eef4fb')
    pages = [
        self.tao_trang_khoi_dong_nhanh(),
        self.tao_trang_phien_lam_viec(),
        self.tao_trang_nhan_dien(),
        self.tao_trang_roi(),
        self.tao_trang_vsl(),
        self.tao_trang_bao_cao(),
    ]
    short_page_indices = {0, 1, 2}
    for idx, page in enumerate(pages):
        self.stack.addWidget(_v10_wrap_page(page, use_scroll=(idx not in short_page_indices)))
    out.addWidget(self.stack)
    return wrap


def _v10_build_monitoring_area(self):
    content = _orig_v10_build_monitoring_area(self)
    _v10_palette_fill(content, '#eef4fb')
    try:
        self.video_label.setAlignment(QtCore.Qt.AlignCenter)
        self.video_label.setMinimumHeight(420)
        self.video_label.setMaximumHeight(620)
        self.video_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        # keep preview light when there is no frame rendered yet
        if self.video_label.pixmap() is None or self.video_label.pixmap().isNull():
            self.video_label.setStyleSheet(
                'background:qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #f8fbff, stop:1 #eef4fb); '
                'border:1px solid #d9e6f3; border-radius:18px; color:#64748b; font-weight:700; padding:24px;'
            )
    except Exception:
        pass
    scroll = QtWidgets.QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
    _v10_palette_fill(scroll, '#eef4fb')
    _v10_palette_fill(scroll.viewport(), '#eef4fb')
    scroll.setWidget(content)
    return scroll


def _v10_show_frame(self, qimg: QtGui.QImage):
    try:
        pix = QtGui.QPixmap.fromImage(qimg)
        if pix.isNull():
            return
        # light canvas around the scaled image; no ugly black block
        self.video_label.setStyleSheet(
            'background:#eef4fb; border:1px solid #d9e6f3; border-radius:18px; color:#64748b; font-weight:700;'
        )
    except Exception:
        pass
    return _orig_v10_show_frame(self, qimg)


GiaoDienChinh.tao_trang_phien_lam_viec = _v10_build_session_page
GiaoDienChinh.dong_bo_trang_thai_chay = _v10_sync_running_state
GiaoDienChinh.tao_chong_trang_chuc_nang = _v10_build_module_stack
GiaoDienChinh.tao_khu_giam_sat = _v10_build_monitoring_area
GiaoDienChinh.show_frame = _v10_show_frame

if False and __name__ == "__main__":
    main()



# =========================================================
# V10 MINI BIRD-EYE RESTORE
# - restore mini bird-eye lane map in current final pipeline
# =========================================================

def _v10_extract_detections_from_last_boxes(self):
    detections = []
    for item in getattr(self, 'last_inference_boxes', []) or []:
        try:
            if len(item) >= 14:
                x1, y1, x2, y2, name, confv, color, ax, ay, in_roi, lane_label, speed_kmh, slow_alert, history = item[:14]
                detections.append({
                    'x1': int(x1), 'y1': int(y1), 'x2': int(x2), 'y2': int(y2),
                    'ax': int(ax), 'ay': int(ay), 'in_roi': bool(in_roi),
                    'lane_label': lane_label, 'speed_kmh': float(speed_kmh or 0.0),
                    'slow_alert': bool(slow_alert), 'history': history or [],
                })
            elif len(item) >= 11:
                x1, y1, x2, y2, name, confv, color, ax, ay, in_roi, lane_label = item[:11]
                detections.append({
                    'x1': int(x1), 'y1': int(y1), 'x2': int(x2), 'y2': int(y2),
                    'ax': int(ax), 'ay': int(ay), 'in_roi': bool(in_roi),
                    'lane_label': lane_label, 'speed_kmh': 0.0,
                    'slow_alert': False, 'history': [],
                })
        except Exception:
            continue
    return detections


def _v10_rebuild_lane_items(self, frame):
    h, w = frame.shape[:2]
    rc = self.config.roi
    fallback_poly = tao_da_giac_roi(w, h, rc.top_center_x, rc.bottom_center_x, rc.bottom_width, rc.top_width, rc.height, rc.bottom_y)
    roi_mode = str(getattr(self.config.lane, 'roi_mode', 'Tự nhận dạng mặt đường'))
    poly = fallback_poly
    lane_items = []
    if roi_mode == 'Tự nhận dạng mặt đường':
        auto_poly = getattr(self, '_auto_poly_prev', None)
        poly = auto_poly.copy() if isinstance(auto_poly, np.ndarray) else fallback_poly
        lane_items = build_lane_polygons_smart_v4(
            frame,
            poly,
            lane_count=max(2, int(self.config.lane.lane_count)),
            include_shoulder=False,
        )
    elif roi_mode == 'Làn bán tự động':
        lane_items = build_lane_polygons_smart_v4(
            frame,
            poly,
            lane_count=max(2, int(self.config.lane.lane_count)),
            include_shoulder=bool(self.config.lane.include_shoulder),
        )
    elif roi_mode == 'Tự động chia làn từ ROI':
        lane_items = tao_lan_duong_tu_roi(
            poly,
            lane_count=max(2, int(self.config.lane.lane_count)),
            include_shoulder=bool(self.config.lane.include_shoulder),
        )
    return poly, lane_items


def _v10_lane_speed_map_from_runtime(self, t_sec: float):
    lane_speed_map = {}
    tracks = getattr(self, '_lane_tracks_v9', {}) or {}
    for tr in tracks.values():
        try:
            if (t_sec - float(tr.get('t', t_sec))) > 0.9:
                continue
            lane = tr.get('lane')
            if not lane:
                continue
            speed = float(tr.get('speed', 0.0))
            if speed <= 0.5:
                continue
            lane_speed_map.setdefault(lane, []).append(speed)
        except Exception:
            continue
    return {k: (sum(v) / max(1, len(v))) for k, v in lane_speed_map.items() if v}


def _v10_draw_mini_birdeye(frame, lane_items, detections, lane_counts, lane_speed_map):
    if frame is None or not lane_items:
        return
    h, w = frame.shape[:2]
    margin = 16
    box_w = max(180, min(260, int(w * 0.19)))
    box_h = max(110, min(170, int(h * 0.26)))
    x0 = margin
    y0 = 64
    if y0 + box_h > h - 12:
        y0 = max(10, h - box_h - 12)

    x1 = min(w - 10, x0 + box_w)
    y1 = min(h - 10, y0 + box_h)
    box_w = x1 - x0
    box_h = y1 - y0
    if box_w < 120 or box_h < 80:
        return

    overlay = frame.copy()
    cv2.rectangle(overlay, (x0, y0), (x1, y1), (22, 26, 32), -1)
    cv2.rectangle(frame, (x0, y0), (x1, y1), (180, 180, 180), 1)
    cv2.addWeighted(overlay, 0.72, frame, 0.28, 0, frame)

    cv2.putText(frame, 'SO DO LAN', (x0 + 10, y0 + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (245, 245, 245), 1, cv2.LINE_AA)

    labels = [label for label, _ in lane_items]
    labels = _v9_sorted_lane_labels(labels)
    if not labels:
        return

    lane_lookup = {label: poly for label, poly in lane_items}
    inner_x0 = x0 + 12
    inner_y0 = y0 + 28
    inner_x1 = x1 - 12
    inner_y1 = y1 - 14
    inner_w = max(40, inner_x1 - inner_x0)
    inner_h = max(40, inner_y1 - inner_y0)
    col_w = inner_w / max(1, len(labels))

    for idx, label in enumerate(labels):
        lx0 = int(round(inner_x0 + idx * col_w))
        lx1 = int(round(inner_x0 + (idx + 1) * col_w))
        state = _v9_lane_state_from_metrics(lane_counts.get(label, 0), lane_speed_map.get(label))
        color = _v9_color_for_lane_state(state)
        lane_overlay = frame.copy()
        cv2.rectangle(lane_overlay, (lx0, inner_y0), (lx1, inner_y1), color, -1)
        cv2.addWeighted(lane_overlay, 0.22, frame, 0.78, 0, frame)
        cv2.rectangle(frame, (lx0, inner_y0), (lx1, inner_y1), (235, 235, 235), 1)
        short = _lane_short_label(label)
        count = int(lane_counts.get(label, 0))
        cv2.putText(frame, f'{short}:{count}', (lx0 + 4, y1 - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1, cv2.LINE_AA)

        poly = lane_lookup.get(label)
        if poly is None:
            continue
        px_min = int(np.min(poly[:, 0]))
        px_max = int(np.max(poly[:, 0]))
        py_min = int(np.min(poly[:, 1]))
        py_max = int(np.max(poly[:, 1]))
        py_span = max(1, py_max - py_min)
        px_span = max(1, px_max - px_min)

        for det in detections:
            if not det.get('in_roi') or det.get('lane_label') != label:
                continue
            ax = int(det.get('ax', 0))
            ay = int(det.get('ay', 0))
            x_ratio = float(np.clip((ax - px_min) / px_span, 0.1, 0.9))
            y_ratio = float(np.clip((ay - py_min) / py_span, 0.0, 1.0))
            bx = int(lx0 + x_ratio * (lx1 - lx0))
            by = int(inner_y0 + y_ratio * inner_h)
            dot_color = (255, 255, 255)
            if det.get('slow_alert'):
                dot_color = (80, 80, 255)
            elif float(det.get('speed_kmh', 0.0) or 0.0) > 0:
                dot_color = (255, 245, 120)
            cv2.circle(frame, (bx, by), 3, dot_color, -1, cv2.LINE_AA)
            cv2.circle(frame, (bx, by), 3, (20, 20, 20), 1, cv2.LINE_AA)


def _v10_build_view_page(self):
    page = _orig_build_view_page_v10(self)
    if not hasattr(self.config.display, 'show_mini_birdeye'):
        self.config.display.show_mini_birdeye = True
    c_birdeye = KhungNoiDung('Sơ đồ làn thu nhỏ', 'Khôi phục sơ đồ làn thu nhỏ trực tiếp trên canvas để quan sát phân bố phương tiện theo làn.')
    self.chk_show_mini_birdeye = QtWidgets.QCheckBox('Hiển thị sơ đồ làn thu nhỏ')
    self.chk_show_mini_birdeye.setChecked(bool(getattr(self.config.display, 'show_mini_birdeye', True)))
    c_birdeye.lay.addWidget(self.chk_show_mini_birdeye)
    page.content.insertWidget(3, c_birdeye)
    return page


def _v10_bind_initial_state(self):
    _orig_bind_initial_state_v10(self)
    if hasattr(self, 'chk_show_mini_birdeye'):
        self.chk_show_mini_birdeye.stateChanged.connect(lambda s: setattr(self.config.display, 'show_mini_birdeye', s == QtCore.Qt.Checked))


def _v10_set_controls_enabled_for_runtime(self, running: bool):
    _orig_set_controls_enabled_for_runtime_v10(self, running)
    if hasattr(self, 'chk_show_mini_birdeye'):
        self.chk_show_mini_birdeye.setEnabled(True)


def _videoworker_process_frame_v10(self, frame):
    frame = _orig_videoworker_process_frame_v10(self, frame)
    try:
        show_mini_birdeye = bool(getattr(self.config.display, 'show_mini_birdeye', True))
        if not show_mini_birdeye:
            return frame
        poly, lane_items = _v10_rebuild_lane_items(self, frame)
        if not lane_items:
            return frame
        detections = _v10_extract_detections_from_last_boxes(self)
        lane_counts = dict(getattr(self, 'last_stats', {}).get('lane_counts', {}) or {})
        t_sec = self.frame_idx / self.fps_video if self.fps_video > 0 else 0.0
        lane_speed_map = _v10_lane_speed_map_from_runtime(self, t_sec)
        _v10_draw_mini_birdeye(frame, lane_items, detections, lane_counts, lane_speed_map)
    except Exception as e:
        try:
            self.them_nhat_ky(f'[WARN] mini bird-eye restore error: {e}')
        except Exception:
            pass
    return frame


_orig_build_view_page_v10 = GiaoDienChinh.tao_trang_bao_cao
_orig_bind_initial_state_v10 = GiaoDienChinh._gan_trang_thai_ban_dau
_orig_set_controls_enabled_for_runtime_v10 = GiaoDienChinh.bat_tat_dieu_khien_khi_chay
_orig_videoworker_process_frame_v10 = XuLyVideo.xu_ly_khung_hinh

GiaoDienChinh.tao_trang_bao_cao = _v10_build_view_page
GiaoDienChinh._gan_trang_thai_ban_dau = _v10_bind_initial_state
GiaoDienChinh.bat_tat_dieu_khien_khi_chay = _v10_set_controls_enabled_for_runtime
XuLyVideo.xu_ly_khung_hinh = _videoworker_process_frame_v10


# =========================================================
# V11 MINI BIRD-EYE RIGHT CORNER + REALISTIC SPEED CALIBRATION
# - ensure this patch runs BEFORE launching main()
# - mini bird-eye is drawn at top-right of the video canvas
# - speed estimate is conservative to avoid unrealistic jumps
# =========================================================

try:
    _orig_v11_app_init = GiaoDienChinh.__init__
    def _v11_app_init(self, session_user: dict):
        _orig_v11_app_init(self, session_user)
        try:
            if not hasattr(self.config.display, 'show_mini_birdeye'):
                self.config.display.show_mini_birdeye = True
            if hasattr(self, 'chk_show_mini_birdeye'):
                self.chk_show_mini_birdeye.setChecked(bool(getattr(self.config.display, 'show_mini_birdeye', True)))
        except Exception:
            pass
    GiaoDienChinh.__init__ = _v11_app_init
except Exception:
    pass


def _v11_draw_mini_birdeye(frame, lane_items, detections, lane_counts, lane_speed_map):
    """Draw a compact bird-eye lane panel at the top-right corner."""
    if frame is None or not lane_items:
        return
    h, w = frame.shape[:2]
    margin = 18
    box_w = max(210, min(320, int(w * 0.25)))
    box_h = max(130, min(210, int(h * 0.30)))
    x1 = w - margin
    y0 = 18
    x0 = max(10, x1 - box_w)
    y1 = min(h - 12, y0 + box_h)
    box_w = x1 - x0
    box_h = y1 - y0
    if box_w < 150 or box_h < 95:
        return

    shadow = frame.copy()
    cv2.rectangle(shadow, (max(0, x0 + 5), max(0, y0 + 6)), (min(w - 1, x1 + 5), min(h - 1, y1 + 6)), (0, 0, 0), -1)
    cv2.addWeighted(shadow, 0.18, frame, 0.82, 0, frame)

    card = frame.copy()
    cv2.rectangle(card, (x0, y0), (x1, y1), (18, 24, 38), -1)
    cv2.addWeighted(card, 0.78, frame, 0.22, 0, frame)
    cv2.rectangle(frame, (x0, y0), (x1, y1), (130, 160, 190), 1, cv2.LINE_AA)

    cv2.putText(frame, 'SO DO LAN', (x0 + 10, y0 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (245, 248, 255), 1, cv2.LINE_AA)
    cv2.putText(frame, 'lane density / speed', (x0 + 10, y0 + 38), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (175, 190, 210), 1, cv2.LINE_AA)

    labels = [label for label, _ in lane_items]
    try:
        labels = _v9_sorted_lane_labels(labels)
    except Exception:
        labels = sorted(labels)
    if not labels:
        return

    lane_lookup = {label: poly for label, poly in lane_items}
    inner_x0 = x0 + 12
    inner_y0 = y0 + 48
    inner_x1 = x1 - 12
    inner_y1 = y1 - 18
    inner_w = max(60, inner_x1 - inner_x0)
    inner_h = max(50, inner_y1 - inner_y0)
    col_w = inner_w / max(1, len(labels))

    for idx, label in enumerate(labels):
        lx0 = int(round(inner_x0 + idx * col_w))
        lx1 = int(round(inner_x0 + (idx + 1) * col_w))
        state = _v9_lane_state_from_metrics(int(lane_counts.get(label, 0)), lane_speed_map.get(label))
        color = _v9_color_for_lane_state(state)

        lane_card = frame.copy()
        cv2.rectangle(lane_card, (lx0, inner_y0), (lx1, inner_y1), color, -1)
        cv2.addWeighted(lane_card, 0.30, frame, 0.70, 0, frame)
        cv2.rectangle(frame, (lx0, inner_y0), (lx1, inner_y1), (210, 220, 235), 1, cv2.LINE_AA)

        short = _lane_short_label(label)
        count = int(lane_counts.get(label, 0))
        speed = lane_speed_map.get(label)
        speed_txt = '-' if speed is None else f'{int(round(float(speed)))}'
        cv2.putText(frame, f'{short}', (lx0 + 5, inner_y0 + 17), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(frame, f'n={count}', (lx0 + 5, inner_y0 + 35), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (240, 245, 255), 1, cv2.LINE_AA)
        cv2.putText(frame, f'{speed_txt}km/h', (lx0 + 5, inner_y1 - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (240, 245, 255), 1, cv2.LINE_AA)

        poly = lane_lookup.get(label)
        if poly is None:
            continue
        px_min = int(np.min(poly[:, 0])); px_max = int(np.max(poly[:, 0]))
        py_min = int(np.min(poly[:, 1])); py_max = int(np.max(poly[:, 1]))
        px_span = max(1, px_max - px_min)
        py_span = max(1, py_max - py_min)

        for det in detections:
            if not det.get('in_roi') or det.get('lane_label') != label:
                continue
            ax = int(det.get('ax', 0)); ay = int(det.get('ay', 0))
            x_ratio = float(np.clip((ax - px_min) / px_span, 0.12, 0.88))
            y_ratio = float(np.clip((ay - py_min) / py_span, 0.02, 0.98))
            bx = int(lx0 + x_ratio * max(1, lx1 - lx0))
            by = int(inner_y0 + y_ratio * inner_h)
            dot = (255, 255, 255)
            if det.get('slow_alert'):
                dot = (70, 85, 255)
            elif float(det.get('speed_kmh', 0.0) or 0.0) > 0:
                dot = (255, 235, 105)
            cv2.circle(frame, (bx, by), 4, dot, -1, cv2.LINE_AA)
            cv2.circle(frame, (bx, by), 4, (12, 16, 24), 1, cv2.LINE_AA)

_v10_draw_mini_birdeye = _v11_draw_mini_birdeye


def _v11_est_speed_kmh(prev_pt, pt, dt, frame_h: int, lane_label=None) -> float:
    """
    Ước lượng tốc độ xe theo chuyển động tâm box.
    Đây là tốc độ ước lượng AI, không thay thế radar/GPS.
    Đã cải thiện:
    - lọc nhảy ID
    - giảm sai số theo phối cảnh
    - hiệu chỉnh theo làn
    - làm mềm tốc độ bất thường
    """
    if dt <= 1e-6:
        return 0.0

    px0, py0 = float(prev_pt[0]), float(prev_pt[1])
    px1, py1 = float(pt[0]), float(pt[1])

    dx = px1 - px0
    dy = py1 - py0

    # Ưu tiên chuyển động dọc đường, giảm ảnh hưởng xe lệch ngang
    disp = ((dx * 0.35) ** 2 + (dy * 1.00) ** 2) ** 0.5

    # Lọc nhảy ID / nhảy box bất thường
    max_jump = max(36.0, float(frame_h) * 0.065)
    if disp > max_jump:
        return 0.0

    y_norm = float(np.clip(py1 / max(1.0, float(frame_h)), 0.0, 1.0))

    # Hệ số mét/pixel theo phối cảnh:
    # gần camera: mét/pixel nhỏ hơn
    # xa camera: mét/pixel lớn hơn
    meters_per_px = 0.030 + 0.170 * ((1.0 - y_norm) ** 1.55)

    # Hiệu chỉnh theo làn
    lane_factor = 1.0
    if lane_label:
        lane_text = str(lane_label).lower()

        if "lane 0" in lane_text:
            lane_factor = 1.05
        elif "lane 1" in lane_text:
            lane_factor = 1.00
        elif "lane 2" in lane_text:
            lane_factor = 0.95
        elif "emergency" in lane_text:
            lane_factor = 0.85

    speed_kmh = (disp / dt) * meters_per_px * 3.6 * lane_factor

    # Lọc tốc độ phi thực tế trên cao tốc
    if speed_kmh < 2:
        return 0.0

    return float(np.clip(speed_kmh, 0.0, 140.0))


_v9_est_speed_kmh = _v11_est_speed_kmh
# =========================================================
# V12 DECISION INTELLIGENCE SUITE
# Adds:
#   1) Digital Twin mini-map polish
#   2) Explainable VSL panel / overlay
#   3) Lane Health Score
#   4) Risk Heat Index
#   5) Adaptive VSL What-if Simulation
# =========================================================


def _v12_priority_score(priority: str) -> int:
    return {
        'Bình thường': 0,
        'Theo dõi': 12,
        'Cần can thiệp': 28,
        'Khẩn cấp': 42,
    }.get(str(priority), 10)


def _v12_density_score(density: str) -> int:
    return {'THẤP': 8, 'TRUNG BÌNH': 22, 'CAO': 38}.get(str(density).upper(), 12)


def _v12_weather_score(weather: str) -> int:
    try:
        # Quy đổi điểm rủi ro thời tiết sang thang Risk Heat Index.
        return int(diem_rui_ro_thoi_tiet(weather) * 8)
    except Exception:
        return 0


def _v12_incident_score(incident: str) -> int:
    return {'Không': 0, 'Nhẹ': 16, 'Nghiêm trọng': 32}.get(str(incident), 0)


def _v12_risk_label(score: int) -> str:
    score = int(np.clip(score, 0, 100))
    if score < 30:
        return 'THẤP'
    if score < 60:
        return 'TRUNG BÌNH'
    if score < 80:
        return 'CAO'
    return 'NGUY KỊCH'


def _v12_risk_color(score: int):
    score = int(np.clip(score, 0, 100))
    if score < 30:
        return (34, 197, 94)
    if score < 60:
        return (250, 204, 21)
    if score < 80:
        return (249, 115, 22)
    return (239, 68, 68)


def _v12_speed_penalty_from_map(speed_map: dict) -> int:
    vals = []
    for v in (speed_map or {}).values():
        try:
            if v is not None and float(v) > 0:
                vals.append(float(v))
        except Exception:
            pass
    if not vals:
        return 8
    avg_speed = sum(vals) / max(1, len(vals))
    if avg_speed < 15:
        return 28
    if avg_speed < 30:
        return 18
    if avg_speed < 45:
        return 8
    return 0


def _v12_lane_health(lane_counts: dict, speed_map: dict, slow_count: int = 0):
    labels = set((lane_counts or {}).keys()) | set((speed_map or {}).keys())
    try:
        labels = _v9_sorted_lane_labels(labels)
    except Exception:
        labels = sorted(labels)
    out = {}
    for label in labels:
        cnt = int((lane_counts or {}).get(label, 0) or 0)
        sp = (speed_map or {}).get(label)
        score = 100
        score -= min(35, cnt * 8)
        if sp is None:
            score -= 8
        else:
            sp = float(sp)
            if sp < 12:
                score -= 34
            elif sp < 25:
                score -= 22
            elif sp < 40:
                score -= 10
        score -= min(18, int(slow_count) * 6)
        score = int(np.clip(score, 0, 100))
        if score >= 76:
            state = 'GOOD'
        elif score >= 51:
            state = 'WATCH'
        elif score >= 31:
            state = 'RISK'
        else:
            state = 'NGUY KỊCH'
        out[label] = {'score': score, 'state': state, 'count': cnt, 'speed': sp}
    return out


def _v12_lane_health_text(health: dict) -> str:
    if not health:
        return '-'
    parts = []
    try:
        labels = _v9_sorted_lane_labels(health.keys())
    except Exception:
        labels = sorted(health.keys())
    for label in labels:
        data = health.get(label, {})
        short = _lane_short_label(label) if '_lane_short_label' in globals() else str(label)
        parts.append(f"{short}:{data.get('score', 0)}/{data.get('state', '-')}")
    return ' | '.join(parts)


def _v12_explain_vsl(stats: dict, speed_map: dict, health: dict, risk_score: int) -> str:
    reasons = []
    density = stats.get('density', 'THẤP')
    priority = stats.get('priority', 'Bình thường')
    slow_count = int(stats.get('slow_alert_count', 0) or 0)
    vsl = int(stats.get('suggested_vsl', 0) or 0)
    avg = int(stats.get('avg_vehicles', 0) or 0)
    if density in ('TRUNG BÌNH', 'CAO'):
        reasons.append(f'mật độ {density.lower()} với trung bình {avg} xe')
    if speed_map:
        low_lanes = []
        for lane, sp in speed_map.items():
            try:
                if sp is not None and float(sp) < 30:
                    low_lanes.append(_lane_short_label(lane) if '_lane_short_label' in globals() else lane)
            except Exception:
                pass
        if low_lanes:
            reasons.append('tốc độ thấp tại ' + ', '.join(low_lanes[:3]))
    if slow_count > 0:
        reasons.append(f'{slow_count} cảnh báo xe chậm/dừng')
    bad_lanes = []
    for lane, item in (health or {}).items():
        if item.get('score', 100) < 55:
            bad_lanes.append(_lane_short_label(lane) if '_lane_short_label' in globals() else lane)
    if bad_lanes:
        reasons.append('sức khỏe làn cần chú ý: ' + ', '.join(bad_lanes[:3]))
    if risk_score >= 70:
        reasons.append(f'Risk Heat Index cao ({risk_score}/100)')
    if priority not in ('Bình thường', None, ''):
        reasons.append(f'mức ưu tiên {priority}')
    if not reasons:
        reasons.append('luồng giao thông ổn định, chưa phát hiện bất thường rõ rệt')
    return f"Đề xuất VSL {vsl} km/h vì " + '; '.join(reasons) + '.'


def _v12_compute_risk(stats: dict, speed_map: dict, lane_health: dict, worker=None) -> int:
    density = stats.get('density', 'THẤP')
    priority = stats.get('priority', 'Bình thường')
    slow_count = int(stats.get('slow_alert_count', 0) or 0)
    avg_count = int(stats.get('avg_vehicles', 0) or 0)
    weather_name = getattr(getattr(getattr(worker, 'config', None), 'vsl', None), 'weather', 'Trời quang')
    incident_name = getattr(getattr(getattr(worker, 'config', None), 'vsl', None), 'incident', 'Không')
    score = 0
    score += _v12_density_score(density)
    score += _v12_priority_score(priority)
    score += min(18, max(0, avg_count - 5) * 2)
    score += min(18, slow_count * 9)
    score += _v12_speed_penalty_from_map(speed_map)
    if lane_health:
        worst = min([int(v.get('score', 100)) for v in lane_health.values()] or [100])
        score += int(np.clip((75 - worst) * 0.45, 0, 25))
    score += _v12_weather_score(weather_name)
    score += _v12_incident_score(incident_name)
    return int(np.clip(score, 0, 100))


def _v12_whatif_vsl(base_count: int, weather: str, incident: str, density_boost: int, cfg: CauHinhVSL):
    tmp_cfg = CauHinhVSL(
        vsl_min=cfg.vsl_min,
        vsl_max=cfg.vsl_max,
        scale_max=cfg.scale_max,
        smoothing_window=cfg.smoothing_window,
        weather=weather,
        incident=incident,
        control_mode='Tự động',
        manual_vsl=cfg.manual_vsl,
    )
    pseudo_count = max(0, int(base_count) + int(density_boost))
    pseudo_classes = {k: 0 for k in VEHICLE_CLASSES}
    pseudo_classes['car'] = max(1, pseudo_count)
    density, speed, state, reason = tinh_vsl_theo_ngu_canh(pseudo_count, pseudo_classes, tmp_cfg)
    risk = int(np.clip(_v12_density_score(density) + _v12_weather_score(weather) + _v12_incident_score(incident) + min(25, density_boost * 3), 0, 100))
    return speed, density, state, risk, reason


def _v12_draw_risk_overlay(frame, risk_score: int, explain_text: str):
    'Clean OpenCV-run Risk Heat Index overlay.\n    OpenCV putText does not render Vietnamese/Unicode reliably, so this canvas\n    overlay intentionally uses short ASCII text only. Full Vietnamese explanation\n    remains available in the Phân tích giao thông panel.\n    '
    if frame is None:
        return
    h, w = frame.shape[:2]
    x0, y0 = 18, max(82, int(h * 0.12))
    box_w, box_h = 392, 118
    x1, y1 = min(w - 18, x0 + box_w), min(h - 18, y0 + box_h)
    if x1 - x0 < 280 or y1 - y0 < 88:
        return

    label = _v12_risk_label(risk_score)
    color = _v12_risk_color(risk_score)

    # Glass card background
    card = frame.copy()
    cv2.rectangle(card, (x0, y0), (x1, y1), (13, 20, 34), -1)
    cv2.addWeighted(card, 0.78, frame, 0.22, 0, frame)
    cv2.rectangle(frame, (x0, y0), (x1, y1), (120, 150, 185), 1, cv2.LINE_AA)

    # Header
    cv2.putText(frame, 'CHI SO RUI RO', (x0 + 14, y0 + 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.58, (238, 242, 255), 2, cv2.LINE_AA)
    score_text = f'{int(np.clip(risk_score, 0, 100)):02d}/100'
    score_size = cv2.getTextSize(score_text, cv2.FONT_HERSHEY_SIMPLEX, 0.64, 2)[0]
    cv2.putText(frame, score_text, (x1 - score_size[0] - 14, y0 + 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.64, color, 2, cv2.LINE_AA)

    # Status pill
    pill_w, pill_h = 92, 24
    pill_x0, pill_y0 = x0 + 14, y0 + 36
    cv2.rectangle(frame, (pill_x0, pill_y0), (pill_x0 + pill_w, pill_y0 + pill_h), color, -1)
    cv2.putText(frame, label, (pill_x0 + 12, pill_y0 + 17),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (10, 18, 32), 2, cv2.LINE_AA)

    # Progress bar
    bar_x0, bar_y0 = x0 + 118, y0 + 42
    bar_x1, bar_y1 = x1 - 14, y0 + 56
    cv2.rectangle(frame, (bar_x0, bar_y0), (bar_x1, bar_y1), (48, 58, 78), -1)
    fill_x = int(bar_x0 + (bar_x1 - bar_x0) * np.clip(risk_score, 0, 100) / 100.0)
    cv2.rectangle(frame, (bar_x0, bar_y0), (fill_x, bar_y1), color, -1)
    cv2.rectangle(frame, (bar_x0, bar_y0), (bar_x1, bar_y1), (105, 125, 155), 1, cv2.LINE_AA)

    # Bottom details: ASCII only to avoid garbled OpenCV text.
    text = str(explain_text or '')
    m = re.search(r'(\d{2,3})\s*km/h', text)
    vsl_text = f'VSL: {m.group(1)} km/h' if m else 'VSL: -- km/h'
    if label == 'THẤP':
        action = 'Luu thong on dinh - tiep tuc giam sat'
    elif label == 'TRUNG BÌNH':
        action = 'Theo doi mat do va toc do lan'
    elif label == 'CAO':
        action = 'Chuan bi can thiep VSL'
    else:
        action = 'Can dieu hanh khan cap'
    cv2.putText(frame, vsl_text, (x0 + 14, y0 + 82),
                cv2.FONT_HERSHEY_SIMPLEX, 0.48, (226, 232, 240), 1, cv2.LINE_AA)
    cv2.putText(frame, action, (x0 + 14, y0 + 104),
                cv2.FONT_HERSHEY_SIMPLEX, 0.43, (190, 205, 225), 1, cv2.LINE_AA)

def _v12_draw_health_on_birdeye(frame, lane_health: dict):
    if not lane_health or frame is None:
        return
    h, w = frame.shape[:2]
    margin = 18
    box_w = max(210, min(320, int(w * 0.25)))
    x1 = w - margin
    x0 = max(10, x1 - box_w)
    y0 = max(156, int(h * 0.12) + 110)
    y1 = min(h - 18, y0 + 78)
    if y1 - y0 < 55:
        return
    card = frame.copy()
    cv2.rectangle(card, (x0, y0), (x1, y1), (18, 24, 38), -1)
    cv2.addWeighted(card, 0.74, frame, 0.26, 0, frame)
    cv2.rectangle(frame, (x0, y0), (x1, y1), (130, 160, 190), 1, cv2.LINE_AA)
    cv2.putText(frame, 'DIEM SUC KHOE LAN', (x0 + 10, y0 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (245, 248, 255), 1, cv2.LINE_AA)
    try:
        labels = _v9_sorted_lane_labels(lane_health.keys())
    except Exception:
        labels = sorted(lane_health.keys())
    if not labels:
        return
    inner_x0, inner_x1 = x0 + 10, x1 - 10
    y = y0 + 42
    col = max(1, len(labels))
    col_w = (inner_x1 - inner_x0) / col
    for idx, label in enumerate(labels):
        data = lane_health.get(label, {})
        score = int(data.get('score', 0))
        short = _lane_short_label(label) if '_lane_short_label' in globals() else str(label)
        color = _v12_risk_color(100 - score)
        lx0 = int(inner_x0 + idx * col_w)
        lx1 = int(inner_x0 + (idx + 1) * col_w) - 5
        cv2.putText(frame, f'{short}', (lx0, y), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (235, 240, 250), 1, cv2.LINE_AA)
        cv2.rectangle(frame, (lx0, y + 8), (lx1, y + 18), (51, 65, 85), -1)
        fill = int(lx0 + max(1, (lx1 - lx0)) * score / 100.0)
        cv2.rectangle(frame, (lx0, y + 8), (fill, y + 18), color, -1)
        cv2.putText(frame, f'{score}', (lx0, y + 34), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (235, 240, 250), 1, cv2.LINE_AA)


try:
    _orig_v12_birdeye = _v10_draw_mini_birdeye
    def _v12_draw_digital_twin(frame, lane_items, detections, lane_counts, lane_speed_map):
        _orig_v12_birdeye(frame, lane_items, detections, lane_counts, lane_speed_map)
        try:
            h, w = frame.shape[:2]
            x = max(10, w - max(210, min(320, int(w * 0.25))) - 18 + 10)
            y = 56
            cv2.putText(frame, 'DIGITAL TWIN', (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (125, 211, 252), 1, cv2.LINE_AA)
        except Exception:
            pass
    _v10_draw_mini_birdeye = _v12_draw_digital_twin
except Exception:
    pass


try:
    _orig_v12_build_monitoring = GiaoDienChinh.tao_khu_giam_sat
    def _v12_build_monitoring_area(self):
        widget = _orig_v12_build_monitoring(self)
        try:
            if hasattr(self, 'lbl_reason') and self.lbl_reason is not None:
                grid = self.lbl_reason.parentWidget().layout()
                self.lbl_risk_heat = QtWidgets.QLabel('Risk Heat Index: -')
                self.lbl_lane_health = QtWidgets.QLabel('Làn Health Score: -')
                self.lbl_explain_vsl = QtWidgets.QLabel('Explainable VSL: -')
                self.lbl_whatif = QtWidgets.QLabel('What-if Simulation: chọn kịch bản ở Điều khiển tốc độ')
                for lb in (self.lbl_risk_heat, self.lbl_lane_health, self.lbl_explain_vsl, self.lbl_whatif):
                    lb.setObjectName('InsightText')
                    lb.setWordWrap(True)
                grid.addWidget(self.lbl_risk_heat, 9, 0, 1, 2)
                grid.addWidget(self.lbl_lane_health, 10, 0, 1, 2)
                grid.addWidget(self.lbl_explain_vsl, 11, 0, 1, 2)
                grid.addWidget(self.lbl_whatif, 12, 0, 1, 2)
            else:
                self.lbl_risk_heat = self.lbl_lane_health = self.lbl_explain_vsl = self.lbl_whatif = None
        except Exception:
            self.lbl_risk_heat = self.lbl_lane_health = self.lbl_explain_vsl = self.lbl_whatif = None
        return widget
    GiaoDienChinh.tao_khu_giam_sat = _v12_build_monitoring_area
except Exception:
    pass


try:
    _orig_v12_build_view = GiaoDienChinh.tao_trang_bao_cao
    def _v12_build_view_page(self):
        page = _orig_v12_build_view(self)
        try:
            for attr, default in (
                ('show_risk_overlay', True),
                ('show_explainable_vsl', True),
                ('show_lane_health_overlay', True),
            ):
                if not hasattr(self.config.display, attr):
                    setattr(self.config.display, attr, default)
            c = KhungNoiDung('Decision Intelligence', 'Các lớp giải thích quyết định AI giúp hệ thống giống trung tâm điều hành ITS hơn.')
            self.chk_show_digital_twin = QtWidgets.QCheckBox('Show Digital Twin Mini-map')
            self.chk_show_risk_overlay = QtWidgets.QCheckBox('Show Risk Heat Index Overlay')
            self.chk_show_explainable_vsl = QtWidgets.QCheckBox('Show Explainable VSL')
            self.chk_show_lane_health_overlay = QtWidgets.QCheckBox('Show Làn Health Score Overlay')
            self.chk_show_digital_twin.setChecked(bool(getattr(self.config.display, 'show_mini_birdeye', True)))
            self.chk_show_risk_overlay.setChecked(True)
            self.chk_show_explainable_vsl.setChecked(True)
            self.chk_show_lane_health_overlay.setChecked(True)
            for w in (self.chk_show_digital_twin, self.chk_show_risk_overlay, self.chk_show_explainable_vsl, self.chk_show_lane_health_overlay):
                c.lay.addWidget(w)
            page.content.insertWidget(0, c)
        except Exception:
            pass
        return page
    GiaoDienChinh.tao_trang_bao_cao = _v12_build_view_page
except Exception:
    pass


try:
    _orig_v12_build_vsl = GiaoDienChinh.tao_trang_vsl
    def _v12_build_vsl_page(self):
        page = _orig_v12_build_vsl(self)
        try:
            c = KhungNoiDung('Adaptive VSL What-if Simulation', 'Thử kịch bản điều hành mà không cần chạy lại video: mưa/sương mù/sự cố/mật độ tăng.')
            self.cbo_whatif_weather = QtWidgets.QComboBox()
            self.cbo_whatif_weather.addItems(DANH_SACH_THOI_TIET_VI)
            self.cbo_whatif_incident = QtWidgets.QComboBox()
            self.cbo_whatif_incident.addItems(['Không', 'Nhẹ', 'Nghiêm trọng'])
            self.sld_whatif_density = ThanhTruotCoNhan('Mật độ Boost', 0, 20, 5)
            self.lbl_whatif_result = QtWidgets.QLabel('What-if: chọn kịch bản để mô phỏng VSL')
            self.lbl_whatif_result.setObjectName('ReportPathLabel')
            self.lbl_whatif_result.setWordWrap(True)
            c.lay.addWidget(QtWidgets.QLabel('Thời tiết scenario'))
            c.lay.addWidget(self.cbo_whatif_weather)
            c.lay.addWidget(QtWidgets.QLabel('Sự cố scenario'))
            c.lay.addWidget(self.cbo_whatif_incident)
            c.lay.addWidget(self.sld_whatif_density)
            c.lay.addWidget(self.lbl_whatif_result)
            page.content.addWidget(c)
        except Exception:
            pass
        return page
    GiaoDienChinh.tao_trang_vsl = _v12_build_vsl_page
except Exception:
    pass


def _v12_refresh_whatif(self):
    try:
        base_count = int(getattr(self, '_last_avg_vehicles_v12', 0) or 0)
        weather = self.cbo_whatif_weather.currentText() if hasattr(self, 'cbo_whatif_weather') else self.config.vsl.weather
        incident = self.cbo_whatif_incident.currentText() if hasattr(self, 'cbo_whatif_incident') else self.config.vsl.incident
        boost = int(self.sld_whatif_density.slider.value()) if hasattr(self, 'sld_whatif_density') else 0
        speed, density, state, risk, reason = _v12_whatif_vsl(base_count, weather, incident, boost, self.config.vsl)
        text = f'What-if → {weather}/{incident}, +{boost} xe: VSL {speed} km/h | {density} | {state} | Risk {risk}/100 | {reason}'
        if hasattr(self, 'lbl_whatif_result'):
            self.lbl_whatif_result.setText(text)
        if hasattr(self, 'lbl_whatif') and self.lbl_whatif is not None:
            self.lbl_whatif.setText('What-if Simulation: ' + text.replace('What-if → ', ''))
    except Exception:
        pass


try:
    _orig_v12_bind = GiaoDienChinh._gan_trang_thai_ban_dau
    def _v12_bind_initial_state(self):
        _orig_v12_bind(self)
        try:
            if hasattr(self, 'chk_show_risk_overlay'):
                self.chk_show_risk_overlay.stateChanged.connect(lambda s: setattr(self.config.display, 'show_risk_overlay', s == QtCore.Qt.Checked))
            if hasattr(self, 'chk_show_explainable_vsl'):
                self.chk_show_explainable_vsl.stateChanged.connect(lambda s: setattr(self.config.display, 'show_explainable_vsl', s == QtCore.Qt.Checked))
            if hasattr(self, 'chk_show_lane_health_overlay'):
                self.chk_show_lane_health_overlay.stateChanged.connect(lambda s: setattr(self.config.display, 'show_lane_health_overlay', s == QtCore.Qt.Checked))
            if hasattr(self, 'chk_show_digital_twin'):
                self.chk_show_digital_twin.stateChanged.connect(lambda s: setattr(self.config.display, 'show_mini_birdeye', s == QtCore.Qt.Checked))
            if hasattr(self, 'cbo_whatif_weather'):
                self.cbo_whatif_weather.currentTextChanged.connect(lambda _: _v12_refresh_whatif(self))
            if hasattr(self, 'cbo_whatif_incident'):
                self.cbo_whatif_incident.currentTextChanged.connect(lambda _: _v12_refresh_whatif(self))
            if hasattr(self, 'sld_whatif_density'):
                self.sld_whatif_density.valueChanged.connect(lambda _: _v12_refresh_whatif(self))
            _v12_refresh_whatif(self)
        except Exception:
            pass
    GiaoDienChinh._gan_trang_thai_ban_dau = _v12_bind_initial_state
except Exception:
    pass


try:
    _orig_v12_set_controls = GiaoDienChinh.bat_tat_dieu_khien_khi_chay
    def _v12_set_controls_enabled_for_runtime(self, running: bool):
        _orig_v12_set_controls(self, running)
        for name in ('chk_show_risk_overlay', 'chk_show_explainable_vsl', 'chk_show_lane_health_overlay', 'chk_show_digital_twin'):
            try:
                if hasattr(self, name):
                    getattr(self, name).setEnabled(True)
            except Exception:
                pass
    GiaoDienChinh.bat_tat_dieu_khien_khi_chay = _v12_set_controls_enabled_for_runtime
except Exception:
    pass


try:
    _orig_v12_update_ui = GiaoDienChinh.update_ui_from_stats
    def _v12_update_ui_from_stats(self, stats: dict):
        _orig_v12_update_ui(self, stats)
        try:
            self._last_avg_vehicles_v12 = int(stats.get('avg_vehicles', 0) or 0)
            risk = int(stats.get('risk_heat_index', 0) or 0)
            risk_label = stats.get('risk_heat_label', _v12_risk_label(risk))
            health_text = stats.get('lane_health_text', '-')
            explain_text = stats.get('explainable_vsl', '-')
            if hasattr(self, 'lbl_risk_heat') and self.lbl_risk_heat is not None:
                self.lbl_risk_heat.setText(f'Risk Heat Index: {risk}/100 • {risk_label}')
            if hasattr(self, 'lbl_lane_health') and self.lbl_lane_health is not None:
                self.lbl_lane_health.setText(f'Lane Health Score: {health_text}')
            if hasattr(self, 'lbl_explain_vsl') and self.lbl_explain_vsl is not None:
                self.lbl_explain_vsl.setText(f'Explainable VSL: {explain_text}')
            _v12_refresh_whatif(self)
        except Exception:
            pass
    GiaoDienChinh.update_ui_from_stats = _v12_update_ui_from_stats
except Exception:
    pass


try:
    _orig_v12_process_frame = XuLyVideo.xu_ly_khung_hinh
    def _v12_process_frame(self, frame):
        frame = _orig_v12_process_frame(self, frame)
        try:
            t_sec = self.frame_idx / self.fps_video if self.fps_video > 0 else 0.0
            try:
                lane_speed_map = _v10_lane_speed_map_from_runtime(self, t_sec)
            except Exception:
                lane_speed_map = getattr(self, '_last_lane_speed_map_v12', {}) or {}
            stats = dict(getattr(self, 'last_stats', {}) or {})
            lane_counts = dict(stats.get('lane_counts', {}) or {})
            slow_count = int(stats.get('slow_alert_count', 0) or 0)
            lane_health = _v12_lane_health(lane_counts, lane_speed_map, slow_count)
            risk_score = _v12_compute_risk(stats, lane_speed_map, lane_health, self)
            risk_label = _v12_risk_label(risk_score)
            explain_text = _v12_explain_vsl(stats, lane_speed_map, lane_health, risk_score)
            health_text = _v12_lane_health_text(lane_health)

            stats.update({
                'lane_health': lane_health,
                'lane_health_text': health_text,
                'risk_heat_index': risk_score,
                'risk_heat_label': risk_label,
                'explainable_vsl': explain_text,
                'digital_twin': 'enabled' if bool(getattr(self.config.display, 'show_mini_birdeye', True)) else 'disabled',
            })
            self.last_stats = stats
            self._last_lane_speed_map_v12 = lane_speed_map

            if bool(getattr(self.config.display, 'show_risk_overlay', True)):
                _v12_draw_risk_overlay(frame, risk_score, explain_text)
            if bool(getattr(self.config.display, 'show_lane_health_overlay', True)):
                _v12_draw_health_on_birdeye(frame, lane_health)
            if bool(getattr(self.config.display, 'show_explainable_vsl', True)) and risk_score >= 60:
                try:
                    _v6_draw_chip(frame, 'EXPLAINABLE VSL ACTIVE', (18, 252), (14, 165, 233))
                except Exception:
                    pass
            try:
                self.statsReady.emit(self.last_stats)
            except Exception:
                pass
        except Exception as e:
            try:
                self.them_nhat_ky(f'[WARN] decision intelligence error: {e}')
            except Exception:
                pass
        return frame
    XuLyVideo.xu_ly_khung_hinh = _v12_process_frame
except Exception:
    pass
# =========================================================
# PATCH ĐA CAMERA - SỬA LỖI on_chon_camera
# DÁN NGAY TRƯỚC: if __name__ == "__main__":
# =========================================================

try:
    CauHinhCamera
except NameError:
    @dataclass
    class CauHinhCamera:
        camera_id: str
        ten_camera: str
        duong_dan_video: str
        vi_tri: str = ""
        kich_hoat: bool = True


class QuanLyCamera:
    def __init__(self):
        video_1 = str(BASE_DIR / "video 1.mp4")
        video_2 = str(BASE_DIR / "video 2.mp4")
        video_3 = str(BASE_DIR / "video3.mp4")
        video_4 = str(BASE_DIR / "video 4.mp4")
        print("[DEBUG CAMERA PATH]", video_1)
        print("[DEBUG EXISTS]", os.path.exists(video_1))

        self.danh_sach_camera = [
            CauHinhCamera("CAM_01", "Camera KM10", video_1, "KM10", True),
            CauHinhCamera("CAM_02", "Camera KM15", video_2, "KM15", True),
            CauHinhCamera("CAM_03", "Camera KM20", video_3, "KM20", True),
            CauHinhCamera("CAM_04", "Camera KM25", video_4, "KM25", False),
        ]   

    def lay_tat_ca(self):
        return self.danh_sach_camera

    def lay_camera_dang_bat(self):
        return [cam for cam in self.danh_sach_camera if cam.kich_hoat]

    def lay_camera_theo_id(self, camera_id):
        for cam in self.danh_sach_camera:
            if cam.camera_id == camera_id:
                return cam
        return None

try:
    MultiCameraWorker
except NameError:
    class MultiCameraWorker(QtCore.QObject):
        frameCameraReady = QtCore.pyqtSignal(str, QtGui.QImage)
        statsCameraReady = QtCore.pyqtSignal(str, dict)
        logCameraReady = QtCore.pyqtSignal(str)

        def __init__(self, danh_sach_camera, config, session_user, parent=None):
            super().__init__(parent)
            self.danh_sach_camera = danh_sach_camera
            self.config = config
            self.session_user = session_user
            self.workers = {}

        def bat_dau(self):
            for cam in self.danh_sach_camera:
                try:
                    worker = XuLyVideo(
                        cam.duong_dan_video,
                        self.config,
                        self.session_user,
                        camera_id=cam.camera_id,
                    )
                except TypeError:
                    worker = XuLyVideo(
                        cam.duong_dan_video,
                        self.config,
                        self.session_user,
                    )
                    worker.camera_id = cam.camera_id

                worker.frameReady.connect(
                    lambda qimg, cid=cam.camera_id: self.frameCameraReady.emit(cid, qimg)
                )
                worker.statsReady.connect(
                    lambda stats, cid=cam.camera_id: self.statsCameraReady.emit(cid, stats)
                )
                worker.logReady.connect(
                    lambda text, cid=cam.camera_id: self.logCameraReady.emit(f"[{cid}] {text}")
                )
                worker.errorReady.connect(
                    lambda err, cid=cam.camera_id: self.logCameraReady.emit(f"[{cid}] LỖI: {err}")
                )

                worker.start()
                self.workers[cam.camera_id] = worker

        def dung(self):
            for worker in self.workers.values():
                try:
                    worker.yeu_cau_dung()
                    worker.dat_tam_dung(False)
                except Exception:
                    pass

            for worker in self.workers.values():
                try:
                    worker.wait(2000)
                except Exception:
                    pass

            self.workers.clear()

        def dang_chay(self):
            return any(worker.isRunning() for worker in self.workers.values())


def _multi_on_chon_camera(self):
    camera_id = self.cbo_camera.currentData()

    if not camera_id:
        self.camera_hien_tai = None
        return

    cam = self.quan_ly_camera.lay_camera_theo_id(camera_id)

    if cam is None:
        return

    self.camera_hien_tai = cam
    self.video_path = cam.duong_dan_video

    self.lbl_video_name.setText(f"Camera: {cam.ten_camera}")
    self.lbl_video_res.setText(f"Vị trí: {cam.vi_tri}")
    self.append_log(f"[CAMERA] Đã chọn {cam.ten_camera} - {cam.vi_tri}")

    self.dong_bo_trang_thai_chay(False)


def _multi_on_start_multi_camera(self):
    if self.multi_worker is not None and self.multi_worker.dang_chay():
        return

    danh_sach_camera = self.quan_ly_camera.lay_camera_dang_bat()

    if not danh_sach_camera:
        QtWidgets.QMessageBox.warning(self, "Lỗi", "Không có camera nào được bật.")
        return

    self.camera_stats = {}
    self.camera_frames = {}
    self.video_label.show()
    self.video_label.clear()
    self.video_label.setText("Đang chạy đa camera...")
    for label in self.camera_labels.values():
         label.deleteLater()

    self.camera_labels = {}

    self.multi_worker = MultiCameraWorker(
        danh_sach_camera=danh_sach_camera,
        config=self.config,
        session_user=self.session_user,
    )

    self.multi_worker.frameCameraReady.connect(self.on_multi_camera_frame)
    self.multi_worker.statsCameraReady.connect(self.on_multi_camera_stats)
    self.multi_worker.logCameraReady.connect(self.append_log)

    self.multi_worker.bat_dau()

    self.lbl_status.setText("Đang chạy đa camera...")
    self.hero_badge_status.setText("TRẠNG THÁI: ĐA CAMERA")
    self.badge_live.setText("TRỰC TUYẾN: ĐA CAMERA")
    self.badge_live.setObjectName("BadgeGreen")
    self.badge_live.style().unpolish(self.badge_live)
    self.badge_live.style().polish(self.badge_live)

    self.append_log("[MULTI-CAMERA] Đã chạy tất cả camera")


def _multi_on_multi_camera_frame(self, camera_id, qimg):
    self.camera_frames[camera_id] = qimg

    items = list(self.camera_frames.items())

    if not items:
        return

    cell_w = 520
    cell_h = 300

    canvas_w = cell_w * 2
    canvas_h = cell_h * 2

    mosaic = QtGui.QPixmap(canvas_w, canvas_h)
    mosaic.fill(QtGui.QColor("#081120"))

    painter = QtGui.QPainter(mosaic)

    for index, (cid, img) in enumerate(items[:4]):
        row = index // 2
        col = index % 2

        x0 = col * cell_w
        y0 = row * cell_h

        pix = QtGui.QPixmap.fromImage(img)
        pix = pix.scaled(
            cell_w,
            cell_h,
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation,
        )

        px = x0 + (cell_w - pix.width()) // 2
        py = y0 + (cell_h - pix.height()) // 2

        painter.fillRect(x0, y0, cell_w, cell_h, QtGui.QColor("#081120"))
        painter.drawPixmap(px, py, pix)

        painter.setPen(QtGui.QColor("#ffffff"))
        painter.setFont(QtGui.QFont("Segoe UI", 12, QtGui.QFont.Bold))
        painter.drawText(x0 + 12, y0 + 28, cid)

        painter.setPen(QtGui.QColor("#38bdf8"))
        painter.drawRect(x0, y0, cell_w - 1, cell_h - 1)

    painter.end()
    scaled = mosaic.scaled(
        self.video_label.size(),
        QtCore.Qt.KeepAspectRatio,
        QtCore.Qt.SmoothTransformation,
    )

    self.video_label.setPixmap(scaled)

def _multi_on_multi_camera_stats(self, camera_id, stats):
    self.camera_stats[camera_id] = stats

    tong_xe = sum(s.get("vehicles_in_roi", 0) for s in self.camera_stats.values())
    vsl_min = min([s.get("suggested_vsl", 100) for s in self.camera_stats.values()] or [100])
    tong_canh_bao = sum(s.get("warning_count", 0) for s in self.camera_stats.values())
    tong_su_kien = sum(s.get("event_count", 0) for s in self.camera_stats.values())

    stats_tong = dict(stats)
    stats_tong["vehicles_in_roi"] = tong_xe
    stats_tong["suggested_vsl"] = vsl_min
    stats_tong["warning_count"] = tong_canh_bao
    stats_tong["event_count"] = tong_su_kien
    stats_tong["reason"] = f"Tổng hợp đa camera | Camera hiện tại: {camera_id}"

    self.update_ui_from_stats(stats_tong)


GiaoDienChinh.on_chon_camera = _multi_on_chon_camera
GiaoDienChinh.on_start_multi_camera = _multi_on_start_multi_camera
GiaoDienChinh.on_multi_camera_frame = _multi_on_multi_camera_frame
GiaoDienChinh.on_multi_camera_stats = _multi_on_multi_camera_stats
# =========================================================
# PATCH DO TIN CAY AI - KHONG CAN DATASET TEST
# =========================================================

def tinh_do_tin_cay_nhan_dien(confidence, box, frame_shape, in_roi=True):
    
    h, w = frame_shape[:2]
    x1, y1, x2, y2 = box

    box_w = max(1, x2 - x1)
    box_h = max(1, y2 - y1)
    dien_tich_box = box_w * box_h
    dien_tich_frame = max(1, w * h)
    ti_le_box = dien_tich_box / dien_tich_frame

    diem = float(confidence) * 100.0

    if in_roi:
        diem += 10
    else:
        diem -= 15

    if ti_le_box >= 0.015:
        diem += 10
    elif ti_le_box >= 0.005:
        diem += 5
    else:
        diem -= 10

    diem = max(0, min(100, diem))
    return round(diem, 1)


_orig_ai_conf_process_frame = XuLyVideo.xu_ly_khung_hinh

# =========================================================
# PATCH ĐỘ TIN CẬY AI - KHÔNG CẦN DATASET
# =========================================================

try:
    _orig_ai_conf_xu_ly = XuLyVideo.xu_ly_khung_hinh

    def _ai_conf_xu_ly_khung_hinh(self, frame):
        frame = _orig_ai_conf_xu_ly(self, frame)

        try:
            conf_list = []

            for item in getattr(self, "last_inference_boxes", []):
                if len(item) >= 6:
                    confv = float(item[5])
                    conf_list.append(confv)

            if conf_list:
                do_tin_cay_ai = round(
                    sum(conf_list) / len(conf_list) * 100,
                    1
                )
            else:
                do_tin_cay_ai = 0.0

            if not hasattr(self, "last_stats") or self.last_stats is None:
                self.last_stats = {}

            self.last_stats["do_tin_cay_ai"] = do_tin_cay_ai

            try:
                self.statsReady.emit(self.last_stats)
            except Exception:
                pass

        except Exception as e:
            try:
                self.them_nhat_ky(f"[WARN] Lỗi độ tin cậy AI: {e}")
            except Exception:
                pass

        return frame

    XuLyVideo.xu_ly_khung_hinh = _ai_conf_xu_ly_khung_hinh

except Exception:
    pass
try:
    _orig_ai_conf_update = GiaoDienChinh.update_ui_from_stats

    def _ai_conf_update_ui(self, stats):
        _orig_ai_conf_update(self, stats)

        try:
            do_tin_cay_ai = float(stats.get("do_tin_cay_ai", 0.0))
            fps_est = float(stats.get("fps_est", 0.0))

            if do_tin_cay_ai >= 90:
                muc = "RẤT CAO"
            elif do_tin_cay_ai >= 80:
                muc = "CAO"
            elif do_tin_cay_ai >= 60:
                muc = "TRUNG BÌNH"
            elif do_tin_cay_ai > 0:
                muc = "THẤP"
            else:
                muc = "CHƯA CÓ BOX"

            if hasattr(self, "lbl_fps"):
                self.lbl_fps.setText(
                    f"Tốc độ xử lý: {fps_est:.1f} | "
                    f"Độ tin cậy AI: {do_tin_cay_ai:.1f}% ({muc})"
                )

        except Exception:
            pass

    GiaoDienChinh.update_ui_from_stats = _ai_conf_update_ui

except Exception:
    pass
# =========================================================
# PATCH BIỂN SỐ RIÊNG - YOLO PLATE + EASYOCR
# KHÔNG XUNG ĐỘT YOLO XE
# =========================================================

PLATE_MODEL_WEIGHTS = str(BASE_DIR / "trong_so" / "bien_so_yolov8.pt")


def chuan_hoa_bien_so(text):
    if not text:
        return ""

    text = str(text).upper()
    text = text.replace(" ", "")
    text = text.replace(".", "")
    text = text.replace("_", "-")
    text = text.replace("—", "-").replace("–", "-")
    text = text.replace(":", "").replace(";", "")
    text = text.replace("/", "").replace("\\", "")
    text = re.sub(r"[^A-Z0-9-]", "", text)

    m = re.match(r"^([0-9]{2}[A-Z]{1,2})([0-9]{4,6})$", text)
    if m:
        text = m.group(1) + "-" + m.group(2)

    return text


def bien_so_hop_le(text):
    if not text:
        return False

    mau = [
        r"^[0-9]{2}[A-Z]{1,2}-[0-9]{4,6}$",
        r"^[0-9]{2}[A-Z]{1,2}[0-9]{4,6}$",
    ]

    return any(re.match(p, text) for p in mau)


class NhanDienBienSoRieng:
    def __init__(self):
        self.model_plate = None
        self.reader = None
        self.ready = False
        self.history = {}

    def khoi_tao(self):
        if self.ready:
            return self.model_plate is not None and self.reader is not None

        self.ready = True

        if YOLO is None:
            print("[PLATE] Chưa cài ultralytics")
            return False

        if easyocr is None:
            print("[PLATE] Chưa cài easyocr")
            return False

        if not os.path.exists(PLATE_MODEL_WEIGHTS):
            print("[PLATE] Không thấy model:", PLATE_MODEL_WEIGHTS)
            return False

        try:
            self.model_plate = YOLO(PLATE_MODEL_WEIGHTS)
            self.reader = easyocr.Reader(["en"], gpu=False)
            print("[PLATE] Đã tải YOLO biển số + EasyOCR")
            return True
        except Exception as e:
            print("[PLATE] Lỗi khởi tạo:", e)
            self.model_plate = None
            self.reader = None
            return False

    def xu_ly_anh_bien_so(self, crop):
        if crop is None or crop.size == 0:
            return None

        crop = cv2.resize(
            crop,
            None,
            fx=4.0,
            fy=4.0,
            interpolation=cv2.INTER_CUBIC
        )

        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)

        gray = cv2.bilateralFilter(gray, 9, 75, 75)

        blur = cv2.GaussianBlur(gray, (0, 0), 3)
        sharp = cv2.addWeighted(gray, 1.7, blur, -0.7, 0)

        return sharp

    def doc_ocr(self, crop):
        if self.reader is None:
            return ""

        img = self.xu_ly_anh_bien_so(crop)

        if img is None:
            return ""

        try:
            ket_qua = self.reader.readtext(
                img,
                detail=0,
                paragraph=False,
                allowlist="0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-"
            )
        except Exception:
            return ""

        if not ket_qua:
            return ""

        text = chuan_hoa_bien_so("".join(ket_qua))

        if bien_so_hop_le(text):
            return text

        return text

    def loc_on_dinh(self, camera_key, text):
        if not text:
            return ""

        if camera_key not in self.history:
            self.history[camera_key] = []

        self.history[camera_key].append(text)
        self.history[camera_key] = self.history[camera_key][-8:]

        dem = {}
        for x in self.history[camera_key]:
            dem[x] = dem.get(x, 0) + 1

        return max(dem, key=dem.get)

    def detect(self, frame, camera_id="CAM_00"):
        if not self.khoi_tao():
            return []

        try:
            results = self.model_plate.predict(
                frame,
                imgsz=960,
                conf=0.25,
                verbose=False
            )

            if not results:
                return []

            result = results[0]

            if result.boxes is None:
                return []

            h, w = frame.shape[:2]
            ds = []

            for idx, box in enumerate(result.boxes):
                x1, y1, x2, y2 = map(int, box.xyxy[0].cpu().numpy())
                conf = float(box.conf[0].cpu().numpy())

                x1 = max(0, x1)
                y1 = max(0, y1)
                x2 = min(w - 1, x2)
                y2 = min(h - 1, y2)

                if x2 <= x1 or y2 <= y1:
                    continue

                crop = frame[y1:y2, x1:x2]

                if crop.size == 0:
                    continue

                text_raw = self.doc_ocr(crop)
                text = self.loc_on_dinh(f"{camera_id}_{idx}", text_raw)

                if not text:
                    continue

                ds.append({
                    "text": text,
                    "conf": conf,
                    "box": (x1, y1, x2, y2)
                })

            return ds

        except Exception as e:
            print("[PLATE] Detect lỗi:", e)
            return []


try:
    bo_bien_so_rieng = NhanDienBienSoRieng()
    _goc_plate_process = XuLyVideo.xu_ly_khung_hinh

    def _patch_plate_process(self, frame):
        frame = _goc_plate_process(self, frame)

        try:
            stats = dict(getattr(self, "last_stats", {}) or {})
            camera_id = stats.get("camera_id", getattr(self, "camera_id", "CAM_00"))

            plates = bo_bien_so_rieng.detect(frame, camera_id=camera_id)
            bien_so_list = []

            for p in plates:
                text = p["text"]
                conf = p["conf"]
                x1, y1, x2, y2 = p["box"]

                bien_so_list.append(text)

                cv2.rectangle(
                    frame,
                    (x1, y1),
                    (x2, y2),
                    (0, 255, 255),
                    2
                )

                cv2.putText(
                    frame,
                    f"PLATE: {text}",
                    (x1, max(24, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.65,
                    (0, 255, 255),
                    2,
                    cv2.LINE_AA
                )

                cv2.putText(
                    frame,
                    f"{conf:.2f}",
                    (x1, min(frame.shape[0] - 8, y2 + 22)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (0, 255, 255),
                    2,
                    cv2.LINE_AA
                )

            stats["bien_so_nhan_dien"] = bien_so_list[-5:]
            self.last_stats = stats

            try:
                self.statsReady.emit(self.last_stats)
            except Exception:
                pass

        except Exception as e:
            try:
                self.them_nhat_ky(f"[PLATE] Lỗi biển số: {e}")
            except Exception:
                pass

        return frame

    XuLyVideo.xu_ly_khung_hinh = _patch_plate_process

except Exception as e:
    print("[PLATE] Không thể patch:", e)
try:
    _goc_plate_update_ui = GiaoDienChinh.update_ui_from_stats

    def _patch_plate_update_ui(self, stats):
        _goc_plate_update_ui(self, stats)

        bien_so_list = stats.get("bien_so_nhan_dien", [])

        if bien_so_list:
            text = "Biển số nhận diện: " + " | ".join(bien_so_list)

            try:
                self.lbl_action.setText(text)
            except Exception:
                try:
                    self.append_log("[PLATE] " + " | ".join(bien_so_list))
                except Exception:
                    pass

    GiaoDienChinh.update_ui_from_stats = _patch_plate_update_ui

except Exception:
    pass
# =========================================================
# PATCH ĐO TỐC ĐỘ THẬT HƠN BẰNG 2 VẠCH XA NHAU
# =========================================================

SPEED_LINE_A_RATIO = 0.43
SPEED_LINE_B_RATIO = 0.70
SPEED_DISTANCE_METERS = 50.0

SPEED_X_MIN_RATIO = 0.12
SPEED_X_MAX_RATIO = 0.88

SPEED_MAX_MATCH_DISTANCE = 75
SPEED_TRACK_TTL = 90
SPEED_MIN_BOX_W = 30
SPEED_MIN_BOX_H = 30


class DoTocDoHaiVach:
    def __init__(self):
        self.next_id = 1
        self.tracks = {}

    def tim_track_gan_nhat(self, cx, cy, name):
        best_id = None
        best_dist = 10 ** 9

        for tid, tr in self.tracks.items():
            if tr.get("name") != name:
                continue

            px, py = tr.get("last_center", (None, None))

            if px is None:
                continue

            dist = ((cx - px) ** 2 + (cy - py) ** 2) ** 0.5

            if dist < best_dist:
                best_dist = dist
                best_id = tid

        if best_id is not None and best_dist <= SPEED_MAX_MATCH_DISTANCE:
            return best_id

        return None

    def tao_track_moi(self, cx, cy, name):
        tid = self.next_id
        self.next_id += 1

        self.tracks[tid] = {
            "name": name,
            "last_center": (cx, cy),
            "last_y": cy,
            "ttl": SPEED_TRACK_TTL,

            "first_line": None,
            "first_frame": None,
            "second_line": None,
            "second_frame": None,

            "speed_kmh": None,
        }

        return tid

    def cap_nhat(self, frame, boxes, frame_idx, fps_video):
        h, w = frame.shape[:2]

        y_line_a = int(h * self.speed_line_a_ratio)
        y_line_b = int(h * self.speed_line_b_ratio)

        x_min = int(w * SPEED_X_MIN_RATIO)
        x_max = int(w * SPEED_X_MAX_RATIO)

        ket_qua = []

        # giảm TTL để xóa track cũ
        xoa = []
        for tid, tr in self.tracks.items():
            tr["ttl"] -= 1
            if tr["ttl"] <= 0:
                xoa.append(tid)

        for tid in xoa:
            self.tracks.pop(tid, None)

        for item in boxes:
            if len(item) < 11:
                continue

            x1, y1, x2, y2, name, confv, color, cx, cy, in_roi, lane_label = item[:11]

            if not in_roi:
                continue

            if name not in ["car", "motorcycle", "bus", "truck", "bicycle"]:
                continue

            x1 = int(x1)
            y1 = int(y1)
            x2 = int(x2)
            y2 = int(y2)
            cx = int(cx)
            cy = int(cy)

            box_w = x2 - x1
            box_h = y2 - y1

            if box_w < SPEED_MIN_BOX_W or box_h < SPEED_MIN_BOX_H:
                continue

            if cx < x_min or cx > x_max:
                continue

            tid = self.tim_track_gan_nhat(cx, cy, name)

            if tid is None:
                tid = self.tao_track_moi(cx, cy, name)

            tr = self.tracks[tid]

            last_y = int(tr.get("last_y", cy))

            # kiểm tra xe cắt vạch A
            cat_a = (
                (last_y < y_line_a <= cy) or
                (last_y > y_line_a >= cy)
            )

            # kiểm tra xe cắt vạch B
            cat_b = (
                (last_y < y_line_b <= cy) or
                (last_y > y_line_b >= cy)
            )

            if tr["first_line"] is None:
                if cat_a:
                    tr["first_line"] = "A"
                    tr["first_frame"] = frame_idx

                elif cat_b:
                    tr["first_line"] = "B"
                    tr["first_frame"] = frame_idx

            else:
                if tr["second_line"] is None:
                    if tr["first_line"] == "A" and cat_b:
                        tr["second_line"] = "B"
                        tr["second_frame"] = frame_idx

                    elif tr["first_line"] == "B" and cat_a:
                        tr["second_line"] = "A"
                        tr["second_frame"] = frame_idx

                    if tr["second_frame"] is not None:
                        delta_frame = abs(tr["second_frame"] - tr["first_frame"])
                        delta_time = delta_frame / max(1.0, float(fps_video))

                        if delta_time > 0:
                            speed_kmh = SPEED_DISTANCE_METERS / delta_time * 3.6

                            if 5 <= speed_kmh <= 180:
                                tr["speed_kmh"] = round(speed_kmh, 1)

            tr["last_center"] = (cx, cy)
            tr["last_y"] = cy
            tr["ttl"] = SPEED_TRACK_TTL
            tr["name"] = name

            ket_qua.append({
                "id": tid,
                "name": name,
                "box": (x1, y1, x2, y2),
                "center": (cx, cy),
                "speed_kmh": tr.get("speed_kmh"),
            })

        return ket_qua

    def lay_toc_do_da_do(self):
        speeds = []

        for tr in self.tracks.values():
            sp = tr.get("speed_kmh")
            if sp is not None:
                speeds.append(sp)

        return speeds


try:
    _goc_do_toc_do_2_vach = XuLyVideo.xu_ly_khung_hinh

    def _patch_do_toc_do_2_vach(self, frame):
        frame = _goc_do_toc_do_2_vach(self, frame)

        try:
            if not hasattr(self, "bo_do_toc_do_2_vach"):
                self.bo_do_toc_do_2_vach = DoTocDoHaiVach()

            boxes = getattr(self, "last_inference_boxes", [])

            ket_qua_speed = self.bo_do_toc_do_2_vach.cap_nhat(
                frame=frame,
                boxes=boxes,
                frame_idx=self.frame_idx,
                fps_video=self.fps_video,
            )

            h, w = frame.shape[:2]

            y_line_a = int(h * self.speed_line_a_ratio)
            y_line_b = int(h * self.speed_line_b_ratio)

            x_min = int(w * SPEED_X_MIN_RATIO)
            x_max = int(w * SPEED_X_MAX_RATIO)

            cv2.line(
                frame,
                (x_min, y_line_a),
                (x_max, y_line_a),
                (255, 255, 0),
                3
            )

            cv2.line(
                frame,
                (x_min, y_line_b),
                (x_max, y_line_b),
                (0, 255, 255),
                3
            )

            cv2.putText(
                frame,
                "SPEED LINE A",
                (x_min + 10, max(25, y_line_a - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 0),
                2,
                cv2.LINE_AA
            )

            cv2.putText(
                frame,
                f"SPEED LINE B | {self.speed_distance_m:.0f}m",
                (x_min + 10, max(25, y_line_b - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 255),
                2,
                cv2.LINE_AA
            )

            for item in ket_qua_speed:
                x1, y1, x2, y2 = item["box"]
                tid = item["id"]
                sp = item["speed_kmh"]

                label = f"ID {tid}"

                if sp is not None:
                    label += f" | {sp:.1f} km/h"

                cv2.putText(
                    frame,
                    label,
                    (x1, min(frame.shape[0] - 10, y2 + 24)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (255, 255, 0),
                    2,
                    cv2.LINE_AA
                )

            speeds_all = self.bo_do_toc_do_2_vach.lay_toc_do_da_do()

            if speeds_all:
                toc_do_tb = round(sum(speeds_all) / len(speeds_all), 1)
                toc_do_max = round(max(speeds_all), 1)
            else:
                toc_do_tb = 0.0
                toc_do_max = 0.0

            if not hasattr(self, "last_stats") or self.last_stats is None:
                self.last_stats = {}

            self.last_stats["toc_do_tb_kmh"] = toc_do_tb
            self.last_stats["toc_do_cao_nhat_kmh"] = toc_do_max
            self.last_stats["toc_do_xe_danh_sach"] = speeds_all[-10:]

            try:
                self.statsReady.emit(self.last_stats)
            except Exception:
                pass

        except Exception as e:
            try:
                self.them_nhat_ky(f"[SPEED] Lỗi đo tốc độ 2 vạch: {e}")
            except Exception:
                pass

        return frame

    # TẮT patch đo tốc độ cũ để không vẽ trùng SPEED LINE
    # XuLyVideo.xu_ly_khung_hinh = _patch_do_toc_do_2_vach

except Exception as e:
    print("[SPEED] Không thể patch đo tốc độ 2 vạch:", e)


try:
    _goc_speed_update_ui = GiaoDienChinh.update_ui_from_stats

    def _patch_speed_update_ui(self, stats):
        _goc_speed_update_ui(self, stats)

        try:
            toc_do_tb = float(stats.get("toc_do_tb_kmh", 0.0))
            toc_do_max = float(stats.get("toc_do_cao_nhat_kmh", 0.0))

            if toc_do_tb > 0:
                text_speed = (
                    f"Tốc độ xe TB: {toc_do_tb:.1f} km/h | "
                    f"Cao nhất: {toc_do_max:.1f} km/h"
                )
            else:
                text_speed = "Tốc độ xe: chờ xe đi qua đủ 2 vạch"

            if hasattr(self, "lbl_action"):
                self.lbl_action.setText(text_speed)

            if hasattr(self, "lbl_fps"):
                old_text = self.lbl_fps.text()

                if "Tốc độ xe TB" not in old_text and "Tốc độ xe:" not in old_text:
                    self.lbl_fps.setText(old_text + " | " + text_speed)

        except Exception:
            pass

    GiaoDienChinh.update_ui_from_stats = _patch_speed_update_ui

except Exception:
    pass


# =========================================================
# FINAL HOTFIX - VEHICLE DETECTION STABILIZER
# Đặt ở CUỐI FILE để thắng toàn bộ monkey-patch phía trên.
# Mục tiêu: YOLO phải hiện box trước, sau đó mới tính ROI/làn/VSL.
# =========================================================
try:
    _goc_xu_ly_khung_hinh_final_vehicle = XuLyVideo.xu_ly_khung_hinh

    def _final_vehicle_detection_hotfix(self, frame):
        # Chạy pipeline cũ trước để giữ overlay làn, mặt đường, biển báo, tốc độ.
        frame = _goc_xu_ly_khung_hinh_final_vehicle(self, frame)

        try:
            # Nếu pipeline cũ đã có box thì không làm lại, tránh nặng máy.
            old_boxes = getattr(self, "last_inference_boxes", []) or []
            if len(old_boxes) > 0:
                return frame

            if getattr(self, "model", None) is None:
                return frame

            device = "cuda:0" if self.config.detection.use_gpu and CUDA_AVAILABLE else "cpu"

            res = self.model.predict(
                frame,
                imgsz=max(960, int(getattr(self.config.detection, "imgsz", 960))),
                conf=min(0.15, float(getattr(self.config.detection, "conf_th", 0.15))),
                device=device,
                half=bool(self.config.detection.use_gpu and CUDA_AVAILABLE),
                verbose=False,
            )[0]

            if res.boxes is None or res.boxes.xyxy is None:
                self.them_nhat_ky("[FINAL YOLO] Không có boxes")
                return frame

            xyxy = res.boxes.xyxy.cpu().numpy()
            cls = res.boxes.cls.cpu().numpy()
            confs = res.boxes.conf.cpu().numpy()

            h, w = frame.shape[:2]
            rc = self.config.roi
            poly = tao_da_giac_roi(
                w, h,
                rc.top_center_x,
                rc.bottom_center_x,
                rc.bottom_width,
                rc.top_width,
                rc.height,
                rc.bottom_y,
            )

            boxes = []
            class_counts = {name: 0 for name in VEHICLE_CLASSES}
            total_in_roi = 0

            for box, cls_id, confv in zip(xyxy, cls, confs):
                raw_name = self.name_map.get(int(cls_id), str(cls_id))
                name = chuan_hoa_ten_xe(raw_name)

                if name is None:
                    continue

                x1, y1, x2, y2 = map(int, box)
                ax = (x1 + x2) // 2
                ay = int(y2 - 0.08 * (y2 - y1))

                in_roi = kiem_tra_diem_trong_da_giac((ax, ay), poly)

                # Quan trọng: vẫn hiện box dù ngoài ROI để kiểm tra YOLO.
                color = (0, 255, 102) if in_roi else (0, 180, 255)
                boxes.append((x1, y1, x2, y2, name, float(confv), color, ax, ay, in_roi, None))

                if in_roi:
                    total_in_roi += 1
                    class_counts[name] += 1

                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                cv2.circle(frame, (ax, ay), 4, (0, 255, 255), -1)
                cv2.putText(
                    frame,
                    f"{name} {float(confv):.2f}",
                    (x1, max(24, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    color,
                    2,
                    cv2.LINE_AA,
                )

            self.last_inference_boxes = boxes

            if len(boxes) > 0:
                self.vehicle_history.append(total_in_roi)
                avg_vehicles = round(sum(self.vehicle_history) / max(1, len(self.vehicle_history)))

                density, vsl_speed, traffic_state, reason = tinh_vsl_theo_ngu_canh(
                    avg_vehicles,
                    class_counts,
                    self.config.vsl,
                )

                stats = dict(getattr(self, "last_stats", {}) or {})
                stats.update({
                    "vehicles_in_roi": total_in_roi,
                    "avg_vehicles": avg_vehicles,
                    "density": density,
                    "traffic_state": traffic_state,
                    "suggested_vsl": vsl_speed,
                    "class_counts": class_counts,
                    "do_tin_cay_ai": round(sum([b[5] for b in boxes]) / max(1, len(boxes)) * 100, 1),
                    "reason": reason + " | FINAL HOTFIX YOLO",
                })
                self.last_stats = stats
                try:
                    self.statsReady.emit(self.last_stats)
                except Exception:
                    pass

                self.them_nhat_ky(f"[FINAL YOLO] Đã bắt {len(boxes)} box, trong ROI={total_in_roi}")

        except Exception as e:
            try:
                self.them_nhat_ky(f"[FINAL YOLO] Lỗi hotfix nhận diện: {e}")
            except Exception:
                pass

        return frame

    XuLyVideo.xu_ly_khung_hinh = _final_vehicle_detection_hotfix

except Exception as e:
    print("[FINAL YOLO] Không thể cài hotfix:", e)


# =========================================================
# FINAL HOTFIX - ĐO TỐC ĐỘ 2 VẠCH CÓ TRACKING ỔN ĐỊNH
# Đặt trước main để chạy sau hotfix nhận diện.
# Cách đo: gán ID theo tâm bbox, ghi thời điểm xe cắt vạch A/B,
# tốc độ = khoảng cách thực tế giữa 2 vạch / thời gian đi qua.
# =========================================================
try:
    _goc_xu_ly_khung_hinh_final_speed = XuLyVideo.xu_ly_khung_hinh

    def _speed_iou_bbox(a, b):
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
        inter = iw * ih
        area_a = max(1, (ax2 - ax1) * (ay2 - ay1))
        area_b = max(1, (bx2 - bx1) * (by2 - by1))
        return inter / max(1, area_a + area_b - inter)

    def _speed_init_state(self):
        if not hasattr(self, "speed_tracks_chuan"):
            self.speed_tracks_chuan = {}
            self.speed_next_id_chuan = 1
            self.speed_done_values_chuan = []
            self.speed_distance_m_chuan = 50.0
            self.speed_track_timeout_frames = 45
            self.speed_min_kmh = 5.0
            self.speed_max_kmh = 160.0
            self.speed_last_log_frame = -999

    def _speed_match_track(self, name, bbox, foot, frame_idx):
        _speed_init_state(self)
        best_tid = None
        best_score = -1e9
        fx, fy = foot
        for tid, tr in list(self.speed_tracks_chuan.items()):
            if frame_idx - tr.get("last_frame", frame_idx) > self.speed_track_timeout_frames:
                self.speed_tracks_chuan.pop(tid, None)
                continue
            if tr.get("name") != name:
                continue
            px, py = tr.get("foot", foot)
            dist = ((fx - px) ** 2 + (fy - py) ** 2) ** 0.5
            iou = _speed_iou_bbox(bbox, tr.get("bbox", bbox))
            # Điểm ghép: ưu tiên IoU, sau đó khoảng cách tâm chân bbox.
            score = iou * 100.0 - dist * 0.8
            if dist < 130 or iou > 0.05:
                if score > best_score:
                    best_score = score
                    best_tid = tid
        if best_tid is None:
            best_tid = self.speed_next_id_chuan
            self.speed_next_id_chuan += 1
            self.speed_tracks_chuan[best_tid] = {
                "name": name,
                "bbox": bbox,
                "foot": foot,
                "last_foot": foot,
                "last_frame": frame_idx,
                "time_a": None,
                "time_b": None,
                "line_first": None,
                "speed": None,
                "speed_smooth": None,
            }
        return best_tid

    def _speed_update_track(self, tid, name, bbox, foot, line_a_y, line_b_y, t_sec, frame_idx):
        tr = self.speed_tracks_chuan[tid]
        last_x, last_y = tr.get("foot", foot)
        x, y = foot

        def crossed(y0, y1, line_y):
            return (y0 < line_y <= y1) or (y0 > line_y >= y1)

        # Ghi vạch đầu tiên theo hướng di chuyển. Xe có thể đi từ trên xuống hoặc dưới lên.
        if tr["time_a"] is None and crossed(last_y, y, line_a_y):
            tr["time_a"] = t_sec
            tr["line_first"] = "A"
        if tr["time_b"] is None and crossed(last_y, y, line_b_y):
            tr["time_b"] = t_sec
            if tr["line_first"] is None:
                tr["line_first"] = "B"

        # Khi đã qua đủ 2 vạch thì tính tốc độ.
        if tr.get("speed") is None and tr["time_a"] is not None and tr["time_b"] is not None:
            dt = abs(float(tr["time_b"]) - float(tr["time_a"]))
            if dt >= 0.08:
                speed_kmh = (float(self.speed_distance_m_chuan) / dt) * 3.6
                if self.speed_min_kmh <= speed_kmh <= self.speed_max_kmh:
                    tr["speed"] = round(speed_kmh, 1)
                    tr["speed_smooth"] = tr["speed"]
                    self.speed_done_values_chuan.append(tr["speed"])
                    if len(self.speed_done_values_chuan) > 100:
                        self.speed_done_values_chuan = self.speed_done_values_chuan[-100:]

        tr["last_foot"] = tr.get("foot", foot)
        tr["foot"] = foot
        tr["bbox"] = bbox
        tr["name"] = name
        tr["last_frame"] = frame_idx
        return tr.get("speed")

    def _final_speed_measurement_hotfix(self, frame):
        frame = _goc_xu_ly_khung_hinh_final_speed(self, frame)

        try:
            _speed_init_state(self)
            h, w = frame.shape[:2]
            t_sec = self.frame_idx / self.fps_video if getattr(self, "fps_video", 0) else time.time()

            # Hai vạch đo đặt theo phối cảnh đường cao tốc trong video.
            # Muốn hiệu chuẩn thật hơn: đổi self.speed_distance_m_chuan đúng khoảng cách thực địa giữa 2 vạch.
            line_a_y = int(h * 0.43)
            line_b_y = int(h * 0.68)
            x0, x1 = int(w * 0.40), int(w * 0.98)

            boxes = list(getattr(self, "last_inference_boxes", []) or [])
            current_speeds = []

            cv2.line(frame, (x0, line_a_y), (x1, line_a_y), (255, 255, 0), 3)
            cv2.line(frame, (x0, line_b_y), (x1, line_b_y), (0, 255, 255), 3)
            cv2.putText(frame, "SPEED LINE A", (x0 + 8, max(24, line_a_y - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.68, (255, 255, 0), 2, cv2.LINE_AA)
            cv2.putText(frame, f"SPEED LINE B | {self.speed_distance_m_chuan:.0f}m", (x0 + 8, max(24, line_b_y - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.68, (0, 255, 255), 2, cv2.LINE_AA)

            for b in boxes:
                if len(b) < 11:
                    continue
                x1b, y1b, x2b, y2b, name, confv, color, cx, cy, in_roi, lane_label = b[:11]
                # Dùng chân bbox để ổn định hướng đi qua vạch.
                foot = (int((x1b + x2b) / 2), int(y2b - 0.04 * (y2b - y1b)))
                bbox = (int(x1b), int(y1b), int(x2b), int(y2b))
                tid = _speed_match_track(self, str(name), bbox, foot, self.frame_idx)
                sp = _speed_update_track(self, tid, str(name), bbox, foot, line_a_y, line_b_y, t_sec, self.frame_idx)

                if sp is not None:
                    current_speeds.append(float(sp))
                    txt = f"ID {tid} | {sp:.1f} km/h"
                    txt_color = (0, 255, 255)
                else:
                    txt = f"ID {tid} | measuring"
                    txt_color = (255, 255, 0)

                cv2.circle(frame, foot, 4, txt_color, -1)
                cv2.putText(frame, txt, (int(x1b), min(h - 8, int(y2b) + 22)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, txt_color, 2, cv2.LINE_AA)

            speeds_all = list(getattr(self, "speed_done_values_chuan", []) or [])
            if speeds_all:
                avg_speed = round(sum(speeds_all[-20:]) / len(speeds_all[-20:]), 1)
                max_speed = round(max(speeds_all), 1)
                min_speed = round(min(speeds_all), 1)
                speed_text = f"SPEED AVG {avg_speed:.1f} km/h | MAX {max_speed:.1f}"
            else:
                avg_speed = max_speed = min_speed = 0.0
                speed_text = "SPEED: waiting vehicles cross A+B"

            cv2.rectangle(frame, (20, 20), (520, 58), (0, 0, 0), -1)
            cv2.putText(frame, speed_text, (30, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (0, 255, 255), 2, cv2.LINE_AA)

            stats = dict(getattr(self, "last_stats", {}) or {})
            stats.update({
                "toc_do_tb_kmh": avg_speed,
                "toc_do_cao_nhat_kmh": max_speed,
                "toc_do_thap_nhat_kmh": min_speed,
                "toc_do_xe_danh_sach": speeds_all[-10:],
                "so_xe_da_do_toc_do": len(speeds_all),
                "speed_distance_m": float(self.speed_distance_m_chuan),
                "speed_note": "Đo 2 vạch: speed = distance/time. Cần hiệu chuẩn distance_m theo thực địa để đạt độ chính xác cao nhất.",
            })
            self.last_stats = stats
            try:
                self.statsReady.emit(self.last_stats)
            except Exception:
                pass

            if self.frame_idx - getattr(self, "speed_last_log_frame", -999) >= 90:
                self.speed_last_log_frame = self.frame_idx
                try:
                    self.them_nhat_ky(f"[SPEED FINAL] measured={len(speeds_all)} avg={avg_speed:.1f} max={max_speed:.1f} distance={self.speed_distance_m_chuan:.0f}m")
                except Exception:
                    pass

        except Exception as e:
            try:
                self.them_nhat_ky(f"[SPEED FINAL] Lỗi đo tốc độ: {e}")
            except Exception:
                pass

        return frame

    XuLyVideo.xu_ly_khung_hinh = _final_speed_measurement_hotfix

except Exception as e:
    print("[SPEED FINAL] Không thể cài hotfix đo tốc độ:", e)


try:
    _goc_update_ui_speed_final = GiaoDienChinh.update_ui_from_stats

    def _final_speed_update_ui(self, stats):
        _goc_update_ui_speed_final(self, stats)
        try:
            avg_speed = float(stats.get("toc_do_tb_kmh", 0.0) or 0.0)
            max_speed = float(stats.get("toc_do_cao_nhat_kmh", 0.0) or 0.0)
            measured = int(stats.get("so_xe_da_do_toc_do", 0) or 0)
            if avg_speed > 0:
                text_speed = f"Tốc độ xe TB: {avg_speed:.1f} km/h | Max: {max_speed:.1f} km/h | Đã đo: {measured} xe"
            else:
                text_speed = "Tốc độ xe: đang chờ xe cắt đủ 2 vạch A/B"

            for attr in ["lbl_action", "lbl_fps", "lbl_reason", "lbl_status"]:
                if hasattr(self, attr):
                    obj = getattr(self, attr)
                    if hasattr(obj, "setText"):
                        old = obj.text() if hasattr(obj, "text") else ""
                        if "Tốc độ xe" in old or attr in ["lbl_action"]:
                            obj.setText(text_speed)
                            break
        except Exception:
            pass

    GiaoDienChinh.update_ui_from_stats = _final_speed_update_ui
except Exception:
    pass


# =========================================================
# FINAL HOTFIX - ROI/LÀN ĐƯỜNG ĐÃ HIỆU CHUẨN CHO VIDEO CAO TỐC
# Mục tiêu: bỏ auto-road bị lệch sang lề/median, dùng hình học phối cảnh ổn định.
# Điểm ROI chuẩn theo frame: chỉ lấy chiều xe chạy bên phải màn hình.
# =========================================================
def _roi_cao_toc_chuan_theo_frame(w, h):
    return np.array([
        [int(w * 0.49), int(h * 0.39)],   # mép trái xa, gần dải phân cách
        [int(w * 0.98), int(h * 0.39)],   # mép phải xa
        [int(w * 0.98), int(h * 0.92)],   # mép phải gần
        [int(w * 0.37), int(h * 0.92)],   # mép trái gần
    ], dtype=np.int32)


def _v6_auto_road_polygon_from_frame(frame, prev_poly=None):
    h, w = frame.shape[:2]
    poly = _roi_cao_toc_chuan_theo_frame(w, h)
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.fillPoly(mask, [poly], 255)
    return poly, mask, 0.92, True


def build_lane_polygons_smart_v4(frame: np.ndarray, poly: np.ndarray, lane_count: int = 3, include_shoulder: bool = False):
    lane_count = max(1, int(lane_count))
    total_segments = lane_count
    top_left, top_right, bot_right, bot_left = [np.array(p, dtype=np.float32) for p in poly]
    items = []
    for i in range(total_segments):
        t0 = i / total_segments
        t1 = (i + 1) / total_segments
        p_top_0 = top_left + (top_right - top_left) * t0
        p_top_1 = top_left + (top_right - top_left) * t1
        p_bot_0 = bot_left + (bot_right - bot_left) * t0
        p_bot_1 = bot_left + (bot_right - bot_left) * t1
        quad = np.array([p_top_0, p_top_1, p_bot_1, p_bot_0], dtype=np.int32)
        label = f"Lane {i}"
        items.append((label, quad))
    return items



# =========================================================
# FINAL HOTFIX V2 - ĐO TỐC ĐỘ TẤT CẢ LÀN + VẼ ROI CHUẨN
# - Dùng ROI phủ toàn bộ chiều xe chạy.
# - Chia 3 làn theo phối cảnh.
# - Vẽ vạch A/B riêng trên từng làn.
# - Đo tốc độ cho xe ở mọi làn, không chỉ một vùng giữa.
# =========================================================
def _roi_toan_bo_lan_duong_chuan(w, h):
    """
    ROI THỦ CÔNG / ROI CŨ ĐÚNG CHIỀU XE CHẠY.
    Không lấy làn ngược chiều bên trái dải phân cách.
    Chỉ phủ 3 làn cao tốc cùng chiều ở nửa phải khung hình.
    Muốn chỉnh tay thì chỉ sửa 4 cặp hệ số dưới đây.
    """
    #            x%      y%
    diem_trai_xa  = (0.49, 0.39)
    diem_phai_xa  = (0.98, 0.39)
    diem_phai_gan = (0.98, 0.92)
    diem_trai_gan = (0.37, 0.92)

    return np.array([
        [int(w * diem_trai_xa[0]),  int(h * diem_trai_xa[1])],
        [int(w * diem_phai_xa[0]),  int(h * diem_phai_xa[1])],
        [int(w * diem_phai_gan[0]), int(h * diem_phai_gan[1])],
        [int(w * diem_trai_gan[0]), int(h * diem_trai_gan[1])],
    ], dtype=np.int32)


def _noi_suy_canh(poly, y):
    """Trả về x trái/phải của ROI/lane tại cao độ y để vẽ vạch tốc độ đúng trong đa giác."""
    pts = np.asarray(poly, dtype=np.float32)
    xs = []
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        if abs(y2 - y1) < 1e-6:
            continue
        if (y1 <= y <= y2) or (y2 <= y <= y1):
            t = (y - y1) / (y2 - y1)
            if 0 <= t <= 1:
                xs.append(x1 + (x2 - x1) * t)
    if len(xs) < 2:
        return None
    xs = sorted(xs)
    return int(xs[0]), int(xs[-1])


def _chia_lan_doc_theo_phoi_canh(poly, so_lan=3):
    """Chia ROI thành các làn theo chiều ngang phối cảnh: Lane 0 trái -> Lane 2 phải."""
    so_lan = max(1, int(so_lan))
    top_left, top_right, bot_right, bot_left = [np.array(p, dtype=np.float32) for p in poly]
    lanes = []
    for i in range(so_lan):
        t0 = i / so_lan
        t1 = (i + 1) / so_lan
        p_top_0 = top_left + (top_right - top_left) * t0
        p_top_1 = top_left + (top_right - top_left) * t1
        p_bot_0 = bot_left + (bot_right - bot_left) * t0
        p_bot_1 = bot_left + (bot_right - bot_left) * t1
        lane_poly = np.array([p_top_0, p_top_1, p_bot_1, p_bot_0], dtype=np.int32)
        lanes.append((f"Lane {i}", lane_poly))
    return lanes


def _tim_lan_cua_diem(point, lane_items):
    for label, lane_poly in lane_items:
        if cv2.pointPolygonTest(lane_poly.astype(np.float32), (float(point[0]), float(point[1])), False) >= 0:
            return label
    return None


# Ghi đè ROI engine để các phần khác trong app cũng dùng ROI/làn chuẩn này.
def _v6_auto_road_polygon_from_frame(frame, prev_poly=None):
    h, w = frame.shape[:2]
    poly = _roi_toan_bo_lan_duong_chuan(w, h)
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.fillPoly(mask, [poly], 255)
    return poly, mask, 0.96, True


def build_lane_polygons_smart_v4(frame: np.ndarray, poly: np.ndarray, lane_count: int = 3, include_shoulder: bool = False):
    return _chia_lan_doc_theo_phoi_canh(poly, so_lan=lane_count)


try:
    # Lấy hàm nhận diện gốc TRƯỚC hotfix tốc độ cũ để tránh vẽ trùng vạch A/B.
    _base_detect_all_lanes_speed = globals().get("_goc_xu_ly_khung_hinh_final_speed", XuLyVideo.xu_ly_khung_hinh)

    def _lane_speed_init_v2(self):
        if not hasattr(self, "speed_tracks_all_lanes_v2"):
            self.speed_tracks_all_lanes_v2 = {}
            self.speed_next_id_all_lanes_v2 = 1
            self.speed_done_all_lanes_v2 = []
            self.speed_by_lane_all_lanes_v2 = {"Lane 0": [], "Lane 1": [], "Lane 2": []}
            self.speed_distance_m_chuan = float(getattr(self, "speed_distance_m_chuan", 50.0))
            self.speed_track_timeout_frames = 55
            self.speed_min_kmh = 5.0
            self.speed_max_kmh = 180.0

    def _iou_v2(a, b):
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
        inter = iw * ih
        area_a = max(1, (ax2 - ax1) * (ay2 - ay1))
        area_b = max(1, (bx2 - bx1) * (by2 - by1))
        return inter / max(1, area_a + area_b - inter)

    def _match_track_v2(self, name, lane_label, bbox, foot, frame_idx):
        _lane_speed_init_v2(self)
        best_id, best_score = None, -1.0
        fx, fy = foot
        for tid, tr in list(self.speed_tracks_all_lanes_v2.items()):
            if frame_idx - tr.get("last_frame", frame_idx) > self.speed_track_timeout_frames:
                self.speed_tracks_all_lanes_v2.pop(tid, None)
                continue
            if tr.get("name") != name:
                continue
            if tr.get("lane") != lane_label:
                continue
            tx, ty = tr.get("foot", foot)
            dist = ((fx - tx) ** 2 + (fy - ty) ** 2) ** 0.5
            iou = _iou_v2(bbox, tr.get("bbox", bbox))
            score = iou * 2.2 - dist / 180.0
            if score > best_score:
                best_id, best_score = tid, score
        if best_id is None or best_score < -0.25:
            best_id = self.speed_next_id_all_lanes_v2
            self.speed_next_id_all_lanes_v2 += 1
            self.speed_tracks_all_lanes_v2[best_id] = {
                "name": name,
                "lane": lane_label,
                "bbox": bbox,
                "foot": foot,
                "last_y": foot[1],
                "last_frame": frame_idx,
                "time_a": None,
                "time_b": None,
                "speed": None,
            }
        return best_id

    def _update_track_v2(self, tid, lane_label, bbox, foot, line_a_y, line_b_y, t_sec, frame_idx):
        tr = self.speed_tracks_all_lanes_v2[tid]
        last_y = int(tr.get("last_y", foot[1]))
        cy = int(foot[1])

        crossed_a = (last_y <= line_a_y <= cy) or (last_y >= line_a_y >= cy)
        crossed_b = (last_y <= line_b_y <= cy) or (last_y >= line_b_y >= cy)

        if tr.get("time_a") is None and crossed_a:
            tr["time_a"] = float(t_sec)
        if tr.get("time_a") is not None and tr.get("time_b") is None and crossed_b:
            tr["time_b"] = float(t_sec)

        if tr.get("speed") is None and tr.get("time_a") is not None and tr.get("time_b") is not None:
            dt = abs(float(tr["time_b"]) - float(tr["time_a"]))
            if dt > 0.08:
                kmh = (float(self.speed_distance_m_chuan) / dt) * 3.6
                if self.speed_min_kmh <= kmh <= self.speed_max_kmh:
                    sp = round(kmh, 1)
                    tr["speed"] = sp
                    self.speed_done_all_lanes_v2.append(sp)
                    self.speed_by_lane_all_lanes_v2.setdefault(lane_label, []).append(sp)
                    self.speed_done_all_lanes_v2 = self.speed_done_all_lanes_v2[-120:]
                    for k in list(self.speed_by_lane_all_lanes_v2.keys()):
                        self.speed_by_lane_all_lanes_v2[k] = self.speed_by_lane_all_lanes_v2[k][-60:]

        tr["bbox"] = bbox
        tr["foot"] = foot
        tr["last_y"] = cy
        tr["last_frame"] = frame_idx
        tr["lane"] = lane_label
        return tr.get("speed")

    def _xu_ly_khung_hinh_all_lanes_speed_v2(self, frame):
        frame = _base_detect_all_lanes_speed(self, frame)
        try:
            _lane_speed_init_v2(self)
            h, w = frame.shape[:2]
            t_sec = self.frame_idx / self.fps_video if getattr(self, "fps_video", 0) else time.time()

            roi_poly = _roi_toan_bo_lan_duong_chuan(w, h)
            lane_items = _chia_lan_doc_theo_phoi_canh(roi_poly, so_lan=3)
            line_a_y = int(h * 0.47)
            line_b_y = int(h * 0.70)

            # Vẽ ROI tổng.
            overlay = frame.copy()
            cv2.fillPoly(overlay, [roi_poly], (0, 255, 120))
            cv2.addWeighted(overlay, 0.10, frame, 0.90, 0, frame)
            cv2.polylines(frame, [roi_poly], True, (0, 255, 0), 3)
            cv2.putText(frame, "ROI CU - DUNG CHIEU XE CHAY", (int(w * 0.38), int(h * 0.92) - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.70, (0, 255, 0), 2, cv2.LINE_AA)

            # Vẽ từng làn và vạch tốc độ A/B trong từng làn.
            lane_counts_v2 = {"Lane 0": 0, "Lane 1": 0, "Lane 2": 0}
            for lane_label, lane_poly in lane_items:
                cv2.polylines(frame, [lane_poly], True, (0, 180, 255), 2)
                c = np.mean(lane_poly, axis=0).astype(int)
                cv2.putText(frame, lane_label, (int(c[0]) - 35, int(c[1])), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 180, 255), 2, cv2.LINE_AA)

                seg_a = _noi_suy_canh(lane_poly, line_a_y)
                seg_b = _noi_suy_canh(lane_poly, line_b_y)
                if seg_a:
                    ax0, ax1 = seg_a
                    cv2.line(frame, (ax0 + 3, line_a_y), (ax1 - 3, line_a_y), (255, 255, 0), 3)
                if seg_b:
                    bx0, bx1 = seg_b
                    cv2.line(frame, (bx0 + 3, line_b_y), (bx1 - 3, line_b_y), (0, 255, 255), 3)

            cv2.putText(frame, "SPEED LINE A - 3 LAN DUNG CHIEU", (int(w * 0.38), line_a_y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 0), 2, cv2.LINE_AA)
            cv2.putText(frame, f"SPEED LINE B - 3 LAN | {self.speed_distance_m_chuan:.0f}m", (int(w * 0.38), line_b_y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 255, 255), 2, cv2.LINE_AA)

            boxes = list(getattr(self, "last_inference_boxes", []) or [])
            for b in boxes:
                if len(b) < 11:
                    continue
                x1b, y1b, x2b, y2b, name, confv, color, cx, cy, in_roi, old_lane = b[:11]
                foot = (int((x1b + x2b) / 2), int(y2b - 0.04 * (y2b - y1b)))
                lane_label = _tim_lan_cua_diem(foot, lane_items)
                if lane_label is None:
                    continue
                lane_counts_v2[lane_label] = lane_counts_v2.get(lane_label, 0) + 1
                bbox = (int(x1b), int(y1b), int(x2b), int(y2b))
                tid = _match_track_v2(self, str(name), lane_label, bbox, foot, self.frame_idx)
                sp = _update_track_v2(self, tid, lane_label, bbox, foot, line_a_y, line_b_y, t_sec, self.frame_idx)

                if sp is None:
                    txt = f"ID {tid} | {lane_label} | measuring"
                    tc = (255, 255, 0)
                else:
                    txt = f"ID {tid} | {lane_label} | {sp:.1f} km/h"
                    tc = (0, 255, 255)
                cv2.circle(frame, foot, 5, tc, -1)
                cv2.putText(frame, txt, (int(x1b), min(h - 8, int(y2b) + 22)), cv2.FONT_HERSHEY_SIMPLEX, 0.50, tc, 2, cv2.LINE_AA)

            speeds_all = list(self.speed_done_all_lanes_v2 or [])
            by_lane = self.speed_by_lane_all_lanes_v2
            if speeds_all:
                avg_speed = round(sum(speeds_all[-30:]) / len(speeds_all[-30:]), 1)
                max_speed = round(max(speeds_all), 1)
                min_speed = round(min(speeds_all), 1)
                speed_text = f"SPEED AVG {avg_speed:.1f} km/h | MAX {max_speed:.1f} | measured {len(speeds_all)}"
            else:
                avg_speed = max_speed = min_speed = 0.0
                speed_text = "SPEED: waiting vehicles cross A+B in any lane"

            cv2.rectangle(frame, (20, 18), (760, 58), (0, 0, 0), -1)
            cv2.putText(frame, speed_text, (30, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (0, 255, 255), 2, cv2.LINE_AA)

            lane_speed_texts = []
            for lane in ["Lane 0", "Lane 1", "Lane 2"]:
                arr = by_lane.get(lane, [])
                if arr:
                    lane_speed_texts.append(f"{lane}: {round(sum(arr[-10:]) / len(arr[-10:]), 1)}km/h/{len(arr)}xe")
                else:
                    lane_speed_texts.append(f"{lane}: chờ")
            cv2.putText(frame, " | ".join(lane_speed_texts), (30, 82), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 255, 255), 2, cv2.LINE_AA)

            stats = dict(getattr(self, "last_stats", {}) or {})
            lane_avg = {}
            lane_measured = {}
            for lane, arr in by_lane.items():
                lane_avg[lane] = round(sum(arr[-10:]) / len(arr[-10:]), 1) if arr else 0.0
                lane_measured[lane] = len(arr)
            stats.update({
                "lane_counts": lane_counts_v2,
                "toc_do_tb_kmh": avg_speed,
                "toc_do_cao_nhat_kmh": max_speed,
                "toc_do_thap_nhat_kmh": min_speed,
                "toc_do_xe_danh_sach": speeds_all[-10:],
                "so_xe_da_do_toc_do": len(speeds_all),
                "toc_do_theo_lan": lane_avg,
                "so_xe_da_do_theo_lan": lane_measured,
                "speed_distance_m": float(self.speed_distance_m_chuan),
                "speed_note": "Đo 3 làn đúng chiều bằng ROI cũ thủ công + 2 vạch A/B riêng theo từng lane. Muốn chuẩn thực địa, hiệu chỉnh speed_distance_m_chuan theo khoảng cách thật.",
                "reason": str(stats.get("reason", "")) + " | ROI=roi-cu-dung-chieu | speed=3-lanes-A/B",
            })
            self.last_stats = stats
            try:
                self.statsReady.emit(self.last_stats)
            except Exception:
                pass
        except Exception as e:
            try:
                self.them_nhat_ky(f"[ALL LANES SPEED] Lỗi: {e}")
            except Exception:
                pass
        return frame

    XuLyVideo.xu_ly_khung_hinh = _xu_ly_khung_hinh_all_lanes_speed_v2
except Exception as e:
    print("[ALL LANES SPEED] Không thể cài hotfix:", e)



# =========================================================
# FINAL HOTFIX V3 - ROI TẤT CẢ LÀN, TRỪ DẢI/GIẢI PHÂN CÁCH
# - Vẽ 2 ROI: chiều trái + chiều phải, bỏ vùng phân cách ở giữa.
# - Chia làn riêng cho mỗi chiều.
# - Đo tốc độ cho xe ở mọi lane, hỗ trợ xe đi lên hoặc đi xuống ảnh.
# =========================================================
def _roi_tat_ca_lan_tru_giai_phan_cach(w, h):
    """
    Trả về danh sách ROI cho đường cao tốc có dải phân cách giữa.
    Mỗi ROI là một chiều xe chạy; vùng dải phân cách ở giữa bị bỏ trống.
    Chỉ cần chỉnh các hệ số x/y bên dưới nếu camera khác góc.
    """
    y_top = 0.39
    y_bot = 0.92

    # Bên trái dải phân cách: các làn ngược chiều trên ảnh.
    roi_trai = np.array([
        [int(w * 0.08), int(h * y_top)],
        [int(w * 0.465), int(h * y_top)],
        [int(w * 0.405), int(h * y_bot)],
        [int(w * 0.00), int(h * y_bot)],
    ], dtype=np.int32)

    # Bên phải dải phân cách: các làn cùng chiều trên ảnh.
    roi_phai = np.array([
        [int(w * 0.535), int(h * y_top)],
        [int(w * 0.985), int(h * y_top)],
        [int(w * 0.985), int(h * y_bot)],
        [int(w * 0.505), int(h * y_bot)],
    ], dtype=np.int32)

    # Vùng dải phân cách để vẽ viền cảnh báo, không dùng đo/đếm.
    median = np.array([
        [int(w * 0.465), int(h * y_top)],
        [int(w * 0.535), int(h * y_top)],
        [int(w * 0.505), int(h * y_bot)],
        [int(w * 0.405), int(h * y_bot)],
    ], dtype=np.int32)

    return [
        ("LEFT", roi_trai),
        ("RIGHT", roi_phai),
    ], median


def _split_lanes_in_roi_v3(side, poly, lane_count=3):
    """Chia một ROI thành các làn dọc theo phối cảnh."""
    lane_count = max(1, int(lane_count))
    top_left, top_right, bot_right, bot_left = [np.array(p, dtype=np.float32) for p in poly]
    lanes = []
    for i in range(lane_count):
        t0 = i / lane_count
        t1 = (i + 1) / lane_count
        p_top_0 = top_left + (top_right - top_left) * t0
        p_top_1 = top_left + (top_right - top_left) * t1
        p_bot_0 = bot_left + (bot_right - bot_left) * t0
        p_bot_1 = bot_left + (bot_right - bot_left) * t1
        lane_poly = np.array([p_top_0, p_top_1, p_bot_1, p_bot_0], dtype=np.int32)
        label = f"{side} Lane {i}"
        lanes.append((label, lane_poly, side))
    return lanes


def _all_lane_items_v3(w, h, lane_count=3):
    rois, median = _roi_tat_ca_lan_tru_giai_phan_cach(w, h)
    items = []
    for side, poly in rois:
        items.extend(_split_lanes_in_roi_v3(side, poly, lane_count=lane_count))
    return rois, median, items


def _find_lane_v3(point, lane_items):
    for label, poly, side in lane_items:
        if cv2.pointPolygonTest(poly.astype(np.float32), (float(point[0]), float(point[1])), False) >= 0:
            return label, side
    return None, None


def _draw_roi_all_lanes_no_median_v3(frame, rois, median, lane_items, line_a_y, line_b_y, distance_m):
    h, w = frame.shape[:2]
    overlay = frame.copy()

    # Tô 2 ROI đường chạy, không tô dải phân cách.
    for side, poly in rois:
        cv2.fillPoly(overlay, [poly], (0, 255, 120))
    cv2.addWeighted(overlay, 0.12, frame, 0.88, 0, frame)

    # Dải phân cách: chỉ vẽ viền tím, không đo/đếm trong vùng này.
    cv2.polylines(frame, [median], True, (255, 0, 255), 3)
    cmed = np.mean(median, axis=0).astype(int)
    cv2.putText(frame, "MEDIAN - EXCLUDED", (max(5, int(cmed[0]) - 95), max(25, int(cmed[1]))),
                cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 0, 255), 2, cv2.LINE_AA)

    # Viền ROI từng chiều.
    for side, poly in rois:
        cv2.polylines(frame, [poly], True, (0, 255, 0), 3)
        c = np.mean(poly, axis=0).astype(int)
        cv2.putText(frame, f"ROI {side} ROAD", (max(5, int(c[0]) - 75), int(c[1]) + 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 255, 0), 2, cv2.LINE_AA)

    # Làn + vạch tốc độ A/B trong từng lane.
    for label, lane_poly, side in lane_items:
        cv2.polylines(frame, [lane_poly], True, (0, 180, 255), 2)
        c = np.mean(lane_poly, axis=0).astype(int)
        short = label.replace("LEFT", "L").replace("RIGHT", "R")
        cv2.putText(frame, short, (int(c[0]) - 40, int(c[1])),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 180, 255), 2, cv2.LINE_AA)

        seg_a = _noi_suy_canh(lane_poly, line_a_y)
        seg_b = _noi_suy_canh(lane_poly, line_b_y)
        if seg_a:
            ax0, ax1 = seg_a
            cv2.line(frame, (ax0 + 2, line_a_y), (ax1 - 2, line_a_y), (255, 255, 0), 2)
        if seg_b:
            bx0, bx1 = seg_b
            cv2.line(frame, (bx0 + 2, line_b_y), (bx1 - 2, line_b_y), (0, 255, 255), 2)

    cv2.putText(frame, "SPEED LINE A - ALL LANES", (30, line_a_y - 9),
                cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 0), 2, cv2.LINE_AA)
    cv2.putText(frame, f"SPEED LINE B - ALL LANES | {distance_m:.0f}m", (30, line_b_y - 9),
                cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 255, 255), 2, cv2.LINE_AA)


def _lane_speed_init_v3(self):
    if not hasattr(self, "speed_tracks_all_lanes_v3"):
        self.speed_tracks_all_lanes_v3 = {}
        self.speed_next_id_all_lanes_v3 = 1
        self.speed_done_all_lanes_v3 = []
        self.speed_by_lane_all_lanes_v3 = {}
        self.speed_distance_m_chuan = float(getattr(self, "speed_distance_m_chuan", 50.0))
        self.speed_track_timeout_frames = 60
        self.speed_min_kmh = 5.0
        self.speed_max_kmh = 180.0


def _match_track_v3(self, name, lane_label, bbox, foot, frame_idx):
    _lane_speed_init_v3(self)
    best_id, best_score = None, -1e9
    fx, fy = foot
    for tid, tr in list(self.speed_tracks_all_lanes_v3.items()):
        if frame_idx - tr.get("last_frame", frame_idx) > self.speed_track_timeout_frames:
            self.speed_tracks_all_lanes_v3.pop(tid, None)
            continue
        if tr.get("name") != name:
            continue
        if tr.get("lane") != lane_label:
            continue
        tx, ty = tr.get("foot", foot)
        dist = ((fx - tx) ** 2 + (fy - ty) ** 2) ** 0.5
        iou = _iou_v2(bbox, tr.get("bbox", bbox)) if "_iou_v2" in globals() else 0.0
        score = iou * 2.4 - dist / 170.0
        if score > best_score:
            best_id, best_score = tid, score
    if best_id is None or best_score < -0.30:
        best_id = self.speed_next_id_all_lanes_v3
        self.speed_next_id_all_lanes_v3 += 1
        self.speed_tracks_all_lanes_v3[best_id] = {
            "name": name, "lane": lane_label, "bbox": bbox, "foot": foot,
            "last_y": foot[1], "last_frame": frame_idx,
            "time_a": None, "time_b": None, "speed": None,
        }
    return best_id


def _update_track_v3(self, tid, lane_label, bbox, foot, line_a_y, line_b_y, t_sec, frame_idx):
    tr = self.speed_tracks_all_lanes_v3[tid]
    last_y = int(tr.get("last_y", foot[1]))
    cy = int(foot[1])

    crossed_a = (last_y <= line_a_y <= cy) or (last_y >= line_a_y >= cy)
    crossed_b = (last_y <= line_b_y <= cy) or (last_y >= line_b_y >= cy)

    # Ghi thời điểm qua từng vạch độc lập, đo được cả xe đi xuống ảnh và đi lên ảnh.
    if tr.get("time_a") is None and crossed_a:
        tr["time_a"] = float(t_sec)
    if tr.get("time_b") is None and crossed_b:
        tr["time_b"] = float(t_sec)

    if tr.get("speed") is None and tr.get("time_a") is not None and tr.get("time_b") is not None:
        dt = abs(float(tr["time_b"]) - float(tr["time_a"]))
        if dt > 0.08:
            kmh = (float(self.speed_distance_m_chuan) / dt) * 3.6
            if self.speed_min_kmh <= kmh <= self.speed_max_kmh:
                sp = round(kmh, 1)
                tr["speed"] = sp
                self.speed_done_all_lanes_v3.append(sp)
                self.speed_by_lane_all_lanes_v3.setdefault(lane_label, []).append(sp)
                self.speed_done_all_lanes_v3 = self.speed_done_all_lanes_v3[-160:]
                for k in list(self.speed_by_lane_all_lanes_v3.keys()):
                    self.speed_by_lane_all_lanes_v3[k] = self.speed_by_lane_all_lanes_v3[k][-80:]

    tr["bbox"] = bbox
    tr["foot"] = foot
    tr["last_y"] = cy
    tr["last_frame"] = frame_idx
    tr["lane"] = lane_label
    return tr.get("speed")


try:
    _base_detect_all_lanes_no_median_v3 = globals().get(
        "_base_detect_all_lanes_speed",
        globals().get("_goc_xu_ly_khung_hinh_final_speed", XuLyVideo.xu_ly_khung_hinh)
    )

    def _xu_ly_khung_hinh_all_lanes_no_median_v3(self, frame):
        # Chạy detection gốc trước, sau đó tự vẽ ROI/lane đúng; không dùng ROI sai cũ.
        frame = _base_detect_all_lanes_no_median_v3(self, frame)
        try:
            _lane_speed_init_v3(self)
            h, w = frame.shape[:2]
            t_sec = self.frame_idx / self.fps_video if getattr(self, "fps_video", 0) else time.time()
            rois, median, lane_items = _all_lane_items_v3(w, h, lane_count=3)
            line_a_y = int(h * 0.47)
            line_b_y = int(h * 0.70)

            _draw_roi_all_lanes_no_median_v3(
                frame, rois, median, lane_items,
                line_a_y, line_b_y, float(self.speed_distance_m_chuan)
            )

            lane_counts_v3 = {label: 0 for label, _, _ in lane_items}
            boxes = list(getattr(self, "last_inference_boxes", []) or [])
            for b in boxes:
                if len(b) < 11:
                    continue
                x1b, y1b, x2b, y2b, name, confv, color, cx, cy, in_roi, old_lane = b[:11]
                foot = (int((x1b + x2b) / 2), int(y2b - 0.04 * (y2b - y1b)))
                lane_label, side = _find_lane_v3(foot, lane_items)
                if lane_label is None:
                    continue

                lane_counts_v3[lane_label] = lane_counts_v3.get(lane_label, 0) + 1
                bbox = (int(x1b), int(y1b), int(x2b), int(y2b))
                tid = _match_track_v3(self, str(name), lane_label, bbox, foot, self.frame_idx)
                sp = _update_track_v3(self, tid, lane_label, bbox, foot, line_a_y, line_b_y, t_sec, self.frame_idx)

                if sp is None:
                    txt = f"ID {tid} | {lane_label} | measuring"
                    tc = (255, 255, 0)
                else:
                    txt = f"ID {tid} | {lane_label} | {sp:.1f} km/h"
                    tc = (0, 255, 255)
                cv2.circle(frame, foot, 5, tc, -1)
                cv2.putText(frame, txt, (int(x1b), min(h - 8, int(y2b) + 22)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.47, tc, 2, cv2.LINE_AA)

            speeds_all = list(self.speed_done_all_lanes_v3 or [])
            by_lane = self.speed_by_lane_all_lanes_v3
            if speeds_all:
                last30 = speeds_all[-30:]
                avg_speed = round(sum(last30) / len(last30), 1)
                max_speed = round(max(speeds_all), 1)
                min_speed = round(min(speeds_all), 1)
                speed_text = f"SPEED AVG {avg_speed:.1f} km/h | MAX {max_speed:.1f} | measured {len(speeds_all)}"
            else:
                avg_speed = max_speed = min_speed = 0.0
                speed_text = "SPEED: waiting vehicles cross A+B in any lane"

            cv2.rectangle(frame, (20, 18), (880, 58), (0, 0, 0), -1)
            cv2.putText(frame, speed_text, (30, 48),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.72, (0, 255, 255), 2, cv2.LINE_AA)

            lane_speed_texts = []
            for label, _, _ in lane_items:
                arr = by_lane.get(label, [])
                short = label.replace("LEFT", "L").replace("RIGHT", "R")
                if arr:
                    lane_speed_texts.append(f"{short}:{round(sum(arr[-10:]) / len(arr[-10:]), 1)}km/h/{len(arr)}xe")
                else:
                    lane_speed_texts.append(f"{short}:cho")
            cv2.putText(frame, " | ".join(lane_speed_texts[:3]), (30, 82),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 255, 255), 2, cv2.LINE_AA)
            cv2.putText(frame, " | ".join(lane_speed_texts[3:]), (30, 108),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 255, 255), 2, cv2.LINE_AA)

            stats = dict(getattr(self, "last_stats", {}) or {})
            lane_avg = {}
            lane_measured = {}
            for label, _, _ in lane_items:
                arr = by_lane.get(label, [])
                lane_avg[label] = round(sum(arr[-10:]) / len(arr[-10:]), 1) if arr else 0.0
                lane_measured[label] = len(arr)
            stats.update({
                "lane_counts": lane_counts_v3,
                "toc_do_tb_kmh": avg_speed,
                "toc_do_cao_nhat_kmh": max_speed,
                "toc_do_thap_nhat_kmh": min_speed,
                "toc_do_xe_danh_sach": speeds_all[-10:],
                "so_xe_da_do_toc_do": len(speeds_all),
                "toc_do_theo_lan": lane_avg,
                "so_xe_da_do_theo_lan": lane_measured,
                "speed_distance_m": float(self.speed_distance_m_chuan),
                "speed_note": "ROI phủ tất cả làn hai chiều, loại trừ dải phân cách giữa. Đo tốc độ A/B độc lập cho mọi lane.",
                "reason": str(stats.get("reason", "")) + " | ROI=all-lanes-no-median | speed=all-lanes",
            })
            self.last_stats = stats
            try:
                self.statsReady.emit(self.last_stats)
            except Exception:
                pass
        except Exception as e:
            try:
                self.them_nhat_ky(f"[ALL LANES NO MEDIAN] Lỗi: {e}")
            except Exception:
                pass
        return frame

    XuLyVideo.xu_ly_khung_hinh = _xu_ly_khung_hinh_all_lanes_no_median_v3
except Exception as e:
    print("[ALL LANES NO MEDIAN] Không thể cài hotfix:", e)




# =========================================================
# FINAL OVERRIDE - ROI CHUAN TAT CA LAN, BO GIAI PHAN CACH + DO TOC DO
# Patch cuối cùng: không gọi các pipeline ROI cũ để tránh vẽ chồng/sai.
# ROI gồm 2 phần đường chạy hai chiều, loại trừ dải phân cách giữa.
# Tốc độ đo theo 2 vạch A/B trong từng làn, có tracking đơn giản theo bbox.
# =========================================================
def _final_roi_chuan_bo_median(w, h):
    """
    ROI cuối cùng dùng cho video cao tốc 2 chiều.
    Dải phân cách tím + 2 vùng đường chạy được đọc từ data_v5/roi_road_config.json.
    Chỉnh JSON là đủ, khỏi đào mộ 11 nghìn dòng code như khảo cổ phần mềm.
    """
    cfg = doc_cau_hinh_roi_duong()
    y_top = _clamp_ratio(cfg.get("y_top", 0.36), 0.05, 0.95)
    y_bot = _clamp_ratio(cfg.get("y_bot", 0.92), y_top + 0.05, 0.99)

    left_cfg = cfg.get("left_road", {})
    right_cfg = cfg.get("right_road", {})
    med_cfg = cfg.get("median", {})

    left_road = np.array([
        [int(w * _clamp_ratio(left_cfg.get("top_left_x", 0.04))), int(h * y_top)],
        [int(w * _clamp_ratio(left_cfg.get("top_right_x", 0.490))), int(h * y_top)],
        [int(w * _clamp_ratio(left_cfg.get("bottom_right_x", 0.430))), int(h * y_bot)],
        [int(w * _clamp_ratio(left_cfg.get("bottom_left_x", 0.000))), int(h * y_bot)],
    ], dtype=np.int32)

    right_road = np.array([
        [int(w * _clamp_ratio(right_cfg.get("top_left_x", 0.595))), int(h * y_top)],
        [int(w * _clamp_ratio(right_cfg.get("top_right_x", 0.985))), int(h * y_top)],
        [int(w * _clamp_ratio(right_cfg.get("bottom_right_x", 1.000))), int(h * y_bot)],
        [int(w * _clamp_ratio(right_cfg.get("bottom_left_x", 0.570))), int(h * y_bot)],
    ], dtype=np.int32)

    median = np.array([
        [int(w * _clamp_ratio(med_cfg.get("top_left_x", 0.490))), int(h * y_top)],
        [int(w * _clamp_ratio(med_cfg.get("top_right_x", 0.595))), int(h * y_top)],
        [int(w * _clamp_ratio(med_cfg.get("bottom_right_x", 0.570))), int(h * y_bot)],
        [int(w * _clamp_ratio(med_cfg.get("bottom_left_x", 0.430))), int(h * y_bot)],
    ], dtype=np.int32)

    return [("LEFT", left_road), ("RIGHT", right_road)], median


def _final_split_lanes(side, poly, n=3):
    tl, tr, br, bl = [np.array(p, dtype=np.float32) for p in poly]
    out = []
    for i in range(n):
        t0 = i / n
        t1 = (i + 1) / n
        p0t = tl + (tr - tl) * t0
        p1t = tl + (tr - tl) * t1
        p1b = bl + (br - bl) * t1
        p0b = bl + (br - bl) * t0
        lane = np.array([p0t, p1t, p1b, p0b], dtype=np.int32)
        out.append((f"{side} Lane {i}", lane, side))
    return out


def _final_all_lanes(w, h):
    rois, median = _final_roi_chuan_bo_median(w, h)
    lanes = []
    for side, poly in rois:
        lanes.extend(_final_split_lanes(side, poly, 3))
    return rois, median, lanes


def _final_point_in_poly(pt, poly):
    return cv2.pointPolygonTest(poly.astype(np.float32), (float(pt[0]), float(pt[1])), False) >= 0


def _final_find_lane(pt, lanes):
    for label, poly, side in lanes:
        if _final_point_in_poly(pt, poly):
            return label, side, poly
    return None, None, None


def _final_lane_x_segment(poly, y):
    pts = poly.astype(np.float32)
    xs = []
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        if (y1 <= y <= y2) or (y2 <= y <= y1):
            if abs(y2 - y1) < 1e-6:
                xs.extend([x1, x2])
            else:
                t = (y - y1) / (y2 - y1)
                xs.append(x1 + t * (x2 - x1))
    if len(xs) < 2:
        return None
    return int(min(xs)), int(max(xs))


def _final_draw_roi(frame, rois, median, lanes, line_a_y, line_b_y, distance_m):
    overlay = frame.copy()
    for side, poly in rois:
        cv2.fillPoly(overlay, [poly], (0, 255, 120))
    cv2.addWeighted(overlay, 0.15, frame, 0.85, 0, frame)

    # Dải phân cách: không tô xanh, chỉ khoanh tím để thấy vùng bị loại trừ.
    cv2.polylines(frame, [median], True, (255, 0, 255), 3)
    cm = np.mean(median, axis=0).astype(int)
    cv2.putText(frame, "GIAI PHAN CACH - KHONG DO", (max(5, cm[0] - 140), max(25, cm[1])),
                cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 0, 255), 2, cv2.LINE_AA)

    for side, poly in rois:
        cv2.polylines(frame, [poly], True, (0, 255, 0), 3)
        c = np.mean(poly, axis=0).astype(int)
        cv2.putText(frame, f"ROI {side} ROAD", (max(5, c[0] - 70), c[1]),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 255, 0), 2, cv2.LINE_AA)

    for label, poly, side in lanes:
        cv2.polylines(frame, [poly], True, (0, 180, 255), 2)
        c = np.mean(poly, axis=0).astype(int)
        short = label.replace("LEFT", "L").replace("RIGHT", "R")
        cv2.putText(frame, short, (c[0] - 32, c[1]),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 180, 255), 2, cv2.LINE_AA)
        for y, color in [(line_a_y, (255, 255, 0)), (line_b_y, (0, 255, 255))]:
            seg = _final_lane_x_segment(poly, y)
            if seg:
                x0, x1 = seg
                cv2.line(frame, (x0 + 2, y), (x1 - 2, y), color, 2)

    cv2.putText(frame, "SPEED LINE A - MOI LAN", (30, line_a_y - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 0), 2, cv2.LINE_AA)
    cv2.putText(frame, f"SPEED LINE B - MOI LAN | {distance_m:.0f}m", (30, line_b_y - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 255, 255), 2, cv2.LINE_AA)


def _final_speed_init(self):
    if not hasattr(self, "speed_tracks_final_roi"):
        self.speed_tracks_final_roi = {}
        self.speed_next_id_final_roi = 1
        self.speed_done_final_roi = []
        self.speed_by_lane_final_roi = {}
        self.speed_distance_m_chuan = float(getattr(self, "speed_distance_m_chuan", 50.0))
        self.speed_track_timeout_frames = 75
        self.speed_min_kmh = 5.0
        self.speed_max_kmh = 180.0


def _final_iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    area_a = max(1, (ax2 - ax1) * (ay2 - ay1))
    area_b = max(1, (bx2 - bx1) * (by2 - by1))
    return inter / max(1, area_a + area_b - inter)


def _final_match_track(self, name, lane, bbox, foot):
    _final_speed_init(self)
    fx, fy = foot
    best, best_score = None, -1e9
    for tid, tr in list(self.speed_tracks_final_roi.items()):
        if self.frame_idx - tr.get("last_frame", self.frame_idx) > self.speed_track_timeout_frames:
            self.speed_tracks_final_roi.pop(tid, None)
            continue
        if tr.get("name") != name or tr.get("lane") != lane:
            continue
        tx, ty = tr.get("foot", foot)
        dist = ((fx - tx) ** 2 + (fy - ty) ** 2) ** 0.5
        score = _final_iou(bbox, tr.get("bbox", bbox)) * 2.2 - dist / 150.0
        if score > best_score:
            best, best_score = tid, score
    if best is None or best_score < -0.35:
        best = self.speed_next_id_final_roi
        self.speed_next_id_final_roi += 1
        self.speed_tracks_final_roi[best] = {
            "name": name, "lane": lane, "bbox": bbox, "foot": foot,
            "last_y": foot[1], "last_frame": self.frame_idx,
            "time_a": None, "time_b": None, "speed": None,
        }
    return best


def _final_update_speed(self, tid, lane, bbox, foot, line_a_y, line_b_y, t_sec):
    tr = self.speed_tracks_final_roi[tid]
    last_y = int(tr.get("last_y", foot[1]))
    cy = int(foot[1])
    crossed_a = (last_y <= line_a_y <= cy) or (last_y >= line_a_y >= cy)
    crossed_b = (last_y <= line_b_y <= cy) or (last_y >= line_b_y >= cy)
    if tr.get("time_a") is None and crossed_a:
        tr["time_a"] = float(t_sec)
    if tr.get("time_b") is None and crossed_b:
        tr["time_b"] = float(t_sec)
    if tr.get("speed") is None and tr.get("time_a") is not None and tr.get("time_b") is not None:
        dt = abs(float(tr["time_b"]) - float(tr["time_a"]))
        if dt > 0.08:
            kmh = float(self.speed_distance_m_chuan) / dt * 3.6
            if self.speed_min_kmh <= kmh <= self.speed_max_kmh:
                sp = round(kmh, 1)
                tr["speed"] = sp
                self.speed_done_final_roi.append(sp)
                self.speed_done_final_roi = self.speed_done_final_roi[-200:]
                self.speed_by_lane_final_roi.setdefault(lane, []).append(sp)
                self.speed_by_lane_final_roi[lane] = self.speed_by_lane_final_roi[lane][-80:]
    tr.update({"lane": lane, "bbox": bbox, "foot": foot, "last_y": cy, "last_frame": self.frame_idx})
    return tr.get("speed")


def _final_process_frame_roi_speed(self, frame):
    try:
        _final_speed_init(self)
        h, w = frame.shape[:2]
        clean = frame.copy()
        t_sec = self.frame_idx / self.fps_video if getattr(self, "fps_video", 0) else time.time()
        rois, median, lanes = _final_all_lanes(w, h)
        line_a_y = int(h * 0.43)
        line_b_y = int(h * 0.68)

        class_counts = {name: 0 for name in VEHICLE_CLASSES}
        lane_counts = {label: 0 for label, _, _ in lanes}
        boxes = []
        total_in_roi = 0

        if getattr(self, "model", None) is not None:
            device = "cuda:0" if self.config.detection.use_gpu and CUDA_AVAILABLE else "cpu"
            res = self.model.predict(
                clean,
                imgsz=max(960, int(getattr(self.config.detection, "imgsz", 960))),
                conf=min(0.15, float(getattr(self.config.detection, "conf_th", 0.15))),
                device=device,
                half=bool(self.config.detection.use_gpu and CUDA_AVAILABLE),
                verbose=False,
            )[0]
            if res.boxes is not None and res.boxes.xyxy is not None:
                xyxy = res.boxes.xyxy.cpu().numpy()
                cls = res.boxes.cls.cpu().numpy()
                confs = res.boxes.conf.cpu().numpy()
                for box, cls_id, confv in zip(xyxy, cls, confs):
                    raw = self.name_map.get(int(cls_id), str(cls_id)) if isinstance(self.name_map, dict) else str(cls_id)
                    name = chuan_hoa_ten_xe(raw)
                    if name is None:
                        continue
                    x1, y1, x2, y2 = map(int, box)
                    foot = (int((x1 + x2) / 2), int(y2 - 0.04 * (y2 - y1)))
                    lane_label, side, _ = _final_find_lane(foot, lanes)
                    in_roi = lane_label is not None
                    color = (0, 255, 102) if in_roi else (130, 130, 130)
                    sp = None
                    tid = None
                    if in_roi:
                        total_in_roi += 1
                        class_counts[name] += 1
                        lane_counts[lane_label] = lane_counts.get(lane_label, 0) + 1
                        tid = _final_match_track(self, name, lane_label, (x1, y1, x2, y2), foot)
                        sp = _final_update_speed(self, tid, lane_label, (x1, y1, x2, y2), foot, line_a_y, line_b_y, t_sec)
                    boxes.append((x1, y1, x2, y2, name, float(confv), color, foot[0], foot[1], in_roi, lane_label, tid, sp))

        self.last_inference_boxes = [(b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7], b[8], b[9], b[10]) for b in boxes]

        _final_draw_roi(clean, rois, median, lanes, line_a_y, line_b_y, float(self.speed_distance_m_chuan))

        for x1, y1, x2, y2, name, confv, color, fx, fy, in_roi, lane_label, tid, sp in boxes:
            cv2.rectangle(clean, (x1, y1), (x2, y2), color, 2 if in_roi else 1)
            cv2.circle(clean, (fx, fy), 5, (0, 255, 255) if in_roi else color, -1)
            label = f"{name} {confv:.2f}"
            if in_roi:
                label += f" | ID {tid} | {lane_label}"
                label += f" | {sp:.1f} km/h" if sp is not None else " | measuring"
            cv2.putText(clean, label, (x1, max(24, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.50, color, 2, cv2.LINE_AA)

        self.vehicle_history.append(total_in_roi)
        avg_vehicles = round(sum(self.vehicle_history) / max(1, len(self.vehicle_history))) if self.vehicle_history else 0
        density, vsl_speed, traffic_state, reason = tinh_vsl_theo_ngu_canh(avg_vehicles, class_counts, self.config.vsl)
        sudden_increase = (avg_vehicles - self.prev_avg_vehicles) >= self.sudden_increase_threshold
        self.prev_avg_vehicles = avg_vehicles
        priority = tinh_muc_do_uu_tien(density, traffic_state, self.config.vsl.weather, self.config.vsl.incident, sudden_increase, vsl_speed)

        speeds = list(self.speed_done_final_roi or [])
        if speeds:
            last30 = speeds[-30:]
            avg_speed = round(sum(last30) / len(last30), 1)
            max_speed = round(max(speeds), 1)
            min_speed = round(min(speeds), 1)
            speed_text = f"SPEED AVG {avg_speed:.1f} km/h | MAX {max_speed:.1f} | measured {len(speeds)}"
        else:
            avg_speed = max_speed = min_speed = 0.0
            speed_text = "SPEED: dang cho xe cat du 2 vach A/B"
        cv2.rectangle(clean, (20, 18), (760, 58), (0, 0, 0), -1)
        cv2.putText(clean, speed_text, (30, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.70, (0, 255, 255), 2, cv2.LINE_AA)

        by_lane_avg = {}
        by_lane_n = {}
        lane_line = []
        for label, _, _ in lanes:
            arr = self.speed_by_lane_final_roi.get(label, [])
            by_lane_avg[label] = round(sum(arr[-10:]) / len(arr[-10:]), 1) if arr else 0.0
            by_lane_n[label] = len(arr)
            short = label.replace("LEFT", "L").replace("RIGHT", "R")
            lane_line.append(f"{short}:{by_lane_avg[label]}km/h/{by_lane_n[label]}")
        cv2.putText(clean, " | ".join(lane_line[:3]), (30, 82), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(clean, " | ".join(lane_line[3:]), (30, 106), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 255, 255), 2, cv2.LINE_AA)

        self.last_stats = {
            "vehicles_in_roi": total_in_roi,
            "avg_vehicles": avg_vehicles,
            "density": density,
            "traffic_state": traffic_state,
            "suggested_vsl": vsl_speed,
            "priority": priority,
            "sudden_increase": sudden_increase,
            "reason": f"{reason} | ROI=2 chieu, bo giai phan cach | speed=A/B moi lane",
            "class_counts": class_counts,
            "lane_counts": lane_counts,
            "fps_est": round(getattr(self, "fps_est", 0.0), 1),
            "warning_count": self.warning_count,
            "snapshot_count": self.snapshot_count,
            "event_count": self.event_count,
            "summary_html_path": str(self.summary_html_path),
            "camera_id": self.camera_id,
            "toc_do_tb_kmh": avg_speed,
            "toc_do_cao_nhat_kmh": max_speed,
            "toc_do_thap_nhat_kmh": min_speed,
            "so_xe_da_do_toc_do": len(speeds),
            "toc_do_xe_danh_sach": speeds[-10:],
            "toc_do_theo_lan": by_lane_avg,
            "so_xe_da_do_theo_lan": by_lane_n,
            "speed_distance_m": float(self.speed_distance_m_chuan),
            "do_tin_cay_ai": round(sum([b[5] for b in boxes]) / max(1, len(boxes)) * 100, 1) if boxes else 0.0,
        }
        self.statsReady.emit(self.last_stats)
        return clean
    except Exception as e:
        try:
            self.them_nhat_ky(f"[FINAL ROI SPEED] Loi: {e}")
        except Exception:
            pass
        return frame

try:
    XuLyVideo.xu_ly_khung_hinh = _final_process_frame_roi_speed
    print("[FINAL ROI SPEED] Da cai dat ROI chuan + do toc do moi lane")
except Exception as e:
    print("[FINAL ROI SPEED] Khong the cai dat:", e)


# =========================================================
# PATCH ỔN ĐỊNH CHẾ ĐỘ CHẠY: VIDEO THỦ CÔNG / ĐA CAMERA
# Mục tiêu:
# - VIDEO thủ công và MULTI camera không còn chạy song song.
# - Khi chuyển chế độ sẽ dừng sạch thread cũ, xóa frame cũ, reset stats cũ.
# - Không dùng chung trạng thái đang chạy giữa self.worker và self.multi_worker.
# - Không để combobox camera tự đè video thủ công khi đang chạy video.
# =========================================================

def _run_set_badge(widget, text, object_name=None):
    try:
        widget.setText(text)
        if object_name:
            widget.setObjectName(object_name)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
    except Exception:
        pass


def _run_append_log(self, text):
    try:
        self.append_log(text)
    except Exception:
        try:
            print(text)
        except Exception:
            pass


def _run_clear_video_view(self, text="Video giám sát sẽ hiển thị tại đây"):
    try:
        self.video_label.clear()
        self.video_label.setText(text)
        self.video_label.show()
    except Exception:
        pass


def _run_reset_runtime_state(self):
    """Reset dữ liệu hiển thị giữa 2 chế độ, không reset cấu hình AI/ROI/VSL."""
    try:
        self.camera_stats = {}
        self.camera_frames = {}
    except Exception:
        pass

    try:
        for label in getattr(self, "camera_labels", {}).values():
            try:
                label.deleteLater()
            except Exception:
                pass
        self.camera_labels = {}
    except Exception:
        pass


def _run_stop_single_worker(self, timeout_ms=3500, clear_view=False):
    """Dừng worker video thủ công/camera đơn."""
    worker = getattr(self, "worker", None)
    if worker is None:
        return True

    try:
        worker.yeu_cau_dung()
        worker.dat_tam_dung(False)
    except Exception:
        pass

    try:
        if worker.isRunning():
            deadline = time.time() + timeout_ms / 1000.0
            while worker.isRunning() and time.time() < deadline:
                QtWidgets.QApplication.processEvents()
                worker.wait(50)

        if worker.isRunning():
            try:
                worker.terminate()
                worker.wait(1000)
            except Exception:
                pass
    except Exception as e:
        _run_append_log(self, f"[RUN] Lỗi dừng worker đơn: {e}")

    self.worker = None

    if clear_view:
        _run_clear_video_view(self)

    return True


def _run_stop_multi_worker(self, timeout_ms=4000, clear_view=False):
    """Dừng toàn bộ worker đa camera."""
    multi = getattr(self, "multi_worker", None)
    if multi is None:
        return True

    try:
        multi.dung()
    except Exception as e:
        _run_append_log(self, f"[RUN] Lỗi dừng đa camera: {e}")

    self.multi_worker = None
    _run_reset_runtime_state(self)

    if clear_view:
        _run_clear_video_view(self)

    return True


def _run_controls_for_mode(self, mode):
    """Khóa/mở nút để tránh đổi nguồn khi đang chạy."""
    try:
        if mode == "MULTI":
            self.btn_open_video.setEnabled(False)
            self.btn_start.setEnabled(False)
            self.cbo_camera.setEnabled(False)
            self.btn_pause.setEnabled(False)
        elif mode == "SINGLE_RUNNING":
            self.btn_open_video.setEnabled(False)
            self.cbo_camera.setEnabled(False)
            self.btn_start.setEnabled(False)
            self.btn_pause.setEnabled(True)
        else:
            self.btn_open_video.setEnabled(True)
            self.cbo_camera.setEnabled(True)
            self.btn_start.setEnabled(True)
            self.btn_pause.setEnabled(True)
    except Exception:
        pass


def _run_on_open_video(self):
    """Chọn video thủ công: dừng đa camera trước, chọn nguồn VIDEO_THU_CONG."""
    if getattr(self, "multi_worker", None) is not None:
        ok = QtWidgets.QMessageBox.question(
            self,
            "Đổi sang video thủ công",
            "Đa camera đang chạy. Hệ thống sẽ dừng tất cả camera trước khi chọn video thủ công. Tiếp tục?",
        )
        if ok != QtWidgets.QMessageBox.Yes:
            return
        _run_stop_multi_worker(self, clear_view=True)

    # Nếu video/camera đơn đang chạy, dừng sạch trước khi đổi file.
    if getattr(self, "worker", None) is not None:
        ok = QtWidgets.QMessageBox.question(
            self,
            "Đổi video",
            "Phiên hiện tại đang chạy hoặc đang dừng. Hệ thống sẽ dừng hẳn rồi mở video mới. Tiếp tục?",
        )
        if ok != QtWidgets.QMessageBox.Yes:
            return
        _run_stop_single_worker(self, clear_view=True)

    fn, _ = QtWidgets.QFileDialog.getOpenFileName(
        self,
        "Chọn video",
        "",
        "Video files (*.mp4 *.avi *.mkv *.mov);;All files (*)",
    )

    if not fn:
        return

    self.che_do_chay = "SINGLE"
    self.camera_hien_tai = None
    self.video_path = fn

    try:
        self.cbo_camera.blockSignals(True)
        self.cbo_camera.setCurrentIndex(0)
        self.cbo_camera.blockSignals(False)
    except Exception:
        pass

    try:
        self.lbl_video_name.setText(f"Video: {Path(fn).name}")
        cap = cv2.VideoCapture(fn)
        if cap.isOpened():
            ww = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            hh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self.lbl_video_res.setText(f"Resolution: {ww} x {hh}")
        else:
            self.lbl_video_res.setText("Resolution: - x -")
        cap.release()
    except Exception:
        pass

    _run_clear_video_view(self, "Video đã chọn. Bấm Bắt đầu phân tích.")
    _run_controls_for_mode(self, "READY")
    _run_set_badge(self.hero_badge_status, "TRẠNG THÁI: ĐÃ CHỌN VIDEO")
    try:
        self.lbl_status.setText("Đã chọn video thủ công.")
    except Exception:
        pass
    _run_append_log(self, f"[MODE] Đã chọn VIDEO_THỦ_CÔNG: {Path(fn).name}")


def _run_on_chon_camera(self):
    """Chọn camera đơn: chỉ đổi nguồn khi không chạy đa camera/video."""
    if getattr(self, "multi_worker", None) is not None and self.multi_worker.dang_chay():
        QtWidgets.QMessageBox.warning(
            self,
            "Đang chạy đa camera",
            "Bạn đang chạy đa camera. Hãy bấm Dừng hệ thống trước khi đổi camera.",
        )
        try:
            self.cbo_camera.blockSignals(True)
            self.cbo_camera.setCurrentIndex(0)
            self.cbo_camera.blockSignals(False)
        except Exception:
            pass
        return

    if getattr(self, "worker", None) is not None:
        QtWidgets.QMessageBox.warning(
            self,
            "Đang chạy video",
            "Bạn đang chạy video/camera đơn. Hãy bấm Dừng hệ thống trước khi đổi camera.",
        )
        return

    camera_id = self.cbo_camera.currentData()

    if not camera_id:
        self.camera_hien_tai = None
        return

    cam = self.quan_ly_camera.lay_camera_theo_id(camera_id)
    if cam is None:
        return

    if not os.path.exists(cam.duong_dan_video):
        QtWidgets.QMessageBox.warning(
            self,
            "Lỗi camera",
            f"Không thấy nguồn camera/video:\n{cam.duong_dan_video}",
        )
        return

    self.che_do_chay = "SINGLE"
    self.camera_hien_tai = cam
    self.video_path = cam.duong_dan_video

    try:
        self.lbl_video_name.setText(f"Camera: {cam.ten_camera}")
        self.lbl_video_res.setText(f"Vị trí: {cam.vi_tri}")
    except Exception:
        pass

    _run_clear_video_view(self, f"Đã chọn {cam.ten_camera}. Bấm Bắt đầu phân tích.")
    _run_controls_for_mode(self, "READY")
    _run_set_badge(self.hero_badge_status, "TRẠNG THÁI: ĐÃ CHỌN CAMERA")
    try:
        self.lbl_status.setText("Đã chọn camera đơn.")
    except Exception:
        pass
    _run_append_log(self, f"[MODE] Đã chọn CAMERA_ĐƠN: {cam.camera_id} - {cam.ten_camera}")


def _run_on_start(self):
    """Start chế độ SINGLE: video thủ công hoặc camera đơn."""
    # Đảm bảo đa camera chết hẳn trước khi chạy single.
    if getattr(self, "multi_worker", None) is not None:
        _run_stop_multi_worker(self, clear_view=True)
        _run_append_log(self, "[MODE] Đã dừng đa camera để chạy chế độ đơn.")

    if getattr(self, "worker", None) is not None:
        try:
            if self.worker.isRunning():
                return
        except Exception:
            _run_stop_single_worker(self, clear_view=False)

    if not getattr(self, "video_path", None) or not os.path.isfile(self.video_path):
        QtWidgets.QMessageBox.warning(self, "Lỗi", "Chưa chọn video/camera hoặc đường dẫn không hợp lệ.")
        return

    self.che_do_chay = "SINGLE"
    try:
        self.log_view.clear()
    except Exception:
        pass

    camera_id = self.camera_hien_tai.camera_id if getattr(self, "camera_hien_tai", None) else "VIDEO_THU_CONG"

    self.worker = XuLyVideo(
        self.video_path,
        self.config,
        self.session_user,
        camera_id=camera_id,
    )

    self.worker.frameReady.connect(self.show_frame)
    self.worker.statsReady.connect(self.update_ui_from_stats)
    self.worker.statusReady.connect(self.on_worker_status)
    self.worker.logReady.connect(self.append_log)
    self.worker.errorReady.connect(self.on_worker_error)
    self.worker.finishedCleanly.connect(self.on_worker_finished)

    self.worker.start()

    _run_controls_for_mode(self, "SINGLE_RUNNING")
    try:
        self.btn_pause.setText("Tạm dừng")
    except Exception:
        pass
    _run_set_badge(self.hero_badge_status, "TRẠNG THÁI: ĐANG CHẠY")
    _run_set_badge(self.badge_live, "TRỰC TUYẾN: BẬT", "BadgeGreen")
    try:
        self.lbl_status.setText("Đang phân tích nguồn đơn...")
    except Exception:
        pass
    _run_append_log(self, f"[MODE] START SINGLE | camera_id={camera_id} | source={self.video_path}")


def _run_on_start_multi_camera(self):
    """Start MULTI: dừng single trước, không cho video thủ công chạy song song."""
    if getattr(self, "multi_worker", None) is not None and self.multi_worker.dang_chay():
        _run_append_log(self, "[MULTI-CAMERA] Đa camera đang chạy.")
        return

    if getattr(self, "worker", None) is not None:
        _run_stop_single_worker(self, clear_view=True)
        _run_append_log(self, "[MODE] Đã dừng video/camera đơn để chạy đa camera.")

    danh_sach_camera = self.quan_ly_camera.lay_camera_dang_bat()
    danh_sach_camera = [cam for cam in danh_sach_camera if os.path.exists(cam.duong_dan_video)]

    if not danh_sach_camera:
        QtWidgets.QMessageBox.warning(self, "Lỗi", "Không có camera nào được bật hoặc không thấy file nguồn camera.")
        self.che_do_chay = "SINGLE"
        _run_controls_for_mode(self, "READY")
        return

    self.che_do_chay = "MULTI"
    _run_reset_runtime_state(self)
    _run_clear_video_view(self, "Đang chạy đa camera...")

    self.multi_worker = MultiCameraWorker(
        danh_sach_camera=danh_sach_camera,
        config=self.config,
        session_user=self.session_user,
    )

    self.multi_worker.frameCameraReady.connect(self.on_multi_camera_frame)
    self.multi_worker.statsCameraReady.connect(self.on_multi_camera_stats)
    self.multi_worker.logCameraReady.connect(self.append_log)
    self.multi_worker.bat_dau()

    _run_controls_for_mode(self, "MULTI")
    _run_set_badge(self.hero_badge_status, "TRẠNG THÁI: ĐA CAMERA")
    _run_set_badge(self.badge_live, "TRỰC TUYẾN: ĐA CAMERA", "BadgeGreen")
    try:
        self.lbl_status.setText("Đang chạy đa camera...")
    except Exception:
        pass
    _run_append_log(self, f"[MULTI-CAMERA] Đã chạy {len(danh_sach_camera)} camera.")


def _run_on_pause_resume(self):
    if getattr(self, "worker", None) is None:
        return
    try:
        if self.btn_pause.text() == "Tạm dừng":
            self.worker.dat_tam_dung(True)
            self.btn_pause.setText("Tiếp tục")
            _run_set_badge(self.hero_badge_status, "TRẠNG THÁI: TẠM DỪNG")
            _run_set_badge(self.badge_live, "TRỰC TUYẾN: TẠM DỪNG", "BadgeAmber")
            self.lbl_status.setText("Đã tạm dừng.")
        else:
            self.worker.dat_tam_dung(False)
            self.btn_pause.setText("Tạm dừng")
            _run_set_badge(self.hero_badge_status, "TRẠNG THÁI: ĐANG CHẠY")
            _run_set_badge(self.badge_live, "TRỰC TUYẾN: BẬT", "BadgeGreen")
            self.lbl_status.setText("Đang chạy...")
    except Exception as e:
        _run_append_log(self, f"[RUN] Lỗi tạm dừng/tiếp tục: {e}")


def _run_on_stop(self):
    """Dừng tuyệt đối cả single và multi."""
    _run_stop_multi_worker(self, clear_view=False)
    _run_stop_single_worker(self, clear_view=False)

    self.che_do_chay = "SINGLE"
    _run_reset_runtime_state(self)
    _run_controls_for_mode(self, "READY")

    try:
        self.btn_pause.setText("Tạm dừng")
    except Exception:
        pass

    _run_clear_video_view(self)
    _run_set_badge(self.hero_badge_status, "TRẠNG THÁI: ĐÃ DỪNG")
    _run_set_badge(self.badge_live, "TRỰC TUYẾN: TẮT", "BadgeRed")
    try:
        self.lbl_status.setText("Đã dừng hệ thống.")
    except Exception:
        pass
    _run_append_log(self, "[MODE] Đã dừng toàn bộ worker VIDEO/CAMERA.")


def _run_on_worker_finished(self, summary):
    """Khi worker single kết thúc, không động vào multi."""
    try:
        self.worker = None
    except Exception:
        pass

    if getattr(self, "che_do_chay", "SINGLE") != "MULTI":
        _run_controls_for_mode(self, "READY")
        try:
            self.btn_pause.setText("Tạm dừng")
        except Exception:
            pass
        _run_set_badge(self.badge_live, "TRỰC TUYẾN: TẮT", "BadgeRed")
        _run_set_badge(self.hero_badge_status, "TRẠNG THÁI: ĐÃ DỪNG")
        try:
            self.lbl_status.setText("Đã kết thúc phiên.")
        except Exception:
            pass

    try:
        if isinstance(summary, dict) and summary.get("summary_html_path"):
            self.lbl_report.setText(f"Báo cáo mới nhất: {summary.get('summary_html_path')}")
    except Exception:
        pass


def _run_on_multi_camera_frame(self, camera_id, qimg):
    """Chỉ nhận frame multi khi đang ở chế độ MULTI."""
    if getattr(self, "che_do_chay", "SINGLE") != "MULTI":
        return

    self.camera_frames[camera_id] = qimg
    items = list(self.camera_frames.items())
    if not items:
        return

    cell_w = 520
    cell_h = 300
    canvas_w = cell_w * 2
    canvas_h = cell_h * 2
    mosaic = QtGui.QPixmap(canvas_w, canvas_h)
    mosaic.fill(QtGui.QColor("#081120"))

    painter = QtGui.QPainter(mosaic)
    for index, (cid, img) in enumerate(items[:4]):
        row = index // 2
        col = index % 2
        x0 = col * cell_w
        y0 = row * cell_h
        pix = QtGui.QPixmap.fromImage(img).scaled(
            cell_w,
            cell_h,
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation,
        )
        px = x0 + (cell_w - pix.width()) // 2
        py = y0 + (cell_h - pix.height()) // 2
        painter.fillRect(x0, y0, cell_w, cell_h, QtGui.QColor("#081120"))
        painter.drawPixmap(px, py, pix)
        painter.setPen(QtGui.QColor("#ffffff"))
        painter.setFont(QtGui.QFont("Segoe UI", 12, QtGui.QFont.Bold))
        painter.drawText(x0 + 12, y0 + 28, cid)
        painter.setPen(QtGui.QColor("#38bdf8"))
        painter.drawRect(x0, y0, cell_w - 1, cell_h - 1)
    painter.end()

    try:
        scaled = mosaic.scaled(
            self.video_label.size(),
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation,
        )
        self.video_label.setPixmap(scaled)
    except Exception:
        pass


def _run_on_multi_camera_stats(self, camera_id, stats):
    """Chỉ tổng hợp stats multi khi đang ở chế độ MULTI."""
    if getattr(self, "che_do_chay", "SINGLE") != "MULTI":
        return

    self.camera_stats[camera_id] = stats
    tong_xe = sum(s.get("vehicles_in_roi", 0) for s in self.camera_stats.values())
    vsl_min = min([s.get("suggested_vsl", 100) for s in self.camera_stats.values()] or [100])
    tong_canh_bao = sum(s.get("warning_count", 0) for s in self.camera_stats.values())
    tong_su_kien = sum(s.get("event_count", 0) for s in self.camera_stats.values())

    stats_tong = dict(stats)
    stats_tong["vehicles_in_roi"] = tong_xe
    stats_tong["suggested_vsl"] = vsl_min
    stats_tong["warning_count"] = tong_canh_bao
    stats_tong["event_count"] = tong_su_kien
    stats_tong["reason"] = f"Tổng hợp đa camera | Camera hiện tại: {camera_id}"
    self.update_ui_from_stats(stats_tong)


try:
    GiaoDienChinh.on_open_video = _run_on_open_video
    GiaoDienChinh.on_chon_camera = _run_on_chon_camera
    GiaoDienChinh.on_start = _run_on_start
    GiaoDienChinh.on_start_multi_camera = _run_on_start_multi_camera
    GiaoDienChinh.on_pause_resume = _run_on_pause_resume
    GiaoDienChinh.on_stop = _run_on_stop
    GiaoDienChinh.on_worker_finished = _run_on_worker_finished
    GiaoDienChinh.on_multi_camera_frame = _run_on_multi_camera_frame
    GiaoDienChinh.on_multi_camera_stats = _run_on_multi_camera_stats
except Exception as e:
    print("[RUN] Không thể vá chế độ chạy:", e)



# BỘ ĐIỀU PHỐI NGUỒN CHẠY
# Chỉ cho một nguồn hoạt động tại một thời điểm: video thủ công, camera đơn hoặc đa camera.

def _dat_nut_theo_che_do(self, che_do):
    try:
        if che_do == "MULTI":
            self.btn_open_video.setEnabled(False)
            self.cbo_camera.setEnabled(False)
            self.btn_start.setEnabled(False)
            self.btn_pause.setEnabled(False)
            self.btn_stop.setEnabled(True)
        elif che_do == "SINGLE_RUNNING":
            # Cho phép đổi video khi đang chạy: hàm mở video sẽ dừng phiên cũ trước.
            self.btn_open_video.setEnabled(True)
            self.cbo_camera.setEnabled(False)
            self.btn_start.setEnabled(False)
            self.btn_pause.setEnabled(True)
            self.btn_stop.setEnabled(True)
        else:
            self.btn_open_video.setEnabled(True)
            self.cbo_camera.setEnabled(True)
            self.btn_start.setEnabled(bool(getattr(self, "video_path", None)))
            self.btn_pause.setEnabled(False)
            self.btn_stop.setEnabled(False)
    except Exception:
        pass


def _dung_worker_don(self, timeout_ms=3500):
    worker = getattr(self, "worker", None)
    if worker is None:
        return

    try:
        worker.yeu_cau_dung()
        worker.dat_tam_dung(False)
    except Exception:
        pass

    try:
        if worker.isRunning():
            deadline = time.time() + timeout_ms / 1000.0
            while worker.isRunning() and time.time() < deadline:
                QtWidgets.QApplication.processEvents()
                worker.wait(50)

        if worker.isRunning():
            worker.terminate()
            worker.wait(1000)
    except Exception:
        pass

    self.worker = None


def _dung_da_camera(self):
    multi = getattr(self, "multi_worker", None)
    if multi is None:
        return

    try:
        multi.dung()
    except Exception:
        pass

    self.multi_worker = None
    self.camera_frames = {}
    self.camera_stats = {}


def _cap_nhat_nhan_chay(self, dang_chay):
    try:
        if dang_chay:
            self.lbl_status.setText("Đang chạy...")
            self.hero_badge_status.setText("TRẠNG THÁI: ĐANG CHẠY")
            self.badge_live.setText("TRỰC TUYẾN: BẬT")
            self.badge_live.setObjectName("BadgeGreen")
        else:
            self.lbl_status.setText("Sẵn sàng chạy." if getattr(self, "video_path", None) else "Sẵn sàng.")
            self.hero_badge_status.setText("TRẠNG THÁI: ĐÃ CHỌN VIDEO" if getattr(self, "video_path", None) else "TRẠNG THÁI: SẴN SÀNG")
            self.badge_live.setText("TRỰC TUYẾN: TẮT")
            self.badge_live.setObjectName("BadgeRed")

        self.badge_live.style().unpolish(self.badge_live)
        self.badge_live.style().polish(self.badge_live)
    except Exception:
        pass


def _mo_video_thu_cong(self):
    if getattr(self, "che_do_chay", "SINGLE") == "MULTI":
        tra_loi = QtWidgets.QMessageBox.question(
            self,
            "Đổi nguồn video",
            "Đa camera đang chạy. Dừng đa camera để mở video thủ công?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if tra_loi != QtWidgets.QMessageBox.Yes:
            return
        _dung_da_camera(self)

    if getattr(self, "worker", None) is not None:
        tra_loi = QtWidgets.QMessageBox.question(
            self,
            "Đổi video",
            "Phiên hiện tại đang chạy. Dừng phiên cũ và chọn video mới?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.Yes,
        )
        if tra_loi != QtWidgets.QMessageBox.Yes:
            return
        _dung_worker_don(self)

    fn, _ = QtWidgets.QFileDialog.getOpenFileName(
        self,
        "Chọn video",
        str(BASE_DIR),
        "Video (*.mp4 *.avi *.mkv *.mov *.MOV);;Tất cả tệp (*)",
    )
    if not fn:
        _dat_nut_theo_che_do(self, "READY")
        return

    self.che_do_chay = "SINGLE"
    self.video_path = fn
    self.camera_hien_tai = None

    try:
        self.cbo_camera.blockSignals(True)
        self.cbo_camera.setCurrentIndex(0)
        self.cbo_camera.blockSignals(False)
    except Exception:
        pass

    try:
        self.lbl_video_name.setText(f"Video: {Path(fn).name}")
        cap = cv2.VideoCapture(fn)
        if cap.isOpened():
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS) or 0
            self.lbl_video_res.setText(f"Resolution: {w} x {h} | FPS: {fps:.1f}")
        else:
            self.lbl_video_res.setText("Resolution: - x -")
        cap.release()
    except Exception:
        pass

    try:
        self.video_label.clear()
        self.video_label.setText("Đã chọn video. Bấm Bắt đầu phân tích.")
    except Exception:
        pass

    _dat_nut_theo_che_do(self, "READY")
    _cap_nhat_nhan_chay(self, False)
    try:
        self.append_log(f"[VIDEO] Đã chọn: {Path(fn).name}")
    except Exception:
        pass


def _chon_camera_don(self):
    if getattr(self, "che_do_chay", "SINGLE") == "MULTI":
        QtWidgets.QMessageBox.warning(self, "Đang chạy đa camera", "Dừng hệ thống trước khi đổi camera.")
        return

    if getattr(self, "worker", None) is not None:
        QtWidgets.QMessageBox.warning(self, "Đang chạy", "Dừng phiên hiện tại trước khi đổi camera.")
        return

    camera_id = self.cbo_camera.currentData()
    if not camera_id:
        self.camera_hien_tai = None
        return

    cam = self.quan_ly_camera.lay_camera_theo_id(camera_id)
    if cam is None:
        return

    if not os.path.exists(cam.duong_dan_video):
        QtWidgets.QMessageBox.warning(self, "Lỗi camera", f"Không thấy nguồn video:\n{cam.duong_dan_video}")
        return

    self.che_do_chay = "SINGLE"
    self.camera_hien_tai = cam
    self.video_path = cam.duong_dan_video

    try:
        self.lbl_video_name.setText(f"Camera: {cam.ten_camera}")
        self.lbl_video_res.setText(f"Vị trí: {cam.vi_tri}")
        self.video_label.clear()
        self.video_label.setText("Đã chọn camera. Bấm Bắt đầu phân tích.")
        self.append_log(f"[CAMERA] Đã chọn {cam.ten_camera} - {cam.vi_tri}")
    except Exception:
        pass

    _dat_nut_theo_che_do(self, "READY")
    _cap_nhat_nhan_chay(self, False)


def _bat_dau_mot_nguon(self):
    if getattr(self, "che_do_chay", "SINGLE") == "MULTI":
        QtWidgets.QMessageBox.warning(self, "Đang chạy đa camera", "Dừng đa camera trước khi chạy nguồn đơn.")
        return

    _dung_da_camera(self)

    worker = getattr(self, "worker", None)
    if worker is not None:
        try:
            if worker.isRunning():
                return
        except Exception:
            _dung_worker_don(self)

    if not getattr(self, "video_path", None) or not os.path.isfile(self.video_path):
        QtWidgets.QMessageBox.warning(self, "Lỗi", "Chưa chọn video/camera hoặc đường dẫn không hợp lệ.")
        return

    camera_id = self.camera_hien_tai.camera_id if getattr(self, "camera_hien_tai", None) else "VIDEO_THU_CONG"

    try:
        self.log_view.clear()
    except Exception:
        pass

    self.worker = XuLyVideo(
        self.video_path,
        self.config,
        self.session_user,
        camera_id=camera_id,
    )

    self.worker.frameReady.connect(self.show_frame)
    self.worker.statsReady.connect(self.update_ui_from_stats)
    self.worker.statusReady.connect(self.lbl_status.setText)
    self.worker.logReady.connect(self.append_log)
    self.worker.errorReady.connect(self.on_worker_error)
    self.worker.finishedCleanly.connect(self.on_worker_finished)
    self.worker.start()

    self.che_do_chay = "SINGLE"
    _dat_nut_theo_che_do(self, "SINGLE_RUNNING")
    _cap_nhat_nhan_chay(self, True)
    try:
        self.btn_pause.setText("Tạm dừng")
        self.append_log("[RUN] Bắt đầu phân tích nguồn đơn.")
    except Exception:
        pass


def _bat_dau_da_camera(self):
    if getattr(self, "worker", None) is not None:
        tra_loi = QtWidgets.QMessageBox.question(
            self,
            "Chạy đa camera",
            "Nguồn đơn đang chạy. Dừng nguồn đơn để chạy đa camera?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.Yes,
        )
        if tra_loi != QtWidgets.QMessageBox.Yes:
            return
        _dung_worker_don(self)

    multi = getattr(self, "multi_worker", None)
    if multi is not None:
        try:
            if multi.dang_chay():
                return
        except Exception:
            _dung_da_camera(self)

    danh_sach_camera = self.quan_ly_camera.lay_camera_dang_bat()
    danh_sach_camera = [cam for cam in danh_sach_camera if os.path.exists(cam.duong_dan_video)]

    if not danh_sach_camera:
        QtWidgets.QMessageBox.warning(self, "Lỗi", "Không có camera nào có nguồn video hợp lệ.")
        return

    self.che_do_chay = "MULTI"
    self.camera_hien_tai = None
    self.camera_frames = {}
    self.camera_stats = {}

    try:
        self.video_label.clear()
        self.video_label.setText("Đang chạy đa camera...")
    except Exception:
        pass

    self.multi_worker = MultiCameraWorker(
        danh_sach_camera=danh_sach_camera,
        config=self.config,
        session_user=self.session_user,
    )
    self.multi_worker.frameCameraReady.connect(self.on_multi_camera_frame)
    self.multi_worker.statsCameraReady.connect(self.on_multi_camera_stats)
    self.multi_worker.logCameraReady.connect(self.append_log)
    self.multi_worker.bat_dau()

    _dat_nut_theo_che_do(self, "MULTI")
    _cap_nhat_nhan_chay(self, True)
    try:
        self.hero_badge_status.setText("TRẠNG THÁI: ĐA CAMERA")
        self.badge_live.setText("TRỰC TUYẾN: ĐA CAMERA")
        self.append_log("[MULTI] Bắt đầu chạy đa camera.")
    except Exception:
        pass


def _tam_dung_tiep_tuc(self):
    if getattr(self, "che_do_chay", "SINGLE") != "SINGLE":
        return

    worker = getattr(self, "worker", None)
    if worker is None:
        return

    dang_tam_dung = self.btn_pause.text() == "Tiếp tục"
    if dang_tam_dung:
        worker.dat_tam_dung(False)
        self.btn_pause.setText("Tạm dừng")
        _cap_nhat_nhan_chay(self, True)
    else:
        worker.dat_tam_dung(True)
        self.btn_pause.setText("Tiếp tục")
        try:
            self.lbl_status.setText("Đã tạm dừng.")
            self.hero_badge_status.setText("TRẠNG THÁI: TẠM DỪNG")
            self.badge_live.setText("TRỰC TUYẾN: TẠM DỪNG")
            self.badge_live.setObjectName("BadgeAmber")
            self.badge_live.style().unpolish(self.badge_live)
            self.badge_live.style().polish(self.badge_live)
        except Exception:
            pass


def _dung_tat_ca(self):
    _dung_da_camera(self)
    _dung_worker_don(self)

    self.che_do_chay = "SINGLE"
    try:
        self.btn_pause.setText("Tạm dừng")
        self.video_label.clear()
        self.video_label.setText("Đã dừng hệ thống.")
        self.lbl_status.setText("Đã dừng.")
        self.append_log("[RUN] Đã dừng toàn bộ hệ thống.")
    except Exception:
        pass

    _dat_nut_theo_che_do(self, "READY")
    _cap_nhat_nhan_chay(self, False)


def _ket_thuc_worker_don(self, summary):
    self.worker = None
    if getattr(self, "che_do_chay", "SINGLE") != "MULTI":
        _dat_nut_theo_che_do(self, "READY")
        _cap_nhat_nhan_chay(self, False)
        try:
            self.btn_pause.setText("Tạm dừng")
        except Exception:
            pass

    try:
        if isinstance(summary, dict) and summary.get("summary_html_path"):
            self.lbl_report.setText(f"Báo cáo mới nhất: {summary.get('summary_html_path')}")
    except Exception:
        pass


def _khung_hinh_da_camera(self, camera_id, qimg):
    if getattr(self, "che_do_chay", "SINGLE") != "MULTI":
        return

    self.camera_frames[camera_id] = qimg
    items = list(self.camera_frames.items())[:4]
    if not items:
        return

    cell_w, cell_h = 520, 300
    mosaic = QtGui.QPixmap(cell_w * 2, cell_h * 2)
    mosaic.fill(QtGui.QColor("#081120"))

    painter = QtGui.QPainter(mosaic)
    for index, (cid, img) in enumerate(items):
        row, col = divmod(index, 2)
        x0, y0 = col * cell_w, row * cell_h
        pix = QtGui.QPixmap.fromImage(img).scaled(cell_w, cell_h, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        px = x0 + (cell_w - pix.width()) // 2
        py = y0 + (cell_h - pix.height()) // 2
        painter.fillRect(x0, y0, cell_w, cell_h, QtGui.QColor("#081120"))
        painter.drawPixmap(px, py, pix)
        painter.setPen(QtGui.QColor("#ffffff"))
        painter.setFont(QtGui.QFont("Segoe UI", 12, QtGui.QFont.Bold))
        painter.drawText(x0 + 12, y0 + 28, cid)
        painter.setPen(QtGui.QColor("#38bdf8"))
        painter.drawRect(x0, y0, cell_w - 1, cell_h - 1)
    painter.end()

    try:
        scaled = mosaic.scaled(self.video_label.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        self.video_label.setPixmap(scaled)
    except Exception:
        pass


def _thong_ke_da_camera(self, camera_id, stats):
    if getattr(self, "che_do_chay", "SINGLE") != "MULTI":
        return

    self.camera_stats[camera_id] = dict(stats)
    tong_xe = sum(s.get("vehicles_in_roi", 0) for s in self.camera_stats.values())
    vsl_min = min([s.get("suggested_vsl", 100) for s in self.camera_stats.values()] or [100])
    tong_canh_bao = sum(s.get("warning_count", 0) for s in self.camera_stats.values())
    tong_su_kien = sum(s.get("event_count", 0) for s in self.camera_stats.values())

    stats_tong = dict(stats)
    stats_tong["vehicles_in_roi"] = tong_xe
    stats_tong["suggested_vsl"] = vsl_min
    stats_tong["warning_count"] = tong_canh_bao
    stats_tong["event_count"] = tong_su_kien
    stats_tong["reason"] = f"Tổng hợp đa camera | Camera hiện tại: {camera_id}"
    self.update_ui_from_stats(stats_tong)


try:
    GiaoDienChinh.dong_bo_trang_thai_chay = lambda self, running: _dat_nut_theo_che_do(self, "SINGLE_RUNNING" if running else "READY")
    GiaoDienChinh.on_open_video = _mo_video_thu_cong
    GiaoDienChinh.on_chon_video = _mo_video_thu_cong
    GiaoDienChinh.on_chon_camera = _chon_camera_don
    GiaoDienChinh.on_start = _bat_dau_mot_nguon
    GiaoDienChinh.on_start_multi_camera = _bat_dau_da_camera
    GiaoDienChinh.on_start_multi = _bat_dau_da_camera
    GiaoDienChinh.on_pause_resume = _tam_dung_tiep_tuc
    GiaoDienChinh.on_stop = _dung_tat_ca
    GiaoDienChinh.on_worker_finished = _ket_thuc_worker_don
    GiaoDienChinh.on_multi_camera_frame = _khung_hinh_da_camera
    GiaoDienChinh.on_multi_camera_stats = _thong_ke_da_camera
except Exception as loi:
    print("[RUN] Không thể nạp bộ điều phối nguồn:", loi)




# Bổ sung hiển thị tốc độ đo bằng hai vạch lên giao diện.
try:
    _update_ui_goc_speed = GiaoDienChinh.update_ui_from_stats

    def _update_ui_co_toc_do(self, stats):
        _update_ui_goc_speed(self, stats)
        toc_do_text = stats.get("toc_do_text")
        if not toc_do_text:
            return

        try:
            if hasattr(self, "lbl_fps"):
                fps_est = float(stats.get("fps_est", 0.0))
                da_do = int(stats.get("so_xe_da_do_toc_do", 0))
                dang_do = int(stats.get("so_xe_dang_do_toc_do", 0))
                self.lbl_fps.setText(
                    f"Tốc độ xử lý: {fps_est:.1f} | {toc_do_text}"
                )
        except Exception:
            pass

        try:
            if hasattr(self, "lbl_action"):
                self.lbl_action.setText(toc_do_text)
        except Exception:
            pass

    GiaoDienChinh.update_ui_from_stats = _update_ui_co_toc_do
except Exception:
    pass



# =========================================================
# MERGED PROFESSIONAL EDITION PATCH
# Nguồn lõi: fix_viet_hoa_full (nhiều tính năng hơn)
# Giao diện: vá lại theo phong cách fix.py, tối màu, sạch objectName
# Bổ sung: chuyển ngôn ngữ Việt / Anh ở lớp giao diện
# =========================================================

LANG_VI = "vi"
LANG_EN = "en"

_VALUE_TRANSLATIONS = {
    "LOW": "THẤP",
    "MEDIUM": "TRUNG BÌNH",
    "HIGH": "CAO",
    "THẤP": "LOW",
    "TRUNG BÌNH": "MEDIUM",
    "CAO": "HIGH",
    "Lưu thông tốt": "Free flow",
    "Lưu thông ổn định": "Stable flow",
    "Mật độ cao": "Dense flow",
    "Nguy cơ ùn tắc": "Congestion risk",
    "Free Flow": "Lưu thông tốt",
    "Stable Flow": "Lưu thông ổn định",
    "Dense Flow": "Mật độ cao",
    "Congestion Risk": "Nguy cơ ùn tắc",
    "Bình thường": "Normal",
    "Theo dõi": "Monitor",
    "Cần can thiệp": "Intervention recommended",
    "Khẩn cấp": "Urgent action",
    "Normal": "Bình thường",
    "Monitor": "Theo dõi",
    "Intervention Recommended": "Cần can thiệp",
    "Urgent Action": "Khẩn cấp",
    "Trời quang": "Clear",
    "Mưa nhỏ": "Light rain",
    "Mưa vừa": "Moderate rain",
    "Mưa to": "Heavy rain",
    "Sương mù mỏng": "Thin fog (>1 km visibility)",
    "Sương mù vừa": "Moderate fog (0.5-1 km visibility)",
    "Sương mù dày": "Dense fog (<0.5 km visibility)",
    # Giá trị cũ để tương thích ngược
    "Mưa": "Moderate rain",
    "Sương mù": "Moderate fog (0.5-1 km visibility)",
    "Clear": "Trời quang",
    "Light rain": "Mưa nhỏ",
    "Moderate rain": "Mưa vừa",
    "Heavy rain": "Mưa to",
    "Thin fog (>1 km visibility)": "Sương mù mỏng",
    "Moderate fog (0.5-1 km visibility)": "Sương mù vừa",
    "Dense fog (<0.5 km visibility)": "Sương mù dày",
    "Rain": "Mưa vừa",
    "Fog": "Sương mù vừa",
    "Không": "None",
    "Nhẹ": "Minor",
    "Nghiêm trọng": "Serious",
    "None": "Không",
    "Minor": "Nhẹ",
    "Serious": "Nghiêm trọng",
    "Tự động": "Auto",
    "Thủ công": "Manual",
    "Auto": "Tự động",
    "Manual": "Thủ công",
    "Có": "Yes",
    "Không có": "No",
    "Yes": "Có",
    "No": "Không có",
}

_UI_TEXT = {
    LANG_VI: {
        "window_title": "HỆ THỐNG GIÁM SÁT BIỂN BÁO TỐC ĐỘ LINH HOẠT",
        "hero_title": "HỆ THỐNG GIÁM SÁT BIỂN BÁO TỐC ĐỘ LINH HOẠT",
        "hero_subtitle": "Giám sát giao thông thông minh • Điều khiển tốc độ linh hoạt • Phân tích thời gian thực",
        "language": "Ngôn ngữ",
        "nav": [
            ("Khởi động nhanh", "quy trình nhanh • cấu hình mẫu"),
            ("Phiên làm việc", "video • chạy • báo cáo"),
            ("Nhận diện phương tiện", "độ nhạy AI • hiệu năng"),
            ("Khu vực giám sát", "hình học • vùng theo dõi"),
            ("Điều khiển tốc độ", "quy tắc tốc độ • bối cảnh"),
            ("Báo cáo và lịch sử", "hiển thị • nhật ký • báo cáo"),
        ],
        "card_roi": "Số xe trong vùng giám sát",
        "card_vsl": "Tốc độ đề xuất",
        "card_state": "Trạng thái giao thông",
        "card_priority": "Mức độ ưu tiên",
        "btn_open_video": "Chọn video",
        "btn_start": "Bắt đầu phân tích",
        "btn_pause": "Tạm dừng",
        "btn_pause_resume": "Tiếp tục",
        "btn_stop": "Dừng hệ thống",
        "btn_export": "Lưu ảnh sự kiện",
        "btn_output": "Mở thư mục kết quả",
        "btn_report": "Mở báo cáo mới nhất",
        "btn_multi": "Chạy tất cả camera",
        "btn_logout": "Đăng xuất",
        "btn_reset_roi": "Đặt lại ROI",
        "btn_save_speed": "Lưu cấu hình tốc độ",
        "video_placeholder": "Video giám sát sẽ hiển thị tại đây",
        "live_off": "TRỰC TUYẾN: TẮT",
        "live_on": "TRỰC TUYẾN: BẬT",
        "ready": "SẴN SÀNG",
        "device": "THIẾT BỊ",
        "mode": "CHẾ ĐỘ",
        "status": "TRẠNG THÁI",
        "sign": "BIỂN BÁO",
        "user": "NGƯỜI DÙNG",
        "weather": "THỜI TIẾT",
        "incident": "SỰ CỐ",
        "avg": "Số xe trung bình",
        "density": "Mật độ",
        "state": "Trạng thái giao thông",
        "vsl": "Tốc độ đề xuất",
        "control_mode": "Chế độ",
        "priority": "Mức ưu tiên",
        "alert": "Cảnh báo tăng đột biến",
        "fps": "Tốc độ xử lý",
        "classes": "Ô tô: {car} | Xe máy: {motorcycle} | Xe khách: {bus} | Xe tải: {truck} | Xe đạp: {bicycle}",
        "reason": "Lý do",
        "counts": "Cảnh báo: {warning} | Ảnh chụp: {snapshot} | Sự kiện: {event}",
        "lanes": "Số xe theo làn",
        "action": "Khuyến nghị điều hành",
        "default_action": "Tiếp tục giám sát",
        "none_report": "Báo cáo mới nhất: chưa có báo cáo nào được xuất",
    },
    LANG_EN: {
        "window_title": "INTELLIGENT VARIABLE SPEED LIMIT MONITORING SYSTEM",
        "hero_title": "INTELLIGENT VARIABLE SPEED LIMIT MONITORING SYSTEM",
        "hero_subtitle": "Smart traffic monitoring • Variable speed control • Real-time analytics",
        "language": "Language",
        "nav": [
            ("Quick start", "fast workflow • sample configuration"),
            ("Session", "video • run • reports"),
            ("Vehicle detection", "AI sensitivity • performance"),
            ("Monitoring area", "geometry • tracking zone"),
            ("Speed control", "VSL rules • operating context"),
            ("Reports & history", "display • logs • reports"),
        ],
        "card_roi": "Vehicles in ROI",
        "card_vsl": "Recommended speed",
        "card_state": "Traffic state",
        "card_priority": "Priority level",
        "btn_open_video": "Choose video",
        "btn_start": "Start analysis",
        "btn_pause": "Pause",
        "btn_pause_resume": "Resume",
        "btn_stop": "Stop system",
        "btn_export": "Save event snapshot",
        "btn_output": "Open output folder",
        "btn_report": "Open latest report",
        "btn_multi": "Run all cameras",
        "btn_logout": "Log out",
        "btn_reset_roi": "Reset ROI",
        "btn_save_speed": "Save speed profile",
        "video_placeholder": "Traffic monitoring video will appear here",
        "live_off": "LIVE: OFF",
        "live_on": "LIVE: ON",
        "ready": "READY",
        "device": "DEVICE",
        "mode": "MODE",
        "status": "STATUS",
        "sign": "SIGN",
        "user": "USER",
        "weather": "WEATHER",
        "incident": "INCIDENT",
        "avg": "Average vehicles",
        "density": "Density",
        "state": "Traffic state",
        "vsl": "Recommended speed",
        "control_mode": "Mode",
        "priority": "Priority",
        "alert": "Sudden increase alert",
        "fps": "Processing speed",
        "classes": "Car: {car} | Motorcycle: {motorcycle} | Bus: {bus} | Truck: {truck} | Bicycle: {bicycle}",
        "reason": "Reason",
        "counts": "Warnings: {warning} | Snapshots: {snapshot} | Events: {event}",
        "lanes": "Vehicles by lane",
        "action": "Operational recommendation",
        "default_action": "Continue monitoring",
        "none_report": "Latest report: no report has been exported yet",
    },
}

_COMBO_VALUES = {
    "weather": [
        ("Trời quang", "Clear"),
        ("Mưa nhỏ", "Light rain"),
        ("Mưa vừa", "Moderate rain"),
        ("Mưa to", "Heavy rain"),
        ("Sương mù mỏng", "Thin fog (>1 km visibility)"),
        ("Sương mù vừa", "Moderate fog (0.5-1 km visibility)"),
        ("Sương mù dày", "Dense fog (<0.5 km visibility)"),
    ],
    "incident": [("Không", "None"), ("Nhẹ", "Minor"), ("Nghiêm trọng", "Serious")],
    "mode": [("Tự động", "Auto"), ("Thủ công", "Manual")],
}


def _merged_text(self, key: str) -> str:
    lang = getattr(self, "ngon_ngu_hien_tai", LANG_VI)
    return _UI_TEXT.get(lang, _UI_TEXT[LANG_VI]).get(key, key)


def _merged_value(value, lang=None):
    if value is None:
        return "-"
    text = str(value)
    if lang == LANG_EN:
        return _VALUE_TRANSLATIONS.get(text, text)
    # Khi dùng tiếng Việt, chỉ đổi các giá trị tiếng Anh về tiếng Việt; giá trị tiếng Việt giữ nguyên.
    return _VALUE_TRANSLATIONS.get(text, text) if text in _VALUE_TRANSLATIONS else text


def _merged_normalize_vi(value):
    text = str(value)
    return _VALUE_TRANSLATIONS.get(text, text) if text in _VALUE_TRANSLATIONS else text


def _merged_set_combo_language(combo, pairs, current_vi, lang):
    if combo is None:
        return
    try:
        blocker = QtCore.QSignalBlocker(combo)
        combo.clear()
        for vi, en in pairs:
            combo.addItem(en if lang == LANG_EN else vi, vi)
        for i, (vi, _) in enumerate(pairs):
            if vi == current_vi:
                combo.setCurrentIndex(i)
                break
        del blocker
    except Exception:
        pass


def _merged_init_style_dark(self):
    QtWidgets.QApplication.setStyle("Fusion")
    self.setFont(QtGui.QFont("Segoe UI", 10))
    palette = QtGui.QPalette()
    palette.setColor(QtGui.QPalette.Window, QtGui.QColor("#0b0f19"))
    palette.setColor(QtGui.QPalette.WindowText, QtGui.QColor("#e5eefb"))
    palette.setColor(QtGui.QPalette.Base, QtGui.QColor("#0f172a"))
    palette.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor("#111827"))
    palette.setColor(QtGui.QPalette.Button, QtGui.QColor("#1e293b"))
    palette.setColor(QtGui.QPalette.ButtonText, QtGui.QColor("#f8fafc"))
    palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor("#38bdf8"))
    palette.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor("#020617"))
    self.setPalette(palette)
    self.setStyleSheet("""
        QMainWindow { background-color:#0b0f19; }
        QWidget { color:#e5eefb; font-family:'Segoe UI'; }
        QFrame#HeroHeader {
            background:qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #020617, stop:0.42 #1d4ed8, stop:1 #06b6d4);
            border:none; border-radius:24px;
        }
        QLabel#HeroTitle { color:white; font-size:24px; font-weight:900; letter-spacing:0.3px; }
        QLabel#HeroSubtitle { color:rgba(255,255,255,0.88); font-size:11px; font-weight:600; }
        QLabel#HeroBadge {
            color:#e0f2fe; background-color:rgba(255,255,255,0.13);
            border:1px solid rgba(255,255,255,0.22); border-radius:14px;
            padding:6px 12px; font-size:11px; font-weight:800;
        }
        QFrame#NavRail { background:#0f172a; border:1px solid #1e293b; border-radius:20px; }
        QPushButton#NavButton { background:transparent; border:1px solid transparent; border-radius:16px; text-align:left; }
        QPushButton#NavButton:hover { background:#172554; border:1px solid #1d4ed8; }
        QPushButton#NavButton:checked { background:qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #1e3a8a, stop:1 #0e7490); border:1px solid #38bdf8; }
        QLabel#NavTitle { font-size:13px; font-weight:900; color:#f8fafc; }
        QLabel#NavSub { font-size:10px; font-weight:700; color:#94a3b8; }
        QFrame#ModuleHeader { background:#0f172a; border:1px solid #1e293b; border-radius:18px; }
        QLabel#ModuleTitle { color:#f8fafc; font-size:18px; font-weight:900; }
        QLabel#ModuleSubtitle { color:#94a3b8; font-size:11px; font-weight:700; }
        QGroupBox#CardSection { background:#0f172a; border:1px solid #1e293b; border-radius:18px; margin-top:18px; padding-top:16px; font-weight:900; color:#f8fafc; }
        QGroupBox#CardSection::title { subcontrol-origin:margin; left:14px; top:4px; padding:0 8px; color:#bae6fd; background:#0b0f19; border-radius:8px; }
        QLabel#SectionHint { color:#94a3b8; font-size:11px; font-weight:600; }
        QLabel#MetricLabel { color:#cbd5e1; font-size:13px; font-weight:800; padding:4px 0; }
        QPushButton { background-color:#2563eb; color:white; border:none; border-radius:12px; padding:10px 16px; font-weight:800; min-height:18px; }
        QPushButton:hover { background-color:#1d4ed8; }
        QPushButton:disabled { background-color:#1e293b; color:#64748b; border:none; }
        QPushButton#SecondaryBtn { background-color:#1e293b; color:#cbd5e1; border:1px solid #334155; }
        QPushButton#SecondaryBtn:hover { background-color:#334155; color:#f8fafc; }
        QPushButton#WarningBtn { background-color:#d97706; color:#ffffff; border:none; }
        QPushButton#WarningBtn:hover { background-color:#f59e0b; }
        QPushButton#DangerBtn { background-color:#b91c1c; color:white; border:none; }
        QPushButton#DangerBtn:hover { background-color:#ef4444; }
        QPushButton#SuccessBtn { background-color:#059669; color:white; border:none; }
        QPushButton#SuccessBtn:hover { background-color:#10b981; }
        QComboBox, QLineEdit { background-color:#111827; color:#f8fafc; border:1px solid #334155; border-radius:10px; padding:8px 10px; min-height:20px; }
        QComboBox QAbstractItemView { background:#0f172a; color:#e5eefb; selection-background-color:#1d4ed8; }
        QCheckBox { spacing:8px; font-weight:700; color:#cbd5e1; }
        QSlider::groove:horizontal { border:none; height:7px; background:#1e293b; border-radius:4px; }
        QSlider::sub-page:horizontal { background:#38bdf8; border-radius:4px; }
        QSlider::handle:horizontal { background:#e0f2fe; width:18px; margin:-6px 0; border-radius:9px; border:2px solid #38bdf8; }
        QPlainTextEdit { background-color:#020617; color:#dbeafe; border:1px solid #1e293b; border-radius:14px; padding:8px; font-family:Consolas; }
        QFrame#VideoPanel { background:#0f172a; border:1px solid #1e293b; border-radius:22px; }
        QLabel#PanelTitle { color:#f8fafc; font-size:16px; font-weight:900; }
        QLabel#PanelSubTitle { color:#94a3b8; font-size:11px; font-weight:700; }
        QLabel#BadgeBlue { background:#172554; color:#93c5fd; border-radius:10px; padding:8px 12px; font-weight:900; }
        QLabel#BadgeGreen { background:#052e2b; color:#5eead4; border-radius:10px; padding:8px 12px; font-weight:900; }
        QLabel#BadgeAmber { background:#451a03; color:#fbbf24; border-radius:10px; padding:8px 12px; font-weight:900; }
        QLabel#BadgeRed { background:#450a0a; color:#fca5a5; border-radius:10px; padding:8px 12px; font-weight:900; }
        QFrame#InsightPanel { background:#0f172a; border:1px solid #1e293b; border-radius:18px; }
        QLabel#InsightTitle { color:#e0f2fe; font-size:13px; font-weight:900; }
        QLabel#InsightText { color:#cbd5e1; font-size:12px; font-weight:700; }
        QLabel#StatusLine { color:#bae6fd; font-weight:900; font-size:12px; padding:6px 10px; background:#082f49; border-radius:10px; }
        QLabel#ReportPathLabel { color:#cbd5e1; background:#020617; border:1px solid #1e293b; border-radius:12px; padding:10px 12px; font-size:11px; font-weight:700; }
        QStatusBar { background:#020617; color:#94a3b8; border-top:1px solid #1e293b; }
    """)


def _merged_set_card_accent(self, color: str):
    self.setStyleSheet(f"""
        QFrame#StatCard {{
            background-color:#0f172a;
            border:1px solid #1e293b;
            border-left:5px solid {color};
            border-radius:16px;
        }}
        QLabel#StatCardTitle {{ color:#94a3b8; font-size:11px; font-weight:800; }}
        QLabel#StatCardValue {{ color:#f8fafc; font-size:26px; font-weight:900; }}
        QLabel#StatCardSub {{ color:#64748b; font-size:10px; font-weight:700; }}
    """)


def _merged_install_language_selector(self):
    try:
        self.ngon_ngu_hien_tai = getattr(self, "ngon_ngu_hien_tai", LANG_VI)
        bar = self.statusBar()
        self.lbl_language_selector = QtWidgets.QLabel("Ngôn ngữ / Language")
        self.cbo_language_selector = QtWidgets.QComboBox()
        self.cbo_language_selector.addItem("Tiếng Việt", LANG_VI)
        self.cbo_language_selector.addItem("English", LANG_EN)
        self.cbo_language_selector.setMinimumWidth(135)
        bar.addPermanentWidget(self.lbl_language_selector)
        bar.addPermanentWidget(self.cbo_language_selector)
        self.cbo_language_selector.currentIndexChanged.connect(
            lambda _: self.doi_ngon_ngu(self.cbo_language_selector.currentData())
        )
    except Exception as exc:
        try:
            print("[LANG] Không thể tạo bộ chọn ngôn ngữ:", exc)
        except Exception:
            pass


def _merged_cleanup_duplicate_buttons(self):
    try:
        main_multi_btn = getattr(self, "btn_start_multi", None)
        for btn in self.findChildren(QtWidgets.QPushButton):
            if btn is main_multi_btn:
                continue
            if btn.text().strip() in ("Chạy tất cả camera", "Run all cameras"):
                btn.hide()
    except Exception:
        pass


def _merged_apply_static_language(self):
    lang = getattr(self, "ngon_ngu_hien_tai", LANG_VI)
    t = _UI_TEXT.get(lang, _UI_TEXT[LANG_VI])
    try:
        self.setWindowTitle(t["window_title"])
    except Exception:
        pass
    try:
        title_labels = self.findChildren(QtWidgets.QLabel, "HeroTitle")
        subtitle_labels = self.findChildren(QtWidgets.QLabel, "HeroSubtitle")
        if title_labels:
            title_labels[0].setText(t["hero_title"])
        if subtitle_labels:
            subtitle_labels[0].setText(t["hero_subtitle"])
    except Exception:
        pass
    try:
        if hasattr(self, "nav_buttons"):
            for btn, (title, subtitle) in zip(self.nav_buttons, t["nav"]):
                btn.lb_title.setText(title)
                btn.lb_sub.setText(subtitle)
    except Exception:
        pass
    for attr, key in [
        ("card_roi", "card_roi"), ("card_vsl", "card_vsl"),
        ("card_state", "card_state"), ("card_priority", "card_priority"),
    ]:
        try:
            card = getattr(self, attr, None)
            if card is not None:
                card.title_label.setText(t[key])
        except Exception:
            pass
    for attr, key in [
        ("btn_open_video", "btn_open_video"), ("btn_start", "btn_start"),
        ("btn_stop", "btn_stop"), ("btn_export", "btn_export"),
        ("btn_open_output", "btn_output"), ("btn_open_latest", "btn_report"),
        ("btn_start_multi", "btn_multi"), ("btn_logout", "btn_logout"),
        ("btn_reset_roi", "btn_reset_roi"), ("btn_save_speed_profile", "btn_save_speed"),
    ]:
        try:
            widget = getattr(self, attr, None)
            if widget is not None:
                widget.setText(t[key])
        except Exception:
            pass
    try:
        if hasattr(self, "btn_pause"):
            current = self.btn_pause.text().strip()
            if current in ("Tiếp tục", "Resume"):
                self.btn_pause.setText(t["btn_pause_resume"])
            else:
                self.btn_pause.setText(t["btn_pause"])
    except Exception:
        pass
    try:
        if hasattr(self, "lbl_language_selector"):
            self.lbl_language_selector.setText(t["language"])
    except Exception:
        pass
    # Các combobox hiển thị tiếng Anh nhưng userData vẫn giữ giá trị tiếng Việt để thuật toán không bị lệch logic.
    _merged_set_combo_language(getattr(self, "cbo_weather", None), _COMBO_VALUES["weather"], getattr(self.config.vsl, "weather", "Trời quang"), lang)
    _merged_set_combo_language(getattr(self, "cbo_incident", None), _COMBO_VALUES["incident"], getattr(self.config.vsl, "incident", "Không"), lang)
    _merged_set_combo_language(getattr(self, "cbo_mode", None), _COMBO_VALUES["mode"], getattr(self.config.vsl, "control_mode", "Tự động"), lang)
    try:
        self._merged_apply_dynamic_language(getattr(self, "_last_stats_for_language", {}))
    except Exception:
        pass


def _merged_apply_dynamic_language(self, stats=None):
    stats = stats or {}
    lang = getattr(self, "ngon_ngu_hien_tai", LANG_VI)
    t = _UI_TEXT.get(lang, _UI_TEXT[LANG_VI])
    class_counts = stats.get("class_counts", {k: 0 for k in VEHICLE_CLASSES}) or {}
    vehicles = stats.get("vehicles_in_roi", 0)
    avg = stats.get("avg_vehicles", 0)
    density = _merged_value(stats.get("density", "THẤP"), lang)
    traffic_state = _merged_value(stats.get("traffic_state", "Lưu thông tốt"), lang)
    vsl = stats.get("suggested_vsl", getattr(getattr(self, "config", None), "vsl", CauHinhVSL()).vsl_max)
    priority = _merged_value(stats.get("priority", "Bình thường"), lang)
    weather = _merged_value(getattr(self.config.vsl, "weather", "Trời quang"), lang)
    incident = _merged_value(getattr(self.config.vsl, "incident", "Không"), lang)
    mode = _merged_value(getattr(self.config.vsl, "control_mode", "Tự động"), lang)
    sudden = stats.get("sudden_increase", False)
    sudden_text = ("Yes" if lang == LANG_EN else "Có") if sudden else ("No" if lang == LANG_EN else "Không")
    try:
        self.card_roi.dat_gia_tri(str(vehicles))
        self.card_vsl.dat_gia_tri(f"{vsl} km/h")
        self.card_state.dat_gia_tri(str(traffic_state))
        self.card_priority.dat_gia_tri(str(priority))
    except Exception:
        pass
    try:
        self.lbl_avg.setText(f"{t['avg']}: {avg}")
        self.lbl_density.setText(f"{t['density']}: {density}")
        self.lbl_state.setText(f"{t['state']}: {traffic_state}")
        self.lbl_vsl.setText(f"{t['vsl']}: {vsl} km/h")
        self.lbl_mode.setText(f"{t['control_mode']}: {mode}")
        self.lbl_weather.setText(f"{t['weather']}: {weather} ({mo_ta_thoi_tiet_chi_tiet(getattr(self.config.vsl, 'weather', 'Trời quang'))}) | {t['incident']}: {incident}")
        self.lbl_priority.setText(f"{t['priority']}: {priority}")
        self.lbl_alert.setText(f"{t['alert']}: {sudden_text}")
        self.lbl_fps.setText(f"{t['fps']}: {float(stats.get('fps_est', 0.0)):.1f}")
        self.lbl_classes.setText(t["classes"].format(
            car=class_counts.get("car", 0), motorcycle=class_counts.get("motorcycle", 0),
            bus=class_counts.get("bus", 0), truck=class_counts.get("truck", 0), bicycle=class_counts.get("bicycle", 0)
        ))
        self.lbl_counts.setText(t["counts"].format(
            warning=stats.get("warning_count", 0), snapshot=stats.get("snapshot_count", 0), event=stats.get("event_count", 0)
        ))
        lane_text = stats.get("lane_counts_text") or stats.get("reason", "-")
        self.lbl_lane_counts.setText(f"{t['lanes']}: {lane_text}")
        self.lbl_reason.setText(f"{t['reason']}: {stats.get('reason', 'system initialized' if lang == LANG_EN else 'hệ thống đã khởi tạo')}")
        if hasattr(self, "lbl_action"):
            action_text = stats.get("toc_do_text") or t["default_action"]
            self.lbl_action.setText(f"{t['action']}: {action_text}")
    except Exception:
        pass
    try:
        self.badge_weather.setText(f"{t['weather']}: {str(weather).upper()}")
        self.badge_incident.setText(f"{t['incident']}: {str(incident).upper()}")
        self.badge_mode.setText(f"{t['control_mode']}: {mode}")
        running = False
        try:
            running = bool(self.is_running())
        except Exception:
            pass
        self.badge_live.setText(t["live_on"] if running else t["live_off"])
        self.hero_badge_mode.setText(f"{t['mode']}: {str(mode).upper()}")
        self.hero_badge_device.setText(f"{t['device']}: {'GPU' if self.config.detection.use_gpu else 'CPU'}")
        self.hero_badge_status.setText(f"{t['status']}: {t['ready']}")
        self.hero_badge_vsl.setText(f"{t['sign']}: {vsl} km/h")
        self.hero_badge_user.setText(f"{t['user']}: {self.session_user.get('username', 'guest').upper()}")
    except Exception:
        pass


def _merged_change_language(self, lang):
    lang = lang if lang in (LANG_VI, LANG_EN) else LANG_VI
    self.ngon_ngu_hien_tai = lang
    _merged_apply_static_language(self)


def _merged_weather_changed(self, text):
    self.config.vsl.weather = _merged_normalize_vi(text)
    try:
        self._merged_apply_dynamic_language(getattr(self, "_last_stats_for_language", {}))
    except Exception:
        pass


def _merged_incident_changed(self, text):
    self.config.vsl.incident = _merged_normalize_vi(text)
    try:
        self._merged_apply_dynamic_language(getattr(self, "_last_stats_for_language", {}))
    except Exception:
        pass


def _merged_mode_changed(self, text):
    self.config.vsl.control_mode = _merged_normalize_vi(text)
    try:
        self.dong_bo_giao_dien_che_do()
    except Exception:
        pass
    try:
        self._merged_apply_dynamic_language(getattr(self, "_last_stats_for_language", {}))
    except Exception:
        pass


# Giữ style thẻ thống kê gốc theo fix(6).py, không dùng theme tối.
try:
    # Giữ hàm _khoi_tao_giao_dien gốc theo fix(6).py; không ghi đè bằng theme tối.
    GiaoDienChinh.doi_ngon_ngu = _merged_change_language
    GiaoDienChinh._merged_apply_dynamic_language = _merged_apply_dynamic_language
    GiaoDienChinh.xu_ly_doi_thoi_tiet = _merged_weather_changed
    GiaoDienChinh.xu_ly_doi_su_co = _merged_incident_changed
    GiaoDienChinh.xu_ly_doi_che_do = _merged_mode_changed

    _merged_orig_init = GiaoDienChinh.__init__
    def _merged_init(self, session_user: dict):
        _merged_orig_init(self, session_user)
        _merged_cleanup_duplicate_buttons(self)
        _merged_install_language_selector(self)
        _merged_apply_static_language(self)
    GiaoDienChinh.__init__ = _merged_init

    _merged_orig_update_stats = GiaoDienChinh.update_ui_from_stats
    def _merged_update_ui_from_stats(self, stats: dict):
        self._last_stats_for_language = dict(stats or {})
        _merged_orig_update_stats(self, stats)
        try:
            self._merged_apply_dynamic_language(stats)
        except Exception:
            pass
    GiaoDienChinh.update_ui_from_stats = _merged_update_ui_from_stats
except Exception as exc:
    try:
        print("[MERGED PATCH] Không thể kích hoạt lớp vá hợp nhất:", exc)
    except Exception:
        pass





# =========================================================
# FIX(6) UI RESTORE PATCH
# - Khôi phục đúng bảng màu sáng xanh/trắng và khung giao diện kiểu fix(6).py
# - Không can thiệp thuật toán VSL, đo tốc độ, multi-camera, báo cáo hay VI/EN
# =========================================================

def _fix6_restore_card_accent(self, color: str):
    self.setStyleSheet(f"""
        QFrame#StatCard {{
            background:qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ffffff, stop:1 #f8fbff);
            border:1px solid #dbe5f2;
            border-left:5px solid {color};
            border-radius:16px;
        }}
        QLabel#StatCardTitle {{ color:#64748b; font-size:11px; font-weight:600; }}
        QLabel#StatCardValue {{ color:#0f172a; font-size:26px; font-weight:800; }}
        QLabel#StatCardSub {{ color:#475569; font-size:10px; }}
    """)


def _fix6_restore_light_shell(self):
    """Đưa các widget hay bị patch tối/nhem nhuốc về đúng phong cách fix(6)."""
    try:
        self.statusBar().setStyleSheet("""
            QStatusBar { background:#eef4fb; color:#475569; border-top:1px solid #d9e6f3; }
            QLabel { color:#334155; font-weight:600; }
            QComboBox { background:#ffffff; color:#0f172a; border:1px solid #cbd5e1; border-radius:8px; padding:5px 8px; min-height:18px; }
            QComboBox QAbstractItemView { background:#ffffff; color:#0f172a; selection-background-color:#dbeafe; }
        """)
    except Exception:
        pass

    try:
        if hasattr(self, "video_label"):
            self.video_label.setStyleSheet(
                "background-color:#081120; border:1px solid #d9e6f3; "
                "border-radius:18px; color:#cbd5e1; font-weight:700;"
            )
    except Exception:
        pass

    try:
        for scroll in self.findChildren(QtWidgets.QScrollArea):
            scroll.setStyleSheet("""
                QScrollArea { background:transparent; border:none; }
                QScrollArea > QWidget > QWidget { background:transparent; }
            """)
    except Exception:
        pass

    try:
        if hasattr(self, "btn_start"):
            self.btn_start.setObjectName("WarningBtn")
        if hasattr(self, "btn_pause"):
            self.btn_pause.setObjectName("SecondaryBtn")
        if hasattr(self, "btn_stop"):
            self.btn_stop.setObjectName("DangerBtn")
        if hasattr(self, "btn_export"):
            self.btn_export.setObjectName("SuccessBtn")
        if hasattr(self, "btn_open_output"):
            self.btn_open_output.setObjectName("SecondaryBtn")
        if hasattr(self, "btn_open_latest"):
            self.btn_open_latest.setObjectName("SecondaryBtn")
        if hasattr(self, "btn_start_multi"):
            self.btn_start_multi.setObjectName("SuccessBtn")
    except Exception:
        pass


try:
    TheThongKeDong.dat_mau_nhan = _fix6_restore_card_accent
    _fix6_previous_init = GiaoDienChinh.__init__

    def _fix6_init(self, session_user: dict):
        _fix6_previous_init(self, session_user)
        _fix6_restore_light_shell(self)
        try:
            for card, color in [
                (getattr(self, "card_roi", None), "#0ea5e9"),
                (getattr(self, "card_vsl", None), "#10b981"),
                (getattr(self, "card_state", None), "#f59e0b"),
                (getattr(self, "card_priority", None), "#ef4444"),
            ]:
                if card is not None:
                    card.dat_mau_nhan(color)
        except Exception:
            pass

    GiaoDienChinh.__init__ = _fix6_init
except Exception as exc:
    try:
        print("[FIX6 UI RESTORE] Không thể kích hoạt lớp vá giao diện:", exc)
    except Exception:
        pass

# =========================================================
# RUNTIME STABILITY PATCH - KHÔNG TÁCH FILE
# =========================================================
# Lớp vá này giữ nguyên kiến trúc một file nhưng cải thiện độ ổn định:
# - log lỗi ra logs/app.log
# - cấu hình YOLO nhẹ hơn nếu cấu hình cũ vẫn còn tồn tại ở các patch bên dưới
# - log mọi nhật ký worker ra file
try:
    CauHinhNhanDien.conf_th = 0.30
    CauHinhNhanDien.frame_stride = 2
    CauHinhNhanDien.imgsz = 960
except Exception as _e:
    ghi_log(f"Không thể áp cấu hình nhận diện ổn định: {_e}")

try:
    _old_xulyvideo_log = XuLyVideo.them_nhat_ky

    def _stable_xulyvideo_log(self, text: str):
        try:
            ghi_log(str(text))
        except Exception:
            pass
        try:
            _old_xulyvideo_log(self, text)
        except Exception:
            try:
                self.logReady.emit(str(text))
            except Exception:
                pass

    XuLyVideo.them_nhat_ky = _stable_xulyvideo_log
except Exception as _e:
    ghi_log(f"Không thể vá logging cho XuLyVideo: {_e}")

try:
    _old_sign_publish = BienBaoDienTu.gui_lenh

    def _stable_sign_publish(self, camera_id, toc_do, mat_do, trang_thai):
        try:
            return _old_sign_publish(self, camera_id, toc_do, mat_do, trang_thai)
        except Exception as e:
            ghi_log(f"Lỗi gửi lệnh biển báo điện tử: {e}")

    BienBaoDienTu.gui_lenh = _stable_sign_publish
except Exception as _e:
    ghi_log(f"Không thể vá MQTT sign publish: {_e}")


# =========================================================
# MEDIAN-ONLY ROI PATCH - CHỈNH RIÊNG DẢI PHÂN CÁCH TÍM
# =========================================================
# Mục tiêu:
# - Slider ROI hình thang vẫn dùng để chỉnh vùng đường/làn vàng-xanh nếu cần.
# - Nhóm slider mới "Dải phân cách tím" chỉ chỉnh vùng tím, KHÔNG kéo theo vùng làn đường.
# - Khi đang chạy video, kéo slider tím sẽ áp dụng ở frame tiếp theo vì worker dùng chung self.config.roi.

def _median_only_get_default_values():
    try:
        cfg = doc_cau_hinh_roi_duong()
    except Exception:
        cfg = DEFAULT_ROI_ROAD_CONFIG
    med = cfg.get("median", {}) if isinstance(cfg, dict) else {}
    default_med = DEFAULT_ROI_ROAD_CONFIG.get("median", {})
    return {
        "median_top_left_x": _clamp_ratio(med.get("top_left_x", default_med.get("top_left_x", 0.49))),
        "median_top_right_x": _clamp_ratio(med.get("top_right_x", default_med.get("top_right_x", 0.595))),
        "median_bottom_right_x": _clamp_ratio(med.get("bottom_right_x", default_med.get("bottom_right_x", 0.57))),
        "median_bottom_left_x": _clamp_ratio(med.get("bottom_left_x", default_med.get("bottom_left_x", 0.43))),
        "median_y_top": _clamp_ratio(med.get("y_top", cfg.get("y_top", DEFAULT_ROI_ROAD_CONFIG.get("y_top", 0.36))), 0.02, 0.98),
        "median_y_bot": _clamp_ratio(med.get("y_bot", cfg.get("y_bot", DEFAULT_ROI_ROAD_CONFIG.get("y_bot", 0.92))), 0.05, 0.99),
    }


def _median_only_ensure_attrs(roi_obj):
    vals = _median_only_get_default_values()
    if roi_obj is None:
        return vals
    for k, v in vals.items():
        if not hasattr(roi_obj, k):
            try:
                setattr(roi_obj, k, float(v))
            except Exception:
                pass
    return {k: float(getattr(roi_obj, k, v)) for k, v in vals.items()}


def _median_only_read_part(cfg, part_name, defaults):
    part = cfg.get(part_name, {}) if isinstance(cfg, dict) else {}
    return {
        "top_left_x": float(part.get("top_left_x", defaults["top_left_x"])),
        "top_right_x": float(part.get("top_right_x", defaults["top_right_x"])),
        "bottom_right_x": float(part.get("bottom_right_x", defaults["bottom_right_x"])),
        "bottom_left_x": float(part.get("bottom_left_x", defaults["bottom_left_x"])),
    }


def _final_roi_chuan_bo_median(w, h, roi_cfg=None):
    """
    ROI cuối cùng, tách riêng dải phân cách tím.

    - left_road/right_road: vẫn đi theo bộ slider ROI hình thang cũ.
    - median: dùng bộ tham số median_* riêng, nên chỉnh tím không làm méo làn vàng.
    """
    cfg = doc_cau_hinh_roi_duong()

    # Mốc mặc định tương ứng với CauHinhROI ban đầu.
    base_top_cx = 0.55
    base_bot_cx = 0.62
    base_top_w = 0.22
    base_bot_w = 0.75
    base_bottom_y = 0.96
    base_height = 0.48

    if roi_cfg is not None:
        top_cx = _clamp_ratio(getattr(roi_cfg, "top_center_x", base_top_cx), 0.05, 0.95)
        bot_cx = _clamp_ratio(getattr(roi_cfg, "bottom_center_x", base_bot_cx), 0.05, 0.95)
        top_w = _clamp_ratio(getattr(roi_cfg, "top_width", base_top_w), 0.03, 0.95)
        bot_w = _clamp_ratio(getattr(roi_cfg, "bottom_width", base_bot_w), 0.05, 1.00)
        y_bot = _clamp_ratio(getattr(roi_cfg, "bottom_y", base_bottom_y), 0.50, 0.99)
        height_r = _clamp_ratio(getattr(roi_cfg, "height", base_height), 0.10, 0.95)
        y_top = _clamp_ratio(y_bot - height_r, 0.02, y_bot - 0.05)
    else:
        top_cx = base_top_cx
        bot_cx = base_bot_cx
        top_w = base_top_w
        bot_w = base_bot_w
        y_top = _clamp_ratio(cfg.get("y_top", base_bottom_y - base_height), 0.05, 0.95)
        y_bot = _clamp_ratio(cfg.get("y_bot", base_bottom_y), y_top + 0.05, 0.99)

    def map_top_x(x):
        x = float(x)
        val = top_cx + ((x - base_top_cx) / max(0.01, base_top_w)) * top_w
        return _clamp_ratio(val, 0.0, 1.0)

    def map_bot_x(x):
        x = float(x)
        val = bot_cx + ((x - base_bot_cx) / max(0.01, base_bot_w)) * bot_w
        return _clamp_ratio(val, 0.0, 1.0)

    left_cfg = _median_only_read_part(cfg, "left_road", DEFAULT_ROI_ROAD_CONFIG["left_road"])
    right_cfg = _median_only_read_part(cfg, "right_road", DEFAULT_ROI_ROAD_CONFIG["right_road"])

    left_road = np.array([
        [int(w * map_top_x(left_cfg["top_left_x"])), int(h * y_top)],
        [int(w * map_top_x(left_cfg["top_right_x"])), int(h * y_top)],
        [int(w * map_bot_x(left_cfg["bottom_right_x"])), int(h * y_bot)],
        [int(w * map_bot_x(left_cfg["bottom_left_x"])), int(h * y_bot)],
    ], dtype=np.int32)

    right_road = np.array([
        [int(w * map_top_x(right_cfg["top_left_x"])), int(h * y_top)],
        [int(w * map_top_x(right_cfg["top_right_x"])), int(h * y_top)],
        [int(w * map_bot_x(right_cfg["bottom_right_x"])), int(h * y_bot)],
        [int(w * map_bot_x(right_cfg["bottom_left_x"])), int(h * y_bot)],
    ], dtype=np.int32)

    # Dải phân cách tím: độc lập hoàn toàn với map_top_x/map_bot_x.
    med_vals = _median_only_ensure_attrs(roi_cfg)
    med_y_top = _clamp_ratio(med_vals.get("median_y_top", cfg.get("y_top", 0.36)), 0.02, 0.98)
    med_y_bot = _clamp_ratio(med_vals.get("median_y_bot", cfg.get("y_bot", 0.92)), med_y_top + 0.02, 0.99)
    median = np.array([
        [int(w * _clamp_ratio(med_vals.get("median_top_left_x", 0.49))), int(h * med_y_top)],
        [int(w * _clamp_ratio(med_vals.get("median_top_right_x", 0.595))), int(h * med_y_top)],
        [int(w * _clamp_ratio(med_vals.get("median_bottom_right_x", 0.57))), int(h * med_y_bot)],
        [int(w * _clamp_ratio(med_vals.get("median_bottom_left_x", 0.43))), int(h * med_y_bot)],
    ], dtype=np.int32)

    return [("LEFT", left_road), ("RIGHT", right_road)], median


def _median_only_slider_value(roi_obj, attr, default):
    try:
        return int(round(float(getattr(roi_obj, attr, default)) * 100))
    except Exception:
        return int(round(float(default) * 100))


def _median_only_set_attr(self, attr, value):
    try:
        if not hasattr(self.config, "roi") or self.config.roi is None:
            self.config.roi = CauHinhROI()
        setattr(self.config.roi, attr, float(value) / 100.0)
        # Gợi ý trạng thái để người dùng biết đang chỉnh đúng lớp tím, không phải làn vàng.
        if hasattr(self, "lbl_status"):
            self.lbl_status.setText("Đã chỉnh riêng dải phân cách tím. Vùng làn đường không bị kéo theo.")
    except Exception as e:
        ghi_log(f"Lỗi cập nhật slider dải phân cách tím {attr}: {e}")


def _median_only_save_json(self):
    try:
        vals = _median_only_ensure_attrs(getattr(self.config, "roi", None))
        cfg = doc_cau_hinh_roi_duong()
        if not isinstance(cfg, dict):
            cfg = json.loads(json.dumps(DEFAULT_ROI_ROAD_CONFIG))
        med = cfg.get("median", {}) if isinstance(cfg.get("median", {}), dict) else {}
        med.update({
            "top_left_x": float(vals["median_top_left_x"]),
            "top_right_x": float(vals["median_top_right_x"]),
            "bottom_right_x": float(vals["median_bottom_right_x"]),
            "bottom_left_x": float(vals["median_bottom_left_x"]),
            "y_top": float(vals["median_y_top"]),
            "y_bot": float(vals["median_y_bot"]),
        })
        cfg["median"] = med
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(ROI_ROAD_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        if hasattr(self, "lbl_status"):
            self.lbl_status.setText("Đã lưu cấu hình dải phân cách tím vào data_v5/roi_road_config.json")
        try:
            QtWidgets.QMessageBox.information(self, "Đã lưu", "Đã lưu riêng vùng dải phân cách tím. Làn đường vàng/xanh không bị thay đổi.")
        except Exception:
            pass
    except Exception as e:
        ghi_log(f"Lỗi lưu dải phân cách tím: {e}")
        try:
            QtWidgets.QMessageBox.warning(self, "Lỗi", f"Không lưu được dải phân cách tím:\n{e}")
        except Exception:
            pass


def _median_only_reset(self):
    try:
        vals = {
            "median_top_left_x": DEFAULT_ROI_ROAD_CONFIG["median"]["top_left_x"],
            "median_top_right_x": DEFAULT_ROI_ROAD_CONFIG["median"]["top_right_x"],
            "median_bottom_right_x": DEFAULT_ROI_ROAD_CONFIG["median"]["bottom_right_x"],
            "median_bottom_left_x": DEFAULT_ROI_ROAD_CONFIG["median"]["bottom_left_x"],
            "median_y_top": DEFAULT_ROI_ROAD_CONFIG.get("y_top", 0.36),
            "median_y_bot": DEFAULT_ROI_ROAD_CONFIG.get("y_bot", 0.92),
        }
        if not hasattr(self.config, "roi") or self.config.roi is None:
            self.config.roi = CauHinhROI()
        for attr, val in vals.items():
            setattr(self.config.roi, attr, float(val))
        for slider_attr, attr in [
            ("sld_med_tl", "median_top_left_x"),
            ("sld_med_tr", "median_top_right_x"),
            ("sld_med_bl", "median_bottom_left_x"),
            ("sld_med_br", "median_bottom_right_x"),
            ("sld_med_ytop", "median_y_top"),
            ("sld_med_ybot", "median_y_bot"),
        ]:
            if hasattr(self, slider_attr):
                getattr(self, slider_attr).setValue(int(round(vals[attr] * 100)))
        if hasattr(self, "lbl_status"):
            self.lbl_status.setText("Đã đặt lại riêng dải phân cách tím.")
    except Exception as e:
        ghi_log(f"Lỗi reset dải phân cách tím: {e}")


try:
    _median_only_old_build_roi = GiaoDienChinh.tao_trang_roi

    def _median_only_build_roi_page(self):
        page = _median_only_old_build_roi(self)
        vals = _median_only_ensure_attrs(getattr(self.config, "roi", None))

        c_med = KhungNoiDung(
            "Dải phân cách tím",
            "Chỉnh riêng vùng dải phân cách ở giữa video. Các thanh này chỉ làm đổi vùng tím, không kéo theo vùng làn đường màu vàng/xanh."
        )
        note = QtWidgets.QLabel(
            "Cách dùng: chỉnh mép trên trước cho khớp dải phân cách ở xa, sau đó chỉnh mép dưới cho khớp phần gần camera. "
            "Bấm Lưu để lần sau mở video vẫn giữ cấu hình."
        )
        note.setWordWrap(True)
        note.setObjectName("SectionHint")
        c_med.lay.addWidget(note)

        self.sld_med_tl = ThanhTruotCoNhan("Tím mép trên trái X (%)", 0, 100, _median_only_slider_value(self.config.roi, "median_top_left_x", vals["median_top_left_x"]))
        self.sld_med_tr = ThanhTruotCoNhan("Tím mép trên phải X (%)", 0, 100, _median_only_slider_value(self.config.roi, "median_top_right_x", vals["median_top_right_x"]))
        self.sld_med_bl = ThanhTruotCoNhan("Tím mép dưới trái X (%)", 0, 100, _median_only_slider_value(self.config.roi, "median_bottom_left_x", vals["median_bottom_left_x"]))
        self.sld_med_br = ThanhTruotCoNhan("Tím mép dưới phải X (%)", 0, 100, _median_only_slider_value(self.config.roi, "median_bottom_right_x", vals["median_bottom_right_x"]))
        self.sld_med_ytop = ThanhTruotCoNhan("Tím bắt đầu Y (%)", 0, 95, _median_only_slider_value(self.config.roi, "median_y_top", vals["median_y_top"]))
        self.sld_med_ybot = ThanhTruotCoNhan("Tím kết thúc Y (%)", 5, 99, _median_only_slider_value(self.config.roi, "median_y_bot", vals["median_y_bot"]))

        for wdg in [self.sld_med_tl, self.sld_med_tr, self.sld_med_bl, self.sld_med_br, self.sld_med_ytop, self.sld_med_ybot]:
            c_med.lay.addWidget(wdg)

        btn_row = QtWidgets.QHBoxLayout()
        self.btn_save_median_roi = QtWidgets.QPushButton("Lưu dải phân cách tím")
        self.btn_save_median_roi.setObjectName("SuccessBtn")
        self.btn_reset_median_roi = QtWidgets.QPushButton("Reset dải tím")
        self.btn_reset_median_roi.setObjectName("SecondaryBtn")
        btn_row.addWidget(self.btn_save_median_roi)
        btn_row.addWidget(self.btn_reset_median_roi)
        c_med.lay.addLayout(btn_row)

        # Đưa nhóm này ngay sau ROI hình thang nếu có thể, không phá bố cục cũ.
        try:
            page.content.insertWidget(3, c_med)
        except Exception:
            page.content.addWidget(c_med)
        return page

    GiaoDienChinh.tao_trang_roi = _median_only_build_roi_page
except Exception as e:
    ghi_log(f"Không thể thêm UI chỉnh riêng dải phân cách tím: {e}")


try:
    _median_only_old_bind = GiaoDienChinh._gan_trang_thai_ban_dau

    def _median_only_bind_initial(self):
        _median_only_old_bind(self)
        pairs = [
            ("sld_med_tl", "median_top_left_x"),
            ("sld_med_tr", "median_top_right_x"),
            ("sld_med_bl", "median_bottom_left_x"),
            ("sld_med_br", "median_bottom_right_x"),
            ("sld_med_ytop", "median_y_top"),
            ("sld_med_ybot", "median_y_bot"),
        ]
        for slider_name, attr in pairs:
            if hasattr(self, slider_name):
                try:
                    getattr(self, slider_name).valueChanged.connect(lambda v, a=attr: _median_only_set_attr(self, a, v))
                except Exception as e:
                    ghi_log(f"Không thể bind {slider_name}: {e}")
        if hasattr(self, "btn_save_median_roi"):
            try:
                self.btn_save_median_roi.clicked.connect(lambda: _median_only_save_json(self))
            except Exception:
                pass
        if hasattr(self, "btn_reset_median_roi"):
            try:
                self.btn_reset_median_roi.clicked.connect(lambda: _median_only_reset(self))
            except Exception:
                pass

    GiaoDienChinh._gan_trang_thai_ban_dau = _median_only_bind_initial
except Exception as e:
    ghi_log(f"Không thể bind UI chỉnh riêng dải phân cách tím: {e}")


try:
    _median_only_old_controls = GiaoDienChinh.bat_tat_dieu_khien_khi_chay

    def _median_only_controls_runtime(self, running: bool):
        _median_only_old_controls(self, running)
        # Cho phép chỉnh dải tím ngay khi video đang chạy, để căn ROI trực quan theo frame.
        for name in (
            "sld_med_tl", "sld_med_tr", "sld_med_bl", "sld_med_br",
            "sld_med_ytop", "sld_med_ybot", "btn_save_median_roi", "btn_reset_median_roi"
        ):
            if hasattr(self, name):
                try:
                    getattr(self, name).setEnabled(True)
                except Exception:
                    pass

    GiaoDienChinh.bat_tat_dieu_khien_khi_chay = _median_only_controls_runtime
except Exception as e:
    ghi_log(f"Không thể giữ control dải tím khi chạy: {e}")



# =========================================================
# LIVE MEDIAN ROI PATCH - KÉO SLIDER LÀ THẤY NGAY TRÊN VIDEO
# =========================================================
# Bản trước đã tách riêng dải phân cách tím, nhưng worker vẽ video vẫn đọc
# _final_all_lanes(w, h) theo cấu hình cũ nên đôi khi phải bấm Lưu/chạy lại mới thấy.
# Patch này dùng một biến live dùng chung giữa UI và worker: kéo slider -> cập nhật live object
# -> frame kế tiếp vẽ lại vùng tím ngay, không làm thay đổi vùng làn đường vàng/xanh.
_LIVE_MEDIAN_ROI_OBJECT = None


def _median_live_sync_from_ui(ui_obj=None):
    """Đưa cấu hình median hiện tại của UI vào biến live để worker đọc ngay."""
    global _LIVE_MEDIAN_ROI_OBJECT
    try:
        roi = getattr(getattr(ui_obj, "config", None), "roi", None) if ui_obj is not None else None
        if roi is not None:
            _median_only_ensure_attrs(roi)
            _LIVE_MEDIAN_ROI_OBJECT = roi
            return roi
    except Exception as e:
        ghi_log(f"Lỗi sync live median ROI từ UI: {e}")
    try:
        dummy = CauHinhROI()
        _median_only_ensure_attrs(dummy)
        _LIVE_MEDIAN_ROI_OBJECT = dummy
        return dummy
    except Exception:
        return None


def _median_live_save_silent(roi_obj):
    """Tự lưu nhẹ vào JSON khi kéo slider, không hiện popup phiền phức."""
    try:
        vals = _median_only_ensure_attrs(roi_obj)
        cfg = doc_cau_hinh_roi_duong()
        if not isinstance(cfg, dict):
            cfg = json.loads(json.dumps(DEFAULT_ROI_ROAD_CONFIG))
        med = cfg.get("median", {}) if isinstance(cfg.get("median", {}), dict) else {}
        med.update({
            "top_left_x": float(vals["median_top_left_x"]),
            "top_right_x": float(vals["median_top_right_x"]),
            "bottom_right_x": float(vals["median_bottom_right_x"]),
            "bottom_left_x": float(vals["median_bottom_left_x"]),
            "y_top": float(vals["median_y_top"]),
            "y_bot": float(vals["median_y_bot"]),
        })
        cfg["median"] = med
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(ROI_ROAD_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        ghi_log(f"Lỗi auto-save live median ROI: {e}")


# Ghi đè hàm all-lanes để worker vẽ dải tím từ cấu hình live thay vì chỉ đọc JSON cũ.
def _final_all_lanes(w, h, roi_cfg=None):
    try:
        live_roi = roi_cfg or _LIVE_MEDIAN_ROI_OBJECT
        rois, median = _final_roi_chuan_bo_median(w, h, live_roi)
        lanes = []
        for side, poly in rois:
            lanes.extend(_final_split_lanes(side, poly, 3))
        return rois, median, lanes
    except Exception as e:
        ghi_log(f"Lỗi dựng live ROI/dải phân cách: {e}")
        rois, median = _final_roi_chuan_bo_median(w, h, None)
        lanes = []
        for side, poly in rois:
            lanes.extend(_final_split_lanes(side, poly, 3))
        return rois, median, lanes


try:
    _median_live_old_set_attr = _median_only_set_attr

    def _median_only_set_attr(self, attr, value):
        try:
            _median_live_old_set_attr(self, attr, value)
        except Exception as e:
            ghi_log(f"Lỗi gọi setter cũ của dải tím: {e}")
            try:
                if not hasattr(self.config, "roi") or self.config.roi is None:
                    self.config.roi = CauHinhROI()
                setattr(self.config.roi, attr, float(value) / 100.0)
            except Exception:
                pass

        try:
            roi = _median_live_sync_from_ui(self)
            _median_live_save_silent(roi)
            # Đẩy trực tiếp sang worker đang chạy nếu worker giữ reference khác.
            if hasattr(self, "worker") and self.worker is not None:
                try:
                    self.worker.config.roi = roi
                except Exception:
                    pass
            if hasattr(self, "lbl_status"):
                self.lbl_status.setText(
                    "Đã áp dụng trực tiếp dải phân cách tím lên video. Không cần bấm Lưu để xem thay đổi."
                )
        except Exception as e:
            ghi_log(f"Lỗi áp dụng live dải phân cách tím: {e}")
except Exception as e:
    ghi_log(f"Không thể vá live setter dải phân cách tím: {e}")


try:
    _median_live_old_reset = _median_only_reset

    def _median_only_reset(self):
        try:
            _median_live_old_reset(self)
        finally:
            try:
                roi = _median_live_sync_from_ui(self)
                _median_live_save_silent(roi)
                if hasattr(self, "worker") and self.worker is not None:
                    try:
                        self.worker.config.roi = roi
                    except Exception:
                        pass
                if hasattr(self, "lbl_status"):
                    self.lbl_status.setText("Đã reset và áp dụng trực tiếp dải phân cách tím lên video.")
            except Exception as e:
                ghi_log(f"Lỗi reset live dải phân cách tím: {e}")
except Exception as e:
    ghi_log(f"Không thể vá live reset dải phân cách tím: {e}")


try:
    _median_live_old_bind_initial = GiaoDienChinh._gan_trang_thai_ban_dau

    def _median_live_bind_initial(self):
        _median_live_old_bind_initial(self)
        _median_live_sync_from_ui(self)
        try:
            if hasattr(self, "btn_save_median_roi"):
                self.btn_save_median_roi.setText("Lưu cấu hình tím")
            # Bỏ hiểu nhầm: giờ kéo slider đã thấy ngay, nút lưu chỉ còn là lưu chắc cấu hình.
            if hasattr(self, "lbl_status"):
                self.lbl_status.setText("Kéo thanh dải tím sẽ áp dụng trực tiếp lên video, không cần bấm Lưu để xem.")
        except Exception:
            pass

    GiaoDienChinh._gan_trang_thai_ban_dau = _median_live_bind_initial
except Exception as e:
    ghi_log(f"Không thể vá bind live dải phân cách tím: {e}")




# =========================================================
# FINAL_HCM_PATCH - CHỈ THÊM CÔNG THỨC HCM/VSL CUỐI FILE
# Không sửa class/hàm/giao diện/ROI/YOLO/MQTT/báo cáo/show_frame/video_label hiện có.
# Patch này chỉ bọc XuLyVideo.xu_ly_khung_hinh để cập nhật VSL thực tế hơn.
# =========================================================
try:
    FINAL_HCM_PCU = {
        "car": 1.0,
        "motorcycle": 0.3,
        "bicycle": 0.2,
        "truck": 2.0,
        "bus": 2.5,
    }

    FINAL_HCM_ET = float(os.getenv("VSL_HCM_ET", "1.5"))
    FINAL_HCM_PHF = float(os.getenv("VSL_HCM_PHF", "0.92"))
    FINAL_HCM_FP = float(os.getenv("VSL_HCM_FP", "1.0"))
    FINAL_HCM_WINDOW_SEC = float(os.getenv("VSL_HCM_WINDOW_SEC", "60"))
    FINAL_HCM_ROI_LENGTH_M = float(os.getenv("VSL_HCM_ROI_LENGTH_M", "500"))
    FINAL_HCM_COUNT_LINE_RATIO = float(os.getenv("VSL_HCM_COUNT_LINE_RATIO", "0.70"))
    FINAL_HCM_MATCH_PX = float(os.getenv("VSL_HCM_MATCH_PX", "150"))

    def _final_hcm_to_float(value, default=0.0):
        try:
            if value is None:
                return float(default)
            return float(value)
        except Exception:
            return float(default)

    def _final_hcm_to_int(value, default=0):
        try:
            if value is None:
                return int(default)
            return int(value)
        except Exception:
            return int(default)

    def _final_hcm_floor_to_10(value, vsl_min, vsl_max):
        value = max(float(vsl_min), min(float(vsl_max), float(value)))
        return int(max(vsl_min, min(vsl_max, (int(value) // 10) * 10)))

    def _final_hcm_norm_text(value):
        try:
            return str(value or "").strip().lower()
        except Exception:
            return ""

    def _final_hcm_weather_cap(weather, vsl_max):
        w = _final_hcm_norm_text(weather)
        if "mưa nhỏ" in w or "mua nho" in w or "light rain" in w:
            return min(vsl_max, 90)
        if "mưa vừa" in w or "mua vua" in w or "moderate rain" in w:
            return min(vsl_max, 80)
        if "mưa to" in w or "mua to" in w or "heavy rain" in w:
            return min(vsl_max, 70)
        if "sương mù mỏng" in w or "suong mu mong" in w or "light fog" in w:
            return min(vsl_max, 80)
        if "sương mù vừa" in w or "suong mu vua" in w or "moderate fog" in w:
            return min(vsl_max, 70)
        if "sương mù dày" in w or "suong mu day" in w or "dense fog" in w:
            return min(vsl_max, 60)
        if w == "mưa" or w == "mua":
            return min(vsl_max, 80)
        if w == "sương mù" or w == "suong mu":
            return min(vsl_max, 70)
        return vsl_max

    def _final_hcm_incident_cap(incident, vsl_max):
        inc = _final_hcm_norm_text(incident)
        if "nghiêm trọng" in inc or "nghiem trong" in inc or "serious" in inc or "nặng" in inc or "nang" in inc:
            return min(vsl_max, 40)
        if "nhẹ" in inc or "nhe" in inc or "minor" in inc:
            return min(vsl_max, 70)
        return vsl_max

    def _final_hcm_los(D_star):
        D_star = float(D_star)
        if D_star <= 7:
            return "A"
        if D_star <= 11:
            return "B"
        if D_star <= 16:
            return "C"
        if D_star <= 22:
            return "D"
        if D_star <= 28:
            return "E"
        return "F"

    def _final_hcm_v_by_los(los, vsl_min, vsl_max):
        if los in ("A", "B"):
            return vsl_max
        if los == "C":
            return max(vsl_min, vsl_max - 10)
        if los == "D":
            return max(vsl_min, vsl_max - 20)
        if los == "E":
            return max(vsl_min, vsl_max - 30)
        return vsl_min

    def _final_hcm_density_text(los):
        if los in ("A", "B"):
            return "THẤP"
        if los in ("C", "D"):
            return "TRUNG BÌNH"
        return "CAO"

    def _final_hcm_state_text(los):
        if los == "A":
            return "Lưu thông tốt"
        if los in ("B", "C"):
            return "Lưu thông ổn định"
        if los in ("D", "E"):
            return "Mật độ cao"
        return "Nguy cơ ùn tắc"

    def _final_hcm_box_parts(box):
        """Trả về x1,y1,x2,y2,name,cx,cy,in_roi an toàn từ tuple detection cũ."""
        try:
            x1, y1, x2, y2 = box[0], box[1], box[2], box[3]
            name = str(box[4])
            cx = box[7] if len(box) > 7 else (float(x1) + float(x2)) / 2.0
            cy = box[8] if len(box) > 8 else (float(y1) + float(y2)) / 2.0
            in_roi = bool(box[9]) if len(box) > 9 else True
            return float(x1), float(y1), float(x2), float(y2), name, float(cx), float(cy), in_roi
        except Exception:
            return 0.0, 0.0, 0.0, 0.0, "unknown", 0.0, 0.0, False

    def _final_hcm_collect_counts(stats, boxes):
        counts = {k: 0 for k in FINAL_HCM_PCU.keys()}
        pcu_roi = 0.0
        total_roi = 0

        for box in boxes or []:
            _x1, _y1, _x2, _y2, name, _cx, _cy, in_roi = _final_hcm_box_parts(box)
            if not in_roi:
                continue
            if name not in counts:
                # Không đưa class lạ vào công thức để tránh nhiễu.
                continue
            counts[name] += 1
            total_roi += 1
            pcu_roi += FINAL_HCM_PCU.get(name, 1.0)

        # Nếu frame hiện tại không có box do chưa inference ở stride này,
        # lấy tạm class_counts cũ để D_roi không tụt ảo về 0.
        if total_roi <= 0:
            old_counts = {}
            try:
                old_counts = dict(stats.get("class_counts", {}) or {})
            except Exception:
                old_counts = {}
            for name in counts:
                counts[name] = _final_hcm_to_int(old_counts.get(name, 0), 0)
            total_roi = sum(counts.values())
            pcu_roi = sum(counts.get(name, 0) * FINAL_HCM_PCU.get(name, 1.0) for name in counts)

        return counts, float(pcu_roi), int(total_roi)

    class _FinalHCMFlowCounter:
        def __init__(self):
            self.tracks = {}
            self.next_id = 1
            self.events = deque()
            self.ttl_max = 45

        def _match(self, name, cx, cy):
            best_id = None
            best_dist = None
            for tid, tr in self.tracks.items():
                if tr.get("name") != name:
                    continue
                px, py = tr.get("center", (cx, cy))
                dist = ((float(cx) - float(px)) ** 2 + (float(cy) - float(py)) ** 2) ** 0.5
                if dist <= FINAL_HCM_MATCH_PX and (best_dist is None or dist < best_dist):
                    best_dist = dist
                    best_id = tid
            return best_id

        def update(self, boxes, frame_h, t_sec, window_sec):
            y_line = float(frame_h) * float(FINAL_HCM_COUNT_LINE_RATIO)
            for tid in list(self.tracks.keys()):
                self.tracks[tid]["ttl"] = self.tracks[tid].get("ttl", self.ttl_max) - 1
                if self.tracks[tid]["ttl"] <= 0:
                    del self.tracks[tid]

            for box in boxes or []:
                _x1, _y1, _x2, _y2, name, cx, cy, in_roi = _final_hcm_box_parts(box)
                if not in_roi or name not in FINAL_HCM_PCU:
                    continue

                tid = self._match(name, cx, cy)
                if tid is None:
                    tid = self.next_id
                    self.next_id += 1
                    self.tracks[tid] = {
                        "name": name,
                        "center": (cx, cy),
                        "prev_y": cy,
                        "ttl": self.ttl_max,
                    }

                tr = self.tracks[tid]
                prev_y = float(tr.get("prev_y", cy))
                cur_y = float(cy)
                crossed = (prev_y < y_line <= cur_y) or (prev_y > y_line >= cur_y)
                if crossed:
                    self.events.append((float(t_sec), name))

                tr["center"] = (cx, cy)
                tr["prev_y"] = cy
                tr["name"] = name
                tr["ttl"] = self.ttl_max

            min_t = float(t_sec) - float(window_sec)
            while self.events and self.events[0][0] < min_t:
                self.events.popleft()

            return len(self.events)

    def _final_hcm_speed(stats, worker, vsl_max):
        for key in ("toc_do_tb_kmh", "speed_avg_kmh"):
            value = _final_hcm_to_float(stats.get(key, 0.0), 0.0)
            if value > 1.0:
                return value

        try:
            speeds = worker.speed_tracker.lay_toc_do()
            speeds = [float(v) for v in speeds if v is not None and float(v) > 1.0]
            if speeds:
                return sum(speeds) / len(speeds)
        except Exception:
            pass

        return float(vsl_max)

    def _final_hcm_compute(worker, frame):
        stats = dict(getattr(worker, "last_stats", {}) or {})
        cfg = getattr(worker, "config", None)
        vsl_cfg = getattr(cfg, "vsl", None)
        lane_cfg = getattr(cfg, "lane", None)

        vsl_min = _final_hcm_to_int(getattr(vsl_cfg, "vsl_min", 40), 40)
        vsl_max = _final_hcm_to_int(getattr(vsl_cfg, "vsl_max", 100), 100)
        if vsl_max < vsl_min:
            vsl_max = vsl_min

        N_lane = max(1, _final_hcm_to_int(getattr(lane_cfg, "lane_count", 1), 1))
        weather = getattr(vsl_cfg, "weather", "Trời quang")
        incident = getattr(vsl_cfg, "incident", "Không")
        control_mode = getattr(vsl_cfg, "control_mode", "Tự động")
        manual_vsl = _final_hcm_to_int(getattr(vsl_cfg, "manual_vsl", vsl_max), vsl_max)

        boxes = list(getattr(worker, "last_inference_boxes", []) or [])
        class_counts, PCU_roi, N_total = _final_hcm_collect_counts(stats, boxes)

        N_truck = class_counts.get("truck", 0)
        N_bus = class_counts.get("bus", 0)
        P_HV = (N_truck + N_bus) / max(1, N_total)
        f_HV = 1.0 / max(0.05, (1.0 + P_HV * (FINAL_HCM_ET - 1.0)))

        S = _final_hcm_speed(stats, worker, vsl_max)

        h, _w = frame.shape[:2]
        t_sec = getattr(worker, "frame_idx", 0) / max(1.0, float(getattr(worker, "fps_video", 25.0) or 25.0))
        if not hasattr(worker, "_final_hcm_flow_counter"):
            worker._final_hcm_flow_counter = _FinalHCMFlowCounter()

        N_cross = worker._final_hcm_flow_counter.update(boxes, h, t_sec, FINAL_HCM_WINDOW_SEC)
        V_flow = float(N_cross) * 3600.0 / max(1.0, float(FINAL_HCM_WINDOW_SEC))

        D_flow = V_flow / max(1.0, FINAL_HCM_PHF * N_lane * f_HV * FINAL_HCM_FP * max(1.0, S))

        L_eff_km = max(0.05, float(FINAL_HCM_ROI_LENGTH_M) / 1000.0)
        D_roi = PCU_roi / max(0.05, L_eff_km * N_lane)

        D_star = max(float(D_flow), float(D_roi))
        LOS = _final_hcm_los(D_star)

        V_HCM = _final_hcm_v_by_los(LOS, vsl_min, vsl_max)
        V_obs = min(vsl_max, S + 10.0) if S > 0 else vsl_max
        V_weather = _final_hcm_weather_cap(weather, vsl_max)
        V_incident = _final_hcm_incident_cap(incident, vsl_max)
        V_legal = vsl_max

        raw_vsl = min(vsl_max, V_HCM, V_obs, V_weather, V_incident, V_legal)
        new_vsl = _final_hcm_floor_to_10(max(vsl_min, raw_vsl), vsl_min, vsl_max)

        if str(control_mode).strip().lower() in ("thủ công", "thu cong", "manual"):
            new_vsl = _final_hcm_floor_to_10(manual_vsl, vsl_min, vsl_max)
            reason_mode = f"can thiệp thủ công={new_vsl}"
        else:
            reason_mode = "HCM tự động"

        old_vsl = getattr(worker, "_final_hcm_last_vsl", None)
        if old_vsl is None:
            final_vsl = new_vsl
        elif new_vsl < old_vsl:
            final_vsl = new_vsl
        elif new_vsl > old_vsl:
            final_vsl = min(new_vsl, int(old_vsl) + 10)
        else:
            final_vsl = new_vsl
        worker._final_hcm_last_vsl = int(final_vsl)

        stats["suggested_vsl"] = int(final_vsl)
        stats["density"] = _final_hcm_density_text(LOS)
        stats["traffic_state"] = _final_hcm_state_text(LOS)
        stats["reason"] = (
            f"{reason_mode} | LOS={LOS} | D*={D_star:.1f} pc/km/làn "
            f"| D_flow={D_flow:.1f} | D_roi={D_roi:.1f} | "
            f"N_cross={N_cross}/{int(FINAL_HCM_WINDOW_SEC)}s | S={S:.1f} km/h | "
            f"fHV={f_HV:.2f} | PCU_roi={PCU_roi:.1f} | "
            f"min(HCM={int(V_HCM)}, OBS={int(V_obs)}, WEATHER={int(V_weather)}, INCIDENT={int(V_incident)}, LEGAL={int(V_legal)})"
        )
        stats["class_counts"] = class_counts
        stats["hcm_D_flow"] = round(float(D_flow), 3)
        stats["hcm_D_roi"] = round(float(D_roi), 3)
        stats["hcm_D_star"] = round(float(D_star), 3)
        stats["hcm_LOS"] = LOS
        stats["hcm_P_HV"] = round(float(P_HV), 4)
        stats["hcm_f_HV"] = round(float(f_HV), 4)
        stats["hcm_V_flow"] = round(float(V_flow), 3)
        stats["hcm_N_cross"] = int(N_cross)
        stats["hcm_speed_S_kmh"] = round(float(S), 2)
        stats["hcm_formula"] = "D*=max(D_flow,D_roi); VSL=floor10(max(Vmin,min(Vmax,V_HCM,V_obs,V_weather,V_incident,V_legal)))"

        return stats

    _final_hcm_old_xu_ly_khung_hinh = XuLyVideo.xu_ly_khung_hinh

    def _final_hcm_xu_ly_khung_hinh(self, frame):
        frame = _final_hcm_old_xu_ly_khung_hinh(self, frame)
        try:
            stats = _final_hcm_compute(self, frame)
            self.last_stats = stats

            try:
                self.statsReady.emit(self.last_stats)
            except Exception:
                pass

            try:
                los = self.last_stats.get("hcm_LOS", "-")
                vsl = self.last_stats.get("suggested_vsl", "-")
                dstar = _final_hcm_to_float(self.last_stats.get("hcm_D_star", 0.0), 0.0)
                line1 = f"HCM VSL: {vsl} km/h | LOS {los} | D*={dstar:.1f}"
                line2 = f"Dflow={self.last_stats.get('hcm_D_flow', 0)} | Droi={self.last_stats.get('hcm_D_roi', 0)} | S={self.last_stats.get('hcm_speed_S_kmh', 0)} km/h"
                cv2.rectangle(frame, (10, 10), (650, 72), (0, 0, 0), -1)
                cv2.putText(frame, line1, (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (0, 255, 255), 2, cv2.LINE_AA)
                cv2.putText(frame, line2, (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (220, 255, 220), 1, cv2.LINE_AA)
            except Exception:
                pass

        except Exception as e:
            try:
                ghi_log(f"FINAL_HCM_PATCH lỗi khi tính VSL: {e}")
            except Exception:
                pass
        return frame

    XuLyVideo.xu_ly_khung_hinh = _final_hcm_xu_ly_khung_hinh
    try:
        ghi_log("FINAL_HCM_PATCH đã được nạp: thêm công thức HCM/VSL cuối file, không đổi giao diện.")
    except Exception:
        pass

except Exception as e:
    try:
        ghi_log(f"FINAL_HCM_PATCH không thể nạp: {e}")
    except Exception:
        pass


try:
    # FINAL_VISIBLE_VSL_PATCH: lop bao ve cuoi cung cho VSL HCM/ROI va UI.
    def _final_visible_vsl_safe_int(value, default=0):
        try:
            if value is None or str(value).strip() == "":
                return int(default)
            return int(float(value))
        except Exception:
            return int(default)


    def _final_visible_vsl_los_from_dstar(value):
        try:
            d_star = float(value)
        except Exception:
            return "-"
        if d_star <= 7:
            return "A"
        if d_star <= 11:
            return "B"
        if d_star <= 16:
            return "C"
        if d_star <= 22:
            return "D"
        if d_star <= 28:
            return "E"
        return "F"


    def _final_visible_vsl_config_bounds(obj):
        cfg = getattr(obj, "config", None)
        vsl_cfg = getattr(cfg, "vsl", None)
        vsl_min = _final_visible_vsl_safe_int(getattr(vsl_cfg, "vsl_min", 40), 40)
        vsl_max = _final_visible_vsl_safe_int(getattr(vsl_cfg, "vsl_max", 100), 100)
        if vsl_max < vsl_min:
            vsl_max = vsl_min
        return vsl_min, vsl_max


    def _final_visible_vsl_push_to_ui(self, stats):
        if not isinstance(stats, dict):
            stats = {}
        else:
            stats = dict(stats)

        vsl_min, vsl_max = _final_visible_vsl_config_bounds(self)
        vsl = _final_visible_vsl_safe_int(stats.get("suggested_vsl", vsl_max), vsl_max)
        vsl = max(vsl_min, min(vsl_max, vsl))
        stats["suggested_vsl"] = vsl
        density = str(stats.get("density") or "ĐANG KHỞI TẠO")
        traffic_state = str(stats.get("traffic_state") or "Đang phân tích")
        reason = str(stats.get("reason") or "Đang khởi tạo HCM/ROI, VSL sẽ cập nhật theo từng frame")
        if vsl_min >= 70:
            min_reason = f"VSL bị chặn bởi tốc độ tối thiểu = {vsl_min} km/h"
            if min_reason not in reason:
                reason = f"{reason} | {min_reason}"
        stats["density"] = density
        stats["traffic_state"] = traffic_state
        stats["reason"] = reason

        def set_widget_text(attr_name, text_value):
            try:
                widget = getattr(self, attr_name, None)
                if widget is not None and hasattr(widget, "setText"):
                    widget.setText(text_value)
            except Exception:
                pass

        try:
            card_vsl = getattr(self, "card_vsl", None)
            if card_vsl is not None and hasattr(card_vsl, "dat_gia_tri"):
                card_vsl.dat_gia_tri(f"{vsl} km/h")
            if card_vsl is not None and hasattr(card_vsl, "dat_mo_ta"):
                card_vsl.dat_mo_ta(reason)
        except Exception:
            pass

        set_widget_text("lbl_vsl", f"Tốc độ đề xuất: {vsl} km/h")
        set_widget_text("hero_badge_vsl", f"BIỂN BÁO: {vsl} km/h")
        set_widget_text("lbl_density", f"Mật độ: {density}")
        set_widget_text("lbl_state", f"Trạng thái giao thông: {traffic_state}")
        set_widget_text("lbl_reason", f"Lý do: {reason}")

        try:
            card_state = getattr(self, "card_state", None)
            if card_state is not None and hasattr(card_state, "dat_gia_tri"):
                card_state.dat_gia_tri(traffic_state)
            if card_state is not None and hasattr(card_state, "dat_mo_ta"):
                card_state.dat_mo_ta(f"Mật độ: {density}")
        except Exception:
            pass

        try:
            card_roi = getattr(self, "card_roi", None)
            if card_roi is not None and hasattr(card_roi, "dat_gia_tri"):
                card_roi.dat_gia_tri(str(stats.get("vehicles_in_roi", 0)))
            if card_roi is not None and hasattr(card_roi, "dat_mo_ta"):
                card_roi.dat_mo_ta(f"Trung bình trong cửa sổ: {stats.get('avg_vehicles', 0)}")
        except Exception:
            pass

        return stats


    _final_visible_vsl_old_update_ui = GiaoDienChinh.update_ui_from_stats

    def _final_visible_vsl_update_ui_from_stats(self, stats):
        try:
            _final_visible_vsl_old_update_ui(self, stats)
        except Exception as exc:
            try:
                ghi_log(f"FINAL_VISIBLE_VSL UI cu loi: {exc}")
            except Exception:
                pass
        try:
            _final_visible_vsl_push_to_ui(self, stats)
        except Exception as exc:
            try:
                ghi_log(f"FINAL_VISIBLE_VSL khong day duoc UI: {exc}")
            except Exception:
                pass

    GiaoDienChinh.update_ui_from_stats = _final_visible_vsl_update_ui_from_stats


    _final_visible_vsl_old_process = XuLyVideo.xu_ly_khung_hinh

    def _final_visible_vsl_process_frame(self, frame):
        # Chan rieng overlay legacy dai 650 px cua FINAL_HCM_PATCH trong khi goi ham cu.
        # Khong de patch nay lam thay doi cac rectangle/text con lai cua pipeline.
        old_rectangle = cv2.rectangle
        old_put_text = cv2.putText

        def guarded_rectangle(image, pt1, pt2, color, thickness, *args, **kwargs):
            try:
                is_black_fill = int(thickness) == -1 and tuple(int(v) for v in color[:3]) == (0, 0, 0)
                is_legacy_box = is_black_fill and int(pt1[0]) == 10 and int(pt1[1]) == 10 and int(pt2[0]) >= 600
                if is_legacy_box:
                    return image
            except Exception:
                pass
            return old_rectangle(image, pt1, pt2, color, thickness, *args, **kwargs)

        def guarded_put_text(image, text, org, *args, **kwargs):
            try:
                legacy_text = str(text).startswith(("HCM VSL:", "Dflow="))
                if legacy_text and int(org[0]) >= 20 and int(org[1]) <= 72:
                    return image
            except Exception:
                pass
            return old_put_text(image, text, org, *args, **kwargs)

        cv2.rectangle = guarded_rectangle
        cv2.putText = guarded_put_text
        try:
            frame_out = _final_visible_vsl_old_process(self, frame)
        finally:
            cv2.rectangle = old_rectangle
            cv2.putText = old_put_text
        try:
            stats = dict(getattr(self, "last_stats", {}) or {})
        except Exception:
            stats = {}

        vsl_min, vsl_max = _final_visible_vsl_config_bounds(self)
        raw_vsl = stats.get("suggested_vsl")
        try:
            float(raw_vsl)
            invalid_vsl = raw_vsl is None or str(raw_vsl).strip() == ""
        except Exception:
            invalid_vsl = True
        if invalid_vsl:
            vehicles = _final_visible_vsl_safe_int(stats.get("vehicles_in_roi", 0), 0)
            temp_vsl = max(vsl_min, min(vsl_max, vsl_max - vehicles * 5))
            temp_vsl = int(temp_vsl // 10 * 10)
            if temp_vsl < vsl_min:
                temp_vsl = vsl_min
            stats["suggested_vsl"] = temp_vsl
            stats["reason"] = "VSL tạm thời theo ROI, đang chờ đủ dữ liệu HCM"

        had_hcm_data = (
            stats.get("hcm_LOS") not in (None, "", "-")
            or stats.get("hcm_D_star") not in (None, "")
        )
        stats["suggested_vsl"] = _final_visible_vsl_safe_int(stats.get("suggested_vsl"), vsl_max)
        stats["suggested_vsl"] = max(vsl_min, min(vsl_max, stats["suggested_vsl"]))
        if not stats.get("density"):
            stats["density"] = "ĐANG KHỞI TẠO"
        if not stats.get("traffic_state"):
            stats["traffic_state"] = "Đang phân tích"
        if not stats.get("reason"):
            stats["reason"] = "VSL tạm thời theo ROI, đang chờ đủ dữ liệu HCM"
        if stats.get("hcm_D_star") is None:
            stats["hcm_D_star"] = 0.0
        if not stats.get("hcm_LOS"):
            stats["hcm_LOS"] = "-"

        if had_hcm_data:
            try:
                d_star = float(stats.get("hcm_D_star", 0.0))
            except Exception:
                d_star = 0.0
            d_star_text = f"{d_star:.1f}"
            los = str(stats.get("hcm_LOS") or "").strip()
            if not los or los == "-":
                los = _final_visible_vsl_los_from_dstar(d_star)
            stats["hcm_LOS"] = los or "-"
            old_reason = str(stats.get("reason") or "").strip()
            hcm_prefix = f"HCM LOS {stats['hcm_LOS']} | D*={d_star_text}"
            if not old_reason.startswith("HCM LOS "):
                stats["reason"] = f"{hcm_prefix} | {old_reason}" if old_reason else hcm_prefix

        if vsl_min >= 70:
            min_reason = f"VSL bị chặn bởi tốc độ tối thiểu = {vsl_min} km/h"
            current_reason = str(stats.get("reason") or "")
            if min_reason not in current_reason:
                stats["reason"] = f"{current_reason} | {min_reason}" if current_reason else min_reason

        self.last_stats = stats
        self.last_vsl = stats["suggested_vsl"]
        try:
            self.statsReady.emit(stats)
        except Exception:
            pass

        try:
            if frame_out is not None and hasattr(frame_out, "shape") and len(frame_out.shape) >= 2:
                h, w = frame_out.shape[:2]
                los = str(stats.get("hcm_LOS", "-") or "-")
                try:
                    d_star_text = f"{float(stats.get('hcm_D_star', 0.0)):.1f}"
                except Exception:
                    d_star_text = "0.0"
                line1 = f"VSL: {stats['suggested_vsl']} km/h | LOS {los} | D*={d_star_text}"
                line2 = "HCM/ROI realtime"
                font = cv2.FONT_HERSHEY_SIMPLEX
                scale = 0.50
                thickness = 1
                (tw1, _th1), _ = cv2.getTextSize(line1, font, scale, thickness)
                (tw2, _th2), _ = cv2.getTextSize(line2, font, scale, thickness)
                box_w = min(560, max(tw1, tw2) + 18)
                box_h = min(58, max(42, h - 12))
                x0, y0 = 10, 10
                x1 = min(x0 + box_w, max(x0 + 1, w - 2))
                y1 = min(y0 + box_h, max(y0 + 1, h - 2))
                cv2.rectangle(frame_out, (x0, y0), (x1, y1), (0, 0, 0), -1)
                cv2.putText(frame_out, line1, (x0 + 8, min(y0 + 24, y1 - 20)), font, scale, (0, 255, 255), thickness, cv2.LINE_AA)
                cv2.putText(frame_out, line2, (x0 + 8, min(y0 + 46, y1 - 4)), font, scale, (220, 255, 220), thickness, cv2.LINE_AA)
        except Exception:
            pass

        return frame_out

    XuLyVideo.xu_ly_khung_hinh = _final_visible_vsl_process_frame


    if hasattr(GiaoDienChinh, "on_start"):
        _final_visible_vsl_old_on_start = GiaoDienChinh.on_start

        def _final_visible_vsl_on_start(self, *args, **kwargs):
            result = None
            try:
                # PyQt co the tra ve ham start da bind san; khi do khong truyen self lan nua.
                if getattr(_final_visible_vsl_old_on_start, "__self__", None) is not None:
                    result = _final_visible_vsl_old_on_start(*args, **kwargs)
                else:
                    result = _final_visible_vsl_old_on_start(self, *args, **kwargs)
            except Exception as exc:
                try:
                    ghi_log(f"FINAL_VISIBLE_VSL on_start cu loi: {exc}")
                except Exception:
                    pass
            try:
                _vsl_min, vsl_max = _final_visible_vsl_config_bounds(self)
                _final_visible_vsl_push_to_ui(self, {
                    "suggested_vsl": vsl_max,
                    "density": "ĐANG KHỞI TẠO",
                    "traffic_state": "Đang phân tích",
                    "reason": "Đang khởi tạo HCM/ROI, VSL sẽ cập nhật theo từng frame",
                })
            except Exception as exc:
                try:
                    ghi_log(f"FINAL_VISIBLE_VSL khong hien thi VSL luc start: {exc}")
                except Exception:
                    pass
            return result

        GiaoDienChinh.on_start = _final_visible_vsl_on_start

except Exception as _final_visible_vsl_exc:
    try:
        ghi_log(f"FINAL_VISIBLE_VSL khong the nap patch: {_final_visible_vsl_exc}")
    except Exception:
        pass


try:
    # =========================================================
    # FINAL_RUN_FIX_PATCH - SUA LUONG CHON VIDEO/START/WORKER/VSL CUOI FILE
    # =========================================================
    def _final_run_fix_call_method(method, self, *args, **kwargs):
        if method is None:
            return None
        if getattr(method, "__self__", None) is not None:
            return method(*args, **kwargs)
        return method(self, *args, **kwargs)


    def _final_run_fix_set_text(obj, text):
        try:
            if obj is not None and hasattr(obj, "setText"):
                obj.setText(str(text))
        except Exception:
            pass


    def _final_run_fix_configure_runtime(self):
        try:
            detection = getattr(getattr(self, "config", None), "detection", None)
            if detection is None:
                return
            detection.imgsz = int(os.getenv("VSL_RUN_IMGSZ", "640"))
            detection.frame_stride = max(1, int(os.getenv("VSL_RUN_STRIDE", "3")))
            detection.conf_th = float(os.getenv("VSL_RUN_CONF", "0.30"))
            if not CUDA_AVAILABLE:
                detection.use_gpu = False
        except Exception as exc:
            try:
                ghi_log(f"FINAL_RUN_FIX config runtime loi: {exc}")
            except Exception:
                pass


    def _final_run_fix_stop_old_worker(self):
        worker = getattr(self, "worker", None)
        if worker is None:
            return True
        try:
            running = bool(worker.isRunning()) if hasattr(worker, "isRunning") else False
        except Exception:
            running = False

        if running:
            try:
                if hasattr(worker, "yeu_cau_dung"):
                    worker.yeu_cau_dung()
            except Exception:
                pass
            try:
                if hasattr(worker, "dat_tam_dung"):
                    worker.dat_tam_dung(False)
            except Exception:
                pass
            try:
                if hasattr(worker, "quit"):
                    worker.quit()
            except Exception:
                pass
            try:
                if hasattr(worker, "wait"):
                    worker.wait(1500)
            except Exception:
                pass
            try:
                if hasattr(worker, "isRunning") and worker.isRunning() and hasattr(worker, "terminate"):
                    worker.terminate()
                    worker.wait(500)
            except Exception:
                pass

        try:
            still_running = bool(worker.isRunning()) if hasattr(worker, "isRunning") else False
        except Exception:
            still_running = False
        if not still_running:
            try:
                if getattr(self, "worker", None) is worker:
                    self.worker = None
            except Exception:
                pass
        return not still_running


    def _final_run_fix_restore_controls(self):
        try:
            worker = getattr(self, "worker", None)
            running = bool(worker is not None and worker.isRunning())
        except Exception:
            running = False
        try:
            btn_start = getattr(self, "btn_start", None)
            if btn_start is not None:
                btn_start.setEnabled(bool(getattr(self, "video_path", None)) and not running)
        except Exception:
            pass
        try:
            btn_pause = getattr(self, "btn_pause", None)
            if btn_pause is not None:
                btn_pause.setEnabled(running)
        except Exception:
            pass
        try:
            btn_stop = getattr(self, "btn_stop", None)
            if btn_stop is not None:
                btn_stop.setEnabled(running)
        except Exception:
            pass


    def _final_run_fix_validate_video(self_obj, video_path):
        path = str(video_path or "").strip()
        if not path or not os.path.isfile(path):
            return False, None
        cap = None
        try:
            cap = cv2.VideoCapture(path)
            if cap is None or not cap.isOpened():
                return False, None
            ok, first_frame = cap.read()
            if not ok or first_frame is None:
                return False, None
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or first_frame.shape[1])
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or first_frame.shape[0])
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
            return True, {"width": width, "height": height, "fps": fps}
        except Exception as exc:
            try:
                ghi_log(f"FINAL_RUN_FIX validate video loi: {exc}")
            except Exception:
                pass
            return False, None
        finally:
            try:
                if cap is not None:
                    cap.release()
            except Exception:
                pass


    def _final_run_fix_open_video(self, *args, **kwargs):
        result = None
        try:
            result = _final_run_fix_call_method(
                _final_run_fix_old_open_video,
                self,
                *args,
                **kwargs,
            )
        except Exception as exc:
            try:
                ghi_log(f"FINAL_RUN_FIX mo video cu loi: {exc}")
            except Exception:
                pass

        video_path = getattr(self, "video_path", None)
        valid, metadata = _final_run_fix_validate_video(self, video_path)
        if not valid:
            try:
                self.video_path = None
            except Exception:
                pass
            _final_run_fix_set_text(getattr(self, "lbl_video_res", None), "Resolution/FPS: không đọc được video")
            try:
                btn_start = getattr(self, "btn_start", None)
                if btn_start is not None:
                    btn_start.setEnabled(False)
            except Exception:
                pass
            try:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Lỗi video",
                    "Không mở được video hoặc không đọc được frame đầu tiên. Vui lòng chọn file khác.",
                )
            except Exception:
                pass
            return result

        try:
            self.video_path = os.path.abspath(str(video_path))
        except Exception:
            pass
        name = Path(getattr(self, "video_path", video_path)).name
        fps_text = f" | FPS: {metadata['fps']:.1f}" if metadata and metadata.get("fps", 0.0) > 0 else ""
        _final_run_fix_set_text(getattr(self, "lbl_video_name", None), f"Video: {name}")
        _final_run_fix_set_text(
            getattr(self, "lbl_video_res", None),
            f"Resolution: {metadata['width']} x {metadata['height']}{fps_text}",
        )
        _final_run_fix_set_text(getattr(self, "lbl_status", None), f"Đã chọn video: {name}")
        try:
            video_label = getattr(self, "video_label", None)
            if video_label is not None and hasattr(video_label, "setText"):
                video_label.setText("Đã chọn video. Bấm Bắt đầu phân tích.")
        except Exception:
            pass
        try:
            btn_start = getattr(self, "btn_start", None)
            if btn_start is not None:
                btn_start.setEnabled(True)
        except Exception:
            pass
        return result


    def _final_run_fix_push_vsl_to_ui(self, stats):
        if not isinstance(stats, dict):
            stats = {}
        else:
            stats = dict(stats)
        try:
            vsl_cfg = getattr(getattr(self, "config", None), "vsl", None)
            vsl_max = int(float(getattr(vsl_cfg, "vsl_max", 100)))
            vsl_min = int(float(getattr(vsl_cfg, "vsl_min", 40)))
        except Exception:
            vsl_min, vsl_max = 40, 100
        if vsl_max < vsl_min:
            vsl_max = vsl_min
        try:
            vsl = int(float(stats.get("suggested_vsl", vsl_max)))
        except Exception:
            vsl = vsl_max
        vsl = max(vsl_min, min(vsl_max, vsl))
        reason = str(stats.get("reason") or "Đang khởi tạo HCM/ROI, VSL sẽ cập nhật theo từng frame")
        density = str(stats.get("density") or "ĐANG KHỞI TẠO")
        traffic_state = str(stats.get("traffic_state") or "Đang phân tích")
        stats["suggested_vsl"] = vsl
        stats["reason"] = reason

        try:
            card_vsl = getattr(self, "card_vsl", None)
            if card_vsl is not None:
                card_vsl.dat_gia_tri(f"{vsl} km/h")
                card_vsl.dat_mo_ta(reason)
        except Exception:
            pass
        _final_run_fix_set_text(getattr(self, "lbl_vsl", None), f"Tốc độ đề xuất: {vsl} km/h")
        _final_run_fix_set_text(getattr(self, "hero_badge_vsl", None), f"BIỂN BÁO: {vsl} km/h")
        _final_run_fix_set_text(getattr(self, "lbl_density", None), f"Mật độ: {density}")
        _final_run_fix_set_text(getattr(self, "lbl_state", None), f"Trạng thái giao thông: {traffic_state}")
        _final_run_fix_set_text(getattr(self, "lbl_reason", None), f"Lý do: {reason}")
        try:
            card_state = getattr(self, "card_state", None)
            if card_state is not None:
                card_state.dat_gia_tri(traffic_state)
                card_state.dat_mo_ta(f"Mật độ: {density}")
        except Exception:
            pass
        try:
            card_roi = getattr(self, "card_roi", None)
            if card_roi is not None:
                card_roi.dat_gia_tri(str(stats.get("vehicles_in_roi", 0)))
                card_roi.dat_mo_ta(f"Trung bình trong cửa sổ: {stats.get('avg_vehicles', 0)}")
        except Exception:
            pass
        return stats


    def _final_run_fix_restore_after_worker(self):
        try:
            worker = getattr(self, "worker", None)
            if worker is not None and hasattr(worker, "isRunning") and not worker.isRunning():
                self.worker = None
        except Exception:
            pass
        _final_run_fix_restore_controls(self)


    _final_run_fix_old_open_video = getattr(GiaoDienChinh, "on_open_video", None)
    if _final_run_fix_old_open_video is not None:
        GiaoDienChinh.on_open_video = _final_run_fix_open_video
        if hasattr(GiaoDienChinh, "on_chon_video"):
            GiaoDienChinh.on_chon_video = _final_run_fix_open_video


    _final_run_fix_old_update_ui = getattr(GiaoDienChinh, "update_ui_from_stats", None)

    def _final_run_fix_update_ui_from_stats(self, stats):
        try:
            _final_run_fix_call_method(_final_run_fix_old_update_ui, self, stats)
        except Exception as exc:
            try:
                ghi_log(f"FINAL_RUN_FIX update UI cu loi: {exc}")
            except Exception:
                pass
        try:
            _final_run_fix_push_vsl_to_ui(self, stats)
        except Exception as exc:
            try:
                ghi_log(f"FINAL_RUN_FIX push VSL UI loi: {exc}")
            except Exception:
                pass

    GiaoDienChinh.update_ui_from_stats = _final_run_fix_update_ui_from_stats


    _final_run_fix_old_process = XuLyVideo.xu_ly_khung_hinh

    def _final_run_fix_process(self, frame):
        frame_out = _final_run_fix_call_method(_final_run_fix_old_process, self, frame)
        try:
            stats = dict(getattr(self, "last_stats", {}) or {})
        except Exception:
            stats = {}

        try:
            vsl_cfg = getattr(getattr(self, "config", None), "vsl", None)
            vsl_min = int(float(getattr(vsl_cfg, "vsl_min", 40)))
            vsl_max = int(float(getattr(vsl_cfg, "vsl_max", 100)))
        except Exception:
            vsl_min, vsl_max = 40, 100
        if vsl_max < vsl_min:
            vsl_max = vsl_min

        raw_vsl = stats.get("suggested_vsl")
        try:
            invalid_vsl = raw_vsl is None or str(raw_vsl).strip() == "" or not str(float(raw_vsl))
        except Exception:
            invalid_vsl = True
        if invalid_vsl:
            try:
                vehicles = int(float(stats.get("vehicles_in_roi", 0) or 0))
            except Exception:
                vehicles = 0
            temp_vsl = vsl_max - vehicles * 5
            temp_vsl = max(vsl_min, min(vsl_max, temp_vsl))
            temp_vsl = int(temp_vsl // 10 * 10)
            if temp_vsl < vsl_min:
                temp_vsl = vsl_min
            stats["suggested_vsl"] = temp_vsl
            stats["reason"] = "VSL tạm thời theo ROI, đang chờ đủ dữ liệu HCM"

        stats["suggested_vsl"] = max(
            vsl_min,
            min(vsl_max, _final_run_fix_push_vsl_to_ui(self, stats)["suggested_vsl"]),
        )
        stats.setdefault("density", "ĐANG KHỞI TẠO")
        stats.setdefault("traffic_state", "Đang phân tích")
        stats.setdefault("reason", "VSL tạm thời theo ROI, đang chờ đủ dữ liệu HCM")
        had_hcm = stats.get("hcm_LOS") not in (None, "", "-") or stats.get("hcm_D_star") not in (None, "")
        stats.setdefault("hcm_D_star", 0.0)
        stats.setdefault("hcm_LOS", "-")
        if had_hcm:
            try:
                d_star_text = f"{float(stats.get('hcm_D_star', 0.0)):.1f}"
            except Exception:
                d_star_text = str(stats.get("hcm_D_star", "-"))
            los = str(stats.get("hcm_LOS") or "-")
            old_reason = str(stats.get("reason") or "")
            if not old_reason.startswith("HCM LOS "):
                stats["reason"] = f"HCM LOS {los} | D*={d_star_text} | {old_reason}".rstrip(" |")
        if vsl_min >= 70:
            min_reason = f"VSL bị chặn bởi tốc độ tối thiểu = {vsl_min} km/h"
            if min_reason not in str(stats.get("reason") or ""):
                stats["reason"] = f"{stats.get('reason', '')} | {min_reason}".strip(" |")

        self.last_stats = stats
        self.last_vsl = stats["suggested_vsl"]
        try:
            self.statsReady.emit(stats)
        except Exception:
            pass

        try:
            if frame_out is not None and hasattr(frame_out, "shape") and len(frame_out.shape) >= 2:
                h, w = frame_out.shape[:2]
                los = str(stats.get("hcm_LOS", "-") or "-")
                try:
                    d_star_text = f"{float(stats.get('hcm_D_star', 0.0)):.1f}"
                except Exception:
                    d_star_text = "0.0"
                line1 = f"VSL: {stats['suggested_vsl']} km/h | LOS {los} | D*={d_star_text}"
                line2 = "HCM/ROI realtime"
                font = cv2.FONT_HERSHEY_SIMPLEX
                scale = 0.50
                thickness = 1
                (tw1, _), _ = cv2.getTextSize(line1, font, scale, thickness)
                (tw2, _), _ = cv2.getTextSize(line2, font, scale, thickness)
                box_w = min(560, max(tw1, tw2) + 18)
                box_h = min(60, max(42, h - 12))
                x0, y0 = 10, 10
                x1 = min(x0 + box_w, max(x0 + 1, w - 2))
                y1 = min(y0 + box_h, max(y0 + 1, h - 2))
                cv2.rectangle(frame_out, (x0, y0), (x1, y1), (0, 0, 0), -1)
                cv2.putText(frame_out, line1, (x0 + 8, min(y0 + 24, y1 - 20)), font, scale, (0, 255, 255), thickness, cv2.LINE_AA)
                cv2.putText(frame_out, line2, (x0 + 8, min(y0 + 46, y1 - 4)), font, scale, (220, 255, 220), thickness, cv2.LINE_AA)
        except Exception:
            pass
        return frame_out

    XuLyVideo.xu_ly_khung_hinh = _final_run_fix_process


    _final_run_fix_old_start = getattr(GiaoDienChinh, "on_start", None)

    def _final_run_fix_on_start(self, *args, **kwargs):
        _final_run_fix_configure_runtime(self)
        _final_run_fix_stop_old_worker(self)

        video_path = getattr(self, "video_path", None)
        valid, _metadata = _final_run_fix_validate_video(self, video_path)
        if not valid:
            _final_run_fix_set_text(getattr(self, "lbl_status", None), "Chưa chọn video hợp lệ.")
            try:
                QtWidgets.QMessageBox.warning(self, "Chưa có video", "Vui lòng chọn video hợp lệ trước khi bắt đầu phân tích.")
            except Exception:
                pass
            _final_run_fix_restore_controls(self)
            return None

        result = None
        try:
            result = _final_run_fix_call_method(_final_run_fix_old_start, self, *args, **kwargs)
        except Exception as exc:
            try:
                ghi_log(f"FINAL_RUN_FIX start loi: {exc}")
            except Exception:
                pass
            _final_run_fix_stop_old_worker(self)
            _final_run_fix_set_text(getattr(self, "lbl_status", None), f"Lỗi khởi động video: {exc}")
            try:
                QtWidgets.QMessageBox.critical(self, "Lỗi khởi động", str(exc))
            except Exception:
                pass
            _final_run_fix_restore_controls(self)
            return None

        try:
            temp_stats = {
                "suggested_vsl": getattr(getattr(getattr(self, "config", None), "vsl", None), "vsl_max", 100),
                "density": "ĐANG KHỞI TẠO",
                "traffic_state": "Đang phân tích video...",
                "reason": "Đang khởi tạo HCM/ROI, VSL sẽ cập nhật theo từng frame",
            }
            _final_run_fix_push_vsl_to_ui(self, temp_stats)
        except Exception:
            pass
        _final_run_fix_set_text(getattr(self, "lbl_status", None), "Đang phân tích video...")
        _final_run_fix_restore_controls(self)
        return result

    GiaoDienChinh.on_start = _final_run_fix_on_start


    _final_run_fix_old_error = getattr(GiaoDienChinh, "on_worker_error", None)
    if _final_run_fix_old_error is not None:
        def _final_run_fix_on_worker_error(self, err):
            try:
                _final_run_fix_call_method(_final_run_fix_old_error, self, err)
            except Exception as exc:
                try:
                    ghi_log(f"FINAL_RUN_FIX worker error handler loi: {exc}")
                except Exception:
                    pass
            _final_run_fix_stop_old_worker(self)
            _final_run_fix_restore_after_worker(self)

        GiaoDienChinh.on_worker_error = _final_run_fix_on_worker_error


    _final_run_fix_old_finished = getattr(GiaoDienChinh, "on_worker_finished", None)
    if _final_run_fix_old_finished is not None:
        def _final_run_fix_on_worker_finished(self, summary):
            try:
                _final_run_fix_call_method(_final_run_fix_old_finished, self, summary)
            except Exception as exc:
                try:
                    ghi_log(f"FINAL_RUN_FIX worker finished handler loi: {exc}")
                except Exception:
                    pass
            _final_run_fix_restore_after_worker(self)

        GiaoDienChinh.on_worker_finished = _final_run_fix_on_worker_finished

except Exception as _final_run_fix_exc:
    try:
        ghi_log(f"FINAL_RUN_FIX khong the nap patch: {_final_run_fix_exc}")
    except Exception:
        pass


try:
    # FINAL_FIX_ZOOM_VSL_CONTROL_PATCH: sua hien thi toan canh, VSL realtime va dieu khien.
    def _final_fix_call(method, self, *args, **kwargs):
        if method is None:
            return None
        try:
            if getattr(method, "__self__", None) is not None:
                return method(*args, **kwargs)
        except Exception:
            pass
        return method(self, *args, **kwargs)


    def _final_fix_safe_int(value, default=0):
        try:
            return int(float(value))
        except Exception:
            return int(default)


    def _final_fix_safe_float(value, default=0.0):
        try:
            return float(value)
        except Exception:
            return float(default)


    def _final_fix_set_text(widget, value):
        try:
            if widget is not None and hasattr(widget, "setText"):
                widget.setText(str(value))
        except Exception:
            pass


    def _final_fix_slider_value(widget, default=None):
        if widget is None:
            return default
        for obj in (widget, getattr(widget, "slider", None)):
            try:
                getter = getattr(obj, "value", None)
                if callable(getter):
                    return getter()
            except Exception:
                pass
        return default


    def _final_fix_combo_text(widget, default=None):
        try:
            if widget is not None and hasattr(widget, "currentText"):
                return str(widget.currentText())
        except Exception:
            pass
        return default


    def _final_fix_sync_vsl_config_from_ui(self):
        try:
            config = getattr(self, "config", None)
            vsl = getattr(config, "vsl", None)
            if vsl is None:
                return config

            slider_map = (
                ("sld_vmin", "vsl_min"),
                ("sld_vmax", "vsl_max"),
                ("sld_scale_max", "scale_max"),
                ("sld_smoothing", "smoothing_window"),
                ("sld_manual_vsl", "manual_vsl"),
            )
            for widget_name, attr_name in slider_map:
                value = _final_fix_slider_value(getattr(self, widget_name, None), None)
                if value is not None:
                    setattr(vsl, attr_name, _final_fix_safe_int(value, getattr(vsl, attr_name, 0)))

            vsl.vsl_min = max(0, _final_fix_safe_int(getattr(vsl, "vsl_min", 40), 40))
            vsl.vsl_max = max(vsl.vsl_min, _final_fix_safe_int(getattr(vsl, "vsl_max", 100), 100))
            vsl.scale_max = max(1, _final_fix_safe_int(getattr(vsl, "scale_max", 20), 20))
            vsl.smoothing_window = max(1, _final_fix_safe_int(getattr(vsl, "smoothing_window", 30), 30))

            combo_map = (
                ("cbo_weather", "weather"),
                ("cbo_incident", "incident"),
                ("cbo_mode", "control_mode"),
            )
            for widget_name, attr_name in combo_map:
                value = _final_fix_combo_text(getattr(self, widget_name, None), None)
                if value:
                    setattr(vsl, attr_name, value)
        except Exception as exc:
            try:
                ghi_log(f"FINAL_FIX_ZOOM_VSL_CONTROL sync VSL loi: {exc}")
            except Exception:
                pass
        return getattr(getattr(self, "config", None), "vsl", None)


    def _final_fix_apply_worker_config(self):
        try:
            worker = getattr(self, "worker", None)
            if worker is not None and getattr(self, "config", None) is not None:
                worker.config = self.config
        except Exception:
            pass


    def _final_fix_show_status(self_obj, text):
        _final_fix_set_text(getattr(self_obj, "lbl_status", None), text)
        _final_fix_set_text(getattr(self_obj, "status_label", None), text)


    def _final_fix_show_frame_no_zoom(self, qimg):
        video_label = getattr(self, "video_label", None)
        if video_label is None or qimg is None:
            return None
        try:
            pixmap = QtGui.QPixmap.fromImage(qimg)
            if pixmap.isNull():
                return None
            video_label.setAlignment(QtCore.Qt.AlignCenter)
            try:
                video_label.setScaledContents(False)
            except Exception:
                pass
            try:
                video_label.setStyleSheet(
                    (video_label.styleSheet() or "")
                    + "; background:#081120; border:1px solid #d9e6f3;"
                )
            except Exception:
                pass
            target_size = video_label.contentsRect().size()
            if target_size.width() <= 0 or target_size.height() <= 0:
                target_size = video_label.size()
            if target_size.width() <= 0 or target_size.height() <= 0:
                return None
            scaled = pixmap.scaled(
                target_size,
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation,
            )
            video_label.setPixmap(scaled)
            video_label.show()
            return None
        except Exception as exc:
            try:
                ghi_log(f"FINAL_FIX_ZOOM_VSL_CONTROL show_frame loi: {exc}")
            except Exception:
                pass
            return None


    _final_fix_old_show_frame = getattr(GiaoDienChinh, "show_frame", None)
    if _final_fix_old_show_frame is not None:
        GiaoDienChinh.show_frame = _final_fix_show_frame_no_zoom


    def _final_fix_pause_or_resume(self):
        worker = getattr(self, "worker", None)
        try:
            running = bool(worker is not None and worker.isRunning())
        except Exception:
            running = False
        if not running:
            _final_fix_show_status(self, "Chưa có video đang chạy")
            try:
                getattr(self, "btn_pause", None).setEnabled(False)
            except Exception:
                pass
            return None

        try:
            is_paused = bool(getattr(worker, "pause_requested", False))
            if not is_paused:
                is_paused = str(getattr(getattr(self, "btn_pause", None), "text", lambda: "")()) == "Tiếp tục"
        except Exception:
            is_paused = False
        paused = not is_paused
        try:
            method = getattr(worker, "dat_tam_dung", None)
            if callable(method):
                method(paused)
            else:
                worker.pause_requested = paused
        except Exception:
            try:
                worker.pause_requested = paused
            except Exception:
                pass

        button = getattr(self, "btn_pause", None)
        _final_fix_set_text(button, "Tiếp tục" if paused else "Tạm dừng")
        _final_fix_show_status(self, "Đã tạm dừng" if paused else "Đang phân tích...")
        try:
            badge = getattr(self, "badge_live", None)
            _final_fix_set_text(badge, "TRỰC TUYẾN: TẠM DỪNG" if paused else "TRỰC TUYẾN: BẬT")
        except Exception:
            pass
        return paused


    def _final_fix_stop_video(self):
        try:
            multi_worker = getattr(self, "multi_worker", None)
            if multi_worker is not None and hasattr(multi_worker, "dung"):
                multi_worker.dung()
            self.multi_worker = None
        except Exception:
            pass

        worker = getattr(self, "worker", None)
        if worker is not None:
            try:
                method = getattr(worker, "yeu_cau_dung", None)
                if callable(method):
                    method()
            except Exception:
                pass
            try:
                worker.stop_requested = True
            except Exception:
                pass
            try:
                method = getattr(worker, "dat_tam_dung", None)
                if callable(method):
                    method(False)
            except Exception:
                pass
            try:
                method = getattr(worker, "quit", None)
                if callable(method):
                    method()
            except Exception:
                pass
            try:
                method = getattr(worker, "wait", None)
                if callable(method):
                    method(2000)
            except Exception:
                pass
            try:
                if hasattr(worker, "isRunning") and worker.isRunning() and hasattr(worker, "terminate"):
                    worker.terminate()
                    worker.wait(500)
            except Exception:
                pass
            try:
                self.worker = None
            except Exception:
                pass

        try:
            self.che_do_chay = "SINGLE"
        except Exception:
            pass
        try:
            btn_start = getattr(self, "btn_start", None)
            if btn_start is not None:
                btn_start.setEnabled(bool(getattr(self, "video_path", None)))
        except Exception:
            pass
        for attr in ("btn_pause", "btn_stop"):
            try:
                widget = getattr(self, attr, None)
                if widget is not None:
                    widget.setEnabled(False)
            except Exception:
                pass
        _final_fix_set_text(getattr(self, "btn_pause", None), "Tạm dừng")
        _final_fix_show_status(self, "Đã dừng phân tích")
        try:
            _final_fix_set_text(getattr(self, "hero_badge_status", None), "TRẠNG THÁI: ĐÃ DỪNG")
            _final_fix_set_text(getattr(self, "badge_live", None), "TRỰC TUYẾN: TẮT")
        except Exception:
            pass
        return None


    def _final_fix_set_running_controls(self_obj, running):
        try:
            getattr(self_obj, "btn_start", None).setEnabled(not running and bool(getattr(self_obj, "video_path", None)))
        except Exception:
            pass
        for attr in ("btn_pause", "btn_stop"):
            try:
                getattr(self_obj, attr, None).setEnabled(bool(running))
            except Exception:
                pass
        if running:
            _final_fix_set_text(getattr(self_obj, "btn_pause", None), "Tạm dừng")
            _final_fix_show_status(self_obj, "Đang phân tích video...")


    _final_fix_old_pause_resume = getattr(GiaoDienChinh, "on_pause_resume", None)
    _final_fix_old_stop = getattr(GiaoDienChinh, "on_stop", None)
    _final_fix_old_start = getattr(GiaoDienChinh, "on_start", None)

    GiaoDienChinh.on_pause_resume = _final_fix_pause_or_resume
    GiaoDienChinh.on_pause = _final_fix_pause_or_resume
    GiaoDienChinh.tam_dung = _final_fix_pause_or_resume
    GiaoDienChinh.xu_ly_tam_dung = _final_fix_pause_or_resume
    GiaoDienChinh.on_stop = _final_fix_stop_video
    GiaoDienChinh.dung_he_thong = _final_fix_stop_video
    GiaoDienChinh.xu_ly_dung = _final_fix_stop_video


    def _final_fix_on_start(self, *args, **kwargs):
        _final_fix_sync_vsl_config_from_ui(self)
        _final_fix_apply_worker_config(self)
        worker = getattr(self, "worker", None)
        try:
            if worker is not None and worker.isRunning():
                _final_fix_stop_video(self)
        except Exception:
            pass
        result = None
        try:
            result = _final_fix_call(_final_fix_old_start, self, *args, **kwargs)
        except Exception as exc:
            _final_fix_show_status(self, f"Lỗi khởi động video: {exc}")
            try:
                ghi_log(f"FINAL_FIX_ZOOM_VSL_CONTROL start loi: {exc}")
            except Exception:
                pass
            return None
        _final_fix_apply_worker_config(self)
        try:
            running = bool(getattr(self, "worker", None) is not None and self.worker.isRunning())
        except Exception:
            running = False
        _final_fix_set_running_controls(self, running)
        if running:
            _final_fix_show_status(self, "Đang phân tích video...")
        return result


    GiaoDienChinh.on_start = _final_fix_on_start
    for _final_fix_start_name in ("bat_dau_phan_tich", "xu_ly_bat_dau", "start_analysis"):
        if hasattr(GiaoDienChinh, _final_fix_start_name):
            setattr(GiaoDienChinh, _final_fix_start_name, _final_fix_on_start)


    def _final_fix_bind_controls(self):
        _final_fix_call(_final_fix_old_bind_controls, self)
        for attr, method_name in (
            ("btn_pause", "on_pause_resume"),
            ("btn_stop", "on_stop"),
        ):
            signal = None
            try:
                signal = getattr(getattr(self, attr, None), "clicked", None)
                if signal is not None:
                    signal.disconnect()
            except Exception:
                pass
            try:
                callback = getattr(self, method_name, None)
                if signal is not None and callable(callback):
                    signal.connect(callback)
            except Exception:
                pass


    _final_fix_old_bind_controls = getattr(GiaoDienChinh, "_gan_trang_thai_ban_dau", None)
    if _final_fix_old_bind_controls is not None:
        GiaoDienChinh._gan_trang_thai_ban_dau = _final_fix_bind_controls


    def _final_fix_wrap_vsl_context_method(method):
        if method is None:
            return None

        def wrapped(self, *args, **kwargs):
            result = _final_fix_call(method, self, *args, **kwargs)
            _final_fix_sync_vsl_config_from_ui(self)
            _final_fix_apply_worker_config(self)
            return result

        wrapped.__name__ = "_final_fix_wrapped_vsl_context"
        return wrapped


    for _final_fix_context_name in (
        "xu_ly_doi_thoi_tiet",
        "xu_ly_doi_su_co",
        "xu_ly_doi_che_do",
        "update_vsl_config",
        "cap_nhat_cau_hinh_vsl",
    ):
        _final_fix_context_old = getattr(GiaoDienChinh, _final_fix_context_name, None)
        if _final_fix_context_old is not None:
            setattr(GiaoDienChinh, _final_fix_context_name, _final_fix_wrap_vsl_context_method(_final_fix_context_old))


    def _final_fix_weather_cap(weather, vsl_max):
        try:
            return min(vsl_max, _final_hcm_weather_cap(weather, vsl_max))
        except Exception:
            text = str(weather or "").lower()
            for key, cap in (("mưa nhỏ", 90), ("mưa vừa", 80), ("mưa to", 70), ("sương mù mỏng", 80), ("sương mù vừa", 70), ("sương mù dày", 60)):
                if key in text:
                    return min(vsl_max, cap)
            return vsl_max


    def _final_fix_incident_cap(incident, vsl_max):
        try:
            return min(vsl_max, _final_hcm_incident_cap(incident, vsl_max))
        except Exception:
            text = str(incident or "").lower()
            if "nghiêm trọng" in text:
                return min(vsl_max, 40)
            if "nhẹ" in text:
                return min(vsl_max, 70)
            return vsl_max


    _final_fix_old_process = getattr(XuLyVideo, "xu_ly_khung_hinh", None)

    def _final_fix_process_hcm_visible(self, frame):
        try:
            frame_out = _final_fix_call(_final_fix_old_process, self, frame)
        except Exception as exc:
            frame_out = frame
            try:
                ghi_log(f"FINAL_FIX_ZOOM_VSL_CONTROL process cu loi: {exc}")
            except Exception:
                pass
        try:
            stats = dict(getattr(self, "last_stats", {}) or {})
        except Exception:
            stats = {}
        cfg = getattr(self, "config", None)
        vsl_cfg = getattr(cfg, "vsl", None)
        vsl_min = max(0, _final_fix_safe_int(getattr(vsl_cfg, "vsl_min", 40), 40))
        vsl_max = max(vsl_min, _final_fix_safe_int(getattr(vsl_cfg, "vsl_max", 100), 100))
        weather = getattr(vsl_cfg, "weather", "Trời quang")
        incident = getattr(vsl_cfg, "incident", "Không")
        control_mode = str(getattr(vsl_cfg, "control_mode", "Tự động") or "Tự động").strip().lower()

        has_hcm = stats.get("hcm_LOS") not in (None, "", "-") or stats.get("hcm_D_star") not in (None, "")
        if not has_hcm:
            try:
                vehicles = max(0, _final_fix_safe_int(stats.get("vehicles_in_roi", 0), 0))
            except Exception:
                vehicles = 0
            temp = max(vsl_min, min(vsl_max, vsl_max - vehicles * 5))
            temp = int(temp // 10 * 10)
            v_hcm = max(vsl_min, temp)
            stats["reason"] = "VSL tạm theo ROI, đang chờ đủ dữ liệu HCM"
        else:
            v_hcm = _final_fix_safe_int(stats.get("suggested_vsl", vsl_max), vsl_max)
        if control_mode in ("thủ công", "thu cong", "manual"):
            v_hcm = _final_fix_safe_int(getattr(vsl_cfg, "manual_vsl", v_hcm), v_hcm)

        speed = _final_fix_safe_float(
            stats.get("hcm_speed_S_kmh", stats.get("speed_avg_kmh", stats.get("toc_do_tb_kmh", 0.0))),
            0.0,
        )
        v_obs = min(vsl_max, speed + 10.0) if speed > 1.0 else vsl_max
        v_weather = _final_fix_weather_cap(weather, vsl_max)
        v_incident = _final_fix_incident_cap(incident, vsl_max)
        v_legal = vsl_max
        raw_vsl = min(vsl_max, v_hcm, v_obs, v_weather, v_incident, v_legal)
        candidate = max(vsl_min, min(vsl_max, int(raw_vsl) // 10 * 10))
        previous = getattr(self, "_final_fix_previous_vsl", None)
        if previous is None:
            final_vsl = candidate
        elif candidate < _final_fix_safe_int(previous, candidate):
            final_vsl = candidate
        else:
            final_vsl = min(candidate, _final_fix_safe_int(previous, candidate) + 10)
        final_vsl = max(vsl_min, min(vsl_max, int(final_vsl)))

        stats["suggested_vsl"] = final_vsl
        stats.setdefault("density", "ĐANG KHỞI TẠO")
        stats.setdefault("traffic_state", "Đang phân tích")
        stats.setdefault("reason", "Đang khởi tạo HCM/ROI, VSL sẽ cập nhật theo từng frame")
        try:
            d_star = _final_fix_safe_float(stats.get("hcm_D_star", 0.0), 0.0)
            stats["hcm_D_star"] = d_star
        except Exception:
            stats["hcm_D_star"] = 0.0
        if not stats.get("hcm_LOS") or stats.get("hcm_LOS") == "-":
            try:
                stats["hcm_LOS"] = _final_hcm_los(stats["hcm_D_star"])
            except Exception:
                stats["hcm_LOS"] = "-"
        if has_hcm and not str(stats.get("reason") or "").startswith("HCM LOS "):
            stats["reason"] = f"HCM LOS {stats.get('hcm_LOS', '-')} | D*={stats['hcm_D_star']:.1f} | {stats.get('reason', '')}".strip(" |")
        if vsl_min >= 70:
            min_reason = f"VSL bị chặn bởi tốc độ tối thiểu = {vsl_min} km/h"
            if min_reason not in str(stats.get("reason") or ""):
                stats["reason"] = f"{stats.get('reason', '')} | {min_reason}".strip(" |")
        if str(weather) not in ("", "Trời quang") and f"thời tiết={weather}" not in str(stats.get("reason") or ""):
            stats["reason"] = f"{stats.get('reason', '')} | thời tiết={weather}".strip(" |")
        if str(incident) not in ("", "Không") and f"sự cố={incident}" not in str(stats.get("reason") or ""):
            stats["reason"] = f"{stats.get('reason', '')} | sự cố={incident}".strip(" |")
        self._final_fix_previous_vsl = final_vsl
        self.last_stats = stats
        self.last_vsl = final_vsl
        try:
            self.statsReady.emit(stats)
        except Exception:
            pass

        try:
            if frame_out is not None and hasattr(frame_out, "shape") and len(frame_out.shape) >= 2:
                h, w = frame_out.shape[:2]
                los = str(stats.get("hcm_LOS", "-") or "-")
                line1 = f"VSL: {final_vsl} km/h | LOS {los} | D*={stats['hcm_D_star']:.1f}"
                line2 = "HCM/ROI realtime"
                font = cv2.FONT_HERSHEY_SIMPLEX
                scale = 0.50
                thickness = 1
                size1 = cv2.getTextSize(line1, font, scale, thickness)[0]
                size2 = cv2.getTextSize(line2, font, scale, thickness)[0]
                box_w = min(560, max(size1[0], size2[0]) + 18)
                box_h = min(58, max(42, h - 12))
                x0, y0 = 10, 10
                x1 = min(x0 + box_w, max(x0 + 1, w - 2))
                y1 = min(y0 + box_h, max(y0 + 1, h - 2))
                cv2.rectangle(frame_out, (x0, y0), (x1, y1), (0, 0, 0), -1)
                cv2.putText(frame_out, line1, (x0 + 8, min(y0 + 23, y1 - 20)), font, scale, (0, 255, 255), thickness, cv2.LINE_AA)
                cv2.putText(frame_out, line2, (x0 + 8, min(y0 + 45, y1 - 4)), font, scale, (220, 255, 220), thickness, cv2.LINE_AA)
        except Exception:
            pass
        return frame_out


    if _final_fix_old_process is not None:
        XuLyVideo.xu_ly_khung_hinh = _final_fix_process_hcm_visible
except Exception as _final_fix_zoom_vsl_control_exc:
    try:
        ghi_log(f"FINAL_FIX_ZOOM_VSL_CONTROL khong the nap patch: {_final_fix_zoom_vsl_control_exc}")
    except Exception:
        pass


try:
    _final_fix_old_update_ui = getattr(GiaoDienChinh, "update_ui_from_stats", None)

    def _final_fix_update_ui_from_stats(self, stats):
        try:
            _final_fix_call(_final_fix_old_update_ui, self, stats)
        except Exception as exc:
            try:
                ghi_log(f"FINAL_FIX_ZOOM_VSL_CONTROL update UI cu loi: {exc}")
            except Exception:
                pass
        try:
            data = dict(stats or {})
        except Exception:
            data = {}
        vsl_cfg = getattr(getattr(self, "config", None), "vsl", None)
        vsl_min = max(0, _final_fix_safe_int(getattr(vsl_cfg, "vsl_min", 40), 40))
        vsl_max = max(vsl_min, _final_fix_safe_int(getattr(vsl_cfg, "vsl_max", 100), 100))
        vsl = max(vsl_min, min(vsl_max, _final_fix_safe_int(data.get("suggested_vsl", vsl_max), vsl_max)))
        reason = str(data.get("reason") or "Đang khởi tạo HCM/ROI, VSL sẽ cập nhật theo từng frame")
        if vsl_min >= 70:
            min_reason = f"VSL bị chặn bởi tốc độ tối thiểu = {vsl_min} km/h"
            if min_reason not in reason:
                reason = f"{reason} | {min_reason}"
        density = str(data.get("density") or "ĐANG KHỞI TẠO")
        state = str(data.get("traffic_state") or "Đang phân tích")
        try:
            card = getattr(self, "card_vsl", None)
            if card is not None and hasattr(card, "dat_gia_tri"):
                card.dat_gia_tri(f"{vsl} km/h")
            if card is not None and hasattr(card, "dat_mo_ta"):
                card.dat_mo_ta(reason)
        except Exception:
            pass
        _final_fix_set_text(getattr(self, "hero_badge_vsl", None), f"BIỂN BÁO: {vsl} km/h")
        _final_fix_set_text(getattr(self, "lbl_vsl", None), f"Tốc độ đề xuất: {vsl} km/h")
        _final_fix_set_text(getattr(self, "lbl_density", None), f"Mật độ: {density}")
        _final_fix_set_text(getattr(self, "lbl_state", None), f"Trạng thái giao thông: {state}")
        _final_fix_set_text(getattr(self, "lbl_reason", None), f"Lý do: {reason}")
        try:
            card = getattr(self, "card_state", None)
            if card is not None and hasattr(card, "dat_gia_tri"):
                card.dat_gia_tri(state)
            if card is not None and hasattr(card, "dat_mo_ta"):
                card.dat_mo_ta(f"Mật độ: {density}")
        except Exception:
            pass
        try:
            card = getattr(self, "card_roi", None)
            if card is not None and hasattr(card, "dat_gia_tri"):
                card.dat_gia_tri(str(data.get("vehicles_in_roi", 0)))
            if card is not None and hasattr(card, "dat_mo_ta"):
                card.dat_mo_ta(f"Trung bình trong cửa sổ: {data.get('avg_vehicles', 0)}")
        except Exception:
            pass
        return None


    if _final_fix_old_update_ui is not None:
        GiaoDienChinh.update_ui_from_stats = _final_fix_update_ui_from_stats
except Exception as _final_fix_zoom_vsl_control_ui_exc:
    try:
        ghi_log(f"FINAL_FIX_ZOOM_VSL_CONTROL khong the nap UI patch: {_final_fix_zoom_vsl_control_ui_exc}")
    except Exception:
        pass


try:
    # FINAL_FULL_RUNTIME_FIX_PATCH: mo video an toan va dieu khien runtime cuoi file.
    def _final_full_runtime_fix_norm(value):
        try:
            value = os.fspath(value) if value is not None else ""
        except Exception:
            value = str(value or "")
        value = str(value).strip().strip('"')
        if not value:
            return ""
        try:
            return os.path.abspath(os.path.normpath(value))
        except Exception:
            return value


    def _final_full_runtime_fix_call(method, self, *args, **kwargs):
        if method is None:
            return None
        try:
            if getattr(method, "__self__", None) is not None:
                return method(*args, **kwargs)
        except Exception:
            pass
        return method(self, *args, **kwargs)


    def _final_full_runtime_fix_set_text(widget, value):
        try:
            if widget is not None and hasattr(widget, "setText"):
                widget.setText(str(value))
        except Exception:
            pass


    def _final_full_runtime_fix_try_open_video(path):
        path = _final_full_runtime_fix_norm(path)
        if not path:
            return False, {}, "Đường dẫn video rỗng"
        try:
            if not os.path.isfile(path):
                return False, {}, "File không tồn tại"
        except Exception as exc:
            return False, {}, f"Không kiểm tra được file: {exc}"
        backends = []
        for name in ("CAP_FFMPEG", "CAP_ANY"):
            backend = getattr(cv2, name, None)
            if backend is not None and backend not in backends:
                backends.append(backend)
        if not backends:
            backends = [None]
        error = "OpenCV không mở được video."
        for backend in backends:
            cap = None
            try:
                cap = cv2.VideoCapture(path) if backend is None else cv2.VideoCapture(path, backend)
                if cap is None or not cap.isOpened():
                    error = f"Backend {backend} không mở được video."
                    continue
                ok, frame = cap.read()
                if not ok or frame is None:
                    try:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    except Exception:
                        pass
                    ok, frame = cap.read()
                if ok and frame is not None:
                    h, w = frame.shape[:2]
                    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or w)
                    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or h)
                    fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
                    if fps <= 0:
                        fps = 25.0
                    count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                    try:
                        cap.release()
                    except Exception:
                        pass
                    return True, {"path": path, "width": width, "height": height, "fps": fps, "frame_count": count, "frame": frame}, ""
                error = "Video mở được nhưng không đọc được frame đầu tiên."
            except TypeError:
                try:
                    cap = cv2.VideoCapture(path)
                    ok, frame = cap.read() if cap is not None and cap.isOpened() else (False, None)
                    if ok and frame is not None:
                        h, w = frame.shape[:2]
                        fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
                        return True, {"path": path, "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or w), "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or h), "fps": max(25.0, fps), "frame_count": int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0), "frame": frame}, ""
                except Exception as exc:
                    error = f"Lỗi codec/backend: {exc}"
            except Exception as exc:
                error = f"Lỗi codec hoặc đường dẫn: {exc}"
            finally:
                try:
                    if cap is not None:
                        cap.release()
                except Exception:
                    pass
        try:
            raw = np.fromfile(path, dtype=np.uint8)
            if raw.size:
                error = "File tồn tại nhưng OpenCV không đọc được codec. Hãy chuyển sang MP4 H.264 hoặc đổi tên không dấu."
            else:
                error = "File rỗng hoặc không đọc được dữ liệu."
        except Exception as exc:
            error = f"Không đọc được file: {exc}"
        return False, {}, error


    def _final_full_runtime_fix_set_aliases(self, path):
        path = _final_full_runtime_fix_norm(path)
        if not path:
            return ""
        for name in ("video_path", "selected_video_path", "current_video_path", "duong_dan_video", "file_video", "video_file"):
            try:
                setattr(self, name, path)
            except Exception:
                pass
        return path


    def _final_full_runtime_fix_error(self, path, error):
        message = ("Không mở được video.\n"
                   f"Đường dẫn: {path or '(trống)'}\n"
                   f"Lý do: {error}\n"
                   "Gợi ý:\n"
                   "- Đổi tên file không dấu, không khoảng trắng, ví dụ video_1.mp4\n"
                   "- Đặt video cùng thư mục với file .py hoặc trong thư mục video/\n"
                   "- Chuyển video sang MP4 H.264")
        _final_full_runtime_fix_set_text(getattr(self, "lbl_status", None), "Không mở được video.")
        try:
            ghi_log(f"[VIDEO] Không mở được video: {path} | {error}")
        except Exception:
            pass
        try:
            QtWidgets.QMessageBox.warning(self, "Lỗi mở video", message)
        except Exception:
            pass


    def _final_full_runtime_fix_set_video_info(self, path, info):
        name = os.path.basename(path) or path
        fps = float(info.get("fps", 25.0) or 25.0)
        if fps <= 0:
            fps = 25.0
        video_text = f"Video: {name}"
        resolution_text = f"Resolution: {int(info.get('width', 0))} x {int(info.get('height', 0))} | FPS: {fps:.1f}"
        for attr in ("lbl_video_info", "label_video_info", "lbl_video_name", "video_info_label"):
            _final_full_runtime_fix_set_text(getattr(self, attr, None), video_text)
        for attr in ("lbl_resolution", "label_resolution", "lbl_video_res"):
            _final_full_runtime_fix_set_text(getattr(self, attr, None), resolution_text)
        _final_full_runtime_fix_set_text(getattr(self, "status_label", None), video_text)
        try:
            _final_full_runtime_fix_set_text(getattr(self, "video_label", None), "Đã chọn video. Bấm Bắt đầu phân tích.")
        except Exception:
            pass


    def _final_full_runtime_fix_preview(self, frame):
        try:
            convert = globals().get("chuyen_bgr_sang_qimage")
            show = getattr(self, "show_frame", None)
            if frame is not None and callable(convert) and callable(show):
                show(convert(frame))
        except Exception:
            pass


    def _final_full_runtime_fix_choose_video(self, *args, **kwargs):
        try:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Chọn video", "", "Video Files (*.mp4 *.avi *.mov *.mkv *.wmv *.m4v);;All Files (*.*)")
        except Exception as exc:
            _final_full_runtime_fix_error(self, "", f"Không mở được hộp thoại chọn file: {exc}")
            return None
        if not path:
            return None
        normalized = _final_full_runtime_fix_norm(path)
        ok, info, error = _final_full_runtime_fix_try_open_video(normalized)
        if not ok:
            _final_full_runtime_fix_error(self, normalized, error)
            return None
        _final_full_runtime_fix_set_aliases(self, normalized)
        try:
            self.che_do_chay = "SINGLE"
            self.camera_hien_tai = None
        except Exception:
            pass
        _final_full_runtime_fix_set_video_info(self, normalized, info)
        for attr in ("btn_start", "btn_bat_dau", "start_button"):
            try:
                widget = getattr(self, attr, None)
                if widget is not None:
                    widget.setEnabled(True)
            except Exception:
                pass
        _final_full_runtime_fix_preview(self, info.get("frame"))
        try:
            ghi_log(f"[VIDEO] Đã chọn video hợp lệ: {normalized}")
            if callable(getattr(self, "append_log", None)):
                self.append_log(f"[VIDEO] Đã chọn video hợp lệ: {normalized}")
        except Exception:
            pass
        return normalized


    _final_full_runtime_fix_old_open = getattr(GiaoDienChinh, "on_open_video", None)
    GiaoDienChinh.on_open_video = _final_full_runtime_fix_choose_video
    for _name in ("on_chon_video", "chon_video", "xu_ly_chon_video", "chon_file_video", "open_video_file", "browse_video", "select_video"):
        if hasattr(GiaoDienChinh, _name):
            setattr(GiaoDienChinh, _name, _final_full_runtime_fix_choose_video)
except Exception as _final_full_runtime_fix_open_exc:
    try:
        ghi_log(f"FINAL_FULL_RUNTIME_FIX open patch loi: {_final_full_runtime_fix_open_exc}")
    except Exception:
        pass


try:
    def _final_full_runtime_fix_sync_vsl_config_from_ui(self):
        try:
            vsl = getattr(getattr(self, "config", None), "vsl", None)
            if vsl is None:
                return None
            for widget_name, attr_name in (("sld_vmin", "vsl_min"), ("sld_vmax", "vsl_max"), ("sld_scale_max", "scale_max"), ("sld_smoothing", "smoothing_window"), ("sld_manual_vsl", "manual_vsl")):
                widget = getattr(self, widget_name, None)
                slider = getattr(widget, "slider", widget)
                getter = getattr(slider, "value", None)
                if callable(getter):
                    setattr(vsl, attr_name, int(getter()))
            for widget_name, attr_name in (("cbo_weather", "weather"), ("cbo_incident", "incident"), ("cbo_mode", "control_mode")):
                widget = getattr(self, widget_name, None)
                getter = getattr(widget, "currentText", None)
                if callable(getter):
                    value = str(getter())
                    if value:
                        setattr(vsl, attr_name, value)
            vsl.vsl_min = max(0, int(getattr(vsl, "vsl_min", 40)))
            vsl.vsl_max = max(vsl.vsl_min, int(getattr(vsl, "vsl_max", 100)))
            vsl.scale_max = max(1, int(getattr(vsl, "scale_max", 20)))
            vsl.smoothing_window = max(1, int(getattr(vsl, "smoothing_window", 30)))
            worker = getattr(self, "worker", None)
            if worker is not None:
                worker.config.vsl = vsl
            return vsl
        except Exception as exc:
            try:
                ghi_log(f"FINAL_FULL_RUNTIME_FIX sync VSL loi: {exc}")
            except Exception:
                pass
            return None


    def _final_full_runtime_fix_configure_runtime(self):
        try:
            detection = getattr(getattr(self, "config", None), "detection", None)
            if detection is None:
                return
            detection.imgsz = int(os.getenv("VSL_RUN_IMGSZ", "640"))
            detection.frame_stride = max(1, int(os.getenv("VSL_RUN_STRIDE", "3")))
            detection.conf_th = float(os.getenv("VSL_RUN_CONF", "0.30"))
            try:
                import torch
                if not torch.cuda.is_available():
                    detection.use_gpu = False
            except Exception:
                detection.use_gpu = False
            if not bool(getattr(detection, "use_gpu", False)):
                for attr in ("half", "use_half"):
                    if hasattr(detection, attr):
                        setattr(detection, attr, False)
        except Exception:
            pass


    def _final_full_runtime_fix_stop_old_worker(self):
        worker = getattr(self, "worker", None)
        if worker is None:
            return
        try:
            running = bool(worker.isRunning())
        except Exception:
            running = True
        if running:
            try:
                method = getattr(worker, "yeu_cau_dung", None)
                if callable(method):
                    method()
            except Exception:
                pass
            try:
                worker.stop_requested = True
            except Exception:
                pass
            try:
                method = getattr(worker, "dat_tam_dung", None)
                if callable(method):
                    method(False)
            except Exception:
                pass
            try:
                method = getattr(worker, "quit", None)
                if callable(method):
                    method()
            except Exception:
                pass
            try:
                method = getattr(worker, "wait", None)
                if callable(method):
                    method(2000)
            except Exception:
                pass
            try:
                if worker.isRunning() and hasattr(worker, "terminate"):
                    worker.terminate()
                    worker.wait(500)
            except Exception:
                pass
        try:
            self.worker = None
        except Exception:
            pass


    def _final_full_runtime_fix_connect_worker(self, worker):
        pairs = (
            ("frameReady", getattr(self, "show_frame", None)),
            ("statsReady", getattr(self, "update_ui_from_stats", None)),
            ("statusReady", getattr(self, "on_worker_status", None) or getattr(getattr(self, "lbl_status", None), "setText", None)),
            ("logReady", getattr(self, "append_log", None)),
            ("errorReady", getattr(self, "on_worker_error", None)),
            ("finishedCleanly", getattr(self, "on_worker_finished", None)),
        )
        for signal_name, callback in pairs:
            try:
                signal = getattr(worker, signal_name, None)
                if signal is not None and callable(callback):
                    signal.connect(callback)
            except Exception:
                pass


    _final_full_runtime_fix_old_start = getattr(GiaoDienChinh, "on_start", None)

    def _final_full_runtime_fix_on_start(self, *args, **kwargs):
        _final_full_runtime_fix_sync_vsl_config_from_ui(self)
        path = ""
        for attr in ("video_path", "selected_video_path", "current_video_path", "duong_dan_video", "file_video", "video_file"):
            candidate = _final_full_runtime_fix_norm(getattr(self, attr, ""))
            if candidate and (not path or os.path.isfile(candidate)):
                path = candidate
                if os.path.isfile(candidate):
                    break
        if not path:
            _final_full_runtime_fix_error(self, "", "Chưa chọn video.")
            return None
        ok, info, error = _final_full_runtime_fix_try_open_video(path)
        if not ok:
            _final_full_runtime_fix_error(self, path, error)
            return None
        _final_full_runtime_fix_set_aliases(self, path)
        _final_full_runtime_fix_stop_old_worker(self)
        _final_full_runtime_fix_configure_runtime(self)
        result = None
        try:
            result = _final_full_runtime_fix_call(_final_full_runtime_fix_old_start, self, *args, **kwargs)
        except Exception as exc:
            try:
                ghi_log(f"FINAL_FULL_RUNTIME_FIX start cu loi: {exc}")
            except Exception:
                pass
        worker = getattr(self, "worker", None)
        try:
            running = bool(worker is not None and worker.isRunning())
        except Exception:
            running = False
        if not running:
            try:
                worker = XuLyVideo(path, getattr(self, "config", None), getattr(self, "session_user", {}) or {}, camera_id="VIDEO_THU_CONG")
                self.worker = worker
                _final_full_runtime_fix_connect_worker(self, worker)
                worker.start()
            except Exception as exc:
                _final_full_runtime_fix_error(self, path, f"Không tạo được worker phân tích: {exc}")
                return None
        for attr in ("btn_start", "btn_bat_dau", "start_button"):
            try:
                widget = getattr(self, attr, None)
                if widget is not None:
                    widget.setEnabled(False)
            except Exception:
                pass
        for attr in ("btn_pause", "btn_tam_dung", "pause_button", "btn_stop", "btn_dung", "stop_button"):
            try:
                widget = getattr(self, attr, None)
                if widget is not None:
                    widget.setEnabled(True)
            except Exception:
                pass
        _final_full_runtime_fix_set_text(getattr(self, "btn_pause", None), "Tạm dừng")
        _final_full_runtime_fix_set_text(getattr(self, "lbl_status", None), "Đang phân tích video...")
        try:
            update = getattr(self, "update_ui_from_stats", None)
            if callable(update):
                update({"suggested_vsl": getattr(getattr(getattr(self, "config", None), "vsl", None), "vsl_max", 100), "density": "ĐANG KHỞI TẠO", "traffic_state": "Đang phân tích", "reason": "Đang khởi tạo video, VSL sẽ cập nhật theo HCM/ROI"})
        except Exception:
            pass
        return result


    GiaoDienChinh.on_start = _final_full_runtime_fix_on_start
    for _name in ("bat_dau_phan_tich", "xu_ly_bat_dau", "start_analysis", "start_video"):
        if hasattr(GiaoDienChinh, _name):
            setattr(GiaoDienChinh, _name, _final_full_runtime_fix_on_start)
except Exception as _final_full_runtime_fix_runtime_exc:
    try:
        ghi_log(f"FINAL_FULL_RUNTIME_FIX runtime patch loi: {_final_full_runtime_fix_runtime_exc}")
    except Exception:
        pass


try:
    _final_full_runtime_fix_old_show_frame = getattr(GiaoDienChinh, "show_frame", None)

    def _final_full_runtime_fix_show_frame(self, qimg):
        label = getattr(self, "video_label", None)
        if label is None or qimg is None:
            return None
        try:
            pix = QtGui.QPixmap.fromImage(qimg)
            if pix.isNull():
                return None
            label.setScaledContents(False)
            label.setAlignment(QtCore.Qt.AlignCenter)
            try:
                label.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
            except Exception:
                pass
            try:
                label.setStyleSheet((label.styleSheet() or "") + ";background:#081120;")
            except Exception:
                pass
            target_size = label.contentsRect().size()
            if target_size.width() <= 0 or target_size.height() <= 0:
                target_size = label.size()
            if target_size.width() <= 0 or target_size.height() <= 0:
                return None
            label.setPixmap(pix.scaled(target_size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
            label.show()
        except Exception:
            pass
        return None


    GiaoDienChinh.show_frame = _final_full_runtime_fix_show_frame


    def _final_full_runtime_fix_pause_or_resume(self):
        worker = getattr(self, "worker", None)
        try:
            if worker is None or not worker.isRunning():
                _final_full_runtime_fix_set_text(getattr(self, "lbl_status", None), "Chưa có video đang chạy")
                return None
        except Exception:
            _final_full_runtime_fix_set_text(getattr(self, "lbl_status", None), "Chưa có video đang chạy")
            return None
        paused = not bool(getattr(worker, "pause_requested", False))
        try:
            method = getattr(worker, "dat_tam_dung", None)
            if callable(method):
                method(paused)
            else:
                worker.pause_requested = paused
        except Exception:
            pass
        _final_full_runtime_fix_set_text(getattr(self, "btn_pause", None), "Tiếp tục" if paused else "Tạm dừng")
        _final_full_runtime_fix_set_text(getattr(self, "lbl_status", None), "Đã tạm dừng" if paused else "Đang phân tích video...")
        return paused


    def _final_full_runtime_fix_stop_video(self):
        worker = getattr(self, "worker", None)
        if worker is not None:
            try:
                method = getattr(worker, "yeu_cau_dung", None)
                if callable(method):
                    method()
            except Exception:
                pass
            try:
                worker.stop_requested = True
            except Exception:
                pass
            try:
                method = getattr(worker, "quit", None)
                if callable(method):
                    method()
            except Exception:
                pass
            try:
                method = getattr(worker, "wait", None)
                if callable(method):
                    method(2000)
            except Exception:
                pass
            try:
                if hasattr(worker, "isRunning") and worker.isRunning() and hasattr(worker, "terminate"):
                    worker.terminate()
                    worker.wait(500)
            except Exception:
                pass
            try:
                self.worker = None
            except Exception:
                pass
        for attr in ("btn_start", "btn_bat_dau", "start_button"):
            try:
                widget = getattr(self, attr, None)
                if widget is not None:
                    widget.setEnabled(bool(getattr(self, "video_path", None)))
            except Exception:
                pass
        for attr in ("btn_pause", "btn_tam_dung", "pause_button", "btn_stop", "btn_dung", "stop_button"):
            try:
                widget = getattr(self, attr, None)
                if widget is not None:
                    widget.setEnabled(False)
            except Exception:
                pass
        _final_full_runtime_fix_set_text(getattr(self, "btn_pause", None), "Tạm dừng")
        _final_full_runtime_fix_set_text(getattr(self, "lbl_status", None), "Đã dừng phân tích")
        return None


    GiaoDienChinh.on_pause_resume = _final_full_runtime_fix_pause_or_resume
    GiaoDienChinh.on_pause = _final_full_runtime_fix_pause_or_resume
    GiaoDienChinh.tam_dung = _final_full_runtime_fix_pause_or_resume
    GiaoDienChinh.on_stop = _final_full_runtime_fix_stop_video
    GiaoDienChinh.dung_he_thong = _final_full_runtime_fix_stop_video


    _final_full_runtime_fix_old_bind = getattr(GiaoDienChinh, "_gan_trang_thai_ban_dau", None)

    def _final_full_runtime_fix_bind_controls(self):
        _final_full_runtime_fix_call(_final_full_runtime_fix_old_bind, self)
        for button_name, method_name in (("btn_pause", "on_pause_resume"), ("btn_tam_dung", "on_pause_resume"), ("pause_button", "on_pause_resume"), ("btn_stop", "on_stop"), ("btn_dung", "on_stop"), ("stop_button", "on_stop")):
            signal = None
            try:
                signal = getattr(getattr(self, button_name, None), "clicked", None)
                if signal is not None:
                    signal.disconnect()
            except Exception:
                pass
            try:
                callback = getattr(self, method_name, None)
                if signal is not None and callable(callback):
                    signal.connect(callback)
            except Exception:
                pass


    if _final_full_runtime_fix_old_bind is not None:
        GiaoDienChinh._gan_trang_thai_ban_dau = _final_full_runtime_fix_bind_controls
except Exception as _final_full_runtime_fix_control_exc:
    try:
        ghi_log(f"FINAL_FULL_RUNTIME_FIX control patch loi: {_final_full_runtime_fix_control_exc}")
    except Exception:
        pass


try:
    _final_full_runtime_fix_old_process = getattr(XuLyVideo, "xu_ly_khung_hinh", None)

    def _final_full_runtime_fix_process(self, frame):
        try:
            frame_out = _final_full_runtime_fix_call(_final_full_runtime_fix_old_process, self, frame)
        except Exception:
            frame_out = frame
        try:
            stats = dict(getattr(self, "last_stats", {}) or {})
        except Exception:
            stats = {}
        vsl_cfg = getattr(getattr(self, "config", None), "vsl", None)
        vsl_min = max(0, int(float(getattr(vsl_cfg, "vsl_min", 40) or 40)))
        vsl_max = max(vsl_min, int(float(getattr(vsl_cfg, "vsl_max", 100) or 100)))
        weather = str(getattr(vsl_cfg, "weather", "Trời quang") or "Trời quang")
        incident = str(getattr(vsl_cfg, "incident", "Không") or "Không")
        try:
            raw = stats.get("suggested_vsl")
            has_vsl = raw is not None and str(raw).strip() != ""
            v_hcm = int(float(raw))
        except Exception:
            has_vsl = False
            v_hcm = vsl_max
        if not has_vsl:
            vehicles = max(0, int(float(stats.get("vehicles_in_roi", 0) or 0)))
            v_hcm = int(max(vsl_min, min(vsl_max, vsl_max - vehicles * 5)) // 10 * 10)
            stats["reason"] = "VSL tạm theo ROI, đang chờ đủ dữ liệu HCM"
        try:
            v_weather = min(vsl_max, _final_hcm_weather_cap(weather, vsl_max))
        except Exception:
            v_weather = vsl_max
        try:
            v_incident = min(vsl_max, _final_hcm_incident_cap(incident, vsl_max))
        except Exception:
            lower = incident.lower()
            v_incident = 40 if "nghiêm trọng" in lower else 70 if "nhẹ" in lower else vsl_max
        final_vsl = int(max(vsl_min, min(vsl_max, v_hcm, v_weather, v_incident)) // 10 * 10)
        old_vsl = getattr(self, "last_vsl", None)
        if old_vsl is not None and final_vsl > int(old_vsl):
            final_vsl = min(final_vsl, int(old_vsl) + 10)
        final_vsl = max(vsl_min, min(vsl_max, final_vsl))
        stats["suggested_vsl"] = int(final_vsl)
        stats.setdefault("density", "ĐANG KHỞI TẠO")
        stats.setdefault("traffic_state", "Đang phân tích")
        stats.setdefault("reason", "Đang khởi tạo video, VSL sẽ cập nhật theo HCM/ROI")
        stats.setdefault("hcm_D_star", 0.0)
        stats.setdefault("hcm_LOS", "-")
        if vsl_min >= 70:
            reason = str(stats.get("reason") or "")
            minimum = f"VSL bị chặn bởi tốc độ tối thiểu = {vsl_min} km/h"
            if minimum not in reason:
                stats["reason"] = f"{reason} | {minimum}".strip(" |")
        self.last_stats = stats
        self.last_vsl = int(final_vsl)
        try:
            self.statsReady.emit(stats)
        except Exception:
            pass
        try:
            h, w = frame_out.shape[:2]
            los = str(stats.get("hcm_LOS", "-") or "-")
            dstar = float(stats.get("hcm_D_star", 0.0) or 0.0)
            line1 = f"VSL: {final_vsl} km/h | LOS {los} | D*={dstar:.1f}"
            line2 = "HCM/ROI realtime"
            font = cv2.FONT_HERSHEY_SIMPLEX
            scale = 0.50
            thickness = 1
            s1 = cv2.getTextSize(line1, font, scale, thickness)[0]
            s2 = cv2.getTextSize(line2, font, scale, thickness)[0]
            box_w = min(560, max(s1[0], s2[0]) + 18)
            box_h = min(58, max(42, h - 12))
            x0, y0 = 10, 10
            x1 = min(x0 + box_w, max(x0 + 1, w - 2))
            y1 = min(y0 + box_h, max(y0 + 1, h - 2))
            cv2.rectangle(frame_out, (x0, y0), (x1, y1), (0, 0, 0), -1)
            cv2.putText(frame_out, line1, (x0 + 8, min(y0 + 23, y1 - 20)), font, scale, (0, 255, 255), thickness, cv2.LINE_AA)
            cv2.putText(frame_out, line2, (x0 + 8, min(y0 + 45, y1 - 4)), font, scale, (220, 255, 220), thickness, cv2.LINE_AA)
        except Exception:
            pass
        return frame_out


    if _final_full_runtime_fix_old_process is not None:
        XuLyVideo.xu_ly_khung_hinh = _final_full_runtime_fix_process
except Exception as _final_full_runtime_fix_process_exc:
    try:
        ghi_log(f"FINAL_FULL_RUNTIME_FIX process patch loi: {_final_full_runtime_fix_process_exc}")
    except Exception:
        pass


try:
    _final_full_runtime_fix_old_update_ui = getattr(GiaoDienChinh, "update_ui_from_stats", None)

    def _final_full_runtime_fix_update_ui_from_stats(self, stats):
        try:
            _final_full_runtime_fix_call(_final_full_runtime_fix_old_update_ui, self, stats)
        except Exception:
            pass
        try:
            data = dict(stats or {})
        except Exception:
            data = {}
        cfg = getattr(getattr(self, "config", None), "vsl", None)
        vsl_min = max(0, int(float(getattr(cfg, "vsl_min", 40) or 40)))
        vsl_max = max(vsl_min, int(float(getattr(cfg, "vsl_max", 100) or 100)))
        try:
            vsl = int(float(data.get("suggested_vsl", vsl_max)))
        except Exception:
            vsl = vsl_max
        vsl = max(vsl_min, min(vsl_max, vsl))
        reason = str(data.get("reason") or "Đang khởi tạo video, VSL sẽ cập nhật theo HCM/ROI")
        if vsl_min >= 70:
            minimum = f"VSL bị chặn bởi tốc độ tối thiểu = {vsl_min} km/h"
            if minimum not in reason:
                reason = f"{reason} | {minimum}"
        density = str(data.get("density") or "ĐANG KHỞI TẠO")
        state = str(data.get("traffic_state") or "Đang phân tích")
        try:
            card = getattr(self, "card_vsl", None)
            if card is not None and hasattr(card, "dat_gia_tri"):
                card.dat_gia_tri(f"{vsl} km/h")
            if card is not None and hasattr(card, "dat_mo_ta"):
                card.dat_mo_ta(reason)
        except Exception:
            pass
        _final_full_runtime_fix_set_text(getattr(self, "hero_badge_vsl", None), f"BIỂN BÁO: {vsl} km/h")
        _final_full_runtime_fix_set_text(getattr(self, "lbl_vsl", None), f"Tốc độ đề xuất: {vsl} km/h")
        _final_full_runtime_fix_set_text(getattr(self, "lbl_density", None), f"Mật độ: {density}")
        _final_full_runtime_fix_set_text(getattr(self, "lbl_state", None), f"Trạng thái giao thông: {state}")
        _final_full_runtime_fix_set_text(getattr(self, "lbl_reason", None), f"Lý do: {reason}")
        try:
            card = getattr(self, "card_state", None)
            if card is not None and hasattr(card, "dat_gia_tri"):
                card.dat_gia_tri(state)
            if card is not None and hasattr(card, "dat_mo_ta"):
                card.dat_mo_ta(f"Mật độ: {density}")
        except Exception:
            pass
        return None


    if _final_full_runtime_fix_old_update_ui is not None:
        GiaoDienChinh.update_ui_from_stats = _final_full_runtime_fix_update_ui_from_stats
except Exception as _final_full_runtime_fix_ui_exc:
    try:
        ghi_log(f"FINAL_FULL_RUNTIME_FIX UI patch loi: {_final_full_runtime_fix_ui_exc}")
    except Exception:
        pass


try:
    # FINAL_ONE_RUNTIME_CLEAN_PATCH: mot lop runtime cuoi cung cho video, VSL va dieu khien.
    def _final_one_call(method, self, *args, **kwargs):
        if method is None:
            return None
        try:
            if getattr(method, "__self__", None) is not None:
                return method(*args, **kwargs)
        except Exception:
            pass
        return method(self, *args, **kwargs)


    def _final_one_int(value, default=0):
        try:
            return int(float(value))
        except Exception:
            return int(default)


    def _final_one_set_text(widget, value):
        try:
            if widget is not None and hasattr(widget, "setText"):
                widget.setText(str(value))
        except Exception:
            pass


    def _final_one_norm_path(value):
        try:
            value = os.fspath(value) if value is not None else ""
        except Exception:
            value = str(value or "")
        value = str(value).strip().strip('"')
        if not value:
            return ""
        try:
            return os.path.abspath(os.path.normpath(value))
        except Exception:
            return value


    def _final_one_try_open_video(path):
        path = _final_one_norm_path(path)
        if not path:
            return False, {}, None, "Đường dẫn video rỗng"
        try:
            if not os.path.isfile(path):
                return False, {}, None, "File không tồn tại"
        except Exception as exc:
            return False, {}, None, f"Không kiểm tra được file: {exc}"
        backends = []
        for name in ("CAP_FFMPEG", "CAP_ANY"):
            backend = getattr(cv2, name, None)
            if backend is not None and backend not in backends:
                backends.append(backend)
        if not backends:
            backends = [None]
        error = "OpenCV không đọc được codec hoặc đường dẫn"
        for backend in backends:
            cap = None
            try:
                cap = cv2.VideoCapture(path) if backend is None else cv2.VideoCapture(path, backend)
                if cap is None or not cap.isOpened():
                    continue
                ok, frame = cap.read()
                if not ok or frame is None:
                    try:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    except Exception:
                        pass
                    ok, frame = cap.read()
                if ok and frame is not None:
                    h, w = frame.shape[:2]
                    fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
                    if fps <= 0:
                        fps = 25.0
                    info = {
                        "path": path,
                        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or w),
                        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or h),
                        "fps": fps,
                        "frame_count": int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0),
                    }
                    try:
                        cap.release()
                    except Exception:
                        pass
                    return True, info, frame, ""
                error = "Video mở được nhưng không đọc được frame đầu tiên"
            except Exception as exc:
                error = f"Lỗi codec hoặc đường dẫn: {exc}"
            finally:
                try:
                    if cap is not None:
                        cap.release()
                except Exception:
                    pass
        try:
            raw = np.fromfile(path, dtype=np.uint8)
            if raw.size:
                error = "OpenCV không đọc được codec. Hãy đổi tên không dấu hoặc chuyển sang MP4 H.264"
        except Exception as exc:
            error = f"Không đọc được file: {exc}"
        return False, {}, None, error


    def _final_one_stop_worker(self):
        worker = getattr(self, "worker", None)
        if worker is None:
            return
        try:
            if worker.isRunning():
                method = getattr(worker, "yeu_cau_dung", None)
                if callable(method):
                    method()
                worker.stop_requested = True
                method = getattr(worker, "dat_tam_dung", None)
                if callable(method):
                    method(False)
                method = getattr(worker, "quit", None)
                if callable(method):
                    method()
                method = getattr(worker, "wait", None)
                if callable(method):
                    method(2000)
                if worker.isRunning() and hasattr(worker, "terminate"):
                    worker.terminate()
                    worker.wait(500)
        except Exception:
            pass
        try:
            self.worker = None
        except Exception:
            pass


    def _final_one_reset_runtime_for_new_video(self):
        _final_one_stop_worker(self)
        try:
            multi = getattr(self, "multi_worker", None)
            if multi is not None and hasattr(multi, "dung"):
                multi.dung()
            self.multi_worker = None
        except Exception:
            pass
        for attr, value in (("current_stats", {}), ("last_stats", {}), ("last_vsl", None), ("video_loaded", False)):
            try:
                setattr(self, attr, value)
            except Exception:
                pass
        try:
            self.video_path = None
        except Exception:
            pass
        try:
            vsl_max = _final_one_int(getattr(getattr(getattr(self, "config", None), "vsl", None), "vsl_max", 100), 100)
        except Exception:
            vsl_max = 100
        _final_one_set_text(getattr(self, "hero_badge_vsl", None), f"BIỂN BÁO: {vsl_max} km/h")
        _final_one_set_text(getattr(self, "lbl_vsl", None), f"Tốc độ đề xuất: {vsl_max} km/h")
        _final_one_set_text(getattr(self, "lbl_density", None), "Mật độ: -")
        _final_one_set_text(getattr(self, "lbl_state", None), "Trạng thái giao thông: Đang chờ")
        _final_one_set_text(getattr(self, "lbl_reason", None), "Đã đổi video, chờ bắt đầu phân tích")
        try:
            card = getattr(self, "card_vsl", None)
            if card is not None:
                card.dat_gia_tri(f"{vsl_max} km/h")
                card.dat_mo_ta("Đã đổi video, chờ bắt đầu phân tích")
        except Exception:
            pass
        try:
            card = getattr(self, "card_roi", None)
            if card is not None:
                card.dat_gia_tri("0")
        except Exception:
            pass
        try:
            card = getattr(self, "card_state", None)
            if card is not None:
                card.dat_gia_tri("Đang chờ")
        except Exception:
            pass
        _final_one_set_text(getattr(self, "btn_pause", None), "Tạm dừng")
        try:
            label = getattr(self, "video_label", None)
            if label is not None:
                label.clear()
                label.setText("Chưa chọn video")
        except Exception:
            pass


    def _final_one_open_video(self, *args, **kwargs):
        try:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Chọn video", "", "Video Files (*.mp4 *.avi *.mov *.mkv *.wmv *.m4v);;All Files (*.*)")
        except Exception as exc:
            try:
                QtWidgets.QMessageBox.warning(self, "Lỗi mở video", str(exc))
            except Exception:
                pass
            return None
        if not path:
            return None
        _final_one_reset_runtime_for_new_video(self)
        path = _final_one_norm_path(path)
        ok, info, frame, error = _final_one_try_open_video(path)
        if not ok:
            try:
                QtWidgets.QMessageBox.warning(self, "Lỗi mở video", "Không mở được video. Hãy đổi tên file không dấu, không khoảng trắng hoặc chuyển sang MP4 H.264.\n" + str(error))
            except Exception:
                pass
            return None
        for attr in ("video_path", "selected_video_path", "current_video_path", "duong_dan_video", "file_video", "video_file"):
            try:
                setattr(self, attr, path)
            except Exception:
                pass
        _final_one_set_text(getattr(self, "lbl_video_name", None), f"Video: {os.path.basename(path)}")
        resolution = f"Resolution: {info['width']} x {info['height']} | FPS: {info['fps']:.1f}"
        for attr in ("lbl_video_info", "label_video_info", "video_info_label"):
            _final_one_set_text(getattr(self, attr, None), f"Video: {os.path.basename(path)}")
        for attr in ("lbl_resolution", "label_resolution", "lbl_video_res"):
            _final_one_set_text(getattr(self, attr, None), resolution)
        try:
            self.show_frame(chuyen_bgr_sang_qimage(frame))
        except Exception:
            pass
        try:
            self.video_loaded = True
        except Exception:
            pass
        _final_one_set_text(getattr(self, "lbl_status", None), "Sẵn sàng chạy.")
        for attr in ("btn_start", "btn_bat_dau", "start_button"):
            try:
                widget = getattr(self, attr, None)
                if widget is not None:
                    widget.setEnabled(True)
            except Exception:
                pass
        try:
            if callable(getattr(self, "append_log", None)):
                self.append_log(f"[VIDEO] Đã chọn video hợp lệ: {path}")
            ghi_log(f"[VIDEO] Đã chọn video hợp lệ: {path}")
        except Exception:
            pass
        return path


    _final_one_old_open_video = getattr(GiaoDienChinh, "on_open_video", None)
    _final_one_old_start = getattr(GiaoDienChinh, "on_start", None)
    GiaoDienChinh.on_open_video = _final_one_open_video
    for _name in ("on_chon_video", "chon_video", "xu_ly_chon_video", "chon_file_video", "open_video_file", "browse_video", "select_video"):
        if hasattr(GiaoDienChinh, _name):
            setattr(GiaoDienChinh, _name, _final_one_open_video)
except Exception as _final_one_open_exc:
    try:
        ghi_log(f"FINAL_ONE_RUNTIME_CLEAN open loi: {_final_one_open_exc}")
    except Exception:
        pass


try:
    def _final_one_sync_config_from_ui(self):
        try:
            vsl = getattr(getattr(self, "config", None), "vsl", None)
            if vsl is None:
                return None
            for widget_name, attr_name in (("sld_vmin", "vsl_min"), ("sld_vmax", "vsl_max"), ("sld_scale_max", "scale_max"), ("sld_smoothing", "smoothing_window"), ("sld_manual_vsl", "manual_vsl")):
                widget = getattr(self, widget_name, None)
                slider = getattr(widget, "slider", widget)
                getter = getattr(slider, "value", None)
                if callable(getter):
                    setattr(vsl, attr_name, int(getter()))
            for widget_name, attr_name in (("cbo_weather", "weather"), ("cbo_incident", "incident"), ("cbo_mode", "control_mode")):
                widget = getattr(self, widget_name, None)
                getter = getattr(widget, "currentText", None)
                if callable(getter):
                    value = str(getter())
                    if value:
                        setattr(vsl, attr_name, value)
            vsl.vsl_min = max(0, _final_one_int(getattr(vsl, "vsl_min", 40), 40))
            vsl.vsl_max = max(vsl.vsl_min, _final_one_int(getattr(vsl, "vsl_max", 100), 100))
            vsl.scale_max = max(1, _final_one_int(getattr(vsl, "scale_max", 20), 20))
            vsl.smoothing_window = max(1, _final_one_int(getattr(vsl, "smoothing_window", 30), 30))
            if getattr(self, "worker", None) is not None:
                self.worker.config.vsl = vsl
            return vsl
        except Exception:
            return None


    def _final_one_configure_runtime(self):
        try:
            detection = getattr(getattr(self, "config", None), "detection", None)
            if detection is None:
                return
            detection.imgsz = int(os.getenv("VSL_RUN_IMGSZ", "640"))
            detection.frame_stride = max(1, int(os.getenv("VSL_RUN_STRIDE", "3")))
            detection.conf_th = float(os.getenv("VSL_RUN_CONF", "0.30"))
            try:
                import torch
                if not torch.cuda.is_available():
                    detection.use_gpu = False
            except Exception:
                detection.use_gpu = False
            if not bool(getattr(detection, "use_gpu", False)):
                for attr in ("half", "use_half"):
                    if hasattr(detection, attr):
                        setattr(detection, attr, False)
        except Exception:
            pass


    def _final_one_connect_worker(self, worker):
        for signal_name, callback in (("frameReady", getattr(self, "show_frame", None)), ("statsReady", getattr(self, "update_ui_from_stats", None)), ("statusReady", getattr(self, "on_worker_status", None) or getattr(getattr(self, "lbl_status", None), "setText", None)), ("logReady", getattr(self, "append_log", None)), ("errorReady", getattr(self, "on_worker_error", None)), ("finishedCleanly", getattr(self, "on_worker_finished", None))):
            try:
                signal = getattr(worker, signal_name, None)
                if signal is not None and callable(callback):
                    signal.connect(callback)
            except Exception:
                pass


    def _final_one_on_start(self, *args, **kwargs):
        _final_one_sync_config_from_ui(self)
        path = ""
        for attr in ("video_path", "selected_video_path", "current_video_path", "duong_dan_video", "file_video", "video_file"):
            candidate = _final_one_norm_path(getattr(self, attr, ""))
            if candidate and not path:
                path = candidate
            try:
                if candidate and os.path.isfile(candidate):
                    path = candidate
                    break
            except Exception:
                pass
        if not path:
            _final_one_set_text(getattr(self, "lbl_status", None), "Chưa chọn video.")
            return None
        ok, info, frame, error = _final_one_try_open_video(path)
        if not ok:
            try:
                QtWidgets.QMessageBox.warning(self, "Lỗi mở video", f"Không mở được video.\n{error}")
            except Exception:
                pass
            return None
        for alias in ("video_path", "selected_video_path", "current_video_path", "duong_dan_video", "file_video", "video_file"):
            try:
                setattr(self, alias, path)
            except Exception:
                pass
        _final_one_stop_worker(self)
        _final_one_configure_runtime(self)
        result = None
        try:
            result = _final_one_call(_final_one_old_start, self, *args, **kwargs)
        except Exception as exc:
            try:
                ghi_log(f"FINAL_ONE_RUNTIME_CLEAN start cu loi: {exc}")
            except Exception:
                pass
        worker = getattr(self, "worker", None)
        try:
            running = bool(worker is not None and worker.isRunning())
        except Exception:
            running = False
        if not running:
            try:
                worker = XuLyVideo(path, getattr(self, "config", None), getattr(self, "session_user", {}) or {}, camera_id="VIDEO_THU_CONG")
                self.worker = worker
                _final_one_connect_worker(self, worker)
                worker.start()
            except Exception as exc:
                try:
                    ghi_log(f"FINAL_ONE_RUNTIME_CLEAN worker loi: {exc}")
                except Exception:
                    pass
                return None
        for attr in ("btn_start", "btn_bat_dau", "start_button"):
            try:
                widget = getattr(self, attr, None)
                if widget is not None:
                    widget.setEnabled(False)
            except Exception:
                pass
        for attr in ("btn_pause", "btn_tam_dung", "pause_button", "btn_stop", "btn_dung", "stop_button"):
            try:
                widget = getattr(self, attr, None)
                if widget is not None:
                    widget.setEnabled(True)
            except Exception:
                pass
        _final_one_set_text(getattr(self, "btn_pause", None), "Tạm dừng")
        _final_one_set_text(getattr(self, "lbl_status", None), "Đang phân tích video...")
        try:
            update = getattr(self, "update_ui_from_stats", None)
            if callable(update):
                update({"suggested_vsl": getattr(getattr(getattr(self, "config", None), "vsl", None), "vsl_max", 100), "density": "ĐANG KHỞI TẠO", "traffic_state": "Đang phân tích", "reason": "Đang khởi tạo HCM/ROI, VSL sẽ cập nhật từ frame đầu"})
        except Exception:
            pass
        return result


    def _final_one_show_frame(self, qimg):
        label = getattr(self, "video_label", None)
        if label is None or qimg is None:
            return None
        try:
            if qimg.isNull():
                return None
            frame_w, frame_h = qimg.width(), qimg.height()
            if frame_w <= 0 or frame_h <= 0:
                return None
            available_w = label.contentsRect().width()
            available_h = label.contentsRect().height()
            if available_w <= 0 or available_h <= 0:
                available_w, available_h = label.width(), label.height()
            if available_w <= 0 or available_h <= 0:
                return None
            scale = min(float(available_w) / frame_w, float(available_h) / frame_h)
            new_w = max(1, int(frame_w * scale))
            new_h = max(1, int(frame_h * scale))
            pix = QtGui.QPixmap.fromImage(qimg)
            pix = pix.scaled(new_w, new_h, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
            label.setPixmap(pix)
            label.setAlignment(QtCore.Qt.AlignCenter)
            label.setScaledContents(False)
            label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
            label.setStyleSheet((label.styleSheet() or "") + ";background:#0b1220;")
        except Exception:
            pass
        return None


    def _final_one_pause_resume(self):
        worker = getattr(self, "worker", None)
        try:
            if worker is None or not worker.isRunning():
                _final_one_set_text(getattr(self, "lbl_status", None), "Chưa có video đang chạy")
                return None
        except Exception:
            _final_one_set_text(getattr(self, "lbl_status", None), "Chưa có video đang chạy")
            return None
        paused = not bool(getattr(worker, "pause_requested", False))
        try:
            method = getattr(worker, "dat_tam_dung", None)
            if callable(method):
                method(paused)
            else:
                worker.pause_requested = paused
        except Exception:
            pass
        _final_one_set_text(getattr(self, "btn_pause", None), "Tiếp tục" if paused else "Tạm dừng")
        _final_one_set_text(getattr(self, "lbl_status", None), "Đã tạm dừng" if paused else "Đang phân tích video...")
        return paused


    def _final_one_stop(self):
        _final_one_stop_worker(self)
        for attr in ("btn_start", "btn_bat_dau", "start_button"):
            try:
                widget = getattr(self, attr, None)
                if widget is not None:
                    widget.setEnabled(bool(getattr(self, "video_path", None)))
            except Exception:
                pass
        for attr in ("btn_pause", "btn_tam_dung", "pause_button", "btn_stop", "btn_dung", "stop_button"):
            try:
                widget = getattr(self, attr, None)
                if widget is not None:
                    widget.setEnabled(False)
            except Exception:
                pass
        _final_one_set_text(getattr(self, "btn_pause", None), "Tạm dừng")
        _final_one_set_text(getattr(self, "lbl_status", None), "Đã dừng phân tích")
        return None


    _final_one_old_bind = getattr(GiaoDienChinh, "_gan_trang_thai_ban_dau", None)
    GiaoDienChinh.on_start = _final_one_on_start
    GiaoDienChinh.show_frame = _final_one_show_frame
    GiaoDienChinh.on_pause_resume = _final_one_pause_resume
    GiaoDienChinh.on_pause = _final_one_pause_resume
    GiaoDienChinh.tam_dung = _final_one_pause_resume
    GiaoDienChinh.on_stop = _final_one_stop
    GiaoDienChinh.dung_he_thong = _final_one_stop
    for _name in ("bat_dau_phan_tich", "xu_ly_bat_dau", "start_analysis", "start_video"):
        if hasattr(GiaoDienChinh, _name):
            setattr(GiaoDienChinh, _name, _final_one_on_start)


    def _final_one_bind_buttons(self):
        _final_one_call(_final_one_old_bind, self)
        for button_name, method_name in (("btn_pause", "on_pause_resume"), ("btn_tam_dung", "on_pause_resume"), ("pause_button", "on_pause_resume"), ("btn_stop", "on_stop"), ("btn_dung", "on_stop"), ("stop_button", "on_stop")):
            signal = None
            try:
                signal = getattr(getattr(self, button_name, None), "clicked", None)
                if signal is not None:
                    signal.disconnect()
            except Exception:
                pass
            try:
                callback = getattr(self, method_name, None)
                if signal is not None and callable(callback):
                    signal.connect(callback)
            except Exception:
                pass


    if _final_one_old_bind is not None:
        GiaoDienChinh._gan_trang_thai_ban_dau = _final_one_bind_buttons
except Exception as _final_one_runtime_exc:
    try:
        ghi_log(f"FINAL_ONE_RUNTIME_CLEAN runtime loi: {_final_one_runtime_exc}")
    except Exception:
        pass


try:
    _final_one_old_process_frame = getattr(XuLyVideo, "xu_ly_khung_hinh", None)

    def _final_one_process_frame(self, frame):
        try:
            frame_out = _final_one_call(_final_one_old_process_frame, self, frame)
        except Exception:
            frame_out = frame
        try:
            stats = dict(getattr(self, "last_stats", {}) or {})
        except Exception:
            stats = {}
        cfg = getattr(getattr(self, "config", None), "vsl", None)
        lane_cfg = getattr(getattr(self, "config", None), "lane", None)
        vsl_min = max(0, _final_one_int(getattr(cfg, "vsl_min", 40), 40))
        vsl_max = max(vsl_min, _final_one_int(getattr(cfg, "vsl_max", 100), 100))
        weather = str(getattr(cfg, "weather", "Trời quang") or "Trời quang")
        incident = str(getattr(cfg, "incident", "Không") or "Không")
        counts = stats.get("class_counts") if isinstance(stats.get("class_counts"), dict) else {}
        pcu = (float(counts.get("car", 0) or 0) * 1.0 + float(counts.get("motorcycle", 0) or 0) * 0.3 + float(counts.get("bicycle", 0) or 0) * 0.2 + float(counts.get("truck", 0) or 0) * 2.0 + float(counts.get("bus", 0) or 0) * 2.5)
        vehicles = max(0, _final_one_int(stats.get("vehicles_in_roi", sum(counts.values()) or 0), 0))
        lanes = max(1, _final_one_int(getattr(lane_cfg, "lane_count", 1), 1))
        roi_length = float(os.getenv("VSL_HCM_ROI_LENGTH_M", "500")) / 1000.0
        d_roi = pcu / max(0.05, roi_length * lanes)
        d_flow = float(stats.get("hcm_D_flow", 0.0) or 0.0)
        d_star = max(d_flow, d_roi)
        if d_star <= 7:
            los, v_hcm = "A", vsl_max
        elif d_star <= 11:
            los, v_hcm = "B", vsl_max
        elif d_star <= 16:
            los, v_hcm = "C", max(vsl_min, vsl_max - 10)
        elif d_star <= 22:
            los, v_hcm = "D", max(vsl_min, vsl_max - 20)
        elif d_star <= 28:
            los, v_hcm = "E", max(vsl_min, vsl_max - 30)
        else:
            los, v_hcm = "F", vsl_min
        old_hcm = stats.get("hcm_V_HCM", stats.get("V_HCM"))
        if old_hcm is not None:
            v_hcm = _final_one_int(old_hcm, v_hcm)
        elif stats.get("hcm_D_star") not in (None, "") and stats.get("suggested_vsl") not in (None, ""):
            v_hcm = _final_one_int(stats.get("suggested_vsl"), v_hcm)
        try:
            v_weather = min(vsl_max, _final_hcm_weather_cap(weather, vsl_max))
        except Exception:
            lower_weather = weather.lower()
            v_weather = 90 if "mưa nhỏ" in lower_weather else 80 if "mưa vừa" in lower_weather or lower_weather == "mưa" else 70 if "mưa to" in lower_weather or "sương mù vừa" in lower_weather else 60 if "sương mù dày" in lower_weather else vsl_max
        try:
            v_incident = min(vsl_max, _final_hcm_incident_cap(incident, vsl_max))
        except Exception:
            lower_incident = incident.lower()
            v_incident = 40 if "nghiêm trọng" in lower_incident else 70 if "nhẹ" in lower_incident else vsl_max
        speed = 0.0
        for key in ("toc_do_tb_kmh", "speed_avg_kmh"):
            if _final_one_int(stats.get(key, 0), 0) > 0:
                speed = float(stats.get(key))
                break
        v_obs = min(vsl_max, speed + 10.0) if speed > 0 else vsl_max
        raw_vsl = max(vsl_min, min(vsl_max, v_hcm, v_weather, v_incident, v_obs))
        final_vsl = int(raw_vsl // 10 * 10)
        old = getattr(self, "last_vsl", None)
        if old is not None and final_vsl > _final_one_int(old, final_vsl):
            final_vsl = min(final_vsl, _final_one_int(old, final_vsl) + 10)
        final_vsl = max(vsl_min, min(vsl_max, final_vsl))
        density = "THẤP" if los in ("A", "B") else "TRUNG BÌNH" if los in ("C", "D") else "CAO"
        traffic = "Lưu thông tốt" if los in ("A", "B") else "Lưu thông ổn định" if los in ("C", "D") else "Mật độ cao" if los == "E" else "Nguy cơ ùn tắc"
        stats.update({"suggested_vsl": int(final_vsl), "vehicles_in_roi": vehicles, "hcm_D_roi": round(d_roi, 2), "hcm_D_flow": round(d_flow, 2), "hcm_D_star": round(d_star, 2), "hcm_LOS": los, "density": density, "traffic_state": traffic})
        reason = f"HCM LOS {los} | D*={d_star:.2f} | D_roi={d_roi:.2f} | min(HCM={int(v_hcm)}, OBS={int(v_obs)}, WEATHER={int(v_weather)}, INCIDENT={int(v_incident)})"
        if vsl_min >= 70:
            reason += f" | VSL bị chặn bởi tốc độ tối thiểu = {vsl_min} km/h"
        stats["reason"] = reason
        self.last_stats = stats
        self.last_vsl = int(final_vsl)
        try:
            self.statsReady.emit(stats)
        except Exception:
            pass
        try:
            h, w = frame_out.shape[:2]
            line1 = f"VSL: {final_vsl} km/h | LOS {los} | D*={d_star:.1f}"
            line2 = "HCM/ROI realtime"
            font = cv2.FONT_HERSHEY_SIMPLEX
            scale = 0.50
            thickness = 1
            s1 = cv2.getTextSize(line1, font, scale, thickness)[0]
            s2 = cv2.getTextSize(line2, font, scale, thickness)[0]
            box_w = min(520, max(s1[0], s2[0]) + 18)
            box_h = min(58, max(42, h - 12))
            x0, y0 = 10, 10
            x1 = min(x0 + box_w, max(x0 + 1, w - 2))
            y1 = min(y0 + box_h, max(y0 + 1, h - 2))
            cv2.rectangle(frame_out, (x0, y0), (x1, y1), (0, 0, 0), -1)
            cv2.putText(frame_out, line1, (x0 + 8, min(y0 + 23, y1 - 20)), font, scale, (0, 255, 255), thickness, cv2.LINE_AA)
            cv2.putText(frame_out, line2, (x0 + 8, min(y0 + 45, y1 - 4)), font, scale, (220, 255, 220), thickness, cv2.LINE_AA)
        except Exception:
            pass
        return frame_out


    XuLyVideo.xu_ly_khung_hinh = _final_one_process_frame


    def _final_one_push_stats_to_ui(self, stats):
        try:
            data = dict(stats or {})
        except Exception:
            data = {}
        vsl_cfg = getattr(getattr(self, "config", None), "vsl", None)
        vsl_min = _final_one_int(getattr(vsl_cfg, "vsl_min", 40), 40)
        vsl_max = max(vsl_min, _final_one_int(getattr(vsl_cfg, "vsl_max", 100), 100))
        vsl = max(vsl_min, min(vsl_max, _final_one_int(data.get("suggested_vsl", vsl_max), vsl_max)))
        reason = str(data.get("reason", "") or "")
        if vsl_min >= 70 and f"{vsl_min} km/h" not in reason:
            reason = f"{reason} | VSL bị chặn bởi tốc độ tối thiểu = {vsl_min} km/h".strip(" |")
        _final_one_set_text(getattr(self, "hero_badge_vsl", None), f"BIỂN BÁO: {vsl} km/h")
        _final_one_set_text(getattr(self, "lbl_vsl", None), f"Tốc độ đề xuất: {vsl} km/h")
        _final_one_set_text(getattr(self, "lbl_density", None), f"Mật độ: {data.get('density', '-')}")
        _final_one_set_text(getattr(self, "lbl_state", None), f"Trạng thái giao thông: {data.get('traffic_state', '-')}")
        _final_one_set_text(getattr(self, "lbl_reason", None), reason)
        try:
            card = getattr(self, "card_vsl", None)
            if card is not None:
                card.dat_gia_tri(f"{vsl} km/h")
                card.dat_mo_ta(reason)
        except Exception:
            pass
        return None


    _final_one_old_update_ui = getattr(GiaoDienChinh, "update_ui_from_stats", None)

    def _final_one_update_ui_from_stats(self, stats):
        try:
            _final_one_call(_final_one_old_update_ui, self, stats)
        except Exception:
            pass
        _final_one_push_stats_to_ui(self, stats)


    GiaoDienChinh.update_ui_from_stats = _final_one_update_ui_from_stats
except Exception as _final_one_vsl_exc:
    try:
        ghi_log(f"FINAL_ONE_RUNTIME_CLEAN VSL loi: {_final_one_vsl_exc}")
    except Exception:
        pass


# =========================================================
# FINAL_DYNAMIC_VSL_CLEAN_PATCH
# Reset runtime khi đổi video, bắt infer frame đầu và tính VSL
# động theo ROI + PCU + HCM; các lớp/chức năng lõi vẫn giữ nguyên.
# =========================================================
try:
    def _final_dynamic_call(method, self, *args, **kwargs):
        if method is None:
            return None
        try:
            if getattr(method, "__self__", None) is not None:
                return method(*args, **kwargs)
        except Exception:
            pass
        return method(self, *args, **kwargs)


    def _final_dynamic_int(value, default=0):
        try:
            return int(float(value))
        except Exception:
            return int(default)


    def _final_dynamic_float(value, default=0.0):
        try:
            return float(value)
        except Exception:
            return float(default)


    def _final_dynamic_set_text(widget, value):
        try:
            if widget is not None and callable(getattr(widget, "setText", None)):
                widget.setText(str(value))
        except Exception:
            pass


    def _final_dynamic_dat_value(card, value):
        try:
            if card is not None and callable(getattr(card, "dat_gia_tri", None)):
                card.dat_gia_tri(str(value))
        except Exception:
            pass


    def _final_dynamic_dat_desc(card, value):
        try:
            if card is not None and callable(getattr(card, "dat_mo_ta", None)):
                card.dat_mo_ta(str(value))
        except Exception:
            pass


    def _final_dynamic_video_path(value):
        try:
            value = os.fspath(value) if value is not None else ""
        except Exception:
            value = str(value or "")
        value = str(value).strip().strip('"')
        try:
            return os.path.abspath(os.path.normpath(value)) if value else ""
        except Exception:
            return value


    def _final_dynamic_stop_worker(worker, owner=None):
        if worker is None:
            return
        try:
            tracker = getattr(worker, "speed_tracker", None)
            if tracker is not None and callable(getattr(tracker, "reset", None)):
                tracker.reset()
        except Exception:
            pass
        try:
            running = bool(worker.isRunning()) if callable(getattr(worker, "isRunning", None)) else False
            if running:
                stop = getattr(worker, "yeu_cau_dung", None)
                if callable(stop):
                    stop()
                try:
                    worker.stop_requested = True
                except Exception:
                    pass
                pause = getattr(worker, "dat_tam_dung", None)
                if callable(pause):
                    pause(False)
                quit_method = getattr(worker, "quit", None)
                if callable(quit_method):
                    quit_method()
                wait = getattr(worker, "wait", None)
                if callable(wait):
                    wait(2000)
                try:
                    if worker.isRunning() and callable(getattr(worker, "terminate", None)):
                        worker.terminate()
                        worker.wait(500)
                except Exception:
                    pass
        except Exception:
            pass
        if owner is not None:
            try:
                if getattr(owner, "worker", None) is worker:
                    owner.worker = None
            except Exception:
                pass


    def _final_dynamic_reset_when_change_video(self):
        old_worker = getattr(self, "worker", None)
        _final_dynamic_stop_worker(old_worker, self)
        try:
            multi = getattr(self, "multi_worker", None)
            if multi is not None and callable(getattr(multi, "dung", None)):
                multi.dung()
            self.multi_worker = None
        except Exception:
            pass
        for name, value in (
            ("current_stats", {}),
            ("last_stats", {}),
            ("last_vsl", None),
            ("prev_vsl", None),
            ("video_loaded", False),
        ):
            try:
                setattr(self, name, value)
            except Exception:
                pass
        try:
            tracker = getattr(old_worker, "speed_tracker", None)
            if tracker is not None and callable(getattr(tracker, "reset", None)):
                tracker.reset()
        except Exception:
            pass
        try:
            vsl_cfg = getattr(getattr(self, "config", None), "vsl", None)
            vsl_max = max(
                _final_dynamic_int(getattr(vsl_cfg, "vsl_min", 40), 40),
                _final_dynamic_int(getattr(vsl_cfg, "vsl_max", 100), 100),
            )
        except Exception:
            vsl_max = 100
        reason = "\u0110\u00e3 \u0111\u1ed5i video, \u0111ang ch\u1edd ph\u00e2n t\u00edch l\u1ea1i"
        _final_dynamic_dat_value(getattr(self, "card_vsl", None), f"{vsl_max} km/h")
        _final_dynamic_dat_desc(getattr(self, "card_vsl", None), reason)
        _final_dynamic_dat_value(getattr(self, "card_roi", None), "0")
        _final_dynamic_dat_value(getattr(self, "card_state", None), "\u0110ang ch\u1edd")
        _final_dynamic_set_text(getattr(self, "hero_badge_vsl", None), f"BI\u1ec2N B\u00c1O: {vsl_max} km/h")
        _final_dynamic_set_text(getattr(self, "lbl_vsl", None), f"T\u1ed1c \u0111\u1ed9 \u0111\u1ec1 xu\u1ea5t: {vsl_max} km/h")
        _final_dynamic_set_text(getattr(self, "lbl_density", None), "M\u1eadt \u0111\u1ed9: -")
        _final_dynamic_set_text(getattr(self, "lbl_state", None), "Tr\u1ea1ng th\u00e1i giao th\u00f4ng: \u0110ang ch\u1edd")
        _final_dynamic_set_text(getattr(self, "lbl_reason", None), reason)
        _final_dynamic_set_text(getattr(self, "btn_pause", None), "T\u1ea1m d\u1eebng")
        try:
            pause = getattr(self, "btn_pause", None)
            if pause is not None:
                pause.setEnabled(False)
        except Exception:
            pass
        return None


    def _final_dynamic_try_open_video(path):
        path = _final_dynamic_video_path(path)
        if not path or not os.path.isfile(path):
            return False, {}, None, "File video kh\u00f4ng t\u1ed3n t\u1ea1i ho\u1eb7c \u0111\u01b0\u1eddng d\u1eabn kh\u00f4ng h\u1ee3p l\u1ec7"
        last_error = "OpenCV kh\u00f4ng \u0111\u1ecdc \u0111\u01b0\u1ee3c video"
        backends = []
        for backend_name in ("CAP_FFMPEG", "CAP_ANY"):
            backend = getattr(cv2, backend_name, None)
            if backend is not None and backend not in backends:
                backends.append(backend)
        if not backends:
            backends = [None]
        for backend in backends:
            cap = None
            try:
                cap = cv2.VideoCapture(path) if backend is None else cv2.VideoCapture(path, backend)
                if cap is None or not cap.isOpened():
                    continue
                ok, frame = cap.read()
                if not ok or frame is None:
                    try:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    except Exception:
                        pass
                    ok, frame = cap.read()
                if ok and frame is not None:
                    h, w = frame.shape[:2]
                    fps = _final_dynamic_float(cap.get(cv2.CAP_PROP_FPS), 25.0)
                    if fps <= 0:
                        fps = 25.0
                    info = {
                        "width": _final_dynamic_int(cap.get(cv2.CAP_PROP_FRAME_WIDTH), w),
                        "height": _final_dynamic_int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT), h),
                        "fps": fps,
                        "frame_count": _final_dynamic_int(cap.get(cv2.CAP_PROP_FRAME_COUNT), 0),
                    }
                    return True, info, frame, ""
                last_error = "Video m\u1edf \u0111\u01b0\u1ee3c nh\u01b0ng kh\u00f4ng \u0111\u1ecdc \u0111\u01b0\u1ee3c frame \u0111\u1ea7u ti\u00ean"
            except Exception as exc:
                last_error = str(exc)
            finally:
                try:
                    if cap is not None:
                        cap.release()
                except Exception:
                    pass
        return False, {}, None, last_error


    def _final_dynamic_push_stats_to_ui(self, stats):
        try:
            data = dict(stats or {})
        except Exception:
            data = {}
        vsl_cfg = getattr(getattr(self, "config", None), "vsl", None)
        vsl_min = max(0, _final_dynamic_int(getattr(vsl_cfg, "vsl_min", 40), 40))
        vsl_max = max(vsl_min, _final_dynamic_int(getattr(vsl_cfg, "vsl_max", 100), 100))
        vsl = _final_dynamic_int(data.get("suggested_vsl", vsl_max), vsl_max)
        vsl = max(vsl_min, min(vsl_max, vsl))
        reason = str(data.get("reason", "") or "\u0110ang ph\u00e2n t\u00edch HCM/ROI")
        if vsl_min >= 70:
            minimum = f"VSL b\u1ecb ch\u1eb7n b\u1edfi t\u1ed1c \u0111\u1ed9 t\u1ed1i thi\u1ec3u = {vsl_min} km/h"
            if minimum not in reason:
                reason = f"{reason} | {minimum}"
        data["suggested_vsl"] = vsl
        data["reason"] = reason
        _final_dynamic_dat_value(getattr(self, "card_vsl", None), f"{vsl} km/h")
        _final_dynamic_dat_desc(getattr(self, "card_vsl", None), reason)
        _final_dynamic_set_text(getattr(self, "lbl_vsl", None), f"T\u1ed1c \u0111\u1ed9 \u0111\u1ec1 xu\u1ea5t: {vsl} km/h")
        _final_dynamic_set_text(getattr(self, "hero_badge_vsl", None), f"BI\u1ec2N B\u00c1O: {vsl} km/h")
        _final_dynamic_set_text(getattr(self, "lbl_density", None), f"M\u1eadt \u0111\u1ed9: {data.get('density', '-')}")
        _final_dynamic_set_text(getattr(self, "lbl_state", None), f"Tr\u1ea1ng th\u00e1i giao th\u00f4ng: {data.get('traffic_state', '-')}")
        _final_dynamic_set_text(getattr(self, "lbl_reason", None), reason)
        _final_dynamic_dat_value(getattr(self, "card_roi", None), data.get("vehicles_in_roi", 0))
        _final_dynamic_dat_value(getattr(self, "card_state", None), data.get("traffic_state", "-"))
        _final_dynamic_dat_desc(getattr(self, "card_state", None), f"M\u1eadt \u0111\u1ed9: {data.get('density', '-')}")
        return data


    def _final_dynamic_sync_config_from_ui(self):
        cfg = getattr(getattr(self, "config", None), "vsl", None)
        if cfg is None:
            return None
        try:
            for widget_name, attr_name in (
                ("sld_vmin", "vsl_min"),
                ("sld_vmax", "vsl_max"),
                ("sld_scale_max", "scale_max"),
                ("sld_smoothing", "smoothing_window"),
                ("sld_manual_vsl", "manual_vsl"),
            ):
                widget = getattr(self, widget_name, None)
                slider = getattr(widget, "slider", widget)
                getter = getattr(slider, "value", None)
                if callable(getter):
                    setattr(cfg, attr_name, _final_dynamic_int(getter(), getattr(cfg, attr_name, 0)))
            for widget_name, attr_name in (
                ("cbo_weather", "weather"),
                ("cbo_incident", "incident"),
                ("cbo_mode", "control_mode"),
            ):
                widget = getattr(self, widget_name, None)
                getter = getattr(widget, "currentText", None)
                if callable(getter):
                    value = str(getter())
                    if value:
                        setattr(cfg, attr_name, value)
            cfg.vsl_min = max(0, _final_dynamic_int(getattr(cfg, "vsl_min", 40), 40))
            cfg.vsl_max = max(cfg.vsl_min, _final_dynamic_int(getattr(cfg, "vsl_max", 100), 100))
        except Exception:
            pass
        worker = getattr(self, "worker", None)
        try:
            if worker is not None and getattr(worker, "config", None) is not None:
                worker.config.vsl.weather = cfg.weather
                worker.config.vsl.incident = cfg.incident
                worker.config.vsl.vsl_min = cfg.vsl_min
                worker.config.vsl.vsl_max = cfg.vsl_max
                worker.config.vsl.control_mode = cfg.control_mode
        except Exception:
            pass
        return cfg


    _final_dynamic_old_process_frame = getattr(XuLyVideo, "xu_ly_khung_hinh", None)

    def _final_dynamic_process_frame(self, frame):
        frame_out = frame
        original_stride = None
        try:
            detection = getattr(getattr(self, "config", None), "detection", None)
            if detection is not None:
                original_stride = getattr(detection, "frame_stride", None)
                if _final_dynamic_int(getattr(self, "frame_idx", 0), 0) <= 2:
                    detection.frame_stride = 1
            frame_out = _final_dynamic_call(_final_dynamic_old_process_frame, self, frame)
        except Exception:
            frame_out = frame
        finally:
            try:
                if original_stride is not None:
                    detection.frame_stride = original_stride
            except Exception:
                pass
        try:
            stats = dict(getattr(self, "last_stats", {}) or {})
        except Exception:
            stats = {}
        cfg = getattr(getattr(self, "config", None), "vsl", None)
        vsl_min = max(0, _final_dynamic_int(getattr(cfg, "vsl_min", 40), 40))
        vsl_max = max(vsl_min, _final_dynamic_int(getattr(cfg, "vsl_max", 100), 100))
        weather = str(getattr(cfg, "weather", "Tr\u1eddi quang") or "Tr\u1eddi quang")
        incident = str(getattr(cfg, "incident", "Kh\u00f4ng") or "Kh\u00f4ng")
        counts = stats.get("class_counts") if isinstance(stats.get("class_counts"), dict) else {}
        counts = {name: max(0, _final_dynamic_int(counts.get(name, 0), 0)) for name in VEHICLE_CLASSES}
        vehicles = max(0, _final_dynamic_int(stats.get("vehicles_in_roi", 0), 0))
        boxes = getattr(self, "last_inference_boxes", []) or []
        if boxes:
            fresh = {name: 0 for name in VEHICLE_CLASSES}
            fresh_total = 0
            for det in boxes:
                try:
                    name = str(det[4])
                    in_roi = bool(det[9]) if len(det) > 9 else True
                    if in_roi and name in fresh:
                        fresh[name] += 1
                        fresh_total += 1
                except Exception:
                    pass
            if fresh_total > 0 or _final_dynamic_int(getattr(self, "frame_idx", 0), 0) <= 2:
                counts, vehicles = fresh, fresh_total
        if vehicles <= 0:
            vehicles = sum(counts.values())
        pcu = (
            counts.get("car", 0) * 1.0
            + counts.get("motorcycle", 0) * 0.3
            + counts.get("bicycle", 0) * 0.2
            + counts.get("truck", 0) * 2.0
            + counts.get("bus", 0) * 2.5
        )
        lanes = max(1, _final_dynamic_int(getattr(getattr(getattr(self, "config", None), "lane", None), "lane_count", 1), 1))
        l_eff_m = _final_dynamic_float(os.getenv("VSL_HCM_ROI_LENGTH_M", "200"), 200.0)
        l_eff_km = max(0.05, l_eff_m / 1000.0)
        d_roi = pcu / max(0.05, l_eff_km * lanes)
        d_flow = max(0.0, _final_dynamic_float(stats.get("hcm_D_flow", 0.0), 0.0))
        d_star = max(d_roi, d_flow)
        if d_star <= 7:
            los, v_hcm = "A", vsl_max
        elif d_star <= 11:
            los, v_hcm = "B", vsl_max
        elif d_star <= 16:
            los, v_hcm = "C", max(vsl_min, vsl_max - 10)
        elif d_star <= 22:
            los, v_hcm = "D", max(vsl_min, vsl_max - 20)
        elif d_star <= 28:
            los, v_hcm = "E", max(vsl_min, vsl_max - 30)
        else:
            los, v_hcm = "F", vsl_min
        pressure = 30 if vehicles >= 12 else 20 if vehicles >= 8 else 10 if vehicles >= 5 else 0
        v_density = max(vsl_min, vsl_max - pressure)
        speed = 0.0
        for key in ("toc_do_tb_kmh", "speed_avg_kmh", "avg_speed_kmh"):
            value = _final_dynamic_float(stats.get(key, 0), 0.0)
            if value > 0:
                speed = value
                break
        if speed <= 0:
            try:
                values = self.speed_tracker.lay_toc_do()
                if values:
                    speed = sum(values) / len(values)
            except Exception:
                pass
        v_obs = min(vsl_max, speed + 10) if speed > 0 else vsl_max
        weather_l = weather.lower()
        if "m\u01b0a to" in weather_l:
            v_weather = min(vsl_max, 70)
        elif "m\u01b0a v\u1eeba" in weather_l or weather_l.strip() == "m\u01b0a":
            v_weather = min(vsl_max, 80)
        elif "m\u01b0a nh\u1ecf" in weather_l:
            v_weather = min(vsl_max, 90)
        elif "s\u01b0\u01a1ng m\u00f9 d\u00e0y" in weather_l:
            v_weather = min(vsl_max, 60)
        elif "s\u01b0\u01a1ng m\u00f9 v\u1eeba" in weather_l or weather_l.strip() == "s\u01b0\u01a1ng m\u00f9":
            v_weather = min(vsl_max, 70)
        elif "s\u01b0\u01a1ng m\u00f9 m\u1ecfng" in weather_l:
            v_weather = min(vsl_max, 80)
        else:
            v_weather = vsl_max
        incident_l = incident.lower()
        v_incident = min(vsl_max, 40) if "nghi\u00eam tr\u1ecdng" in incident_l else min(vsl_max, 70) if "nh\u1eb9" in incident_l else vsl_max
        raw_vsl = max(vsl_min, min(vsl_max, v_hcm, v_density, v_obs, v_weather, v_incident))
        final_vsl = int(raw_vsl // 10 * 10)
        old_vsl = getattr(self, "last_vsl", None)
        if old_vsl is not None:
            old_vsl = _final_dynamic_int(old_vsl, final_vsl)
            if final_vsl > old_vsl:
                final_vsl = min(final_vsl, old_vsl + 10)
        final_vsl = max(vsl_min, min(vsl_max, final_vsl))
        density = "TH\u1ea4P" if los in ("A", "B") and vehicles < 5 else "TRUNG B\u00ccNH"
        traffic = "L\u01b0u th\u00f4ng t\u1ed1t" if density == "TH\u1ea4P" else "L\u01b0u th\u00f4ng \u1ed5n \u0111\u1ecbnh"
        if los in ("E", "F") or vehicles >= 8:
            density, traffic = "CAO", "M\u1eadt \u0111\u1ed9 cao"
        if los == "F" or vehicles >= 12:
            traffic = "Nguy c\u01a1 \u00f9n t\u1eafc"
        reason = (
            f"HCM LOS {los} | D*={d_star:.2f} | D_roi={d_roi:.2f} | xe_roi={vehicles} | PCU={pcu:.1f} | "
            f"min(HCM={int(v_hcm)}, DENSITY={int(v_density)}, OBS={int(v_obs)}, WEATHER={int(v_weather)}, INCIDENT={int(v_incident)})"
        )
        if vsl_min >= 70:
            reason += f" | VSL b\u1ecb ch\u1eb7n b\u1edfi t\u1ed1c \u0111\u1ed9 t\u1ed1i thi\u1ec3u = {vsl_min} km/h"
        stats.update({
            "suggested_vsl": int(final_vsl),
            "vehicles_in_roi": int(vehicles),
            "class_counts": counts,
            "density": density,
            "traffic_state": traffic,
            "reason": reason,
            "hcm_D_roi": round(d_roi, 2),
            "hcm_D_flow": round(d_flow, 2),
            "hcm_D_star": round(d_star, 2),
            "hcm_LOS": los,
            "hcm_V_HCM": int(v_hcm),
            "hcm_V_density": int(v_density),
            "hcm_V_observed": int(v_obs),
            "hcm_V_weather": int(v_weather),
            "hcm_V_incident": int(v_incident),
        })
        self.last_stats = stats
        self.last_vsl = int(final_vsl)
        try:
            self.statsReady.emit(stats)
        except Exception:
            pass
        try:
            h, w = frame_out.shape[:2]
            line1 = f"VSL: {final_vsl} km/h | LOS {los} | D*={d_star:.1f}"
            line2 = "HCM/ROI realtime"
            font = cv2.FONT_HERSHEY_SIMPLEX
            scale = 0.50
            thick = 1
            size1 = cv2.getTextSize(line1, font, scale, thick)[0]
            size2 = cv2.getTextSize(line2, font, scale, thick)[0]
            box_w = min(520, max(size1[0], size2[0]) + 18)
            box_h = min(58, max(42, h - 12))
            x0, y0 = 10, 10
            x1 = min(w - 2, x0 + box_w)
            y1 = min(h - 2, y0 + box_h)
            cv2.rectangle(frame_out, (x0, y0), (max(x0 + 1, x1), max(y0 + 1, y1)), (0, 0, 0), -1)
            cv2.putText(frame_out, line1, (x0 + 8, min(y0 + 23, y1 - 20)), font, scale, (0, 255, 255), thick, cv2.LINE_AA)
            cv2.putText(frame_out, line2, (x0 + 8, min(y0 + 45, y1 - 4)), font, scale, (220, 255, 220), thick, cv2.LINE_AA)
        except Exception:
            pass
        return frame_out


    XuLyVideo.xu_ly_khung_hinh = _final_dynamic_process_frame

    _final_dynamic_old_update_ui = getattr(GiaoDienChinh, "update_ui_from_stats", None)

    def _final_dynamic_update_ui_from_stats(self, stats):
        try:
            _final_dynamic_call(_final_dynamic_old_update_ui, self, stats)
        except Exception:
            pass
        _final_dynamic_push_stats_to_ui(self, stats)


    GiaoDienChinh.update_ui_from_stats = _final_dynamic_update_ui_from_stats

    _final_dynamic_old_open_video = getattr(GiaoDienChinh, "on_open_video", None)

    def _final_dynamic_open_video(self, *args, **kwargs):
        try:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Ch\u1ecdn video", "", "Video files (*.mp4 *.avi *.mkv *.mov *.wmv *.m4v);;All files (*)")
        except Exception as exc:
            try:
                QtWidgets.QMessageBox.warning(self, "L\u1ed7i m\u1edf video", str(exc))
            except Exception:
                pass
            return None
        if not path:
            return None
        previous_path = getattr(self, "video_path", None)
        _final_dynamic_reset_when_change_video(self)
        ok, info, frame, error = _final_dynamic_try_open_video(path)
        if not ok:
            try:
                self.video_path = previous_path
            except Exception:
                pass
            try:
                QtWidgets.QMessageBox.warning(self, "L\u1ed7i m\u1edf video", f"Kh\u00f4ng m\u1edf \u0111\u01b0\u1ee3c video.\n{error}")
            except Exception:
                pass
            return None
        path = _final_dynamic_video_path(path)
        for name in ("video_path", "selected_video_path", "current_video_path", "duong_dan_video", "file_video", "video_file"):
            try:
                setattr(self, name, path)
            except Exception:
                pass
        try:
            self.camera_hien_tai = None
            combo = getattr(self, "cbo_camera", None)
            if combo is not None:
                combo.blockSignals(True)
                combo.setCurrentIndex(0)
                combo.blockSignals(False)
        except Exception:
            pass
        _final_dynamic_set_text(getattr(self, "lbl_video_name", None), f"Video: {os.path.basename(path)}")
        info_text = f"Resolution: {info.get('width', 0)} x {info.get('height', 0)} | FPS: {info.get('fps', 25.0):.1f}"
        for name in ("lbl_video_res", "lbl_resolution", "label_resolution"):
            _final_dynamic_set_text(getattr(self, name, None), info_text)
        try:
            self.show_frame(chuyen_bgr_sang_qimage(frame))
        except Exception:
            pass
        self.video_loaded = True
        _final_dynamic_set_text(getattr(self, "lbl_status", None), "S\u1eb5n s\u00e0ng ch\u1ea1y.")
        try:
            sync_state = getattr(self, "dong_bo_trang_thai_chay", None)
            if callable(sync_state):
                sync_state(False)
        except Exception:
            pass
        for _button_name in ("btn_start", "btn_bat_dau", "start_button"):
            try:
                _button = getattr(self, _button_name, None)
                if _button is not None:
                    _button.setEnabled(True)
            except Exception:
                pass
        for _button_name in ("btn_pause", "btn_tam_dung", "pause_button"):
            try:
                _button = getattr(self, _button_name, None)
                if _button is not None:
                    _button.setEnabled(False)
            except Exception:
                pass
        try:
            self.video_label.show()
            self.video_label.clear()
            self.show_frame(chuyen_bgr_sang_qimage(frame))
        except Exception:
            pass
        try:
            nap = getattr(self, "nap_cau_hinh_toc_do_cho_video", None)
            if callable(nap):
                nap(path)
        except Exception:
            pass
        try:
            if callable(getattr(self, "append_log", None)):
                self.append_log(f"[VIDEO] \u0110\u00e3 ch\u1ecdn video h\u1ee3p l\u1ec7: {path}")
        except Exception:
            pass
        return path


    GiaoDienChinh.on_open_video = _final_dynamic_open_video
    for _name in ("on_chon_video", "chon_video", "xu_ly_chon_video", "chon_file_video", "open_video_file", "browse_video", "select_video"):
        if hasattr(GiaoDienChinh, _name):
            setattr(GiaoDienChinh, _name, _final_dynamic_open_video)

    _final_dynamic_old_start = getattr(GiaoDienChinh, "on_start", None)

    def _final_dynamic_on_start(self, *args, **kwargs):
        _final_dynamic_sync_config_from_ui(self)
        _final_dynamic_stop_worker(getattr(self, "worker", None), self)
        for name, value in (("current_stats", {}), ("last_stats", {}), ("last_vsl", None), ("prev_vsl", None)):
            try:
                setattr(self, name, value)
            except Exception:
                pass
        result = _final_dynamic_call(_final_dynamic_old_start, self, *args, **kwargs)
        worker = getattr(self, "worker", None)
        try:
            if worker is not None:
                worker.last_stats = {}
                worker.last_vsl = None
                if hasattr(worker, "vehicle_history"):
                    worker.vehicle_history.clear()
                tracker = getattr(worker, "speed_tracker", None)
                if tracker is not None and callable(getattr(tracker, "reset", None)):
                    tracker.reset()
        except Exception:
            pass
        vsl_max = _final_dynamic_int(getattr(getattr(getattr(self, "config", None), "vsl", None), "vsl_max", 100), 100)
        _final_dynamic_push_stats_to_ui(self, {
            "suggested_vsl": vsl_max,
            "vehicles_in_roi": 0,
            "density": "\u0110ANG KH\u1edeI T\u1ea0O",
            "traffic_state": "\u0110ang ph\u00e2n t\u00edch",
            "reason": "\u0110ang kh\u1edfi t\u1ea1o HCM/ROI dynamic, VSL s\u1ebd c\u1eadp nh\u1eadt t\u1eeb frame \u0111\u1ea7u",
        })
        return result


    GiaoDienChinh.on_start = _final_dynamic_on_start
    for _name in ("bat_dau_phan_tich", "xu_ly_bat_dau", "start_analysis", "start_video"):
        if hasattr(GiaoDienChinh, _name):
            setattr(GiaoDienChinh, _name, _final_dynamic_on_start)

    def _final_dynamic_sync_callback(self, *args, **kwargs):
        result = getattr(self, "_final_dynamic_callback_old_result", None)
        return result


    for _name in ("xu_ly_doi_thoi_tiet", "xu_ly_doi_su_co", "xu_ly_doi_che_do", "update_vsl_config", "cap_nhat_cau_hinh_vsl"):
        _old_callback = getattr(GiaoDienChinh, _name, None)
        if _old_callback is None:
            continue
        def _final_dynamic_wrapped_callback(self, *args, _old=_old_callback, **kwargs):
            result = _final_dynamic_call(_old, self, *args, **kwargs)
            _final_dynamic_sync_config_from_ui(self)
            try:
                _final_dynamic_push_stats_to_ui(self, getattr(self, "last_stats", {}) or {})
            except Exception:
                pass
            return result
        setattr(GiaoDienChinh, _name, _final_dynamic_wrapped_callback)

except Exception as _final_dynamic_patch_exc:
    try:
        ghi_log(f"FINAL_DYNAMIC_VSL_CLEAN_PATCH loi: {_final_dynamic_patch_exc}")
    except Exception:
        pass


# =========================================================
# TWO-WAY INDEPENDENT ROAD ROI
# =========================================================
_TWO_WAY_ROI_FIELDS = (
    ("top_left_x", "Mép trên trái X (%)", 0, 100),
    ("top_right_x", "Mép trên phải X (%)", 0, 100),
    ("bottom_left_x", "Mép dưới trái X (%)", 0, 100),
    ("bottom_right_x", "Mép dưới phải X (%)", 0, 100),
    ("y_top", "Y trên (%)", 0, 95),
    ("y_bot", "Y dưới (%)", 5, 99),
)


def _two_way_road_defaults(side):
    cfg = doc_cau_hinh_roi_duong()
    part = dict(DEFAULT_ROI_ROAD_CONFIG.get(side, {}))
    part.update(cfg.get(side, {}) if isinstance(cfg.get(side, {}), dict) else {})
    return {
        "top_left_x": _clamp_ratio(part.get("top_left_x", 0.0)),
        "top_right_x": _clamp_ratio(part.get("top_right_x", 1.0)),
        "bottom_left_x": _clamp_ratio(part.get("bottom_left_x", 0.0)),
        "bottom_right_x": _clamp_ratio(part.get("bottom_right_x", 1.0)),
        "y_top": _clamp_ratio(part.get("y_top", cfg.get("y_top", 0.36)), 0.02, 0.95),
        "y_bot": _clamp_ratio(part.get("y_bot", cfg.get("y_bot", 0.92)), 0.05, 0.99),
    }


def _ensure_two_way_road_roi(roi_config, side):
    if side not in ("left_road", "right_road"):
        raise ValueError(f"ROI side không hợp lệ: {side}")
    if roi_config is None:
        roi_config = CauHinhROI()
    defaults = _two_way_road_defaults(side)
    values = {}
    for field, _label, _minimum, _maximum in _TWO_WAY_ROI_FIELDS:
        attr = f"{side}_{field}"
        value = getattr(roi_config, attr, defaults[field])
        if field in ("y_top", "y_bot"):
            value = _clamp_ratio(value, 0.02 if field == "y_top" else 0.05, 0.95 if field == "y_top" else 0.99)
        else:
            value = _clamp_ratio(value)
        setattr(roi_config, attr, value)
        values[field] = value
    if values["y_bot"] <= values["y_top"] + 0.02:
        values["y_bot"] = min(0.99, values["y_top"] + 0.02)
        setattr(roi_config, f"{side}_y_bot", values["y_bot"])
    return roi_config, values


def update_two_way_road_roi(roi_config, side, field, value):
    """Update exactly one road ROI control; the opposite side is untouched."""
    if field not in {item[0] for item in _TWO_WAY_ROI_FIELDS}:
        raise ValueError(f"Trường ROI không hợp lệ: {field}")
    roi_config, _values = _ensure_two_way_road_roi(roi_config, side)
    opposite_side = "right_road" if side == "left_road" else "left_road"
    _ensure_two_way_road_roi(roi_config, opposite_side)
    number = float(value) / 100.0 if float(value) > 1.0 else float(value)
    if field == "y_top":
        number = _clamp_ratio(number, 0.02, 0.95)
    elif field == "y_bot":
        number = _clamp_ratio(number, 0.05, 0.99)
    else:
        number = _clamp_ratio(number)
    setattr(roi_config, f"{side}_{field}", number)
    _ensure_two_way_road_roi(roi_config, side)
    return roi_config


def build_two_way_road_rois(width, height, roi_config=None):
    polygons = {}
    for side in ("left_road", "right_road"):
        _roi, values = _ensure_two_way_road_roi(roi_config, side)
        polygons[side] = np.array([
            [int(width * values["top_left_x"]), int(height * values["y_top"])],
            [int(width * values["top_right_x"]), int(height * values["y_top"])],
            [int(width * values["bottom_right_x"]), int(height * values["y_bot"])],
            [int(width * values["bottom_left_x"]), int(height * values["y_bot"])],
        ], dtype=np.int32)
    return polygons


def _two_way_save_road_rois(roi_config):
    cfg = doc_cau_hinh_roi_duong()
    for side in ("left_road", "right_road"):
        _roi, values = _ensure_two_way_road_roi(roi_config, side)
        cfg[side] = dict(values)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(ROI_ROAD_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _two_way_apply_from_ui(self, side, field, value):
    try:
        if getattr(self.config, "roi", None) is None:
            self.config.roi = CauHinhROI()
        roi = update_two_way_road_roi(self.config.roi, side, field, value)
        _two_way_save_road_rois(roi)
        _median_live_sync_from_ui(self)
        if getattr(self, "worker", None) is not None:
            self.worker.config.roi = roi
        if hasattr(self, "lbl_status"):
            label = "trái" if side == "left_road" else "phải"
            self.lbl_status.setText(f"Đã áp dụng riêng ROI lề {label}; ROI bên còn lại không thay đổi.")
    except Exception as exc:
        ghi_log(f"Lỗi cập nhật ROI {side}.{field}: {exc}")


def _two_way_reset_road_roi(self, side):
    try:
        roi = getattr(self.config, "roi", None) or CauHinhROI()
        self.config.roi = roi
        defaults = _two_way_road_defaults(side)
        for field, value in defaults.items():
            setattr(roi, f"{side}_{field}", value)
            slider = getattr(self, f"sld_{'left' if side == 'left_road' else 'right'}_{field}", None)
            if slider is not None:
                slider.setValue(int(round(value * 100)))
        _two_way_save_road_rois(roi)
        _median_live_sync_from_ui(self)
        if getattr(self, "worker", None) is not None:
            self.worker.config.roi = roi
    except Exception as exc:
        ghi_log(f"Lỗi reset ROI {side}: {exc}")


try:
    _two_way_old_all_lanes = _final_all_lanes

    def _final_all_lanes(w, h, roi_cfg=None):
        live_roi = roi_cfg or _LIVE_MEDIAN_ROI_OBJECT
        polygons = build_two_way_road_rois(w, h, live_roi)
        _old_roads, median = _final_roi_chuan_bo_median(w, h, live_roi)
        roads = [("LEFT", polygons["left_road"]), ("RIGHT", polygons["right_road"])]
        lanes = []
        for side, polygon in roads:
            lanes.extend(_final_split_lanes(side, polygon, 3))
        return roads, median, lanes


    _two_way_old_build_roi = GiaoDienChinh.tao_trang_roi

    def _two_way_build_roi_page(self):
        page = _two_way_old_build_roi(self)
        legacy_card = None
        for name in ("sld_top_cx", "sld_bot_cx", "sld_bot_w", "sld_top_w", "sld_height", "sld_bottom_y"):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.setVisible(False)
                parent = widget.parentWidget()
                while parent is not None and not isinstance(parent, KhungNoiDung):
                    parent = parent.parentWidget()
                legacy_card = legacy_card or parent
        if legacy_card is not None:
            legacy_card.setVisible(False)
        for side, title, prefix in (
            ("left_road", "ROI lề trái", "left"),
            ("right_road", "ROI lề phải", "right"),
        ):
            _roi, values = _ensure_two_way_road_roi(self.config.roi, side)
            card = KhungNoiDung(title, "6 thanh riêng: chỉnh vùng này không làm dịch chuyển ROI phía đối diện.")
            for field, label, minimum, maximum in _TWO_WAY_ROI_FIELDS:
                slider = ThanhTruotCoNhan(label, minimum, maximum, int(round(values[field] * 100)))
                setattr(self, f"sld_{prefix}_{field}", slider)
                card.lay.addWidget(slider)
            button = QtWidgets.QPushButton(f"Reset {title}")
            button.setObjectName("SecondaryBtn")
            setattr(self, f"btn_reset_{prefix}_roi", button)
            card.lay.addWidget(button)
            page.content.addWidget(card)
        return page


    GiaoDienChinh.tao_trang_roi = _two_way_build_roi_page

    _two_way_old_bind = GiaoDienChinh._gan_trang_thai_ban_dau

    def _two_way_bind_roi_controls(self):
        _two_way_old_bind(self)
        for side, prefix in (("left_road", "left"), ("right_road", "right")):
            for field, _label, _minimum, _maximum in _TWO_WAY_ROI_FIELDS:
                slider = getattr(self, f"sld_{prefix}_{field}", None)
                if slider is not None:
                    slider.valueChanged.connect(
                        lambda value, s=side, f=field: _two_way_apply_from_ui(self, s, f, value)
                    )
            button = getattr(self, f"btn_reset_{prefix}_roi", None)
            if button is not None:
                button.clicked.connect(lambda _checked=False, s=side: _two_way_reset_road_roi(self, s))


    GiaoDienChinh._gan_trang_thai_ban_dau = _two_way_bind_roi_controls

    _two_way_old_runtime_controls = GiaoDienChinh.bat_tat_dieu_khien_khi_chay

    def _two_way_runtime_controls(self, running):
        _two_way_old_runtime_controls(self, running)
        for prefix in ("left", "right"):
            for field, _label, _minimum, _maximum in _TWO_WAY_ROI_FIELDS:
                slider = getattr(self, f"sld_{prefix}_{field}", None)
                if slider is not None:
                    slider.setEnabled(True)
            button = getattr(self, f"btn_reset_{prefix}_roi", None)
            if button is not None:
                button.setEnabled(True)


    GiaoDienChinh.bat_tat_dieu_khien_khi_chay = _two_way_runtime_controls
except Exception as _two_way_roi_patch_exc:
    try:
        ghi_log(f"TWO_WAY_INDEPENDENT_ROI lỗi: {_two_way_roi_patch_exc}")
    except Exception:
        pass


# MISSION CONTROL – STANDALONE PAGE
class _MissionChart(QtWidgets.QWidget):
    def __init__(self,title,color,parent=None): super().__init__(parent); self.title,self.color=title,QtGui.QColor(color); self.data=deque(maxlen=60); self.setMinimumHeight(210)
    def push(self,v):
        try: self.data.append(float(v)); self.update()
        except Exception: pass
    def paintEvent(self,e):
        p=QtGui.QPainter(self); p.setRenderHint(QtGui.QPainter.Antialiasing); r=self.rect().adjusted(52,44,-16,-42); p.fillRect(self.rect(),QtGui.QColor('#fff')); p.setPen(QtGui.QColor('#173b67')); p.drawText(14,22,self.title+' – 60 GIÂY GẦN NHẤT'); values=list(self.data); current=values[-1] if values else 0; low=min(values) if values else 0; high=max(values) if values else 0; p.setPen(self.color); p.setFont(QtGui.QFont('Segoe UI',13,QtGui.QFont.Bold)); p.drawText(self.width()-145,25,f'{current:.1f}'); p.setFont(QtGui.QFont('Segoe UI',8)); p.setPen(QtGui.QColor('#64748b')); p.drawText(self.width()-72,25,'hiện tại'); p.drawText(14,self.height()-25,f'Min {low:.1f}   •   Max {high:.1f}'); p.drawText(self.width()-160,self.height()-25,'60s trước → bây giờ'); p.setPen(QtGui.QPen(QtGui.QColor('#dbe7f4'),1))
        for i in range(5):
            y=int(r.top()+i*r.height()/4); p.drawLine(r.left(),y,r.right(),y); p.setPen(QtGui.QColor('#94a3b8')); p.drawText(14,y+4,f'{(high-(high-low)*i/4):.0f}'); p.setPen(QtGui.QPen(QtGui.QColor('#dbe7f4'),1))
        if len(self.data)>1:
            m=max(max(self.data),1); path=QtGui.QPainterPath()
            for i,v in enumerate(self.data):
                x=r.left()+i*r.width()/max(1,len(self.data)-1); y=r.bottom()-v/m*r.height(); path.moveTo(x,y) if i==0 else path.lineTo(x,y)
            p.setPen(QtGui.QPen(self.color,3)); p.drawPath(path)
        p.end()
try:
    _mission_old_nav=GiaoDienChinh.tao_thanh_dieu_huong
    def _mission_nav(self):
        rail=_mission_old_nav(self); self._mission_nav_layout=rail.layout(); return rail
    GiaoDienChinh.tao_thanh_dieu_huong=_mission_nav
    _mission_old_stack=GiaoDienChinh.tao_chong_trang_chuc_nang
    def _mission_stack(self):
        wrap=_mission_old_stack(self); page=TrangChucNang('Mission Control','Biểu đồ điều hành giao thông thời gian thực.'); card=KhungNoiDung('Dòng dữ liệu trực tiếp','Theo dõi mật độ, tốc độ trung bình và VSL đề xuất.'); self.mission_density=_MissionChart('MẬT ĐỘ XE','#1687f8'); self.mission_speed=_MissionChart('TỐC ĐỘ TB','#10b981'); self.mission_vsl=_MissionChart('VSL ĐỀ XUẤT','#f59e0b'); [card.lay.addWidget(c) for c in (self.mission_density,self.mission_speed,self.mission_vsl)]; page.content.addWidget(card); idx=self.stack.addWidget(page)
        def add_mission_button():
            if not hasattr(self,'nav_group') or hasattr(self,'btn_mission_control'): return
            btn=NutDieuHuong('Mission Control','biểu đồ • dòng thời gian'); self.btn_mission_control=btn; self.nav_group.addButton(btn,idx); self.nav_buttons.append(btn)
            layout=getattr(self,'_mission_nav_layout',None)
            if layout is not None: layout.insertWidget(max(1,layout.count()-2),btn)
            btn.clicked.connect(lambda: self.hieu_ung_chuyen_trang(idx))
        QtCore.QTimer.singleShot(0,add_mission_button); return wrap
    GiaoDienChinh.tao_chong_trang_chuc_nang=_mission_stack
    _mission_old_update=GiaoDienChinh.update_ui_from_stats
    def _mission_update(self,s):
        _mission_old_update(self,s)
        for n,k in (('mission_density','vehicles_in_roi'),('mission_speed','toc_do_tb_kmh'),('mission_vsl','suggested_vsl')):
            c=getattr(self,n,None)
            if c: c.push(s.get(k,0))
    GiaoDienChinh.update_ui_from_stats=_mission_update
except Exception as _e: ghi_log(f'MISSION_CONTROL lỗi: {_e}')

# =========================================================
# DASHBOARD RENDER SMOOTHING
# The processing pipeline above emits statistics from several compatibility
# layers for one video frame.  Rendering every emission overloads Qt's GUI
# event queue and makes the dashboard flicker.  Keep the latest data, but
# redraw the dashboard at a steady, human-visible cadence.
# =========================================================
def should_refresh_dashboard(last_update, now, interval_seconds):
    """Return True when a dashboard repaint is due.

    This intentionally has no Qt dependency so the refresh policy remains
    deterministic and easy to verify.
    """
    return last_update is None or (now - last_update) + 1e-9 >= interval_seconds


try:
    _dashboard_smooth_push_stats = _final_dynamic_push_stats_to_ui

    def _dashboard_smooth_update_ui(self, stats):
        now = time.monotonic()
        self._dashboard_latest_stats = dict(stats or {})
        if not should_refresh_dashboard(
            getattr(self, "_dashboard_last_stats_paint", None), now, 0.10
        ):
            return None
        self._dashboard_last_stats_paint = now
        return _dashboard_smooth_push_stats(self, self._dashboard_latest_stats)


    GiaoDienChinh.update_ui_from_stats = _dashboard_smooth_update_ui
except Exception as _dashboard_smooth_patch_exc:
    try:
        ghi_log(f"DASHBOARD_RENDER_SMOOTHING loi: {_dashboard_smooth_patch_exc}")
    except Exception:
        pass


# Final callback: this must be installed after dashboard smoothing, otherwise
# the smoothing wrapper consumes stats before Mission Control sees them.
try:
    _mission_final_update = GiaoDienChinh.update_ui_from_stats

    def _mission_final_update_ui(self, stats):
        _mission_final_update(self, stats)
        for name, key in (
            ("mission_density", "vehicles_in_roi"),
            ("mission_speed", "toc_do_tb_kmh"),
            ("mission_vsl", "suggested_vsl"),
        ):
            chart = getattr(self, name, None)
            if chart is not None:
                chart.push((stats or {}).get(key, 0))

    GiaoDienChinh.update_ui_from_stats = _mission_final_update_ui
except Exception as _mission_final_chart_exc:
    ghi_log(f"MISSION_CONTROL final callback lỗi: {_mission_final_chart_exc}")


# =========================================================
# FINAL_SPEED_VIOLATION_PATCH
# Đo tốc độ từng xe, chống cập nhật tracker trùng frame, đánh dấu
# phương tiện vượt VSL và lưu ảnh vi phạm theo thời gian giới hạn.
# =========================================================
try:
    _final_speed_old_tracker_update = getattr(BoDoTocDoHaiVach, "cap_nhat", None)

    def _final_speed_cached_tracker_update(
        self,
        frame_h,
        detections,
        frame_idx,
        fps_video,
        line_a=None,
        line_b=None,
        distance_m=None,
    ):
        """Trả lại kết quả đã đo nếu cùng tracker đã xử lý cùng frame."""
        cache_key = (
            int(frame_idx),
            id(detections),
            int(frame_h),
            float(line_a if line_a is not None else SPEED_LINE_A_RATIO),
            float(line_b if line_b is not None else SPEED_LINE_B_RATIO),
            float(distance_m if distance_m is not None else SPEED_DISTANCE_METERS),
        )
        if getattr(self, "_final_speed_cache_key", None) == cache_key:
            return list(getattr(self, "_final_speed_cache_value", []) or [])

        if _final_speed_old_tracker_update is None:
            measured = []
        else:
            measured = _final_speed_old_tracker_update(
                self,
                frame_h=frame_h,
                detections=detections,
                frame_idx=frame_idx,
                fps_video=fps_video,
                line_a=line_a,
                line_b=line_b,
                distance_m=distance_m,
            ) or []

        self._final_speed_cache_key = cache_key
        self._final_speed_cache_value = list(measured)
        return list(measured)


    if _final_speed_old_tracker_update is not None:
        BoDoTocDoHaiVach.cap_nhat = _final_speed_cached_tracker_update

    _final_speed_old_process_frame = XuLyVideo.xu_ly_khung_hinh

    def _final_speed_safe_int(value, default=0):
        try:
            return int(float(value))
        except Exception:
            return int(default)


    def _final_speed_safe_float(value, default=0.0):
        try:
            return float(value)
        except Exception:
            return float(default)


    def _final_speed_process_frame(self, frame):
        try:
            frame_out = _final_speed_old_process_frame(self, frame)
        except Exception as exc:
            frame_out = frame
            try:
                ghi_log(f"FINAL_SPEED_VIOLATION_PATCH process cũ lỗi: {exc}")
            except Exception:
                pass

        if frame_out is None or not hasattr(frame_out, "shape"):
            frame_out = frame

        try:
            h, w = frame_out.shape[:2]
        except Exception:
            return frame_out

        try:
            detections = getattr(self, "last_inference_boxes", []) or []
        except Exception:
            detections = []

        tracker = getattr(self, "speed_tracker", None)
        if tracker is None or not callable(getattr(tracker, "cap_nhat", None)):
            try:
                tracker = BoDoTocDoHaiVach()
                self.speed_tracker = tracker
            except Exception:
                tracker = None

        measured = []
        if tracker is not None and detections:
            try:
                measured = tracker.cap_nhat(
                    frame_h=h,
                    detections=detections,
                    frame_idx=_final_speed_safe_int(getattr(self, "frame_idx", 0), 0),
                    fps_video=_final_speed_safe_float(getattr(self, "fps_video", 25.0), 25.0),
                    line_a=getattr(self, "speed_line_a_ratio", SPEED_LINE_A_RATIO),
                    line_b=getattr(self, "speed_line_b_ratio", SPEED_LINE_B_RATIO),
                    distance_m=getattr(self, "speed_distance_m", SPEED_DISTANCE_METERS),
                ) or []
            except Exception as exc:
                measured = []
                try:
                    ghi_log(f"FINAL_SPEED_VIOLATION_PATCH đo tốc độ lỗi: {exc}")
                except Exception:
                    pass

        try:
            stats = dict(getattr(self, "last_stats", {}) or {})
        except Exception:
            stats = {}

        current_vsl = stats.get("suggested_vsl")
        if current_vsl in (None, ""):
            current_vsl = getattr(self, "last_vsl", None)
        if current_vsl in (None, ""):
            current_vsl = getattr(getattr(getattr(self, "config", None), "vsl", None), "vsl_max", None)
        try:
            current_vsl = _final_speed_safe_int(current_vsl, 0)
        except Exception:
            current_vsl = 0

        tolerance = _final_speed_safe_int(os.getenv("VSL_VIOLATION_TOLERANCE", "5"), 5)
        tolerance = max(0, tolerance)
        speed_min = _final_speed_safe_float(globals().get("SPEED_MIN_KMH", 5.0), 5.0)
        speed_max = _final_speed_safe_float(globals().get("SPEED_MAX_KMH", 160.0), 160.0)
        violation_saved = getattr(self, "violation_saved", None)
        if not isinstance(violation_saved, dict):
            violation_saved = {}
            self.violation_saved = violation_saved
        self.violation_count = _final_speed_safe_int(getattr(self, "violation_count", 0), 0)

        vehicle_speeds = []
        last_violation = None
        new_violation = False
        frame_idx = _final_speed_safe_int(getattr(self, "frame_idx", 0), 0)
        now = time.time()

        for item in measured:
            try:
                tid, speed_kmh, box, lane_label = item
                x1, y1, x2, y2 = [int(v) for v in box[:4]]
            except Exception:
                continue

            speed_value = None
            try:
                if speed_kmh is not None:
                    speed_value = float(speed_kmh)
            except Exception:
                speed_value = None

            valid_speed = (
                speed_value is not None
                and speed_value > 0
                and speed_value >= speed_min
                and speed_value <= speed_max
            )
            violation = bool(valid_speed and current_vsl > 0 and speed_value > current_vsl + tolerance)

            x1 = max(0, min(w - 1, x1))
            x2 = max(0, min(w - 1, x2))
            y1 = max(0, min(h - 1, y1))
            y2 = max(0, min(h - 1, y2))

            if speed_value is None or not valid_speed:
                label = f"ID {tid} | dang do"
                label_color = (0, 255, 255)
            elif violation:
                label = f"VI PHAM | ID {tid} | {speed_value:.1f}>{current_vsl} km/h"
                label_color = (0, 0, 255)
                cv2.rectangle(frame_out, (x1, y1), (x2, y2), (0, 0, 255), 3)
                cv2.putText(
                    frame_out,
                    f"VSL hien tai: {current_vsl} km/h",
                    (x1, min(h - 8, max(22, y2 + 22))),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.50,
                    (0, 0, 255),
                    2,
                    cv2.LINE_AA,
                )
            else:
                label = f"ID {tid} | {speed_value:.1f} km/h"
                label_color = (0, 220, 0)

            text_size = cv2.getTextSize(
                label, cv2.FONT_HERSHEY_SIMPLEX, 0.48, 1
            )[0]
            tx = max(0, min(w - text_size[0] - 12, x1))
            ty = max(20, y1 - 8)
            cv2.rectangle(
                frame_out,
                (tx, max(0, ty - text_size[1] - 8)),
                (min(w - 1, tx + text_size[0] + 10), min(h - 1, ty + 4)),
                (0, 0, 0),
                -1,
            )
            cv2.putText(
                frame_out,
                label,
                (tx + 5, ty),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.48,
                label_color,
                1,
                cv2.LINE_AA,
            )

            row = {
                "id": tid,
                "speed_kmh": round(speed_value, 1) if speed_value is not None else None,
                "lane": lane_label,
                "violation": violation,
            }
            vehicle_speeds.append(row)

            if not violation:
                continue

            message = f"Xe ID {tid} vượt VSL: {speed_value:.1f} km/h > {current_vsl} km/h"
            last_violation = message
            key = f"{tid}_{int(current_vsl)}"
            last_save = _final_speed_safe_float(violation_saved.get(key, 0), 0.0)
            if now - last_save < 5.0:
                continue

            try:
                root = getattr(self, "snapshots_dir", None)
                if root is None:
                    root = Path(OUTPUT_DIR) / "violations"
                violation_dir = Path(root) / "violations"
                violation_dir.mkdir(parents=True, exist_ok=True)
                stamp = time.strftime("%Y%m%d_%H%M%S")
                speed_text = f"{speed_value:.1f}".replace("/", "_")
                filename = (
                    f"violation_ID{tid}_speed{speed_text}_vsl{current_vsl}_"
                    f"frame{frame_idx}_{stamp}.jpg"
                )
                image_path = violation_dir / filename
                if cv2.imwrite(str(image_path), frame_out):
                    violation_saved[key] = now
                    self.violation_count += 1
                    new_violation = True
                    if hasattr(self, "warning_count"):
                        self.warning_count = _final_speed_safe_int(self.warning_count, 0) + 1
                    try:
                        t_sec = frame_idx / max(
                            1.0,
                            _final_speed_safe_float(getattr(self, "fps_video", 25.0), 25.0),
                        )
                        if callable(getattr(self, "them_su_kien", None)):
                            self.them_su_kien("VIOLATION", message, t_sec)
                        elif callable(getattr(self, "them_nhat_ky", None)):
                            self.them_nhat_ky(message)
                    except Exception:
                        pass
            except Exception as exc:
                try:
                    ghi_log(f"FINAL_SPEED_VIOLATION_PATCH lưu ảnh lỗi: {exc}")
                except Exception:
                    pass

        stats["vehicle_speeds"] = vehicle_speeds
        stats["violation_count"] = self.violation_count
        if last_violation is not None:
            stats["last_violation"] = last_violation
        self.last_stats = stats

        if new_violation or frame_idx % 10 == 0:
            try:
                self.statsReady.emit(stats)
            except Exception:
                pass

        try:
            line_a = int(h * _final_speed_safe_float(getattr(self, "speed_line_a_ratio", SPEED_LINE_A_RATIO), SPEED_LINE_A_RATIO))
            line_b = int(h * _final_speed_safe_float(getattr(self, "speed_line_b_ratio", SPEED_LINE_B_RATIO), SPEED_LINE_B_RATIO))
            cv2.line(frame_out, (0, line_a), (w - 1, line_a), (255, 0, 0), 2)
            cv2.line(frame_out, (0, line_b), (w - 1, line_b), (0, 165, 255), 2)
            cv2.putText(frame_out, "Line A - bat dau do toc do", (12, max(20, line_a - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 0, 0), 1, cv2.LINE_AA)
            cv2.putText(frame_out, "Line B - ket thuc do toc do", (12, max(20, line_b - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 165, 255), 1, cv2.LINE_AA)
        except Exception:
            pass

        return frame_out


    # Khối vẽ box/tốc độ/vi phạm đã được xử lý trực tiếp trong
    # XuLyVideo.xu_ly_khung_hinh gốc; không bọc lại frame để tránh đo và vẽ trùng.
    if _final_speed_old_tracker_update is not None:
        BoDoTocDoHaiVach.cap_nhat = _final_speed_old_tracker_update
except Exception as _final_speed_violation_patch_exc:
    try:
        ghi_log(f"FINAL_SPEED_VIOLATION_PATCH loi: {_final_speed_violation_patch_exc}")
    except Exception:
        pass


if __name__ == "__main__":
    main()

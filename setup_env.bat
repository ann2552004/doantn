@echo off
chcp 65001 >nul
echo ============================================
echo  CAI DAT MOI TRUONG CHO HE THONG VSL
echo ============================================

cd /d "%~dp0"

echo [1/5] Kiem tra Python...
python --version
IF ERRORLEVEL 1 (
    echo Khong tim thay Python.
    echo Vui long cai Python 3.10 hoac 3.11 roi chay lai.
    pause
    exit /b
)

echo [2/5] Tao moi truong ao venv...
IF EXIST venv (
    echo Da ton tai venv, bo qua buoc tao moi.
) ELSE (
    python -m venv venv
)

echo [3/5] Kich hoat venv...
call venv\Scripts\activate.bat

echo [4/5] Nang cap pip...
python -m pip install --upgrade pip

echo [5/5] Cai dat thu vien...
pip install -r requirements.txt

echo.
echo ============================================
echo  CAI DAT XONG.
echo  Hay chay file run_demo.bat de mo chuong trinh.
echo ============================================
pause
@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo  CHAY DEMO HE THONG VSL
echo ============================================

IF NOT EXIST venv (
    echo Chua co moi truong venv.
    echo Vui long chay setup_env.bat truoc.
    pause
    exit /b
)

call venv\Scripts\activate.bat

echo.
echo Kiem tra cu phap file Python...
python -m py_compile doantn.py

IF ERRORLEVEL 1 (
    echo.
    echo File doantn.py dang co loi cu phap. Vui long kiem tra lai.
    pause
    exit /b
)

echo.
echo Thiet lap thong so chay demo...
set VSL_RUN_IMGSZ=640
set VSL_RUN_STRIDE=3
set VSL_RUN_CONF=0.30
set VSL_HCM_ROI_LENGTH_M=200

echo.
echo Dang khoi dong chuong trinh...
python doantn.py

pause

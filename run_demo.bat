@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul

echo ============================================
echo  CHAY DEMO HE THONG VSL
echo ============================================

set "PROJECT_DIR=%CD%"
set "VENV_PY=%CD%\venv\Scripts\python.exe"
set "QT_REPAIRED="

if not exist "%PROJECT_DIR%\doantn.py" goto :missing_source
call :ensure_venv
if errorlevel 1 goto :environment_failed

:configure_qt
set "QT_PLUGIN_PATH="
set "QT_QPA_PLATFORM_PLUGIN_PATH="
set "QT_QPA_PLATFORM="

for /f "usebackq delims=" %%P in (`"%VENV_PY%" -c "import PyQt5; from pathlib import Path; print(Path(PyQt5.__file__).resolve().parent / 'Qt5' / 'plugins')"`) do set "QT_PLUGIN_PATH=%%P"
if not defined QT_PLUGIN_PATH goto :repair_environment
set "QT_QPA_PLATFORM_PLUGIN_PATH=%QT_PLUGIN_PATH%\platforms"
set "QT_QPA_PLATFORM=windows"

if not exist "%QT_QPA_PLATFORM_PLUGIN_PATH%\qwindows.dll" goto :repair_environment

echo Python dang dung:
"%VENV_PY%" -c "import sys; print(sys.executable)"
echo Qt PluginsPath:
"%VENV_PY%" -c "from PyQt5 import QtCore, QtGui, QtWidgets; from PyQt5.QtCore import QLibraryInfo; print(QLibraryInfo.location(QLibraryInfo.PluginsPath))"
if errorlevel 1 goto :repair_environment

echo Kiem tra QApplication...
"%VENV_PY%" -c "import sys; from PyQt5.QtWidgets import QApplication; app=QApplication(sys.argv); print('QAPPLICATION_OK'); app.quit()"
if errorlevel 1 goto :repair_environment

echo.
echo Thiet lap thong so chay demo...
set "VSL_RUN_IMGSZ=640"
set "VSL_RUN_STRIDE=3"
set "VSL_RUN_CONF=0.30"
set "VSL_HCM_ROI_LENGTH_M=200"

echo.
echo Dang khoi dong chuong trinh...
"%VENV_PY%" "%PROJECT_DIR%\doantn.py"
set "APP_EXIT=%errorlevel%"
if not "%APP_EXIT%"=="0" (
    echo.
    echo Chuong trinh ket thuc voi ma loi %APP_EXIT%.
    echo Python: %VENV_PY%
    echo QT_PLUGIN_PATH: %QT_PLUGIN_PATH%
    echo QT_QPA_PLATFORM_PLUGIN_PATH: %QT_QPA_PLATFORM_PLUGIN_PATH%
)
pause
exit /b %APP_EXIT%

:ensure_venv
if exist "%VENV_PY%" (
    "%VENV_PY%" -c "import sys; print(sys.executable)" >nul 2>&1
    if not errorlevel 1 (
        "%VENV_PY%" -c "import cv2, numpy, torch, ultralytics, PyQt5" >nul 2>&1
        if not errorlevel 1 exit /b 0
    )
)
echo Venv chua co hoac bi hong. Dang chay setup_env.bat...
call "%PROJECT_DIR%\setup_env.bat"
if errorlevel 1 exit /b 1
if not exist "%VENV_PY%" exit /b 1
"%VENV_PY%" -c "import sys; print(sys.executable)" >nul 2>&1
if errorlevel 1 exit /b 1
"%VENV_PY%" -c "import cv2, numpy, torch, ultralytics, PyQt5" >nul 2>&1
if errorlevel 1 exit /b 1
exit /b 0

:repair_environment
if defined QT_REPAIRED goto :qt_startup_failed
set "QT_REPAIRED=1"
echo Qt/PyQt5 chua san sang. Dang chay lai setup_env.bat...
call "%PROJECT_DIR%\setup_env.bat"
if errorlevel 1 goto :environment_failed
goto :configure_qt

:missing_source
echo Khong tim thay doantn.py trong thu muc project.
goto :stop
:environment_failed
echo Khong the tao hoac kiem tra venv.
goto :stop
:qt_startup_failed
echo Khong the khoi tao PyQt5/QApplication.
echo Python: %VENV_PY%
echo QT_PLUGIN_PATH: %QT_PLUGIN_PATH%
echo QT_QPA_PLATFORM_PLUGIN_PATH: %QT_QPA_PLATFORM_PLUGIN_PATH%
goto :stop
:stop
pause
exit /b 1

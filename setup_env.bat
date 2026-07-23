@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul

echo ============================================
echo  CAI DAT MOI TRUONG CHO HE THONG VSL
echo ============================================

set "PROJECT_DIR=%CD%"
set "VENV_PY=%PROJECT_DIR%\venv\Scripts\python.exe"
set "PYTHON_CMD="

echo [1/6] Tim Python phu hop...
call :select_python
if errorlevel 1 goto :python_missing
echo Python duoc chon: %PYTHON_CMD%

echo [2/6] Kiem tra moi truong ao...
if exist "%VENV_PY%" (
    "%VENV_PY%" -c "import pathlib, sys; raise SystemExit(0 if sys.prefix != sys.base_prefix and pathlib.Path(sys.base_prefix).exists() else 1)" >nul 2>&1
    if errorlevel 1 (
        echo Venv hien tai bi hong hoac khong con Python goc. Dang tao lai...
        call :remove_venv
        if errorlevel 1 goto :venv_remove_failed
    )
)
if exist "%PROJECT_DIR%\venv" if not exist "%VENV_PY%" (
    echo Venv khong day du. Dang xoa de tao lai...
    call :remove_venv
    if errorlevel 1 goto :venv_remove_failed
)

if not exist "%VENV_PY%" (
    echo Tao venv bang %PYTHON_CMD% ...
    %PYTHON_CMD% -m venv "%PROJECT_DIR%\venv"
    if errorlevel 1 goto :venv_create_failed
)

"%VENV_PY%" -c "import sys; print(sys.executable)"
if errorlevel 1 goto :venv_invalid

call venv\Scripts\activate.bat
if errorlevel 1 goto :venv_invalid

echo [3/6] Nang cap pip, setuptools, wheel...
"%VENV_PY%" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 goto :pip_upgrade_failed

echo [4/6] Cai dat requirements.txt...
"%VENV_PY%" -m pip install -r "%PROJECT_DIR%\requirements.txt"
if errorlevel 1 goto :requirements_failed

echo [5/6] Kiem tra PyQt5 va qwindows.dll...
set "QT_PLUGIN_PATH="
set "QT_QPA_PLATFORM_PLUGIN_PATH="
set "QT_QPA_PLATFORM="
call :validate_pyqt
if errorlevel 1 (
    echo qwindows.dll dang thieu. Dang cai lai bo PyQt5...
    "%VENV_PY%" -m pip uninstall -y PyQt5 PyQt5-Qt5 PyQt5-sip
    if errorlevel 1 goto :pyqt_uninstall_failed
    "%VENV_PY%" -m pip install --no-cache-dir --force-reinstall PyQt5==5.15.11 PyQt5-Qt5==5.15.18 PyQt5-sip
    if errorlevel 1 (
        echo PyQt5-Qt5 5.15.18 khong co ban Windows tren index hien tai. Dung ban Windows tuong thich 5.15.2...
        "%VENV_PY%" -m pip install --no-cache-dir --force-reinstall PyQt5==5.15.11 PyQt5-Qt5==5.15.2 PyQt5-sip
        if errorlevel 1 goto :pyqt_install_failed
    )
    call :validate_pyqt
    if errorlevel 1 goto :qwindows_missing
)

echo [6/6] Kiem tra QApplication...
set "QT_PLUGIN_PATH="
set "QT_QPA_PLATFORM_PLUGIN_PATH="
set "QT_QPA_PLATFORM=windows"
for /f "usebackq delims=" %%P in (`"%VENV_PY%" -c "import PyQt5; from pathlib import Path; print(Path(PyQt5.__file__).resolve().parent / 'Qt5' / 'plugins')"`) do set "QT_PLUGIN_PATH=%%P"
if not defined QT_PLUGIN_PATH goto :qwindows_missing
set "QT_QPA_PLATFORM_PLUGIN_PATH=%QT_PLUGIN_PATH%\platforms"
if not exist "%QT_QPA_PLATFORM_PLUGIN_PATH%\qwindows.dll" goto :qwindows_missing
"%VENV_PY%" -c "import sys; from PyQt5.QtWidgets import QApplication; app=QApplication(sys.argv); print('QAPPLICATION_OK'); app.quit()"
if errorlevel 1 goto :qapplication_failed

echo.
echo CAI DAT VA KIEM TRA MOI TRUONG THANH CONG.
exit /b 0

:select_python
py -3.11 -c "import sys; print(sys.executable)" >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=py -3.11"
    exit /b 0
)
py -3.10 -c "import sys; print(sys.executable)" >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=py -3.10"
    exit /b 0
)
py -c "import sys; print(sys.executable)" >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=py"
    exit /b 0
)
python -c "import sys; print(sys.executable)" >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=python"
    exit /b 0
)
exit /b 1

:remove_venv
if exist "%PROJECT_DIR%\venv" rmdir /s /q "%PROJECT_DIR%\venv"
if exist "%PROJECT_DIR%\venv" exit /b 1
exit /b 0

:validate_pyqt
"%VENV_PY%" -c "import PyQt5; from pathlib import Path; from PyQt5 import QtCore, QtGui, QtWidgets; p=Path(PyQt5.__file__).resolve().parent/'Qt5'/'plugins'/'platforms'/'qwindows.dll'; print('PluginsPath=', QtCore.QLibraryInfo.location(QtCore.QLibraryInfo.PluginsPath)); print('qwindows.dll=', p); raise SystemExit(0 if p.exists() else 1)"
exit /b %errorlevel%

:python_missing
echo Khong tim thay Python 3.11, 3.10, py hoac python.
goto :fail
:venv_remove_failed
echo Khong the xoa venv cu. Hay dong cac chuong trinh dang su dung venv roi thu lai.
goto :fail
:venv_create_failed
echo Tao venv that bai.
goto :fail
:venv_invalid
echo Python trong venv khong chay duoc.
goto :fail
:pip_upgrade_failed
echo Nang cap pip/setuptools/wheel that bai.
goto :fail
:requirements_failed
echo Cai requirements.txt that bai.
goto :fail
:pyqt_uninstall_failed
echo Go bo PyQt5 that bai.
goto :fail
:pyqt_install_failed
echo Cai lai PyQt5 that bai.
goto :fail
:qwindows_missing
echo qwindows.dll van thieu sau khi cai lai PyQt5.
goto :fail
:qapplication_failed
echo Khong the khoi tao QApplication.
goto :fail

:fail
echo.
echo SETUP THAT BAI. Ma loi: %errorlevel%
pause
exit /b 1

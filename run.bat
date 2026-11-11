@echo off
REM Khoi dong Tro ly ao Giao vien tren Windows (nhap dup de chay)
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Tao moi truong ao Python .venv ...
  py -3 -m venv .venv 2>nul || python -m venv .venv
  if errorlevel 1 (
    echo Khong tim thay Python. Hay cai Python 3.11+ tu https://www.python.org/downloads/ va tick "Add python.exe to PATH".
    pause
    exit /b 1
  )
)
call ".venv\Scripts\activate.bat"

echo [2/3] Cai dat / cap nhat thu vien ...
python -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
  echo Cai thu vien that bai. Kiem tra ket noi mang roi chay lai.
  pause
  exit /b 1
)

if not exist ".env" copy ".env.example" ".env" >nul

echo [3/3] May chu dang chay tai http://localhost:8000  (nhan Ctrl+C de dung)
start "" http://localhost:8000
python -m uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
pause

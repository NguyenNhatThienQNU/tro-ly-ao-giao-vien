#!/usr/bin/env bash
# Khởi động Trợ lý ảo Giáo viên trên macOS/Linux
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "[1/3] Tạo môi trường ảo .venv ..."
  python3 -m venv .venv
fi
source .venv/bin/activate
echo "[2/3] Cài đặt thư viện ..."
python -m pip install --disable-pip-version-check -q -r requirements.txt
[ -f .env ] || cp .env.example .env
echo "[3/3] Máy chủ chạy tại http://localhost:8000 (Ctrl+C để dừng)"
exec python -m uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000

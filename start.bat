@echo off
chcp 65001 >nul
title Shaltot Suite
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [!] البيئة الافتراضية غير موجودة. جارٍ إنشاؤها...
    python -m venv .venv
    .venv\Scripts\python.exe -m pip install --upgrade pip
    .venv\Scripts\python.exe -m pip install -r backend\requirements.txt
)

if not exist "frontend\dist\index.html" (
    echo [!] الواجهة غير مبنية. جارٍ بناؤها...
    pushd frontend
    call npm install
    call npm run build
    popd
)

if not exist ".env" (
    echo.
    echo [!] ملف .env غير موجود.
    echo     انسخ .env.example باسم .env وضع فيه مفتاح Anthropic
    echo     وإلا ستعمل الأداة بدون ترجمة حقيقية.
    echo.
)

echo.
echo   Shaltot Suite
echo   http://127.0.0.1:8756
echo   اضغط Ctrl+C للإيقاف
echo.

start "" http://127.0.0.1:8756
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8756

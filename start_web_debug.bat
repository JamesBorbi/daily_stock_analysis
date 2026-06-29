@echo off
cd /d d:\code\daily_stock_analysis
echo [%date% %time%] Starting DSA with debug logging...
"C:\Users\Anthony\.workbuddy\binaries\python\versions\3.14.3\python.exe" -m uvicorn server:app --host 127.0.0.1 --port 8000 --log-level debug --reload
pause

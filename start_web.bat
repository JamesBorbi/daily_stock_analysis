@echo off
cd /d d:\code\daily_stock_analysis
title DSA Web Server
echo ============================================
echo   Daily Stock Analysis - Web Server
echo ============================================
echo.
echo Starting server...
echo.
C:\Users\Anthony\.workbuddy\binaries\python\versions\3.14.3\python.exe scripts\start_server.py 8000
echo.
echo Opening http://127.0.0.1:8000 ...
start http://127.0.0.1:8000
echo.
echo To stop the server, run:   taskkill /F /PID (PID from logs)
echo Or restart your computer.
echo.
pause

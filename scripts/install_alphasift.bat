@echo off
cd /d d:\code\daily_stock_analysis
echo Installing AlphaSift...
"C:\Users\Anthony\.workbuddy\binaries\python\versions\3.14.3\python.exe" -m pip install git+https://github.com/ZhuLinsen/alphasift.git@377049857cc04175dc3cca62121ee41adec6cdb8#egg=alphasift > logs\install_alphasift.log 2>&1
echo Exit code: %ERRORLEVEL%
if %ERRORLEVEL% equ 0 (
    echo AlphaSift installed successfully!
) else (
    echo Installation FAILED. Check logs\install_alphasift.log for details.
)
pause

@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -c "import uiautomation, win32gui" 2>nul
if errorlevel 1 (
  echo Installing dependencies...
  python -m pip install -r requirements.txt
)
echo Starting taskbar numbers...
python taskbar_numbers.py
pause
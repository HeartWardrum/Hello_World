@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Gamer520-Protocol-Launch.ps1" %*
set ERR=%ERRORLEVEL%
if %ERR% neq 0 timeout /t 5 >nul
exit /b %ERR%

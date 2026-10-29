@echo off
chcp 65001 >nul
title FlClash 手动更新
echo 正在检查 FlClash 更新...
echo 有新版本时只会确认一次，随后自动：退出 / 安装 / 删旧版 / 启动新版
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Update-FlClash.ps1" -ForcePrompt
set ERR=%ERRORLEVEL%
echo.
if %ERR% neq 0 (
  echo 更新失败，退出码 %ERR%。详见同目录 update.log
  pause
  exit /b %ERR%
)
echo 完成。
pause

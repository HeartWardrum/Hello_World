@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if "%~1"=="" (
  echo.
  echo 用法: Gamer520-BaiduDownload.cmd "https://www.gamer520.com/xxxxx.html"
  echo.
  echo 说明: 直接解析网盘地址并唤起百度客户端，不用在网页点「立即下载」，也就没有验证码。
  echo.
  set /p "URL=请粘贴文章网址: "
) else (
  set "URL=%~1"
)

if "%URL%"=="" (
  echo 未提供网址。
  exit /b 1
)

echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Gamer520-BaiduDownload.ps1" -Url "%URL%" %2 %3 %4 %5
set ERR=%ERRORLEVEL%
echo.
if %ERR% neq 0 (
  echo [失败] 退出码 %ERR%
  pause
  exit /b %ERR%
)
echo [完成] 看百度网盘是否弹出分享提示；不要去网页填验证码。
pause
exit /b 0

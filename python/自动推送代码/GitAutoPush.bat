@echo off
:: 【配置】将这里换成你本地 Git 仓库的绝对路径
cd /d "D:\projects\my-repo"

:: 检查是否有文件变动
git status --porcelain | findstr /R "." >nul
if %errorlevel% equ 0 (
    :: 获取当前时间
    set CURRENT_TIME=%date% %time%
    
    :: 执行 Git 命令
    git add .
    git commit -m "Auto-commit: %CURRENT_TIME%"
    git push origin main
    
    echo [%CURRENT_TIME%] Success.
) else (
    echo No changes detected.
)
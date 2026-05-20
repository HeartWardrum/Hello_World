@echo off
:: 支持中文防止乱码
chcp 65001 >nul

:: ==========================================
:: 【配置】把你所有的 Git 仓库绝对路径写在下面，用双引号包裹
:: ==========================================
for %%G in (
    "D:\projects\my-repo-1"
    "D:\projects\my-repo-2"
    "E:\notes\my-markdown-notes"
) do (
    
    :: 进入对应的仓库目录
    cd /d "%%G" 2>nul
    
    if exist "%%G\.git" (
        :: 检查是否有文件变动
        git status --porcelain | findstr /R "." >nul
        if %errorlevel% equ 0 (
            
            :: 【核心修复】获取当前时间，并将上午 10 点前可能出现的空格替换为 0
            set "CUR_TIME=%time: =0%"
            
            :: 重新拼接成干净的时间格式 (例如: 2026-05-20_17:35:00)
            set "COMMIT_MSG=Auto-commit: %date:~0,10%_%CUR_TIME:~0,8%"
            
            :: 执行 Git 推送
            git add .
            git commit -m "%COMMIT_MSG%"
            git push origin main
        )
    )
)
exit
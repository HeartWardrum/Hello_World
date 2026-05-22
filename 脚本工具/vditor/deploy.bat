@echo off
chcp 65001 >nul
title Markdown知识库部署工具

echo ========================================
echo   Markdown 知识库 - 自动部署脚本
echo ========================================
echo.

:: 检查 Node.js
where node >nul 2>nul
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Node.js，请先安装 Node.js
    echo 下载地址: https://nodejs.org/
    pause
    exit /b 1
)

:: 显示 Node 版本
echo [✓] Node.js 版本: 
node -v
echo.

:: 检查 package.json
if not exist "package.json" (
    echo [!] 未找到 package.json，正在初始化...
    call npm init -y
    echo [✓] 初始化完成
)

:: 安装依赖
echo [→] 正在安装依赖...
call npm install express cors
echo [✓] 依赖安装完成

:: 创建目录结构
echo [→] 创建目录结构...
if not exist "public" mkdir public
echo [✓] 目录创建完成

:: 检查并移动 index.html
if exist "index.html" (
    if not exist "public\index.html" (
        echo [→] 移动 index.html 到 public 目录...
        move index.html public\index.html >nul
    )
)

:: 检查并移动 server.js
if not exist "server.js" (
    echo [错误] 未找到 server.js 文件！
    echo 请将 server.js 放在当前目录后重新运行
    pause
    exit /b 1
)

:: 启动服务
echo.
echo ========================================
echo   ✨ 部署完成！✨
echo ========================================
echo.
echo 访问地址: http://localhost:3000
echo.
echo 按 Ctrl+C 停止服务
echo ========================================
echo.

:: 启动服务器
node server.js

pause
@echo off
chcp 65001 >nul
title FlClash 检查更新
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Update-FlClash.ps1" -ForcePrompt
if errorlevel 1 pause

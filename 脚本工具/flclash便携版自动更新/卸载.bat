@echo off
chcp 65001 >nul
title FlClash 卸载自动更新
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Uninstall-FlClashUpdater.ps1"
if errorlevel 1 pause

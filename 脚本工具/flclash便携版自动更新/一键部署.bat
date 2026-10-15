@echo off
chcp 65001 >nul
title FlClash 一键部署
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-FlClashUpdater.ps1"
if errorlevel 1 pause

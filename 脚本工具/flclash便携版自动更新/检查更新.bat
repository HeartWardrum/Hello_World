@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Update-FlClash.ps1" -ForcePrompt
if errorlevel 1 pause

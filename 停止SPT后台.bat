@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" exit /b 0
start "" ".venv\Scripts\pythonw.exe" -m windows.runtime --stop
exit /b 0

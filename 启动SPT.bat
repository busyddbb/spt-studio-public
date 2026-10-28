@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist ".venv\Scripts\pythonw.exe" goto missing
".venv\Scripts\python.exe" -c "import playwright" >nul 2>&1
if errorlevel 1 goto missing
start "" ".venv\Scripts\pythonw.exe" "%~dp0启动.py" %*
exit /b 0
:missing
echo 请先双击「安装Windows.bat」，安装本地运行组件和浏览器，再打开 SPT。
pause
exit /b 1

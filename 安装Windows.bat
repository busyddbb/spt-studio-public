@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
if exist ".venv\Scripts\python.exe" goto install
py -3 -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>&1
if not errorlevel 1 goto usepy
python -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>&1
if not errorlevel 1 goto usepython
echo 请先从 https://www.python.org/downloads/windows/ 安装 Python 3.11 或更新版本。
echo 安装时勾选 Add python.exe to PATH，然后重新运行本文件。
pause
exit /b 1
:usepy
py -3 -m venv .venv
if errorlevel 1 goto failed
goto install
:usepython
python -m venv .venv
if errorlevel 1 goto failed
:install
".venv\Scripts\python.exe" -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>&1
if errorlevel 1 goto oldvenv
".venv\Scripts\python.exe" -m pip install -r requirements-windows.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -c "import pathlib,shutil,sys,imageio_ffmpeg; shutil.copy2(imageio_ffmpeg.get_ffmpeg_exe(),pathlib.Path(sys.executable).with_name('ffmpeg.exe'))"
if errorlevel 1 goto failed
echo 安装完成。双击「启动SPT.bat」即可使用。
echo 第一次请在 SPT 的平台入口中自行登录自己的账号。安装包不附带任何登录资料。
pause
exit /b 0
:oldvenv
echo 现有 .venv 的 Python 版本过旧。请把本软件解压到新文件夹后，用 Python 3.11 或更新版本重新安装。
pause
exit /b 1
:failed
echo 安装未完成，请检查上面的错误与网络后重新运行。
pause
exit /b 1

@echo off
setlocal
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python tools\camera_probe.py --max-index 8
pause

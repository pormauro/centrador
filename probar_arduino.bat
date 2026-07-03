@echo off
setlocal
cd /d "%~dp0"
call .venv\Scripts\activate.bat
set /p COMPORT=Puerto COM del Arduino, ej COM3: 
python tools\serial_manual_test.py --port %COMPORT%
pause

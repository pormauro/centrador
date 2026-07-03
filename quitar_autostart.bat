@echo off
setlocal
set TASK_NAME=CentradorCorrugadora
schtasks /Delete /TN "%TASK_NAME%" /F
pause

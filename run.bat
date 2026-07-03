@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (
  echo Falta instalar. Ejecuta install.bat primero.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
python -m centrador.main --config config\config.yaml

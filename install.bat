@echo off
setlocal
cd /d "%~dp0"

echo =============================================
echo Instalando Centrador Corrugadora
echo =============================================

set "PYTHON_CMD="

python --version >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_CMD=python"
)

if "%PYTHON_CMD%"=="" (
  py -3.12 --version >nul 2>nul
  if not errorlevel 1 (
    set "PYTHON_CMD=py -3.12"
  )
)

if "%PYTHON_CMD%"=="" (
  py -3.11 --version >nul 2>nul
  if not errorlevel 1 (
    set "PYTHON_CMD=py -3.11"
  )
)

if "%PYTHON_CMD%"=="" (
  py -3.10 --version >nul 2>nul
  if not errorlevel 1 (
    set "PYTHON_CMD=py -3.10"
  )
)

if "%PYTHON_CMD%"=="" (
  py -3 --version >nul 2>nul
  if not errorlevel 1 (
    set "PYTHON_CMD=py -3"
  )
)

if "%PYTHON_CMD%"=="" (
  echo ERROR: No encuentro Python.
  echo Instala Python 3.10+ desde python.org y marca "Add python.exe to PATH".
  pause
  exit /b 1
)

echo Usando Python:
%PYTHON_CMD% --version

if exist .venv (
  echo Eliminando entorno virtual anterior...
  rmdir /s /q .venv
)

echo Creando entorno virtual...
%PYTHON_CMD% -m venv .venv
if errorlevel 1 (
  echo ERROR creando entorno virtual.
  pause
  exit /b 1
)

call .venv\Scripts\activate.bat

echo Actualizando pip...
python -m pip install --upgrade pip
if errorlevel 1 (
  echo ERROR actualizando pip.
  pause
  exit /b 1
)

echo Instalando dependencias...
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo ERROR instalando dependencias.
  pause
  exit /b 1
)

if not exist config\config.yaml (
  copy config\config.example.yaml config\config.yaml
)

echo.
echo Instalacion completa.
echo.
echo Proximo paso:
echo Ejecuta run_sin_arduino.bat para probar camara y calibrar sin mover la maquina.
echo.
pause
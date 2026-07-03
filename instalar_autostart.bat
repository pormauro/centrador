@echo off
setlocal
cd /d "%~dp0"
set TASK_NAME=CentradorCorrugadora
set APP_DIR=%~dp0

echo Creando tarea de inicio de sesion: %TASK_NAME%
schtasks /Create /TN "%TASK_NAME%" /SC ONLOGON /DELAY 0000:20 /RL HIGHEST /TR "cmd.exe /c cd /d \"%APP_DIR%\" ^&^& run.bat" /F
if errorlevel 1 (
  echo ERROR creando tarea. Ejecuta este .bat como Administrador.
  pause
  exit /b 1
)

echo OK. El centrador arrancara al iniciar sesion de Windows.
echo Para usarlo real, deja app.auto_start_enabled=true en config\config.yaml luego de calibrar.
pause

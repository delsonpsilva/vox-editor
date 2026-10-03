@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo.
  echo  O programa ainda nao foi instalado. Rode primeiro o INSTALAR.bat
  echo.
  pause
  exit /b
)
rem Abre o programa na janela propria, sem a janela preta
start "" ".venv\Scripts\pythonw.exe" -m backend.desktop

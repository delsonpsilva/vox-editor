@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Editor IA
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo  O Editor IA ainda nao foi instalado. Rode primeiro o INSTALAR.bat
  echo.
  pause
  exit /b
)
".venv\Scripts\python.exe" -m backend.app
pause

@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Editor IA (modo navegador)
rem Modo antigo, pelo navegador e com a janela preta mostrando o que acontece. Use se a janela propria nao abrir.
if not exist ".venv\Scripts\python.exe" (
  echo  O programa ainda nao foi instalado. Rode o INSTALAR.bat
  pause
  exit /b
)
".venv\Scripts\python.exe" -m backend.app
pause

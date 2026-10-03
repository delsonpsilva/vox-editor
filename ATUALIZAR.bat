@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Atualizar
if not exist ".venv\Scripts\python.exe" (
  echo  O programa ainda nao foi instalado. Rode o INSTALAR.bat
  pause
  exit /b
)
echo.
echo  Feche o programa antes de continuar (se estiver aberto).
echo.
pause
echo  [1/3] Atualizando as bibliotecas (janela propria, baixador de videos)...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\python.exe" -m pip install -r requirements.txt --quiet
if errorlevel 1 (
  echo  Algo falhou ao atualizar. Verifique a internet e rode de novo.
  pause
  exit /b
)
".venv\Scripts\python.exe" -m pip install --upgrade "yt-dlp[default]" --quiet
echo  [2/3] Conferindo o componente de janela do Windows (WebView2)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\webview2.ps1"
echo  [3/3] Atualizando o atalho na area de trabalho...
".venv\Scripts\python.exe" -m backend.desktop --atalho
echo.
echo  Pronto! Abra o programa pelo atalho na area de trabalho.
echo.
pause

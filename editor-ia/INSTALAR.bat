@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Instalador - Editor IA
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\instalar-windows.ps1"
pause

@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Limpar cache da tela
echo.
echo  Feche o VOX Editor antes de continuar.
echo  Isto apaga so o cache das paginas da janela (seus projetos, contas e configuracoes ficam).
echo.
pause
for /d %%P in ("dados\janela\EBWebView\*") do (
  if exist "%%P\Cache" rd /s /q "%%P\Cache"
  if exist "%%P\Code Cache" rd /s /q "%%P\Code Cache"
  if exist "%%P\GPUCache" rd /s /q "%%P\GPUCache"
  if exist "%%P\Service Worker" rd /s /q "%%P\Service Worker"
)
if exist "dados\janela\versao-da-tela.txt" del /q "dados\janela\versao-da-tela.txt"
echo.
echo  Pronto! Abra o VOX Editor pelo atalho.
echo.
pause
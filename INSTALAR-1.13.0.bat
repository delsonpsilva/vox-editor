@echo off
chcp 65001 >nul
cd /d "%~dp0"
title VOX Editor 1.13.0 - instalar no PC
echo.
echo  ==============================================
echo     VOX Editor 1.13.0 - copiar para C:\editor-ia
echo  ==============================================
echo.
set "DEST=C:\editor-ia"
if exist "%DEST%\backend\app.py" goto :achou
echo  Nao achei o VOX Editor em %DEST%.
set "DEST="
set /p "DEST= Digite a pasta do VOX Editor (ou so Enter para cancelar): "
if "%DEST%"=="" goto :fim
if not exist "%DEST%\backend\app.py" (
  echo  Essa pasta nao tem o VOX Editor. Nada foi copiado.
  goto :fim
)
:achou
if not exist "backend\core\montagem_som.py" (
  echo  Rode este arquivo de DENTRO da pasta extraida do .zip
  echo  ^(clique com o botao direito no .zip ^> Extrair tudo^).
  goto :fim
)
echo  Feche o VOX Editor antes de continuar.
pause
set "BK=%DEST%\dados\backup-antes-1.13.0"
echo  [1/2] Guardando copia dos arquivos que vao mudar em %BK% ...
if not exist "%BK%\backend\core" mkdir "%BK%\backend\core"
if not exist "%BK%\backend\rotas" mkdir "%BK%\backend\rotas"
if not exist "%BK%\frontend" mkdir "%BK%\frontend"
for %%F in (backend\app.py backend\core\montagem.py backend\rotas\montagem.py frontend\montagem.js frontend\style.css LEIA-ME.md COMO-ATUALIZAR.txt) do (
  if exist "%DEST%\%%F" copy /y "%DEST%\%%F" "%BK%\%%F" >nul
)
echo  [2/2] Copiando a versao 1.13.0...
xcopy /e /y /i /q "backend" "%DEST%\backend" >nul
xcopy /e /y /i /q "frontend" "%DEST%\frontend" >nul
xcopy /e /y /i /q "tests" "%DEST%\tests" >nul
copy /y "LEIA-ME.md" "%DEST%\" >nul
copy /y "COMO-ATUALIZAR.txt" "%DEST%\" >nul
findstr /c:"1.13.0" "%DEST%\backend\app.py" >nul
if errorlevel 1 (
  echo  Algo nao copiou certo. Rode este arquivo de novo.
  goto :fim
)
echo.
echo  ==============================================
echo   Pronto! VOX Editor 1.13.0 instalado em %DEST%
echo.
echo   1. Abra o programa (embaixo deve aparecer "versao 1.13.0")
echo      e teste a aba Montagem.
echo   2. Estando tudo certo: dois cliques no PUBLICAR.bat
echo   3. No terminal da VPS:  sudo vox-atualizar
echo.
echo   Se precisar desfazer: a copia antiga ficou em
echo   %BK%
echo  ==============================================
:fim
echo.
pause

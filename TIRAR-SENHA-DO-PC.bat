@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Tirar a senha do programa do PC - VOX Editor
echo.
echo  ==============================================
echo     Tirar a senha do programa do PC
echo  ==============================================
echo.
if not exist ".venv\Scripts\python.exe" (
  echo  Coloque este arquivo dentro da pasta C:\editor-ia e rode de novo.
  pause
  exit /b
)
echo  Isto tira a senha SO do programa do PC. A versao online nao muda.
echo  Seus projetos e configuracoes continuam como estao.
echo.
pause
".venv\Scripts\python.exe" -c "from backend.core import store; store.set_password(str()); print(not store.password_hash())" > "%TEMP%\vox_senha.txt" 2>&1
findstr /c:"True" "%TEMP%\vox_senha.txt" >nul
if errorlevel 1 (
  echo  Algo deu errado. Mande uma foto desta janela:
  type "%TEMP%\vox_senha.txt"
  pause
  exit /b
)
del "%TEMP%\vox_senha.txt" >nul 2>nul
echo  Senha do PC removida.
echo.
echo  Pronto! Feche e abra o VOX Editor: ele entra direto, sem senha.
echo  Se quiser uma senha nova: Configuracoes, parte "Senha do programa".
echo.
pause

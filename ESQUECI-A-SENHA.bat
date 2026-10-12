@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Esqueci a senha - VOX Editor
echo.
echo  ==============================================
echo     Esqueci a senha do programa do PC
echo  ==============================================
echo.
if not exist ".venv\Scripts\python.exe" (
  echo  Coloque este arquivo dentro da pasta C:\editor-ia e rode de novo.
  pause
  exit /b
)
echo  A senha do admin NESTE PC volta para a senha padrao: admin123
echo  (a versao online nao muda). No proximo acesso o programa pede uma senha nova.
echo.
pause
".venv\Scripts\python.exe" -c "from backend.core import store; from backend.app import SENHA_PADRAO as P; store.set_password(P); store.marcar_troca_de_senha(True); print(store.check_password(P))" > "%TEMP%\vox_senha.txt" 2>&1
findstr /c:"True" "%TEMP%\vox_senha.txt" >nul
if errorlevel 1 (
  echo  Algo deu errado. Mande uma foto desta janela:
  type "%TEMP%\vox_senha.txt"
  pause
  exit /b
)
del "%TEMP%\vox_senha.txt" >nul 2>nul
echo  Pronto! Abra o VOX Editor e entre com:
echo      Usuario: admin
echo      Senha:   admin123
echo  Em seguida ele pede para voce criar a sua senha nova.
echo.
pause

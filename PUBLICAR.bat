@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Publicar versao no GitHub - VOX Editor
echo.
echo  ==============================================
echo     Publicar esta versao no GitHub
echo  ==============================================
echo.
echo  Envia o CODIGO desta pasta para o GitHub. Seus projetos, videos,
echo  contas e chaves (pasta dados) NUNCA sao enviados.
echo.

where git >nul 2>nul
if errorlevel 1 goto :semgit

set "VER="
for /f "tokens=2 delims==" %%v in ('findstr /b /c:"VERSION = " backend\app.py') do set "VER=%%v"
set "VER=%VER:"=%"
set "VER=%VER: =%"
echo  Versao desta pasta: %VER%
echo.

if exist ".git" goto :identidade
echo  Primeira vez: vamos ligar esta pasta ao seu repositorio no GitHub.
echo  Antes, crie um repositorio PRIVADO e VAZIO em:  https://github.com/new
echo  (nao marque "Add a README file")
echo.
set "REPO="
set /p "REPO= Cole o endereco do repositorio (ex.: https://github.com/seunome/vox-editor): "
if "%REPO%"=="" goto :fim
git init -q -b main
git remote add origin "%REPO%"
echo.

:identidade
git config user.name >nul 2>nul
if errorlevel 1 goto :pedenome
:temnome
git config user.email >nul 2>nul
if errorlevel 1 goto :pedeemail
:tememail

echo  [1/3] Separando os arquivos do codigo...
git add -A
git diff --cached --quiet
if not errorlevel 1 (
  echo        Nada mudou desde a ultima publicacao.
  goto :enviar
)
echo.
set "DESC="
set /p "DESC= Descreva em poucas palavras o que mudou (ou so Enter, sem aspas): "
set "MSG=Versao %VER%"
if not "%DESC%"=="" set "MSG=Versao %VER% - %DESC%"
echo  [2/3] Registrando a versao...
git commit -q -m "%MSG%"
if errorlevel 1 (
  echo  Nao consegui registrar a versao.
  goto :fim
)

:enviar
echo  [3/3] Enviando para o GitHub...
echo        (na primeira vez abre uma janela para voce entrar na sua conta do GitHub)
git push -u origin main
if errorlevel 1 (
  echo.
  echo  Nao consegui enviar. Confira:
  echo   - a internet;
  echo   - se voce entrou na conta certa do GitHub na janela que abriu;
  echo   - se o repositorio foi criado VAZIO, sem README.
  goto :fim
)
echo.
echo  ==============================================
echo   Pronto! Versao %VER% publicada no GitHub.
echo.
echo   Agora, no terminal da VPS, rode:
echo       sudo vox-atualizar
echo  ==============================================
goto :fim

:pedenome
set "NOME="
set /p "NOME= Seu nome (aparece no historico das versoes): "
if "%NOME%"=="" set "NOME=VOX Editor"
git config user.name "%NOME%"
goto :temnome

:pedeemail
set "EMAIL="
set /p "EMAIL= Seu e-mail do GitHub: "
if "%EMAIL%"=="" set "EMAIL=sem-email@voxeditor"
git config user.email "%EMAIL%"
goto :tememail

:semgit
echo  O Git nao esta instalado neste computador (e ele que envia para o GitHub).
choice /c SN /m " Quer instalar agora"
if errorlevel 2 goto :fim
winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements
echo.
echo  Terminou. FECHE esta janela e abra o PUBLICAR.bat de novo.
goto :fim

:fim
echo.
pause

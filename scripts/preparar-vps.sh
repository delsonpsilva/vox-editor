#!/usr/bin/env bash
# VOX Editor — prepara a VPS UMA VEZ: liga a VPS ao repositório do GitHub (só leitura),
# baixa o código, instala o comando "vox-atualizar" e roda o instalador.
# Depois disso, para atualizar, basta:  sudo vox-atualizar
set -euo pipefail
if [ "$EUID" -ne 0 ]; then echo "Rode como root (ou com sudo)."; exit 1; fi

verde() { printf "\033[32m%s\033[0m\n" "$*"; }
amarelo() { printf "\033[33m%s\033[0m\n" "$*"; }
vermelho() { printf "\033[31m%s\033[0m\n" "$*"; }
passo() { echo; printf "\033[36m[%s] %s\033[0m\n" "$1" "$2"; }

BASE_DIR=/srv/voxeditor
APP_DIR=$BASE_DIR/app
CHAVE=/root/.ssh/voxeditor_github
APELIDO=github-voxeditor

echo
echo "=============================================="
echo "   VOX Editor — preparar a VPS (uma vez só)"
echo "=============================================="
echo
echo "Endereço do repositório no GitHub. Pode colar o link inteiro"
read -rp "(ex.: https://github.com/seunome/vox-editor): " REPO
REPO=$(echo "$REPO" | tr -d ' ' | sed -E 's#^(https?://)?(www\.)?github\.com[/:]##; s#^git@github\.com:##; s#\.git$##; s#/+$##')
if ! [[ "$REPO" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then vermelho "Não entendi o endereço: '$REPO'. Use o formato seunome/repositorio."; exit 1; fi
read -rp "Ramo (só aperte Enter) [main]: " RAMO; RAMO=${RAMO:-main}
if ! [[ "$RAMO" =~ ^[A-Za-z0-9._/-]+$ ]]; then amarelo "'$RAMO' não é um nome de ramo; usando main."; RAMO=main; fi

passo 1/4 "Conferindo o git..."
command -v git > /dev/null || { apt-get update -qq && apt-get install -y -qq git > /dev/null; }
verde "      OK - $(git --version)"

passo 2/4 "Criando a chave de acesso da VPS ao GitHub (só leitura)..."
mkdir -p /root/.ssh && chmod 700 /root/.ssh
[ -f "$CHAVE" ] || ssh-keygen -q -t ed25519 -N "" -C "vps-voxeditor" -f "$CHAVE"
if ! grep -q "Host $APELIDO" /root/.ssh/config 2>/dev/null; then
  cat >> /root/.ssh/config <<EOF

Host $APELIDO
    HostName github.com
    User git
    IdentityFile $CHAVE
    IdentitiesOnly yes
EOF
  chmod 600 /root/.ssh/config
fi
ssh-keyscan -t ed25519 github.com 2>/dev/null >> /root/.ssh/known_hosts
sort -u /root/.ssh/known_hosts -o /root/.ssh/known_hosts

testar() { ssh -o BatchMode=yes -o ConnectTimeout=10 -T "$APELIDO" 2>&1 | grep -q "successfully authenticated"; }
if ! testar || ! git ls-remote "$APELIDO:$REPO.git" > /dev/null 2>&1; then
  echo
  amarelo "  Falta autorizar esta VPS no GitHub. Faça assim:"
  echo "   1. Abra:  https://github.com/$REPO/settings/keys/new"
  echo "   2. Em \"Title\" escreva:  VPS"
  echo "   3. Em \"Key\" cole a linha abaixo (inteira):"
  echo
  printf "\033[1m%s\033[0m\n" "$(cat "$CHAVE.pub")"
  echo
  echo "   4. NÃO marque \"Allow write access\" (a VPS só precisa ler)."
  echo "   5. Clique em \"Add key\"."
  echo
  while true; do
    read -rp "Depois de adicionar, aperte Enter para eu testar... " _
    if git ls-remote "$APELIDO:$REPO.git" > /dev/null 2>&1; then break; fi
    vermelho "  Ainda não consegui acessar $REPO. Confira se colou a chave nesse repositório e tente de novo."
  done
fi
verde "      OK - a VPS consegue ler o repositório"

passo 3/4 "Baixando o código..."
if [ -z "$(git ls-remote --heads "$APELIDO:$REPO.git" "$RAMO")" ]; then
  vermelho "O repositório ainda não tem o ramo '$RAMO' (está vazio?)."
  vermelho "No PC, rode o PUBLICAR.bat até aparecer \"Pronto!\" e depois rode de novo:  bash /root/preparar-voxeditor.sh"
  exit 1
fi
mkdir -p "$BASE_DIR/dados" "$BASE_DIR/backups"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch -q origin "$RAMO" && git -C "$APP_DIR" reset -q --hard "origin/$RAMO"
else
  git clone -q --branch "$RAMO" "$APELIDO:$REPO.git" "$APP_DIR"
fi
cat > /etc/voxeditor.conf <<EOF
# VOX Editor — usado pelo comando vox-atualizar
APP_DIR=$APP_DIR
BASE_DIR=$BASE_DIR
RAMO=$RAMO
EOF
install -m 755 "$APP_DIR/scripts/vox-atualizar.sh" /usr/local/bin/vox-atualizar
verde "      OK - código em $APP_DIR, versão $(sed -n 's/^VERSION = "\(.*\)"/\1/p' "$APP_DIR/backend/app.py")"

passo 4/4 "Abrindo o instalador do editor..."
DADOS_DIR="$BASE_DIR/dados" bash "$APP_DIR/scripts/instalar-online.sh"

echo
verde "Tudo pronto. Para atualizar no futuro:  sudo vox-atualizar"

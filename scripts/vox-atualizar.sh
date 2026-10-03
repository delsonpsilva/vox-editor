#!/usr/bin/env bash
# VOX Editor — atualiza a versão online com a versão mais nova que está no GitHub.
#
#   sudo vox-atualizar            baixa a versão nova e troca (só se houver novidade)
#   sudo vox-atualizar --forcar   reconstrói mesmo sem novidade
#   sudo vox-atualizar --voltar   volta para a versão que estava antes da última atualização
#
# Antes de trocar, guarda uma cópia das configurações, contas e projetos (sem os vídeos).
# Se a versão nova não ligar, volta sozinho para a anterior.
set -euo pipefail
if [ "$EUID" -ne 0 ]; then echo "Rode com sudo:  sudo vox-atualizar"; exit 1; fi

verde() { printf "\033[32m%s\033[0m\n" "$*"; }
amarelo() { printf "\033[33m%s\033[0m\n" "$*"; }
vermelho() { printf "\033[31m%s\033[0m\n" "$*"; }
passo() { echo; printf "\033[36m[%s] %s\033[0m\n" "$1" "$2"; }

CONF=/etc/voxeditor.conf
[ -f "$CONF" ] || { vermelho "Não achei $CONF. O editor foi instalado pelo preparar-vps?"; exit 1; }
# shellcheck disable=SC1090
. "$CONF"   # APP_DIR, BASE_DIR, RAMO
APP_DIR=${APP_DIR:-/srv/voxeditor/app}; BASE_DIR=${BASE_DIR:-/srv/voxeditor}; RAMO=${RAMO:-main}
ENV="$APP_DIR/online/.env"
[ -f "$ENV" ] || { vermelho "O editor ainda não foi instalado (falta $ENV)."; exit 1; }
PORTA=$(sed -n 's/^PORTA=//p' "$ENV"); PORTA=${PORTA:-8765}
DADOS=$(sed -n 's/^DADOS=//p' "$ENV"); DADOS=${DADOS:-$APP_DIR/online/dados}
ANTERIOR_ARQ="$BASE_DIR/versao-anterior"
cd "$APP_DIR"

versao_de() { git show "$1:backend/app.py" 2>/dev/null | sed -n 's/^VERSION = "\(.*\)"/\1/p'; }
no_ar() { curl -s --max-time 4 "http://127.0.0.1:$PORTA/api/status" | sed -n 's/.*"version": *"\([^"]*\)".*/\1/p'; }

reconstruir() {
  bash "$APP_DIR/scripts/instalar-online.sh" --atualizar
}

esperar_versao() {  # espera o editor responder com a versão esperada (até 3 minutos)
  local quer="$1" v=""
  for _ in $(seq 1 90); do
    v=$(no_ar || true)
    [ -n "$v" ] && [ "$v" = "$quer" ] && return 0
    sleep 2
  done
  return 1
}

backup() {
  mkdir -p "$BASE_DIR/backups"
  local arq="$BASE_DIR/backups/dados-$(date +%Y%m%d-%H%M%S).tar.gz"
  # configurações, contas das redes, fila de publicações, marca e os arquivos .json dos projetos (sem os vídeos)
  ( cd "$DADOS" && find . \( -name '*.json' -o -path './marca/*' \) -type f -print0 \
      | tar --null -czf "$arq" -T - ) 2>/dev/null || true
  # guarda só as 10 cópias mais recentes
  ls -1t "$BASE_DIR"/backups/dados-*.tar.gz 2>/dev/null | tail -n +11 | xargs -r rm -f
  echo "      Cópia guardada: $arq"
}

autoatualizar() {  # se este próprio comando mudou na versão nova, troca (arquivo novo, sem mexer no que está rodando)
  install -m 755 "$APP_DIR/scripts/vox-atualizar.sh" /usr/local/bin/vox-atualizar.novo \
    && mv -f /usr/local/bin/vox-atualizar.novo /usr/local/bin/vox-atualizar
}

# ------------------------------------------------------------------ voltar
if [ "${1:-}" = "--voltar" ]; then
  [ -s "$ANTERIOR_ARQ" ] || { vermelho "Não há versão anterior guardada."; exit 1; }
  ALVO=$(cat "$ANTERIOR_ARQ")
  echo "Voltando para a versão $(versao_de "$ALVO") (agora está na $(versao_de HEAD))."
  read -rp "Confirmar? [s/N]: " C; [[ "${C:-n}" =~ ^[sS] ]] || exit 0
  passo 1/3 "Guardando cópia dos dados..."; backup
  passo 2/3 "Voltando o código..."
  git rev-parse HEAD > "$ANTERIOR_ARQ.tmp"
  git reset -q --hard "$ALVO"; mv -f "$ANTERIOR_ARQ.tmp" "$ANTERIOR_ARQ"
  passo 3/3 "Reconstruindo..."; reconstruir
  esperar_versao "$(versao_de HEAD)" && verde "Pronto! Voltou para a versão $(versao_de HEAD)." \
    || amarelo "O editor ainda não respondeu. Veja:  cd $APP_DIR/online && sudo docker compose logs --tail 50"
  autoatualizar
  exit 0
fi

# ------------------------------------------------------------------ atualizar
echo
echo "=============================================="
echo "   Atualizar o VOX Editor (versão online)"
echo "=============================================="

passo 1/5 "Procurando versão nova no GitHub..."
git fetch -q origin "$RAMO" || { vermelho "Não consegui falar com o GitHub. Confira a internet da VPS e a chave de acesso."; exit 1; }
ATUAL=$(git rev-parse HEAD); NOVA=$(git rev-parse "origin/$RAMO")
echo "      No ar:     versão $(versao_de "$ATUAL")  ($(git log -1 --format='%cd' --date=format:'%d/%m/%Y %H:%M' "$ATUAL"))"
echo "      No GitHub: versão $(versao_de "$NOVA")  ($(git log -1 --format='%cd' --date=format:'%d/%m/%Y %H:%M' "$NOVA"))"
if [ "$ATUAL" = "$NOVA" ] && [ "${1:-}" != "--forcar" ]; then
  verde "Já está na versão mais nova. Nada a fazer."
  exit 0
fi
if [ "$ATUAL" != "$NOVA" ]; then
  echo "      O que mudou:"
  git log --format='        - %s' "$ATUAL..$NOVA" | head -15
fi

passo 2/5 "Guardando cópia das configurações, contas e projetos (sem os vídeos)..."
backup

passo 3/5 "Trocando o código pela versão nova..."
git reset -q --hard "$NOVA"
verde "      OK"

passo 4/5 "Reconstruindo o container (o editor fica fora do ar só alguns segundos no fim)..."
if ! reconstruir; then
  vermelho "A construção falhou. Voltando para a versão anterior..."
  git reset -q --hard "$ATUAL"; reconstruir || true
  vermelho "Ficou na versão $(versao_de "$ATUAL"), que já funcionava. Nada foi perdido."
  exit 1
fi

passo 5/5 "Conferindo se a versão nova ligou..."
QUER=$(versao_de "$NOVA")
if esperar_versao "$QUER"; then
  # só agora, com a versão nova funcionando, ela passa a ter uma "anterior" para o --voltar
  if [ "$ATUAL" != "$NOVA" ]; then echo "$ATUAL" > "$ANTERIOR_ARQ"; fi
  autoatualizar
  echo
  verde "=============================================="
  verde "  Pronto! O editor está na versão $QUER."
  verde "=============================================="
  echo "  Se algo ficou estranho:  sudo vox-atualizar --voltar"
else
  vermelho "A versão nova não respondeu. Voltando para a anterior..."
  cd "$APP_DIR/online" && docker compose logs --tail 20 editor 2>/dev/null | sed 's/^/      /' || true
  cd "$APP_DIR"
  git reset -q --hard "$ATUAL"; reconstruir || true
  esperar_versao "$(versao_de "$ATUAL")" || true
  vermelho "Ficou na versão $(versao_de "$ATUAL"), que já funcionava. Me mande as linhas acima para eu corrigir."
  exit 1
fi

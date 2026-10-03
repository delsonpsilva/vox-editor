#!/usr/bin/env bash
# Instalador do Editor IA (versão online) para VPS Ubuntu/Debian — x86 ou ARM (Oracle Ampere).
# Rode dentro da pasta do projeto:  sudo bash scripts/instalar-vps.sh
set -e
cd "$(dirname "$0")/.."
DIR="$(pwd)"
if [ "$EUID" -ne 0 ]; then echo "Rode com sudo:  sudo bash scripts/instalar-vps.sh"; exit 1; fi
USUARIO="${SUDO_USER:-root}"

echo ""
echo "=== Instalação do Editor IA (online) ==="
echo ""
read -rp "Porta do painel [8765]: " PORTA; PORTA=${PORTA:-8765}
while true; do
  read -rsp "Crie uma senha de acesso ao painel: " SENHA; echo
  [ ${#SENHA} -ge 6 ] && break
  echo "A senha precisa ter pelo menos 6 caracteres."
done
read -rp "Tamanho máximo de envio em GB [10]: " MAXGB; MAXGB=${MAXGB:-10}
read -rp "Modelo de transcrição local (base/small/medium) [small]: " MODELO; MODELO=${MODELO:-small}

echo ""
echo "[1/5] Instalando pacotes do sistema (Python e FFmpeg)..."
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip ffmpeg > /dev/null

echo "[2/5] Criando ambiente Python e instalando bibliotecas..."
sudo -u "$USUARIO" python3 -m venv .venv
sudo -u "$USUARIO" .venv/bin/pip install --upgrade pip -q
sudo -u "$USUARIO" .venv/bin/pip install -r requirements.txt -q

echo "[3/5] Baixando o modelo de transcrição ($MODELO)..."
sudo -u "$USUARIO" mkdir -p dados/modelos
sudo -u "$USUARIO" .venv/bin/python -c "from faster_whisper import download_model; download_model('$MODELO', cache_dir='dados/modelos')" \
  || echo "   (não consegui baixar agora; será baixado no primeiro vídeo)"
sudo -u "$USUARIO" .venv/bin/python - <<EOF
import sys; sys.path.insert(0, "$DIR")
from backend.core import store
store.save_config({"transcription": {"local_model": "$MODELO"}})
EOF

echo "[4/5] Criando o serviço (liga sozinho quando a VPS reinicia)..."
SENHA_ESC=${SENHA//%/%%}; SENHA_ESC=${SENHA_ESC//\\/\\\\}; SENHA_ESC=${SENHA_ESC//\"/\\\"}
SEGREDO=$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')
cat > /etc/systemd/system/editor-ia.service <<EOF
[Unit]
Description=Editor IA
After=network.target

[Service]
User=$USUARIO
WorkingDirectory=$DIR
Environment=HOST=0.0.0.0
Environment=PORT=$PORTA
Environment="APP_PASSWORD=$SENHA_ESC"
Environment=APP_SECRET=$SEGREDO
Environment=MAX_UPLOAD_GB=$MAXGB
Environment=NO_BROWSER=1
ExecStart=$DIR/.venv/bin/python -m backend.app
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
chmod 600 /etc/systemd/system/editor-ia.service
systemctl daemon-reload
systemctl enable --now editor-ia > /dev/null 2>&1

echo "[5/5] Liberando a porta $PORTA no firewall..."
if command -v iptables > /dev/null; then
  iptables -C INPUT -p tcp --dport "$PORTA" -j ACCEPT 2>/dev/null || iptables -I INPUT 6 -p tcp --dport "$PORTA" -j ACCEPT
  command -v netfilter-persistent > /dev/null && netfilter-persistent save > /dev/null 2>&1 || true
fi
command -v ufw > /dev/null && ufw allow "$PORTA"/tcp > /dev/null 2>&1 || true

IP=$(curl -s -4 ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
sleep 2
echo ""
if systemctl is-active --quiet editor-ia; then
  echo "Pronto! Acesse:  http://$IP:$PORTA"
else
  echo "O serviço não iniciou. Veja o erro com:  sudo journalctl -u editor-ia -n 50"
fi
echo ""
echo "Na Oracle Cloud, libere também a porta $PORTA na 'Security List' da sua VCN (Ingress, TCP)."
echo "Comandos úteis:  sudo systemctl restart editor-ia   |   sudo journalctl -u editor-ia -f"
echo ""

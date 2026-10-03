#!/usr/bin/env bash
# Instalador da versão online em container (Docker), feito para rodar AO LADO de outros sistemas na mesma VPS.
# Pergunta tudo aqui no terminal e configura sozinho: container com limite de processador e memória,
# domínio com https (Caddy próprio, o Caddy em container de outro sistema, ou o Nginx/Apache que já existir)
# e senha de acesso.
#
#   Instalar:   sudo bash scripts/instalar-online.sh
#   Atualizar:  sudo bash scripts/instalar-online.sh --atualizar
set -euo pipefail
cd "$(dirname "$0")/.."
DIR="$(pwd)"
ON="$DIR/online"
if [ "$EUID" -ne 0 ]; then echo "Rode com sudo:  sudo bash scripts/instalar-online.sh"; exit 1; fi

verde() { printf "\033[32m%s\033[0m\n" "$*"; }
amarelo() { printf "\033[33m%s\033[0m\n" "$*"; }
vermelho() { printf "\033[31m%s\033[0m\n" "$*"; }
passo() { echo; printf "\033[36m[%s] %s\033[0m\n" "$1" "$2"; }

compose() { (cd "$ON" && docker compose "$@"); }
perfil() { grep -q '^MODO=caddy' "$ON/.env" 2>/dev/null && echo "--profile caddy" || true; }

# ---------------------------------------------------------------- atualizar
if [ "${1:-}" = "--atualizar" ]; then
  [ -f "$ON/.env" ] || { vermelho "Ainda não instalado. Rode sem --atualizar."; exit 1; }
  passo 1/2 "Reconstruindo o container com a versão nova..."
  # shellcheck disable=SC2046
  compose $(perfil) up -d --build
  passo 2/2 "Limpando imagens antigas..."
  docker image prune -f > /dev/null
  verde "Atualizado! Os projetos e as configurações foram mantidos."
  exit 0
fi

echo
echo "=============================================="
echo "   Instalação da versão online (container)"
echo "=============================================="
echo
NUCLEOS=$(nproc)
MEM_GB=$(awk '/MemTotal/ {printf "%d", $2/1024/1024}' /proc/meminfo)
echo "Esta VPS tem $NUCLEOS núcleos e ${MEM_GB} GB de memória."
echo "O editor vai usar só o limite que você escolher; o resto fica para os seus outros sistemas."
echo

read -rp "Domínio do painel (ex.: editor.seusite.com.br) — deixe vazio para usar só IP e porta: " DOMINIO
DOMINIO=$(echo "$DOMINIO" | tr -d ' ' | sed -E 's#^https?://##; s#/.*$##' | tr 'A-Z' 'a-z')
EMAIL=""
if [ -n "$DOMINIO" ]; then
  read -rp "Seu e-mail (para o certificado https, avisos de vencimento): " EMAIL
fi
while true; do
  read -rsp "Crie uma senha de acesso ao painel (mínimo 6 caracteres): " SENHA; echo
  if [ ${#SENHA} -lt 6 ]; then echo "A senha precisa ter pelo menos 6 caracteres."; continue; fi
  if [[ "$SENHA" == *"'"* ]]; then echo "Não use aspas simples ( ' ) na senha."; continue; fi
  read -rsp "Repita a senha: " SENHA2; echo
  [ "$SENHA" = "$SENHA2" ] && break
  echo "As senhas não conferem. Vamos de novo."
done
SUG_CPU=$(( NUCLEOS / 2 )); [ "$SUG_CPU" -lt 1 ] && SUG_CPU=1; [ "$SUG_CPU" -gt 4 ] && SUG_CPU=4
read -rp "Quantos núcleos o editor pode usar [$SUG_CPU]: " CPUS; CPUS=${CPUS:-$SUG_CPU}
SUG_MEM=$(( MEM_GB / 5 )); [ "$SUG_MEM" -lt 3 ] && SUG_MEM=3; [ "$SUG_MEM" -gt 6 ] && SUG_MEM=6
read -rp "Quantos GB de memória o editor pode usar [$SUG_MEM]: " MEMORIA; MEMORIA=${MEMORIA:-$SUG_MEM}
read -rp "Tamanho máximo de vídeo enviado, em GB [20]: " MAXGB; MAXGB=${MAXGB:-20}
DADOS="${DADOS_DIR:-}"
if [ -z "$DADOS" ] && [ -f "$ON/.env" ]; then DADOS=$(sed -n 's/^DADOS=//p' "$ON/.env"); fi
DADOS="${DADOS:-$ON/dados}"
echo "Pasta dos projetos e vídeos (fica fora do código; as atualizações não mexem nela): $DADOS"
PORTA=8765
while ss -ltnH "sport = :$PORTA" 2>/dev/null | grep -q .; do PORTA=$((PORTA + 1)); done
echo "Porta interna escolhida: $PORTA"

# ---------------------------------------------------------------- 1. Docker
passo 1/5 "Conferindo o Docker..."
if ! command -v docker > /dev/null; then
  amarelo "Docker não encontrado. Instalando (alguns minutos)..."
  curl -fsSL https://get.docker.com | sh > /dev/null
fi
if ! docker compose version > /dev/null 2>&1; then
  (apt-get install -y -qq docker-compose-plugin || dnf install -y -q docker-compose-plugin) > /dev/null 2>&1 || true
fi
docker compose version > /dev/null 2>&1 || { vermelho "Não consegui instalar o Docker Compose. Instale e rode de novo."; exit 1; }
systemctl enable --now docker > /dev/null 2>&1 || true
verde "      OK - $(docker --version)"
if [ "$(swapon --show --noheadings 2>/dev/null | wc -l)" -eq 0 ] && [ ! -f /swapfile ]; then
  echo "      A VPS está sem memória de reserva (swap). Criando 4 GB, para um pico de vídeo nunca derrubar os outros sistemas..."
  if fallocate -l 4G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=4096 status=none; then
    if chmod 600 /swapfile && mkswap /swapfile > /dev/null && swapon /swapfile; then
      grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
      sysctl -q vm.swappiness=10 || true
      grep -q '^vm.swappiness' /etc/sysctl.conf || echo 'vm.swappiness=10' >> /etc/sysctl.conf
      verde "      OK - swap de 4 GB ativo"
    else
      amarelo "      Não consegui ativar o swap (seguindo sem ele)."
    fi
  fi
fi

# ---------------------------------------------------------------- 2. Como publicar (https)
passo 2/5 "Vendo como publicar o painel na internet..."
dono() { ss -ltnpH "sport = :$1" 2>/dev/null | grep -o 'users:(("[^"]*' | head -1 | sed 's/users:(("//'; }
P80=$(dono 80); P443=$(dono 443)
# Outro sistema já tem um Caddy em container publicando a 443 (ex.: painel Vox)? Então o editor entra nele.
caddy_em_container() {
  local ct
  for ct in $(docker ps --format '{{.Names}} {{.Ports}}' | awk '/:443->/ {print $1}'); do
    if docker exec "$ct" caddy version > /dev/null 2>&1 \
       && [ -n "$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/etc/caddy/Caddyfile"}}{{.Source}}{{end}}{{end}}' "$ct")" ]; then
      echo "$ct"; return 0
    fi
  done
  return 1
}
CADDY_CT=""; CADDYFILE=""; REDE=""
MODO="porta"
if [ -n "$DOMINIO" ]; then
  if [ -z "$P80" ] && [ -z "$P443" ]; then MODO="caddy"
  elif CADDY_CT=$(caddy_em_container) && [ -n "$CADDY_CT" ]; then MODO="caddy-docker"
  elif [ "$P80" = "nginx" ] && { [ -d /etc/nginx/sites-enabled ] || [ -d /etc/nginx/conf.d ]; }; then MODO="nginx"
  elif [ "$P80" = "apache2" ] || [ "$P80" = "httpd" ]; then MODO="apache"
  else MODO="manual"
  fi
fi
case "$MODO" in
  caddy)  echo "      As portas 80/443 estão livres: o https será feito por um container próprio (Caddy)." ;;
  caddy-docker)
    CADDYFILE=$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/etc/caddy/Caddyfile"}}{{.Source}}{{end}}{{end}}' "$CADDY_CT")
    REDE=$(docker inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$CADDY_CT" | awk '{print $1}')
    echo "      Encontrei o Caddy do seu outro sistema (container '$CADDY_CT')."
    echo "      Vou só ACRESCENTAR o domínio no fim de $CADDYFILE, sem mudar nenhuma linha que já existe."
    echo "      Antes de valer, o próprio Caddy confere o arquivo; se der qualquer erro, nada é trocado." ;;
  nginx)  echo "      Encontrei o Nginx do seu outro sistema: vou só acrescentar o domínio nele, sem mexer no resto." ;;
  apache) echo "      Encontrei o Apache do seu outro sistema: vou só acrescentar o domínio nele, sem mexer no resto." ;;
  manual) amarelo "      As portas 80/443 já são usadas por '$P80' (painel ou proxy em container). Vou deixar o editor na porta $PORTA e explicar no fim como apontar o domínio." ;;
  porta)  echo "      Sem domínio: o painel fica em http://IP:$PORTA (sem https)." ;;
esac
IP=$(curl -s -4 --max-time 5 ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
if [ -n "$DOMINIO" ]; then
  DNS=$(getent ahostsv4 "$DOMINIO" 2>/dev/null | awk 'NR==1{print $1}')
  if [ "$DNS" != "$IP" ]; then
    amarelo "      Atenção: o domínio $DOMINIO aponta para '${DNS:-nada}', e esta VPS é $IP."
    amarelo "      Crie no DNS um registro A de $DOMINIO para $IP (o https só sai depois que isso valer)."
    read -rp "      Continuar mesmo assim? [s/N]: " C; [[ "${C:-n}" =~ ^[sS] ]] || exit 1
  fi
fi

# ---------------------------------------------------------------- 3. Configuração
passo 3/5 "Gravando a configuração..."
BIND=127.0.0.1
if [ "$MODO" = "porta" ] || [ "$MODO" = "manual" ]; then BIND=0.0.0.0; fi
rm -f "$ON/docker-compose.override.yml"
if [ "$MODO" = "caddy-docker" ]; then
  # o editor entra na mesma rede do Caddy do outro sistema, para o Caddy achar o editor pelo nome
  cat > "$ON/docker-compose.override.yml" <<EOF
# Gerado pelo instalador: liga o editor à rede do Caddy que já existia na VPS ($CADDY_CT).
services:
  editor:
    networks: [default, proxy]
networks:
  proxy:
    external: true
    name: $REDE
EOF
fi
URL="http://$IP:$PORTA"
if [ -n "$DOMINIO" ] && [ "$MODO" != "manual" ]; then URL="https://$DOMINIO"; fi
SEGREDO=$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 40)
umask 077
cat > "$ON/.env" <<EOF
# Gerado pelo instalador em $(date '+%d/%m/%Y %H:%M'). Para mudar, rode o instalador de novo.
MODO=$MODO
DOMINIO=${DOMINIO:-localhost}
PUBLIC_URL=$URL
APP_PASSWORD='$SENHA'
APP_SECRET=$SEGREDO
MAX_UPLOAD_GB=$MAXGB
PORTA=$PORTA
BIND=$BIND
CPUS=$CPUS
MEMORIA=${MEMORIA}g
DADOS=$DADOS
CADDY_CT=$CADDY_CT
CADDYFILE=$CADDYFILE
EOF
umask 022
mkdir -p "$DADOS" "$ON/caddy"
chown -R 1000:1000 "$DADOS"
verde "      OK - limite de $CPUS núcleos e ${MEMORIA} GB de memória"

# ---------------------------------------------------------------- 4. Container
passo 4/5 "Construindo e ligando o container (na primeira vez demora alguns minutos)..."
PERFIL=""; [ "$MODO" = "caddy" ] && PERFIL="--profile caddy"
# shellcheck disable=SC2086
compose $PERFIL up -d --build
for _ in $(seq 1 60); do curl -s -o /dev/null "http://127.0.0.1:$PORTA/api/status" && break; sleep 2; done
curl -s -o /dev/null "http://127.0.0.1:$PORTA/api/status" || { vermelho "O editor não respondeu. Veja:  cd $ON && docker compose logs --tail 50"; exit 1; }
verde "      OK - editor rodando"
echo "      Baixando o modelo de transcrição (~500 MB, só desta vez)..."
compose exec -T editor python -c "from faster_whisper import download_model; download_model('small', cache_dir='/dados/modelos')" > /dev/null 2>&1 \
  && verde "      OK - modelo pronto" || amarelo "      Não consegui baixar agora; ele será baixado no primeiro vídeo."

# ---------------------------------------------------------------- 5. Domínio e https
passo 5/5 "Configurando o acesso..."
certbot_instalar() {
  command -v certbot > /dev/null && return 0
  (apt-get install -y -qq certbot "$1" || dnf install -y -q certbot "$1") > /dev/null 2>&1 || snap install --classic certbot > /dev/null 2>&1 || true
  command -v certbot > /dev/null
}
case "$MODO" in
  nginx)
    CONF=/etc/nginx/conf.d/editor-ia.conf
    [ -d /etc/nginx/sites-enabled ] && CONF=/etc/nginx/sites-available/editor-ia
    cat > "$CONF" <<EOF
# Editor IA (container) — criado pelo instalador
server {
    listen 80;
    server_name $DOMINIO;
    client_max_body_size ${MAXGB}G;
    proxy_request_buffering off;
    proxy_buffering off;
    location / {
        proxy_pass http://127.0.0.1:$PORTA;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
EOF
    if [ -d /etc/nginx/sites-enabled ]; then ln -sf "$CONF" /etc/nginx/sites-enabled/editor-ia; fi
    if nginx -t > /dev/null 2>&1; then systemctl reload nginx; else vermelho "A configuração do Nginx deu erro (nginx -t). Nada foi recarregado."; rm -f "$CONF" /etc/nginx/sites-enabled/editor-ia; exit 1; fi
    if certbot_instalar python3-certbot-nginx; then
      certbot --nginx -d "$DOMINIO" --non-interactive --agree-tos -m "$EMAIL" --redirect > /dev/null 2>&1 \
        && verde "      OK - https ativo" || amarelo "      O certificado não saiu (o DNS já aponta para cá?). Depois rode:  sudo certbot --nginx -d $DOMINIO"
    else amarelo "      Instale o certbot e rode:  sudo certbot --nginx -d $DOMINIO"; fi
    ;;
  apache)
    A2=/etc/apache2/sites-available; [ -d "$A2" ] || A2=/etc/httpd/conf.d
    cat > "$A2/editor-ia.conf" <<EOF
# Editor IA (container) — criado pelo instalador
<VirtualHost *:80>
    ServerName $DOMINIO
    ProxyPreserveHost On
    ProxyTimeout 3600
    RequestHeader set X-Forwarded-Proto "http"
    ProxyPass / http://127.0.0.1:$PORTA/
    ProxyPassReverse / http://127.0.0.1:$PORTA/
    LimitRequestBody 0
</VirtualHost>
EOF
    if command -v a2enmod > /dev/null; then a2enmod -q proxy proxy_http headers > /dev/null; a2ensite -q editor-ia > /dev/null; fi
    if apachectl configtest > /dev/null 2>&1; then systemctl reload apache2 2>/dev/null || systemctl reload httpd; else vermelho "A configuração do Apache deu erro. Nada foi recarregado."; exit 1; fi
    if certbot_instalar python3-certbot-apache; then
      certbot --apache -d "$DOMINIO" --non-interactive --agree-tos -m "$EMAIL" --redirect > /dev/null 2>&1 \
        && verde "      OK - https ativo" || amarelo "      O certificado não saiu. Depois rode:  sudo certbot --apache -d $DOMINIO"
    else amarelo "      Instale o certbot e rode:  sudo certbot --apache -d $DOMINIO"; fi
    ;;
  caddy)
    echo "      O Caddy pede o certificado sozinho (leva até 1 minuto depois que o DNS aponta para cá)."
    ;;
  caddy-docker)
    COPIA="$CADDYFILE.antes-voxeditor-$(date +%Y%m%d-%H%M%S)"
    cp -p "$CADDYFILE" "$COPIA"
    NOVO=$(mktemp)
    # tira o bloco do editor de uma instalação anterior (se houver) e põe o novo no fim
    awk '/^# --- inicio VOX Editor ---$/{f=1} !f{print} /^# --- fim VOX Editor ---$/{f=0}' "$CADDYFILE" \
      | sed -e ':a' -e '/^\n*$/{$d;N;ba' -e '}' > "$NOVO"
    {
      echo
      echo "# --- inicio VOX Editor ---"
      echo "# Criado pelo instalador do VOX Editor. Para tirar o editor, apague daqui até a linha \"fim VOX Editor\"."
      echo "$DOMINIO {"
      printf '\tencode zstd gzip\n'
      printf '\treverse_proxy editor-ia:8765 {\n'
      printf '\t\tflush_interval -1\n'
      printf '\t\ttransport http {\n\t\t\tread_timeout 1h\n\t\t\twrite_timeout 1h\n\t\t}\n'
      printf '\t}\n'
      echo "}"
      echo "# --- fim VOX Editor ---"
    } >> "$NOVO"
    # 1) o Caddy confere uma CÓPIA; o arquivo que está no ar ainda não foi tocado
    docker cp "$NOVO" "$CADDY_CT:/tmp/Caddyfile.voxeditor" > /dev/null
    if ! docker exec "$CADDY_CT" caddy validate --config /tmp/Caddyfile.voxeditor --adapter caddyfile > /tmp/voxeditor-caddy.txt 2>&1; then
      vermelho "      O Caddy recusou a configuração nova. NADA foi alterado no seu outro sistema."
      tail -5 /tmp/voxeditor-caddy.txt; rm -f "$NOVO" "$COPIA"; exit 1
    fi
    # 2) grava por cima do MESMO arquivo (o container só enxerga o arquivo original, não um arquivo substituído)
    cat "$NOVO" > "$CADDYFILE"; rm -f "$NOVO"
    # 3) recarrega sem derrubar ninguém; se falhar, devolve o original na hora
    if docker exec "$CADDY_CT" caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile > /tmp/voxeditor-caddy.txt 2>&1; then
      verde "      OK - domínio acrescentado no Caddy, sem queda (cópia do original: $COPIA)"
      echo "      O certificado https sai sozinho em até 1 minuto, depois que o DNS apontar para cá."
    else
      cat "$COPIA" > "$CADDYFILE"
      docker exec "$CADDY_CT" caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile > /dev/null 2>&1 || true
      vermelho "      O Caddy não aceitou recarregar. O arquivo original foi devolvido e o outro sistema segue igual."
      tail -5 /tmp/voxeditor-caddy.txt; exit 1
    fi
    ;;
esac
if [ "$BIND" = "0.0.0.0" ]; then
  command -v ufw > /dev/null && ufw status | grep -q active && ufw allow "$PORTA"/tcp > /dev/null || true
fi

echo
verde "=============================================="
verde "  Pronto! Acesse:  $URL"
verde "=============================================="
if [ "$MODO" = "manual" ]; then
  echo
  amarelo "Para usar o domínio com https: no painel/proxy que já usa as portas 80/443 ($P80),"
  amarelo "crie um site para $DOMINIO apontando para  http://$IP:$PORTA  (ou http://172.17.0.1:$PORTA se o proxy for container)."
  amarelo "Depois rode este instalador de novo para gravar o endereço certo."
fi
echo
echo "Endereço para cadastrar nos apps das redes sociais (redirecionamento):"
echo "   $URL/api/oauth/youtube/callback   (troque youtube por meta ou tiktok)"
echo
echo "Comandos úteis:"
echo "   Atualizar para a versão nova do GitHub:    sudo vox-atualizar"
echo "   Ver o que está acontecendo:                cd $ON && sudo docker compose logs -f --tail 50"
echo "   Reiniciar:                                 cd $ON && sudo docker compose restart"
echo "   Uso de processador e memória:              sudo docker stats editor-ia"
echo

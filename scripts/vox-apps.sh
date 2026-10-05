#!/usr/bin/env bash
# VOX Editor — cadastra os APPS OFICIAIS do VOX nas redes (YouTube, Facebook/Instagram, TikTok).
# Depois disso, quem usa o editor online só clica em "Conectar" e entra com a própria conta:
# não precisa criar app de desenvolvedor nenhum.
#
#   sudo vox-apps          pergunta os dados de cada rede (Enter mantém o que já está salvo)
#   sudo vox-apps --ver    mostra o que está cadastrado (sem mostrar as chaves secretas)
set -euo pipefail
if [ "$EUID" -ne 0 ]; then echo "Rode com sudo:  sudo vox-apps"; exit 1; fi
CONF=/etc/voxeditor.conf
[ -f "$CONF" ] || { echo "Não achei $CONF. O editor está instalado nesta VPS?"; exit 1; }
# shellcheck disable=SC1090
. "$CONF"
APP_DIR=${APP_DIR:-/srv/voxeditor/app}
ENV="$APP_DIR/online/.env"
DADOS=$(sed -n 's/^DADOS=//p' "$ENV" 2>/dev/null); DADOS=${DADOS:-$APP_DIR/online/dados}
ARQ="$DADOS/apps-sistema.json"
DOMINIO=$(sed -n 's/^PUBLIC_URL=//p' "$ENV" 2>/dev/null); DOMINIO=${DOMINIO:-https://SEU-DOMINIO}

python3 - "$ARQ" "$DOMINIO" "${1:-}" <<'PY'
import getpass, json, os, sys
arq, dominio, modo = sys.argv[1], sys.argv[2].rstrip("/"), sys.argv[3]
dados = {}
if os.path.exists(arq):
    try:
        dados = json.load(open(arq, encoding="utf-8"))
    except Exception:
        dados = {}
redes = [("youtube", "YouTube (Google Cloud: ID do cliente OAuth)", "ID do cliente", "Chave secreta do cliente"),
         ("meta", "Facebook e Instagram (Meta for Developers)", "ID do app", "Chave secreta do app"),
         ("tiktok", "TikTok (TikTok for Developers)", "Client key", "Client secret")]
if modo == "--ver":
    for k, nome, *_ in redes:
        c = dados.get(k) or {}
        print(f"  {nome}: " + (f"cadastrado (ID {c['client_id'][:10]}…)" if c.get("client_id") else "não cadastrado"))
    sys.exit(0)
print()
print("  Apps oficiais do VOX — os usuários do editor online vão entrar com a própria conta por estes apps.")
print("  Em cada app, cadastre este endereço de retorno (redirect URI):")
for k, *_ in redes:
    print(f"     {dominio}/api/oauth/{k}/callback")
print("  Aperte Enter para manter o que já está salvo; digite - para apagar a rede.\n")
for k, nome, rot_id, rot_sec in redes:
    c = dados.get(k) or {}
    print(f"  == {nome} ==")
    atual = c.get("client_id", "")
    novo = input(f"     {rot_id}" + (f" [{atual[:12]}…]" if atual else "") + ": ").strip()
    if novo == "-":
        dados.pop(k, None); print("     removido.\n"); continue
    if novo:
        c["client_id"] = novo
    sec = getpass.getpass(f"     {rot_sec}" + (" [já salva]" if c.get("client_secret") else "") + " (não aparece ao digitar): ").strip()
    if sec:
        c["client_secret"] = sec
    if c.get("client_id") and c.get("client_secret"):
        dados[k] = c; print("     ok.\n")
    elif c.get("client_id"):
        dados[k] = c; print("     falta a chave secreta: rode de novo para completar.\n")
    else:
        print("     pulado.\n")
tmp = arq + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(dados, fh, ensure_ascii=False, indent=1)
os.chmod(tmp, 0o600)
try:
    os.chown(tmp, 1000, 1000)  # o editor roda no container com o usuário 1000
except OSError:
    pass
os.replace(tmp, arq)
print("  Salvo. Não precisa reiniciar: na página Redes sociais, cada rede cadastrada já mostra só o botão Conectar.")
PY

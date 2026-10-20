"""Testes da v0.9: senha do PC, pacote do projeto (.vox) e ligação PC ↔ online.
Rode depois do teste_completo.py (usa o projeto que ele cria em teste_dados)."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["EDITOR_DATA"] = str(ROOT / "teste_dados")
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend import app as appmod  # noqa: E402
from backend.core import pacote, store  # noqa: E402

c = TestClient(appmod.app)
ok = lambda cond, msg: print(("OK   " if cond else "FALHOU ") + msg) or cond  # noqa: E731
falhas = 0


def check(cond, msg):
    global falhas
    if not ok(cond, msg):
        falhas += 1


# ---------------------------------------------------------------- senha do PC
store.set_password("")
check(c.get("/api/status").json()["login_required"] is False, "sem senha: não pede login")
check(c.get("/api/projects").status_code == 200, "sem senha: projetos abertos")
r = c.post("/api/security/password", json={"new": "abc"})
check(r.status_code == 400, "senha curta recusada")
r = c.post("/api/security/password", json={"new": "segredo1"})
check(r.status_code == 200 and "editor_auth" in r.cookies, "senha criada e esta sessão continua logada")
check(c.get("/api/projects").status_code == 200, "sessão atual segue funcionando")
d = TestClient(appmod.app)  # outro "navegador", sem login
check(d.get("/api/status").json()["login_required"] is True, "com senha: pede login")
check(d.get("/api/projects").status_code == 401, "com senha: sem login não abre projetos")
check(d.get("/api/meta").status_code == 200, "a janela do PC ainda consegue ver se o servidor está vivo")
janela = TestClient(appmod.app, client=("127.0.0.1", 50000))  # como a janela do PC chega de verdade
check(janela.get("/api/projects", headers={"X-Vox-Interno": appmod.INTERNO}).status_code == 200,
      "janela do PC (código interno) baixa arquivos")
check(d.get("/api/projects", headers={"X-Vox-Interno": appmod.INTERNO}).status_code == 401,
      "código interno vindo de fora do PC é recusado")
check(d.get("/api/projects", headers={"X-Vox-Interno": "errado"}).status_code == 401, "código interno errado recusado")
check(d.get("/api/oauth/youtube/callback?error=x").status_code in (200, 307), "login das redes não é barrado pela senha")
check(d.post("/api/login", json={"password": "errada"}).status_code == 401, "senha errada recusada")
check(d.post("/api/login", json={"password": "segredo1"}).status_code == 200, "senha certa entra")
check(d.get("/api/projects").status_code == 200, "depois do login abre projetos")
check(d.post("/api/security/password", json={"current": "xx", "new": ""}).status_code == 401,
      "tirar a senha exige a senha atual")
cfgtxt = store.CONFIG_FILE.read_text()
check("segredo1" not in cfgtxt, "a senha não fica gravada em texto no config")
check("hash" not in json.dumps(d.get("/api/settings").json()["security"]), "o hash nunca vai para o navegador")
check(d.put("/api/settings", json={"security": {"hash": "x", "salt": "00"}}).status_code == 200
      and store.check_password("segredo1"), "não dá para trocar a senha pela rota de configurações")
check(d.post("/api/security/password", json={"current": "segredo1", "new": ""}).status_code == 200, "senha retirada")
check(c.get("/api/status").json()["login_required"] is False, "sem senha de novo")

# ---------------------------------------------------------------- pacote .vox
proj = next(p for p in store.list_projects() if p["status"] == "pronto")
pid = proj["id"]
orig = store.load(pid)
r = c.get(f"/api/projects/{pid}/pacote")
check(r.status_code == 200 and r.headers["content-type"] == "application/zip", "pacote baixado")
vox = ROOT / "teste_dados" / "teste.vox"
vox.write_bytes(r.content)
print(f"     pacote: {len(r.content) / 1e6:.1f} MB (arquivos do projeto: {pacote.tamanho(pid) / 1e6:.1f} MB)")
import zipfile  # noqa: E402
with zipfile.ZipFile(vox) as zf:
    check(zf.testzip() is None, "zip íntegro (CRC de todos os arquivos confere)")
    nomes = zf.namelist()
check(not any("/cache/" in n or n.endswith("audio48k.raw") for n in nomes), "temporários ficam de fora")
check(any(n.startswith("projeto/renders/") for n in nomes), "vídeos exportados vão junto")
r = c.post("/api/projects/importar-pacote", content=vox.read_bytes())
check(r.status_code == 200, "pacote importado")
novo = r.json()
check(novo["id"] != pid and novo["status"] == "pronto", "virou projeto novo, já pronto (sem nova análise)")
n = store.load(novo["id"])
for k in ("words", "clips", "overrides", "settings", "analysis", "renders", "source"):
    check(n.get(k) == orig.get(k), f"'{k}' igual ao original")
src_a = store.pdir(pid) / orig["source"]
src_b = store.pdir(novo["id"]) / n["source"]
check(src_a.read_bytes() == src_b.read_bytes(), "vídeo original idêntico, byte a byte")
ed = c.get(f"/api/projects/{novo['id']}").json()
check(ed["stats"] == c.get(f"/api/projects/{pid}").json()["stats"], "a edição calculada é a mesma")
check(c.post("/api/projects/importar-pacote", content=b"lixo").status_code == 400, "arquivo que não é .vox é recusado")
# pacote malicioso tentando gravar fora da pasta
mal = ROOT / "teste_dados" / "mal.vox"
with zipfile.ZipFile(mal, "w") as zf:
    zf.writestr("vox-pacote.json", json.dumps({"vox_pacote": 1}))
    zf.writestr("projeto/project.json", json.dumps({"id": "x", "name": "x", "status": "pronto"}))
    zf.writestr("projeto/../../fora.txt", "x")
check(c.post("/api/projects/importar-pacote", content=mal.read_bytes()).status_code in (400, 500)
      and not (ROOT / "teste_dados" / "fora.txt").exists() and not (store.PROJECTS.parent / "fora.txt").exists(),
      "pacote com caminho malicioso não grava fora")
check(not any(p.name.startswith("_importando") for p in store.PROJECTS.iterdir()), "não sobra pasta temporária")
c.delete(f"/api/projects/{novo['id']}")

# ---------------------------------------------------------------- copiar configurações (lado do online)
from backend.core import online  # noqa: E402
store.save_config({"ai": {"provider": "anthropic", "api_key": "sk-ant-teste-1234567890"}})
pac = online.pacote_config()
check("contas" not in json.dumps(pac) and "security" not in pac["config"] and "online" not in pac["config"],
      "não leva contas conectadas, senha do PC nem endereço online")
check(pac["config"]["ai"]["api_key"] == "sk-ant-teste-1234567890", "leva a chave da IA")
store.save_config({"ai": {"provider": "none", "api_key": "__apagar__"}})
r = c.post("/api/sync/config", json=pac)
check(r.status_code == 200 and store.load_config()["ai"]["api_key"] == "sk-ant-teste-1234567890", "online grava o que veio do PC")
check(c.post("/api/sync/config", json={"arquivos": {"../../fora.png": "eA=="}}).status_code == 200
      and not (store.DATA / "fora.png").exists(), "arquivo com caminho malicioso é ignorado")
store.save_config({"ai": {"provider": "none", "api_key": "__apagar__"}})

print()
print("TUDO CERTO" if not falhas else f"{falhas} FALHA(S)")
sys.exit(1 if falhas else 0)

"""Testes da v1.16 — conta Igreja (espaço próprio) na versão online: não vê nada do responsável, tem marca,
logos e redes próprias, publica só nas redes dela e usa só as áreas liberadas."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DADOS = Path(tempfile.mkdtemp()) / "dados"
os.environ["EDITOR_DATA"] = str(DADOS)
os.environ["VOX_SEM_MANUTENCAO"] = "1"
os.environ["APP_PASSWORD"] = "senha-do-dono-123"
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend import app as appmod  # noqa: E402
from backend.core import contas, jobs, montagem, publish, store  # noqa: E402

falhas = 0


def check(cond, msg):
    global falhas
    print(("OK   " if cond else "FALHOU ") + msg)
    if not cond:
        falhas += 1


PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00"
       b"\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82")

dono = TestClient(appmod.app)
r = dono.post("/api/login", json={"email": "admin", "password": "senha-do-dono-123"})
check(r.status_code == 200, "responsável entra")

# 1. criar a conta Igreja com só Stories e Resumo, abrindo nos Stories
r = dono.post("/api/usuarios", json={"nome": "IEAD Congregação Centro", "email": "centro@igreja.com", "senha": "igreja123",
                                     "papel": "igreja", "areas": ["stories", "resumo"], "inicio": "stories"})
check(r.status_code == 200 and r.json()["papel"] == "igreja", "cria conta do tipo Igreja")
uid = r.json()["id"]
check(r.json()["areas"] == ["stories", "resumo"] and r.json()["inicio"] == "stories", "guarda áreas e tela inicial")
lista = dono.get("/api/usuarios").json()["usuarios"]
check(lista[0]["papel_nome"] == "Igreja", "aparece como Igreja na lista")

# o responsável tem marca, projeto e redes
dono.put("/api/brand", json={"handle": "@pastordono", "color": "#112233"})
dono.post("/api/brand/logo", content=PNG)
proj_dono = montagem.projeto_em_branco("Projeto secreto do dono", "9:16")
(store.pdir(proj_dono["id"]) / "renders" / "video.mp4").write_bytes(b"x")
store.update(proj_dono["id"], lambda p: p.update(renders=[{"file": "video.mp4", "created": time.time(), "label": "x"}]))
(DADOS / "contas.json").write_text(json.dumps({"meta": {"user_token": "t", "page_id": "p1", "pages": [
    {"id": "p1", "name": "Página do Dono", "token": "tk", "ig_id": "ig1", "ig_user": "dono_ig"}]}}), encoding="utf-8")

# 2. a Igreja entra
igr = TestClient(appmod.app)
r = igr.post("/api/login", json={"email": "centro@igreja.com", "password": "igreja123"})
check(r.status_code == 200 and r.json()["papel"] == "igreja", "Igreja entra com e-mail e senha")
eu = igr.get("/api/eu").json()
check(eu["papel"] == "igreja" and eu["pode_publicar"] and eu["inicio"] == "stories", "sessão da Igreja: pode publicar, abre nos Stories")

# 3. não vê nada do responsável
check(all(p["id"] != proj_dono["id"] for p in igr.get("/api/projects").json()), "não vê os projetos do responsável")
check(igr.get(f"/api/projects/{proj_dono['id']}").status_code == 404, "não abre projeto do responsável pelo link")
check(not igr.get("/api/renders").json(), "não vê os exportados do responsável")
cfg_i = igr.get("/api/settings").json()
check(cfg_i["brand"].get("handle", "") == "" and cfg_i["brand"].get("color") != "#112233", "não vê a marca do responsável")
check(igr.get("/api/brand/logo").status_code == 404, "não vê o logo do responsável")

# 4. marca própria
r = igr.put("/api/brand", json={"handle": "@iead_centro", "color": "#AA0000"})
check(r.status_code == 200 and r.json()["brand"]["handle"] == "@iead_centro", "salva a própria marca")
check(igr.post("/api/brand/logo", content=PNG).status_code == 200, "envia o próprio logo")
check(igr.get("/api/brand/logo").status_code == 200, "vê o próprio logo")
check(dono.get("/api/settings").json()["brand"]["handle"] == "@pastordono", "a marca do responsável continua igual")
check(store.load_config(propria=False)["brand"]["handle"] == "@pastordono", "arquivo do responsável não foi mexido")
lg_i = igr.get("/api/stories/status").json()["logos"]
check(any(x["id"] == "marca" for x in lg_i), "nos Stories, 'Logo da Marca' é o logo da Igreja")

# 5. áreas liberadas
check(igr.get("/api/stories/status").status_code == 200, "Stories liberado")
check(igr.get("/api/resumo/status").status_code == 200, "Resumo liberado")
check(igr.get("/api/historia/status").status_code == 403, "História → Vídeo bloqueado (não foi liberado)")
check(igr.get("/api/stories/status").json()["pid"] != dono.get("/api/stories/status").json()["pid"], "Stories em espaço separado")

# 6. o que só o responsável faz
check(igr.put("/api/settings", json={"brand": {"handle": "@hack"}}).status_code == 403, "não mexe nas configurações")
check(igr.post("/api/publish/destinos", json={"kind": "pasta"}).status_code == 403, "não cria destinos próprios")
check(igr.get("/api/usuarios").status_code == 403, "não vê as contas")

# 7. redes separadas
st_i = igr.get("/api/publish/status").json()
check(not st_i["networks"]["instagram"]["connected"], "não usa o Instagram do responsável")
check(not st_i["destinos"], "não vê os destinos do responsável")
check(dono.get("/api/publish/status").json()["networks"]["instagram"]["connected"], "o responsável continua conectado")
r = igr.post("/api/oauth/meta/ticket", json={})
check(r.status_code == 200 and f".{uid}." in r.json()["url"], "link de login das redes leva a conta da Igreja")
ticket = r.json()["url"].split("ticket=")[1].split("&")[0]
from backend.rotas.comum import _ticket_conta  # noqa: E402
check(_ticket_conta("meta", ticket) == uid, "link assinado confere")
check(_ticket_conta("meta", ticket.replace(uid, "outraconta")) is None, "link adulterado não vale")
with publish.com_conta(uid):
    publish.save_account("meta", {"user_token": "t2", "page_id": "p9", "pages": [
        {"id": "p9", "name": "Página da Igreja", "token": "tk9", "ig_id": "ig9", "ig_user": "iead_centro"}]})
st_i = igr.get("/api/publish/status").json()
check(st_i["networks"]["instagram"]["connected"] and "iead_centro" in st_i["networks"]["instagram"]["account"],
      "Igreja conectada com o próprio Instagram")
check("dono_ig" in dono.get("/api/publish/status").json()["networks"]["instagram"]["account"], "o responsável segue com o dele")
check("iead_centro" in igr.get("/api/stories/status").json()["redes"]["instagram_story"]["conta"],
      "Stories da Igreja postam no Instagram dela")

# 8. publicar: só nas redes dela, fila separada
proj_i = None
tok = contas.atual.set(contas._publico(contas._buscar(uid)))
try:
    proj_i = montagem.projeto_em_branco("Culto da Igreja", "9:16")
finally:
    contas.atual.reset(tok)
(store.pdir(proj_i["id"]) / "renders" / "story.mp4").write_bytes(b"x")
store.update(proj_i["id"], lambda p: p.update(renders=[{"file": "story.mp4", "created": time.time(), "label": "s"}]))
r = igr.post("/api/publish/queue", json={"project": proj_i["id"], "file": "story.mp4", "nets": ["instagram_story"],
                                         "when": "at", "at": time.time() + 99999})
check(r.status_code == 200 and r.json()["items"][0]["conta"] == uid, "agenda no Instagram da Igreja")
r = dono.post("/api/publish/queue", json={"project": proj_dono["id"], "file": "video.mp4", "nets": ["instagram"],
                                          "when": "at", "at": time.time() + 99999})
item_dono = r.json()["items"][0]["id"]
fila_i = igr.get("/api/publish/queue").json()
check(len(fila_i) == 1 and fila_i[0]["conta"] == uid, "a Igreja só vê a fila dela")
check(len(dono.get("/api/publish/queue").json()) == 2, "o responsável vê todas")
check(igr.delete(f"/api/publish/queue/{item_dono}").status_code == 404, "a Igreja não apaga publicação do responsável")
check(igr.post("/api/publish/queue", json={"project": proj_dono["id"], "file": "video.mp4", "nets": ["instagram"]}).status_code
      in (403, 404), "a Igreja não publica vídeo do responsável")
usado = {}
publish.POSTERS["instagram_story"], antigo = (lambda path, it, log: usado.setdefault("ig", publish._meta_page()["ig_user"]) and ""), \
    publish.POSTERS["instagram_story"]
it = next(x for x in publish.queue() if x["conta"] == uid)
publish._run(it)
publish.POSTERS["instagram_story"] = antigo
check(usado.get("ig") == "iead_centro", "na hora de postar, usa o Instagram da Igreja (mesmo sem ninguém logado)")

# 9. tarefas em segundo plano rodam em nome de quem pediu
tok = contas.atual.set(contas._publico(contas._buscar(uid)))
try:
    j = jobs.submit("teste", proj_i["id"], lambda pr: {"conta": contas.conta_propria(),
                                                       "marca": store.load_config()["brand"].get("handle")}, queue="render")
finally:
    contas.atual.reset(tok)
for _ in range(50):
    if j["status"] in ("concluido", "erro"):
        break
    time.sleep(0.1)
check((j.get("result") or {}).get("conta") == uid and j["result"]["marca"] == "@iead_centro",
      "tarefa da Igreja usa a marca da Igreja")

# 10. editar a conta: liberar tudo de novo
r = dono.put(f"/api/usuarios/{uid}", json={"areas": [], "inicio": ""})
check(r.status_code == 200 and r.json()["areas"] == [] and r.json()["inicio"] == "", "libera todas as áreas")
time.sleep(5.2)  # a sessão é lida de novo depois de alguns segundos
check(igr.get("/api/historia/status").status_code == 200, "História liberada depois de editar")

print("\n" + ("TUDO CERTO" if not falhas else f"{falhas} FALHA(S)"))
sys.exit(1 if falhas else 0)

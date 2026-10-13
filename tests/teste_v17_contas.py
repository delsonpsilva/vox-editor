"""Testes da v1.7: contas de pessoas na versão online (dono, administrador, equipe e cliente).

Confere: login por e-mail, sessão que cai ao bloquear/trocar senha, cliente só vê os próprios projetos, cliente não
publica nem muda configurações, equipe vê tudo mas não mexe em configurações, limites de espaço e minutos,
contagem de minutos na análise, remoção da conta passando os projetos para o dono, e o programa do PC sem contas."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DADOS = Path(tempfile.mkdtemp()) / "online"
DADOS.mkdir(parents=True)
os.environ.update(EDITOR_DATA=str(DADOS), APP_PASSWORD="senha-dono", APP_SECRET="segredo-teste")
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import backend.app as A  # noqa: E402
from backend.core import contas, store  # noqa: E402

falhas = 0


def check(cond, msg):
    global falhas
    print(("OK   " if cond else "FALHOU ") + msg)
    if not cond:
        falhas += 1


A._FALHAS.clear()
dono = TestClient(A.app)
check(dono.get("/api/projects").status_code == 401, "sem login: 401")
st = dono.get("/api/status").json()
check(st["version"] == A.VERSION and st["contas"] is True, f"status mostra a versão ({A.VERSION}) e contas ligadas")
check(dono.post("/api/login", json={"password": "errada"}).status_code == 401, "senha errada do dono: 401")
r = dono.post("/api/login", json={"password": "senha-dono"})
check(r.status_code == 200 and r.json()["papel"] == "dono", "dono entra com a senha do instalador")
check(dono.get("/api/eu").json()["papel"] == "dono", "/api/eu: dono")

# cadastro
r = dono.post("/api/usuarios", json={"nome": "Ana Cliente", "email": "Ana@Teste.com", "senha": "123", "papel": "cliente"})
check(r.status_code == 400 and "6 caracteres" in r.json()["detail"], "senha curta é recusada")
r = dono.post("/api/usuarios", json={"nome": "Ana Cliente", "email": "Ana@Teste.com", "senha": "ana12345",
                                     "papel": "cliente", "limite_gb": 0, "limite_min": 30})
check(r.status_code == 200 and r.json()["email"] == "ana@teste.com" and "hash" not in r.json(), "cria cliente (e-mail em minúsculas, sem hash)")
ana_id = r.json()["id"]
r = dono.post("/api/usuarios", json={"nome": "Outra", "email": "ana@teste.com", "senha": "abcdef12", "papel": "cliente"})
check(r.status_code == 400, "e-mail repetido é recusado")
bia_id = dono.post("/api/usuarios", json={"nome": "Bia Cliente", "email": "bia@teste.com", "senha": "bia12345",
                                          "papel": "cliente"}).json()["id"]
eq_id = dono.post("/api/usuarios", json={"nome": "Edu Equipe", "email": "edu@teste.com", "senha": "edu12345",
                                         "papel": "equipe"}).json()["id"]
adm_id = dono.post("/api/usuarios", json={"nome": "Adm", "email": "adm@teste.com", "senha": "adm12345",
                                          "papel": "admin"}).json()["id"]
lst = dono.get("/api/usuarios").json()["usuarios"]
check(len(lst) == 4 and all("uso" in u for u in lst), "lista as 4 contas com o uso")

# projeto do dono
p_dono = dono.post("/api/montagem/novo", json={"name": "Do dono"}).json()["id"]
check(not store.load(p_dono).get("owner"), "projeto do dono fica sem 'owner'")

# login das pessoas
ana = TestClient(A.app)
check(ana.post("/api/login", json={"email": "ana@teste.com", "password": "errada"}).status_code == 401, "cliente com senha errada: 401")
A._FALHAS.clear()
r = ana.post("/api/login", json={"email": "ANA@teste.com ", "password": "ana12345"})
check(r.status_code == 200 and r.json()["papel"] == "cliente", "cliente entra com e-mail e senha")
eu = ana.get("/api/eu").json()
check(eu["papel"] == "cliente" and eu["pode_publicar"] is False and "uso" in eu, "/api/eu do cliente com uso e sem publicar")
p_ana = ana.post("/api/montagem/novo", json={"name": "Da Ana"}).json()["id"]
check(store.load(p_ana).get("owner") == ana_id, "projeto criado pela cliente fica com ela")
ids = [p["id"] for p in ana.get("/api/projects").json()]
check(ids == [p_ana], "cliente só vê o próprio projeto")
check(ana.get(f"/api/projects/{p_dono}").status_code == 404, "cliente não abre projeto do dono (404)")
check(ana.get(f"/api/projects/{p_dono}/montagem").status_code == 404, "cliente não abre a montagem do dono")
check(ana.delete(f"/api/projects/{p_dono}").status_code == 404 and (store.PROJECTS / p_dono).exists(),
      "cliente não apaga projeto do dono")
check(ana.get(f"/api/projects/{p_ana}/montagem").status_code == 200, "cliente abre a própria montagem")
check(ana.put("/api/settings", json={"app": {"name": "X"}}).status_code == 403, "cliente não muda configurações")
check(ana.get("/api/usuarios").status_code == 403, "cliente não vê as contas")
check(ana.post("/api/publish/queue", json={"project": p_ana, "file": "x.mp4", "nets": ["youtube"]}).status_code == 403,
      "cliente não publica")
check(ana.get("/api/publish/queue").json() == [], "fila de publicações vazia para o cliente")
check(ana.get("/api/publish/status").json().get("bloqueado") is True, "status das redes bloqueado para o cliente")
cfg = ana.get("/api/settings").json()
check("online" not in cfg and "legal" not in cfg and cfg.get("publish") == {}, "configurações do cliente sem dados sensíveis")
check(ana.post("/api/brand/logo", content=b"x").status_code == 403, "cliente não troca a logo da marca")
check(ana.post("/api/oauth/youtube/ticket", json={}).status_code == 403, "cliente não conecta rede")
check(ana.post("/api/maintenance/clean").status_code == 403, "cliente não roda a limpeza do servidor")

# a outra cliente não vê a Ana
bia = TestClient(A.app)
bia.post("/api/login", json={"email": "bia@teste.com", "password": "bia12345"})
check(bia.get("/api/projects").json() == [], "outra cliente não vê nada da Ana")
check(bia.get(f"/api/projects/{p_ana}").status_code == 404, "outra cliente não abre o projeto da Ana")
check(bia.get(f"/api/jobs/{p_ana}").status_code == 404, "outra cliente não vê as tarefas da Ana")

# o dono vê tudo
ids = {p["id"] for p in dono.get("/api/projects").json()}
check({p_dono, p_ana} <= ids, "dono vê os projetos de todos")
check(next(p for p in dono.get("/api/projects").json() if p["id"] == p_ana)["owner"] == ana_id, "lista mostra de quem é o projeto")

# equipe
edu = TestClient(A.app)
edu.post("/api/login", json={"email": "edu@teste.com", "password": "edu12345"})
ids = {p["id"] for p in edu.get("/api/projects").json()}
check({p_dono, p_ana} <= ids, "equipe vê todos os projetos")
check(edu.get(f"/api/projects/{p_ana}/montagem").status_code == 200, "equipe abre projeto da cliente")
check(edu.put("/api/settings", json={"app": {"name": "X"}}).status_code == 403, "equipe não muda configurações")
check(edu.get("/api/usuarios").status_code == 403, "equipe não vê as contas")
r = edu.post("/api/publish/queue", json={"project": p_ana, "file": "nao-existe.mp4", "nets": ["youtube"]})
check(r.status_code == 404, "equipe pode usar a fila de publicação (chega na checagem do vídeo)")
check(edu.get("/api/eu").json()["pode_publicar"] is True, "equipe pode publicar")

# administrador com conta
adm = TestClient(A.app)
adm.post("/api/login", json={"email": "adm@teste.com", "password": "adm12345"})
check(adm.get("/api/usuarios").status_code == 200, "administrador vê as contas")
check(adm.put("/api/settings", json={"brand": {"handle": "@teste"}}).status_code == 200, "administrador muda configurações")

# bloqueio derruba a sessão
dono.put(f"/api/usuarios/{bia_id}", json={"ativo": False})
contas._cache.clear()
check(bia.get("/api/projects").status_code == 401, "bloquear a conta derruba a sessão na hora")
r = TestClient(A.app).post("/api/login", json={"email": "bia@teste.com", "password": "bia12345"})
check(r.status_code == 403 and "bloqueada" in r.json()["detail"], "conta bloqueada não entra")

# troca de senha pela própria pessoa
check(ana.post("/api/eu/senha", json={"atual": "errada", "nova": "nova12345"}).status_code == 401, "troca de senha exige a atual")
check(ana.post("/api/eu/senha", json={"atual": "ana12345", "nova": "nova12345"}).status_code == 200, "cliente troca a própria senha")
check(ana.get("/api/projects").status_code == 200, "continua logada depois de trocar a senha")
contas._cache.clear()
velha = TestClient(A.app)
check(velha.post("/api/login", json={"email": "ana@teste.com", "password": "ana12345"}).status_code == 401, "senha antiga não entra mais")
A._FALHAS.clear()

# limite de minutos e contagem pela análise
contas.somar_minutos(ana_id, 30)
r = ana.post("/api/projects/link", json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"})
check(r.status_code == 403 and "minutos" in r.json()["detail"], "limite de minutos do mês bloqueia vídeo novo")
dono.put(f"/api/usuarios/{ana_id}", json={"limite_min": 0})
orig = A.pipeline.analyze
A.pipeline.analyze = lambda pid, progress: store.update(pid, lambda p: p.update(status="pronto", media={"duration": 600}))
try:
    antes = contas.minutos_no_mes(ana_id)
    A._trabalho_analise(p_ana)(lambda *a: None)
    A._trabalho_analise(p_ana)(lambda *a: None)  # nova análise do mesmo vídeo não conta de novo
    check(round(contas.minutos_no_mes(ana_id) - antes, 1) == 10.0, "análise soma os minutos uma vez só (10 min)")
    A._trabalho_analise(p_dono)(lambda *a: None)
    check(True, "análise de projeto do dono não quebra (sem contagem)")
finally:
    A.pipeline.analyze = orig

# limite de espaço
dono.put(f"/api/usuarios/{ana_id}", json={"limite_gb": 0.000001})
(store.PROJECTS / p_ana / "lixo.bin").write_bytes(b"0" * 5000)
contas.esquecer_espaco()
r = ana.post("/api/projects", content=b"abc", headers={"x-filename": "v.mp4"})
check(r.status_code == 403 and "espaço" in r.json()["detail"].lower(), "limite de espaço bloqueia envio novo")
r = ana.post(f"/api/projects/{p_ana}/midias", content=b"abc", headers={"x-filename": "a.png"})
check(r.status_code == 403, "limite de espaço vale também para mídias da montagem")
dash = ana.get("/api/dashboard").json()
check(dash["storage"] >= 5000 and dash["free"] == 0, "painel do cliente mostra o espaço dele e o que resta")
dono.put(f"/api/usuarios/{ana_id}", json={"limite_gb": 0})

# atividade: a cliente não vê tarefas dos outros
A.jobs.submit("teste", p_dono, lambda pr: {}, label="Do dono")
import time as _t
_t.sleep(0.3)
check(all(j["project"] != p_dono for j in ana.get("/api/atividade").json()["trabalhos"]), "atividade da cliente sem tarefas do dono")
check(any(j["project"] == p_dono for j in dono.get("/api/atividade").json()["trabalhos"]), "atividade do dono mostra tudo")

# remover conta: projetos vão para o dono
r = dono.delete(f"/api/usuarios/{ana_id}")
check(r.status_code == 200 and not store.load(p_ana).get("owner"), "remover a conta passa os projetos para o dono")
contas._cache.clear()
check(ana.get("/api/projects").status_code == 401, "sessão da conta removida cai")
check(len(dono.get("/api/usuarios").json()["usuarios"]) == 3, "sobram 3 contas")

# admin troca a própria senha no online (a do instalador deixa de valer)
r = dono.post("/api/security/password", json={"current": "errada", "new": "novaDono123"})
check(r.status_code == 401, "online: trocar a senha do admin exige a atual")
r = dono.post("/api/security/password", json={"current": "senha-dono", "new": ""})
check(r.status_code == 400, "online: o admin não fica sem senha")
r = dono.post("/api/security/password", json={"current": "senha-dono", "new": "novaDono123"})
check(r.status_code == 200, "online: admin troca a senha pelo painel")
A._FALHAS.clear()
t = TestClient(A.app)
check(t.post("/api/login", json={"email": "admin", "password": "senha-dono"}).status_code == 401, "senha do instalador não vale mais")
A._FALHAS.clear()
check(t.post("/api/login", json={"email": "admin", "password": "novaDono123"}).status_code == 200, "admin entra com a senha nova")
check(t.post("/api/login", json={"password": "novaDono123"}).status_code == 200, "PC ligado ao online (sem usuário) também entra")
edu2 = TestClient(A.app)
edu2.post("/api/login", json={"email": "edu@teste.com", "password": "edu12345"})
check(edu2.post("/api/security/password", json={"current": "novaDono123", "new": "x1234567"}).status_code == 403,
      "equipe não troca a senha do admin")
dono = t

# sair
check(dono.post("/api/logout").status_code == 200 and dono.get("/api/projects").status_code == 401, "Sair encerra a sessão")

shutil.rmtree(DADOS.parent, ignore_errors=True)
print()
print("TUDO CERTO" if not falhas else f"{falhas} FALHA(S)")
sys.exit(1 if falhas else 0)

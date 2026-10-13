"""Testes da v1.8: cópia de segurança diária, limpeza automática, rotas da manutenção, cancelar pela API
e a divisão do app.py (as rotas continuam no mesmo lugar e na mesma ordem)."""
import json
import os
import sqlite3
import sys
import tarfile
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DADOS = Path(tempfile.mkdtemp()) / "online"
DADOS.mkdir(parents=True)
os.environ.update(EDITOR_DATA=str(DADOS), APP_PASSWORD="senha-dono", APP_SECRET="segredo-teste",
                  VOX_SEM_MANUTENCAO="1")
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import backend.app as A  # noqa: E402
from backend.core import contas, jobs, manutencao, store  # noqa: E402

falhas = 0


def check(cond, msg):
    global falhas
    print(("OK   " if cond else "FALHOU ") + msg)
    if not cond:
        falhas += 1


def envelhece(f: Path, horas: float):
    t = time.time() - horas * 3600
    os.utime(f, (t, t))


# ---------- um projeto com de tudo um pouco ----------
p = store.new_project("Culto de domingo")
pid = p["id"]
pasta = store.pdir(pid)
(pasta / "original.mp4").write_bytes(b"v" * 5000)
(pasta / "renders").mkdir(exist_ok=True)
(pasta / "renders" / "corte-1.mp4").write_bytes(b"r" * 3000)          # exportado da lista: fica
(pasta / "renders" / "cancelado-2.mp4").write_bytes(b"o" * 2000)      # órfão antigo: sai
(pasta / "renders" / "agora-3.mp4").write_bytes(b"n" * 2000)          # órfão recente (pode estar gravando): fica
(pasta / "tmp_corte.raw").write_bytes(b"t" * 4000)                    # resto de render antigo: sai
(pasta / "tmp_novo.raw").write_bytes(b"t" * 4000)                     # resto recente: fica
(pasta / "video.f137.mp4.part").write_bytes(b"p" * 1000)              # download pela metade antigo: sai
(pasta / "cache").mkdir(exist_ok=True)
(pasta / "cache" / "velha.jpg").write_bytes(b"c" * 700)               # cache sem uso há 40 dias: sai
(pasta / "cache" / "nova.jpg").write_bytes(b"c" * 700)                # cache recente: fica
(pasta / "midias").mkdir(exist_ok=True)
(pasta / "midias" / "foto.jpg").write_bytes(b"m" * 900)               # mídia da montagem: fica sempre
store.update(pid, lambda x: x.update(renders=[{"file": "corte-1.mp4", "created": time.time()}]))
for nome, h in (("cancelado-2.mp4", 30), ("tmp_corte.raw", 8), ("video.f137.mp4.part", 30)):
    envelhece(pasta / ("renders/" + nome if nome.endswith(".mp4") else nome), h)
envelhece(pasta / "cache" / "velha.jpg", 40 * 24)
envelhece(pasta / "midias" / "foto.jpg", 400 * 24)
envelhece(pasta / "renders" / "corte-1.mp4", 400 * 24)
envelhece(pasta / "original.mp4", 400 * 24)
contas.criar({"nome": "Cliente Teste", "email": "cli@teste.com", "papel": "cliente", "senha": "cliente123"})

# ---------- cópia de segurança ----------
info = manutencao.fazer_backup("teste")
arq = DADOS / "backups" / info["arquivo"]
check(arq.exists() and info["tamanho"] > 0, f"cópia criada: {info['arquivo']} ({info['tamanho']} bytes)")
with tarfile.open(arq) as tar:
    nomes = tar.getnames()
check(f"projetos/{pid}/project.json" in nomes, "a cópia tem a edição do projeto (project.json)")
check(not any(n.endswith((".mp4", ".raw", ".part", ".jpg")) and "marca/" not in n for n in nomes),
      "vídeos, temporários e cache ficam fora da cópia")
if (DADOS / "vox.db").exists():
    check("vox.db" in nomes, "banco de contas (vox.db) entra na cópia")
    with tarfile.open(arq) as tar, tempfile.TemporaryDirectory() as td:
        tar.extract("vox.db", td, filter="data")
        con = sqlite3.connect(str(Path(td) / "vox.db"))
        tabelas = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
        con.close()
    check(len(tabelas) > 0, f"cópia do banco abre normalmente ({len(tabelas)} tabela(s))")
check(not any(n.startswith("backups/") for n in nomes), "a cópia não copia as cópias anteriores")

# guarda só as últimas 7
for d in range(1, 12):
    (DADOS / "backups" / f"diario-2026010{d % 10}{d}.tar.gz").write_bytes(b"x")
manutencao.fazer_backup("teste")
check(len(list((DADOS / "backups").glob("diario-*.tar.gz"))) == 7, "guarda só as 7 cópias mais recentes")
check((DADOS / "backups" / info["arquivo"]).exists(), "a cópia de hoje continua lá")

# ---------- limpeza ----------
r = manutencao.limpar("teste")
existe = lambda rel: (pasta / rel).exists()  # noqa: E731
check(not existe("renders/cancelado-2.mp4"), "exportado órfão antigo apagado")
check(existe("renders/corte-1.mp4"), "exportado da lista continua (mesmo antigo)")
check(existe("renders/agora-3.mp4"), "órfão recente continua (pode estar sendo gravado)")
check(not existe("tmp_corte.raw") and existe("tmp_novo.raw"), "resto de render antigo sai, recente fica")
check(not existe("video.f137.mp4.part"), "download pela metade antigo apagado")
check(not existe("cache/velha.jpg") and existe("cache/nova.jpg"), "cache sem uso há 30 dias sai, recente fica")
check(existe("original.mp4") and existe("midias/foto.jpg"), "vídeo original e mídias da montagem nunca são apagados")
check(r["liberado"] == 2000 + 4000 + 1000 + 700 and r["arquivos"] == 4, f"liberou {r['liberado']} bytes em {r['arquivos']} arquivos")
check(manutencao.estado().get("limpeza", {}).get("liberado") == r["liberado"], "estado guarda a última limpeza")

# agenda: sem cópia há mais de 26h roda assim que abrir; logo depois de uma cópia, não
manutencao._gravar_estado(backup={"quando": time.time() - 30 * 3600})
check(manutencao._hora_de_rodar(time.time()), "ficou mais de um dia sem cópia: roda assim que o programa abrir")
manutencao._gravar_estado(backup={"quando": time.time() - 60})
check(not manutencao._hora_de_rodar(time.time()), "acabou de fazer cópia: não repete")

# ---------- rotas ----------
c = TestClient(A.app)
check(c.get("/api/maintenance/status").status_code == 401, "status da manutenção pede login")
A._FALHAS.clear()
lg = c.post("/api/login", json={"password": "senha-dono"})
check(lg.status_code == 200, "entrar como responsável")
st = c.get("/api/maintenance/status")
check(st.status_code == 200 and st.json()["copias"], "responsável vê as cópias e a fila")
check("fila" in st.json() and st.json()["fila"]["filas"]["render"]["limite"] >= 1, "situação da fila aparece")
nome = st.json()["copias"][0]["arquivo"]
check(c.get(f"/api/maintenance/backups/{nome}").status_code == 200, "responsável baixa a cópia")
check(c.get("/api/maintenance/backups/..%2Fconfig.json").status_code in (400, 404), "não deixa baixar outro arquivo")
ag = c.post("/api/maintenance/backup")
check(ag.status_code == 200 and "backup" in ag.json(), "fazer cópia agora pelo painel")

# cancelar pela API
import threading  # noqa: E402
libera = threading.Event()


def demorado(pr):
    while not libera.is_set():
        pr(0.1, "trabalhando")
        time.sleep(0.05)
    return {}


j1 = jobs.submit("render", pid, demorado, queue="render")
j2 = jobs.submit("render", pid, demorado, queue="render")
j3 = jobs.submit("render", pid, demorado, queue="render")
time.sleep(0.2)
r3 = c.post(f"/api/jobs/{pid}/{j3['id']}/cancelar")
check(r3.status_code == 200 and r3.json()["status"] == "cancelado", "cancelar pela API (na fila)")
r1 = c.post(f"/api/jobs/{pid}/{j1['id']}/cancelar")
time.sleep(0.3)
check(jobs.get(j1["id"])["status"] == "cancelado", "cancelar pela API (rodando)")
check(c.post(f"/api/jobs/{pid}/nao-existe/cancelar").status_code == 404, "tarefa inexistente: 404")
check(c.post(f"/api/jobs/abcdefabcdef/{j2['id']}/cancelar").status_code == 404, "tarefa de outro projeto: 404")
libera.set()

# análise cancelada na fila deixa o projeto com aviso
store.update(pid, lambda x: x.update(status="na fila"))
bloq = threading.Event()
ja = jobs.submit("analise", "outro", lambda pr: bloq.wait(5) and {}, queue="analysis")
jb = jobs.submit("analise", pid, lambda pr: {}, queue="analysis")
c.post(f"/api/jobs/{pid}/{jb['id']}/cancelar")
check(store.load(pid)["status"] == "erro" and "Cancelado" in (store.load(pid).get("progress") or {}).get("msg", ""),
      "análise cancelada: projeto fica com aviso e Tentar novamente")
bloq.set()

check(c.get("/api/fila").status_code == 200, "rota da fila para o responsável")
cc = TestClient(A.app)
A._FALHAS.clear()
check(cc.post("/api/login", json={"email": "cli@teste.com", "password": "cliente123"}).status_code == 200, "cliente entra")
check(cc.get("/api/maintenance/status").status_code == 403, "cliente não vê as cópias de segurança")
check(cc.post("/api/maintenance/backup").status_code == 403, "cliente não faz cópia")
check(cc.get("/api/fila").status_code == 403, "cliente não vê a fila completa")
check(c.get("/api/status").json()["version"] == A.VERSION, f"versão continua vindo do app.py ({A.VERSION})")

print("\nRESULTADO:", "TUDO OK" if not falhas else f"{falhas} FALHA(S)")
sys.exit(1 if falhas else 0)

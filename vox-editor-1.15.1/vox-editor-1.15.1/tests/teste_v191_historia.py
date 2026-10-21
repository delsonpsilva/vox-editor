"""Testes da v1.9.1 — História → Vídeo: chaves na própria tela, imagens por IA (Gemini), fotos sem chave (Openverse),
vídeos em câmera lenta quando são curtos, música automática e avisos claros. A internet é simulada."""
import base64
import contextlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DADOS = Path(tempfile.mkdtemp()) / "dados"
os.environ["EDITOR_DATA"] = str(DADOS)
os.environ["VOX_SEM_MANUTENCAO"] = "1"
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import httpx  # noqa: E402
import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import app as appmod  # noqa: E402
from backend.core import bancos, historia, store, trilhas  # noqa: E402
from backend.engine import ffmpeg_tools as ff  # noqa: E402

c = TestClient(appmod.app)
falhas = 0


def check(cond, msg):
    global falhas
    print(("OK   " if cond else "FALHOU ") + msg)
    if not cond:
        falhas += 1


def espera(r, limite=240):
    pid, jid = r["id"], r["job"]
    t0 = time.time()
    while time.time() - t0 < limite:
        j = next((x for x in c.get(f"/api/jobs/{pid}").json() if x["id"] == jid), None)
        if j and j["status"] in ("concluido", "erro", "cancelado"):
            return j
        time.sleep(0.3)
    return {"status": "tempo"}


tmp = Path(tempfile.mkdtemp())
F = ff.ffmpeg()
ok, png = cv2.imencode(".png", np.full((1920, 1080, 3), (60, 120, 200), np.uint8))
PNG = png.tobytes()
ok, jpg = cv2.imencode(".jpg", np.full((1200, 800, 3), (40, 160, 90), np.uint8))
JPG = jpg.tobytes()
subprocess.run([F, "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=f=330:d=70", "-c:a", "libmp3lame",
                str(tmp / "musica.mp3")], check=True)
subprocess.run([F, "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=720x1280:r=30:d=6",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(tmp / "clipe.mp4")], check=True)

HIST = ("Davi era um jovem pastor. Ele cuidava das ovelhas do pai no campo. Um dia, um gigante desafiou o exército. "
        "Ninguém tinha coragem de enfrentar Golias. Davi pegou cinco pedras lisas do riacho. Com uma só pedra, venceu o gigante!")
BASE = {"formato": "9:16", "voz": "nenhuma", "usar_ia": False}

# ---------- 1) chaves digitadas na tela ----------
st = c.get("/api/historia/status").json()
check(not st["gemini"] and not st["ia"] and not st["pexels"], "começa sem chaves")
check(st["estilos"].get("biblico") and "ia" in st["visuais"], "status traz estilos e a opção de imagens por IA")
st = c.post("/api/historia/chaves", json={"gemini": "AIza-teste-123"}).json()
cfg = store.load_config()
check(st["gemini"] and st["ia"] and st["ia_nome"] == "Gemini", "chave do Gemini liga a IA do programa")
check(cfg["ai"]["provider"] == "openai_compat" and "generativelanguage" in cfg["ai"]["base_url"], "IA aponta para o Gemini")
check(c.get("/api/settings").json()["gemini"]["api_key"] == "", "a chave nunca volta para a tela")
store.save_config({"ai": {"provider": "anthropic", "api_key": "claude-x"}})
c.post("/api/historia/chaves", json={"gemini": "AIza-outra"})
check(store.load_config()["ai"]["provider"] == "anthropic", "se já existe outra IA, a chave do Gemini não troca a IA")
store.save_config({"ai": {"provider": "none", "api_key": "__apagar__"}})

# ---------- 2) imagens por IA (Gemini simulado) ----------
orig_post, orig_get, orig_stream = httpx.post, httpx.get, httpx.stream
pedidos = []


class Resp:
    def __init__(self, code, js=None, content=b""):
        self.status_code, self._js, self.content, self.text = code, js, content, json.dumps(js or {})

    def json(self):
        return self._js

    def iter_bytes(self, n=65536):
        yield self.content


def post_gemini(url, **kw):
    pedidos.append((url, kw.get("json")))
    if "generateContent" in url:
        return Resp(200, {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "image/png",
                                                                                "data": base64.b64encode(PNG).decode()}}]}}]})
    return orig_post(url, **kw)


httpx.post = post_gemini
r = c.post("/api/historia/texto", json={"texto": HIST, "opcoes": {**BASE, "visual": "ia", "estilo": "biblico", "musica": ""}}).json()
j = espera(r)
check(j["status"] == "concluido", f"imagens por IA: {j.get('error')}")
m = c.get(f"/api/projects/{r['id']}/montagem").json()
md = {x["id"]: x for x in m["media"]}
cenas = [x for x in m["items"] if x["track"] == "t_v1"]
check(cenas and all(md[x["src"]]["file"].split("/")[-1].startswith("ia_") for x in cenas), "toda cena com imagem da IA")
check(j["result"]["fotos"] == len(cenas) and not j["result"].get("aviso"), "resumo conta as imagens, sem aviso")
corpo = pedidos[-1][1]
txt = corpo["contents"][0]["parts"][0]["text"]
check(corpo["generationConfig"]["imageConfig"]["aspectRatio"] == "9:16", "imagem pedida no formato vertical")
check("biblical" in txt and "No text" in txt, "estilo e 'sem letras' no pedido da imagem")


def post_sem_cota(url, **kw):
    if "generateContent" in url:
        return Resp(429, {"error": "quota"})
    return orig_post(url, **kw)


httpx.post = post_sem_cota
orig_ov = historia._openverse
historia._openverse = lambda *a, **k: None
r = c.post("/api/historia/texto", json={"texto": HIST, "opcoes": {**BASE, "visual": "ia", "musica": ""}}).json()
j = espera(r)
check(j["status"] == "concluido" and "cota" in (j["result"].get("aviso") or ""), "sem cota de imagem: vídeo sai e explica")
check("fundo colorido" in j["result"]["aviso"], "avisa as cenas que ficaram com fundo colorido")
historia._openverse = orig_ov
httpx.post = orig_post

# ---------- 3) fotos sem chave (Openverse simulado) ----------


def get_ov(url, **kw):
    if "openverse" in url:
        q = kw["params"]["q"]
        return Resp(200, {"results": [{"id": f"{q}-{i}", "url": f"https://img.exemplo/{q}/{i}.jpg", "creator": "Fulano",
                                       "license": "by", "license_version": "4.0", "source": "flickr",
                                       "foreign_landing_url": "https://flickr.com/x"} for i in range(3)]})
    return orig_get(url, **kw)


@contextlib.contextmanager
def stream_ov(metodo, url, **kw):
    yield Resp(200, content=JPG)


httpx.get, httpx.stream = get_ov, stream_ov
r = c.post("/api/historia/texto", json={"texto": HIST, "opcoes": {**BASE, "visual": "fotos", "musica": ""}}).json()
j = espera(r)
m = c.get(f"/api/projects/{r['id']}/montagem").json()
md = {x["id"]: x for x in m["media"]}
cenas = [x for x in m["items"] if x["track"] == "t_v1"]
srcs = [x["src"] for x in cenas]
check(j["status"] == "concluido" and all(md[s]["banco"].startswith("ov-") for s in srcs), "sem chave: fotos do Openverse")
check(len(set(md[s]["banco"] for s in srcs)) == len(srcs), "nenhuma foto repetida")
check("Fulano" in md[srcs[0]]["credito"] and "BY" in md[srcs[0]]["credito"], "crédito da foto guardado")
p = c.post("/api/historia/previa", json={"texto": "o pastor e as ovelhas no campo verde", "formato": "9:16"}).json()
check(p["imagem"] and "img.exemplo" in p["imagem"], "prévia ao vivo também acha foto sem chave")
httpx.get, httpx.stream = orig_get, orig_stream

# ---------- 4) vídeos curtos entram em câmera lenta ----------
orig_status, orig_buscar, orig_baixar = bancos.status, bancos.buscar, bancos.baixar
bancos.status = lambda: {"pexels": True, "pixabay": False}
n = [0]


def buscar_falso(fonte, tipo, q, pagina=1, orient=""):
    n[0] += 1
    return {"itens": [{"id": f"pexels-v-{n[0]}-{i}", "tipo": "video", "dur": 6} for i in range(2)]}


def baixar_falso(bid, pasta, progress=None):
    dest = pasta / f"{bid}.mp4"
    dest.write_bytes((tmp / "clipe.mp4").read_bytes())
    return dest, {"autor": "Ana", "fonte": "pexels", "ext": ".mp4", "credito": "Vídeo: Ana / Pexels"}


bancos.buscar, bancos.baixar = buscar_falso, baixar_falso
longa = " ".join(["Esta é uma frase longa de propósito para a cena durar mais tempo na tela do vídeo."] * 2)
r = c.post("/api/historia/texto", json={"texto": longa, "opcoes": {**BASE, "visual": "videos", "musica": ""}}).json()
j = espera(r)
m = c.get(f"/api/projects/{r['id']}/montagem").json()
v = [x for x in m["items"] if x["track"] == "t_v1"]
check(j["status"] == "concluido" and v and v[0]["type"] == "video", "cena com vídeo do banco")
check(v and 0.55 <= v[0]["speed"] < 1 and v[0]["dur"] * v[0]["speed"] <= 6.01, f"vídeo curto em câmera lenta (velocidade {v and v[0]['speed']})")
check(j["result"]["videos"] == len(v), "resumo conta os vídeos")
bancos.status, bancos.buscar, bancos.baixar = orig_status, orig_buscar, orig_baixar

# ---------- 5) música automática ----------
orig_tb, orig_tbx = trilhas.buscar, trilhas.baixar
pedido_humor = []


def tb(q="", humor="", pagina=1):
    pedido_humor.append(humor)
    return {"faixas": [{"id": "m1", "duration": 30, "license": "by"}, {"id": "m2", "duration": 70, "license": "cc0"}]}


def tbx(tid, pasta):
    dest = pasta / f"{tid}.mp3"
    dest.write_bytes((tmp / "musica.mp3").read_bytes())
    return dest, {"id": tid, "title": "Calma", "creator": "Autor", "license": "cc0", "credito": "Música: Calma — Autor · CC0"}


trilhas.buscar, trilhas.baixar = tb, tbx
r = c.post("/api/historia/texto", json={"texto": "Deus ouviu a oração do pastor. O Senhor respondeu com graça e fé.",
                                        "opcoes": {**BASE, "visual": "cores"}}).json()
j = espera(r)
m = c.get(f"/api/projects/{r['id']}/montagem").json()
mus = [x for x in m["items"] if x["track"] == "t_musica"]
check(j["status"] == "concluido" and j["result"]["musica"] and mus, "música automática quando nada é escolhido")
check(pedido_humor[-1] == "oracao", f"humor da música pela história ({pedido_humor[-1]})")
check(mus and mus[0]["duck"] and mus[0]["volume"] < 0.3, "música baixa e abaixando na fala")
check(store.load(r["id"])["historia"]["musica"]["credito"].startswith("Música:"), "crédito da música guardado no projeto")


def tb_falha(*a, **k):
    raise RuntimeError("sem internet")


trilhas.buscar = tb_falha
r = c.post("/api/historia/texto", json={"texto": HIST, "opcoes": {**BASE, "visual": "cores", "musica": "__auto__"}}).json()
j = espera(r)
check(j["status"] == "concluido" and "Música automática" in (j["result"].get("aviso") or ""), "sem música: vídeo sai e avisa")
trilhas.buscar, trilhas.baixar = orig_tb, orig_tbx

# ---------- 6) IA devolvendo o formato novo (objeto com humor, busca_en e imagem) ----------
import backend.engine.smartcuts as sc  # noqa: E402
orig_llm = sc._call_llm
sc._call_llm = lambda prompt, ai: "Claro! " + json.dumps({"humor": "epico", "cenas": [
    {"inicio": 0, "fim": 2, "busca": "pastor ovelhas", "busca_en": "shepherd sheep", "imagem": "A young shepherd boy",
     "destaque": "O jovem pastor", "grafico": None},
    {"inicio": 3, "fim": 5, "busca": "gigante", "busca_en": "giant warrior", "imagem": "A giant warrior", "destaque": "",
     "grafico": None}]})
store.save_config({"ai": {"provider": "anthropic", "api_key": "k"}})
w = historia.palavras_do_texto(HIST)
cn, modo, humor = historia.planejar(w, "9:16", True)
check(modo == "ia" and humor == "epico" and len(cn) == 2, "IA no formato novo (objeto com humor)")
check(cn[0]["busca_en"] == "shepherd sheep" and cn[1]["imagem"] == "A giant warrior", "busca em inglês e descrição da imagem")
sc._call_llm = orig_llm
store.save_config({"ai": {"provider": "none", "api_key": "__apagar__"}})

# ---------- 7) permissões ----------
r = c.post("/api/historia/microfone/config")
check(r.status_code == 400, "abrir configurações do microfone só no PC com Windows")

print("\nFALHAS:", falhas)
sys.exit(1 if falhas else 0)

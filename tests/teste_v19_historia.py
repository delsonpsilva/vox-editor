"""Testes da v1.9 — História → Vídeo: texto, áudio e narração ao vivo viram uma Montagem que exporta de verdade."""
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

import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import app as appmod  # noqa: E402
from backend.core import historia, montagem, store  # noqa: E402
from backend.engine import ffmpeg_tools as ff  # noqa: E402

c = TestClient(appmod.app)
falhas = 0


def check(cond, msg):
    global falhas
    print(("OK   " if cond else "FALHOU ") + msg)
    if not cond:
        falhas += 1


def espera(pid, jid, limite=240):
    t0 = time.time()
    while time.time() - t0 < limite:
        js = {j["id"]: j for j in c.get(f"/api/jobs/{pid}").json()}
        j = js.get(jid)
        if j and j["status"] in ("concluido", "erro", "cancelado"):
            return j
        time.sleep(0.3)
    return {"status": "tempo esgotado"}


HISTORIA = """O Pastor e a Ovelha Perdida

Havia um pastor que cuidava de cem ovelhas no campo. Todas as tardes ele contava uma por uma, com carinho.
Certo dia, ao contar, percebeu que faltava uma. Noventa e nove estavam ali, mas uma tinha se perdido nas montanhas.
Sem pensar duas vezes, ele deixou as outras em segurança e saiu pela noite, chamando o nome dela.
Depois de muito procurar, encontrou a ovelha presa entre os espinhos. Colocou-a nos ombros e voltou cantando de alegria!"""

# ---------- partes locais ----------
w = historia.palavras_do_texto(HISTORIA)
fr = historia.frases(w)
check(len(fr) >= 6, f"texto dividido em frases ({len(fr)})")
check(historia._txt(w, *fr[0]).startswith("O Pastor e a Ovelha Perdida"), "título (linha sem ponto) vira uma frase só")
kw = historia.palavras_chave("Havia um pastor que cuidava de cem ovelhas no campo, e o pastor amava as ovelhas")
check("pastor" in kw and "ovelhas" in kw, f"palavras de busca sem IA: {kw}")
cn = historia.cenas_por_regra(w, fr, "9:16")
check(2 <= len(cn) <= 6 and cn[0]["i0"] == 0 and cn[-1]["i1"] == len(w) - 1, f"cenas sem IA cobrem tudo ({len(cn)})")
check(all(cn[k]["i0"] == cn[k - 1]["i1"] + 1 for k in range(1, len(cn))), "cenas em sequência, sem pular frase")

# ---------- 1) texto, sem voz, fundos coloridos ----------
st = c.get("/api/historia/status").json()
check({v["id"] for v in st["vozes"]} >= {"francisca", "antonio", "windows", "nenhuma"}, "status lista as vozes")
r = c.post("/api/historia/texto", json={"texto": HISTORIA, "name": "Ovelha", "opcoes": {
    "formato": "9:16", "voz": "nenhuma", "visual": "cores", "usar_ia": False}})
check(r.status_code == 200, f"criar pelo texto: {r.status_code} {r.text[:200]}")
pid, jid = r.json()["id"], r.json()["job"]
j = espera(pid, jid)
check(j["status"] == "concluido", f"tarefa do texto concluída ({j.get('status')} {j.get('error')})")
proj = store.load(pid)
check(proj["kind"] == "montagem" and proj["status"] == "pronto", "projeto vira Montagem pronta")
m = c.get(f"/api/projects/{pid}/montagem").json()
tipos = {}
for it in m["items"]:
    tipos.setdefault(it["track"], []).append(it)
cenas = tipos.get("t_v1", [])
check(len(cenas) == j["result"]["cenas"] and all(x["type"] == "image" for x in cenas), "uma imagem por cena")
check(all(x.get("kf") and len(x["kf"]) == 2 for x in cenas), "cada cena tem zoom suave (quadros-chave)")
check(all(x.get("tr", {}).get("tipo") == "dissolver" for x in cenas[1:]), "transição entre as cenas")
check(all(abs(cenas[k]["start"] - (cenas[k - 1]["start"] + cenas[k - 1]["dur"])) < 0.01 for k in range(1, len(cenas))),
      "cenas encostadas, sem buraco")
leg = tipos.get("t_legenda", [])
check(len(leg) >= 15 and all(x["type"] == "text" and x["upper"] for x in leg), f"legenda em pedaços ({len(leg)})")
check(all(len(ln) <= 18 for x in leg for ln in x["text"].split("\n")), "legenda quebrada em linhas curtas no vertical")
check(all(leg[k]["start"] >= leg[k - 1]["start"] for k in range(1, len(leg))), "legenda em ordem")
tot = cenas[-1]["start"] + cenas[-1]["dur"]
check(leg[-1]["start"] + leg[-1]["dur"] <= tot + 0.5, "legenda termina junto com o vídeo")

# exporta de verdade (curto, 720p) para garantir que o FFmpeg aceita tudo o que foi montado
r = c.post(f"/api/projects/{pid}/montagem/exportar", json={"res": "720"})
check(r.status_code == 200, "exportação pedida")
t0 = time.time()
ok = None
while time.time() - t0 < 600:
    js = [x for x in c.get(f"/api/jobs/{pid}").json() if x["kind"] == "montagem"]
    if js and js[0]["status"] in ("concluido", "erro"):
        ok = js[0]
        break
    time.sleep(1)
check(ok and ok["status"] == "concluido", f"Montagem da história exportada ({ok and ok.get('error')})")
if ok and ok["status"] == "concluido":
    out = store.pdir(pid) / "renders" / Path(ok["result"]["file"]).name
    info = ff.probe(str(out))
    check(abs(info["duration"] - tot) < 1.0 and info["height"] > info["width"], f"vídeo vertical com {info['duration']:.1f}s")

# ---------- 2) IA (simulada) com gráfico e destaque ----------
import backend.engine.smartcuts as sc  # noqa: E402
orig_llm = sc._call_llm


def falsa_ia(prompt, ai):
    n = prompt.count("\n[") + (1 if "\n[0]" in prompt else 0)
    return json.dumps([{"inicio": 0, "fim": 1, "busca": "pastor ovelhas", "destaque": "A ovelha perdida", "grafico": None},
                       {"inicio": 2, "fim": 3, "busca": "rebanho campo", "destaque": "",
                        "grafico": {"titulo": "Ovelhas", "rotulos": ["No rebanho", "Perdida"], "valores": [99, 1]}},
                       {"inicio": 4, "fim": 4, "busca": "noite montanha", "destaque": "", "grafico": None}])


sc._call_llm = falsa_ia
store.save_config({"ai": {"provider": "anthropic", "api_key": "teste-123"}})
r = c.post("/api/historia/texto", json={"texto": HISTORIA, "opcoes": {"formato": "16:9", "voz": "nenhuma",
                                                                      "visual": "cores", "usar_ia": True}})
pid2 = r.json()["id"]
j = espera(pid2, r.json()["job"])
check(j["status"] == "concluido" and j["result"]["modo"] == "ia", f"com IA: {j.get('result')} {j.get('error')}")
m2 = c.get(f"/api/projects/{pid2}/montagem").json()
check(len([x for x in m2["items"] if x["track"] == "t_v1"]) == 3, "IA definiu 3 cenas (a última pegou o resto)")
check(any(x["track"] == "t_titulo" and "OVELHA" in x["text"].upper() for x in m2["items"]), "título de destaque")
gr = [x for x in m2["items"] if x["track"] == "t_v2"]
check(len(gr) == 1, "gráfico entrou na cena com números")
md = {x["id"]: x for x in m2["media"]}
check(gr and md[gr[0]["src"]]["kind"] == "image" and md[gr[0]["src"]]["w"] > 500, "gráfico é um PNG de verdade")
ult = historia.store.load(pid2)["historia"]["cenas"]
check(len(ult) == 3 and ult[0]["busca"] == "pastor ovelhas", "cenas guardadas no projeto")


def ia_quebrada(prompt, ai):
    return "não sei"


sc._call_llm = ia_quebrada
r = c.post("/api/historia/texto", json={"texto": HISTORIA, "opcoes": {"voz": "nenhuma", "visual": "cores"}})
j = espera(r.json()["id"], r.json()["job"])
check(j["status"] == "concluido" and j["result"]["modo"] == "local", "IA falhando: segue sem IA")
sc._call_llm = orig_llm
store.save_config({"ai": {"provider": "none", "api_key": "__apagar__"}})

# ---------- 3) áudio enviado (transcrição simulada) ----------
tmp = Path(tempfile.mkdtemp())
F = ff.ffmpeg()
subprocess.run([F, "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=12", "-c:a", "libmp3lame",
                str(tmp / "narracao.mp3")], check=True)
frase = "Havia um pastor no campo. Ele tinha cem ovelhas. Uma se perdeu na montanha. Ele saiu procurando. Achou e voltou feliz."
falsas = []
for k, p in enumerate(frase.split()):
    falsas.append({"w": p, "s": round(0.5 + k * 0.5, 2), "e": round(0.5 + k * 0.5 + 0.4, 2), "p": 1})
orig_tr = historia._transcrever
historia._transcrever = lambda wav, progress=None, prompt="": {"words": falsas, "segments": [], "language": "pt"}
r = c.post("/api/historia/audio", content=(tmp / "narracao.mp3").read_bytes(),
           headers={"x-filename": "narracao.mp3", "x-opcoes": json.dumps({"formato": "1:1", "visual": "cores"})})
check(r.status_code == 200, f"enviar áudio: {r.status_code} {r.text[:150]}")
pid3 = r.json()["id"]
j = espera(pid3, r.json()["job"])
check(j["status"] == "concluido", f"áudio virou vídeo ({j.get('error')})")
m3 = c.get(f"/api/projects/{pid3}/montagem").json()
nar = [x for x in m3["items"] if x["track"] == "t_audio"]
check(len(nar) == 1 and abs(nar[0]["dur"] - 12) < 0.3, "narração inteira na trilha de áudio")
cs = [x for x in m3["items"] if x["track"] == "t_v1"]
check(abs(cs[-1]["start"] + cs[-1]["dur"] - 12) < 0.3 and cs[0]["start"] == 0, "cenas cobrem o áudio todo")
lg = [x for x in m3["items"] if x["track"] == "t_legenda"]
check(abs(lg[0]["start"] - 0.5) < 0.01, "legenda no tempo da fala")

# ---------- 4) ao vivo ----------
r = c.post("/api/historia/ao-vivo", json={"formato": "16:9", "name": "Ao vivo"})
pid4 = r.json()["id"]
pedacos = []
for k in range(3):
    s = np.sin(np.arange(16000 * 4) * 2 * np.pi * 300 / 16000) * 8000
    pedacos.append(s.astype(np.int16).tobytes())
cont = [0]


def tr_vivo(wav, progress=None, prompt=""):
    k = cont[0]
    cont[0] += 1
    base = ["Era uma vez um menino.", "Ele morava perto do mar.", "Todo dia pescava com o pai."][k].split()
    return {"words": [{"w": p, "s": 0.3 + i * 0.4, "e": 0.6 + i * 0.4} for i, p in enumerate(base)]}


historia._transcrever = tr_vivo
inicios = []
for b in pedacos:
    r = c.post(f"/api/historia/{pid4}/ao-vivo/pedaco", content=b)
    inicios.append(r.json()["inicio"])
check(inicios == [0.0, 4.0, 8.0], f"pedaços com o tempo certo na gravação ({inicios})")
check(r.json()["palavras"][0]["s"] == 8.3, "palavra do 3º pedaço no tempo da gravação inteira")
r = c.post(f"/api/historia/{pid4}/ao-vivo/pedaco", content=np.zeros(16000, np.int16).tobytes())
check(r.json()["palavras"] == [], "silêncio não vai para a transcrição")
r = c.post(f"/api/historia/{pid4}/ao-vivo/terminar", json={"opcoes": {"formato": "16:9", "visual": "cores"}})
j = espera(pid4, r.json()["job"])
check(j["status"] == "concluido", f"ao vivo virou vídeo ({j.get('error')})")
m4 = c.get(f"/api/projects/{pid4}/montagem").json()
au = [x for x in m4["items"] if x["track"] == "t_audio"]
check(len(au) == 1 and abs(au[0]["dur"] - 13) < 0.2, "gravação inteira (13 s) na narração")
check(not (store.pdir(pid4) / "ao_vivo").exists(), "arquivos temporários da gravação apagados")
historia._transcrever = orig_tr

# ---------- 5) voz falhando não derruba o vídeo ----------
orig_narrar = historia.narrar


def narrar_quebrado(*a, **k):
    raise RuntimeError("sem internet")


historia.narrar = narrar_quebrado
r = c.post("/api/historia/texto", json={"texto": "Uma frase curta para testar. Outra frase aqui.",
                                        "opcoes": {"voz": "francisca", "visual": "cores"}})
j = espera(r.json()["id"], r.json()["job"])
check(j["status"] == "concluido" and "sem internet" in (j["result"].get("aviso") or ""), "sem voz: vídeo sai e avisa")
historia.narrar = orig_narrar

# ---------- 6) erros claros ----------
r = c.post("/api/historia/texto", json={"texto": "oi"})
check(r.status_code == 400, "texto vazio recusado")
r = c.post("/api/historia/audio", content=b"abc", headers={"x-filename": "x.txt"})
check(r.status_code == 400, "arquivo que não é áudio recusado")

print("\nFALHAS:", falhas)
sys.exit(1 if falhas else 0)

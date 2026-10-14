"""Testes da v1.10 — História → Vídeo completo: legenda animada (estilos do editor) na prévia e na exportação,
gráficos animados (barras, pizza, linha, número) com fundo transparente, movimentos de câmera variados, títulos
animados, abertura e encerramento com a marca, logo no canto, revisão das cenas antes de montar e voz offline."""
import json
import os
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DADOS = Path(tempfile.mkdtemp()) / "dados"
os.environ["EDITOR_DATA"] = str(DADOS)
os.environ["VOX_SEM_MANUTENCAO"] = "1"
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
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


def espera(pid, jid=None, kind=None, limite=600):
    t0 = time.time()
    while time.time() - t0 < limite:
        js = c.get(f"/api/jobs/{pid}").json()
        j = next((x for x in js if (jid and x["id"] == jid) or (kind and x["kind"] == kind)), None)
        if j and j["status"] in ("concluido", "erro", "cancelado"):
            return j
        time.sleep(0.4)
    return {"status": "tempo"}


def exporta(pid):
    c.post(f"/api/projects/{pid}/montagem/exportar", json={"resolucao": "720"})
    j = espera(pid, kind="montagem")
    if j["status"] != "concluido":
        return None, j
    return store.pdir(pid) / "renders" / Path(j["result"]["file"]).name, j


def quadro(video, t):
    out = Path(tempfile.mkdtemp()) / "q.png"
    subprocess.run([ff.ffmpeg(), "-loglevel", "error", "-y", "-ss", str(t), "-i", str(video), "-frames:v", "1", str(out)],
                   check=True)
    return cv2.imread(str(out))


HIST = """A Força da Fé

Em 2020, a pequena igreja tinha só 40 membros. Muitos achavam que ela fecharia as portas.
Mas o pastor reuniu o povo para orar todas as manhãs. Aos poucos, famílias inteiras começaram a chegar.
Hoje, 85% dos novos membros dizem que vieram por causa de um amigo. A fé que parecia pequena cresceu e deu frutos!"""
BASE = {"formato": "9:16", "voz": "nenhuma", "usar_ia": False, "visual": "cores", "musica": ""}

# ---------- 1) legenda animada e gráfico pela regra (porcentagem) ----------
r = c.post("/api/historia/texto", json={"texto": HIST, "opcoes": {**BASE, "legenda_estilo": "palavra_ativa"}}).json()
pid = r["id"]
j = espera(pid, r["job"])
check(j["status"] == "concluido", f"história com legenda animada ({j.get('error')})")
m = c.get(f"/api/projects/{pid}/montagem").json()
lv = m.get("legenda_viva")
check(lv and lv["cfg"]["style"] == "palavra_ativa" and len(lv["caps"]) >= 8, "legenda animada guardada na Montagem")
check(not [x for x in m["items"] if x["track"] == "t_legenda"], "sem legenda duplicada em texto")
check(any(w.get("kw") for cp in lv["caps"] for ln in cp["lines"] for w in ln), "palavras-chave marcadas na legenda")
titulos = [x for x in m["items"] if x["track"] == "t_titulo"]
check(titulos and "FORÇA" in titulos[0]["text"].upper() and titulos[0]["start"] < 0.5, "abertura com o título da história")
check(titulos and titulos[0].get("kf") and titulos[0]["kf"][0]["opacity"] == 0, "título entra animado (pulo)")
gr = [x for x in m["items"] if x["track"] == "t_v2"]
md = {x["id"]: x for x in m["media"]}
check(len(gr) == 1 and gr[0]["type"] == "video" and md[gr[0]["src"]].get("alpha"), "85% virou número animado (vídeo com alfa)")
cenas = [x for x in m["items"] if x["track"] == "t_v1"]
movs = {(round(x["kf"][0]["scale"], 2), round(x["kf"][0]["x"], 3), round(x["kf"][0]["y"], 3)) for x in cenas if x.get("kf")}
check(len(movs) >= min(3, len(cenas)), f"movimentos de câmera variados ({len(movs)} diferentes)")

# a Montagem salva pela tela (sem a legenda no pacote) não perde a legenda animada
m2 = dict(m)
m2.pop("legenda_viva")
salvo = c.put(f"/api/projects/{pid}/montagem", json=m2).json()
check(salvo.get("legenda_viva") and salvo["legenda_viva"]["caps"], "salvar pela tela mantém a legenda animada")

video, j = exporta(pid)
check(video is not None, f"exportou com legenda animada e gráfico animado ({j.get('error')})")
if video:
    info = ff.probe(str(video))
    tot = max(x["start"] + x["dur"] for x in m["items"])
    check(abs(info["duration"] - tot) < 0.5, f"duração certa ({info['duration']:.1f}s)")
    cap = lv["caps"][3]
    meio = (cap["s"] + cap["e"]) / 2
    q = quadro(video, meio)
    h = q.shape[0]
    faixa = q[int(h * 0.55):int(h * 0.92)]
    claros = (faixa.min(axis=2) > 225).mean()
    check(claros > 0.002, f"legenda queimada no vídeo exportado ({claros:.3%} de branco na faixa da legenda)")
    g = gr[0]
    q2 = quadro(video, g["start"] + g["dur"] - 0.5)
    alvo = np.array([0x3D, 0x8A, 0xFF])  # laranja da marca (BGR)
    laranja = (np.abs(q2.astype(int) - alvo).sum(axis=2) < 70).mean()
    check(laranja > 0.005, f"número do gráfico aparece no vídeo ({laranja:.3%} laranja)")

# desligar a legenda animada pela Montagem
m3 = c.get(f"/api/projects/{pid}/montagem").json()
m3["legenda_viva"]["off"] = True
salvo = c.put(f"/api/projects/{pid}/montagem", json=m3).json()
check(salvo["legenda_viva"].get("off"), "dá para desligar a legenda animada")

# ---------- 2) tipos de gráfico ----------
for g in ({"tipo": "pizza", "titulo": "Uso", "rotulos": ["A", "B", "C"], "valores": [50, 30, 20], "sufixo": "%"},
          {"tipo": "linha", "titulo": "Anos", "rotulos": ["2020", "2021", "2022"], "valores": [40, 90, 160]},
          {"tipo": "barras", "titulo": "Igrejas", "rotulos": ["A", "B"], "valores": [3, 7]}):
    gl = historia._grafico_limpo(g)
    q0 = np.array(historia.quadro_grafico(gl, 800, 500, 0.0, "#FF8A3D"))
    q1 = np.array(historia.quadro_grafico(gl, 800, 500, 1.0, "#FF8A3D"))
    lar = lambda a: (np.abs(a[..., :3].astype(int) - [255, 138, 61]).sum(axis=2) < 40).mean()  # noqa: E731
    check(lar(q1) > lar(q0) + 0.002, f"gráfico '{g['tipo']}' se desenha com o tempo")
check(historia._grafico_limpo({"tipo": "numero", "valores": [12500], "rotulos": ["vidas"]})["tipo"] == "numero", "gráfico de número")
check(historia._grafico_limpo({"tipo": "pizza", "rotulos": ["a"], "valores": [1]}) is None, "pizza com uma fatia recusada")
check(historia.grafico_por_regra("Hoje 85% dos membros vieram por amigos.")["valores"] == [85.0], "regra acha a porcentagem")
check(historia.grafico_por_regra("Sem números aqui.") is None, "sem porcentagem, sem gráfico")

# ---------- 3) encerramento com a marca e logo no canto ----------
store.save_config({"brand": {"handle": "radioestacaogospel", "color": "#FF8A3D", "bg": "#101114"}})
ok, png = cv2.imencode(".png", np.full((300, 300, 3), (0, 200, 0), np.uint8))
(store.BRAND_DIR / "logo.png").write_bytes(png.tobytes())
r = c.post("/api/historia/texto", json={"texto": "Uma frase curta aqui. Outra frase para fechar.",
                                        "opcoes": {**BASE, "encerramento": True, "logo": True, "formato": "16:9"}}).json()
j = espera(r["id"], r["job"])
m = c.get(f"/api/projects/{r['id']}/montagem").json()
cor = [x for x in m["items"] if x["type"] == "color"]
textos = [x["text"] for x in m["items"] if x["type"] == "text"]
logos = [x for x in m["items"] if x["track"] == "t_logo"]
check(j["status"] == "concluido" and cor and abs(cor[0]["dur"] - 3) < 0.01, "encerramento de 3 s no fim")
check("@radioestacaogospel" in textos and any("Inscreva-se" in t for t in textos), "encerramento com o @ e a chamada")
check(logos and logos[0]["scale"] < 0.2 and logos[0]["x"] > 0.8, "logo pequena no canto o vídeo todo")
mus_fim = max(x["start"] + x["dur"] for x in m["items"])
check(abs(mus_fim - (cor[0]["start"] + 3)) < 0.01, "vídeo termina no fim do encerramento")
video, j2 = exporta(r["id"])
check(video is not None, f"exportou com encerramento e logo ({j2.get('error')})")
(store.BRAND_DIR / "logo.png").unlink()
store.save_config({"brand": {"handle": ""}})

# ---------- 4) revisar as cenas antes de montar ----------
rt = c.post("/api/historia/roteiro", json={"texto": HIST, "opcoes": {"usar_ia": False}}).json()
check(rt["modo"] == "local" and len(rt["cenas"]) >= 2 and all(x["texto"] for x in rt["cenas"]), "roteiro com as cenas")
cenas_ed = rt["cenas"]
cenas_ed[0]["destaque"] = "Título que eu escrevi"
cenas_ed[1]["texto"] = "Texto trocado por mim na revisão."
cenas_ed[1]["busca"] = "igreja cheia"
r = c.post("/api/historia/texto", json={"texto": HIST, "cenas": cenas_ed, "opcoes": {**BASE, "humor": "epico"}}).json()
j = espera(r["id"], r["job"])
m = c.get(f"/api/projects/{r['id']}/montagem").json()
tt = [x["text"] for x in m["items"] if x["track"] == "t_titulo"]
pal = " ".join(w["w"] for cp in (m.get("legenda_viva") or {}).get("caps", []) for ln in cp["lines"] for w in ln)
check(j["status"] == "concluido" and j["result"]["modo"] == "revisado", "montou com as cenas revisadas")
check(any("ESCREVI" in t.upper() for t in tt), "título editado na revisão entrou no vídeo")
check("TROCADO" in pal.upper(), "texto editado na revisão virou a legenda")
check(store.load(r["id"])["historia"]["cenas"][1]["busca"] == "igreja cheia", "busca editada guardada")

# ---------- 5) voz offline (Piper) — simulada ----------
import types  # noqa: E402


class VozFalsa:
    @staticmethod
    def load(caminho):
        return VozFalsa()

    def synthesize_wav(self, texto, wf, syn_config=None):
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22050)
        wf.writeframes((np.sin(np.arange(22050 * 2) / 8) * 9000).astype(np.int16).tobytes())


mod = types.ModuleType("piper")
mod.PiperVoice = VozFalsa
mod.SynthesisConfig = lambda **k: k
sys.modules["piper"] = mod
orig_modelo = historia._modelo_piper
historia._modelo_piper = lambda voz: Path("/nao/precisa.onnx")
st = c.get("/api/historia/status").json()
check(any(v["id"] == "faber" and v["ok"] for v in st["vozes"]), "voz offline Faber aparece disponível")
check(st["estilos_legenda"].get("destaque") == "Karaokê", "estilos de legenda na tela")
r = c.post("/api/historia/texto", json={"texto": "Primeira frase falada. Segunda frase falada.",
                                        "opcoes": {**BASE, "voz": "faber"}}).json()
j = espera(r["id"], r["job"])
m = c.get(f"/api/projects/{r['id']}/montagem").json()
nar = [x for x in m["items"] if x["track"] == "t_audio"]
check(j["status"] == "concluido" and nar and abs(nar[0]["dur"] - 2.0) < 0.1, "narração pela voz offline")
historia._modelo_piper = orig_modelo
del sys.modules["piper"]

print("\nFALHAS:", falhas)
sys.exit(1 if falhas else 0)

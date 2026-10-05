"""Testes da v1.2: transições, quadros-chave (animação), filtros de cor, vinheta, fundo verde e texto animado.
Exporta de verdade com o FFmpeg e confere alguns quadros do vídeo pronto."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["EDITOR_DATA"] = str(ROOT / "teste_dados")
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import app as appmod  # noqa: E402
from backend.core import efeitos as fxm  # noqa: E402
from backend.engine import ffmpeg_tools as ff  # noqa: E402

c = TestClient(appmod.app)
falhas = 0


def check(cond, msg):
    global falhas
    print(("OK   " if cond else "FALHOU ") + msg)
    if not cond:
        falhas += 1


tmp = Path(tempfile.mkdtemp())
F = ff.ffmpeg()
# vídeo vermelho, vídeo azul, "fundo verde" com um quadrado branco, foto
subprocess.run([F, "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=640x360:r=30:d=6", "-f", "lavfi",
                "-i", "sine=f=330:d=6", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                str(tmp / "vermelho.mp4")], check=True)
subprocess.run([F, "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=640x360:r=30:d=6", "-f", "lavfi",
                "-i", "sine=f=440:d=6", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                str(tmp / "azul.mp4")], check=True)
subprocess.run([F, "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=0x00FF00:s=640x360:r=30:d=6",
                "-vf", "drawbox=x=270:y=130:w=100:h=100:color=white:t=fill", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                str(tmp / "verde.mp4")], check=True)
cv2.imwrite(str(tmp / "foto.png"), np.full((400, 400, 3), (40, 200, 240), "uint8"))

r = c.post("/api/montagem/novo", json={"name": "Teste 1.2", "formato": "16:9"})
pid = r.json()["id"]
m = c.get(f"/api/projects/{pid}/montagem").json()
ids = {}
for nome in ("vermelho.mp4", "azul.mp4", "verde.mp4", "foto.png"):
    r = c.post(f"/api/projects/{pid}/midias", content=(tmp / nome).read_bytes(), headers={"x-filename": nome})
    check(r.status_code == 200, f"envia {nome}")
    ids[nome] = r.json()["id"]


def base(**kw):
    it = {"id": kw.pop("id"), "type": "video", "track": "t_v1", "x": 0.5, "y": 0.5, "scale": 1, "rot": 0,
          "opacity": 1, "volume": 1, "fadeIn": 0, "fadeOut": 0, "speed": 1, "fit": "cover", "in": 0}
    it.update(kw)
    return it


# 0-3 s vermelho, 3-6 s azul entrando com "dissolver" de 1 s
m["items"] = [
    base(id="a", src=ids["vermelho.mp4"], start=0, dur=3),
    base(id="b", src=ids["azul.mp4"], start=3, dur=3, tr={"tipo": "dissolver", "dur": 1.0}),
]
r = c.put(f"/api/projects/{pid}/montagem", json=m)
salvo = r.json()
check(salvo["items"][1].get("tr") == {"tipo": "dissolver", "dur": 1.0}, "transição é salva")
check("tr" not in salvo["items"][0], "item sem transição não ganha transição")


def exporta(nome):
    r = c.post(f"/api/projects/{pid}/montagem/exportar", json={"quality": "rapida"})
    check(r.status_code == 200, f"exportação começou ({nome})")
    import time
    for _ in range(600):
        js = c.get(f"/api/jobs/{pid}").json()
        j = next((x for x in js if x["kind"] == "montagem"), None)
        if j and j["status"] in ("concluido", "erro"):
            break
        time.sleep(0.25)
    check(j and j["status"] == "concluido", f"exportou ({nome}) {'' if not j else (j.get('error') or '')[:300]}")
    P = c.get(f"/api/projects/{pid}").json()
    return ROOT / "teste_dados" / "projetos" / pid / "renders" / P["renders"][0]["file"]


def quadro(arq, t):
    out = tmp / f"q{t}.png"
    subprocess.run([F, "-loglevel", "error", "-y", "-ss", f"{t}", "-i", str(arq), "-frames:v", "1", str(out)],
                   check=True)
    return cv2.imread(str(out))  # BGR


def cor(img, x=0.5, y=0.5):
    h, w = img.shape[:2]
    return tuple(int(v) for v in img[int(h * y), int(w * x)][::-1])  # RGB


arq = exporta("dissolver")
q1, q2, q3 = cor(quadro(arq, 2.5)), cor(quadro(arq, 3.5)), cor(quadro(arq, 5.0))
check(q1[0] > 200 and q1[2] < 50, f"antes da transição: vermelho {q1}")
check(q2[0] > 60 and q2[2] > 60, f"no meio do dissolver: mistura de vermelho e azul {q2}")
check(q3[2] > 200 and q3[0] < 50, f"depois: azul {q3}")
dur = float(ff.probe(str(arq))["duration"])
check(abs(dur - 6.0) < 0.1, f"duração não muda com a transição ({dur:.2f}s)")

# deslizar da direita: no meio, metade esquerda ainda vermelha, metade direita azul
m["items"][1]["tr"] = {"tipo": "deslizar_d", "dur": 1.0}
c.put(f"/api/projects/{pid}/montagem", json=m)
arq = exporta("deslizar")
img = quadro(arq, 3.3)
check(cor(img, 0.1)[0] > 200 and cor(img, 0.95)[2] > 200, f"deslizar: esquerda {cor(img, 0.1)} direita {cor(img, 0.95)}")

# passar pelo preto: no meio fica escuro
m["items"][1]["tr"] = {"tipo": "preto", "dur": 1.0}
c.put(f"/api/projects/{pid}/montagem", json=m)
arq = exporta("preto")
q = cor(quadro(arq, 3.5))
check(sum(q) < 60, f"passar pelo preto: escuro no meio {q}")

# quadros-chave: foto pequena que cresce e anda; filtro P&B na foto; vinheta no vídeo
m["items"] = [
    base(id="a", src=ids["vermelho.mp4"], start=0, dur=4, fx={"vinheta": 1.0}),
    base(id="f", type="image", track="t_v2", src=ids["foto.png"], start=0, dur=4, fit="contain", scale=0.2,
         kf=[{"t": 0, "x": 0.2, "y": 0.5, "scale": 0.2, "rot": 0, "opacity": 1, "e": "linear"},
             {"t": 4, "x": 0.8, "y": 0.5, "scale": 0.5, "rot": 0, "opacity": 1, "e": "linear"}],
         fx={"pb": 1.0}),
]
r = c.put(f"/api/projects/{pid}/montagem", json=m)
check(len(r.json()["items"][1]["kf"]) == 2, "quadros-chave salvos")
check(r.json()["items"][1]["fx"]["pb"] == 1.0, "filtro salvo")
arq = exporta("quadros-chave")
im0, im3 = quadro(arq, 0.2), quadro(arq, 3.8)
p0 = cor(im0, 0.21)
check(abs(p0[0] - p0[1]) < 12 and abs(p0[1] - p0[2]) < 12 and p0[0] > 100, f"foto em preto e branco no começo {p0}")
check(cor(im0, 0.8)[0] > 150, f"no começo a foto ainda não chegou na direita {cor(im0, 0.8)}")
check(sum(cor(im3, 0.8)) > 300 and abs(cor(im3, 0.8)[0] - cor(im3, 0.8)[2]) < 12,
      f"no fim a foto está na direita {cor(im3, 0.8)}")
canto, meio = cor(im0, 0.01, 0.01), cor(im0, 0.5, 0.1)
check(canto[0] < 60 and meio[0] > 150, f"vinheta escurece o canto {canto} e não o meio {meio}")
# valor() igual à expressão do FFmpeg
it = r.json()["items"][1]
check(abs(fxm.valor(it, "x", 2.0) - 0.5) < 1e-6, "interpolação no meio (linear)")

# fundo verde: o vermelho aparece onde era verde; o quadrado branco fica
m["items"] = [
    base(id="a", src=ids["vermelho.mp4"], start=0, dur=3),
    base(id="g", track="t_v2", src=ids["verde.mp4"], start=0, dur=3, fit="contain",
         chroma={"on": True, "cor": "#00FF00", "tol": 0.3, "suave": 0.05}),
]
c.put(f"/api/projects/{pid}/montagem", json=m)
arq = exporta("fundo verde")
img = quadro(arq, 1.0)
check(cor(img, 0.1)[0] > 200 and cor(img, 0.1)[1] < 60, f"fundo verde virou transparente {cor(img, 0.1)}")
check(min(cor(img, 0.5)) > 200, f"o que não é verde continua {cor(img, 0.5)}")

# texto animado (escala de 0.5 a 1.5 e girando) + zoom de entrada
m["items"] = [
    base(id="a", src=ids["vermelho.mp4"], start=0, dur=3),
    base(id="b", src=ids["azul.mp4"], start=3, dur=3, tr={"tipo": "zoom_in", "dur": 0.8}),
    {"id": "t", "type": "text", "track": "t_texto", "start": 0, "dur": 6, "x": 0.5, "y": 0.5, "scale": 1,
     "rot": 0, "opacity": 1, "fadeIn": 0, "fadeOut": 0, "text": "Olá, VOX!", "font": "Poppins ExtraBold",
     "size": 0.1, "color": "#FFFFFF", "strokeW": 0.05, "stroke": "#000000",
     "kf": [{"t": 0, "x": 0.5, "y": 0.5, "scale": 0.5, "rot": 0, "opacity": 1, "e": "suave"},
            {"t": 3, "x": 0.5, "y": 0.5, "scale": 1.5, "rot": 20, "opacity": 0.5, "e": "suave"}]},
]
r = c.put(f"/api/projects/{pid}/montagem", json=m)
check(r.json()["items"][2].get("kf"), "quadros-chave no texto")
arq = exporta("texto animado")
check(abs(float(ff.probe(str(arq))["duration"]) - 6.0) < 0.1, "texto animado: duração certa")
img = quadro(arq, 4.0)
check(cor(img, 0.05)[2] > 200, f"zoom de entrada terminou: azul na borda {cor(img, 0.05)}")

# sem nada novo: continua igual (caminho antigo)
m["items"] = [base(id="a", src=ids["vermelho.mp4"], start=0, dur=2)]
c.put(f"/api/projects/{pid}/montagem", json=m)
arq = exporta("simples")
check(cor(quadro(arq, 1.0))[0] > 200, "montagem simples continua funcionando")

# ---------------- remover fundo com IA (modelo rápido, baixado na primeira vez)
c.put("/api/settings", json={"fundo": {"qualidade": "rapida"}})
st = c.get("/api/fundo/status").json()
check(st["disponivel"] and st["qualidade"] == "rapida", f"remoção de fundo disponível {st}")
subprocess.run([F, "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=0x3060A0:s=480x270:r=30:d=4", "-f", "lavfi",
                "-i", "sine=d=4", "-vf", "drawbox=x=180:y=60:w=120:h=180:color=0xF0C8A0:t=fill", "-c:v", "libx264",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(tmp / "pessoa.mp4")], check=True)
r = c.post(f"/api/projects/{pid}/midias", content=(tmp / "pessoa.mp4").read_bytes(), headers={"x-filename": "pessoa.mp4"})
ids["pessoa.mp4"] = r.json()["id"]
m["items"] = [
    base(id="a", src=ids["vermelho.mp4"], start=0, dur=3),
    base(id="sf", track="t_v2", src=ids["pessoa.mp4"], start=0, dur=2, **{"in": 1.0}),
    base(id="sfi", type="image", track="t_v2", src=ids["foto.png"], start=2, dur=1, fit="contain"),
]
c.put(f"/api/projects/{pid}/montagem", json=m)


def espera(job_id, nome):
    import time
    for _ in range(1200):
        j = next((x for x in c.get(f"/api/jobs/{pid}").json() if x["id"] == job_id), None)
        if j and j["status"] in ("concluido", "erro"):
            break
        time.sleep(0.25)
    check(j and j["status"] == "concluido", f"{nome} terminou {'' if not j else (j.get('error') or '')[:200]}")
    return j


j = espera(c.post(f"/api/projects/{pid}/montagem/sem-fundo", json={"item": "sf"}).json()["job"], "tirar fundo do vídeo")
md = j["result"]["media"]
check(md.get("alpha") and md.get("semfundo") and md["preview"] == md["file"], "vídeo sem fundo: WebM com transparência")
check(md["substitui"]["item"] == "sf" and abs(md["substitui"]["in"] - 0.7) < 1e-6, f"marcado para trocar o pedaço {md['substitui']}")
check(md.get("has_audio"), "vídeo sem fundo mantém o som do trecho")
j = espera(c.post(f"/api/projects/{pid}/montagem/sem-fundo", json={"item": "sfi"}).json()["job"], "tirar fundo da foto")
check(j["result"]["media"]["file"].endswith(".png"), "foto sem fundo vira PNG")
# a tela troca o pedaço; aqui simulamos o que o montagem.js faz
mm = c.get(f"/api/projects/{pid}/montagem").json()
m["items"][1]["src"], m["items"][1]["in"] = md["id"], 0.3
c.put(f"/api/projects/{pid}/montagem", json=m)
c.post(f"/api/projects/{pid}/midias/{md['id']}/aplicado")
mm = c.get(f"/api/projects/{pid}/montagem").json()
check(not next(x for x in mm["media"] if x["id"] == md["id"]).get("substitui"), "troca marcada como feita")
arq = exporta("vídeo sem fundo")
check(abs(float(ff.probe(str(arq))["duration"]) - 3.0) < 0.1, "exporta com o vídeo sem fundo (transparência lida)")

# ---------------- bancos grátis (sem internet: respostas simuladas)
from backend.core import bancos  # noqa: E402


class Resp:
    def __init__(self, dados, status=200):
        self.status_code, self._d, self.text, self.headers = status, dados, "", {}

    def json(self):
        return self._d

    def raise_for_status(self):
        pass


def falso_get(url, params=None, headers=None, timeout=None):
    if "pexels" in url:
        return Resp({"videos": [{"id": 1, "url": "https://pexels.com/v/1", "image": "https://img/1.jpg", "duration": 9,
                                 "user": {"name": "Ana"}, "video_files": [
                                     {"link": "https://v/4k.mp4", "width": 3840, "height": 2160, "file_type": "video/mp4"},
                                     {"link": "https://v/hd.mp4", "width": 1920, "height": 1080, "file_type": "video/mp4"},
                                     {"link": "https://v/sd.mp4", "width": 640, "height": 360, "file_type": "video/mp4"}]}],
                     "next_page": "x"})
    return Resp({"totalHits": 1, "hits": [{"id": 7, "pageURL": "https://pixabay.com/v/7", "duration": 5, "user": "Beto",
                                           "tags": "céu, nuvens", "videos": {
                                               "large": {"url": "https://p/l.mp4", "width": 1920, "height": 1080, "thumbnail": "t"},
                                               "tiny": {"url": "https://p/t.mp4", "width": 640, "height": 360, "thumbnail": "t2"}}}]})


class Stream:
    def __init__(self, *a, **k):
        self.status_code, self.headers = 200, {"content-length": str((tmp / "azul.mp4").stat().st_size)}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_bytes(self, n):
        yield (tmp / "azul.mp4").read_bytes()


bancos.httpx.get, bancos.httpx.stream = falso_get, Stream
r = c.get("/api/bancos/buscar?tipo=video&q=céu")
check(r.status_code == 400 and "chave" in r.json()["detail"], "sem chave: avisa onde colocar")
c.put("/api/settings", json={"pexels": {"api_key": "abc"}, "pixabay": {"api_key": "def"}})
cfg = c.get("/api/settings").json()
check(cfg["pexels"]["api_key"] == "" and cfg["pexels"]["api_key_set"], "a chave do banco não volta para o navegador")
r = c.get("/api/bancos/buscar?tipo=video&q=céu").json()
check(len(r["itens"]) == 2 and r["itens"][0]["fonte"] == "pexels" and r["itens"][1]["fonte"] == "pixabay",
      "busca nos dois bancos, intercalados")
check(r["itens"][0]["baixar"] == "https://v/hd.mp4", "escolhe o arquivo Full HD (não o 4K)")
r = c.post(f"/api/projects/{pid}/bancos/pexels-v-1").json()
j = espera(r["job"], "baixar do banco")
check(j["result"]["credito"].startswith("Vídeo: Ana / Pexels"), "crédito guardado na mídia")
check(c.post(f"/api/projects/{pid}/bancos/pexels-v-999").status_code == 404, "não baixa o que não veio da busca")

print("\nTudo certo!" if not falhas else f"\n{falhas} FALHA(S)")
sys.exit(1 if falhas else 0)

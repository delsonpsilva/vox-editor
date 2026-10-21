"""Testes da v1.13 (Super Pacote 2, parte 2) na Montagem: fundo desfocado (exportação de verdade, vídeo e foto)
e figurinhas."""
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
import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import app as appmod  # noqa: E402
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
# vídeo deitado: metade de cima verde, metade de baixo azul (o desfoque espalha essas cores para as faixas)
subprocess.run([F, "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=green:s=640x360:r=30:d=3", "-f", "lavfi",
                "-i", "color=c=blue:s=640x180:r=30:d=3", "-filter_complex", "[0][1]overlay=0:180", "-f", "lavfi",
                "-i", "sine=f=330:d=3", "-map", "0:v", "-map", "2:a", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", str(tmp / "deitado.mp4")], check=True)
subprocess.run([F, "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=green:s=640x360:r=30:d=3", "-f", "lavfi",
                "-i", "color=c=blue:s=640x180:r=30:d=3", "-filter_complex", "[0][1]overlay=0:180", "-frames:v", "1",
                "-update", "1", str(tmp / "foto.png")], check=True)

pid = c.post("/api/montagem/novo", json={"name": "Teste 1.13", "formato": "9:16"}).json()["id"]
c.get(f"/api/projects/{pid}/montagem")
vid = c.post(f"/api/projects/{pid}/midias", content=(tmp / "deitado.mp4").read_bytes(), headers={"x-filename": "deitado.mp4"}).json()["id"]
foto = c.post(f"/api/projects/{pid}/midias", content=(tmp / "foto.png").read_bytes(), headers={"x-filename": "foto.png"}).json()["id"]


def item(**kw):
    it = {"id": kw.pop("id"), "type": "video", "track": "t_v1", "x": 0.5, "y": 0.5, "scale": 1, "rot": 0,
          "opacity": 1, "volume": 1, "fadeIn": 0, "fadeOut": 0, "speed": 1, "fit": "contain", "in": 0}
    it.update(kw)
    return it


m = c.get(f"/api/projects/{pid}/montagem").json()
m["items"] = [item(id="v1", src=vid, start=0, dur=2, fundoDesf=True),
              item(id="f1", type="image", src=foto, start=2, dur=1, fundoDesf=True),
              item(id="t1", type="text", track="t_texto", start=0, dur=1, text="Oi", fundoDesf=True, font="Poppins", size=0.07,
                   color="#FFFFFF", stroke="#000000", strokeW=0, box="#000000", boxOn=False, boxAlpha=0.6, upper=False)]
m = c.put(f"/api/projects/{pid}/montagem", json=m).json()
its = {i["id"]: i for i in m["items"]}
check(its["v1"].get("fundoDesf") is True and its["f1"].get("fundoDesf") is True, "fundo desfocado guardado em vídeo e foto")
check("fundoDesf" not in its["t1"], "texto não guarda fundo desfocado")


def exportar(nome):
    feitos = {j["id"] for j in c.get(f"/api/jobs/{pid}").json() if j["kind"] == "montagem"}
    r = c.post(f"/api/projects/{pid}/montagem/exportar", json={"quality": "rapida", "resolucao": "720"})
    check(r.status_code == 200, f"exportação começou ({nome})")
    j = None
    for _ in range(1200):
        js = c.get(f"/api/jobs/{pid}").json()
        j = next((x for x in js if x["kind"] == "montagem" and x["id"] not in feitos
                  and x["status"] in ("concluido", "erro", "cancelado")), None)
        if j:
            break
        time.sleep(0.25)
    check(j and j["status"] == "concluido", f"exportou ({nome}) {'' if not j else (j.get('error') or '')[:400]}")
    P = c.get(f"/api/projects/{pid}").json()
    return DADOS / "projetos" / pid / "renders" / P["renders"][0]["file"]


def quadro(arq, t):
    out = tmp / f"q{time.time_ns()}.png"
    subprocess.run([F, "-loglevel", "error", "-y", "-ss", f"{t}", "-i", str(arq), "-frames:v", "1", str(out)], check=True)
    return cv2.imread(str(out))


arq = exportar("com fundo desfocado")
for t, nome in ((1.0, "vídeo"), (2.5, "foto")):
    q = quadro(arq, t)
    h = q.shape[0]
    topo, meio, base = q[int(h * 0.08)], q[h // 2], q[int(h * 0.92)]
    check(topo.mean() > 25 and base.mean() > 25, f"{nome}: as faixas de cima e de baixo não ficam pretas (brilho {topo.mean():.0f} / {base.mean():.0f})")
    check(topo[:, 1].mean() > topo[:, 0].mean() and base[:, 0].mean() > base[:, 1].mean(),
          f"{nome}: o fundo é a própria imagem desfocada (verde em cima, azul embaixo)")
    check(meio[:, 1].mean() > 90 or meio[:, 0].mean() > 90, f"{nome}: a imagem nítida continua no meio, por cima")
# o pedaço original continua igual: só o vídeo no meio, nítido
q = quadro(arq, 1.0)
h, w = q.shape[:2]
faixa_video = q[int(h / 2 - w * 9 / 16 / 2) + 6:int(h / 2 - w * 9 / 16 / 2) + 30]
check(faixa_video[:, :, 1].mean() > 100 and faixa_video[:, :, 0].mean() < 40, "vídeo nítido no meio (verde puro, sem desfoque por cima)")

# sem o fundo: faixas pretas (confere que é o fundo desfocado que preenche)
m = c.get(f"/api/projects/{pid}/montagem").json()
for i in m["items"]:
    i.pop("fundoDesf", None)
c.put(f"/api/projects/{pid}/montagem", json=m)
q = quadro(exportar("sem fundo desfocado"), 1.0)
check(q[int(q.shape[0] * 0.08)].mean() < 8, "sem o fundo desfocado as faixas ficam pretas")

# ---------- figurinhas ----------
lst = c.get("/api/figurinhas").json()
check(len(lst) >= 50 and all(x["arquivo"].endswith(".png") for x in lst), f"lista de figurinhas ({len(lst)})")
r = c.get(f"/api/figurinhas/{lst[0]['arquivo']}")
check(r.status_code == 200 and r.content[:4] == b"\x89PNG", "imagem da figurinha")
check(c.get("/api/figurinhas/..%2F..%2Fbackend%2Fapp.py").status_code == 404, "não deixa ler outros arquivos")
r = c.post(f"/api/projects/{pid}/montagem/figurinha", json={"arquivo": lst[0]["arquivo"]})
md = r.json()
check(r.status_code == 200 and md["kind"] == "image" and md.get("figurinha") == lst[0]["arquivo"], f"figurinha nas mídias ({md.get('name')})")
r2 = c.post(f"/api/projects/{pid}/montagem/figurinha", json={"arquivo": lst[0]["arquivo"]})
check(r2.json()["id"] == md["id"], "a mesma figurinha não é copiada duas vezes")
check(c.post(f"/api/projects/{pid}/montagem/figurinha", json={"arquivo": "nada.png"}).status_code == 404, "figurinha inexistente dá 404")

print()
print("RESULTADO:", "TUDO OK" if falhas == 0 else f"{falhas} FALHA(S)")
sys.exit(1 if falhas else 0)

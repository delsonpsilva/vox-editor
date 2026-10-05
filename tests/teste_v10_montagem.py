"""Testes da v1.0: Montagem (editor manual multicamadas).
Cria mídias de teste com o FFmpeg, monta uma linha do tempo com vídeo, imagem, texto, cor e áudio,
exporta e confere o arquivo final. Não precisa de transcrição nem de internet."""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["EDITOR_DATA"] = str(ROOT / "teste_dados")
sys.path.insert(0, str(ROOT))

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
subprocess.run([F, "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=10", "-f", "lavfi", "-i",
                "sine=f=440:d=10", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                str(tmp / "video.mp4")], check=True)
subprocess.run([F, "-loglevel", "error", "-y", "-f", "lavfi", "-i", "mandelbrot=s=800x600", "-frames:v", "1",
                str(tmp / "foto.png")], check=True)
subprocess.run([F, "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=12", str(tmp / "musica.mp3")], check=True)

r = c.post("/api/montagem/novo", json={"name": "Teste da montagem", "formato": "9:16"})
check(r.status_code == 200, "cria projeto em branco")
pid = r.json()["id"]
p = c.get(f"/api/projects/{pid}").json()
check(p.get("kind") == "montagem" and p["status"] == "pronto", "projeto em branco não passa por análise")
m = c.get(f"/api/projects/{pid}/montagem").json()
check(m["w"] == 1080 and m["h"] == 1920 and not m["items"], "montagem vertical vazia")

ids = {}
for nome in ("video.mp4", "foto.png", "musica.mp3"):
    r = c.post(f"/api/projects/{pid}/midias", content=(tmp / nome).read_bytes(), headers={"x-filename": nome})
    check(r.status_code == 200, f"envia {nome} ({r.json().get('kind')})")
    ids[nome] = r.json()["id"]
r = c.post(f"/api/projects/{pid}/midias", content=b"abc", headers={"x-filename": "planilha.xlsx"})
check(r.status_code == 400, "recusa arquivo que não é mídia")

v = ids["video.mp4"]
m["tracks"].append({"id": "t_fundo", "kind": "video", "name": "Fundo"})
m["items"] = [
    {"id": "a", "type": "color", "track": "t_fundo", "start": 0, "dur": 8, "color": "#203060"},
    {"id": "b", "type": "video", "track": "t_v1", "src": v, "start": 0, "dur": 3, "in": 1, "fit": "cover"},
    {"id": "c", "type": "video", "track": "t_v1", "src": v, "start": 3, "dur": 2, "in": 6, "fit": "cover"},
    {"id": "d", "type": "video", "track": "t_v2", "src": v, "start": 1, "dur": 3, "in": 0, "scale": 0.4, "x": 0.7,
     "y": 0.25, "rot": 10, "opacity": 0.9, "fadeIn": 0.5, "speed": 1.5, "volume": 0.3},
    {"id": "e", "type": "image", "track": "t_v2", "src": ids["foto.png"], "start": 5, "dur": 3, "scale": 0.8, "fadeOut": 1},
    {"id": "f", "type": "text", "track": "t_texto", "start": 0.5, "dur": 6, "text": "Olá: 'teste' 100%\nsegunda linha",
     "size": 0.06, "y": 0.8, "strokeW": 0.08, "fadeIn": 0.4, "boxOn": True},
    {"id": "g", "type": "audio", "track": "t_audio", "src": ids["musica.mp3"], "start": 0, "dur": 8, "in": 2,
     "volume": 0.4, "fadeOut": 2},
    {"id": "x", "type": "video", "track": "t_v1", "src": "nao-existe", "start": 9, "dur": 1},
]
r = c.put(f"/api/projects/{pid}/montagem", json=m)
check(r.status_code == 200 and len(r.json()["items"]) == 7, "salva e descarta pedaço com mídia inexistente")

c.post(f"/api/projects/{pid}/montagem/exportar", json={})
job = None
for _ in range(240):
    job = next(j for j in c.get(f"/api/jobs/{pid}").json() if j["kind"] == "montagem")
    if job["status"] in ("concluido", "erro"):
        break
    time.sleep(0.5)
check(job["status"] == "concluido", f"exporta a montagem ({job.get('error') or job['status']})")
if job["status"] == "concluido":
    out = appmod.store.pdir(pid) / "renders" / job["result"]["file"]
    info = ff.probe(str(out))
    check(info["width"] == 1080 and info["height"] == 1920, "vídeo final em 1080x1920")
    check(abs(info["duration"] - 8.0) < 0.15, f"duração certa ({info['duration']:.2f}s)")
    check(info["has_audio"], "vídeo final tem som")

r = c.delete(f"/api/projects/{pid}/midias/{ids['foto.png']}")
check(r.status_code == 200 and not any(i.get("src") == ids["foto.png"] for i in r.json()["items"]),
      "remover mídia tira os pedaços dela")
c.delete(f"/api/projects/{pid}")
print("\nTUDO CERTO" if not falhas else f"\n{falhas} FALHA(S)")
sys.exit(1 if falhas else 0)

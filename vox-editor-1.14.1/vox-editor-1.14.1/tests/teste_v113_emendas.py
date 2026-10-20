"""Testes da v1.1.3: exportação com muitos pedaços (igual a um projeto vindo da edição automática),
grafo longo passado por arquivo (FFmpeg novo e antigo) e emendas suaves sem perder a sincronia."""
import json
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


print("FFmpeg:", ff.run([ff.ffmpeg(), "-version"]).stdout.splitlines()[0][:60], "| arquivo de filtro:",
      ff._filter_file_style())
tmp = Path(tempfile.mkdtemp())
F = ff.ffmpeg()
subprocess.run([F, "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=120", "-f", "lavfi",
                "-i", "sine=f=330:d=120", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", str(tmp / "pregacao.mp4")], check=True)

r = c.post("/api/montagem/novo", json={"name": "Teste emendas", "formato": "16:9"})
pid = r.json()["id"]
m = c.get(f"/api/projects/{pid}/montagem").json()
check(m.get("suave") == "suave", "montagem nova já vem com emendas suaves")
v = c.post(f"/api/projects/{pid}/midias", content=(tmp / "pregacao.mp4").read_bytes(),
           headers={"x-filename": "pregacao.mp4"}).json()["id"]

# 150 pedaços seguidos tirando pausas (como a edição automática faz): 0.5s mantido, 0.2s cortado
items, t, src_t = [], 0.0, 0.0
for k in range(150):
    items.append({"id": f"p{k}", "type": "video", "track": "t_v1", "src": v, "start": round(t, 4), "dur": 0.5,
                  "in": round(src_t, 4), "fit": "cover"})
    t += 0.5
    src_t += 0.7
m["items"] = items


def exporta(suave):
    m["suave"] = suave
    r = c.put(f"/api/projects/{pid}/montagem", json=m)
    check(r.status_code == 200 and r.json().get("suave") == suave, f"salva emendas '{suave}'")
    r = c.post(f"/api/projects/{pid}/montagem/exportar", json={"quality": "rapida"})
    check(r.status_code == 200, f"pede a exportação ({suave})")
    for _ in range(600):
        st = c.get(f"/api/projects/{pid}").json()
        job = next((j for j in st.get("jobs") or [] if j.get("kind") == "montagem"), None)
        if job and job.get("status") in ("concluido", "erro"):
            break
        time.sleep(1)
    check(job and job.get("status") == "concluido", f"exportou com emendas '{suave}' "
          f"({(job or {}).get('error') or (job or {}).get('msg') or ''})"[:200])
    rend = c.get(f"/api/projects/{pid}").json()["renders"][0]
    out = ROOT / "teste_dados" / "projects" / pid / "renders" / rend["file"]
    if not out.exists():
        out = next((ROOT / "teste_dados").rglob(rend["file"]))
    info = json.loads(subprocess.run([ff.ffprobe(), "-v", "error", "-show_streams", "-of", "json", str(out)],
                                     capture_output=True, text=True).stdout)
    durs = {s["codec_type"]: float(s.get("duration") or 0) for s in info["streams"]}
    check(abs(durs.get("video", 0) - 75) < 0.1, f"vídeo com 75s ({durs.get('video')})")
    check(abs(durs.get("audio", 0) - 75) < 0.1, f"áudio com 75s, sem perder sincronia ({durs.get('audio')})")


exporta("suave")
exporta("seca")
print("\nTUDO CERTO" if not falhas else f"\n{falhas} FALHA(S)")
sys.exit(1 if falhas else 0)

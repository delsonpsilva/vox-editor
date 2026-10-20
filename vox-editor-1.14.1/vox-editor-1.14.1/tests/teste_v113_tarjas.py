"""Testes da v1.1.3: todas as tarjas (lower thirds) em vertical e horizontal, com texto comprido, acentos e
música de fundo que abaixa sozinha quando alguém fala. Não precisa de internet."""
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


spec = json.loads((ROOT / "frontend" / "tarjas.json").read_text(encoding="utf-8"))
check(len(spec["modelos"]) >= 12 and len(spec["paletas"]) >= 10, f"{len(spec['modelos'])} modelos × {len(spec['paletas'])} cores")
tmp = Path(tempfile.mkdtemp())
F = ff.ffmpeg()
subprocess.run([F, "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=30", "-f", "lavfi",
                "-i", "sine=f=300:d=30", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
                "-shortest", str(tmp / "fala.mp4")], check=True)
subprocess.run([F, "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=f=660:d=40", str(tmp / "trilha.mp3")], check=True)

for formato in ("16:9", "9:16"):
    pid = c.post("/api/montagem/novo", json={"name": f"Tarjas {formato}", "formato": formato}).json()["id"]
    ids = {n: c.post(f"/api/projects/{pid}/midias", content=(tmp / n).read_bytes(), headers={"x-filename": n}).json()["id"]
           for n in ("fala.mp4", "trilha.mp3")}
    m = c.get(f"/api/projects/{pid}/montagem").json()
    tt = next(t["id"] for t in m["tracks"] if t["kind"] == "text")
    ta = next(t["id"] for t in m["tracks"] if t["kind"] == "audio")
    items = [{"id": "v", "type": "video", "track": "t_v1", "src": ids["fala.mp4"], "start": 0, "dur": 24, "in": 0, "fit": "cover"},
             {"id": "mus", "type": "audio", "track": ta, "src": ids["trilha.mp3"], "start": 0, "dur": 24, "in": 0, "volume": 0.3,
              "duck": True}]
    for i, mo in enumerate(spec["modelos"]):
        pal = spec["paletas"][i % len(spec["paletas"])]
        items.append({"id": f"j{i}", "type": "tarja", "track": tt, "start": i * 2, "dur": 2, "tpl": mo["id"],
                      "l1": "Pr. João D'Ávila: \"Ação\" & Fé — um texto bem comprido para testar se cabe na tela", "l2": mo["l2"],
                      **{k: pal[k] for k in ("c1", "c2", "t1", "t2")}})
    m["items"] = items
    r = c.put(f"/api/projects/{pid}/montagem", json=m)
    salvo = r.json()
    check(r.status_code == 200 and sum(1 for x in salvo["items"] if x["type"] == "tarja") == len(spec["modelos"]),
          f"{formato}: salva as tarjas")
    check(next(x for x in salvo["items"] if x["id"] == "mus").get("duck") is True, f"{formato}: música marcada para abaixar")
    c.post(f"/api/projects/{pid}/montagem/exportar", json={"quality": "rapida"})
    job = None
    for _ in range(600):
        job = (c.get(f"/api/projects/{pid}").json().get("jobs") or [None])[0]
        if job and job["status"] in ("concluido", "erro"):
            break
        time.sleep(1)
    check(job and job["status"] == "concluido", f"{formato}: exporta tarjas + música ({(job or {}).get('error') or ''})"[:300])

print("\nTUDO CERTO" if not falhas else f"\n{falhas} FALHA(S)")
sys.exit(1 if falhas else 0)

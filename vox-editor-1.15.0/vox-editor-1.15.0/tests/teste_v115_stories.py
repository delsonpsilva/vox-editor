"""Testes da v1.15 — Stories do Culto: vídeo/foto + evento + modelo = story 9:16 com capa, pronto para os Stories."""
import os
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DADOS = Path(tempfile.mkdtemp()) / "dados"
os.environ["EDITOR_DATA"] = str(DADOS)
os.environ["VOX_SEM_MANUTENCAO"] = "1"
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend import app as appmod  # noqa: E402
from backend.core import publish, stories  # noqa: E402
from backend.engine import ffmpeg_tools as ff  # noqa: E402

c = TestClient(appmod.app)
falhas = 0
TMP = Path(tempfile.mkdtemp())


def check(cond, msg):
    global falhas
    print(("OK   " if cond else "FALHOU ") + msg)
    if not cond:
        falhas += 1


c.post("/api/login", json={"password": "admin123"})

# arquivos de teste: vídeo deitado de 70 s com som, foto e logo
video = TMP / "culto.mp4"
subprocess.run([ff.ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=70",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=70", "-c:v", "libx264", "-preset", "ultrafast",
                "-c:a", "aac", "-shortest", str(video)], check=True)
foto = TMP / "foto.jpg"
subprocess.run([ff.ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=800x1000",
                "-frames:v", "1", str(foto)], check=True)
logo = TMP / "logo.png"
subprocess.run([ff.ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=blue:size=300x300",
                "-frames:v", "1", str(logo)], check=True)

# 1. status: eventos, modelos e sugestões
r = c.get("/api/stories/status")
check(r.status_code == 200, "status responde")
st = r.json()
nev = sum(len(g["eventos"]) for g in st["grupos"])
check(nev >= 60, f"lista grande de eventos ({nev})")
check(len(st["modelos"]) == 6, "6 modelos de capa")
check("instagram_story" in st["redes"] and "facebook_story" in st["redes"], "Instagram e Facebook Stories na lista")
check(stories.sugestao(date(2025, 12, 31))[0] == "virada", "31/12 sugere Culto da Virada")
check(stories.sugestao(date(2026, 4, 5))[0] == "pascoa", "domingo de Páscoa sugere Páscoa")
check(stories.sugestao(date(2026, 10, 25))[0] == "celebracao", "domingo comum sugere Celebração")
check(stories.data_por_extenso("2026-10-21") == "21 de outubro de 2026", "data por extenso")

# 2. logo da igreja
r = c.post("/api/stories/logos", content=logo.read_bytes(), headers={"x-filename": "IEAD Sede.png"})
check(r.status_code == 200, "envia o logo")
lid = r.json()["novo"]["id"]
check(c.get(f"/api/stories/logos/{lid}").status_code == 200, "logo aparece")

# 3. envio dos arquivos
r1 = c.post("/api/stories/arquivo", content=video.read_bytes(), headers={"x-filename": "culto.mp4"})
r2 = c.post("/api/stories/arquivo", content=foto.read_bytes(), headers={"x-filename": "foto.jpg"})
check(r1.status_code == 200 and r2.status_code == 200, "recebe vídeo e foto")
v, f = r1.json(), r2.json()
check(abs(v["duracao"] - 70) < 1 and v["audio"], "lê duração e som do vídeo")
r = c.post("/api/stories/arquivo", content=b"oi", headers={"x-filename": "texto.txt"})
check(r.status_code == 400, "recusa arquivo que não é vídeo nem foto")

# 4. prévias de todos os modelos
for m in st["modelos"]:
    r = c.post("/api/stories/previa", json={"item": v["id"], "modelo": m["id"], "cor": "dourado", "linha1": "Culto de",
                                            "destaque": "Ação de Graças", "linha3": "21 de outubro de 2026", "logo": lid})
    check(r.status_code == 200 and r.content[:2] == b"\xff\xd8", f"prévia do modelo {m['nome']}")

# 5. criar: vídeo de 70 s vira 2 partes; foto vira vídeo de 7 s + JPG
r = c.post("/api/stories/criar", json={"itens": [v["id"], f["id"]], "opcoes": {
    "modelo": "ouro", "cor": "dourado", "linha1": "Culto da", "destaque": "Virada", "logo": lid, "tamanho": "partes",
    "evento": "virada"}})
check(r.status_code == 200, "começa a criar")
job = r.json()
for _ in range(600):
    js = c.get(f"/api/jobs/{job['pid']}").json()
    j = next((x for x in js if x["id"] == job["job"]), None)
    if j and j["status"] in ("concluido", "erro", "cancelado"):
        break
    time.sleep(1)
check(j and j["status"] == "concluido", "stories criados" + ("" if not j or j["status"] == "concluido" else f": {j.get('error')}"))
res = (j or {}).get("result") or {}
check(res.get("quantos") == 3, "2 partes do vídeo + 1 da foto")
pasta = DADOS / "projetos" / job["pid"] / "renders"
for s in res.get("saidas", []):
    i = ff.probe(str(pasta / s["file"]))
    check(i["width"] == 1080 and i["height"] == 1920 and i["duration"] <= 60.5 and i["has_audio"],
          f"{s['label']}: 1080x1920, até 60 s, com áudio")
check(any(s["jpg"] and (pasta / s["jpg"]).exists() for s in res.get("saidas", [])), "foto também sai em JPG")
lib = c.get("/api/renders").json()
check(sum(1 for x in lib if x.get("story")) == 3, "stories aparecem em Exportados")

# 6. postar sem conta conectada avisa antes de renderizar
r = c.post("/api/stories/criar", json={"itens": [f["id"]], "opcoes": {"destaque": "Virada"}, "postar": ["instagram_story"]})
check(r.status_code == 400 and "Conecte" in r.json()["detail"], "pede para conectar a rede antes")

# 7. publicação: Stories não viram cartão separado e usam a conta da Meta
ns = publish.public_status()
check(ns["instagram_story"]["app"] == "meta" and ns["instagram_story"]["story"], "Instagram Stories pela conta da Meta")
check("instagram_story" in publish.POSTERS and "facebook_story" in publish.POSTERS, "envio para Stories existe")

print("\n" + ("TUDO CERTO" if not falhas else f"{falhas} FALHA(S)"))
sys.exit(1 if falhas else 0)

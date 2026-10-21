"""Teste da versão 0.2: cortes, resumos, partes para Status, enquadramento e estilos de legenda."""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["EDITOR_DATA"] = str(ROOT / "teste_dados")
sys.path.insert(0, str(ROOT))

from backend.core import pipeline, store  # noqa: E402
from backend.engine import edits, subtitles  # noqa: E402
from backend.engine import ffmpeg_tools as ff  # noqa: E402

pid = store.list_projects()[0]["id"]
folder = store.pdir(pid)
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else folder

# 1) Gerar cortes + resumos (sem IA: análise local)
store.update(pid, lambda p: p.setdefault("settings", {}).update(
    studio={"platform": "whatsapp", "mode": "ambos", "duration": "30", "count": 4, "layout": "face", "title_mode": "inicio"}))
r = pipeline.regenerate_clips(pid, lambda x, m: None)
p = store.load(pid)
print("gerados:", r)
for c in p["clips"]:
    print(f"  {c['kind']:7s} {len(c['segments'])} trechos {sum(e - s for s, e in c['segments']):5.1f}s  {c['title'][:40]}")

# 2) Renderizar um resumo (montagem fora de ordem) e conferir duração/sincronia
res = next(c for c in p["clips"] if c["kind"] == "resumo")
keeps = pipeline.clip_keeps(p, res)
t0 = time.time()
out = pipeline.render_clip(pid, res["id"], {"platform": "ig_reels", "layout": "face", "title_mode": "inicio"}, lambda x, m: None)
f = folder / "renders" / out["files"][0]
info = ff.probe(str(f))
snapped = edits.snap_keeps(keeps, p["media"]["fps"])
print(f"resumo: {time.time() - t0:.1f}s · esperado {sum(e - s for s, e in snapped):.2f}s · saída {info['duration']:.2f}s · {info['width']}x{info['height']}")
# Sincronia: no início do 2º trecho, o quadro deve mostrar o tempo original desse trecho
tm = edits.TimeMap(snapped)
t_out = tm.boundaries()[1] + 0.5
expected_src = snapped[1][0] + 0.5
ff.run([ff.ffmpeg(), "-y", "-loglevel", "error", "-ss", f"{t_out:.3f}", "-i", str(f), "-frames:v", "1", str(OUT / "sync.png")])
print(f"sync: na saída {t_out:.2f}s deve aparecer o tempo original {expected_src:.3f}s (ver sync.png)")
ff.run([ff.ffmpeg(), "-y", "-loglevel", "error", "-ss", "1.0", "-i", str(f), "-frames:v", "1", "-vf", "scale=360:-2", str(OUT / "resumo_titulo.png")])

# 3) Fundo desfocado
corte = next(c for c in p["clips"] if c["kind"] == "corte")
out = pipeline.render_clip(pid, corte["id"], {"platform": "yt_shorts", "layout": "blur", "title_mode": "nao"}, lambda x, m: None)
ff.run([ff.ffmpeg(), "-y", "-loglevel", "error", "-ss", "2", "-i", str(folder / "renders" / out["files"][0]), "-frames:v", "1",
        "-vf", "scale=360:-2", str(OUT / "blur.png")])
print("fundo desfocado ok:", out["files"][0])

# 4) Divisão em partes (Status: limite forçado de 12 s para testar)
parts = pipeline.split_parts(pipeline.clip_keeps(p, corte), 12, p["words"])
print("partes:", [round(sum(e - s for s, e in pt), 1) for pt in parts])
words = p["words"]
mids = [((w["s"] + w["e"]) / 2, w) for w in words]
for pt in parts[:-1]:
    end = pt[-1][1]
    inside = [w for m, w in mids if w["s"] < end - 0.01 < w["e"]]
    print("   corte em", round(end, 2), "corta palavra?" , bool(inside))

# 5) Prévia de cada estilo de legenda
for st in subtitles.STYLES:
    img = pipeline.subtitle_preview(pid, st, None)
    os.replace(img, OUT / f"estilo_{st}.jpg") if OUT != folder else None
print("prévias de estilo geradas:", len(subtitles.STYLES))
th = pipeline.thumbnail(pid, 10.0, True, "face")
print("miniatura:", th.name)

"""Testes da v1.1.3: render da edição automática com muitos cortes (mais de 100 trechos), enquadramento que
segue o rosto trecho a trecho e as três suavidades de emenda. Antes, mais de ~100 trechos travavam o FFmpeg."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.engine import ffmpeg_tools as ff  # noqa: E402
from backend.engine import render  # noqa: E402

falhas = 0


def check(cond, msg):
    global falhas
    print(("OK   " if cond else "FALHOU ") + msg)
    if not cond:
        falhas += 1


tmp = Path(tempfile.mkdtemp())
src = tmp / "fonte.mp4"
subprocess.run([ff.ffmpeg(), "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=100", "-f", "lavfi",
                "-i", "sine=f=250:d=100", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
                "-shortest", str(src)], check=True)
media = ff.probe(str(src))
keeps = [[round(i * 0.6, 3), round(i * 0.6 + 0.4, 3)] for i in range(160)]   # 160 trechos de 0,4 s
esperado = sum(e - s for s, e in keeps)

for i, suave in enumerate(("suave", "seca", "bem_suave")):
    out = tmp / f"saida_{suave}.mp4"
    job = {"src": str(src), "folder": str(tmp), "media": media, "keeps": keeps, "ducks": [], "out": str(out),
           "out_w": 1080 if i == 0 else 0, "out_h": 1920 if i == 0 else 0, "layout": "face",
           "center_fn": (lambda t: 0.3 + 0.4 * ((int(t) % 7) / 6)), "zoom_cuts": True, "normalize": False,
           "quality": "rapida", "smooth": suave}
    try:
        res = render.render(job)
        ok = True
    except Exception as e:  # noqa: BLE001
        ok, res = False, {"erro": str(e)[-400:]}
    check(ok, f"render com 160 trechos ({suave}{', vertical seguindo o rosto' if i == 0 else ''}) {res.get('erro', '')}")
    if ok:
        info = json.loads(subprocess.run([ff.ffprobe(), "-v", "error", "-show_streams", "-of", "json", str(out)],
                                         capture_output=True, text=True).stdout)
        d = {s["codec_type"]: float(s.get("duration") or 0) for s in info["streams"]}
        check(abs(d.get("video", 0) - esperado) < 0.15 and abs(d.get("audio", 0) - esperado) < 0.15,
              f"duração certa e áudio junto com o vídeo ({d.get('video')} / {d.get('audio')} / {esperado:.2f})")

print("\nTUDO CERTO" if not falhas else f"\n{falhas} FALHA(S)")
sys.exit(1 if falhas else 0)

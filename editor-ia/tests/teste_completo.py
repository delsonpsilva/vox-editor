"""Teste de ponta a ponta com um vídeo sintético (falas, silêncios e respirações em posições conhecidas)."""
import json
import os
import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
os.environ["EDITOR_DATA"] = str(ROOT / "teste_dados")
sys.path.insert(0, str(ROOT))

from backend.core import pipeline, store  # noqa: E402
from backend.engine import ffmpeg_tools as ff, transcribe  # noqa: E402

SR = 48000
rng = np.random.default_rng(1)
plan = []  # (tipo, duração, texto)
script = [("fala", 1.2, "Então quando eu comecei"), ("silencio", 1.5, ""), ("fala", 0.9, "o canal"),
          ("resp", 0.4, ""), ("fala", 0.5, "é"), ("pausa", 0.3, ""), ("fala", 1.4, "eu não sabia nada mesmo."),
          ("silencio", 2.2, ""), ("fala", 1.0, "Qual é o segredo?"), ("resp", 0.45, ""), ("fala", 1.6, "A dica é cortar tudo"),
          ("silencio", 0.9, ""), ("fala", 1.3, "que não acrescenta nada.")] * 6

chunks, words, t = [], [], 0.0
for kind, dur, text in script:
    n = int(dur * SR)
    tt = np.arange(n) / SR
    if kind == "fala":
        f0 = 140 + 30 * np.sin(2 * np.pi * 3 * tt)
        phase = 2 * np.pi * np.cumsum(f0) / SR
        sig = sum(np.sin(k * phase) / k for k in range(1, 12)) * 0.25
        env = np.minimum(1, np.minimum(tt / 0.03, (dur - tt) / 0.03))
        sig = sig * env * (0.7 + 0.3 * np.sin(2 * np.pi * 4 * tt) ** 2)
        ws = text.split()
        wd = dur / len(ws)
        for i, w in enumerate(ws):
            words.append({"w": w, "s": round(t + i * wd + 0.02, 3), "e": round(t + (i + 1) * wd - 0.02, 3), "p": 0.9})
    elif kind == "resp":
        noise = rng.standard_normal(n)
        spec = np.fft.rfft(noise)
        fr = np.fft.rfftfreq(n, 1 / SR)
        spec[(fr < 1200) | (fr > 6000)] = 0
        sig = np.fft.irfft(spec, n)
        sig = sig / np.max(np.abs(sig)) * 0.03 * np.sin(np.pi * tt / dur)
    else:
        sig = rng.standard_normal(n) * 0.0008
    chunks.append(sig)
    plan.append((kind, round(t, 3), round(t + dur, 3)))
    t += dur
audio = np.concatenate(chunks)
tmp = ROOT / "teste_dados"
tmp.mkdir(exist_ok=True)
wav_path = tmp / "voz.wav"
with wave.open(str(wav_path), "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
video = tmp / "teste.mov"
# Vídeo com contador de quadros visível (para conferir a sincronia) em codec que o navegador não toca (força prévia)
ff.run([ff.ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s=1280x720:r=30000/1001:d={t}",
        "-i", str(wav_path), "-c:v", "mpeg4", "-q:v", "5", "-c:a", "pcm_s16le", "-shortest", str(video)])
print(f"vídeo de teste: {t:.1f}s, {len(words)} palavras")

# Transcrição simulada (o modelo real não pode ser baixado neste ambiente de teste)
transcribe.transcribe = lambda *a, **k: {"words": words, "segments": [], "language": "pt"}
pipeline.transcribe.transcribe = transcribe.transcribe

proj = store.new_project("teste.mov")
folder = store.pdir(proj["id"])
import shutil  # noqa: E402
shutil.copy(video, folder / "original.mov")
store.update(proj["id"], lambda p: p.update(source="original.mov"))
pid = proj["id"]

t0 = time.time()
pipeline.analyze(pid, lambda x, m: None)
print(f"análise: {time.time() - t0:.1f}s")
p = store.load(pid)
an = p["analysis"]
print("níveis:", an["levels"], "limiar:", an["threshold"])
print("prévia:", p.get("preview"))

real_sil = [(s, e) for k, s, e in plan if k == "silencio"]
real_resp = [(s, e) for k, s, e in plan if k == "resp"]
hit_sil = sum(any(a < e and b > s for a, b in an["silences"]) for s, e in real_sil)
hit_resp = sum(any(a < e and b > s for a, b in an["breaths"]) for s, e in real_resp)
false_resp = sum(not any(a < e and b > s for s, e in real_resp) for a, b in an["breaths"])
print(f"silêncios: achou {hit_sil}/{len(real_sil)} (detectados {len(an['silences'])})")
print(f"respirações: achou {hit_resp}/{len(real_resp)}, falsos {false_resp}")
# Nenhum corte de silêncio pode invadir a fala
speech = [(s, e) for k, s, e in plan if k == "fala"]
inv = sum(1 for a, b in an["silences"] for s, e in speech if a < e - 0.005 and b > s + 0.005)
print("cortes invadindo fala:", inv)

from backend.engine import edits  # noqa: E402
ed = edits.build_edit(p)
print("estatísticas:", ed["stats"])
print("clipes:", [(c["s"], c["e"], c["title"][:30]) for c in p["clips"]][:3], p.get("clips_source"))

t0 = time.time()
r = pipeline.render_full(pid, {"subtitles": True}, lambda x, m: None)
info = ff.probe(str(folder / "renders" / r["file"]))
print(f"render completo: {time.time() - t0:.1f}s, esperado {ed['stats']['final']:.2f}s, saída {info['duration']:.2f}s, enc {r['encoder']}")
pr = ff.run([ff.ffprobe(), "-v", "error", "-show_entries", "stream=codec_type,duration,nb_frames", "-of", "json",
             str(folder / "renders" / r["file"])]).stdout
print(pr)
if p["clips"]:
    c = p["clips"][0]
    t0 = time.time()
    r2 = pipeline.render_clip(pid, c["id"], {"vertical": True}, lambda x, m: None)
    i2 = ff.probe(str(folder / "renders" / r2["file"]))
    print(f"corte vertical: {time.time() - t0:.1f}s, {i2['width']}x{i2['height']}, {i2['duration']:.2f}s")
for fmt in ("srt", "edl", "xml", "txt"):
    content, name, _ = pipeline.export(pid, fmt)
    print(f"--- {name} ({len(content)} bytes)")
    print(content[:300])
print("PID", pid)

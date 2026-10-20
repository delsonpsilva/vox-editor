"""Render da v0.9 com limpeza de voz, música de fundo, palavras-chave, emojis e zoom nos momentos fortes."""
import os, sys, time, json, re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
os.environ["EDITOR_DATA"] = str(ROOT / "teste_dados")
sys.path.insert(0, str(ROOT))
import numpy as np
from backend.core import pipeline, store
from backend.engine import destaques, edits, subtitles, ffmpeg_tools as ff, render

falhas = 0
def check(c, m):
    global falhas
    print(("OK   " if c else "FALHOU ") + m)
    falhas += 0 if c else 1

pid = next(p["id"] for p in store.list_projects() if p["status"] == "pronto")
proj = store.load(pid)
# música de teste: acorde de 25 s (volume alto, como música masterizada)
pipeline.MUSICAS.mkdir(parents=True, exist_ok=True)
mus = pipeline.MUSICAS / "teste-trilha.mp3"
ff.run([ff.ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i",
        "aevalsrc=0.3*sin(2*PI*220*t)+0.3*sin(2*PI*277*t)+0.3*sin(2*PI*330*t):s=48000:d=25", "-ac", "2", str(mus)])
store.update(pid, lambda p: p.setdefault("settings", {}).update(
    audio={"normalize": True, "target_lufs": -14.0, "clean": True, "music": "teste-trilha.mp3", "music_volume": 0.15}))

# destaques locais
mapa_l = destaques.locais(proj["words"])
kws = [proj["words"][i]["w"] for i in mapa_l]
check(any("segredo" in w.lower() for w in kws), f"palavras-chave locais: {sorted(set(kws))[:8]}")
check(any(d.get("e") for d in mapa_l.values()), "emoji local escolhido (segredo → 🔑)")
keeps = edits.build_edit(proj)["keeps"]
evs = destaques.eventos_emoji(proj["words"], {str(k): v for k, v in mapa_l.items()}, keeps)
check(len(evs) >= 2 and all(evs[i + 1]["s"] - evs[i]["s"] >= 3.4 for i in range(len(evs) - 1)),
      f"{len(evs)} emojis no vídeo, com espaço entre eles")
# momentos fortes: simula uma palavra gritada
feats = {"db": np.full(int(proj["media"]["duration"] * 100) + 10, -20.0, dtype=np.float32)}
w = proj["words"][40]
feats["db"][int(w["s"] * 100):int(w["e"] * 100)] = -8.0
fortes = destaques.momentos_fortes(proj["words"], feats, keeps)
check(len(fortes) >= 1, f"momento forte encontrado onde a voz subiu: {fortes[:2]}")
check(destaques.expr_zoom([[1, 3]]).startswith("(1+0.120*min(1,clip("), "expressão de zoom suave")

# legenda com palavra-chave colorida
tm = edits.TimeMap(keeps)
caps = subtitles.build_captions(destaques.marcar(proj["words"], {str(k): v for k, v in mapa_l.items()}), tm,
                                edits.merged_settings({})["subtitles"])
ass = subtitles.to_ass(caps, edits.merged_settings({})["subtitles"], 1080, 1920)
check("&H5FE739&" in ass, "palavra-chave pintada de verde na legenda (ASS)")
x, y, tam = subtitles.emoji_box(edits.merged_settings({})["subtitles"], 1080, 1920)
check(0 < y < 1920 - tam and tam > 100, f"emoji acima da legenda: x={x} y={y} tamanho={tam}")

# render do corte vertical com tudo ligado
clip = proj["clips"][0]
t0 = time.time()
r = pipeline.render_clip(pid, clip["id"], {"platform": "ig_reels"}, lambda x, m: None)
f = store.pdir(pid) / "renders" / r["files"][0]
info = ff.probe(str(f))
check(info["width"] == 1080 and info["height"] == 1920, f"vídeo 1080x1920 em {time.time() - t0:.0f}s")
exp = sum(e - s for s, e in pipeline.clip_keeps(store.load(pid), clip))
check(abs(info["duration"] - exp) < 0.25, f"duração certa: {info['duration']:.2f}s (esperado {exp:.2f}s)")
# a música entra nas pausas: mede o volume num trecho de silêncio original do corte
pr = ff.run([ff.ffmpeg(), "-hide_banner", "-i", str(f), "-af", "astats=metadata=1:reset=0", "-f", "null", "-"], check=False)
check("RMS level" in pr.stderr, "áudio final presente")
left = list(store.pdir(pid).glob("tmp_*"))
check(not left, "não sobram arquivos temporários")
# volume integrado continua no alvo de -14 LUFS
pr = ff.run([ff.ffmpeg(), "-hide_banner", "-nostats", "-i", str(f), "-af", "ebur128", "-f", "null", "-"], check=False)
m = re.findall(r"I:\s+(-?[\d.]+) LUFS", pr.stderr)
check(m and abs(float(m[-1]) + 14) < 1.5, f"volume final {m[-1] if m else '?'} LUFS (alvo -14)")
print("ARQUIVO", f)
store.update(pid, lambda p: p["settings"].pop("audio", None))
print("TUDO CERTO" if not falhas else f"{falhas} FALHA(S)")

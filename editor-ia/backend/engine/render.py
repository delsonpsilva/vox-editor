"""Renderização profissional: áudio com precisão de amostra (cruzamento suave em cada corte, atenuação de
respirações, normalização de volume) + vídeo cortado em uma única passada do FFmpeg, com aceleração por GPU."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from . import ffmpeg_tools as ff
from .edits import snap_keeps

ASR = 48000          # taxa do áudio final
CH = 2
XFADE = 0.006        # meia janela do cruzamento (6 ms de cada lado)
RAMP = 0.03          # rampa de 30 ms na atenuação das respirações


def ensure_render_audio(src: str, raw_path: Path) -> None:
    if raw_path.exists() and raw_path.stat().st_size > 0:
        return
    ff.run([ff.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", src, "-vn", "-ac", str(CH),
            "-ar", str(ASR), "-f", "s16le", "-c:a", "pcm_s16le", str(raw_path)])


def _gain(times: np.ndarray, ducks: list[list[float]]) -> np.ndarray:
    g = np.ones_like(times, dtype=np.float32)
    if not ducks:
        return g
    t0, t1 = float(times[0]), float(times[-1])
    for s, e, db in ducks:
        if e + RAMP < t0 or s - RAMP > t1:
            continue
        lin = 10 ** (db / 20)
        # 1 fora; desce na entrada (s-RAMP→s), fica em lin, sobe na saída (e→e+RAMP)
        down = np.clip((times - (s - RAMP)) / RAMP, 0, 1)
        up = np.clip(((e + RAMP) - times) / RAMP, 0, 1)
        shape = np.minimum(down, up)
        g *= (1 - shape * (1 - lin)).astype(np.float32)
    return g


def build_audio(raw_src: Path, keeps: list[list[float]], ducks: list[list[float]], out_raw: Path) -> float:
    """Junta os trechos mantidos com cruzamento equal-power (sem estalos) e preserva a sincronia exata."""
    src = np.memmap(raw_src, dtype=np.int16, mode="r")
    n_total = len(src) // CH
    src = src[: n_total * CH].reshape(n_total, CH)
    h = int(XFADE * ASR)
    fade = np.linspace(0, math.pi / 2, 2 * h, dtype=np.float32)
    fin, fout = np.sin(fade)[:, None], np.cos(fade)[:, None]

    def read(a: int, b: int) -> np.ndarray:
        """Lê amostras [a,b) com silêncio fora dos limites e aplica a atenuação."""
        out = np.zeros((b - a, CH), dtype=np.float32)
        ca, cb = max(0, a), min(n_total, b)
        if cb > ca:
            out[ca - a: cb - a] = src[ca:cb].astype(np.float32)
        times = np.arange(a, b, dtype=np.float64) / ASR
        out *= _gain(times, ducks)[:, None]
        return out

    written = 0
    with open(out_raw, "wb") as fo:
        spans = [(int(round(s * ASR)), int(round(e * ASR))) for s, e in keeps]
        spans = [(a, b) for a, b in spans if b - a > 4 * h]
        for k, (a, b) in enumerate(spans):
            first, last = k == 0, k == len(spans) - 1
            core_a = a if first else a + h
            core_b = b if last else b - h
            if not first:
                pa, pb = spans[k - 1]
                mix = read(pb - h, pb + h) * fout + read(a - h, a + h) * fin
                fo.write(np.clip(mix, -32768, 32767).astype(np.int16).tobytes())
                written += len(mix)
            step = ASR * 20
            for x in range(core_a, core_b, step):
                y = min(core_b, x + step)
                blk = read(x, y)
                fo.write(np.clip(blk, -32768, 32767).astype(np.int16).tobytes())
                written += len(blk)
    return written / ASR


def measure_loudness(raw: Path, target: float) -> Optional[dict]:
    p = ff.run([ff.ffmpeg(), "-hide_banner", "-nostats", "-f", "s16le", "-ar", str(ASR), "-ac", str(CH),
                "-i", str(raw), "-af", f"loudnorm=I={target}:TP=-1.0:LRA=11:print_format=json", "-f", "null", "-"],
               check=False)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", p.stderr, re.S)
    if not m:
        return None
    try:
        js = json.loads(m.group(0))
        if js.get("input_i") in ("-inf", None):
            return None
        return js
    except json.JSONDecodeError:
        return None


def loudnorm_filter(meas: Optional[dict], target: float) -> Optional[str]:
    if not meas:
        return None
    return (f"loudnorm=I={target}:TP=-1.0:LRA=11:measured_I={meas['input_i']}:measured_TP={meas['input_tp']}:"
            f"measured_LRA={meas['input_lra']}:measured_thresh={meas['input_thresh']}:offset={meas['target_offset']}:"
            f"linear=true,aresample={ASR}")


def _esc_path(p: str) -> str:
    p = p.replace("\\", "/")
    return p.replace(":", "\\:").replace("'", "\\'")


def render(job: dict, progress: Optional[Callable[[float, str], None]] = None) -> dict:
    """
    job = {src, folder, media, keeps, ducks, out, window:(s,e)|None, vertical:bool,
           ass_text:str|None, normalize:bool, target_lufs, encoder, quality, fonts_dir}
    """
    folder = Path(job["folder"])
    media = job["media"]
    fps = media.get("fps") or 30.0
    fps_str = media.get("fps_str") or "30"
    keeps = snap_keeps(job["keeps"], fps) if media.get("has_video") else job["keeps"]
    if not keeps:
        raise RuntimeError("Nada para renderizar: todos os trechos foram cortados.")
    win = job.get("window")
    tag = Path(job["out"]).stem

    def p(x, msg):
        if progress:
            progress(x, msg)

    # 1) Áudio
    p(0.02, "Preparando áudio…")
    raw_src = folder / "audio48k.raw"
    ensure_render_audio(job["src"], raw_src)
    out_raw = folder / f"tmp_{tag}.raw"
    total = build_audio(raw_src, keeps, job.get("ducks") or [], out_raw)
    af = None
    if job.get("normalize", True):
        p(0.08, "Medindo volume (normalização)…")
        af = loudnorm_filter(measure_loudness(out_raw, job.get("target_lufs", -14.0)), job.get("target_lufs", -14.0))

    out = job["out"]
    args = [ff.ffmpeg(), "-y"]
    if not media.get("has_video"):
        args += ["-f", "s16le", "-ar", str(ASR), "-ac", str(CH), "-i", str(out_raw)]
        if af:
            args += ["-af", af]
        args += ["-c:a", "aac", "-b:a", "192k", out]
        p(0.1, "Gerando áudio final…")
        ff.run_with_progress(args, total, lambda x: p(0.1 + 0.88 * x, "Gerando áudio final…"), cwd=str(folder))
        out_raw.unlink(missing_ok=True)
        return {"duration": total, "file": out}

    # 2) Vídeo: uma passada, seleciona os quadros mantidos numa grade de quadros constante
    offset = 0.0
    if win:
        offset = max(0.0, win[0] - 1.0)
        args += ["-ss", f"{offset:.3f}", "-t", f"{win[1] - offset + 1.0:.3f}"]
    args += ["-i", job["src"], "-f", "s16le", "-ar", str(ASR), "-ac", str(CH), "-i", str(out_raw)]
    eps = 0.25 / fps
    terms = "+".join(f"gte(t,{s - offset - eps:.4f})*lt(t,{e - offset - eps:.4f})" for s, e in keeps)
    chain = [f"setpts=PTS-STARTPTS", f"fps={fps_str}", f"select='{terms}'", f"setpts=N/({fps_str})/TB"]
    w, h = media["width"], media["height"]
    if job.get("vertical"):
        if w > h:
            chain.append("crop=trunc(ih*9/16/2)*2:ih:(iw-ih*9/16)/2:0")
        chain.append("scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black")
        w, h = 1080, 1920
    else:
        chain.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
    if job.get("ass_text"):
        ass_name = f"tmp_{tag}.ass"
        (folder / ass_name).write_text(job["ass_text"], encoding="utf-8")
        fopt = ""
        fonts = job.get("fonts_dir")
        if fonts and Path(fonts).exists():
            fopt = f":fontsdir='{_esc_path(str(fonts))}'"
        chain.append(f"ass='{ass_name}'{fopt}")
    graph = "[0:v]" + ",".join(chain) + "[v]"
    args += ff.filter_script_args(graph, str(folder / f"tmp_{tag}.filter"))
    args += ["-map", "[v]", "-map", "1:a"]
    if af:
        args += ["-af", af]
    encoder = ff.best_encoder(job.get("encoder", "auto"))
    args += ff.encoder_args(encoder, job.get("quality", "alta"))
    args += ["-r", fps_str, "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", out]
    label = {"libx264": "CPU"}.get(encoder, "GPU")
    p(0.1, f"Renderizando vídeo ({label})…")
    ff.run_with_progress(args, total, lambda x: p(0.1 + 0.89 * x, f"Renderizando vídeo ({label})…"), cwd=str(folder))
    for tmp in folder.glob(f"tmp_{tag}.*"):
        tmp.unlink(missing_ok=True)
    return {"duration": total, "file": out, "encoder": encoder, "width": w, "height": h}

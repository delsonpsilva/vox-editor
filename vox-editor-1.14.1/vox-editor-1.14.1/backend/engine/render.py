"""Renderização profissional: áudio com precisão de amostra (cruzamento suave em cada corte, atenuação de
respirações, normalização de volume) + vídeo cortado em uma única passada do FFmpeg, com aceleração por GPU."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from . import destaques
from . import ffmpeg_tools as ff
from .edits import snap_keeps

ASR = 48000          # taxa do áudio final
CH = 2
XFADE = 0.010        # meia janela do cruzamento quando só tirou pausa (10 ms de cada lado)
XFADE_FAR = 0.040    # emenda entre partes distantes do vídeo (40 ms de cada lado)
# Suavidade das emendas (meia janela perto, meia janela longe). "seca" é o corte de antes, colado.
SUAVIDADE = {"seca": (0.010, 0.040), "suave": (0.035, 0.070), "bem_suave": (0.070, 0.120)}
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


def build_audio(raw_src: Path, keeps: list[list[float]], ducks: list[list[float]], out_raw: Path,
                smooth: str = "suave") -> float:
    """Junta os trechos mantidos com cruzamento equal-power (sem estalos) e preserva a sincronia exata.
    smooth: "seca" | "suave" | "bem_suave" — quanto maior, mais longo o cruzamento em cada emenda."""
    near, far = SUAVIDADE.get(smooth, SUAVIDADE["suave"])
    src = np.memmap(raw_src, dtype=np.int16, mode="r")
    n_total = len(src) // CH
    src = src[: n_total * CH].reshape(n_total, CH)

    def read(a: int, b: int) -> np.ndarray:
        """Lê amostras [a,b) com silêncio fora dos limites e aplica a atenuação."""
        out = np.zeros((b - a, CH), dtype=np.float32)
        ca, cb = max(0, a), min(n_total, b)
        if cb > ca:
            out[ca - a: cb - a] = src[ca:cb].astype(np.float32)
        times = np.arange(a, b, dtype=np.float64) / ASR
        out *= _gain(times, ducks)[:, None]
        return out

    spans = [(int(round(s * ASR)), int(round(e * ASR))) for s, e in keeps]
    spans = [(a, b) for a, b in spans if b - a > int(0.03 * ASR)]
    # meia-janela de cada emenda: curta quando só tirou pausa, mais longa quando junta partes distantes
    hs = [0]
    for k in range(1, len(spans)):
        gap = (spans[k][0] - spans[k - 1][1]) / ASR
        half = far if (gap < -0.01 or gap > 2.5) else near
        lim = min(spans[k - 1][1] - spans[k - 1][0], spans[k][1] - spans[k][0]) // 3
        hs.append(max(16, min(int(half * ASR), lim)))
    hs.append(0)
    written = 0
    with open(out_raw, "wb") as fo:
        for k, (a, b) in enumerate(spans):
            h_in, h_out = hs[k], hs[k + 1]
            if k > 0:
                pb = spans[k - 1][1]
                fade = np.linspace(0, math.pi / 2, 2 * h_in, dtype=np.float32)
                mix = read(pb - h_in, pb + h_in) * np.cos(fade)[:, None] + read(a - h_in, a + h_in) * np.sin(fade)[:, None]
                fo.write(np.clip(mix, -32768, 32767).astype(np.int16).tobytes())
                written += len(mix)
            core_a, core_b = a + h_in, b - h_out
            step = ASR * 20
            for x in range(core_a, core_b, step):
                y = min(core_b, x + step)
                blk = read(x, y)
                fo.write(np.clip(blk, -32768, 32767).astype(np.int16).tobytes())
                written += len(blk)
    return written / ASR


# Voz de estúdio: corta o ronco grave, tira o chiado constante (ar-condicionado, ventilador, som da igreja),
# tira o "abafado", dá presença e segura os picos. Suave de propósito: melhora sem deixar a voz robótica.
VOZ_LIMPA = ("highpass=f=80,afftdn=nr=12:nf=-35:tn=1,"
             "equalizer=f=250:t=q:w=1.0:g=-2.5,equalizer=f=3200:t=q:w=1.2:g=3,equalizer=f=9000:t=q:w=1.5:g=1.5,"
             "acompressor=threshold=-20dB:ratio=3:attack=8:release=140:makeup=2,alimiter=limit=0.95:level=disabled")


def post_audio(raw: Path, total: float, job: dict, out: Path) -> Path:
    """Limpeza da voz e música de fundo (que abaixa sozinha quando a pessoa fala e sobe nas pausas).
    Devolve o arquivo de áudio final (ou o mesmo, se nada foi pedido)."""
    clean = bool(job.get("audio_clean"))
    music = job.get("music_path")
    if music and not Path(music).exists():
        music = None
    if not clean and not music:
        return raw
    args = [ff.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
            "-f", "s16le", "-ar", str(ASR), "-ac", str(CH), "-i", str(raw)]
    voz = VOZ_LIMPA if clean else "anull"
    if music:
        vol = max(0.0, min(1.0, float(job.get("music_volume", 0.12))))
        fade_out = max(0.0, total - 2.5)
        args += ["-stream_loop", "-1", "-i", str(music)]
        graph = (f"[0:a]{voz}[v];[v]asplit=2[va][vs];"
                 f"[1:a]aresample={ASR},aformat=sample_fmts=fltp:channel_layouts=stereo,volume={vol:.3f},"
                 f"atrim=0:{total + 0.5:.3f},afade=t=in:d=1.5,afade=t=out:st={fade_out:.3f}:d=2.5[m];"
                 "[m][vs]sidechaincompress=threshold=0.025:ratio=10:attack=20:release=450:makeup=1[md];"
                 "[va][md]amix=inputs=2:duration=first:normalize=0[out]")
    else:
        graph = f"[0:a]{voz}[out]"
    args += ["-filter_complex", graph, "-map", "[out]", "-t", f"{total:.4f}",
             "-f", "s16le", "-ar", str(ASR), "-ac", str(CH), "-c:a", "pcm_s16le", str(out)]
    ff.run(args)
    return out


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


def _clusters(keeps: list[list[float]], max_gap: float = 30.0) -> list[list[int]]:
    """Agrupa trechos consecutivos e próximos: cada grupo vira uma entrada com busca rápida (-ss)."""
    groups: list[list[int]] = []
    for i, (s, e) in enumerate(keeps):
        if groups:
            ps, pe = keeps[groups[-1][-1]]
            if s >= pe - 0.001 and s - pe <= max_gap:
                groups[-1].append(i)
                continue
        groups.append([i])
    while len(groups) > 40:  # limite de entradas: junta os grupos mais próximos
        best = min(range(len(groups) - 1),
                   key=lambda g: keeps[groups[g + 1][0]][0] - keeps[groups[g][-1]][1]
                   if keeps[groups[g + 1][0]][0] >= keeps[groups[g][-1]][1] else 1e9)
        groups[best] += groups.pop(best + 1)
    return groups


def _zoom_levels(keeps: list[list[float]], strength: float = 1.10) -> list[float]:
    """Zoom alternado (1.0 / 1.10) nas emendas visíveis: o "pulo" vira um corte de câmera intencional."""
    levels, cur, acc, last_t = [], 1.0, 0.0, -99.0
    for i, (s, e) in enumerate(keeps):
        if i > 0:
            gap = s - keeps[i - 1][1]
            visible = gap < -0.01 or gap > 0.6
            if visible and acc - last_t >= 2.0:
                cur = strength if cur == 1.0 else 1.0
                last_t = acc
        levels.append(cur)
        acc += e - s
    return levels


def _piecewise(values: list[float], keeps: list[list[float]], fmt=str) -> str:
    bounds, acc = [], 0.0
    for (s, e), v in zip(keeps, values):
        if not bounds or bounds[-1][1] != v:
            bounds.append((acc, v))
        acc += e - s
    # busca binária em vez de uma fila de "if" (o FFmpeg recusa mais de ~100 níveis)
    def arvore(a: int, b: int) -> str:
        if a == b:
            return fmt(bounds[a][1])
        m = (a + b + 1) // 2
        return f"if(lt(t,{bounds[m][0]:.4f}),{arvore(a, m - 1)},{arvore(m, b)})"
    return arvore(0, len(bounds) - 1)


def _layout_chain(job: dict, keeps: list[list[float]], w: int, h: int) -> tuple[list[str], int, int, bool]:
    """Filtros de imagem: tira faixas pretas, enquadra, aplica zoom nas emendas e nitidez.
    Retorna (cadeia, largura, altura, usa_fundo_desfocado)."""
    chain: list[str] = []
    content = (job.get("media") or {}).get("content")
    ox = 0
    if content:
        cx, cy, cw_, ch_ = content
        chain.append(f"crop={cw_}:{ch_}:{cx}:{cy}")
        ox, w, h = cx, cw_, ch_
    out_w, out_h = job.get("out_w") or 0, job.get("out_h") or 0
    enhance = job.get("enhance", "auto")
    lanczos = ":flags=lanczos"
    if not out_w or not out_h:
        return chain + [f"scale=trunc(iw/2)*2:trunc(ih/2)*2{lanczos}"], w - w % 2, h - h % 2, False
    mode = job.get("layout", "face")
    src_ratio, dst_ratio = w / h, out_w / out_h
    if mode == "blur" and abs(src_ratio - dst_ratio) >= 0.02:
        return chain, out_w, out_h, True
    if abs(src_ratio - dst_ratio) < 0.02:
        crop_w, crop_h, xexpr = w, h, "0"
        ychain = []
    elif src_ratio > dst_ratio:  # fonte mais larga: recorta na horizontal, seguindo o rosto
        crop_w, crop_h = int(h * dst_ratio) // 2 * 2, h - h % 2
        fn = job.get("center_fn")
        xs = []
        for s, e in keeps:
            c = fn((s + e) / 2) if fn else 0.5
            full_w = (job.get("media") or {}).get("width") or w
            px = c * full_w - ox
            xs.append(int(min(max(px - crop_w / 2, 0), w - crop_w)) // 2 * 2)
        xexpr = _piecewise(xs, keeps)
        ychain = []
    else:
        crop_w, crop_h = w - w % 2, int(w / dst_ratio) // 2 * 2
        xexpr = "0"
        ychain = [f"(ih-{crop_h})/2"]
    yexpr = ychain[0] if ychain else "0"
    chain.append(f"crop={crop_w}:{crop_h}:'{xexpr}':{yexpr}")
    upscale = out_h / max(crop_h, 1)
    if enhance != "off" and (upscale > 1.25 or enhance == "on"):
        chain.append("hqdn3d=1.5:1.5:3:3")  # tira o "chuvisco" antes de ampliar
    zooms = _zoom_levels(keeps) if job.get("zoom_cuts") else [1.0]
    fortes = job.get("emphasis") or []
    if len(set(zooms)) > 1 or fortes:
        zexpr = _piecewise(zooms, keeps, fmt=lambda v: f"{v:.2f}") if len(set(zooms)) > 1 else "1"
        if fortes:  # aproxima devagar nos momentos fortes da fala e volta
            zexpr = f"({zexpr})*{destaques.expr_zoom(fortes)}"
        chain.append(f"scale=w='trunc({out_w}*({zexpr})/2)*2':h='trunc({out_h}*({zexpr})/2)*2':eval=frame{lanczos}")
        # recorta o centro, um pouco acima do meio (o rosto fica no terço de cima)
        chain.append(f"crop={out_w}:{out_h}:'(in_w-{out_w})/2':'(in_h-{out_h})*0.35'")
    else:
        chain.append(f"scale={out_w}:{out_h}{lanczos}")
    if enhance != "off" and (upscale > 1.25 or enhance == "on"):
        chain.append("unsharp=5:5:0.55:5:5:0.0")  # devolve a nitidez perdida na ampliação
    return chain, out_w, out_h, False


def frame_graph(job: dict, keeps: list[list[float]], src_label: str, folder: Path, tag: str,
                overlays: list | None = None) -> tuple[list[str], str, int, int]:
    """Imagem final: enquadramento + moldura (fundo, tarjas) + legendas/textos (ASS) + logo."""
    media = job["media"]
    geom = job.get("geom")
    parts: list[str] = []
    if geom and geom.get("layout") != "cheia":
        bx, by, bw, bh = geom["box"]
        CW, CH = geom["canvas"]
        sub = {**job, "out_w": bw, "out_h": bh, "layout": "center" if job.get("layout") == "blur" else job.get("layout")}
        chain, _, _, _ = _layout_chain(sub, keeps, media["width"], media["height"])
        if geom["bg"] == "blur":
            pre = chain[0] + "," if media.get("content") else ""
            parts.append(f"{src_label}split[sa][sb]")
            parts.append(f"[sa]{pre}scale={CW}:{CH}:force_original_aspect_ratio=increase,crop={CW}:{CH},"
                         f"boxblur=30:2,eq=brightness=-0.20:saturation=0.9[bgx]")
            parts.append(f"[sb]{','.join(chain)}[fgx]")
            parts.append(f"[bgx][fgx]overlay={bx}:{by}[fr]")
        else:
            color = "0x" + (job.get("bg_color") or "#101114").lstrip("#")
            parts.append(f"{src_label}{','.join(chain)},pad={CW}:{CH}:{bx}:{by}:color={color}[fr]")
        w, h = CW, CH
    else:
        chain, w, h, blur_bg = _layout_chain(job, keeps, media["width"], media["height"])
        if blur_bg:
            lab = src_label
            if chain:
                parts.append(f"{src_label}{','.join(chain)}[cc]")
                lab = "[cc]"
            parts.append(f"{lab}split[bg0][fg0]")
            parts.append(f"[bg0]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=24:2,eq=brightness=-0.08[bg]")
            parts.append(f"[fg0]scale={w}:-2:flags=lanczos[fg]")
            parts.append("[bg][fg]overlay=(W-w)/2:(H-h)/2[fr]")
        else:
            parts.append(src_label + ",".join(chain) + "[fr]")
    label = "[fr]"
    ass_text = job["ass_builder"](w, h, keeps) if job.get("ass_builder") else None
    if ass_text:
        ass_name = f"tmp_{tag}.ass"
        (folder / ass_name).write_text(ass_text, encoding="utf-8")
        fopt = ""
        fonts = job.get("fonts_dir")
        if fonts and Path(fonts).exists():
            fopt = f":fontsdir='{_esc_path(str(fonts))}'"
        parts.append(f"{label}ass='{ass_name}'{fopt}[fs]")
        label = "[fs]"
    for n, (idx, ov) in enumerate(overlays or []):
        op = max(0.05, min(1.0, float(ov.get("opacity", 1.0))))
        alpha = f",colorchannelmixer=aa={op:.2f}" if op < 0.999 else ""
        if ov.get("fade"):  # emoji: aparece e some suave
            a, b = ov["fade"]
            alpha += (f",fade=t=in:st={a:.3f}:d=0.15:alpha=1,"
                      f"fade=t=out:st={max(a + 0.2, b - 0.25):.3f}:d=0.25:alpha=1")
        parts.append(f"[{idx}:v]scale=-1:{int(ov['h'])}:flags=lanczos,format=rgba{alpha}[ov{n}]")
        en = f":enable='{ov['enable']}'" if ov.get("enable") else ""
        out = "[v]" if n == len(overlays) - 1 else f"[ovo{n}]"
        parts.append(f"{label}[ov{n}]overlay=x='{ov['x']}':y='{ov['y']}'{en}:shortest=1{out}")
        label = out
    return parts, label, w, h


def render(job: dict, progress: Optional[Callable[[float, str], None]] = None) -> dict:
    """
    job = {src, folder, media, keeps (em qualquer ordem), ducks, out, out_w, out_h, layout, center_fn,
           ass_builder(width,height,keeps)->str|None, normalize, target_lufs, encoder, quality, fonts_dir}
    """
    folder = Path(job["folder"])
    media = job["media"]
    fps = media.get("fps") or 30.0
    fps_str = media.get("fps_str") or "30"
    keeps = snap_keeps(job["keeps"], fps) if media.get("has_video") else job["keeps"]
    if not keeps:
        raise RuntimeError("Nada para renderizar: todos os trechos foram cortados.")
    tag = Path(job["out"]).stem

    def p(x, msg):
        if progress:
            progress(x, msg)

    # 1) Áudio (precisão de amostra, em qualquer ordem de trechos)
    p(0.02, "Preparando áudio…")
    raw_src = folder / "audio48k.raw"
    ensure_render_audio(job["src"], raw_src)
    out_raw = folder / f"tmp_{tag}.raw"
    total = build_audio(raw_src, keeps, job.get("ducks") or [], out_raw, job.get("smooth", "suave"))
    if job.get("audio_clean") or job.get("music_path"):
        p(0.06, "Limpando a voz e mixando a música…" if job.get("music_path") else "Limpando a voz…")
        mixed = post_audio(out_raw, total, job, folder / f"tmp_{tag}.mix.raw")
        if mixed != out_raw:
            out_raw.unlink(missing_ok=True)
            out_raw = mixed
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
        ff.run_with_progress(args, total, lambda x: p(0.1 + 0.88 * x, "Gerando áudio final…"), cwd=str(folder))
        out_raw.unlink(missing_ok=True)
        return {"duration": total, "file": out}

    # 2) Vídeo: cada grupo de trechos é uma entrada com busca rápida; depois tudo é concatenado
    groups = _clusters(keeps)
    eps = 0.25 / fps
    parts = []
    for gi, g in enumerate(groups):
        g_s = keeps[g[0]][0]
        g_e = max(keeps[i][1] for i in g)
        k0 = max(0, int((g_s - 1.0) * fps))
        offset = k0 / fps
        # busca meio quadro antes, para o primeiro quadro decodificado ser exatamente o quadro k0
        seek = max(0.0, offset - 0.5 / fps) if k0 > 0 else 0.0
        args += (["-ss", f"{seek:.5f}"] if seek > 0 else []) + ["-t", f"{g_e - offset + 1.0:.3f}", "-i", job["src"]]
        terms = ff.soma_expr([f"gte(t,{keeps[i][0] - offset - eps:.4f})*lt(t,{keeps[i][1] - offset - eps:.4f})"
                              for i in g])
        parts.append(f"[{gi}:v]setpts=PTS-STARTPTS,fps={fps_str},select='{terms}',setpts=N/({fps_str})/TB[c{gi}]")
    a_idx = len(groups)
    args += ["-f", "s16le", "-ar", str(ASR), "-ac", str(CH), "-i", str(out_raw)]
    if len(groups) > 1:
        parts.append("".join(f"[c{gi}]" for gi in range(len(groups))) +
                     f"concat=n={len(groups)}:v=1:a=0,setpts=N/({fps_str})/TB[cat]")
        src_label = "[cat]"
    else:
        src_label = "[c0]"
    overlays = []
    for ov in (job["overlay_builder"](keeps) if job.get("overlay_builder") else []):
        if ov and Path(ov["path"]).exists():
            args += ["-loop", "1", "-i", ov["path"]]
            overlays.append((a_idx + 1 + len(overlays), ov))
    fparts, out_label, w, h = frame_graph(job, keeps, src_label, folder, tag, overlays)
    parts += fparts
    if out_label != "[v]":
        parts.append(f"{out_label}null[v]")
    graph = ";".join(parts)
    args += ff.filter_script_args(graph, str(folder / f"tmp_{tag}.filter"))
    args += ["-map", "[v]", "-map", f"{a_idx}:a"]
    if af:
        args += ["-af", af]
    encoder = ff.best_encoder(job.get("encoder", "auto"))
    args += ff.encoder_args(encoder, job.get("quality", "alta"))
    args += ["-r", fps_str, "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", out]
    label = "CPU" if encoder == "libx264" else "GPU"
    p(0.1, f"Renderizando vídeo ({label})…")
    ff.run_with_progress(args, total, lambda x: p(0.1 + 0.89 * x, f"Renderizando vídeo ({label})…"), cwd=str(folder))
    for tmp in folder.glob(f"tmp_{tag}.*"):
        tmp.unlink(missing_ok=True)
    return {"duration": total, "file": out, "encoder": encoder, "width": w, "height": h}

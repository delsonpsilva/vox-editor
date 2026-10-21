"""Pipeline: análise completa ao subir o arquivo, recálculo rápido ao mudar ajustes e renderizações."""
from __future__ import annotations

import json
import time
from pathlib import Path

from ..engine import audio, destaques, edits, exports, frames, platforms, socials, reframe, render, seams, smartcuts, subtitles, transcribe
from ..engine import ffmpeg_tools as ff
from . import store

AUDIO_EXT_OK = (".mp3", ".m4a", ".aac", ".wav", ".ogg", ".opus")


def _set(pid: str, status: str | None = None, pct: float | None = None, msg: str | None = None, **fields):
    def fn(p):
        if status:
            p["status"] = status
        if pct is not None or msg is not None:
            p["progress"] = {"pct": round(pct if pct is not None else p["progress"].get("pct", 0), 3),
                             "msg": msg if msg is not None else p["progress"].get("msg", "")}
        p.update(fields)
    return store.update(pid, fn)


def ensure_speech(folder: Path) -> dict:
    """Garante o mapa de voz (VAD) nas medições — projetos antigos ganham na primeira vez."""
    feat = audio.load_features(folder)
    if "speech" not in feat:
        wav = folder / "analise16k.wav"
        if wav.exists():
            samples = audio.read_wav_mono(str(wav))
            feat["speech"] = audio.speech_mask(samples, len(feat["db"]))
            audio.save_features(feat, folder)
    return feat


def detect(proj: dict, folder: Path) -> dict:
    """Pausas reais (sem voz) e respirações a partir das medições já salvas (instantâneo)."""
    feat = ensure_speech(folder)
    lv = audio.levels(feat["db"])
    st = edits.merged_settings(proj.get("settings"))
    thr = lv["auto_threshold"] if st["silence"]["auto"] else float(st["silence"]["threshold_db"])
    dur = proj["media"]["duration"]
    sil = audio.detect_silences(feat["db"], thr, float(st["silence"]["min_dur"]), 0.0, dur, feat.get("speech"))
    br = audio.detect_breaths(feat, lv, thr, proj.get("words") or [])
    return {"v": 3, "silences": sil, "breaths": br, "levels": lv, "threshold": round(thr, 1),
            "vad": bool("speech" in feat and feat["speech"].any())}


_SEAMS: dict = {}


def seams_for(proj: dict):
    """Emendas inteligentes do projeto (em cache enquanto a análise não muda)."""
    an = proj.get("analysis") or {}
    if not an.get("levels"):
        return None
    f = store.pdir(proj["id"]) / "features.npz"
    if not f.exists():
        return None
    key = (proj["id"], f.stat().st_mtime, an["levels"]["floor"], an["levels"]["speech"])
    if key not in _SEAMS:
        if len(_SEAMS) > 6:
            _SEAMS.clear()
        _SEAMS[key] = seams.Seams(audio.load_features(f.parent), an["levels"])
    return _SEAMS[key]


edits.SEAMS_PROVIDER = seams_for


def analyze(pid: str, progress) -> dict:
    folder = store.pdir(pid)
    proj = store.load(pid)
    src = str(folder / proj["source"])
    cfg = store.load_config()

    def step(pct, msg):
        progress(pct, msg)
        _set(pid, "processando", pct, msg)

    step(0.01, "Lendo informações do arquivo…")
    media = ff.probe(src)
    if media["duration"] <= 0:
        raise RuntimeError("Não consegui ler a duração do arquivo. Ele pode estar corrompido.")
    if not media["has_audio"]:
        raise RuntimeError("O arquivo não tem áudio: não há o que transcrever ou cortar.")
    if media["has_video"]:
        step(0.02, "Verificando bordas pretas…")
        try:
            media["content"] = ff.detect_content(src, media)
        except Exception:
            media["content"] = None
    _set(pid, media=media)

    # Prévia leve para o navegador (só quando o original não toca bem no navegador)
    preview = proj["source"]
    if media["has_video"] and not ff.browser_friendly(media, src):
        step(0.03, "Criando prévia leve para edição…")
        enc = ff.best_encoder(cfg["render"].get("encoder", "auto"))
        args = [ff.ffmpeg(), "-y", "-i", src, "-vf", "scale=-2:'min(720,ih)'"] + ff.encoder_args(enc, "rapida") + \
               ["-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(folder / "previa.mp4")]
        ff.run_with_progress(args, media["duration"], lambda x: step(0.03 + 0.17 * x, "Criando prévia leve para edição…"))
        preview = "previa.mp4"
    elif not media["has_video"] and Path(src).suffix.lower() not in AUDIO_EXT_OK:
        ff.run([ff.ffmpeg(), "-y", "-loglevel", "error", "-i", src, "-vn", "-c:a", "aac", "-b:a", "160k",
                str(folder / "previa.m4a")])
        preview = "previa.m4a"
    _set(pid, preview=preview)

    step(0.21, "Extraindo e medindo o áudio…")
    wav = folder / "analise16k.wav"
    audio.extract_analysis_audio(src, str(wav))
    samples = audio.read_wav_mono(str(wav))
    feat = audio.compute_features(samples)
    step(0.24, "Detectando onde há voz…")
    feat["speech"] = audio.speech_mask(samples, len(feat["db"]))
    audio.save_features(feat, folder)
    (folder / "onda.json").write_text(json.dumps(audio.waveform(samples)), encoding="utf-8")
    del samples

    step(0.27, "Transcrevendo a fala…")
    t0 = time.time()
    try:
        tr = transcribe.transcribe(str(wav), cfg["transcription"], str(store.MODELS), feat["db"], media["duration"],
                                   lambda x, m: step(0.27 + 0.6 * x, m))
    except Exception as e:
        hint = ("Na primeira vez o modelo de transcrição é baixado da internet (uma única vez). "
                "Verifique a conexão ou use uma API nas Configurações.") if cfg["transcription"].get("provider") == "local" \
            else "Confira a chave e o endereço da API nas Configurações."
        raise RuntimeError(f"Falha na transcrição: {str(e)[:200]}. {hint}")
    _set(pid, words=tr["words"], segments=tr["segments"], language=tr.get("language"),
         transcribe_seconds=round(time.time() - t0, 1))

    step(0.88, "Detectando silêncios e respirações…")
    proj = store.load(pid)
    an = detect(proj, folder)
    _set(pid, analysis=an)

    step(0.92, "Procurando os melhores cortes…")
    proj = store.load(pid)
    clips, how = make_clips(proj, cfg)
    _set(pid, "pronto", 1.0, "Pronto para editar", clips=clips, clips_source=how)
    return {"ok": True}


def make_clips(proj: dict, cfg: dict) -> tuple[list[dict], str]:
    st = edits.merged_settings(proj.get("settings"))
    studio = st["studio"]
    lo, hi = platforms.duration_range(studio)
    plat = platforms.get(studio.get("platform"))
    clips, how = smartcuts.generate(proj, studio, lo, hi, cfg["ai"], plat["name"])
    stamp = int(time.time()) % 100000
    for i, c in enumerate(clips):
        c["id"] = f"c{stamp}{i + 1:02d}"
    return clips, how


def reanalyze(pid: str) -> dict:
    folder = store.pdir(pid)
    with store.lock(pid):
        proj = store.load(pid)
        proj["analysis"] = detect(proj, folder)
        store.save(proj)
    return proj


def regenerate_clips(pid: str, progress, keep_old: bool = False) -> dict:
    progress(0.1, "A IA está lendo a transcrição…")
    proj = store.load(pid)
    clips, how = make_clips(proj, store.load_config())

    def fn(p):
        old = [c for c in p.get("clips", []) if c.get("pinned")] if not keep_old else p.get("clips", [])
        p["clips"] = old + clips
        p["clips_source"] = how
    store.update(pid, fn)
    return {"count": len(clips), "source": how}


def ai_cleanup(pid: str, progress) -> dict:
    from ..engine import cleanup
    proj = store.load(pid)
    ai = store.load_config()["ai"]
    if ai.get("provider") in (None, "none") or not ai.get("api_key"):
        raise RuntimeError("Configure uma IA (Claude ou compatível) em Configurações para usar a limpeza com IA.")
    words = proj.get("words") or []
    if not words:
        raise RuntimeError("Este vídeo não tem transcrição.")
    cuts = cleanup.analyze(words, ai, progress)
    store.update(pid, lambda p: p.update(ai_cuts=cuts))
    return {"count": len(cuts)}


def clip_segments(proj: dict, clip: dict) -> list[list[float]]:
    """Trechos do corte abertos até a pausa real mais próxima (nenhuma palavra começa ou termina cortada)."""
    sm = seams_for(proj)
    dur = proj["media"]["duration"]
    segs = []
    for s, e in clip["segments"]:
        a, b = sm.expand_segment(s, e, dur) if sm else (max(0.0, s - 0.15), min(dur, e + 0.25))
        if segs and 0 <= a - segs[-1][1] < 0.05 or (segs and segs[-1][0] <= a <= segs[-1][1]):
            segs[-1][1] = max(segs[-1][1], b)
        else:
            segs.append([a, b])
    return segs


def clip_keeps(proj: dict, clip: dict) -> list[list[float]]:
    ed = edits.build_edit(proj)
    return edits.intersect(ed["keeps"], clip_segments(proj, clip))


def split_parts(keeps: list[list[float]], limit: float, words: list[dict]) -> list[list[list[float]]]:
    """Divide em partes equilibradas de no máximo `limit` segundos, cortando nas pausas entre palavras."""
    import math
    total = sum(e - s for s, e in keeps)
    n0 = max(1, math.ceil(total / limit))
    parts = []
    for n in range(n0, n0 + 4):
        parts = _greedy_parts(keeps, min(limit, total / n + 1.5), words)
        if len(parts) <= n or min(sum(e - s for s, e in pt) for pt in parts) >= 4:
            break
    if len(parts) > 1 and sum(e - s for s, e in parts[-1]) < 4:
        last = parts.pop()
        if sum(e - s for s, e in parts[-1]) + sum(e - s for s, e in last) <= limit:
            parts[-1] += last
        else:
            parts.append(last)
    return parts


def _greedy_parts(keeps: list[list[float]], limit: float, words: list[dict]) -> list[list[list[float]]]:
    import bisect
    gaps = sorted({round((words[i]["e"] + words[i + 1]["s"]) / 2, 3) for i in range(len(words) - 1)
                   if words[i + 1]["s"] - words[i]["e"] > 0.04}) if words else []
    parts: list[list[list[float]]] = []
    cur: list[list[float]] = []
    acc = 0.0
    queue = [list(k) for k in keeps]
    while queue:
        s, e = queue.pop(0)
        room = limit - acc
        if e - s <= room:
            cur.append([s, e])
            acc += e - s
            continue
        i = bisect.bisect_right(gaps, s + room) - 1
        if i >= 0 and gaps[i] > s + 1.0:
            cur.append([s, gaps[i]])
            queue.insert(0, [gaps[i], e])
        elif cur:
            queue.insert(0, [s, e])
        else:
            cur.append([s, s + room])
            queue.insert(0, [s + room, e])
        parts.append(cur)
        cur, acc = [], 0.0
    if cur:
        parts.append(cur)
    return [p for p in parts if sum(e - s for s, e in p) > 0.3]


def _center_fn(proj: dict, segments: list[list[float]], layout: str):
    """Função tempo-original → centro horizontal (0..1), a partir do rosto de cada trecho."""
    if layout != "face":
        return None
    folder = store.pdir(proj["id"])
    cache = dict(store.load(proj["id"]).get("faces") or {})
    xs = reframe.smooth(reframe.centers_for(str(folder / proj["source"]), segments, proj["media"], cache))
    store.update(proj["id"], lambda p: p.setdefault("faces", {}).update(cache))

    def fn(t: float) -> float:
        k = next((i for i, (a, b) in enumerate(segments) if a - 0.05 <= t <= b + 0.05), None)
        if k is None:
            k = min(range(len(segments)), key=lambda i: min(abs(t - segments[i][0]), abs(t - segments[i][1])))
        return xs[k]
    return fn


def brand_settings(cfg: dict | None = None) -> dict:
    cfg = cfg or store.load_config()
    b = {**frames.DEFAULT_BRAND, **(cfg.get("brand") or {})}
    logo = store.BRAND_DIR / "logo.png"
    b["logo_path"] = str(logo) if logo.exists() else None
    icons = {}
    for net in socials.NETS:
        f = store.BRAND_DIR / "icones" / f"{net}.png"
        if f.exists():
            icons[net] = str(f)
    b["icons"] = icons
    return b


MUSICAS = store.BRAND_DIR / "musicas"


def musica_path(nome: str) -> str | None:
    if not nome or "/" in nome or "\\" in nome or nome.startswith("."):
        return None
    f = MUSICAS / nome
    return str(f) if f.is_file() else None


def destaques_do_trecho(pid: str, keeps: list[list[float]], st: dict, cfg: dict, progress=None) -> dict:
    """Palavras-chave e emojis das palavras deste trecho. Com IA ligada, pergunta só o que ainda não perguntou
    (fica guardado no projeto); sem IA, usa a escolha local. Nunca trava o render: se a IA falhar, segue sem ela."""
    proj = store.load(pid)
    words = proj.get("words") or []
    if not words:
        return {}
    idxs = destaques.palavras_do_trecho(words, keeps)
    local = destaques.locais(words)
    ai = cfg.get("ai") or {}
    salvo = proj.get("destaques_ia") or {"feitos": [], "mapa": {}}
    feitos = set(salvo.get("feitos") or [])
    usar_ia = st["subtitles"].get("ai_highlights", True) and ai.get("provider") not in (None, "none") and ai.get("api_key")
    if usar_ia:
        faltam = [i for i in idxs if i not in feitos]
        if len(faltam) >= 8:
            if progress:
                progress(0.015, "A IA está escolhendo as palavras-chave e os emojis…")
            try:
                novo = destaques.com_ia(words, faltam, ai)

                def fn(p):
                    d = p.setdefault("destaques_ia", {"feitos": [], "mapa": {}})
                    d["feitos"] = sorted(set(d.get("feitos") or []) | set(faltam))
                    d.setdefault("mapa", {}).update({str(k): v for k, v in novo.items()})
                salvo = store.update(pid, fn)["destaques_ia"]
                feitos = set(salvo["feitos"])
            except Exception as e:  # sem crédito, sem internet…: usa a escolha local
                print("destaques com IA falharam:", e)
    mapa = {}
    for i in idxs:
        if i in feitos:
            d = (salvo.get("mapa") or {}).get(str(i))
        else:
            d = local.get(i)
        if d:
            mapa[str(i)] = d
    return mapa


def clip_framing(pid: str, clip_id: str) -> dict:
    proj = store.load(pid)
    clip = next((c for c in proj.get("clips", []) if c["id"] == clip_id), None)
    if not clip:
        raise FileNotFoundError("Corte não encontrado")
    segs = clip["segments"]
    cache = dict(proj.get("faces") or {})
    xs = reframe.smooth(reframe.centers_for(str(store.pdir(pid) / proj["source"]), segs, proj["media"], cache))
    store.update(pid, lambda p: p.setdefault("faces", {}).update(cache))
    return {"segments": segs, "centers": xs}


def _render_keeps(pid: str, progress, keeps: list[list[float]], *, name: str, platform: str | None,
                  layout: str = "face", with_subs: bool = True, title: str | None = None, title_mode: str = "nao",
                  segments: list[list[float]] | None = None, label: str = "", zoom_cuts: bool = False,
                  kicker: str = "", frame_layout: str = "cheia", meta: dict | None = None) -> dict:
    folder = store.pdir(pid)
    proj = store.load(pid)
    cfg = store.load_config()
    st = edits.merged_settings(proj.get("settings"))
    ed = edits.build_edit(proj)
    media = proj["media"]
    if media.get("has_video") and "content" not in media:  # projetos antigos: detecta bordas pretas agora
        try:
            media["content"] = ff.detect_content(str(folder / proj["source"]), media)
        except Exception:
            media["content"] = None
        store.update(pid, lambda p: p["media"].update(content=media["content"]))
    plat = platforms.get(platform) if platform else None
    out_w = plat["w"] if plat and plat["w"] else 0
    out_h = plat["h"] if plat and plat["h"] else 0
    if out_w and media.get("has_video"):
        if progress:
            progress(0.01, "Enquadrando quem está falando…")
        center_fn = _center_fn(proj, segments or keeps, layout)
    else:
        center_fn = None

    brand = brand_settings(cfg)
    # destaques (palavras-chave, emojis, momentos fortes): só nos vídeos verticais/cortes com legenda
    mapa: dict = {}
    sub_cfg = st["subtitles"]
    quer_kw = with_subs and sub_cfg.get("keywords", True)
    quer_emoji = with_subs and sub_cfg.get("emojis", True) and bool(out_w) and media.get("has_video")
    quer_zoom = bool(out_w) and st["studio"].get("emphasis_zoom", True) and media.get("has_video")
    if proj.get("words") and (quer_kw or quer_emoji or quer_zoom):
        mapa = destaques_do_trecho(pid, keeps, st, cfg, progress)
    words_leg = destaques.marcar(proj.get("words") or [], mapa) if quer_kw else (proj.get("words") or [])
    fortes = []
    if quer_zoom:
        try:
            feats = audio.load_features(folder)
        except Exception:
            feats = None
        fortes = destaques.momentos_fortes(proj.get("words") or [], feats, keeps, mapa)
    geom = frames.geometry(frame_layout if out_w and out_h and out_h > out_w else "cheia", out_w or 1920, out_h or 1080) \
        if out_w else None

    def ass_builder(w, h, snapped):
        tmap = edits.TimeMap(snapped)
        g = frames.geometry(geom["layout"], w, h) if geom else frames.geometry("cheia", w, h)
        font = st["subtitles"].get("font") or "Poppins ExtraBold"
        fstyles, fevents = frames.overlay(g, brand, title or "", kicker or brand.get("kicker", ""), tmap.total, font,
                                          title_mode) if out_w else ([], [])
        if out_w:
            bs, be = socials.badge_events(g, brand, platform, tmap.total, font, brand.get("icons"))
            fstyles, fevents = fstyles + bs, fevents + be
        has_text = (with_subs and proj.get("words")) or (title and title_mode != "nao") or fevents
        if not has_text:
            return None
        caps = subtitles.build_captions(words_leg, tmap, st["subtitles"]) if with_subs and proj.get("words") else []
        frame = {"styles": fstyles, "events": fevents, "sub_pos": g.get("sub"), "band_title": bool(g.get("title"))}
        tm = title_mode if not g.get("title") else "nao"
        return subtitles.to_ass(caps, st["subtitles"], w, h, title=title, title_mode=tm, total=tmap.total, frame=frame)

    def overlay_builder(snapped):
        if not out_w:
            return []
        total = sum(e - s for s, e in snapped)
        g = frames.geometry(geom["layout"], out_w, out_h) if geom else frames.geometry("cheia", out_w, out_h)
        ovs = [socials.logo_overlay(g, brand, brand.get("logo_path"))]
        ovs += socials.icon_overlays(g, brand, platform, total, brand.get("icons") or {})
        if quer_emoji and mapa:
            x, y, tam = subtitles.emoji_box(sub_cfg, out_w, out_h, g.get("sub"))
            for ev in destaques.eventos_emoji(proj.get("words") or [], mapa, snapped):
                f = destaques.arquivo_emoji(ev["e"])
                if not f:
                    continue
                s0, s1 = ev["s"], ev["fim"]
                ovs.append({"path": str(f), "h": tam, "x": str(int(x - tam / 2)),
                            "y": f"{y}+{int(tam * 0.18)}*(1-clip((t-{s0:.3f})/0.18,0,1))",
                            "enable": f"between(t,{s0:.3f},{s1:.3f})", "fade": (s0, s1)})
        return [o for o in ovs if o]

    ext = "mp4" if media.get("has_video") else "m4a"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_name = f"{name}-{stamp}.{ext}"
    out = folder / "renders" / out_name
    t0 = time.time()
    res = render.render({
        "src": str(folder / proj["source"]), "folder": str(folder), "media": media, "keeps": keeps,
        "ducks": ed["active_ducks"], "out": str(out), "out_w": out_w, "out_h": out_h, "layout": layout,
        "center_fn": center_fn, "ass_builder": ass_builder if media.get("has_video") else None,
        "zoom_cuts": zoom_cuts, "enhance": st["studio"].get("enhance", "auto"), "emphasis": fortes,
        "smooth": (st.get("render") or {}).get("smooth", "suave"),
        "audio_clean": bool(st["audio"].get("clean")), "music_path": musica_path(st["audio"].get("music", "")),
        "music_volume": st["audio"].get("music_volume", 0.12),
        "geom": geom, "bg_color": brand.get("bg"), "overlay_builder": overlay_builder,
        "normalize": st["audio"]["normalize"], "target_lufs": st["audio"]["target_lufs"],
        "encoder": cfg["render"].get("encoder", "auto"),
        "quality": st["render"].get("quality") or cfg["render"].get("quality", "alta"),
        "fonts_dir": str(store.FONTS),
    }, progress)
    item = {"file": out_name, "created": time.time(), "duration": round(res["duration"], 2),
            "seconds": round(time.time() - t0, 1), "encoder": res.get("encoder"),
            "vertical": bool(out_h and out_h > out_w), "platform": platform, "label": label,
            "subtitles": with_subs, "size": out.stat().st_size, **(meta or {})}
    store.update(pid, lambda p: p.setdefault("renders", []).insert(0, item))
    return item


def render_full(pid: str, opts: dict, progress) -> dict:
    proj = store.load(pid)
    keeps = edits.build_edit(proj)["keeps"]
    platform = "ig_reels" if opts.get("vertical") else None
    return _render_keeps(pid, progress, keeps, name="editado", platform=platform,
                         layout=opts.get("layout", "face"), with_subs=bool(opts.get("subtitles", True)),
                         zoom_cuts=bool(opts.get("zoom_cuts", False)),
                         label="Vídeo editado" + (" 9:16" if platform else ""), meta={"completo": True})


def _slug(text: str) -> str:
    import re
    import unicodedata
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    t = re.sub(r"[^A-Za-z0-9]+", "-", t).strip("-").lower()
    return t[:40] or "corte"


def render_clip(pid: str, clip_id: str, opts: dict, progress) -> dict:
    proj = store.load(pid)
    clip = next((c for c in proj.get("clips", []) if c["id"] == clip_id), None)
    if not clip:
        raise RuntimeError("Corte não encontrado.")
    st = edits.merged_settings(proj.get("settings"))["studio"]
    platform = opts.get("platform") or st["platform"]
    layout = opts.get("layout") or st["layout"]
    title_mode = opts.get("title_mode") or st["title_mode"]
    with_subs = bool(opts.get("subtitles", st.get("subtitles", True)))
    keeps = clip_keeps(proj, clip)
    plat = platforms.get(platform)
    parts = [keeps]
    if plat.get("split") and plat.get("max") and sum(e - s for s, e in keeps) > plat["max"] + 0.5:
        parts = split_parts(keeps, plat["max"] - 0.5, proj.get("words") or [])
    title = clip.get("hook") or clip.get("title")
    base = f"{_slug(clip.get('title', 'corte'))}-{plat['short'].lower().replace(':', 'x')}"
    results = []
    for i, part in enumerate(parts):
        def prog(x, m, i=i):
            progress((i + x) / len(parts), (f"Parte {i + 1} de {len(parts)}: " if len(parts) > 1 else "") + m)
        name = base + (f"-parte{i + 1}de{len(parts)}" if len(parts) > 1 else "")
        label = clip.get("title", "Corte") + (f" (parte {i + 1}/{len(parts)})" if len(parts) > 1 else "")
        results.append(_render_keeps(pid, prog, part, name=name, platform=platform, layout=layout,
                                     with_subs=with_subs, title=title if i == 0 else None,
                                     title_mode=title_mode, segments=clip_segments(proj, clip), label=label,
                                     zoom_cuts=bool(opts.get("zoom_cuts", st.get("zoom_cuts", True))),
                                     kicker=clip.get("kicker", ""), frame_layout=opts.get("frame") or st.get("frame", "cheia"),
                                     meta={"clip": clip_id, "title": clip.get("title", ""), "post": clip.get("post", "")}))
    store.update(pid, lambda p: [c.update(rendered=True) for c in p.get("clips", []) if c["id"] == clip_id])
    return {"parts": len(results), "files": [r["file"] for r in results]}


# ----------------------------- imagens de prévia -----------------------------

def _crop_filter(media: dict, cx: float, vertical: bool, layout: str) -> str:
    w, h = media["width"], media["height"]
    pre = ""
    if media.get("content"):
        x0, y0, cw0, ch0 = media["content"]
        pre = f"crop={cw0}:{ch0}:{x0}:{y0},"
        cx = (cx * w - x0) / cw0
        w, h = cw0, ch0
    return pre + _crop_core(w, h, cx, vertical, layout)


def _crop_core(w: int, h: int, cx: float, vertical: bool, layout: str) -> str:
    if not vertical:
        return "scale=640:-2"
    if layout == "blur" and w > h:
        return ("split[a][b];[a]scale=540:960:force_original_aspect_ratio=increase,crop=540:960,boxblur=20:2[bg];"
                "[b]scale=540:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")
    if w > h:
        cw = int(h * 9 / 16) // 2 * 2
        x = int(min(max(cx * w - cw / 2, 0), w - cw))
        return f"crop={cw}:{h - h % 2}:{x}:0,scale=540:960"
    return "scale=540:960:force_original_aspect_ratio=increase,crop=540:960"


def thumbnail(pid: str, t: float, vertical: bool, layout: str) -> Path:
    proj = store.load(pid)
    folder = store.pdir(pid)
    media = proj["media"]
    out = folder / "cache" / f"thumb-{t:.2f}-{int(vertical)}-{layout}.jpg"
    if out.exists():
        return out
    out.parent.mkdir(exist_ok=True)
    cx = 0.5
    if vertical and layout == "face" and reframe.available():
        x = reframe.face_x(str(folder / proj["source"]), t, media["width"], media["height"])
        cx = x if x is not None else 0.5
    ff.run([ff.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(folder / proj["source"]),
            "-frames:v", "1", "-filter_complex", _crop_filter(media, cx, vertical, layout), "-q:v", "4", str(out)])
    return out


def subtitle_preview(pid: str, style: str, t: float | None, overrides: dict | None = None) -> Path:
    """Renderiza um quadro real do vídeo com a legenda no estilo pedido (o mesmo motor da exportação)."""
    import hashlib
    proj = store.load(pid)
    folder = store.pdir(pid)
    media = proj["media"]
    st = dict(edits.merged_settings(proj.get("settings"))["subtitles"])
    if style and style != st.get("style"):
        st.update({k: v for k, v in subtitles.STYLES.get(style, {}).items() if k not in ("name", "desc")})
        st["style"] = style
    st.update(overrides or {})
    words = proj.get("words") or []
    if t is None:
        t = _preview_time(proj)
    key = hashlib.md5(json.dumps([st, round(t, 2)], sort_keys=True).encode()).hexdigest()[:12]
    out = folder / "cache" / f"leg-{key}.jpg"
    if out.exists():
        return out
    out.parent.mkdir(exist_ok=True)
    # janela de palavras ao redor de t; o quadro mostra o instante t
    w0 = max(0.0, t - 4.0)
    caps = subtitles.build_captions(words, None, st, window=(w0, t + 4.0))
    W, H = 540, 960
    ass = subtitles.to_ass(caps, st, W, H, title=None, title_mode="nao")
    ass_path = folder / "cache" / f"leg-{key}.ass"
    ass_path.write_text(ass, encoding="utf-8")
    cx = 0.5
    if reframe.available():
        x = reframe.face_x(str(folder / proj["source"]), t, media["width"], media["height"])
        cx = x if x is not None else 0.5
    crop = _crop_filter(media, cx, True, "face")
    fonts = render._esc_path(str(store.FONTS))
    graph = f"[0:v]{crop},setpts=PTS-STARTPTS+{t - w0:.3f}/TB,ass='{ass_path.name}':fontsdir='{fonts}'"
    ff.run([ff.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", str(folder / proj["source"]),
            "-frames:v", "1", "-filter_complex", graph, "-q:v", "4", str(out)], cwd=str(folder / "cache"))
    ass_path.unlink(missing_ok=True)
    return out


def frame_still(pid: str, layout: str, t: float | None = None, clip_id: str | None = None, subs: bool = True,
                full: bool = False) -> Path:
    """Um quadro real com a moldura completa (tarja, selo, título, legenda, @perfil, logo)."""
    import hashlib
    proj = store.load(pid)
    folder = store.pdir(pid)
    media = proj["media"]
    st = edits.merged_settings(proj.get("settings"))
    brand = brand_settings()
    clip = next((c for c in proj.get("clips", []) if c["id"] == clip_id), None) if clip_id else None
    if clip is None and proj.get("clips"):
        clip = proj["clips"][0]
    if t is None:
        if clip:
            s0, e0 = clip["segments"][0]
            words = [w for w in proj.get("words") or [] if s0 + 1 <= w["s"] <= e0 - 1]
            t = (words[len(words) // 3]["s"] + words[len(words) // 3]["e"]) / 2 if words else s0 + min(2.0, (e0 - s0) / 2)
        else:
            t = _preview_time(proj)
    platform = st["studio"].get("platform", "ig_reels")
    title = (clip or {}).get("hook") or (clip or {}).get("title") or "Título do seu corte aparece aqui"
    kicker = (clip or {}).get("kicker") or brand.get("kicker") or ""
    stamp = [frames.VERSION, 5, platform, layout, round(t, 2), title, kicker, subs, full, st["subtitles"], st["studio"].get("layout"),
             {k: v for k, v in brand.items()}, (store.BRAND_DIR / "logo.png").stat().st_mtime
             if brand.get("logo_path") else 0]
    key = hashlib.md5(json.dumps(stamp, sort_keys=True, default=str).encode()).hexdigest()[:12]
    out = folder / "cache" / f"frame-{key}.jpg"
    if out.exists():
        return out
    out.parent.mkdir(exist_ok=True)
    W, H = 1080, 1920
    geom = frames.geometry(layout, W, H)
    cx = 0.5
    if reframe.available() and st["studio"].get("layout", "face") == "face":
        x = reframe.face_x(str(folder / proj["source"]), t, media["width"], media["height"])
        cx = x if x is not None else 0.5
    w0 = max(0.0, t - 4.0)

    def ass_builder(w, h, keeps):
        font = st["subtitles"].get("font") or "Poppins ExtraBold"
        g = frames.geometry(layout, w, h)
        fs, fe = frames.overlay(g, brand, title, kicker, 60.0, font, "fixo", cover=not subs)
        if subs:  # na prévia aparece o selo da rede de destino (na capa, não)
            bs, be = socials.badge_events(g, brand, platform, 60.0, font, brand.get("icons"))
            fs, fe = fs + bs, fe + be
        caps = subtitles.build_captions(proj.get("words") or [], None, st["subtitles"], window=(w0, t + 4.0)) if subs else []
        tm = "fixo" if (subs and not g.get("title")) else "nao"
        return subtitles.to_ass(caps, st["subtitles"], w, h, title=title, title_mode=tm,
                                total=60.0, frame={"styles": fs, "events": fe, "sub_pos": g.get("sub"),
                                                   "band_title": bool(g.get("title"))})
    job = {"media": media, "geom": geom, "out_w": W, "out_h": H, "layout": st["studio"].get("layout", "face"),
           "center_fn": lambda _t: cx, "zoom_cuts": False, "enhance": st["studio"].get("enhance", "auto"),
           "bg_color": brand.get("bg"), "ass_builder": ass_builder, "fonts_dir": str(store.FONTS)}
    tag = "still" + key
    ovs = [socials.logo_overlay(geom, brand, brand.get("logo_path"))]
    if subs:
        ovs += socials.icon_overlays(geom, brand, platform, 60.0, brand.get("icons") or {})
    ovs = [o for o in ovs if o]
    overlays = [(1 + i, o) for i, o in enumerate(ovs)]
    parts, label, w, h = render.frame_graph(job, [[t, t + 1.0]], "[s0]", folder / "cache", tag, overlays)
    final = "null" if full else "scale=540:960:flags=lanczos"
    graph = f"[0:v]setpts=PTS-STARTPTS+{t - w0:.3f}/TB[s0];" + ";".join(parts) + f";{label}{final}[out]"
    args = [ff.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", str(folder / proj["source"])]
    for _, o in overlays:
        args += ["-loop", "1", "-i", o["path"]]
    args += ["-filter_complex", graph, "-map", "[out]", "-frames:v", "1", "-q:v", "2" if full else "4", str(out)]
    ff.run(args, cwd=str(folder / "cache"))
    for tmp in (folder / "cache").glob(f"tmp_{tag}.*"):
        tmp.unlink(missing_ok=True)
    return out


def cover_time(proj: dict, clip: dict) -> float:
    """Melhor quadro para a capa: rosto grande e nítido, de boca fechada é impossível saber — usa o mais nítido."""
    s0, e0 = clip["segments"][0]
    folder = store.pdir(proj["id"])
    media = proj["media"]
    best, best_t = -1.0, s0 + min(1.5, (e0 - s0) / 2)
    if reframe.available() and media.get("has_video"):
        span = min(e0 - s0, 20.0)
        for k in range(6):
            t = s0 + span * (k + 0.5) / 6
            fs = reframe.faces_at(str(folder / proj["source"]), t, media["width"], media["height"])
            if fs:
                f = max(fs, key=lambda x: x[1] * min(x[2], 400))
                score = f[1] * 1000 + min(f[2], 400) / 40
                if score > best:
                    best, best_t = score, t
    return round(best_t, 2)


def _preview_time(proj: dict) -> float:
    """Um instante bom para a prévia: o meio de uma frase longa, no meio de uma palavra."""
    words = proj.get("words") or []
    if not words:
        return min(5.0, (proj.get("media") or {}).get("duration", 10) / 2)
    clips = proj.get("clips") or []
    start = clips[0]["segments"][0][0] + 2 if clips else words[len(words) // 3]["s"]
    for i, w in enumerate(words):
        if w["s"] >= start and i + 4 < len(words) and words[i + 4]["e"] - w["s"] < 3:
            ww = words[i + 2]
            return (ww["s"] + ww["e"]) / 2
    return (words[0]["s"] + words[0]["e"]) / 2


def export(pid: str, fmt: str) -> tuple[str, str, str]:
    """Retorna (conteúdo, nome do arquivo, tipo)."""
    proj = store.load(pid)
    folder = store.pdir(pid)
    st = edits.merged_settings(proj.get("settings"))
    ed = edits.build_edit(proj)
    media = proj["media"]
    keeps = edits.snap_keeps(ed["keeps"], media.get("fps") or 30) if media.get("has_video") else ed["keeps"]
    base = Path(proj["name"]).stem
    if fmt == "srt":
        caps = subtitles.build_captions(proj.get("words", []), edits.TimeMap(keeps), st["subtitles"])
        return subtitles.to_srt(caps), f"{base}-legendas.srt", "application/x-subrip"
    if fmt == "srt-original":
        caps = subtitles.build_captions(proj.get("words", []), None, st["subtitles"])
        return subtitles.to_srt(caps), f"{base}-legendas-original.srt", "application/x-subrip"
    if fmt == "edl":
        return exports.to_edl(keeps, media["fps"], Path(proj["source"]).name, base), f"{base}.edl", "text/plain"
    if fmt == "xml":
        return exports.to_fcpxml7(keeps, media, str(folder / proj["source"]), base), f"{base}-premiere-davinci.xml", "application/xml"
    if fmt == "txt":
        return exports.to_text(proj.get("words", []), proj.get("segments", [])), f"{base}-transcricao.txt", "text/plain"
    raise ValueError("Formato desconhecido")

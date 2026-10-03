"""Pipeline: análise completa ao subir o arquivo, recálculo rápido ao mudar ajustes e renderizações."""
from __future__ import annotations

import json
import time
from pathlib import Path

from ..engine import audio, edits, exports, render, smartcuts, subtitles, transcribe
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


def detect(proj: dict, folder: Path) -> dict:
    """Silêncios e respirações a partir das medições já salvas (instantâneo)."""
    feat = audio.load_features(folder)
    lv = audio.levels(feat["db"])
    st = edits.merged_settings(proj.get("settings"))
    thr = lv["auto_threshold"] if st["silence"]["auto"] else float(st["silence"]["threshold_db"])
    dur = proj["media"]["duration"]
    sil = audio.detect_silences(feat["db"], thr, float(st["silence"]["min_dur"]), float(st["silence"]["pad"]), dur)
    br = audio.detect_breaths(feat, lv, thr, proj.get("words") or [])
    return {"silences": sil, "breaths": br, "levels": lv, "threshold": round(thr, 1)}


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
    st = edits.merged_settings(proj.get("settings"))
    clips, how = smartcuts.find_clips(proj, st["clips"], cfg["ai"])
    _set(pid, "pronto", 1.0, "Pronto para editar", clips=clips, clips_source=how)
    return {"ok": True}


def reanalyze(pid: str) -> dict:
    folder = store.pdir(pid)
    with store.lock(pid):
        proj = store.load(pid)
        proj["analysis"] = detect(proj, folder)
        store.save(proj)
    return proj


def regenerate_clips(pid: str, progress) -> dict:
    progress(0.1, "A IA está lendo a transcrição…")
    proj = store.load(pid)
    st = edits.merged_settings(proj.get("settings"))
    clips, how = smartcuts.find_clips(proj, st["clips"], store.load_config()["ai"])
    store.update(pid, lambda p: p.update(clips=clips, clips_source=how))
    return {"count": len(clips), "source": how}


def _render_common(pid: str, progress, *, window=None, vertical=False, with_subs=True, name="video",
                   apply_cuts=True) -> dict:
    folder = store.pdir(pid)
    proj = store.load(pid)
    cfg = store.load_config()
    st = edits.merged_settings(proj.get("settings"))
    ed = edits.build_edit(proj)
    keeps = ed["keeps"] if apply_cuts else [[0.0, proj["media"]["duration"]]]
    if window:
        keeps = [[max(s, window[0]), min(e, window[1])] for s, e in keeps if e > window[0] and s < window[1]]
        keeps = [k for k in keeps if k[1] - k[0] > 0.05]
    media = proj["media"]
    ass_text = None
    if with_subs and proj.get("words") and media.get("has_video"):
        snapped = edits.snap_keeps(keeps, media["fps"])
        tmap = edits.TimeMap(snapped)
        caps = subtitles.build_captions(proj["words"], tmap, st["subtitles"])
        w, h = (1080, 1920) if vertical else (media["width"] - media["width"] % 2, media["height"] - media["height"] % 2)
        ass_text = subtitles.to_ass(caps, st["subtitles"], w, h)
    ext = "mp4" if media.get("has_video") else "m4a"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_name = f"{name}-{stamp}.{ext}"
    out = folder / "renders" / out_name
    t0 = time.time()
    res = render.render({
        "src": str(folder / proj["source"]), "folder": str(folder), "media": media, "keeps": keeps,
        "ducks": ed["active_ducks"], "out": str(out), "window": window, "vertical": vertical,
        "ass_text": ass_text, "normalize": st["audio"]["normalize"], "target_lufs": st["audio"]["target_lufs"],
        "encoder": cfg["render"].get("encoder", "auto"), "quality": st["render"].get("quality") or cfg["render"].get("quality", "alta"),
        "fonts_dir": str(store.FONTS),
    }, progress)
    item = {"file": out_name, "created": time.time(), "duration": round(res["duration"], 2),
            "seconds": round(time.time() - t0, 1), "encoder": res.get("encoder"), "vertical": vertical,
            "subtitles": bool(ass_text), "size": out.stat().st_size}
    store.update(pid, lambda p: p.setdefault("renders", []).insert(0, item))
    return item


def render_full(pid: str, opts: dict, progress) -> dict:
    return _render_common(pid, progress, with_subs=bool(opts.get("subtitles", True)), vertical=bool(opts.get("vertical")),
                          name="editado")


def render_clip(pid: str, clip_id: str, opts: dict, progress) -> dict:
    proj = store.load(pid)
    clip = next((c for c in proj.get("clips", []) if c["id"] == clip_id), None)
    if not clip:
        raise RuntimeError("Corte não encontrado.")
    return _render_common(pid, progress, window=(clip["s"], clip["e"]), vertical=bool(opts.get("vertical", True)),
                          with_subs=bool(opts.get("subtitles", True)), name=clip_id)


def export(pid: str, fmt: str) -> tuple[str, str, str]:
    """Retorna (conteúdo, nome do arquivo, tipo)."""
    proj = store.load(pid)
    folder = store.pdir(pid)
    st = edits.merged_settings(proj.get("settings"))
    ed = edits.build_edit(proj)
    media = proj["media"]
    keeps = edits.snap_keeps(ed["keeps"], media["fps"]) if media.get("has_video") else ed["keeps"]
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

"""Transcrição com marcação de tempo por palavra: local (faster-whisper) ou API compatível com OpenAI (Groq, OpenAI...)."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from . import ffmpeg_tools as ff

# Um "prompt" com vícios de linguagem faz o Whisper transcrevê-los em vez de escondê-los.
FILLER_PROMPT = {
    "pt": "Hum, é... então, tipo, né? Ahn, bom, aí... é, hã.",
    "en": "Um, uh... so, like, you know? Hmm, well, uh.",
    "es": "Eh, este... o sea, pues, ¿no? Mmm, bueno.",
}

_MODEL_CACHE: dict = {}


def _add_cuda_dll_dirs() -> None:
    """No Windows, as bibliotecas da NVIDIA instaladas via pip ficam em site-packages/nvidia/*/bin."""
    if os.name != "nt":
        return
    import site
    for sp in site.getsitepackages() + [site.getusersitepackages()]:
        base = Path(sp) / "nvidia"
        if base.exists():
            for b in base.glob("*/bin"):
                try:
                    os.add_dll_directory(str(b))
                    os.environ["PATH"] = str(b) + os.pathsep + os.environ.get("PATH", "")
                except OSError:
                    pass


_add_cuda_dll_dirs()


def _cuda_available() -> bool:
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def local_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def transcribe_local(wav: str, cfg: dict, models_dir: str,
                     progress: Optional[Callable[[float, str], None]] = None, duration: float = 0) -> dict:
    want_gpu = (cfg.get("device") or "auto") in ("auto", "cuda") and _cuda_available()
    try:
        return _transcribe_local(wav, cfg, models_dir, progress, duration)
    except Exception:
        if not want_gpu:
            raise
        _MODEL_CACHE.clear()
        if progress:
            progress(0.0, "Falha na GPU, refazendo a transcrição pelo processador…")
        return _transcribe_local(wav, {**cfg, "device": "cpu"}, models_dir, progress, duration)


def _transcribe_local(wav: str, cfg: dict, models_dir: str,
                      progress: Optional[Callable[[float, str], None]] = None, duration: float = 0) -> dict:
    from faster_whisper import WhisperModel

    size = cfg.get("local_model") or "small"
    device = cfg.get("device") or "auto"
    if device == "auto":
        device = "cuda" if _cuda_available() else "cpu"
    compute = "float16" if device == "cuda" else "int8"
    key = (size, device)
    if key not in _MODEL_CACHE:
        if progress:
            progress(0.0, f"Carregando modelo de transcrição ({size}, {'GPU' if device == 'cuda' else 'CPU'})…")
        _MODEL_CACHE.clear()
        threads = max(1, (os.cpu_count() or 4) - 1)
        try:
            _MODEL_CACHE[key] = WhisperModel(size, device=device, compute_type=compute,
                                             download_root=models_dir, cpu_threads=threads)
        except Exception:
            if device != "cuda":
                raise
            # GPU sem as bibliotecas CUDA: segue no processador em vez de falhar
            if progress:
                progress(0.0, "GPU indisponível para transcrição, usando o processador…")
            device, compute, key = "cpu", "int8", (size, "cpu")
            _MODEL_CACHE[key] = WhisperModel(size, device="cpu", compute_type="int8",
                                             download_root=models_dir, cpu_threads=threads)
    model = _MODEL_CACHE[key]
    lang = cfg.get("language") or "pt"
    segments, info = model.transcribe(
        wav,
        language=None if lang == "auto" else lang,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300, "speech_pad_ms": 200},
        initial_prompt=FILLER_PROMPT.get(lang, None),
        condition_on_previous_text=False,
        beam_size=5,
    )
    words, segs = [], []
    for seg in segments:
        segs.append({"s": round(seg.start, 3), "e": round(seg.end, 3), "text": seg.text.strip()})
        for w in seg.words or []:
            words.append({"w": w.word.strip(), "s": round(w.start, 3), "e": round(w.end, 3),
                          "p": round(w.probability or 0, 3)})
        if progress and duration:
            progress(min(0.99, seg.end / duration), "Transcrevendo…")
    return {"words": words, "segments": segs, "language": getattr(info, "language", lang)}


def _split_points(db: np.ndarray, duration: float, chunk_s: float) -> list[float]:
    """Escolhe pontos de divisão em silêncios, para não cortar palavras ao meio."""
    pts = [0.0]
    t = chunk_s
    while t < duration - 30:
        a, b = int((t - 20) / 0.01), int((t + 20) / 0.01)
        a, b = max(0, a), min(len(db), b)
        if b > a:
            i = a + int(np.argmin(db[a:b]))
            t_cut = i * 0.01
        else:
            t_cut = t
        pts.append(t_cut)
        t = t_cut + chunk_s
    pts.append(duration)
    return pts


def transcribe_api(wav: str, cfg: dict, db: np.ndarray, duration: float,
                   progress: Optional[Callable[[float, str], None]] = None) -> dict:
    import httpx

    base = (cfg.get("api_base") or "https://api.groq.com/openai/v1").rstrip("/")
    key = cfg.get("api_key") or ""
    model = cfg.get("api_model") or "whisper-large-v3-turbo"
    lang = cfg.get("language") or "pt"
    if not key:
        raise RuntimeError("Chave da API de transcrição não configurada (Configurações).")
    points = _split_points(db, duration, 20 * 60)
    words, segs = [], []
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(len(points) - 1):
            s, e = points[i], points[i + 1]
            part = str(Path(tmp) / f"parte{i}.ogg")
            ff.run([ff.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{s:.3f}", "-to", f"{e:.3f}",
                    "-i", wav, "-ac", "1", "-ar", "16000", "-c:a", "libopus", "-b:a", "32k", part])
            if progress:
                progress(i / (len(points) - 1), f"Enviando parte {i + 1} de {len(points) - 1} para a API…")
            data = {"model": model, "response_format": "verbose_json",
                    "timestamp_granularities[]": ["word", "segment"]}
            if lang != "auto":
                data["language"] = lang
            if FILLER_PROMPT.get(lang):
                data["prompt"] = FILLER_PROMPT[lang]
            with open(part, "rb") as fh:
                r = httpx.post(f"{base}/audio/transcriptions", headers={"Authorization": f"Bearer {key}"},
                               data=data, files={"file": (f"parte{i}.ogg", fh, "audio/ogg")}, timeout=600)
            if r.status_code != 200:
                raise RuntimeError(f"API de transcrição respondeu {r.status_code}: {r.text[:300]}")
            js = r.json()
            for w in js.get("words") or []:
                words.append({"w": str(w.get("word", "")).strip(), "s": round(w["start"] + s, 3),
                              "e": round(w["end"] + s, 3), "p": 1.0})
            for sg in js.get("segments") or []:
                segs.append({"s": round(sg["start"] + s, 3), "e": round(sg["end"] + s, 3),
                             "text": str(sg.get("text", "")).strip()})
    return {"words": words, "segments": segs, "language": lang}


def transcribe(wav: str, cfg: dict, models_dir: str, db: np.ndarray, duration: float,
               progress: Optional[Callable[[float, str], None]] = None) -> dict:
    provider = cfg.get("provider") or "local"
    if provider == "none":
        return {"words": [], "segments": [], "language": cfg.get("language", "pt")}
    if provider == "api":
        return transcribe_api(wav, cfg, db, duration, progress)
    if not local_available():
        raise RuntimeError("Transcrição local indisponível (faster-whisper não instalado). "
                           "Rode o instalador novamente ou configure uma API.")
    return transcribe_local(wav, cfg, models_dir, progress, duration)

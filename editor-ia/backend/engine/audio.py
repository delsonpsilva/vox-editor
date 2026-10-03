"""Análise de áudio: extração, medição de energia/espectro, detecção de silêncios e respirações."""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from . import ffmpeg_tools as ff

SR = 16000          # taxa usada para análise e transcrição
HOP = 160           # 10 ms por quadro
WIN = 400           # janela de 25 ms
FRAME_S = HOP / SR  # duração de um quadro em segundos


def extract_analysis_audio(src: str, out: str) -> None:
    ff.run([ff.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", src, "-vn", "-ac", "1",
            "-ar", str(SR), "-c:a", "pcm_s16le", out])


def extract_render_audio(src: str, out: str, sr: int = 48000) -> None:
    ff.run([ff.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", src, "-vn", "-ac", "2",
            "-ar", str(sr), "-c:a", "pcm_s16le", out])


def read_wav_mono(path: str) -> np.ndarray:
    with wave.open(path, "rb") as w:
        n = w.getnframes()
        data = np.frombuffer(w.readframes(n), dtype=np.int16)
        ch = w.getnchannels()
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    return data.astype(np.float32) / 32768.0


def compute_features(samples: np.ndarray) -> dict:
    """Retorna, a cada 10 ms: volume (dBFS), planicidade espectral e centroide espectral."""
    n_frames = max(1, 1 + (len(samples) - WIN) // HOP) if len(samples) >= WIN else 1
    if len(samples) < WIN:
        samples = np.pad(samples, (0, WIN - len(samples)))
    db = np.empty(n_frames, dtype=np.float32)
    flat = np.empty(n_frames, dtype=np.float32)
    cent = np.empty(n_frames, dtype=np.float32)
    window = np.hanning(WIN).astype(np.float32)
    freqs = np.fft.rfftfreq(512, 1 / SR).astype(np.float32)
    chunk = 20000
    for start in range(0, n_frames, chunk):
        end = min(n_frames, start + chunk)
        idx = (np.arange(start, end)[:, None] * HOP) + np.arange(WIN)[None, :]
        frames = samples[idx]
        rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-12)
        db[start:end] = 20 * np.log10(rms + 1e-9)
        spec = np.abs(np.fft.rfft(frames * window, n=512, axis=1)) ** 2 + 1e-12
        band = spec[:, 32:176]  # 1–5,5 kHz: onde a respiração é ruído "plano" e a voz tem harmônicos
        flat[start:end] = np.exp(np.mean(np.log(band), axis=1)) / np.mean(band, axis=1)
        cent[start:end] = (spec * freqs).sum(axis=1) / spec.sum(axis=1)
    return {"db": db, "flat": flat, "cent": cent}


def waveform(samples: np.ndarray, bins: int = 3000) -> list[float]:
    if len(samples) == 0:
        return []
    bins = min(bins, max(1, len(samples) // 64))
    usable = len(samples) - (len(samples) % bins)
    peaks = np.abs(samples[:usable]).reshape(bins, -1).max(axis=1)
    top = np.percentile(peaks, 99.5) or 1.0
    return [round(float(x), 3) for x in np.clip(np.sqrt(peaks / top), 0, 1)]


def levels(db: np.ndarray) -> dict:
    floor = float(np.percentile(db, 5))
    loud = db[db > floor + 12]
    speech = float(np.percentile(loud, 70)) if loud.size > 50 else float(np.percentile(db, 90))
    auto_thr = floor + 0.38 * (speech - floor)
    auto_thr = float(np.clip(auto_thr, -60, speech - 6))
    return {"floor": round(floor, 1), "speech": round(speech, 1), "auto_threshold": round(auto_thr, 1)}


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Sequências contínuas de True como (início, fim) em quadros."""
    if mask.size == 0:
        return []
    m = np.concatenate([[False], mask, [False]]).astype(np.int8)
    d = np.diff(m)
    starts = np.where(d == 1)[0]
    ends = np.where(d == -1)[0]
    return list(zip(starts.tolist(), ends.tolist()))


def detect_silences(db: np.ndarray, threshold_db: float, min_dur: float, pad: float,
                    duration: float) -> list[list[float]]:
    quiet = db < threshold_db
    # Estalos curtos (< 60 ms) dentro de um silêncio não quebram o silêncio
    for s, e in _runs(~quiet):
        if (e - s) * FRAME_S < 0.06:
            quiet[s:e] = True
    out = []
    for s, e in _runs(quiet):
        t0, t1 = s * FRAME_S, e * FRAME_S
        if t1 - t0 < min_dur:
            continue
        # Margem: mantém um pouco do silêncio para a fala respirar e não "comer" consoantes
        c0 = t0 + (0 if s == 0 else pad)
        c1 = t1 - (0 if e >= len(db) else pad)
        c1 = min(c1, duration)
        if c1 - c0 >= 0.05:
            out.append([round(c0, 3), round(c1, 3)])
    return out


def detect_breaths(feat: dict, lv: dict, threshold_db: float, words: list[dict]) -> list[list[float]]:
    """Respiração: som de baixo volume, ruidoso (espectro plano) e curto, fora das palavras."""
    db, flat, cent = feat["db"], feat["flat"], feat["cent"]
    speech = lv["speech"]
    mask = (db > threshold_db - 6) & (db < speech - 9) & (flat > 0.16) & (cent > 900)
    # Fecha buracos de até 40 ms
    for s, e in _runs(~mask):
        if (e - s) * FRAME_S <= 0.04 and s > 0 and e < len(mask):
            mask[s:e] = True
    cores = [(w["s"] + 0.03, w["e"] - 0.03) for w in words if w["e"] - w["s"] > 0.08]
    starts = np.array([c[0] for c in cores]) if cores else np.array([])
    out = []
    for s, e in _runs(mask):
        t0, t1 = s * FRAME_S, e * FRAME_S
        dur = t1 - t0
        if dur < 0.12 or dur > 1.1:
            continue
        if cores:
            i = int(np.searchsorted(starts, t1))
            overlap = 0.0
            for j in range(max(0, i - 3), min(len(cores), i + 2)):
                a, b = cores[j]
                overlap += max(0.0, min(b, t1) - max(a, t0))
            if overlap > 0.3 * dur:
                continue
        out.append([round(max(0, t0 - 0.02), 3), round(t1 + 0.02, 3)])
    return out


def save_features(feat: dict, folder: Path) -> None:
    np.savez_compressed(folder / "features.npz", **feat)


def load_features(folder: Path) -> dict:
    data = np.load(folder / "features.npz")
    return {k: data[k] for k in data.files}

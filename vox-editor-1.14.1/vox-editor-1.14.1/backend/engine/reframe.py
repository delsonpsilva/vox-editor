"""Enquadramento inteligente para 9:16: encontra o rosto de quem fala em cada trecho e centraliza o corte nele."""
from __future__ import annotations

import subprocess
from statistics import median

import numpy as np

from . import ffmpeg_tools as ff

_CASCADES = None
SAMPLE_W = 480


def available() -> bool:
    try:
        import cv2  # noqa: F401
        return True
    except Exception:
        return False


def _cascades():
    global _CASCADES
    if _CASCADES is None:
        import cv2
        base = cv2.data.haarcascades
        _CASCADES = [cv2.CascadeClassifier(base + "haarcascade_frontalface_default.xml"),
                     cv2.CascadeClassifier(base + "haarcascade_profileface.xml")]
    return _CASCADES


def _grab(src: str, t: float, w: int, h: int) -> np.ndarray | None:
    """Pega um quadro (o quadro-chave mais próximo, bem rápido) em escala reduzida e cinza."""
    sh = int(round(h * SAMPLE_W / max(w, 1) / 2) * 2)
    p = subprocess.run([ff.ffmpeg(), "-hide_banner", "-loglevel", "error", "-skip_frame", "nokey", "-ss", f"{max(0, t):.2f}",
                        "-i", src, "-frames:v", "1", "-vf", f"scale={SAMPLE_W}:{sh}", "-pix_fmt", "gray",
                        "-f", "rawvideo", "-"], capture_output=True, creationflags=ff.CREATE_FLAGS)
    if p.returncode != 0 or len(p.stdout) < SAMPLE_W * sh:
        return None
    return np.frombuffer(p.stdout[: SAMPLE_W * sh], dtype=np.uint8).reshape(sh, SAMPLE_W)


def faces_at(src: str, t: float, w: int, h: int) -> list[tuple[float, float, float]]:
    """Rostos nítidos no quadro: lista de (centro_x 0..1, área relativa, nitidez)."""
    img = _grab(src, t, w, h)
    if img is None:
        return []
    import cv2
    out = []
    min_side = max(24, img.shape[0] // 12)
    for i, casc in enumerate(_cascades()):
        for flip in ((False, True) if i == 1 else (False,)):
            im = np.ascontiguousarray(img[:, ::-1]) if flip else img
            faces = casc.detectMultiScale(im, scaleFactor=1.15, minNeighbors=6, minSize=(min_side, min_side))
            for (x, y, fw, fh) in faces:
                roi = im[y:y + fh, x:x + fw]
                sharp = float(cv2.Laplacian(roi, cv2.CV_64F).var()) if roi.size else 0.0
                cx = x + fw / 2
                if flip:
                    cx = im.shape[1] - cx
                out.append((cx / im.shape[1], fw * fh / (im.shape[0] * im.shape[1]), sharp))
        if out:
            break
    # descarta rostos borrados (reflexos, fundo desfocado, fotos fora de foco)
    if out:
        best = max(f[2] for f in out)
        out = [f for f in out if f[2] >= best * 0.35 and f[2] > 8]
    return out


def face_x(src: str, t: float, w: int, h: int) -> float | None:
    faces = faces_at(src, t, w, h)
    if not faces:
        return None
    return max(faces, key=lambda f: f[1] * min(f[2], 400))[0]


def centers_for(src: str, segments: list[list[float]], media: dict, cache: dict) -> list[float]:
    """Centro horizontal (0..1) para cada trecho, seguindo o ORADOR PRINCIPAL (o rosto mais constante)."""
    w, h = media.get("width") or 1920, media.get("height") or 1080
    if not available() or w <= h:
        return [0.5] * len(segments)
    samples: dict[str, list[list[tuple]]] = {}
    for s, e in segments:
        key = f"{s:.2f}-{e:.2f}"
        if key in cache and isinstance(cache[key], dict):
            continue
        n = 3 if e - s > 4 else 2
        found = [faces_at(src, s + (e - s) * (k + 0.5) / n, w, h) for k in range(n)]
        samples[key] = found
        cache[key] = {"faces": [[list(f) for f in fs] for fs in found]}
    # orador principal = posição mais frequente entre os rostos grandes e nítidos de todos os trechos
    allx = []
    for s, e in segments:
        for fs in cache[f"{s:.2f}-{e:.2f}"]["faces"]:
            if fs:
                allx.append(max(fs, key=lambda f: f[1] * min(f[2], 400))[0])
    main = float(np.median(allx)) if allx else 0.5
    out = []
    for s, e in segments:
        xs = []
        for fs in cache[f"{s:.2f}-{e:.2f}"]["faces"]:
            if fs:
                xs.append(min(fs, key=lambda f: abs(f[0] - main))[0])  # o rosto mais perto do orador principal
        out.append(round(float(median(xs)), 3) if xs else main)
    return out


def smooth(xs: list[float], tol: float = 0.06) -> list[float]:
    """Evita "pulos" pequenos de enquadramento entre trechos vizinhos."""
    out = []
    for x in xs:
        if out and abs(out[-1] - x) < tol:
            out.append(out[-1])
        else:
            out.append(x)
    return out

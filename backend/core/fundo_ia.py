"""Remoção de fundo com IA (pessoas e objetos), sem fundo verde e sem pagar API.

Roda no próprio computador/servidor com o ONNX Runtime e os modelos U²-Net (os mesmos do projeto "rembg",
licença Apache 2.0). Na primeira vez o modelo é baixado sozinho para a pasta dados/modelos/fundo.
  - rápida:     u2netp (4,5 MB) — bom para testar e para PC fraco
  - caprichada: u2net_human_seg (168 MB) — feito para pessoas, contorno bem melhor (padrão)

Foto vira PNG transparente. Vídeo vira WebM (VP9) com transparência, que o navegador mostra na prévia e o FFmpeg
lê na exportação. Só o trecho usado na linha do tempo é processado (mais rápido)."""
from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import httpx

from . import store
from ..engine import ffmpeg_tools as ff

MODELOS = {
    "rapida": ("u2netp.onnx", "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx", 4_574_861),
    "caprichada": ("u2net_human_seg.onnx",
                   "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net_human_seg.onnx", 175_997_641),
}
MAX_SEG = 600          # até 10 minutos de vídeo por vez
LADO_MAX = 1280        # o vídeo sem fundo sai com no máximo 1280 px no lado maior (prévia e exportação rápidas)
_sessoes: dict[str, object] = {}
_lock = threading.Lock()


def disponivel() -> bool:
    try:
        import onnxruntime  # noqa: F401
        return True
    except Exception:
        return False


def qualidade() -> str:
    q = (store.load_config().get("fundo") or {}).get("qualidade", "caprichada")
    return q if q in MODELOS else "caprichada"


def _pasta() -> Path:
    d = store.MODELS / "fundo"
    d.mkdir(parents=True, exist_ok=True)
    return d


def modelo_baixado(q: str) -> bool:
    nome, _, tam = MODELOS[q]
    f = _pasta() / nome
    return f.exists() and f.stat().st_size == tam


def baixar_modelo(q: str, progress: Optional[Callable[[float, str], None]] = None) -> Path:
    nome, url, tam = MODELOS[q]
    f = _pasta() / nome
    if f.exists() and f.stat().st_size == tam:
        return f
    tmp = f.with_suffix(".baixando")
    feito = 0
    try:
        with httpx.stream("GET", url, timeout=httpx.Timeout(30.0, read=180.0), follow_redirects=True) as r:
            if r.status_code != 200:
                raise RuntimeError(f"Não consegui baixar o modelo de IA (erro {r.status_code}).")
            with open(tmp, "wb") as fh:
                for b in r.iter_bytes(1024 * 1024):
                    feito += len(b)
                    fh.write(b)
                    if progress:
                        progress(min(0.99, feito / tam), f"Baixando o modelo de IA (só na primeira vez)… "
                                                         f"{feito / 1e6:.0f} de {tam / 1e6:.0f} MB")
        if feito != tam:
            raise RuntimeError("O download do modelo veio incompleto. Tente de novo.")
        os.replace(tmp, f)
    except httpx.HTTPError:
        raise RuntimeError("A internet caiu ao baixar o modelo de IA. Tente de novo.")
    finally:
        tmp.unlink(missing_ok=True)
    return f


def _sessao(q: str):
    with _lock:
        if q not in _sessoes:
            import onnxruntime as ort
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = max(1, min(8, ff.cpu_threads()))
            provs = [p for p in ("CUDAExecutionProvider", "DmlExecutionProvider", "CPUExecutionProvider")
                     if p in ort.get_available_providers()]
            _sessoes[q] = ort.InferenceSession(str(_pasta() / MODELOS[q][0]), opts, providers=provs)
        return _sessoes[q]


def mascara(sess, rgb) -> "object":
    """Máscara (0 a 1, float32) do primeiro plano de uma imagem RGB uint8 (mesmo pré-processamento do rembg)."""
    import cv2
    import numpy as np
    h, w = rgb.shape[:2]
    x = cv2.resize(rgb, (320, 320), interpolation=cv2.INTER_AREA).astype("float32")
    x /= max(1.0, float(x.max()))
    x = (x - np.array([0.485, 0.456, 0.406], "float32")) / np.array([0.229, 0.224, 0.225], "float32")
    x = x.transpose(2, 0, 1)[None]
    nome = sess.get_inputs()[0].name
    out = sess.run(None, {nome: x})[0][0, 0]
    lo, hi = float(out.min()), float(out.max())
    m = (out - lo) / (hi - lo) if hi - lo > 1e-6 else np.zeros_like(out)
    return cv2.resize(m.astype("float32"), (w, h), interpolation=cv2.INTER_LINEAR)


def _acabamento(m):
    """Contorno mais firme: tira a névoa do fundo e deixa a borda suave (sem serrilhado)."""
    import numpy as np
    return np.clip((m - 0.12) / 0.76, 0, 1)


def foto(origem: Path, destino: Path, progress: Optional[Callable[[float, str], None]] = None) -> Path:
    import cv2
    import numpy as np
    q = qualidade()
    baixar_modelo(q, progress)
    if progress:
        progress(0.5, "Tirando o fundo da foto…")
    img = cv2.imread(str(origem), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError("Não consegui abrir essa imagem.")
    m = _acabamento(mascara(_sessao(q), cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))
    rgba = np.dstack([img, (m * 255 + 0.5).astype("uint8")])
    cv2.imwrite(str(destino), rgba)
    return destino


def video(origem: Path, inicio: float, dur: float, destino: Path, info: dict,
          progress: Optional[Callable[[float, str], None]] = None) -> Path:
    """Processa o trecho [inicio, inicio+dur] do vídeo e grava um WebM com transparência (com o som do trecho)."""
    import numpy as np
    q = qualidade()
    baixar_modelo(q, progress)
    dur = min(dur, MAX_SEG)
    sw, sh = int(info.get("width") or 0), int(info.get("height") or 0)
    if not sw or not sh:
        raise RuntimeError("Esse vídeo não tem imagem.")
    k = min(1.0, LADO_MAX / max(sw, sh))
    w, h = max(2, int(sw * k) // 2 * 2), max(2, int(sh * k) // 2 * 2)
    fps = float(info.get("fps") or 30) or 30
    fps = 60 if fps > 45 else (25 if abs(fps - 25) < 0.5 else 30)
    total_q = max(1, int(dur * fps))
    passo = max(1, round(fps / 15))
    sess = _sessao(q)
    ler = subprocess.Popen([ff.ffmpeg(), "-hide_banner", "-loglevel", "error", "-ss", f"{inicio:.3f}", "-t",
                            f"{dur:.3f}", "-i", str(origem), "-an", "-vf", f"fps={fps},scale={w}:{h}:flags=bicubic",
                            "-pix_fmt", "rgb24", "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
    tmp = destino.with_suffix(".tmp.webm")
    escrever = subprocess.Popen(
        [ff.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s",
         f"{w}x{h}", "-r", str(fps), "-i", "-", "-ss", f"{inicio:.3f}", "-t", f"{dur:.3f}", "-i", str(origem),
         "-map", "0:v", "-map", "1:a?", "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "32",
         "-deadline", "realtime", "-cpu-used", "8", "-row-mt", "1", "-auto-alt-ref", "0", "-c:a", "libopus",
         "-b:a", "128k", "-shortest", str(tmp)], stdin=subprocess.PIPE)
    tamq = w * h * 3
    anterior = None
    n = 0
    t0 = time.time()
    try:
        while True:
            buf = ler.stdout.read(tamq)
            if not buf or len(buf) < tamq:
                break
            rgb = np.frombuffer(buf, "uint8").reshape(h, w, 3)
            if anterior is None or n % passo == 0:  # a IA olha até 15 quadros por segundo (metade do trabalho)
                m = mascara(sess, rgb)
                if anterior is not None:  # suaviza entre quadros: o contorno não fica "tremendo"
                    m = 0.7 * m + 0.3 * anterior
                anterior = m
            m = anterior
            a = (_acabamento(m) * 255 + 0.5).astype("uint8")
            escrever.stdin.write(np.dstack([rgb, a]).tobytes())
            n += 1
            if progress and n % 5 == 0:
                gasto = time.time() - t0
                falta = gasto / n * max(0, total_q - n)
                progress(min(0.99, n / total_q),
                         f"Tirando o fundo… {n} de {total_q} quadros (falta ~{int(falta // 60)}min{int(falta % 60):02d}s)")
        escrever.stdin.close()
        if escrever.wait() != 0:
            raise RuntimeError("Não consegui gravar o vídeo sem fundo.")
    finally:
        try:
            ler.kill()
        except Exception:
            pass
        if escrever.poll() is None:
            escrever.kill()
    if n == 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("Não consegui ler os quadros desse trecho do vídeo.")
    os.replace(tmp, destino)
    return destino

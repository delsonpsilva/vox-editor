"""Utilitários de FFmpeg: localização, sondagem de mídia, codificadores e execução com progresso."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from fractions import Fraction
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parents[2]
IS_WIN = os.name == "nt"
EXE = ".exe" if IS_WIN else ""

# No Windows, evita abrir uma janela de terminal para cada processo do FFmpeg
CREATE_FLAGS = 0x08000000 if IS_WIN else 0


def _find(name: str) -> str:
    env = os.environ.get(name.upper() + "_PATH")
    if env and Path(env).exists():
        return env
    for cand in (ROOT / "ffmpeg" / "bin" / (name + EXE), ROOT / "ffmpeg" / (name + EXE)):
        if cand.exists():
            return str(cand)
    found = shutil.which(name)
    if found:
        return found
    raise RuntimeError(f"{name} não encontrado. Rode o instalador ou coloque o FFmpeg na pasta 'ffmpeg'.")


@lru_cache
def ffmpeg() -> str:
    return _find("ffmpeg")


@lru_cache
def ffprobe() -> str:
    return _find("ffprobe")


def run(args: list[str], cwd: Optional[str] = None, check: bool = True) -> subprocess.CompletedProcess:
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", creationflags=CREATE_FLAGS)
    if check and p.returncode != 0:
        tail = "\n".join(p.stderr.strip().splitlines()[-15:])
        raise RuntimeError(f"Falha no FFmpeg:\n{tail}")
    return p


def run_with_progress(args: list[str], total_seconds: float,
                      on_progress: Optional[Callable[[float], None]] = None,
                      cwd: Optional[str] = None) -> None:
    """Executa o FFmpeg lendo -progress para informar porcentagem (0..1)."""
    full = [args[0], "-hide_banner", "-nostats", "-progress", "pipe:1"] + args[1:]
    proc = subprocess.Popen(full, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace", creationflags=CREATE_FLAGS)
    err_lines: list[str] = []

    import threading

    def _drain():
        for line in proc.stderr:  # type: ignore[union-attr]
            err_lines.append(line)
            if len(err_lines) > 200:
                del err_lines[:100]

    t = threading.Thread(target=_drain, daemon=True)
    t.start()
    for line in proc.stdout:  # type: ignore[union-attr]
        if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
            try:
                us = int(line.split("=", 1)[1])
                if on_progress and total_seconds > 0:
                    on_progress(min(1.0, us / 1e6 / total_seconds))
            except ValueError:
                pass
    proc.wait()
    t.join(timeout=2)
    if proc.returncode != 0:
        tail = "".join(err_lines[-15:])
        raise RuntimeError(f"Falha no FFmpeg:\n{tail}")


def probe(path: str) -> dict:
    p = run([ffprobe(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path])
    data = json.loads(p.stdout or "{}")
    fmt = data.get("format", {})
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"
              and s.get("disposition", {}).get("attached_pic", 0) == 0), None)
    a = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    duration = float(fmt.get("duration") or (v or a or {}).get("duration") or 0)
    info = {
        "duration": duration,
        "format": fmt.get("format_name", ""),
        "has_video": v is not None,
        "has_audio": a is not None,
        "width": int(v["width"]) if v else 0,
        "height": int(v["height"]) if v else 0,
        "vcodec": v.get("codec_name") if v else None,
        "acodec": a.get("codec_name") if a else None,
        "fps": 30.0,
        "fps_str": "30",
        "rotation": 0,
    }
    if v:
        rate = v.get("avg_frame_rate") or v.get("r_frame_rate") or "30/1"
        try:
            fr = Fraction(rate)
            if fr <= 0 or fr > 240:
                fr = Fraction(v.get("r_frame_rate", "30/1"))
        except (ZeroDivisionError, ValueError):
            fr = Fraction(30, 1)
        fr = _normalize_rate(fr)
        info["fps"] = float(fr)
        info["fps_str"] = f"{fr.numerator}/{fr.denominator}"
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                info["rotation"] = int(sd["rotation"])
        rot = (v.get("tags") or {}).get("rotate")
        if rot:
            info["rotation"] = int(rot)
        if abs(info["rotation"]) in (90, 270):
            info["width"], info["height"] = info["height"], info["width"]
    return info


def _normalize_rate(fr: Fraction) -> Fraction:
    """Aproxima taxas variáveis para as taxas padrão (23.976, 25, 29.97, 30, 50, 59.94, 60)."""
    std = [Fraction(24000, 1001), Fraction(24), Fraction(25), Fraction(30000, 1001), Fraction(30),
           Fraction(50), Fraction(60000, 1001), Fraction(60)]
    best = min(std, key=lambda s: abs(float(s) - float(fr)))
    if abs(float(best) - float(fr)) < 0.6:
        return best
    return Fraction(round(float(fr))) if fr > 1 else Fraction(30)


@lru_cache
def ffmpeg_version() -> tuple[int, int]:
    out = run([ffmpeg(), "-version"], check=False).stdout
    m = re.search(r"ffmpeg version n?(\d+)\.(\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else (6, 0)


@lru_cache
def available_encoders() -> dict:
    """Testa de verdade cada codificador de hardware (listar não garante que a GPU exista)."""
    result = {"libx264": True}
    listed = run([ffmpeg(), "-hide_banner", "-encoders"], check=False).stdout
    for enc in ("h264_nvenc", "h264_qsv", "h264_amf", "h264_videotoolbox"):
        if enc not in listed:
            result[enc] = False
            continue
        test = run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    "color=black:s=256x256:d=0.2", "-frames:v", "3", "-c:v", enc, "-f", "null", "-"],
                   check=False)
        result[enc] = test.returncode == 0
    return result


def best_encoder(preference: str = "auto") -> str:
    enc = available_encoders()
    if preference != "auto" and enc.get(preference):
        return preference
    for e in ("h264_nvenc", "h264_qsv", "h264_amf", "h264_videotoolbox"):
        if enc.get(e):
            return e
    return "libx264"


def encoder_args(encoder: str, quality: str = "alta") -> list[str]:
    """Parâmetros de codificação equilibrando qualidade e velocidade."""
    q = {"maxima": 0, "alta": 1, "rapida": 2}.get(quality, 1)
    if encoder == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", ["p6", "p5", "p3"][q], "-tune", "hq",
                "-rc", "vbr", "-cq", ["18", "21", "25"][q], "-b:v", "0", "-pix_fmt", "yuv420p"]
    if encoder == "h264_qsv":
        return ["-c:v", "h264_qsv", "-preset", ["slower", "medium", "faster"][q],
                "-global_quality", ["18", "22", "26"][q], "-pix_fmt", "nv12"]
    if encoder == "h264_amf":
        return ["-c:v", "h264_amf", "-quality", ["quality", "balanced", "speed"][q],
                "-rc", "cqp", "-qp_i", ["18", "21", "25"][q], "-qp_p", ["20", "23", "27"][q], "-pix_fmt", "yuv420p"]
    if encoder == "h264_videotoolbox":
        return ["-c:v", "h264_videotoolbox", "-q:v", ["75", "65", "50"][q], "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", ["slow", "veryfast", "ultrafast"][q],
            "-crf", ["17", "20", "24"][q], "-pix_fmt", "yuv420p"]


def browser_friendly(info: dict, path: str) -> bool:
    ext = Path(path).suffix.lower()
    return (ext in (".mp4", ".m4v", ".mov", ".webm") and info.get("vcodec") in ("h264", "vp8", "vp9", "av1")
            and info.get("acodec") in (None, "aac", "mp3", "opus", "vorbis") and info.get("height", 0) <= 1440)


def filter_script_args(graph: str, script_path: str) -> list[str]:
    """Passa grafos de filtro longos por arquivo (limite de linha de comando do Windows)."""
    if len(graph) < 12000:
        return ["-filter_complex", graph]
    Path(script_path).write_text(graph, encoding="utf-8")
    if ffmpeg_version() >= (7, 1):
        return ["-/filter_complex", script_path]
    return ["-filter_complex_script", script_path]


def python_info() -> str:
    return sys.version.split()[0]

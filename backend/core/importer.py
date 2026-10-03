"""Traz o vídeo para dentro do projeto sem precisar salvar no PC antes:
- por link (YouTube e outros sites que o yt-dlp aceita), baixado pelo próprio programa, sem API e sem custo;
- por caminho de arquivo (só no programa do PC): liga ou copia o arquivo direto, sem passar pelo envio do navegador.

O yt-dlp roda como processo separado para que uma atualização dele valha na hora, sem reiniciar o programa."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from ..engine import ffmpeg_tools as ff
from . import store

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mxf", ".mts", ".m2ts", ".wmv", ".flv",
             ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}

_updated_once = False


def clean_url(url: str) -> str:
    url = (url or "").strip()
    if not re.match(r"^https?://[^\s/$.?#].[^\s]*$", url, re.I):
        raise ValueError("Cole um link completo, começando com https://")
    return url


def friendly(err: str) -> str:
    low = err.lower()
    if "sign in to confirm" in low or "not a bot" in low:
        return ("O YouTube pediu verificação de robô. Isso é comum em servidores (VPS). "
                "Baixe pelo programa no PC ou tente mais tarde.")
    if "private video" in low:
        return "Esse vídeo é privado. Deixe como Não listado ou Público para importar."
    if "members-only" in low or "join this channel" in low:
        return "Esse vídeo é só para membros do canal."
    if "live event will begin" in low or "is_upcoming" in low or "premieres in" in low:
        return "A transmissão ainda não começou."
    if "is not a valid url" in low or "unsupported url" in low:
        return "Esse link não é de um vídeo que o programa consiga baixar."
    if "video unavailable" in low or "has been removed" in low:
        return "Vídeo indisponível (removido, bloqueado no país ou com restrição)."
    if "max-filesize" in low or "larger than max-filesize" in low:
        return "O vídeo é maior que o limite de tamanho configurado."
    if "http error 404" in low or "not found" in low:
        return "Link não encontrado (o endereço está errado ou o vídeo foi apagado)."
    if "unable to download" in low or "timed out" in low or "getaddrinfo" in low or "connection" in low:
        return "Não consegui conectar ao site do vídeo. Verifique a internet e tente de novo."
    tail = [ln for ln in err.strip().splitlines() if ln.strip()][-1:] or ["erro desconhecido"]
    return "Não consegui baixar o vídeo: " + tail[0][:300]


def _needs_update(err: str) -> bool:
    low = err.lower()
    if "unable to connect" in low or "proxy" in low or "getaddrinfo" in low or "timed out" in low:
        return False
    return any(k in low for k in ("http error 403", "unable to extract", "requested format is not available",
                                  "nsig", "signature", "please report this issue", "no video formats found"))


def _self_update(progress) -> bool:
    """Os sites mudam com frequência; quando o baixador falha desse jeito, atualiza ele uma vez e tenta de novo."""
    global _updated_once
    if _updated_once:
        return False
    _updated_once = True
    progress(0.02, "Atualizando o baixador de vídeos…")
    p = subprocess.run([sys.executable, "-m", "pip", "install", "-U", "--quiet", "yt-dlp"],
                       capture_output=True, text=True, creationflags=ff.CREATE_FLAGS)
    return p.returncode == 0


def _cmd(url: str, folder: Path, max_gb: float) -> list[str]:
    cmd = [sys.executable, "-m", "yt_dlp", url,
           "--no-playlist", "--no-simulate", "--newline", "--progress", "--no-colors", "--no-mtime",
           "-f", "bv*[height<=1080][vcodec!*=av01]+ba/b[height<=1080]/bv*+ba/b",
           "-S", "res:1080,vcodec:h264,acodec:m4a",
           "--merge-output-format", "mp4",
           "-o", str(folder / "original.%(ext)s"),
           "--progress-template", "download:[[P]] %(progress.status)s %(progress.downloaded_bytes)s "
                                  "%(progress.total_bytes)s %(progress.total_bytes_estimate)s %(progress.speed)s",
           "--print", "before_dl:[[T]] %(title)s",
           "--print", "before_dl:[[N]] %(requested_formats.1.format_id|NA)s",
           "--print", "after_move:[[F]] %(filepath)s",
           "--max-filesize", f"{int(max_gb * 1024)}M"]
    try:
        cmd += ["--ffmpeg-location", str(Path(ff.ffmpeg()).parent)]
    except RuntimeError:
        pass
    js = _deno()
    if js:  # o YouTube exige um motor de JavaScript para liberar os formatos de vídeo
        cmd += ["--js-runtimes", f"deno:{js}"]
    return cmd


def _deno() -> str:
    try:
        import deno  # pacote "deno" do pip traz o executável junto
        return str(deno.find_deno_bin())
    except Exception:
        return shutil.which("deno") or ""


def _num(x: str) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def download(pid: str, url: str, progress, max_gb: float = 10) -> tuple[Path, str]:
    """Baixa o link para a pasta do projeto. Devolve (arquivo, título)."""
    folder = store.pdir(pid)
    for attempt in (1, 2):
        title, final, parts, done_parts, err = "", "", 1, 0, []
        proc = subprocess.Popen(_cmd(url, folder, max_gb), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", errors="replace", creationflags=ff.CREATE_FLAGS)
        import threading
        t = threading.Thread(target=lambda: err.extend(proc.stderr), daemon=True)  # type: ignore[arg-type]
        t.start()
        last = 0.0
        for line in proc.stdout:  # type: ignore[union-attr]
            line = line.rstrip("\n")
            if line.startswith("[[T]] "):
                title = line[6:].strip()
                progress(0.03, f"Baixando: {title[:70]}")
            elif line.startswith("[[N]] "):
                parts = 1 if line[6:].strip() in ("", "NA", "None") else 2  # vídeo e áudio separados
            elif line.startswith("[[F]] "):
                final = line[6:].strip()
            elif line.startswith("[[P]] "):
                f = line.split()
                st, got = f[1], _num(f[2])
                total = _num(f[3]) or _num(f[4])
                if st == "finished":
                    done_parts += 1
                    continue
                if total > 0 and time.time() - last > 0.5:
                    last = time.time()
                    frac = min(1.0, got / total)
                    weights = (0.85, 0.15) if parts == 2 else (1.0,)
                    pct = sum(weights[:done_parts]) + weights[min(done_parts, len(weights) - 1)] * frac
                    speed = _num(f[5]) if len(f) > 5 else 0
                    extra = f" · {speed / 1048576:.1f} MB/s" if speed else ""
                    progress(0.03 + 0.95 * min(pct, 1.0), f"Baixando {'o áudio' if done_parts and parts == 2 else 'o vídeo'}: "
                             f"{frac * 100:.0f}% de {total / 1048576:.0f} MB{extra}")
        proc.wait()
        t.join(timeout=3)
        if proc.returncode == 0:
            path = Path(final) if final else None
            if not path or not path.exists():
                cands = sorted(folder.glob("original.*"), key=lambda p: p.stat().st_size, reverse=True)
                path = cands[0] if cands else None
            if not path or not path.exists():
                raise RuntimeError("O download terminou, mas o arquivo não apareceu.")
            return path, title
        msg = "".join(err)
        for junk in folder.glob("original.*"):  # sobras do download que falhou
            try:
                junk.unlink()
            except OSError:
                pass
        if attempt == 1 and _needs_update(msg) and _self_update(progress):
            continue
        raise RuntimeError(friendly(msg))
    raise RuntimeError("Não consegui baixar o vídeo.")


def from_path(pid: str, src: str, progress) -> Path:
    """Programa do PC: usa o arquivo escolhido na janela do Windows. Tenta ligar (instantâneo, sem ocupar espaço
    a mais quando está no mesmo disco); se não der, copia mostrando o progresso."""
    s = Path(src)
    if not s.is_file():
        raise RuntimeError("Arquivo não encontrado.")
    if s.suffix.lower() not in VIDEO_EXT:
        raise RuntimeError("Esse tipo de arquivo não é de vídeo ou áudio.")
    dest = store.pdir(pid) / f"original{s.suffix.lower()}"
    try:
        os.link(s, dest)
        return dest
    except OSError:
        pass
    total, done = s.stat().st_size, 0
    with open(s, "rb") as fi, open(dest, "wb") as fo:
        while True:
            buf = fi.read(8 * 1024 * 1024)
            if not buf:
                break
            fo.write(buf)
            done += len(buf)
            progress(done / max(total, 1), f"Copiando o vídeo: {done * 100 // max(total, 1)}%")
    shutil.copystat(s, dest)
    return dest

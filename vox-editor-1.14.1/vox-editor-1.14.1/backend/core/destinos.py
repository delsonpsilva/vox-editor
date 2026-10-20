"""Destinos próprios de publicação (fora das redes sociais): web TV, site, servidor de streaming ou uma pasta.

Tipos:
  rtmp     — transmite o vídeo ao vivo para um servidor (web TV, MediaCP, Wowza, Owncast, YouTube Live, etc.)
  ftp      — envia o arquivo para uma pasta do seu site ou servidor (FTP ou FTPS)
  webhook  — avisa o seu site (POST com título, legenda e link para baixar o vídeo)
  pasta    — copia o arquivo para uma pasta do computador/servidor (ex.: pasta da playlist da web TV)

As senhas e chaves ficam só no servidor (config.json); o navegador recebe apenas se estão preenchidas."""
from __future__ import annotations

import base64
import ftplib
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import ssl
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx

from . import store
from ..engine import ffmpeg_tools as ff

TIPOS = {
    "rtmp": "Transmissão ao vivo (RTMP)",
    "ftp": "Enviar arquivo (FTP)",
    "webhook": "Avisar meu site (webhook)",
    "pasta": "Copiar para uma pasta",
}
SECRETOS = ("password", "key", "token")
_SEGREDO = store.DATA / "segredo-links.txt"


def _todos() -> list[dict]:
    return list((store.load_config().get("publish") or {}).get("destinos") or [])


def _gravar(lista: list[dict]) -> None:
    pub = store.load_config().get("publish") or {}
    pub["destinos"] = lista
    store.save_config({"publish": pub})


def publicos() -> list[dict]:
    out = []
    for d in _todos():
        v = {k: x for k, x in d.items() if k not in SECRETOS}
        for k in SECRETOS:
            v[k + "_set"] = bool(d.get(k))
        v["tipo_nome"] = TIPOS.get(d.get("kind"), d.get("kind"))
        out.append(v)
    return out


def pegar(did: str) -> dict:
    d = next((x for x in _todos() if x["id"] == did), None)
    if not d:
        raise FileNotFoundError("Destino não encontrado (foi removido?)")
    return d


def descricao(d: dict) -> str:
    k = d.get("kind")
    if k == "rtmp":
        return urlparse(d.get("url", "")).hostname or "servidor RTMP"
    if k == "ftp":
        return f"{d.get('host', '')}/{(d.get('folder') or '').strip('/')}".rstrip("/")
    if k == "webhook":
        return urlparse(d.get("url", "")).hostname or "site"
    if k == "pasta":
        return d.get("path", "")
    return ""


def salvar(dados: dict) -> list[dict]:
    kind = dados.get("kind")
    if kind not in TIPOS:
        raise ValueError("Tipo de destino inválido")
    nome = str(dados.get("name") or "").strip()[:60]
    if not nome:
        raise ValueError("Dê um nome ao destino (ex.: Minha Web TV)")
    lista = _todos()
    did = str(dados.get("id") or "")
    atual = next((x for x in lista if x["id"] == did), None) if did else None
    d = dict(atual or {"id": "d" + uuid.uuid4().hex[:8], "created": time.time()})
    d.update(kind=kind, name=nome)
    texto = lambda k, n=300: str(dados.get(k) or "").strip()[:n]  # noqa: E731
    if kind == "rtmp":
        url = texto("url")
        if not re.match(r"^rtmps?://", url):
            raise ValueError("O endereço do servidor precisa começar com rtmp:// ou rtmps://")
        d["url"] = url
    elif kind == "ftp":
        host = texto("host", 200)
        if not host:
            raise ValueError("Informe o servidor FTP (ex.: ftp.meusite.com.br)")
        d.update(host=re.sub(r"^ftps?://", "", host).strip("/"), port=int(dados.get("port") or 21),
                 user=texto("user", 120), folder=texto("folder", 200), tls=bool(dados.get("tls")),
                 public_url=texto("public_url"))
    elif kind == "webhook":
        url = texto("url")
        if not re.match(r"^https?://", url):
            raise ValueError("O endereço do webhook precisa começar com https://")
        d["url"] = url
    elif kind == "pasta":
        path = texto("path", 400)
        if not path or not (path.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", path) or path.startswith("\\\\")):
            raise ValueError("Informe o caminho completo da pasta (ex.: /srv/webtv/videos ou D:\\WebTV)")
        d["path"] = path
    for k in SECRETOS:  # vazio = mantém o que já estava salvo
        v = str(dados.get(k) or "").strip()
        if v:
            d[k] = v[:500]
        elif dados.get(k + "_clear"):
            d.pop(k, None)
    lista = [x for x in lista if x["id"] != d["id"]] + [d]
    _gravar(lista)
    return publicos()


def remover(did: str) -> list[dict]:
    _gravar([x for x in _todos() if x["id"] != did])
    return publicos()


# ----------------------------------------------------------- link para baixar (webhook)

def _segredo() -> bytes:
    if not _SEGREDO.exists():
        _SEGREDO.write_text(secrets.token_hex(32), encoding="utf-8")
    return _SEGREDO.read_text(encoding="utf-8").strip().encode()


def link_publico(pid: str, arquivo: str, dias: int = 7) -> str:
    """Link assinado (sem senha) para o site baixar o vídeo. Vale por alguns dias e só para este arquivo."""
    exp = int(time.time() + dias * 86400)
    carga = base64.urlsafe_b64encode(json.dumps([pid, arquivo, exp]).encode()).decode().rstrip("=")
    assinatura = hmac.new(_segredo(), carga.encode(), hashlib.sha256).hexdigest()[:32]
    base = (os.environ.get("PUBLIC_URL") or "").rstrip("/")
    return f"{base}/api/publico/{carga}.{assinatura}"


def abrir_link(token: str) -> Path:
    try:
        carga, assinatura = token.rsplit(".", 1)
        certo = hmac.new(_segredo(), carga.encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(certo, assinatura):
            raise ValueError
        pid, arquivo, exp = json.loads(base64.urlsafe_b64decode(carga + "=" * (-len(carga) % 4)))
    except Exception:
        raise FileNotFoundError("Link inválido")
    if time.time() > exp:
        raise FileNotFoundError("Link expirado")
    if "/" in arquivo or "\\" in arquivo:
        raise FileNotFoundError("Link inválido")
    f = store.pdir(pid) / "renders" / arquivo
    if not f.exists():
        raise FileNotFoundError("O vídeo não existe mais")
    return f


# ----------------------------------------------------------- envio

def _nome_arquivo(it: dict, path: Path) -> str:
    base = (it.get("title") or it.get("label") or path.stem)
    base = re.sub(r"[^\w\-]+", "-", base.lower(), flags=re.UNICODE).strip("-")[:60] or "video"
    return f"{base}-{time.strftime('%Y%m%d-%H%M')}{path.suffix}"


def _ftp(d: dict):
    if d.get("tls"):
        ctx = ssl.create_default_context()
        f = ftplib.FTP_TLS(context=ctx, timeout=30)
    else:
        f = ftplib.FTP(timeout=30)
    f.connect(d["host"], int(d.get("port") or 21))
    f.login(d.get("user") or "anonymous", d.get("password") or "")
    if d.get("tls"):
        f.prot_p()
    pasta = (d.get("folder") or "").strip("/")
    if pasta:
        for parte in pasta.split("/"):
            try:
                f.cwd(parte)
            except ftplib.error_perm:
                f.mkd(parte)
                f.cwd(parte)
    return f


def _rtmp_url(d: dict) -> str:
    url = d["url"].rstrip("/")
    return url + "/" + d["key"] if d.get("key") else url


def enviar(did: str, path: Path, it: dict, log) -> str:
    d = pegar(did)
    k = d["kind"]
    if k == "rtmp":
        info = ff.probe(str(path))
        dur = info.get("duration") or 1
        log(0.05, f"Transmitindo ao vivo para {d['name']}…")
        args = [ff.ffmpeg(), "-re", "-i", str(path), "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
                "-f", "flv", "-flvflags", "no_duration_filesize", _rtmp_url(d)]
        ff.run_with_progress(args, dur, lambda x: log(0.05 + 0.93 * x, f"Transmitindo ao vivo para {d['name']}…"))
        return ""
    if k == "ftp":
        nome = _nome_arquivo(it, path)
        size = path.stat().st_size
        log(0.05, f"Conectando em {d['host']}…")
        f = _ftp(d)
        enviado = [0]

        def cb(bloco):
            enviado[0] += len(bloco)
            log(0.05 + 0.93 * enviado[0] / max(1, size), f"Enviando para {d['name']}…")
        with open(path, "rb") as fh:
            f.storbinary(f"STOR {nome}", fh, blocksize=1024 * 256, callback=cb)
        try:
            f.quit()
        except Exception:
            pass
        if d.get("public_url"):
            return d["public_url"].rstrip("/") + "/" + nome
        return ""
    if k == "webhook":
        corpo = {"evento": "video_publicado", "titulo": it.get("title") or "", "legenda": it.get("caption") or "",
                 "rotulo": it.get("label") or "", "arquivo": path.name, "tamanho": path.stat().st_size,
                 "link_download": link_publico(it["project"], it["file"]) if os.environ.get("PUBLIC_URL") else "",
                 "enviado_em": int(time.time())}
        h = {"Content-Type": "application/json", "User-Agent": "VOX-Editor"}
        if d.get("token"):
            h["Authorization"] = f"Bearer {d['token']}"
        log(0.3, f"Avisando {d['name']}…")
        r = httpx.post(d["url"], json=corpo, headers=h, timeout=60)
        if r.status_code >= 400:
            raise RuntimeError(f"O site respondeu com erro {r.status_code}: {r.text[:200]}")
        try:
            return str((r.json() or {}).get("url") or "")
        except Exception:
            return ""
    if k == "pasta":
        dest = Path(d["path"])
        dest.mkdir(parents=True, exist_ok=True)
        alvo = dest / _nome_arquivo(it, path)
        log(0.2, f"Copiando para {dest}…")
        shutil.copy2(path, alvo)
        return str(alvo)
    raise RuntimeError("Tipo de destino desconhecido")


def testar(did: str) -> str:
    """Confere se dá para chegar no destino, sem publicar nada de verdade (no RTMP manda 3 segundos de teste)."""
    d = pegar(did)
    k = d["kind"]
    if k == "ftp":
        f = _ftp(d)
        try:
            pasta = f.pwd()
        finally:
            try:
                f.quit()
            except Exception:
                pass
        return f"Conectou e entrou na pasta {pasta}."
    if k == "rtmp":
        ff.run([ff.ffmpeg(), "-hide_banner", "-loglevel", "error", "-re", "-f", "lavfi", "-i",
                "testsrc2=s=1280x720:r=30:d=3", "-f", "lavfi", "-i", "sine=f=440:d=3", "-c:v", "libx264",
                "-preset", "veryfast", "-pix_fmt", "yuv420p", "-g", "60", "-c:a", "aac", "-shortest",
                "-f", "flv", _rtmp_url(d)])
        return "O servidor aceitou 3 segundos de imagem de teste."
    if k == "webhook":
        h = {"Content-Type": "application/json", "User-Agent": "VOX-Editor"}
        if d.get("token"):
            h["Authorization"] = f"Bearer {d['token']}"
        r = httpx.post(d["url"], json={"evento": "teste", "enviado_em": int(time.time())}, headers=h, timeout=30)
        if r.status_code >= 400:
            raise RuntimeError(f"O site respondeu com erro {r.status_code}")
        return f"O site respondeu ({r.status_code})."
    if k == "pasta":
        p = Path(d["path"])
        p.mkdir(parents=True, exist_ok=True)
        t = p / ".vox-teste"
        t.write_text("ok", encoding="utf-8")
        t.unlink()
        return "A pasta existe e dá para gravar nela."
    raise RuntimeError("Tipo de destino desconhecido")

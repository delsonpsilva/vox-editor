"""Ligação do programa do PC com a versão online (VPS): testar, copiar configurações, enviar e trazer projetos.

Quem conversa com a VPS é o programa do PC (não o navegador), com o endereço e a senha salvos em Configurações."""
from __future__ import annotations

import base64
import json
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Callable

import httpx

from . import pacote, store

_TIMEOUT = httpx.Timeout(30.0, read=600.0, write=600.0)


def _cfg() -> tuple[str, str]:
    o = store.load_config().get("online") or {}
    url, senha = (o.get("url") or "").strip().rstrip("/"), o.get("password") or ""
    if not url:
        raise RuntimeError("Coloque o endereço da versão online em Configurações (ex.: https://editor.voxapps.app).")
    if not url.startswith("http"):
        url = "https://" + url
    return url, senha


def cliente() -> tuple[httpx.Client, str]:
    """Entra na versão online e devolve o cliente já com o login feito."""
    url, senha = _cfg()
    c = httpx.Client(base_url=url, timeout=_TIMEOUT, follow_redirects=True)
    try:
        st = c.get("/api/status").json()
    except Exception:
        c.close()
        raise RuntimeError(f"Não consegui falar com {url}. Confira o endereço e a internet.")
    if st.get("login_required"):
        r = c.post("/api/login", json={"password": senha})
        if r.status_code == 429:
            c.close()
            raise RuntimeError(r.json().get("detail", "Muitas tentativas erradas. Espere alguns minutos."))
        if r.status_code != 200:
            c.close()
            raise RuntimeError("A senha da versão online não confere. Corrija em Configurações.")
    return c, st.get("version", "")


def _erro(r: httpx.Response) -> str:
    try:
        return r.json().get("detail") or r.text[:200]
    except Exception:
        return r.text[:200] or f"erro {r.status_code}"


def testar() -> dict:
    c, versao = cliente()
    with closing(c):
        n = len(c.get("/api/projects").json())
    return {"ok": True, "version": versao, "projects": n}


# ----------------------------------------------------------------- configurações

def pacote_config() -> dict:
    """O que vai para o online: chaves de IA, transcrição, marca, modelos, agenda e os apps das redes.
    NÃO vai: as contas conectadas (ficam só no online, para a autopostagem), a senha do PC e o endereço online."""
    cfg = store.load_config()
    pub = cfg.get("publish") or {}
    conf = {k: cfg.get(k) for k in ("app", "transcription", "ai", "render", "defaults", "brand", "audio") if cfg.get(k)}
    conf["publish"] = {k: v for k, v in pub.items() if k in ("youtube", "meta", "tiktok", "slots")}
    arquivos = {}
    for f in [store.BRAND_DIR / "logo.png", store.BRAND_DIR / "app_logo.png", *(store.BRAND_DIR / "icones").glob("*.png"),
              *(store.BRAND_DIR / "musicas").glob("*")]:
        if f.is_file() and f.stat().st_size < 25 * 1024 * 1024:
            arquivos[f.relative_to(store.BRAND_DIR).as_posix()] = base64.b64encode(f.read_bytes()).decode()
    return {"config": conf, "arquivos": arquivos}


def aplicar_config(dados: dict) -> list[str]:
    """Lado do online: grava o que veio do PC. Devolve a lista do que foi atualizado."""
    conf = dados.get("config") or {}
    feito = []
    cfg = store.load_config()
    for sec in ("app", "transcription", "ai", "render", "defaults", "brand", "audio"):
        if isinstance(conf.get(sec), dict):
            cfg[sec] = {**(cfg.get(sec) or {}), **conf[sec]}
            feito.append(sec)
    if isinstance(conf.get("publish"), dict):
        pub = cfg.get("publish") or {}
        for k, v in conf["publish"].items():
            if k in ("youtube", "meta", "tiktok") and isinstance(v, dict):
                pub[k] = {**(pub.get(k) or {}), **v}
            elif k == "slots" and isinstance(v, list):
                pub["slots"] = v
        cfg["publish"] = pub
        feito.append("publish")
    store._write_json(store.CONFIG_FILE, cfg)
    raiz = store.BRAND_DIR.resolve()
    for rel, b64 in (dados.get("arquivos") or {}).items():
        alvo = (store.BRAND_DIR / rel).resolve()
        if raiz not in alvo.parents:
            continue
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_bytes(base64.b64decode(b64))
    if dados.get("arquivos"):
        feito.append("arquivos")
    return feito


def copiar_config() -> dict:
    c, _ = cliente()
    with closing(c):
        r = c.post("/api/sync/config", json=pacote_config())
        if r.status_code != 200:
            raise RuntimeError("O online recusou as configurações: " + _erro(r))
        return r.json()


# ----------------------------------------------------------------- projetos

def enviar_projeto(pid: str, progress: Callable[[float, str], None]) -> dict:
    proj = store.load(pid)
    total = max(1, pacote.tamanho(pid))
    c, _ = cliente()

    def prog(feito, tot):
        progress(min(0.98, feito / max(1, tot)), f"Enviando para o online: {feito / 1e6:,.0f} de {tot / 1e6:,.0f} MB"
                 .replace(",", "."))

    from urllib.parse import quote
    with closing(c):
        progress(0.01, f"Enviando para o online ({total / 1e6:,.0f} MB)…".replace(",", "."))
        r = c.post("/api/projects/importar-pacote", content=pacote.gerar(pid, True, prog),
                   headers={"Content-Type": "application/zip", "X-Filename": quote(pacote.nome_arquivo(proj))})
        if r.status_code != 200:
            raise RuntimeError("O online não aceitou o projeto: " + _erro(r))
        novo = r.json()
    return {"online_id": novo.get("id"), "name": novo.get("name")}


def projetos_online() -> list[dict]:
    c, _ = cliente()
    with closing(c):
        r = c.get("/api/projects")
        if r.status_code != 200:
            raise RuntimeError(_erro(r))
        return r.json()


def trazer_projeto(online_id: str, progress: Callable[[float, str], None]) -> dict:
    c, _ = cliente()
    tmp = Path(tempfile.mkstemp(suffix=".vox", dir=str(store.DATA))[1])
    try:
        with closing(c), c.stream("GET", f"/api/projects/{online_id}/pacote") as r:
            if r.status_code != 200:
                r.read()
                raise RuntimeError("O online não entregou o projeto: " + _erro(r))
            total = int(r.headers.get("x-vox-bytes") or 0)
            feito = 0
            with open(tmp, "wb") as fh:
                for b in r.iter_bytes(4 * 1024 * 1024):
                    fh.write(b)
                    feito += len(b)
                    msg = f"Baixando do online: {feito / 1e6:,.0f} MB".replace(",", ".")
                    progress(min(0.9, feito / total) if total else 0.5, msg)
        progress(0.95, "Abrindo o projeto…")
        proj = pacote.importar(tmp)
    finally:
        tmp.unlink(missing_ok=True)
    return {"id": proj["id"], "name": proj["name"]}

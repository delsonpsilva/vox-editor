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


# ----------------------------------------------------------------- contas das redes pelo online
# O PC não guarda login de rede nenhuma: as contas ficam conectadas no servidor (que renova o acesso sozinho)
# e o PC só pergunta ao online quem está conectado, abre o login de lá no navegador e manda o vídeo para a fila.

_cache_status: dict = {"t": 0.0, "dados": None}


def configurado() -> bool:
    o = store.load_config().get("online") or {}
    return bool((o.get("url") or "").strip())


def status_online(max_idade: float = 20.0) -> dict | None:
    """Contas e apps do online (guardado por alguns segundos para a tela não ficar lenta). None se não der."""
    import time as _t
    if not configurado():
        return None
    if _cache_status["dados"] is not None and _t.time() - _cache_status["t"] < max_idade:
        return _cache_status["dados"]
    try:
        c, _ = cliente()
        with closing(c):
            r = c.get("/api/publish/status", timeout=8.0)
            dados = r.json() if r.status_code == 200 else None
    except Exception:
        dados = None
    _cache_status.update(t=_t.time(), dados=dados)
    return dados


def esquecer_status() -> None:
    _cache_status.update(t=0.0, dados=None)


def link_login(app: str) -> str:
    """Pede ao online um link de login (vale 10 minutos) para abrir no navegador do PC."""
    c, _ = cliente()
    with closing(c):
        r = c.post(f"/api/oauth/{app}/ticket", json={"desk": True})
        if r.status_code == 404:
            raise RuntimeError("A versão online está desatualizada. Na VPS rode: sudo vox-atualizar")
        if r.status_code != 200:
            raise RuntimeError("O online recusou o login: " + _erro(r))
    esquecer_status()
    return r.json()["url"]


def desconectar(app: str) -> None:
    c, _ = cliente()
    with closing(c):
        r = c.delete(f"/api/publish/account/{app}")
        if r.status_code != 200:
            raise RuntimeError(_erro(r))
    esquecer_status()


def escolher_pagina(page_id: str) -> None:
    c, _ = cliente()
    with closing(c):
        c.post("/api/publish/page", json={"page_id": page_id})
    esquecer_status()


def fila_online() -> list[dict]:
    try:
        c, _ = cliente()
        with closing(c):
            r = c.get("/api/publish/queue", timeout=8.0)
            return r.json() if r.status_code == 200 else []
    except Exception:
        return []


def fila_acao(metodo: str, caminho: str, json_body: dict | None = None) -> None:
    c, _ = cliente()
    with closing(c):
        r = c.request(metodo, caminho, json=json_body)
        if r.status_code != 200:
            raise RuntimeError(_erro(r))


def publicar(pid: str, arquivo: str, pedido: dict, progress: Callable[[float, str], None]) -> dict:
    """Manda o vídeo exportado para o online e coloca na fila de lá (o online publica e renova os logins)."""
    import json as _json
    from urllib.parse import quote
    src = store.pdir(pid) / "renders" / arquivo
    if not src.exists():
        raise RuntimeError("Vídeo exportado não encontrado.")
    total = max(1, src.stat().st_size)
    proj = store.load(pid)

    def ler():
        feito = 0
        with open(src, "rb") as fh:
            while True:
                b = fh.read(2 * 1024 * 1024)
                if not b:
                    break
                feito += len(b)
                progress(min(0.97, feito / total), f"Enviando para o online: {feito / 1e6:,.0f} de "
                         f"{total / 1e6:,.0f} MB".replace(",", "."))
                yield b

    meta = {**pedido, "project_name": proj.get("name", "")}
    c, _ = cliente()
    with closing(c):
        progress(0.01, "Enviando o vídeo para o online…")
        r = c.post("/api/publish/receber", content=ler(),
                   headers={"Content-Type": "video/mp4", "X-Filename": quote(arquivo),
                            "X-Vox-Pedido": quote(_json.dumps(meta, ensure_ascii=False))})
        if r.status_code == 404:
            raise RuntimeError("A versão online está desatualizada. Na VPS rode: sudo vox-atualizar")
        if r.status_code != 200:
            raise RuntimeError("O online não aceitou a publicação: " + _erro(r))
    return r.json()

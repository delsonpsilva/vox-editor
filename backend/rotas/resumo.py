"""Resumo do Culto (v1.14): vários vídeos e fotos viram um resumão com música na Montagem."""
from __future__ import annotations

from urllib.parse import unquote

from fastapi import APIRouter

from ..core import resumo
from .comum import *  # noqa: F401,F403

router = APIRouter()


@router.get("/api/resumo/status")
def resumo_status():
    return resumo.status()


@router.get("/api/resumo/lista")
def resumo_lista():
    return resumo.lista()


@router.post("/api/resumo/novo")
def resumo_novo(data: dict = Body(default={})):
    """Projeto vazio que vai recebendo os arquivos enquanto a pessoa escolhe as opções."""
    _limites(minutos=False)
    nome = str(data.get("name") or "").strip()[:120] or "Resumo do culto"
    formato = data.get("formato") if data.get("formato") in montagem.FORMATOS else "9:16"
    proj = montagem.projeto_em_branco(nome, formato)
    store.update(proj["id"], lambda p: p.update(resumo={"criado": time.time()}))
    return {"id": proj["id"]}


@router.post("/api/resumo/{pid}/arquivo")
async def resumo_arquivo(pid: str, request: Request):
    """Um vídeo, foto ou música do culto. Cabeçalhos: x-filename, x-modificado (ms) e x-fuso (minutos)."""
    _404(lambda: store.load(pid))
    _limites(minutos=False)
    nome = unquote(request.headers.get("x-filename", "arquivo"))
    nome = re.sub(r"[\\/:*?\"<>|]+", "_", nome).strip() or "arquivo"
    kind = montagem.tipo_por_extensao(nome)
    if not kind:
        if nome.lower().endswith((".heic", ".heif")):
            raise HTTPException(400, "Foto HEIC do iPhone ainda não é aceita. No iPhone: Ajustes > Câmera > Formatos > "
                                     "\"Mais compatível\" (ou envie a foto pelo WhatsApp, que vira JPG).")
        raise HTTPException(400, "Tipo de arquivo não aceito. Envie vídeos, fotos (JPG, PNG, WEBP) ou uma música.")
    try:
        modificado = float(request.headers.get("x-modificado") or 0) or None
    except ValueError:
        modificado = None
    try:
        fuso = int(request.headers.get("x-fuso")) if request.headers.get("x-fuso") not in (None, "") else None
    except ValueError:
        fuso = None
    dest = montagem.pasta_midias(pid) / f"{secrets.token_hex(4)}_{nome}"
    size, limit = 0, MAX_UPLOAD_GB * 1024 ** 3
    try:
        with open(dest, "wb") as fh:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"Arquivo maior que {MAX_UPLOAD_GB:g} GB")
                fh.write(chunk)
        if size == 0:
            raise HTTPException(400, "Arquivo vazio")
        from starlette.concurrency import run_in_threadpool
        quando = await run_in_threadpool(resumo.hora_da_midia, dest, kind, modificado, fuso)
        extra = {"quando": quando} if quando else None
        item = await run_in_threadpool(montagem.adicionar_midia, pid, dest, nome, extra)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, f"Não consegui usar esse arquivo: {str(e)[:200]}")
    _previas_pendentes(pid, montagem.carregar(pid))
    return item


@router.post("/api/resumo/{pid}/criar")
def resumo_criar(pid: str, data: dict = Body(default={})):
    proj = _404(lambda: store.load(pid))
    if any(j["status"] in jobs.STATUS_ATIVOS for j in jobs.for_project(pid) if j["kind"] == "resumo"):
        raise HTTPException(409, "Este resumo já está sendo montado. Espere terminar.")
    nome = str(data.get("name") or "").strip()[:120]
    if nome and nome != proj.get("name"):
        store.update(pid, lambda p: p.update(name=nome))
    opts = dict(data.get("opcoes") or {})

    def tarefa(pr):
        def prog(x, msg=""):
            pr(x, msg)
            if msg:
                store.update(pid, lambda p: p.update(progress={"pct": round(x, 3), "msg": msg}))
        store.update(pid, lambda p: p.update(status="processando", progress={"pct": 0, "msg": "Começando…"}))
        try:
            r = resumo.criar(pid, opts, prog)
        except Exception as e:
            # o projeto continua com os arquivos: dá para tentar de novo com outras opções
            store.update(pid, lambda p: p.update(status="pronto", progress={"pct": 1, "msg": str(e)[:300]}))
            raise
        store.update(pid, lambda p: p.update(status="pronto", progress={"pct": 1, "msg": ""}))
        return r
    j = jobs.submit("resumo", pid, tarefa, queue="analysis", label="Resumo do culto")
    return {"id": pid, "job": j["id"]}

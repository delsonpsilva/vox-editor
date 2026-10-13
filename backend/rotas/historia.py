"""História → Vídeo (v1.9): texto, áudio ou narração ao vivo viram uma Montagem pronta."""
from __future__ import annotations

import json
from urllib.parse import unquote

from fastapi import APIRouter

from ..core import historia
from .comum import *  # noqa: F401,F403

router = APIRouter()


def _job(pid: str, fn, label: str) -> dict:
    """Roda em segundo plano; o cartão do projeto mostra o andamento e, se der erro, o motivo."""
    def tarefa(pr):
        def prog(x, msg=""):
            pr(x, msg)
            if msg:
                store.update(pid, lambda p: p.update(progress={"pct": round(x, 3), "msg": msg}))
        store.update(pid, lambda p: p.update(status="processando", progress={"pct": 0, "msg": "Começando…"}))
        try:
            r = fn(prog)
        except Exception as e:
            store.update(pid, lambda p: p.update(status="erro", progress={"pct": 0, "msg": str(e)[:300]}))
            raise
        store.update(pid, lambda p: p.update(status="pronto", progress={"pct": 1, "msg": ""}))
        return r
    j = jobs.submit("historia", pid, tarefa, queue="analysis", label=label)
    return {"id": pid, "job": j["id"]}


@router.get("/api/historia/status")
def historia_status():
    return historia.status()


@router.post("/api/historia/texto")
def historia_texto(data: dict = Body(...)):
    texto = str(data.get("texto") or "").strip()
    if len(texto.split()) < 3:
        raise HTTPException(400, "Escreva ou cole a história (pelo menos uma frase).")
    _limites(minutos=False)
    opts = data.get("opcoes") or {}
    pid = historia.novo_projeto(str(data.get("name") or "")[:120] or texto.split("\n")[0][:60],
                                opts.get("formato") or "9:16", "texto")
    return _job(pid, lambda pr: historia.criar_de_texto(pid, texto, opts, pr), "História → vídeo")


@router.post("/api/historia/audio")
async def historia_audio(request: Request):
    """Arquivo de áudio (ou vídeo) com a narração. Opções no cabeçalho x-opcoes (JSON)."""
    _limites(minutos=False)
    nome = unquote(request.headers.get("x-filename", "narracao.mp3"))
    nome = re.sub(r"[\\/:*?\"<>|]+", "_", nome).strip() or "narracao.mp3"
    try:
        opts = json.loads(unquote(request.headers.get("x-opcoes", "{}")) or "{}")
    except json.JSONDecodeError:
        opts = {}
    if montagem.tipo_por_extensao(nome) not in ("audio", "video"):
        raise HTTPException(400, "Envie um áudio (MP3, WAV, M4A, OGG...) ou um vídeo com a narração.")
    pid = historia.novo_projeto(str(opts.get("name") or "")[:120] or nome.rsplit(".", 1)[0][:60],
                                opts.get("formato") or "9:16", "audio")
    dest = montagem.pasta_midias(pid) / ("narracao_" + secrets.token_hex(3) + "_" + nome)
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
    except HTTPException:
        dest.unlink(missing_ok=True)
        store.delete_project(pid)
        raise
    if montagem.tipo_por_extensao(nome) == "video":  # do vídeo, fica só o som da narração
        so_audio = dest.with_suffix(".m4a")
        try:
            ff.run([ff.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(dest), "-vn", "-c:a", "aac",
                    "-b:a", "160k", str(so_audio)])
        except Exception:
            store.delete_project(pid)
            raise HTTPException(400, "Não consegui tirar o som desse vídeo.")
        dest.unlink(missing_ok=True)
        dest = so_audio
    return _job(pid, lambda pr: historia.criar_de_audio(pid, dest, opts, pr), "Narração → vídeo")


@router.post("/api/historia/ao-vivo")
def historia_ao_vivo_novo(data: dict = Body(default={})):
    _limites(minutos=False)
    pid = historia.novo_projeto(str(data.get("name") or "")[:120] or "Narração ao vivo",
                                data.get("formato") or "9:16", "ao_vivo")
    historia.pasta_ao_vivo(pid)
    threading.Thread(target=historia.aquecer, daemon=True).start()
    return {"id": pid}


@router.post("/api/historia/{pid}/ao-vivo/pedaco")
async def historia_pedaco(pid: str, request: Request):
    _404(lambda: store.load(pid))
    corpo = await request.body()
    if len(corpo) > 16000 * 2 * 60:
        raise HTTPException(413, "Pedaço grande demais")
    from starlette.concurrency import run_in_threadpool
    try:
        return await run_in_threadpool(historia.pedaco_ao_vivo, pid, corpo)
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@router.post("/api/historia/{pid}/ao-vivo/terminar")
def historia_terminar(pid: str, data: dict = Body(default={})):
    _404(lambda: store.load(pid))
    opts = data.get("opcoes") or {}
    return _job(pid, lambda pr: historia.terminar_ao_vivo(pid, opts, pr), "Narração ao vivo → vídeo")


@router.post("/api/historia/previa")
def historia_previa(data: dict = Body(...)):
    return historia.previa_cena(str(data.get("texto") or "")[:2000], data.get("formato") or "9:16")

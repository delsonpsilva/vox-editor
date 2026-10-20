"""Exportação: prévia da legenda, renderizar, baixar/apagar exportados, exportar arquivos e a fila de tarefas."""
from __future__ import annotations

from fastapi import APIRouter

from .comum import *  # noqa: F401,F403

router = APIRouter()


@router.get("/api/projects/{pid}/subtitle-preview")
def subtitle_preview(pid: str, style: str = "", t: float | None = None, v: str = ""):
    try:
        f = pipeline.subtitle_preview(pid, style, t)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, str(e)[:300])
    return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})


@router.post("/api/projects/{pid}/render")
def render_full(pid: str, data: dict = Body(default={})):
    _404(lambda: store.load(pid))
    jobs.submit("render", pid, lambda pr: pipeline.render_full(pid, data, pr), queue="render", label="Vídeo editado")
    return view(store.load(pid))


@router.post("/api/projects/{pid}/clips/{clip_id}/render")
def render_clip(pid: str, clip_id: str, data: dict = Body(default={})):
    _404(lambda: store.load(pid))
    jobs.submit("render", pid, lambda pr: pipeline.render_clip(pid, clip_id, data, pr), queue="render",
                label=f"Corte {clip_id.replace('clip', '')}")
    return view(store.load(pid))


@router.get("/api/projects/{pid}/renders/{name}")
def get_render(pid: str, name: str):
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(400, "Nome inválido")
    f = store.pdir(pid) / "renders" / name
    if not f.exists():
        raise HTTPException(404, "Arquivo não encontrado")
    return FileResponse(f, filename=name)


@router.delete("/api/projects/{pid}/renders/{name}")
def del_render(pid: str, name: str):
    if "/" in name or "\\" in name:
        raise HTTPException(400, "Nome inválido")
    (store.pdir(pid) / "renders" / name).unlink(missing_ok=True)
    return view(store.update(pid, lambda p: p.update(renders=[r for r in p.get("renders", []) if r["file"] != name])))


@router.get("/api/projects/{pid}/export/{fmt}")
def export(pid: str, fmt: str):
    try:
        content, fname, mime = _404(lambda: pipeline.export(pid, fmt))
    except ValueError as e:
        raise HTTPException(400, str(e))
    from urllib.parse import quote
    return Response(content, media_type=mime + "; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(fname)}"})


@router.get("/api/jobs/{pid}")
def project_jobs(pid: str):
    return jobs.for_project(pid)


@router.post("/api/jobs/{pid}/{jid}/cancelar")
def cancelar_job(pid: str, jid: str):
    """v1.8: cancela uma tarefa da fila (na fila sai na hora; rodando, para em segundos)."""
    j = jobs.get(jid)
    if not j or j["project"] != pid:
        raise HTTPException(404, "Tarefa não encontrada")
    u = contas.eu()
    if u and u["papel"] == "cliente" and j.get("pedido_por") not in (None, u["id"]):
        raise HTTPException(404, "Tarefa não encontrada")
    jobs.cancelar(jid)
    # análise ou download cancelado: o projeto fica com o aviso e o botão "Tentar novamente"
    if j["kind"] in ("analise", "download", "importar") and pid != "_online":
        try:
            if store.load(pid).get("status") in ("na fila", "baixando", "processando"):
                pipeline._set(pid, "erro", None, "Cancelado por você. Clique em Tentar novamente quando quiser.")
        except Exception:
            pass
    return jobs.get(jid)


@router.get("/api/fila")
def fila_resumo():
    """v1.8: situação da fila (limites, rodando, esperando) — só responsável e administradores."""
    if not contas.ve_tudo():
        raise HTTPException(403, "Só o responsável pela conta pode ver a fila completa.")
    return jobs.resumo()

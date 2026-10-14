"""Projetos: lista, painel, envio de vídeo, importar por link/arquivo, pacote .vox e ligação PC ↔ online."""
from __future__ import annotations

from fastapi import APIRouter

from .comum import *  # noqa: F401,F403

router = APIRouter()


@router.get("/api/projects")
def projects():
    out = store.list_projects()
    for p in out:
        if p["status"] == "pronto":
            try:
                ed = edits.build_edit(store.load(p["id"]))
                p["final"] = ed["stats"]["final"]
                p["timeline"] = _mini_timeline(ed["keeps"], p["duration"])
            except Exception:
                pass
    return out


@router.patch("/api/projects/{pid}")
def rename_project(pid: str, data: dict = Body(...)):
    name = str(data.get("name", "")).strip()[:120]
    if not name:
        raise HTTPException(400, "Dê um nome ao projeto")
    return view(_404(lambda: store.update(pid, lambda p: p.update(name=name))))


@router.get("/api/projects/{pid}/poster")
def poster(pid: str):
    """Miniatura 16:9 do projeto (um quadro do vídeo)."""
    proj = _404(lambda: store.load(pid))
    folder = store.pdir(pid)
    out = folder / "cache" / "poster.jpg"
    if not out.exists():
        media = proj.get("media") or {}
        if not media.get("has_video") or not proj.get("source"):
            raise HTTPException(404, "Sem imagem")
        out.parent.mkdir(exist_ok=True)
        t = max(0.0, min(media.get("duration", 10) * 0.15, 60.0))
        try:
            ff.run([ff.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.2f}", "-i",
                    str(folder / proj["source"]), "-frames:v", "1", "-vf",
                    "scale=640:360:force_original_aspect_ratio=increase,crop=640:360", "-q:v", "4", str(out)])
        except Exception:
            raise HTTPException(404, "Sem imagem")
    return FileResponse(out, media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})


@router.get("/api/renders")
def all_renders():
    """Biblioteca: todos os vídeos exportados, de todos os projetos."""
    out = []
    for p in store.list_projects():
        try:
            proj = store.load(p["id"])
        except Exception:
            continue
        for r in proj.get("renders") or []:
            if (store.pdir(p["id"]) / "renders" / r["file"]).exists():
                out.append({**r, "project": p["id"], "project_name": proj["name"]})
    return sorted(out, key=lambda r: -r.get("created", 0))


@router.get("/api/projects/{pid}/renders/{name}/thumb")
def render_thumb(pid: str, name: str):
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(400, "Nome inválido")
    folder = store.pdir(pid)
    src = folder / "renders" / name
    if not src.exists():
        raise HTTPException(404, "Arquivo não encontrado")
    out = folder / "cache" / f"rt-{Path(name).stem}.jpg"
    if not out.exists():
        out.parent.mkdir(exist_ok=True)
        try:
            ff.run([ff.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-ss", "1.5", "-i", str(src),
                    "-frames:v", "1", "-vf", "scale=-2:480", "-q:v", "5", str(out)])
        except Exception:
            raise HTTPException(404, "Sem imagem")
    return FileResponse(out, media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})


@router.get("/api/dashboard")
def dashboard():
    ps = projects()
    total_in = sum(p.get("duration") or 0 for p in ps)
    removed, clips, renders = 0.0, 0, 0
    for p in ps:
        if p["status"] == "pronto" and p.get("final") is not None:
            removed += max(0.0, (p.get("duration") or 0) - (p.get("final") or 0))
        clips += p.get("clips", 0)
        renders += p.get("renders", 0)
    import shutil as _sh
    try:
        free = _sh.disk_usage(str(store.DATA)).free
    except OSError:
        free = 0
    usado = store.folder_size(store.PROJECTS)
    u = contas.eu()
    if u and u["papel"] != "dono":  # v1.7: a pessoa vê o próprio espaço e o que resta do limite dela
        usado = contas.espaco_usado(u["id"])
        livre = contas.espaco_livre_bytes()
        if livre is not None:
            free = int(livre)
    return {"projects": len(ps), "seconds_in": round(total_in), "removed": round(removed), "clips": clips,
            "renders": renders, "storage": usado, "free": free, "serie": _serie_semanal(ps)}


def _serie_semanal(ps: list[dict], semanas: int = 8) -> dict:
    """v1.11: totais acumulados no fim de cada uma das últimas semanas, para os mini gráficos da tela inicial."""
    import time as _t
    agora = _t.time()
    fins = [agora - (semanas - 1 - i) * 7 * 86400 for i in range(semanas)]
    out = {"enviado": [], "cortado": [], "cortes": [], "exportados": []}
    for fim in fins:
        e = c = n = r = 0.0
        for p in ps:
            if (p.get("created") or 0) > fim:
                continue
            dur = p.get("duration") or 0
            e += dur
            if p.get("status") == "pronto" and p.get("final") is not None:
                c += max(0.0, dur - (p.get("final") or 0))
            n += p.get("clips", 0)
            r += p.get("renders", 0)
        out["enviado"].append(round(e)); out["cortado"].append(round(c))
        out["cortes"].append(int(n)); out["exportados"].append(int(r))
    return out


@router.get("/api/atividade")
def atividade():
    """Tudo o que está acontecendo agora, para a barra do topo: análises, exportações, downloads e as próximas postagens."""
    nomes = {p["id"]: p for p in store.list_projects()}
    trabalhos = []
    ve_tudo = contas.ve_tudo()
    for j in jobs.atividade():
        if not ve_tudo and j["project"] not in nomes:
            continue  # v1.7: cliente só vê o andamento dos próprios projetos
        p = nomes.get(j["project"]) or {}
        trabalhos.append({"id": j["id"], "kind": j["kind"], "label": j.get("label") or "", "status": j["status"],
                          "pct": j["pct"], "msg": j["msg"], "error": j.get("error"), "project": j["project"],
                          "project_name": p.get("name", ""), "project_kind": p.get("kind", ""), "created": j["created"]})
    analisando = [{"id": p["id"], "name": p["name"], "status": p["status"], "progress": p.get("progress") or {}}
                  for p in nomes.values() if p["status"] in ("enviando", "baixando", "processando", "na fila")]
    proximas = []
    try:
        for it in sorted((x for x in (publish.queue() if contas.pode_publicar() else [])
                          if x.get("status") in ("agendado", "publicando")),
                         key=lambda x: x.get("when", 0))[:6]:
            p = nomes.get(it.get("project")) or {}
            proximas.append({"id": it["id"], "net": it["net"], "when": it.get("when", 0), "status": it["status"],
                             "title": it.get("title") or it.get("label") or it.get("file"), "project": it.get("project"),
                             "file": it.get("file"), "project_name": p.get("name", ""), "pct": it.get("pct", 0)})
    except Exception:
        pass
    return {"trabalhos": trabalhos, "analisando": analisando, "proximas": proximas}


@router.post("/api/maintenance/clean")
def clean():
    """Apaga arquivos temporários que o sistema refaz quando precisar (miniaturas, prévias, áudio de render)."""
    freed = 0
    for folder in store.PROJECTS.iterdir():
        if not folder.is_dir():
            continue
        for f in list((folder / "cache").glob("*")) + [folder / "audio48k.raw"]:
            try:
                if f.is_file():
                    freed += f.stat().st_size
                    f.unlink()
            except OSError:
                pass
    try:  # v1.8: também os restos de exportações interrompidas e exportados órfãos
        freed += manutencao.limpar("manual")["liberado"]
    except Exception:
        pass
    return {"freed": freed}


@router.post("/api/app/logo")
async def app_logo(request: Request):
    data = await request.body()
    if not data or len(data) > 8 * 1024 * 1024:
        raise HTTPException(400, "Envie uma imagem de até 8 MB")
    tmp = store.BRAND_DIR / "app_upload.bin"
    tmp.write_bytes(data)
    try:
        ff.run([ff.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(tmp), "-frames:v", "1",
                "-vf", "scale=256:256:force_original_aspect_ratio=decrease:flags=lanczos,format=rgba",
                str(store.BRAND_DIR / "app_logo.png")])
    except Exception:
        raise HTTPException(400, "Não consegui ler a imagem (use PNG ou JPG)")
    finally:
        tmp.unlink(missing_ok=True)
    return {"ok": True}


@router.delete("/api/app/logo")
def app_logo_delete():
    (store.BRAND_DIR / "app_logo.png").unlink(missing_ok=True)
    return {"ok": True}


@router.get("/api/app/logo")
def app_logo_get():
    f = store.BRAND_DIR / "app_logo.png"
    if not f.exists():
        raise HTTPException(404, "Sem logo")
    return FileResponse(f, media_type="image/png", headers={"Cache-Control": "no-cache"})


@router.post("/api/projects")
async def upload(request: Request):
    """Recebe o arquivo em fluxo contínuo (suporta vários GB sem usar memória)."""
    name = request.headers.get("x-filename", "video.mp4")
    try:
        from urllib.parse import unquote
        name = unquote(name)
    except Exception:
        pass
    name = re.sub(r"[\\/:*?\"<>|]+", "_", name).strip() or "video.mp4"
    ext = Path(name).suffix.lower() or ".mp4"
    _limites()
    livre = contas.espaco_livre_bytes()
    proj = store.new_project(name)
    folder = store.pdir(proj["id"])
    dest = folder / f"original{ext}"
    size, limit = 0, MAX_UPLOAD_GB * 1024 ** 3
    try:
        with open(dest, "wb") as fh:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"Arquivo maior que {MAX_UPLOAD_GB:g} GB")
                if livre is not None and size > livre:
                    raise HTTPException(413, "Esse vídeo passa do espaço que ainda resta na sua conta.")
                fh.write(chunk)
    except BaseException:
        store.delete_project(proj["id"])
        raise
    if size == 0:
        store.delete_project(proj["id"])
        raise HTTPException(400, "Arquivo vazio")
    store.update(proj["id"], lambda p: p.update(source=dest.name, size=size, status="na fila",
                                                progress={"pct": 0, "msg": "Na fila para análise…"}))
    pid = proj["id"]
    jobs.submit("analise", pid, _trabalho_analise(pid), label="Análise")
    return view(store.load(pid))


@router.post("/api/projects/link")
def import_link(data: dict = Body(...)):
    """Importa pelo link (YouTube e outros sites). Quem baixa é o próprio programa: sem API e sem custo."""
    try:
        url = importer.clean_url(data.get("url", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))
    _limites()
    proj = store.new_project("Vídeo do link")
    pid = proj["id"]
    store.update(pid, lambda p: p.update(status="baixando", link=url, progress={"pct": 0, "msg": "Conectando ao site do vídeo…"}))
    _import_job(pid, "download", lambda step: importer.download(pid, url, step, MAX_UPLOAD_GB))
    return view(store.load(pid))


@router.post("/api/projects/path")
def import_path(request: Request, data: dict = Body(...)):
    """Só no programa do PC: usa o arquivo escolhido na janela do Windows, sem reenviar pelo navegador."""
    if not _is_local(request):
        raise HTTPException(403, "Disponível só no programa instalado no PC.")
    src = Path(str(data.get("path", "")))
    if not src.is_file():
        raise HTTPException(400, "Arquivo não encontrado.")
    proj = store.new_project(src.name)
    pid = proj["id"]
    store.update(pid, lambda p: p.update(status="baixando", progress={"pct": 0, "msg": "Preparando o vídeo…"}))
    _import_job(pid, "importar", lambda step: (importer.from_path(pid, str(src), step), ""))
    return view(store.load(pid))


# ---------- pacote do projeto (.vox) e ligação PC ↔ online ----------

@router.get("/api/projects/{pid}/pacote")
def baixar_pacote(pid: str):
    """Baixa o projeto inteiro num arquivo .vox, para abrir em outra instalação (PC ↔ online) sem perder nada."""
    proj = _404(lambda: store.load(pid))
    from urllib.parse import quote
    nome = pacote.nome_arquivo(proj)
    return StreamingResponse(pacote.gerar(pid), media_type="application/zip", headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(nome)}",
        "X-Vox-Bytes": str(pacote.tamanho(pid))})


@router.post("/api/projects/importar-pacote")
async def importar_pacote(request: Request):
    """Recebe um .vox (do botão "Importar projeto do PC" ou do "Enviar para o online") e abre como estava."""
    _limites(minutos=False)
    dono = contas.id_atual()
    tmp = store.DATA / f"_recebendo-{secrets.token_hex(6)}.vox"
    size, limit = 0, (MAX_UPLOAD_GB + 2) * 1024 ** 3
    try:
        with open(tmp, "wb") as fh:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"Projeto maior que {MAX_UPLOAD_GB:g} GB")
                fh.write(chunk)
        if size == 0:
            raise HTTPException(400, "Arquivo vazio")
        import asyncio
        try:
            proj = await asyncio.get_running_loop().run_in_executor(None, pacote.importar, tmp)
        except ValueError as e:
            raise HTTPException(400, str(e))
    finally:
        tmp.unlink(missing_ok=True)
    def _carimbo(p):  # o pacote pode ter vindo com o dono de outra instalação: fica com quem importou
        p.pop("owner", None)
        if dono:
            p["owner"] = dono
    proj = store.update(proj["id"], _carimbo)
    return view(proj)


@router.post("/api/sync/config")
def receber_config(data: dict = Body(...)):
    """Lado do online: recebe as configurações copiadas do PC."""
    return {"ok": True, "updated": online.aplicar_config(data)}


@router.put("/api/online/config")
def online_config(data: dict = Body(...)):
    _so_pc()
    store.save_config({"online": {"url": data.get("url", ""), "password": data.get("password", "")}})
    return store.public_config(store.load_config())["online"]


@router.post("/api/online/testar")
def online_testar():
    _so_pc()
    return _falha_online(online.testar)


@router.post("/api/online/copiar-config")
def online_copiar():
    _so_pc()
    return _falha_online(online.copiar_config)


@router.get("/api/online/projetos")
def online_projetos():
    _so_pc()
    return _falha_online(online.projetos_online)


@router.post("/api/projects/{pid}/enviar-online")
def enviar_online(pid: str):
    _so_pc()
    proj = _404(lambda: store.load(pid))
    if proj.get("status") != "pronto":
        raise HTTPException(400, "Espere a análise terminar antes de enviar.")
    _falha_online(lambda: online._cfg())
    jobs.submit("enviar", pid, lambda pr: online.enviar_projeto(pid, pr), queue="download", label="Enviando para o online")
    return view(store.load(pid))


@router.post("/api/online/trazer/{rid}")
def trazer_online(rid: str):
    _so_pc()
    if any(c not in "0123456789abcdef" for c in rid):
        raise HTTPException(400, "Projeto inválido")
    _falha_online(lambda: online._cfg())
    job = jobs.submit("trazer", "_online", lambda pr: online.trazer_projeto(rid, pr), queue="download",
                      label="Trazendo do online")
    return job


@router.get("/api/projects/{pid}")
def project(pid: str):
    proj = _404(lambda: store.load(pid))
    if proj.get("status") == "pronto" and proj.get("kind") != "montagem" and (proj.get("analysis") or {}).get("v", 0) < 3:
        proj = pipeline.reanalyze(pid)  # projetos de versões anteriores ganham as emendas inteligentes
    return view(proj)


@router.delete("/api/projects/{pid}")
def delete(pid: str):
    _404(lambda: store.load(pid))
    store.delete_project(pid)
    return {"ok": True}


@router.post("/api/projects/{pid}/reprocess")
def reprocess(pid: str):
    proj = _404(lambda: store.load(pid))
    src = proj.get("source")
    if (not src or not (store.pdir(pid) / src).exists()) and proj.get("link"):  # download não terminou: baixa de novo
        url = proj["link"]
        store.update(pid, lambda p: p.update(status="baixando", progress={"pct": 0, "msg": "Conectando ao site do vídeo…"}))
        _import_job(pid, "download", lambda step: importer.download(pid, url, step, MAX_UPLOAD_GB))
        return view(store.load(pid))
    store.update(pid, lambda p: p.update(status="na fila", progress={"pct": 0, "msg": "Na fila para análise…"}))
    jobs.submit("analise", pid, _trabalho_analise(pid), label="Nova análise")
    return view(store.load(pid))


@router.get("/api/projects/{pid}/wave")
def wave(pid: str):
    f = store.pdir(pid) / "onda.json"
    if not f.exists():
        return []
    return Response(f.read_text(encoding="utf-8"), media_type="application/json")


@router.get("/api/projects/{pid}/media")
def media(pid: str):
    proj = _404(lambda: store.load(pid))
    f = store.pdir(pid) / (proj.get("preview") or proj["source"])
    if not f.exists():
        raise HTTPException(404, "Mídia não encontrada")
    return FileResponse(f)


@router.put("/api/projects/{pid}/settings")
def put_project_settings(pid: str, data: dict = Body(...)):
    def fn(p):
        cur = p.get("settings") or {}
        for k, v in data.items():
            if isinstance(v, dict):
                cur[k] = {**(cur.get(k) or {}), **v}
        p["settings"] = cur
    proj = _404(lambda: store.update(pid, fn))
    if ("silence" in data or "breath" in data) and proj.get("status") == "pronto":
        proj = pipeline.reanalyze(pid)
    return view(proj)


@router.post("/api/projects/{pid}/cuts/{cid}/toggle")
def toggle_cut(pid: str, cid: str):
    def fn(p):
        r = p.setdefault("overrides", {}).setdefault("restored", [])
        if cid in r:
            r.remove(cid)
        else:
            r.append(cid)
    return view(_404(lambda: store.update(pid, fn)))


@router.post("/api/projects/{pid}/cleanup-ai")
def cleanup_ai(pid: str):
    _404(lambda: store.load(pid))
    jobs.submit("limpeza", pid, lambda pr: pipeline.ai_cleanup(pid, pr), label="Limpeza da fala com IA")
    return view(store.load(pid))


@router.post("/api/projects/{pid}/cuts")
def manual_cut(pid: str, data: dict = Body(...)):
    s, e = float(data["s"]), float(data["e"])
    if e - s < 0.05:
        raise HTTPException(400, "Trecho muito curto")
    cid = f"manual-{int(time.time() * 1000)}"
    return view(_404(lambda: store.update(pid, lambda p: p.setdefault("overrides", {}).setdefault("manual", []).append(
        {"id": cid, "s": round(s, 3), "e": round(e, 3)}))))


@router.delete("/api/projects/{pid}/cuts/{cid}")
def delete_manual(pid: str, cid: str):
    def fn(p):
        ov = p.setdefault("overrides", {})
        ov["manual"] = [m for m in ov.get("manual", []) if m["id"] != cid]
    return view(_404(lambda: store.update(pid, fn)))

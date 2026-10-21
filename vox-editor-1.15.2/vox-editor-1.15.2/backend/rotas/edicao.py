"""Edição automática: cortes de silêncio, perfis, capítulos, palavras, cortes (clips) e prévias."""
from __future__ import annotations

from fastapi import APIRouter

from .comum import *  # noqa: F401,F403

router = APIRouter()


# ---------- edição automática 2.0: perfis e capítulos ----------

@router.get("/api/projects/{pid}/perfis")
def perfis_do_projeto(pid: str):
    """Os perfis da edição automática com a prévia do resultado de cada um neste vídeo (duração final e cortes)."""
    proj = _404(lambda: store.load(pid))
    out = []
    pronto = proj.get("status") == "pronto" and proj.get("words") is not None
    for k, pf in edits.PERFIS.items():
        item = {"id": k, "nome": pf["nome"], "desc": pf["desc"]}
        if pronto:
            try:
                st = edits.build_edit({**proj, "settings": edits.aplicar_perfil(proj.get("settings"), k)})["stats"]
                item.update(final=st["final"], removido=st["removed_s"], cortes=sum(st["counts"].values()))
            except Exception:
                pass
        out.append(item)
    return {"atual": edits.perfil_atual(proj.get("settings")), "original": (proj.get("media") or {}).get("duration", 0),
            "perfis": out}


@router.post("/api/projects/{pid}/perfil")
def aplicar_perfil(pid: str, data: dict = Body(...)):
    perfil = str(data.get("perfil") or "")
    if perfil not in edits.PERFIS:
        raise HTTPException(400, "Perfil desconhecido")
    proj = _404(lambda: store.update(pid, lambda p: p.update(settings=edits.aplicar_perfil(p.get("settings"), perfil))))
    if data.get("padrao"):  # projetos novos já nascem com este perfil
        cfg = store.load_config()
        d = cfg.get("defaults") or {}
        for sec, vals in edits.PERFIS[perfil]["settings"].items():
            d[sec] = {**(d.get(sec) or {}), **vals}
        store.save_config({"defaults": d})
    return view(proj)


@router.get("/api/projects/{pid}/capitulos")
def ver_capitulos(pid: str):
    return _capitulos_view(_404(lambda: store.load(pid)))


@router.post("/api/projects/{pid}/capitulos")
def gerar_capitulos(pid: str, data: dict = Body(default={})):
    proj = _404(lambda: store.load(pid))
    ai = store.load_config().get("ai") if data.get("ia", True) else None
    try:
        res = capitulos.gerar(proj, ai)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    res["criado"] = time.time()
    proj = store.update(pid, lambda p: p.update(capitulos=res))
    return _capitulos_view(proj)


@router.put("/api/projects/{pid}/capitulos")
def salvar_capitulos(pid: str, data: dict = Body(...)):
    itens = []
    for it in data.get("itens") or []:
        try:
            t = float(it["t"])
        except (KeyError, TypeError, ValueError):
            continue
        titulo = str(it.get("titulo") or "").strip()[:80]
        if titulo:
            itens.append({"t": round(max(0.0, t), 2), "titulo": titulo})

    def fn(p):
        cap = p.get("capitulos") or {}
        cap["itens"] = sorted(itens, key=lambda x: x["t"])
        p["capitulos"] = cap
    return _capitulos_view(_404(lambda: store.update(pid, fn)))


@router.post("/api/projects/{pid}/reset")
def reset(pid: str):
    return view(_404(lambda: store.update(pid, lambda p: p.update(overrides={"restored": [], "manual": []}))))


@router.put("/api/projects/{pid}/words/{idx}")
def edit_word(pid: str, idx: int, data: dict = Body(...)):
    def fn(p):
        if 0 <= idx < len(p.get("words", [])):
            p["words"][idx]["w"] = str(data.get("w", "")).strip()[:60]
    return view(_404(lambda: store.update(pid, fn)))


@router.put("/api/projects/{pid}/clips/{clip_id}")
def edit_clip(pid: str, clip_id: str, data: dict = Body(...)):
    def fn(p):
        for c in p.get("clips", []):
            if c["id"] == clip_id:
                if "segments" in data and isinstance(data["segments"], list):
                    segs = [[round(float(a), 2), round(float(b), 2)] for a, b in data["segments"] if float(b) - float(a) > 0.3]
                    if segs:
                        c["segments"] = segs
                for k in ("title", "hook", "post", "kicker"):
                    if k in data:
                        c[k] = str(data[k])[:600]
                if "pinned" in data:
                    c["pinned"] = bool(data["pinned"])
                if isinstance(data.get("redes"), dict):  # textos por rede editados à mão
                    c["redes"] = redes.normalizar(data["redes"], c.get("redes") or {})
                    c["redes_fonte"] = "editado"
    return view(_404(lambda: store.update(pid, fn)))


@router.get("/api/projects/{pid}/clips/{clip_id}/redes")
def ver_redes(pid: str, clip_id: str):
    """Título e legenda pronta (com hashtags) de cada rede — usado no diálogo Publicar."""
    return _redes_view(_corte_e_texto(pid, clip_id)[1])


@router.post("/api/projects/{pid}/clips/{clip_id}/redes")
def refazer_redes(pid: str, clip_id: str, data: dict = Body(default={})):
    """ia=true: o Claude reescreve os textos das 4 redes (centavos). ia=false: volta às sugestões automáticas."""
    proj, clip, texto = _corte_e_texto(pid, clip_id)
    novo = None
    if data.get("ia"):
        ai = store.load_config().get("ai") or {}
        if ai.get("provider") in (None, "none") or not ai.get("api_key"):
            raise HTTPException(400, "Ligue uma IA (Claude ou compatível) em Inteligência artificial para reescrever com IA.")
        instr = ((proj.get("settings") or {}).get("studio") or {}).get("instructions") or ""
        try:
            novo = redes.normalizar(redes.com_ia(clip, texto, ai, instr), clip.get("redes") or {})
        except RuntimeError as e:
            raise HTTPException(400, str(e))

    def fn(p):
        for c in p.get("clips", []):
            if c["id"] == clip_id:
                if novo:
                    c["redes"], c["redes_fonte"] = novo, "ia"
                else:
                    c.pop("redes", None)
                    c.pop("redes_fonte", None)
    v = view(store.update(pid, fn))
    clip = next((c for c in v.get("clips") or [] if c["id"] == clip_id), {})
    return {"projeto": v, **_redes_view(clip)}


@router.delete("/api/projects/{pid}/clips/{clip_id}")
def delete_clip(pid: str, clip_id: str):
    return view(_404(lambda: store.update(pid, lambda p: p.update(clips=[c for c in p.get("clips", []) if c["id"] != clip_id]))))


@router.post("/api/projects/{pid}/clips/generate")
def generate_clips(pid: str, data: dict = Body(default={})):
    _404(lambda: store.load(pid))
    append = bool(data.get("append"))
    jobs.submit("cortes", pid, lambda pr: pipeline.regenerate_clips(pid, pr, keep_old=append), label="Gerando cortes")
    return view(store.load(pid))


@router.post("/api/projects/{pid}/clips/{clip_id}/render")
def render_clip(pid: str, clip_id: str, data: dict = Body(default={})):
    proj = _404(lambda: store.load(pid))
    clip = next((c for c in proj.get("clips", []) if c["id"] == clip_id), None)
    if not clip:
        raise HTTPException(404, "Corte não encontrado")
    jobs.submit("render", pid, lambda pr: pipeline.render_clip(pid, clip_id, data, pr), queue="render",
                label=clip.get("title", "Corte")[:40])
    return view(store.load(pid))


@router.post("/api/projects/{pid}/clips/render-all")
def render_all(pid: str, data: dict = Body(default={})):
    proj = _404(lambda: store.load(pid))
    ids = data.get("ids") or [c["id"] for c in proj.get("clips", [])]
    for c in proj.get("clips", []):
        if c["id"] in ids:
            cid = c["id"]
            jobs.submit("render", pid, lambda pr, cid=cid: pipeline.render_clip(pid, cid, data, pr), queue="render",
                        label=c.get("title", "Corte")[:40])
    return view(store.load(pid))


@router.get("/api/projects/{pid}/clips/{clip_id}/framing")
def clip_framing(pid: str, clip_id: str):
    return _404(lambda: pipeline.clip_framing(pid, clip_id))


@router.get("/api/projects/{pid}/thumb")
def thumb(pid: str, t: float, vertical: int = 1, layout: str = "face"):
    try:
        f = pipeline.thumbnail(pid, t, bool(vertical), layout if layout in ("face", "center", "blur") else "face")
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, str(e)[:200])
    return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})


@router.get("/api/projects/{pid}/frame-preview")
def frame_preview(pid: str, layout: str = "cheia", clip: str = "", v: str = ""):
    try:
        f = pipeline.frame_still(pid, layout, None, clip or None)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, str(e)[:300])
    return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})


@router.get("/api/projects/{pid}/clips/{clip_id}/cover")
def clip_cover(pid: str, clip_id: str):
    """Capa (thumbnail) 1080×1920 do corte: melhor quadro + tarja + título + selo, sem legenda."""
    proj = _404(lambda: store.load(pid))
    clip = next((c for c in proj.get("clips", []) if c["id"] == clip_id), None)
    if not clip:
        raise HTTPException(404, "Corte não encontrado")
    st = edits.merged_settings(proj.get("settings"))["studio"]
    layout = st.get("frame", "cheia")
    try:
        f = pipeline.frame_still(pid, layout, pipeline.cover_time(proj, clip), clip_id, subs=False, full=True)
    except Exception as e:
        raise HTTPException(500, str(e)[:300])
    name = pipeline._slug(clip.get("title", "capa")) + "-capa.jpg"
    return FileResponse(f, media_type="image/jpeg", filename=name)

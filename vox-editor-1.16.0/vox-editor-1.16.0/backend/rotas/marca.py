"""Marca (logo e ícones), músicas de fundo e modelos padrão."""
from __future__ import annotations

from fastapi import APIRouter

from .comum import *  # noqa: F401,F403

router = APIRouter()


@router.put("/api/brand")
def brand_salvar(data: dict = Body(...)):
    """v1.16: salva os campos da marca de quem está usando (o responsável ou a conta Igreja)."""
    if not (contas.manda_em_tudo() or contas.conta_propria()):
        raise HTTPException(403, "Só o responsável pela conta do VOX Editor pode mudar a marca.")
    store.salvar_marca(data if isinstance(data, dict) else {})
    from .sistema import get_settings
    return get_settings()


@router.post("/api/brand/logo")
async def brand_logo(request: Request):
    data = await request.body()
    if not data:
        raise HTTPException(400, "Arquivo vazio")
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(413, "Logo muito grande (máx. 8 MB)")
    tmp = store.marca_dir() / "upload.bin"
    tmp.write_bytes(data)
    out = store.marca_dir() / "logo.png"
    try:  # converte qualquer imagem para PNG com transparência, no máximo 600 px
        ff.run([ff.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(tmp), "-frames:v", "1",
                "-vf", "scale='min(600,iw)':-2:flags=lanczos,format=rgba", str(out)])
    except Exception:
        raise HTTPException(400, "Não consegui ler a imagem do logo (use PNG ou JPG)")
    finally:
        tmp.unlink(missing_ok=True)
    store.salvar_marca({"logo": "logo.png"})
    return {"ok": True}


@router.delete("/api/brand/logo")
def brand_logo_delete():
    (store.marca_dir() / "logo.png").unlink(missing_ok=True)
    store.salvar_marca({"logo": ""})
    return {"ok": True}


@router.get("/api/brand/logo")
def brand_logo_get():
    f = store.marca_dir() / "logo.png"
    if not f.exists():
        raise HTTPException(404, "Sem logo")
    return FileResponse(f, media_type="image/png", headers={"Cache-Control": "no-cache"})


@router.post("/api/brand/icon/{net}")
async def brand_icon(net: str, request: Request):
    """Ícone oficial de uma rede (o usuário baixa do kit de marca da própria rede)."""
    if net not in socials.NETS:
        raise HTTPException(404, "Rede desconhecida")
    data = await request.body()
    if not data or len(data) > 5 * 1024 * 1024:
        raise HTTPException(400, "Envie uma imagem de até 5 MB")
    tmp = store.marca_dir() / "icones" / "upload.bin"
    tmp.write_bytes(data)
    try:
        ff.run([ff.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(tmp), "-frames:v", "1",
                "-vf", "scale=256:256:force_original_aspect_ratio=decrease:flags=lanczos,format=rgba,"
                       "pad=256:256:(ow-iw)/2:(oh-ih)/2:color=black@0", str(store.marca_dir() / "icones" / f"{net}.png")])
    except Exception:
        raise HTTPException(400, "Não consegui ler a imagem (use PNG ou JPG)")
    finally:
        tmp.unlink(missing_ok=True)
    return {"ok": True}


@router.delete("/api/brand/icon/{net}")
def brand_icon_delete(net: str):
    if net in socials.NETS:
        (store.marca_dir() / "icones" / f"{net}.png").unlink(missing_ok=True)
    return {"ok": True}


@router.get("/api/brand/icon/{net}")
def brand_icon_get(net: str):
    f = store.marca_dir() / "icones" / f"{net}.png"
    if net not in socials.NETS or not f.exists():
        raise HTTPException(404, "Sem ícone")
    return FileResponse(f, media_type="image/png", headers={"Cache-Control": "no-cache"})


@router.get("/api/musicas")
def musicas():
    pipeline.MUSICAS.mkdir(parents=True, exist_ok=True)
    out = []
    for f in sorted(pipeline.MUSICAS.iterdir()):
        if f.is_file() and f.suffix.lower() in _AUDIO_OK:
            try:
                dur = ff.probe(str(f)).get("duration", 0)
            except Exception:
                dur = 0
            out.append({"nome": f.name, "duracao": round(dur or 0, 1), "tamanho": f.stat().st_size})
    return out


@router.post("/api/musicas")
async def musica_enviar(request: Request):
    from urllib.parse import unquote
    nome = re.sub(r"[\\/:*?\"<>|]+", "_", unquote(request.headers.get("x-filename", "musica.mp3"))).strip()
    if not nome or nome.startswith(".") or Path(nome).suffix.lower() not in _AUDIO_OK:
        raise HTTPException(400, "Envie uma música em MP3, M4A, WAV, OGG ou FLAC.")
    pipeline.MUSICAS.mkdir(parents=True, exist_ok=True)
    dest = pipeline.MUSICAS / nome
    size = 0
    with open(dest, "wb") as fh:
        async for chunk in request.stream():
            size += len(chunk)
            if size > 60 * 1024 * 1024:
                fh.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, "Música muito grande (máx. 60 MB)")
            fh.write(chunk)
    try:
        ff.probe(str(dest))
    except Exception:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "Não consegui ler esse arquivo de áudio.")
    return musicas()


@router.get("/api/musicas/{nome}")
def musica_ouvir(nome: str):
    f = pipeline.musica_path(nome)
    if not f:
        raise HTTPException(404, "Música não encontrada")
    return FileResponse(f)


@router.delete("/api/musicas/{nome}")
def musica_apagar(nome: str):
    f = pipeline.musica_path(nome)
    if f:
        Path(f).unlink(missing_ok=True)
    return musicas()


# ---------- modelos padrão ----------

@router.get("/api/defaults")
def get_defaults():
    d = store.load_config().get("defaults") or {}
    ready = [p for p in store.list_projects() if p["status"] == "pronto" and p.get("has_video")]
    return {"defaults": edits.merged_settings(d), "preview_project": ready[0]["id"] if ready else None}


@router.put("/api/defaults")
def put_defaults(data: dict = Body(...)):
    cfg = store.load_config()
    d = cfg.get("defaults") or {}
    for sec in ("subtitles", "studio", "audio"):
        if isinstance(data.get(sec), dict):
            d[sec] = {**(d.get(sec) or {}), **data[sec]}
    store.save_config({"defaults": d})
    n = 0
    if data.get("apply_all"):
        for p in store.list_projects():
            def fn(proj):
                st = proj.setdefault("settings", {})
                for sec in ("subtitles", "studio", "audio"):
                    if isinstance(data.get(sec), dict):
                        st[sec] = {**(st.get(sec) or {}), **data[sec]}
            store.update(p["id"], fn)
            n += 1
    return {"ok": True, "applied": n, **get_defaults()}

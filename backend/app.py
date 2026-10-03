"""Servidor do Editor IA: API + painel. Roda no PC (localhost) ou numa VPS (versão online)."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import threading
import time
import webbrowser
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from .core import importer, jobs, pipeline, publish, store
from .engine import edits, frames, platforms, reframe, socials, subtitles, transcribe
from .engine import ffmpeg_tools as ff

VERSION = "0.8.1"
FRONT = store.ROOT / "frontend"
PASSWORD = os.environ.get("APP_PASSWORD", "")
SECRET = os.environ.get("APP_SECRET") or secrets.token_hex(16)
MAX_UPLOAD_GB = float(os.environ.get("MAX_UPLOAD_GB", "20"))
HTTPS = (os.environ.get("PUBLIC_URL") or "").startswith("https://")
_FALHAS: dict[str, list[float]] = {}  # tentativas de senha erradas por IP (versão online)

app = FastAPI(title="Editor IA", version=VERSION)


@app.on_event("startup")
def _start_scheduler():
    publish.start()  # fila de autopostagem roda em segundo plano enquanto o programa estiver aberto
    # trabalhos que estavam no meio quando o programa foi fechado ficam com aviso e botão "Tentar novamente"
    for p in store.list_projects():
        if p.get("status") in ("baixando", "processando", "na fila"):
            try:
                store.update(p["id"], lambda x: x.update(status="erro", progress={"pct": 0, "msg":
                             "Interrompido porque o programa foi fechado. Clique em Tentar novamente."}))
            except Exception:
                pass


def _token() -> str:
    return hmac.new(SECRET.encode(), PASSWORD.encode(), hashlib.sha256).hexdigest()


@app.middleware("http")
async def auth(request: Request, call_next):
    """Senha opcional para a versão online (variável APP_PASSWORD). No PC não é usada."""
    if PASSWORD and request.url.path.startswith("/api/") and request.url.path not in ("/api/login", "/api/status"):
        if not hmac.compare_digest(request.cookies.get("editor_auth", ""), _token()):
            return JSONResponse({"detail": "login necessário"}, status_code=401)
    return await call_next(request)


def _404(fn):
    try:
        return fn()
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


def view(proj: dict) -> dict:
    """Projeto + edição calculada, pronto para o painel."""
    out = dict(proj)
    out["settings"] = edits.merged_settings(proj.get("settings"))
    if proj.get("media") and proj.get("status") == "pronto":
        ed = edits.build_edit(proj)
        out["edit"] = {k: ed[k] for k in ("cuts", "ducks", "keeps", "stats")}
        out["stats"] = ed["stats"]
        plat = platforms.get(out["settings"]["studio"].get("platform"))
        clips = []
        for c in proj.get("clips", []):
            c = dict(c)
            ks = edits.intersect(ed["keeps"], pipeline.clip_segments(proj, c))
            c["keeps"] = ks
            c["final"] = round(sum(e - s for s, e in ks), 1)
            c["raw"] = round(sum(e - s for s, e in c["segments"]), 1)
            c["parts"] = (int(c["final"] // max(1, plat["max"] - 0.5)) + 1) if plat.get("split") and plat.get("max") \
                and c["final"] > plat["max"] + 0.5 else 1
            clips.append(c)
        out["clips"] = clips
    out["jobs"] = jobs.for_project(proj["id"])
    return out


# ---------- sistema / login / configurações ----------

@app.get("/api/status")
def status():
    try:
        encs = ff.available_encoders()
        ff_ok = True
    except Exception:
        encs, ff_ok = {}, False
    return {"version": VERSION, "ffmpeg": ff_ok, "encoders": encs,
            "encoder": ff.best_encoder() if ff_ok else None, "local_transcription": transcribe.local_available(),
            "gpu_transcription": transcribe._cuda_available(), "login_required": bool(PASSWORD),
            "name": store.load_config()["app"].get("name", "Editor IA"),
            "tagline": store.load_config()["app"].get("tagline", ""),
            "accent": store.load_config()["app"].get("accent", "#FF8A3D"),
            "app_logo": (store.BRAND_DIR / "app_logo.png").exists()}


@app.get("/api/meta")
def meta():
    fonts = sorted({f.stem for f in store.FONTS.glob("*.[ot]tf")})
    return {"platforms": platforms.PLATFORMS, "durations": platforms.DURATIONS,
            "styles": {k: {"name": v["name"], "desc": v["desc"], "font": v["font"]} for k, v in subtitles.STYLES.items()},
            "style_defaults": subtitles.STYLES, "fonts": subtitles.FONTS, "font_files": fonts,
            "face_detection": reframe.available(), "layouts": frames.LAYOUTS,
            "geometry": {k: frames.geometry(k, 1080, 1920) for k in frames.LAYOUTS},
            "socials": socials.NETS, "platform_net": socials.PLATFORM_NET,
            "icons": sorted(f.stem for f in (store.BRAND_DIR / "icones").glob("*.png"))}


@app.post("/api/login")
def login(request: Request, data: dict = Body(...)):
    # na internet: depois de 5 senhas erradas em 15 minutos, o IP espera antes de tentar de novo
    ip = request.client.host if request.client else "?"
    agora = time.time()
    falhas = [t for t in _FALHAS.get(ip, []) if agora - t < 900]
    if len(falhas) >= 5:
        espera = int(900 - (agora - falhas[0])) // 60 + 1
        raise HTTPException(429, f"Muitas tentativas erradas. Tente de novo em {espera} min.")
    if not PASSWORD or not hmac.compare_digest(str(data.get("password", "")), PASSWORD):
        falhas.append(agora)
        _FALHAS[ip] = falhas
        time.sleep(1)
        raise HTTPException(401, "Senha incorreta")
    _FALHAS.pop(ip, None)
    r = JSONResponse({"ok": True})
    r.set_cookie("editor_auth", _token(), httponly=True, samesite="lax", secure=HTTPS,
                 max_age=60 * 60 * 24 * 30)
    return r


@app.get("/api/settings")
def get_settings():
    return store.public_config(store.load_config())


@app.put("/api/settings")
def put_settings(data: dict = Body(...)):
    return store.public_config(store.save_config(data))


@app.post("/api/settings/test-ai")
def test_ai():
    from .engine.smartcuts import _call_llm
    cfg = store.load_config()["ai"]
    if cfg.get("provider") in (None, "none"):
        return {"ok": True, "msg": "Sem IA externa: os cortes usam a análise local."}
    try:
        txt = _call_llm("Responda apenas: OK", cfg)
        return {"ok": True, "msg": f"Conectado. Resposta: {txt.strip()[:40]}"}
    except Exception as e:
        return {"ok": False, "msg": str(e)[:300]}


# ---------- projetos ----------

def _mini_timeline(keeps: list, dur: float, n: int = 48) -> list:
    """Linha do tempo resumida (trechos mantidos, de 0 a 1) para o cartão do projeto."""
    if not dur:
        return []
    out = []
    for s, e in keeps:
        a, b = round(s / dur, 4), round(e / dur, 4)
        if out and a - out[-1][1] < 0.004:
            out[-1][1] = b
        else:
            out.append([a, b])
    while len(out) > n:  # junta os buracos menores
        i = min(range(len(out) - 1), key=lambda k: out[k + 1][0] - out[k][1])
        out[i][1] = out.pop(i + 1)[1]
    return out


@app.get("/api/projects")
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


@app.patch("/api/projects/{pid}")
def rename_project(pid: str, data: dict = Body(...)):
    name = str(data.get("name", "")).strip()[:120]
    if not name:
        raise HTTPException(400, "Dê um nome ao projeto")
    return view(_404(lambda: store.update(pid, lambda p: p.update(name=name))))


@app.get("/api/projects/{pid}/poster")
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


@app.get("/api/renders")
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


@app.get("/api/projects/{pid}/renders/{name}/thumb")
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


@app.get("/api/dashboard")
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
    return {"projects": len(ps), "seconds_in": round(total_in), "removed": round(removed), "clips": clips,
            "renders": renders, "storage": store.folder_size(store.PROJECTS), "free": free}


@app.post("/api/maintenance/clean")
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
    return {"freed": freed}


@app.post("/api/app/logo")
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


@app.delete("/api/app/logo")
def app_logo_delete():
    (store.BRAND_DIR / "app_logo.png").unlink(missing_ok=True)
    return {"ok": True}


@app.get("/api/app/logo")
def app_logo_get():
    f = store.BRAND_DIR / "app_logo.png"
    if not f.exists():
        raise HTTPException(404, "Sem logo")
    return FileResponse(f, media_type="image/png", headers={"Cache-Control": "no-cache"})


@app.post("/api/projects")
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

    def work(progress):
        try:
            return pipeline.analyze(pid, progress)
        except Exception as e:
            pipeline._set(pid, "erro", None, str(e))
            raise

    jobs.submit("analise", pid, work, label="Análise")
    return view(store.load(pid))


def _start_analysis(pid: str) -> None:
    def work(progress):
        try:
            return pipeline.analyze(pid, progress)
        except Exception as e:
            pipeline._set(pid, "erro", None, str(e))
            raise
    store.update(pid, lambda p: p.update(status="na fila", progress={"pct": 0, "msg": "Na fila para análise…"}))
    jobs.submit("analise", pid, work, label="Análise")


def _import_job(pid: str, kind: str, fetch) -> None:
    """Baixa/copia em segundo plano (fila própria, não trava as análises) e depois analisa."""
    def work(progress):
        def step(pct, msg):
            progress(pct, msg)
            pipeline._set(pid, "baixando", pct, msg)
        try:
            path, title = fetch(step)
        except Exception as e:
            pipeline._set(pid, "erro", None, str(e))
            raise
        def upd(p):
            p.update(source=path.name, size=path.stat().st_size)
            if title:
                p["name"] = title[:120]
        store.update(pid, upd)
        _start_analysis(pid)
        return {"file": path.name}
    jobs.submit(kind, pid, work, queue="download", label="Download" if kind == "download" else "Importação")


@app.post("/api/projects/link")
def import_link(data: dict = Body(...)):
    """Importa pelo link (YouTube e outros sites). Quem baixa é o próprio programa: sem API e sem custo."""
    try:
        url = importer.clean_url(data.get("url", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))
    proj = store.new_project("Vídeo do link")
    pid = proj["id"]
    store.update(pid, lambda p: p.update(status="baixando", link=url, progress={"pct": 0, "msg": "Conectando ao site do vídeo…"}))
    _import_job(pid, "download", lambda step: importer.download(pid, url, step, MAX_UPLOAD_GB))
    return view(store.load(pid))


def _is_local(request: Request) -> bool:
    return not PASSWORD and (request.client.host if request.client else "") in ("127.0.0.1", "::1", "localhost")


@app.post("/api/projects/path")
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


@app.get("/api/projects/{pid}")
def project(pid: str):
    proj = _404(lambda: store.load(pid))
    if proj.get("status") == "pronto" and (proj.get("analysis") or {}).get("v", 0) < 3:
        proj = pipeline.reanalyze(pid)  # projetos de versões anteriores ganham as emendas inteligentes
    return view(proj)


@app.delete("/api/projects/{pid}")
def delete(pid: str):
    _404(lambda: store.load(pid))
    store.delete_project(pid)
    return {"ok": True}


@app.post("/api/projects/{pid}/reprocess")
def reprocess(pid: str):
    proj = _404(lambda: store.load(pid))
    src = proj.get("source")
    if (not src or not (store.pdir(pid) / src).exists()) and proj.get("link"):  # download não terminou: baixa de novo
        url = proj["link"]
        store.update(pid, lambda p: p.update(status="baixando", progress={"pct": 0, "msg": "Conectando ao site do vídeo…"}))
        _import_job(pid, "download", lambda step: importer.download(pid, url, step, MAX_UPLOAD_GB))
        return view(store.load(pid))
    store.update(pid, lambda p: p.update(status="na fila", progress={"pct": 0, "msg": "Na fila para análise…"}))

    def work(progress):
        try:
            return pipeline.analyze(pid, progress)
        except Exception as e:
            pipeline._set(pid, "erro", None, str(e))
            raise

    jobs.submit("analise", pid, work, label="Nova análise")
    return view(store.load(pid))


@app.get("/api/projects/{pid}/wave")
def wave(pid: str):
    f = store.pdir(pid) / "onda.json"
    if not f.exists():
        return []
    return Response(f.read_text(encoding="utf-8"), media_type="application/json")


@app.get("/api/projects/{pid}/media")
def media(pid: str):
    proj = _404(lambda: store.load(pid))
    f = store.pdir(pid) / (proj.get("preview") or proj["source"])
    if not f.exists():
        raise HTTPException(404, "Mídia não encontrada")
    return FileResponse(f)


@app.put("/api/projects/{pid}/settings")
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


@app.post("/api/projects/{pid}/cuts/{cid}/toggle")
def toggle_cut(pid: str, cid: str):
    def fn(p):
        r = p.setdefault("overrides", {}).setdefault("restored", [])
        if cid in r:
            r.remove(cid)
        else:
            r.append(cid)
    return view(_404(lambda: store.update(pid, fn)))


@app.post("/api/projects/{pid}/cleanup-ai")
def cleanup_ai(pid: str):
    _404(lambda: store.load(pid))
    jobs.submit("limpeza", pid, lambda pr: pipeline.ai_cleanup(pid, pr), label="Limpeza da fala com IA")
    return view(store.load(pid))


@app.post("/api/projects/{pid}/cuts")
def manual_cut(pid: str, data: dict = Body(...)):
    s, e = float(data["s"]), float(data["e"])
    if e - s < 0.05:
        raise HTTPException(400, "Trecho muito curto")
    cid = f"manual-{int(time.time() * 1000)}"
    return view(_404(lambda: store.update(pid, lambda p: p.setdefault("overrides", {}).setdefault("manual", []).append(
        {"id": cid, "s": round(s, 3), "e": round(e, 3)}))))


@app.delete("/api/projects/{pid}/cuts/{cid}")
def delete_manual(pid: str, cid: str):
    def fn(p):
        ov = p.setdefault("overrides", {})
        ov["manual"] = [m for m in ov.get("manual", []) if m["id"] != cid]
    return view(_404(lambda: store.update(pid, fn)))


@app.post("/api/projects/{pid}/reset")
def reset(pid: str):
    return view(_404(lambda: store.update(pid, lambda p: p.update(overrides={"restored": [], "manual": []}))))


@app.put("/api/projects/{pid}/words/{idx}")
def edit_word(pid: str, idx: int, data: dict = Body(...)):
    def fn(p):
        if 0 <= idx < len(p.get("words", [])):
            p["words"][idx]["w"] = str(data.get("w", "")).strip()[:60]
    return view(_404(lambda: store.update(pid, fn)))


@app.put("/api/projects/{pid}/clips/{clip_id}")
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
    return view(_404(lambda: store.update(pid, fn)))


@app.delete("/api/projects/{pid}/clips/{clip_id}")
def delete_clip(pid: str, clip_id: str):
    return view(_404(lambda: store.update(pid, lambda p: p.update(clips=[c for c in p.get("clips", []) if c["id"] != clip_id]))))


@app.post("/api/projects/{pid}/clips/generate")
def generate_clips(pid: str, data: dict = Body(default={})):
    _404(lambda: store.load(pid))
    append = bool(data.get("append"))
    jobs.submit("cortes", pid, lambda pr: pipeline.regenerate_clips(pid, pr, keep_old=append), label="Gerando cortes")
    return view(store.load(pid))


@app.post("/api/projects/{pid}/clips/{clip_id}/render")
def render_clip(pid: str, clip_id: str, data: dict = Body(default={})):
    proj = _404(lambda: store.load(pid))
    clip = next((c for c in proj.get("clips", []) if c["id"] == clip_id), None)
    if not clip:
        raise HTTPException(404, "Corte não encontrado")
    jobs.submit("render", pid, lambda pr: pipeline.render_clip(pid, clip_id, data, pr), queue="render",
                label=clip.get("title", "Corte")[:40])
    return view(store.load(pid))


@app.post("/api/projects/{pid}/clips/render-all")
def render_all(pid: str, data: dict = Body(default={})):
    proj = _404(lambda: store.load(pid))
    ids = data.get("ids") or [c["id"] for c in proj.get("clips", [])]
    for c in proj.get("clips", []):
        if c["id"] in ids:
            cid = c["id"]
            jobs.submit("render", pid, lambda pr, cid=cid: pipeline.render_clip(pid, cid, data, pr), queue="render",
                        label=c.get("title", "Corte")[:40])
    return view(store.load(pid))


@app.get("/api/projects/{pid}/clips/{clip_id}/framing")
def clip_framing(pid: str, clip_id: str):
    return _404(lambda: pipeline.clip_framing(pid, clip_id))


@app.get("/api/projects/{pid}/thumb")
def thumb(pid: str, t: float, vertical: int = 1, layout: str = "face"):
    try:
        f = pipeline.thumbnail(pid, t, bool(vertical), layout if layout in ("face", "center", "blur") else "face")
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, str(e)[:200])
    return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})


@app.get("/api/projects/{pid}/frame-preview")
def frame_preview(pid: str, layout: str = "cheia", clip: str = "", v: str = ""):
    try:
        f = pipeline.frame_still(pid, layout, None, clip or None)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, str(e)[:300])
    return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})


@app.get("/api/projects/{pid}/clips/{clip_id}/cover")
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


@app.post("/api/brand/logo")
async def brand_logo(request: Request):
    data = await request.body()
    if not data:
        raise HTTPException(400, "Arquivo vazio")
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(413, "Logo muito grande (máx. 8 MB)")
    tmp = store.BRAND_DIR / "upload.bin"
    tmp.write_bytes(data)
    out = store.BRAND_DIR / "logo.png"
    try:  # converte qualquer imagem para PNG com transparência, no máximo 600 px
        ff.run([ff.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(tmp), "-frames:v", "1",
                "-vf", "scale='min(600,iw)':-2:flags=lanczos,format=rgba", str(out)])
    except Exception:
        raise HTTPException(400, "Não consegui ler a imagem do logo (use PNG ou JPG)")
    finally:
        tmp.unlink(missing_ok=True)
    store.save_config({"brand": {"logo": "logo.png"}})
    return {"ok": True}


@app.delete("/api/brand/logo")
def brand_logo_delete():
    (store.BRAND_DIR / "logo.png").unlink(missing_ok=True)
    store.save_config({"brand": {"logo": ""}})
    return {"ok": True}


@app.get("/api/brand/logo")
def brand_logo_get():
    f = store.BRAND_DIR / "logo.png"
    if not f.exists():
        raise HTTPException(404, "Sem logo")
    return FileResponse(f, media_type="image/png", headers={"Cache-Control": "no-cache"})


@app.post("/api/brand/icon/{net}")
async def brand_icon(net: str, request: Request):
    """Ícone oficial de uma rede (o usuário baixa do kit de marca da própria rede)."""
    if net not in socials.NETS:
        raise HTTPException(404, "Rede desconhecida")
    data = await request.body()
    if not data or len(data) > 5 * 1024 * 1024:
        raise HTTPException(400, "Envie uma imagem de até 5 MB")
    tmp = store.BRAND_DIR / "icones" / "upload.bin"
    tmp.write_bytes(data)
    try:
        ff.run([ff.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(tmp), "-frames:v", "1",
                "-vf", "scale=256:256:force_original_aspect_ratio=decrease:flags=lanczos,format=rgba,"
                       "pad=256:256:(ow-iw)/2:(oh-ih)/2:color=black@0", str(store.BRAND_DIR / "icones" / f"{net}.png")])
    except Exception:
        raise HTTPException(400, "Não consegui ler a imagem (use PNG ou JPG)")
    finally:
        tmp.unlink(missing_ok=True)
    return {"ok": True}


@app.delete("/api/brand/icon/{net}")
def brand_icon_delete(net: str):
    if net in socials.NETS:
        (store.BRAND_DIR / "icones" / f"{net}.png").unlink(missing_ok=True)
    return {"ok": True}


@app.get("/api/brand/icon/{net}")
def brand_icon_get(net: str):
    f = store.BRAND_DIR / "icones" / f"{net}.png"
    if net not in socials.NETS or not f.exists():
        raise HTTPException(404, "Sem ícone")
    return FileResponse(f, media_type="image/png", headers={"Cache-Control": "no-cache"})


# ---------- modelos padrão ----------

@app.get("/api/defaults")
def get_defaults():
    d = store.load_config().get("defaults") or {}
    ready = [p for p in store.list_projects() if p["status"] == "pronto" and p.get("has_video")]
    return {"defaults": edits.merged_settings(d), "preview_project": ready[0]["id"] if ready else None}


@app.put("/api/defaults")
def put_defaults(data: dict = Body(...)):
    cfg = store.load_config()
    d = cfg.get("defaults") or {}
    for sec in ("subtitles", "studio"):
        if isinstance(data.get(sec), dict):
            d[sec] = {**(d.get(sec) or {}), **data[sec]}
    store.save_config({"defaults": d})
    n = 0
    if data.get("apply_all"):
        for p in store.list_projects():
            def fn(proj):
                st = proj.setdefault("settings", {})
                for sec in ("subtitles", "studio"):
                    if isinstance(data.get(sec), dict):
                        st[sec] = {**(st.get(sec) or {}), **data[sec]}
            store.update(p["id"], fn)
            n += 1
    return {"ok": True, "applied": n, **get_defaults()}


# ---------- autopostagem ----------

@app.get("/api/publish/status")
def publish_status():
    c = publish.cfg()
    apps = {}
    for app_name in ("youtube", "meta", "tiktok"):
        a = c.get(app_name) or {}
        apps[app_name] = {"client_id": a.get("client_id", ""), "secret_set": bool(a.get("client_secret"))}
    return {"networks": publish.public_status(), "apps": apps, "slots": c["slots"]}


@app.put("/api/publish/config")
def publish_config(data: dict = Body(...)):
    cfg = store.load_config()
    pub = cfg.get("publish") or {}
    for app_name in ("youtube", "meta", "tiktok"):
        if app_name in data and isinstance(data[app_name], dict):
            cur = pub.get(app_name) or {}
            if "client_id" in data[app_name]:
                cur["client_id"] = str(data[app_name]["client_id"]).strip()
            if data[app_name].get("client_secret"):
                cur["client_secret"] = str(data[app_name]["client_secret"]).strip()
            pub[app_name] = cur
    if isinstance(data.get("slots"), list):
        slots = []
        for sl in data["slots"][:20]:
            t = str(sl.get("time", "19:00"))[:5]
            days = [int(d) for d in sl.get("days", []) if 0 <= int(d) <= 6]
            if days and len(t) == 5 and t[2] == ":":
                slots.append({"days": sorted(set(days)), "time": t})
        pub["slots"] = slots
    store.save_config({"publish": pub})
    return publish_status()


def _redirect_uri(request: Request, app_name: str) -> str:
    base = (os.environ.get("PUBLIC_URL") or str(request.base_url)).rstrip("/")
    return f"{base}/api/oauth/{app_name}/callback"


@app.get("/api/oauth/{app_name}/start")
def oauth_start(app_name: str, request: Request, desk: str = ""):
    try:
        r = RedirectResponse(publish.auth_url(app_name, _redirect_uri(request, app_name)))
    except Exception as e:
        from urllib.parse import quote
        return RedirectResponse(f"/#/redes?erro={quote(str(e))}")
    if desk:  # login aberto no navegador a partir do programa do PC: no fim, mostra só "pode voltar ao programa"
        r.set_cookie("oauth_desk", "1", max_age=900, httponly=True, samesite="lax")
    return r


_DONE_PAGE = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>{title}</title><style>
body{{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;background:#0e0f13;color:#e9e9ee;
font-family:Segoe UI,system-ui,sans-serif}}div{{max-width:440px;text-align:center;padding:24px}}
h1{{font-size:22px;margin:0 0 10px;color:{color}}}p{{color:#a3a5b0;line-height:1.5;margin:0}}</style></head>
<body><div><h1>{title}</h1><p>{msg}</p></div></body></html>"""


def _oauth_done(request: Request, ok: bool, text: str, app_name: str = ""):
    from urllib.parse import quote
    import html as _h
    if request.cookies.get("oauth_desk"):
        title = "Conta conectada!" if ok else "Não deu certo"
        msg = ("Pode fechar esta aba e voltar ao programa. A conta já aparece em Redes sociais." if ok
               else _h.escape(text) + "<br><br>Feche esta aba, volte ao programa e tente conectar de novo.")
        r = Response(_DONE_PAGE.format(title=title, msg=msg, color="#4ade80" if ok else "#f87171"), media_type="text/html")
        r.delete_cookie("oauth_desk")
        return r
    return RedirectResponse(f"/#/redes?conectado={app_name}" if ok else f"/#/redes?erro={quote(text)}")


@app.get("/api/oauth/{app_name}/callback")
def oauth_callback(app_name: str, request: Request, code: str = "", state: str = "", error: str = "",
                   error_description: str = ""):
    if error or not code:
        return _oauth_done(request, False, error_description or error or "Login cancelado")
    if publish.check_state(state) != app_name:
        return _oauth_done(request, False, "Login expirado. Tente conectar de novo.")
    try:
        publish.finish_login(app_name, code, _redirect_uri(request, app_name))
    except Exception as e:
        return _oauth_done(request, False, str(e)[:300])
    return _oauth_done(request, True, "", app_name)


@app.post("/api/publish/page")
def publish_page(data: dict = Body(...)):
    publish.select_page(str(data.get("page_id", "")))
    return publish_status()


@app.delete("/api/publish/account/{app_name}")
def publish_disconnect(app_name: str):
    publish.remove_account(app_name)
    return publish_status()


@app.get("/api/publish/queue")
def publish_queue():
    names = {p["id"]: p["name"] for p in store.list_projects()}
    out = []
    for it in publish.queue():
        out.append({**it, "project_name": names.get(it["project"], "Projeto apagado")})
    return sorted(out, key=lambda x: -x["when"] if x["status"] in ("publicado", "erro", "cancelado") else x["when"])


@app.post("/api/publish/queue")
def publish_add(data: dict = Body(...)):
    pid, file = str(data.get("project", "")), str(data.get("file", ""))
    if "/" in file or "\\" in file or not (store.pdir(pid) / "renders" / file).exists():
        raise HTTPException(404, "Vídeo exportado não encontrado")
    nets = [n for n in data.get("nets", []) if n in publish.NETWORKS]
    if not nets:
        raise HTTPException(400, "Escolha pelo menos uma rede")
    status = publish.public_status()
    off = [publish.NETWORKS[n]["name"] for n in nets if not status[n]["connected"]]
    if off:
        raise HTTPException(400, "Conecte antes: " + ", ".join(off))
    mode = data.get("when", "slot")
    items = []
    for n in nets:
        if mode == "now":
            when = time.time()
        elif mode == "at":
            when = float(data.get("at") or time.time())
        else:
            when = publish.next_slot(n)
        items.append(publish.new_item(pid, file, n, when, str(data.get("caption", ""))[:2200],
                                      str(data.get("title", ""))[:100], data.get("privacy", "public"),
                                      str(data.get("label", ""))[:120]))
    publish.add(items)
    return {"items": items}


@app.delete("/api/publish/queue/{iid}")
def publish_remove(iid: str):
    with publish._lock:
        q = [it for it in publish.queue() if not (it["id"] == iid and it["status"] != "publicando")]
        publish._save_queue(q)
    return {"ok": True}


@app.post("/api/publish/queue/{iid}/retry")
def publish_retry(iid: str):
    publish.update_item(iid, status="agendado", when=time.time(), error="", msg="", pct=0)
    return {"ok": True}


@app.put("/api/publish/queue/{iid}")
def publish_edit(iid: str, data: dict = Body(...)):
    fields = {}
    if "when" in data:
        fields["when"] = float(data["when"])
    for k in ("caption", "title"):
        if k in data:
            fields[k] = str(data[k])[:2200]
    publish.update_item(iid, **fields)
    return {"ok": True}


@app.get("/api/projects/{pid}/subtitle-preview")
def subtitle_preview(pid: str, style: str = "", t: float | None = None, v: str = ""):
    try:
        f = pipeline.subtitle_preview(pid, style, t)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, str(e)[:300])
    return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})


@app.post("/api/projects/{pid}/render")
def render_full(pid: str, data: dict = Body(default={})):
    _404(lambda: store.load(pid))
    jobs.submit("render", pid, lambda pr: pipeline.render_full(pid, data, pr), queue="render", label="Vídeo editado")
    return view(store.load(pid))


@app.post("/api/projects/{pid}/clips/{clip_id}/render")
def render_clip(pid: str, clip_id: str, data: dict = Body(default={})):
    _404(lambda: store.load(pid))
    jobs.submit("render", pid, lambda pr: pipeline.render_clip(pid, clip_id, data, pr), queue="render",
                label=f"Corte {clip_id.replace('clip', '')}")
    return view(store.load(pid))


@app.get("/api/projects/{pid}/renders/{name}")
def get_render(pid: str, name: str):
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(400, "Nome inválido")
    f = store.pdir(pid) / "renders" / name
    if not f.exists():
        raise HTTPException(404, "Arquivo não encontrado")
    return FileResponse(f, filename=name)


@app.delete("/api/projects/{pid}/renders/{name}")
def del_render(pid: str, name: str):
    if "/" in name or "\\" in name:
        raise HTTPException(400, "Nome inválido")
    (store.pdir(pid) / "renders" / name).unlink(missing_ok=True)
    return view(store.update(pid, lambda p: p.update(renders=[r for r in p.get("renders", []) if r["file"] != name])))


@app.get("/api/projects/{pid}/export/{fmt}")
def export(pid: str, fmt: str):
    try:
        content, fname, mime = _404(lambda: pipeline.export(pid, fmt))
    except ValueError as e:
        raise HTTPException(400, str(e))
    from urllib.parse import quote
    return Response(content, media_type=mime + "; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(fname)}"})


@app.get("/api/jobs/{pid}")
def project_jobs(pid: str):
    return jobs.for_project(pid)


app.mount("/fontes", StaticFiles(directory=str(store.FONTS)), name="fontes")
app.mount("/", StaticFiles(directory=str(FRONT), html=True), name="painel")


def main():
    import uvicorn
    if os.name != "nt" and os.environ.get("EDITOR_NICE"):
        try:  # no servidor, o editor cede a vez para os outros sistemas quando eles precisam do processador
            os.nice(int(os.environ["EDITOR_NICE"]))
        except Exception:
            pass
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8765"))
    if host in ("127.0.0.1", "localhost") and os.environ.get("NO_BROWSER") != "1":
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    print(f"\n  Editor IA rodando em http://{'127.0.0.1' if host == '0.0.0.0' else host}:{port}\n"
          f"  (feche esta janela para desligar)\n")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()

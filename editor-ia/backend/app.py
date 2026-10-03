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
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .core import jobs, pipeline, store
from .engine import edits, transcribe
from .engine import ffmpeg_tools as ff

VERSION = "0.1.0"
FRONT = store.ROOT / "frontend"
PASSWORD = os.environ.get("APP_PASSWORD", "")
SECRET = os.environ.get("APP_SECRET") or secrets.token_hex(16)
MAX_UPLOAD_GB = float(os.environ.get("MAX_UPLOAD_GB", "20"))

app = FastAPI(title="Editor IA", version=VERSION)


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
            "name": store.load_config()["app"].get("name", "Editor IA")}


@app.post("/api/login")
def login(data: dict = Body(...)):
    if not PASSWORD or not hmac.compare_digest(str(data.get("password", "")), PASSWORD):
        raise HTTPException(401, "Senha incorreta")
    r = JSONResponse({"ok": True})
    r.set_cookie("editor_auth", _token(), httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
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

@app.get("/api/projects")
def projects():
    out = store.list_projects()
    for p in out:
        if p["status"] == "pronto":
            try:
                p["final"] = edits.build_edit(store.load(p["id"]))["stats"]["final"]
            except Exception:
                pass
    return out


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


@app.get("/api/projects/{pid}")
def project(pid: str):
    return view(_404(lambda: store.load(pid)))


@app.delete("/api/projects/{pid}")
def delete(pid: str):
    _404(lambda: store.load(pid))
    store.delete_project(pid)
    return {"ok": True}


@app.post("/api/projects/{pid}/reprocess")
def reprocess(pid: str):
    _404(lambda: store.load(pid))
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
                for k in ("s", "e"):
                    if k in data:
                        c[k] = round(float(data[k]), 2)
                if "title" in data:
                    c["title"] = str(data["title"])[:90]
    return view(_404(lambda: store.update(pid, fn)))


@app.post("/api/projects/{pid}/clips/regenerate")
def regen_clips(pid: str):
    _404(lambda: store.load(pid))
    jobs.submit("cortes", pid, lambda pr: pipeline.regenerate_clips(pid, pr), label="Cortes inteligentes")
    return view(store.load(pid))


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


app.mount("/", StaticFiles(directory=str(FRONT), html=True), name="painel")


def main():
    import uvicorn
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8765"))
    if host in ("127.0.0.1", "localhost") and os.environ.get("NO_BROWSER") != "1":
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    print(f"\n  Editor IA rodando em http://{'127.0.0.1' if host == '0.0.0.0' else host}:{port}\n"
          f"  (feche esta janela para desligar)\n")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()

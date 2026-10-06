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

import httpx

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .core import bancos, destinos, importer, jobs, legal, montagem, online, pacote, pipeline, publish, store, trilhas
from .engine import avaliacao, capitulos, edits, frames, platforms, redes, reframe, socials, subtitles, transcribe
from .engine import ffmpeg_tools as ff

VERSION = "1.6.0"
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


# Senha: na versão online vem do instalador (APP_PASSWORD); no PC é opcional, criada em Configurações.
INTERNO = secrets.token_hex(16)  # a janela do PC (mesmo processo) usa este código para baixar arquivos
_LIVRES = ("/api/login", "/api/status", "/api/meta")
_RE_OAUTH = re.compile(r"^/api/oauth/[a-z]+/(start|callback)$")  # o login das redes abre no navegador


def _senha_base() -> str:
    return PASSWORD or store.password_hash()


def _token() -> str:
    return hmac.new(SECRET.encode(), _senha_base().encode(), hashlib.sha256).hexdigest()


def _local(request: Request) -> bool:
    return (request.client.host if request.client else "") in ("127.0.0.1", "::1", "localhost")


@app.middleware("http")
async def sem_cache_da_tela(request: Request, call_next):
    """A tela (HTML, JS, CSS) é sempre conferida com o servidor: depois de atualizar, a versão nova aparece na hora."""
    resp = await call_next(request)
    p = request.url.path
    if not p.startswith("/api/") and (p == "/" or p.endswith((".html", ".js", ".css", ".webmanifest"))):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.middleware("http")
async def auth(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and path not in _LIVRES and not _RE_OAUTH.match(path) \
            and not path.startswith("/api/publico/") and _senha_base():  # /api/publico: link assinado do webhook
        interno = request.headers.get("x-vox-interno", "")
        ok = (interno and _local(request) and hmac.compare_digest(interno, INTERNO)) \
            or hmac.compare_digest(request.cookies.get("editor_auth", ""), _token())
        if not ok:
            return JSONResponse({"detail": "login necessário"}, status_code=401)
    return await call_next(request)


def _cookie(r: Response) -> Response:
    r.set_cookie("editor_auth", _token(), httponly=True, samesite="lax", secure=HTTPS,
                 max_age=60 * 60 * 24 * 30)
    return r


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
        ctx = _ctx_cortes(proj, out["settings"]) if proj.get("clips") else None
        for c in proj.get("clips", []):
            c = dict(c)
            ks = edits.intersect(ed["keeps"], pipeline.clip_segments(proj, c))
            c["keeps"] = ks
            c["final"] = round(sum(e - s for s, e in ks), 1)
            c["raw"] = round(sum(e - s for s, e in c["segments"]), 1)
            c["parts"] = (int(c["final"] // max(1, plat["max"] - 0.5)) + 1) if plat.get("split") and plat.get("max") \
                and c["final"] > plat["max"] + 0.5 else 1
            _enriquecer_corte(c, ctx)
            clips.append(c)
        out["clips"] = clips
    out["jobs"] = jobs.for_project(proj["id"])
    return out


def _ctx_cortes(proj: dict, settings: dict) -> dict:
    """O que a nota e os textos por rede precisam, calculado uma vez por projeto."""
    studio = settings["studio"]
    plat = dict(platforms.get(studio.get("platform")))
    plat["lo"], plat["hi"] = platforms.duration_range(studio)
    words = proj.get("words") or []
    marca = store.load_config().get("brand") or {}
    return {"words": words, "starts": [w["s"] for w in words], "plat": plat, "marca": marca,
            "fixas": redes.limpar_tags([marca.get("hashtags") or ""])}


def _enriquecer_corte(c: dict, ctx: dict) -> None:
    """v1.6: nota com os motivos ("gancho forte", "ideia completa"...) e título/legenda/hashtags de cada rede."""
    try:
        av = avaliacao.avaliar(ctx["words"], c, c.get("keeps"), ctx["plat"], ctx["starts"])
    except Exception:  # nunca derruba a tela por causa da nota
        av = {"nota": 0, "nivel": "fraco", "rotulo": "—", "motivos": [], "criterios": {}, "texto": ""}
    texto = av.pop("texto", "")
    c["avaliacao"] = av
    try:
        auto = redes.de_ia_curto(c["redes_ia"], c, texto, ctx["marca"]) if c.get("redes_ia") else redes.local(c, texto, ctx["marca"])
        if c.get("redes"):
            c["redes"], c["redes_fonte"] = redes.normalizar(c["redes"], auto), c.get("redes_fonte") or "editado"
        else:
            c["redes"], c["redes_fonte"] = auto, ("ia" if c.get("redes_ia") else "auto")
    except Exception:
        c["redes"], c["redes_fonte"] = {}, "auto"
    c.pop("redes_ia", None)
    c["hashtags_fixas"] = ctx["fixas"]


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
            "gpu_transcription": transcribe._cuda_available(), "login_required": bool(_senha_base()),
            "online_mode": bool(PASSWORD),
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
    pw = str(data.get("password", ""))
    certo = hmac.compare_digest(pw, PASSWORD) if PASSWORD else store.check_password(pw)
    if not certo:
        falhas.append(agora)
        _FALHAS[ip] = falhas
        time.sleep(1)
        raise HTTPException(401, "Senha incorreta")
    _FALHAS.pop(ip, None)
    return _cookie(JSONResponse({"ok": True}))


@app.post("/api/security/password")
def set_pc_password(data: dict = Body(...)):
    """Cria, troca ou tira a senha do programa do PC. Na versão online a senha vem do instalador."""
    if PASSWORD:
        raise HTTPException(400, "Na versão online, a senha é definida pelo instalador da VPS.")
    atual, nova = str(data.get("current", "")), str(data.get("new", ""))
    if store.password_hash() and not store.check_password(atual):
        time.sleep(1)
        raise HTTPException(401, "A senha atual não confere.")
    if nova and len(nova) < 4:
        raise HTTPException(400, "A senha precisa ter pelo menos 4 caracteres.")
    store.set_password(nova)
    r = JSONResponse({"ok": True, "password_set": bool(nova)})
    return _cookie(r) if nova else r


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


@app.get("/api/atividade")
def atividade():
    """Tudo o que está acontecendo agora, para a barra do topo: análises, exportações, downloads e as próximas postagens."""
    nomes = {p["id"]: p for p in store.list_projects()}
    trabalhos = []
    for j in jobs.atividade():
        p = nomes.get(j["project"]) or {}
        trabalhos.append({"id": j["id"], "kind": j["kind"], "label": j.get("label") or "", "status": j["status"],
                          "pct": j["pct"], "msg": j["msg"], "error": j.get("error"), "project": j["project"],
                          "project_name": p.get("name", ""), "project_kind": p.get("kind", ""), "created": j["created"]})
    analisando = [{"id": p["id"], "name": p["name"], "status": p["status"], "progress": p.get("progress") or {}}
                  for p in nomes.values() if p["status"] in ("enviando", "baixando", "processando", "na fila")]
    proximas = []
    try:
        for it in sorted((x for x in publish.queue() if x.get("status") in ("agendado", "publicando")),
                         key=lambda x: x.get("when", 0))[:6]:
            p = nomes.get(it.get("project")) or {}
            proximas.append({"id": it["id"], "net": it["net"], "when": it.get("when", 0), "status": it["status"],
                             "title": it.get("title") or it.get("label") or it.get("file"), "project": it.get("project"),
                             "file": it.get("file"), "project_name": p.get("name", ""), "pct": it.get("pct", 0)})
    except Exception:
        pass
    return {"trabalhos": trabalhos, "analisando": analisando, "proximas": proximas}


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
    return not PASSWORD and _local(request)


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


# ---------- pacote do projeto (.vox) e ligação PC ↔ online ----------

@app.get("/api/projects/{pid}/pacote")
def baixar_pacote(pid: str):
    """Baixa o projeto inteiro num arquivo .vox, para abrir em outra instalação (PC ↔ online) sem perder nada."""
    proj = _404(lambda: store.load(pid))
    from urllib.parse import quote
    nome = pacote.nome_arquivo(proj)
    return StreamingResponse(pacote.gerar(pid), media_type="application/zip", headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(nome)}",
        "X-Vox-Bytes": str(pacote.tamanho(pid))})


@app.post("/api/projects/importar-pacote")
async def importar_pacote(request: Request):
    """Recebe um .vox (do botão "Importar projeto do PC" ou do "Enviar para o online") e abre como estava."""
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
    return view(proj)


@app.post("/api/sync/config")
def receber_config(data: dict = Body(...)):
    """Lado do online: recebe as configurações copiadas do PC."""
    return {"ok": True, "updated": online.aplicar_config(data)}


def _so_pc():
    if PASSWORD:
        raise HTTPException(400, "Esta opção é do programa do PC.")


def _falha_online(fn):
    try:
        return fn()
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except httpx.HTTPError as e:
        raise HTTPException(400, f"Falha de conexão com o online: {e}")


@app.put("/api/online/config")
def online_config(data: dict = Body(...)):
    _so_pc()
    store.save_config({"online": {"url": data.get("url", ""), "password": data.get("password", "")}})
    return store.public_config(store.load_config())["online"]


@app.post("/api/online/testar")
def online_testar():
    _so_pc()
    return _falha_online(online.testar)


@app.post("/api/online/copiar-config")
def online_copiar():
    _so_pc()
    return _falha_online(online.copiar_config)


@app.get("/api/online/projetos")
def online_projetos():
    _so_pc()
    return _falha_online(online.projetos_online)


@app.post("/api/projects/{pid}/enviar-online")
def enviar_online(pid: str):
    _so_pc()
    proj = _404(lambda: store.load(pid))
    if proj.get("status") != "pronto":
        raise HTTPException(400, "Espere a análise terminar antes de enviar.")
    _falha_online(lambda: online._cfg())
    jobs.submit("enviar", pid, lambda pr: online.enviar_projeto(pid, pr), queue="download", label="Enviando para o online")
    return view(store.load(pid))


@app.post("/api/online/trazer/{rid}")
def trazer_online(rid: str):
    _so_pc()
    if any(c not in "0123456789abcdef" for c in rid):
        raise HTTPException(400, "Projeto inválido")
    _falha_online(lambda: online._cfg())
    job = jobs.submit("trazer", "_online", lambda pr: online.trazer_projeto(rid, pr), queue="download",
                      label="Trazendo do online")
    return job


@app.get("/api/projects/{pid}")
def project(pid: str):
    proj = _404(lambda: store.load(pid))
    if proj.get("status") == "pronto" and proj.get("kind") != "montagem" and (proj.get("analysis") or {}).get("v", 0) < 3:
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


# ---------- edição automática 2.0: perfis e capítulos ----------

@app.get("/api/projects/{pid}/perfis")
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


@app.post("/api/projects/{pid}/perfil")
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


def _capitulos_view(proj: dict) -> dict:
    cap = proj.get("capitulos") or {}
    itens = cap.get("itens") or []
    keeps = []
    if itens and proj.get("status") == "pronto":
        try:
            keeps = edits.build_edit(proj)["keeps"]
        except Exception:
            keeps = []
    ed = capitulos.no_editado(itens, keeps)
    return {"itens": ed, "texto": capitulos.texto(ed), "fonte": cap.get("fonte", ""), "aviso": cap.get("aviso", ""),
            "criado": cap.get("criado"), "valido_youtube": len(ed) >= 3}


@app.get("/api/projects/{pid}/capitulos")
def ver_capitulos(pid: str):
    return _capitulos_view(_404(lambda: store.load(pid)))


@app.post("/api/projects/{pid}/capitulos")
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


@app.put("/api/projects/{pid}/capitulos")
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
                if isinstance(data.get("redes"), dict):  # textos por rede editados à mão
                    c["redes"] = redes.normalizar(data["redes"], c.get("redes") or {})
                    c["redes_fonte"] = "editado"
    return view(_404(lambda: store.update(pid, fn)))


def _corte_e_texto(pid: str, clip_id: str) -> tuple[dict, dict, str]:
    """Projeto, corte (já com nota e redes calculadas) e a fala do corte."""
    proj = _404(lambda: store.load(pid))
    v = view(proj)
    clip = next((c for c in v.get("clips") or [] if c["id"] == clip_id), None)
    if not clip:
        raise HTTPException(404, "Corte não encontrado")
    words = proj.get("words") or []
    ks = clip.get("keeps") or clip["segments"]
    texto = " ".join(w["w"].strip() for w in words if any(a <= (w["s"] + w["e"]) / 2 <= b for a, b in ks))
    return proj, clip, texto


def _redes_view(clip: dict) -> dict:
    fixas = clip.get("hashtags_fixas") or []
    rd = clip.get("redes") or {}
    return {"redes": rd, "fonte": clip.get("redes_fonte", "auto"), "fixas": fixas,
            "prontos": {n: {"titulo": rd[n].get("titulo", ""), "legenda": redes.texto_final(rd[n], fixas, n)} for n in rd},
            "nomes": {n: redes.REDES[n]["nome"] for n in redes.ORDEM}}


@app.get("/api/projects/{pid}/clips/{clip_id}/redes")
def ver_redes(pid: str, clip_id: str):
    """Título e legenda pronta (com hashtags) de cada rede — usado no diálogo Publicar."""
    return _redes_view(_corte_e_texto(pid, clip_id)[1])


@app.post("/api/projects/{pid}/clips/{clip_id}/redes")
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


# ---------- músicas de fundo ----------

_AUDIO_OK = (".mp3", ".m4a", ".aac", ".wav", ".ogg", ".opus", ".flac")


@app.get("/api/musicas")
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


@app.post("/api/musicas")
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


@app.get("/api/musicas/{nome}")
def musica_ouvir(nome: str):
    f = pipeline.musica_path(nome)
    if not f:
        raise HTTPException(404, "Música não encontrada")
    return FileResponse(f)


@app.delete("/api/musicas/{nome}")
def musica_apagar(nome: str):
    f = pipeline.musica_path(nome)
    if f:
        Path(f).unlink(missing_ok=True)
    return musicas()


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


# ---------- autopostagem ----------

@app.get("/api/publish/status")
def publish_status():
    c = publish.cfg()
    apps = {}
    for app_name in ("youtube", "meta", "tiktok"):
        a = c.get(app_name) or {}
        apps[app_name] = {"client_id": a.get("client_id", ""), "secret_set": bool(a.get("client_secret")),
                          "system": bool((publish._sistema().get(app_name) or {}).get("client_id"))}
    nets = publish.public_status()
    online_info = None
    if not PASSWORD and online.configurado():  # programa do PC ligado ao online: as contas ficam lá
        on = online.status_online()
        online_info = {"ok": on is not None}
        for k, n in nets.items():
            o = ((on or {}).get("networks") or {}).get(k)
            if n["connected"] or not o:
                continue
            if o.get("connected") or o.get("app_ready"):
                n.update(via_online=True, connected=bool(o.get("connected")), account=o.get("account", ""),
                         app_ready=True, system_app=True, warn=o.get("warn"))
                if o.get("pages"):
                    n.update(pages=o["pages"], page_id=o.get("page_id"))
    dests = destinos.publicos()
    targets = dict(nets)
    for d in dests:  # no diálogo de publicar, os destinos próprios aparecem junto das redes
        targets["dest:" + d["id"]] = {"name": d["name"], "connected": True, "account": destinos.descricao(d),
                                      "dest": d["kind"]}
    return {"networks": nets, "apps": apps, "slots": c["slots"], "destinos": dests, "targets": targets,
            "tipos_destino": destinos.TIPOS, "online": online_info}


@app.post("/api/publish/online-login/{app_name}")
def publish_online_login(app_name: str):
    """Programa do PC: link de login da rede no online (a conta fica salva lá e o acesso é renovado sozinho)."""
    try:
        return {"url": online.link_login(app_name)}
    except RuntimeError as e:
        raise HTTPException(400, str(e))


def _app_via_online(app_name: str) -> bool:
    if PASSWORD or not online.configurado():
        return False
    st = publish.public_status()
    return not any(n["connected"] for n in st.values() if n["app"] == app_name)


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


def _ticket(app_name: str, validade: int = 600) -> str:
    exp = int(time.time()) + validade
    sig = hmac.new(SECRET.encode(), f"oauth.{app_name}.{exp}".encode(), hashlib.sha256).hexdigest()[:32]
    return f"{exp}.{sig}"


def _ticket_ok(app_name: str, ticket: str) -> bool:
    try:
        exp_s, sig = ticket.split(".", 1)
        exp = int(exp_s)
    except ValueError:
        return False
    if exp < time.time():
        return False
    certo = hmac.new(SECRET.encode(), f"oauth.{app_name}.{exp}".encode(), hashlib.sha256).hexdigest()[:32]
    return hmac.compare_digest(certo, sig)


@app.post("/api/oauth/{app_name}/ticket")
def oauth_ticket(app_name: str, request: Request, data: dict = Body(default={})):
    """Link de login da rede que vale 10 minutos. Serve para abrir o login num navegador sem a sessão do editor
    (o navegador do PC, ou o programa do PC pedindo o login das contas que ficam no online)."""
    if app_name not in ("youtube", "meta", "tiktok"):
        raise HTTPException(404, "Rede desconhecida")
    base = (os.environ.get("PUBLIC_URL") or str(request.base_url)).rstrip("/")
    url = f"{base}/api/oauth/{app_name}/start?ticket={_ticket(app_name)}"
    if data.get("desk"):
        url += "&desk=1"
    return {"url": url}


@app.get("/api/oauth/{app_name}/start")
def oauth_start(app_name: str, request: Request, desk: str = "", ticket: str = ""):
    # Começar um login troca a conta conectada: só quem está logado no editor (ou tem um link assinado) pode.
    if _senha_base() and not (hmac.compare_digest(request.cookies.get("editor_auth", ""), _token())
                              or _ticket_ok(app_name, ticket)):
        return Response(_DONE_PAGE.format(title="Link expirado", color="#f87171",
                                          msg="Este link de login vale por 10 minutos. Volte ao VOX Editor e clique "
                                              "em Conectar de novo."), media_type="text/html", status_code=403)
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


@app.post("/api/publish/destinos")
def destino_salvar(data: dict = Body(...)):
    try:
        destinos.salvar(data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return publish_status()


@app.delete("/api/publish/destinos/{did}")
def destino_remover(did: str):
    destinos.remover(did)
    return publish_status()


@app.post("/api/publish/destinos/{did}/testar")
def destino_testar(did: str):
    try:
        return {"ok": True, "msg": destinos.testar(did)}
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(400, "Não deu certo: " + publish.friendly_error(e)[:300])


@app.get("/api/publico/{token}")
def link_publico(token: str):
    try:
        f = destinos.abrir_link(token)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    return FileResponse(f, filename=f.name)


@app.post("/api/publish/page")
def publish_page(data: dict = Body(...)):
    if _app_via_online("meta"):
        online.escolher_pagina(str(data.get("page_id", "")))
    else:
        publish.select_page(str(data.get("page_id", "")))
    return publish_status()


@app.delete("/api/publish/account/{app_name}")
def publish_disconnect(app_name: str):
    if _app_via_online(app_name):
        try:
            online.desconectar(app_name)
        except RuntimeError as e:
            raise HTTPException(400, str(e))
    else:
        publish.remove_account(app_name)
    return publish_status()


ON = "on_"  # itens da fila que estão no online (vistos daqui do PC)


@app.get("/api/publish/queue")
def publish_queue():
    names = {p["id"]: p["name"] for p in store.list_projects()}
    out = []
    for it in publish.queue():
        out.append({**it, "project_name": names.get(it["project"], "Projeto apagado")})
    if not PASSWORD and online.configurado():
        for it in online.fila_online():
            out.append({**it, "id": ON + str(it.get("id")), "online": True,
                        "project_name": (it.get("project_name") or "") + " · pelo online"})
    return sorted(out, key=lambda x: -x["when"] if x["status"] in ("publicado", "erro", "cancelado") else x["when"])


def _pelo_online(nets: list[str]) -> list[str]:
    """Redes que, neste PC, saem pelas contas conectadas no online (o PC não tem a conta, o online tem)."""
    if PASSWORD or not online.configurado():
        return []
    local = publish.public_status()
    on = (online.status_online() or {}).get("networks") or {}
    return [n for n in nets if n in publish.NETWORKS and not local[n]["connected"] and (on.get(n) or {}).get("connected")]


@app.post("/api/publish/queue")
def publish_add(data: dict = Body(...)):
    pid, file = str(data.get("project", "")), str(data.get("file", ""))
    if "/" in file or "\\" in file or not (store.pdir(pid) / "renders" / file).exists():
        raise HTTPException(404, "Vídeo exportado não encontrado")
    nets = [str(n) for n in data.get("nets", [])]
    remotas = _pelo_online(nets)
    res = {"items": []}
    if remotas:
        pedido = {**{k: data.get(k) for k in ("when", "at", "caption", "title", "privacy", "label", "textos")}, "nets": remotas}
        jobs.submit("publicar-online", pid, lambda pr: online.publicar(pid, file, pedido, pr), queue="download",
                    label="Enviando para publicar pelo online")
        res["online"] = remotas
    locais = [n for n in nets if n not in remotas]
    if locais:
        res["items"] = _enfileirar(pid, file, {**data, "nets": locais})
    elif not remotas:
        raise HTTPException(400, "Escolha pelo menos uma rede ou destino")
    return res


@app.post("/api/publish/receber")
async def publish_receber(request: Request):
    """Lado do online: recebe um vídeo pronto do programa do PC e coloca na fila de publicação daqui."""
    import json as _json
    from urllib.parse import unquote
    try:
        pedido = _json.loads(unquote(request.headers.get("x-vox-pedido", "{}")))
    except ValueError:
        raise HTTPException(400, "Pedido inválido")
    nome = re.sub(r"[^\w.\- ]+", "_", unquote(request.headers.get("x-filename", "video.mp4")))[:120] or "video.mp4"
    if not nome.lower().endswith((".mp4", ".mov", ".m4a")):
        nome += ".mp4"
    proj = next((p for p in store.list_projects() if p.get("recebidos")), None)
    if not proj:  # projeto de montagem em branco que guarda os vídeos que chegam do PC (aparecem em Exportados)
        proj = montagem.projeto_em_branco("Vídeos enviados do PC", "9:16")
        store.update(proj["id"], lambda p: p.update(recebidos=True))
    pid = proj["id"]
    nome = f"{time.strftime('%Y%m%d-%H%M%S')}-{nome}"
    alvo = store.pdir(pid) / "renders" / nome
    alvo.parent.mkdir(parents=True, exist_ok=True)
    size, limit = 0, (MAX_UPLOAD_GB + 1) * 1024 ** 3
    try:
        with open(alvo, "wb") as fh:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"Vídeo maior que {MAX_UPLOAD_GB:g} GB")
                fh.write(chunk)
        if size == 0:
            raise HTTPException(400, "Arquivo vazio")
        item = {"file": nome, "created": time.time(), "duration": 0, "label": pedido.get("label") or
                f"Do PC: {pedido.get('project_name') or ''}".strip(), "size": size, "platform": None}
        try:
            item["duration"] = round(ff.probe(str(alvo))["duration"], 2)
        except Exception:
            pass
        store.update(pid, lambda p: p.setdefault("renders", []).insert(0, item))
        return {"items": _enfileirar(pid, nome, pedido)}
    except HTTPException:
        alvo.unlink(missing_ok=True)
        raise


def _enfileirar(pid: str, file: str, data: dict) -> list[dict]:
    ids_dest = {"dest:" + d["id"] for d in destinos.publicos()}
    nets = [n for n in data.get("nets", []) if n in publish.NETWORKS or n in ids_dest]
    if not nets:
        raise HTTPException(400, "Escolha pelo menos uma rede ou destino")
    status = publish.public_status()
    off = [publish.NETWORKS[n]["name"] for n in nets if n in publish.NETWORKS and not status[n]["connected"]]
    if off:
        raise HTTPException(400, "Conecte antes: " + ", ".join(off))
    mode = data.get("when") or "slot"
    textos = data.get("textos") if isinstance(data.get("textos"), dict) else {}  # v1.6: texto próprio de cada rede
    items = []
    for n in nets:
        if mode == "now":
            when = time.time()
        elif mode == "at":
            when = float(data.get("at") or time.time())
        else:
            when = publish.next_slot(n)
        tx = textos.get(n) if isinstance(textos.get(n), dict) else {}
        caption = tx.get("caption") if tx.get("caption") is not None else data.get("caption")
        title = tx.get("title") or data.get("title")
        items.append(publish.new_item(pid, file, n, when, str(caption or "")[:2200],
                                      str(title or "")[:100], data.get("privacy") or "public",
                                      str(data.get("label", "") or "")[:120]))
    publish.add(items)
    return items


@app.delete("/api/publish/queue/{iid}")
def publish_remove(iid: str):
    if iid.startswith(ON):
        online.fila_acao("DELETE", f"/api/publish/queue/{iid[len(ON):]}")
        return {"ok": True}
    with publish._lock:
        q = [it for it in publish.queue() if not (it["id"] == iid and it["status"] != "publicando")]
        publish._save_queue(q)
    return {"ok": True}


@app.post("/api/publish/queue/{iid}/retry")
def publish_retry(iid: str):
    if iid.startswith(ON):
        online.fila_acao("POST", f"/api/publish/queue/{iid[len(ON):]}/retry")
        return {"ok": True}
    publish.update_item(iid, status="agendado", when=time.time(), error="", msg="", pct=0)
    return {"ok": True}


@app.put("/api/publish/queue/{iid}")
def publish_edit(iid: str, data: dict = Body(...)):
    if iid.startswith(ON):
        online.fila_acao("PUT", f"/api/publish/queue/{iid[len(ON):]}", data)
        return {"ok": True}
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


# ---------- montagem (editor manual multicamadas) ----------

def _previas_pendentes(pid: str, m: dict) -> None:
    """Vídeos que o navegador não toca (iPhone/HEVC, .mkv, 4K) ganham uma cópia leve em segundo plano."""
    andando = {j.get("ref") for j in jobs.for_project(pid) if j["kind"] == "previa" and j["status"] != "erro"}
    for x in m.get("media") or []:
        if x.get("needs_proxy") and x["id"] not in andando:
            mid = x["id"]
            j = jobs.submit("previa", pid, lambda pr, mid=mid: montagem.gerar_previa(pid, mid, pr), queue="download",
                            label="Prévia da mídia")
            j["ref"] = mid


@app.post("/api/montagem/novo")
def montagem_novo(data: dict = Body(default={})):
    proj = montagem.projeto_em_branco(str(data.get("name") or "")[:120], data.get("formato") or "9:16")
    return {"id": proj["id"]}


@app.get("/api/projects/{pid}/montagem")
def montagem_get(pid: str):
    m = _404(lambda: montagem.carregar(pid))
    _previas_pendentes(pid, m)
    return m


@app.put("/api/projects/{pid}/montagem")
def montagem_put(pid: str, data: dict = Body(...)):
    return _404(lambda: montagem.salvar(pid, data))


@app.post("/api/projects/{pid}/montagem/recomecar")
def montagem_recomecar(pid: str, data: dict = Body(default={})):
    return _404(lambda: montagem.recomecar(pid, data.get("formato")))


# ---------- trilhas sonoras livres ----------

@app.get("/api/trilhas/humores")
def trilhas_humores():
    return trilhas.HUMORES


@app.get("/api/trilhas")
def trilhas_buscar(q: str = "", humor: str = "", pagina: int = 1):
    try:
        return trilhas.buscar(q, humor, pagina)
    except RuntimeError as e:
        raise HTTPException(502, str(e))


@app.post("/api/projects/{pid}/trilhas/{tid}")
def trilha_no_projeto(pid: str, tid: str):
    """Baixa a trilha livre para as mídias da montagem (com o crédito guardado junto)."""
    _404(lambda: store.load(pid))
    try:
        arq, f = trilhas.baixar(tid, montagem.pasta_midias(pid))
        return montagem.adicionar_midia(pid, arq, f"{f['title'] or 'Música'} — {f['creator'] or 'autor'}{arq.suffix}",
                                        {"credito": f["credito"], "licenca": f["license"], "trilha": f["id"]})
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except (RuntimeError, ValueError) as e:
        raise HTTPException(400, str(e))


@app.post("/api/projects/{pid}/minhas-musicas/{nome}")
def minha_musica_no_projeto(pid: str, nome: str):
    """Coloca uma música da biblioteca pessoal (Marca → Músicas) nas mídias da montagem."""
    import shutil
    _404(lambda: store.load(pid))
    src = pipeline.musica_path(nome)
    if not src:
        raise HTTPException(404, "Música não encontrada")
    dest = montagem.pasta_midias(pid) / f"{secrets.token_hex(4)}_{nome}"
    shutil.copy(src, dest)
    try:
        return montagem.adicionar_midia(pid, dest, nome)
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, f"Não consegui usar essa música: {str(e)[:200]}")


@app.post("/api/trilhas/{tid}/guardar")
def trilha_guardar(tid: str):
    """Guarda a trilha livre nas "Minhas músicas" (serve de fundo musical também na edição automática)."""
    try:
        arq, f = trilhas.baixar(tid, pipeline.MUSICAS)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    cred = pipeline.MUSICAS / "creditos.txt"
    linhas = cred.read_text(encoding="utf-8").splitlines() if cred.exists() else []
    linha = f"{arq.name}: {f['credito']}"
    if linha not in linhas:
        cred.write_text("\n".join(linhas + [linha]) + "\n", encoding="utf-8")
    return {"nome": arq.name, "credito": f["credito"]}


@app.post("/api/projects/{pid}/midias")
async def montagem_upload(pid: str, request: Request):
    _404(lambda: store.load(pid))
    from urllib.parse import unquote
    nome = unquote(request.headers.get("x-filename", "arquivo"))
    nome = re.sub(r"[\\/:*?\"<>|]+", "_", nome).strip() or "arquivo"
    if not montagem.tipo_por_extensao(nome):
        raise HTTPException(400, "Tipo de arquivo não aceito. Envie vídeo, imagem (JPG, PNG, WEBP) ou áudio.")
    pasta = montagem.pasta_midias(pid)
    dest = pasta / f"{secrets.token_hex(4)}_{nome}"
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
        item = montagem.adicionar_midia(pid, dest, nome)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, f"Não consegui usar esse arquivo: {str(e)[:200]}")
    _previas_pendentes(pid, montagem.carregar(pid))
    return item


@app.get("/api/projects/{pid}/midias/{mid}")
def montagem_midia(pid: str, mid: str, original: int = 0):
    return FileResponse(_404(lambda: montagem.caminho_midia(pid, mid, previa=not original)))


@app.get("/api/projects/{pid}/midias/{mid}/thumb")
def montagem_thumb(pid: str, mid: str, t: float = 0.0):
    try:
        f = montagem.miniatura(pid, mid, t)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception:
        raise HTTPException(404, "Sem imagem")
    return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})


@app.delete("/api/projects/{pid}/midias/{mid}")
def montagem_midia_del(pid: str, mid: str):
    try:
        return _404(lambda: montagem.remover_midia(pid, mid))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/projects/{pid}/montagem/exportar")
def montagem_exportar(pid: str, data: dict = Body(default={})):
    _404(lambda: store.load(pid))
    if data.get("montagem"):
        _404(lambda: montagem.salvar(pid, data["montagem"]))
    jobs.submit("montagem", pid, lambda pr: montagem.exportar(pid, data, pr), queue="render", label="Montagem")
    return view(store.load(pid))


# ---------- 1.2: bancos grátis (Pexels e Pixabay) e remoção de fundo com IA ----------

@app.get("/api/bancos/status")
def bancos_status():
    return bancos.status()


@app.get("/api/bancos/buscar")
def bancos_buscar(fonte: str = "todos", tipo: str = "video", q: str = "", pagina: int = 1, orient: str = ""):
    try:
        return bancos.buscar(fonte, tipo, q, pagina, orient)
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@app.post("/api/projects/{pid}/bancos/{bid}")
def banco_no_projeto(pid: str, bid: str):
    """Baixa o vídeo/foto do banco grátis para as mídias da montagem (em segundo plano, com progresso)."""
    _404(lambda: store.load(pid))
    try:
        info = bancos.item(bid)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))

    def tarefa(pr):
        arq, it = bancos.baixar(bid, montagem.pasta_midias(pid), pr)
        nome = (it.get("nome") or ("Vídeo" if it["tipo"] == "video" else "Foto")) + f" — {it['autor'] or it['fonte']}"
        md = montagem.adicionar_midia(pid, arq, nome[:100] + it["ext"],
                                      {"credito": it["credito"], "licenca": bancos.FONTES[it["fonte"]], "banco": bid})
        _previas_pendentes(pid, montagem.carregar(pid))
        return md

    j = jobs.submit("banco", pid, tarefa, queue="download", label="Banco grátis")
    j["ref"] = bid
    return {"job": j["id"], "tipo": info["tipo"]}


@app.get("/api/fundo/status")
def fundo_status():
    from .core import fundo_ia
    q = fundo_ia.qualidade()
    return {"disponivel": fundo_ia.disponivel(), "qualidade": q, "baixado": fundo_ia.modelo_baixado(q),
            "tamanho_mb": round(fundo_ia.MODELOS[q][2] / 1e6)}


@app.post("/api/projects/{pid}/montagem/sem-fundo")
def montagem_sem_fundo(pid: str, data: dict = Body(...)):
    _404(lambda: store.load(pid))
    if data.get("montagem"):
        _404(lambda: montagem.salvar(pid, data["montagem"]))
    item_id = str(data.get("item") or "")
    if any(j["kind"] == "semfundo" and j["status"] in ("na fila", "processando") and j.get("ref") == item_id
           for j in jobs.for_project(pid)):
        raise HTTPException(409, "Esse pedaço já está tirando o fundo.")
    j = jobs.submit("semfundo", pid, lambda pr: montagem.sem_fundo(pid, item_id, pr), queue="analysis",
                    label="Remover fundo (IA)")
    j["ref"] = item_id
    return {"job": j["id"]}


@app.post("/api/projects/{pid}/midias/{mid}/aplicado")
def montagem_substituicao_aplicada(pid: str, mid: str):
    return _404(lambda: montagem.substituicao_aplicada(pid, mid))


# ---------- páginas públicas exigidas pelas redes (abrem sem senha) ----------

def _pagina_legal(slug: str, request: Request) -> Response:
    base = (os.environ.get("PUBLIC_URL") or str(request.base_url)).rstrip("/")
    return Response(legal.pagina(slug, base), media_type="text/html; charset=utf-8",
                    headers={"Cache-Control": "no-cache"})


@app.get("/termos")
@app.get("/termos-de-uso")
@app.get("/terms")
def pagina_termos(request: Request):
    return _pagina_legal("termos", request)


@app.get("/privacidade")
@app.get("/politica-de-privacidade")
@app.get("/privacy")
def pagina_privacidade(request: Request):
    return _pagina_legal("privacidade", request)


@app.get("/exclusao-de-dados")
@app.get("/data-deletion")
def pagina_exclusao(request: Request):
    return _pagina_legal("exclusao-de-dados", request)


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

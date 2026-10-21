"""Stories do Culto (v1.15): vídeo ou foto + evento + modelo = story pronto, já postado nos Stories."""
from __future__ import annotations

from urllib.parse import unquote

from fastapi import APIRouter

from ..core import stories
from .comum import *  # noqa: F401,F403

router = APIRouter()


def _pid() -> str:
    return stories.projeto()["id"]


def _opcoes(data: dict) -> dict:
    """Só o que a capa usa, limpo e com tamanho máximo."""
    o = data.get("opcoes") if isinstance(data.get("opcoes"), dict) else data
    txt = lambda k, n: str(o.get(k) or "").strip()[:n]  # noqa: E731
    return {"modelo": txt("modelo", 20), "cor": txt("cor", 20), "linha1": txt("linha1", 40),
            "destaque": txt("destaque", 40), "linha3": txt("linha3", 60), "logo": txt("logo", 20),
            "enquadrar": txt("enquadrar", 20), "tamanho": txt("tamanho", 20), "evento": txt("evento", 40),
            "data_na_tela": bool(o.get("data_na_tela"))}


@router.get("/api/stories/status")
def stories_status():
    st = stories.status()
    pub = publish.public_status()
    nets = {}
    for n in ("instagram_story", "facebook_story"):
        e = pub.get(n) or {}
        nets[n] = {"nome": e.get("name", n), "conectado": bool(e.get("connected")), "conta": e.get("account", ""),
                   "aviso": e.get("warn", "")}
    if not PASSWORD and online.configurado():  # no PC: as contas podem estar conectadas só no online
        try:
            on = (online.status_online() or {}).get("networks") or {}
            for n in nets:
                if not nets[n]["conectado"] and (on.get(n) or {}).get("connected"):
                    nets[n].update(conectado=True, conta=(on[n].get("account") or "") + " (pelo online)")
        except Exception:
            pass
    st["redes"] = nets
    try:
        from ..core import resumo as _rs
        rs = _rs.status()
        modelo = (store.load_config().get("ai") or {}).get("model") or ""
        st["ia"] = {"ligada": bool(rs.get("ia")), "nome": rs.get("ia_nome") or "", "modelo": modelo}
    except Exception:
        st["ia"] = {"ligada": False, "nome": "", "modelo": ""}
    return st


@router.get("/api/stories/sugestao")
def stories_sugestao(data: str = ""):
    from datetime import date as _d
    try:
        dia = _d.fromisoformat(data) if data else None
    except ValueError:
        dia = None
    proj = stories.projeto()
    return {"sugestao": stories.sugestao(dia, (proj.get("stories") or {}).get("usados")),
            "data_extenso": stories.data_por_extenso(data) if data else ""}


@router.get("/api/stories/itens")
def stories_itens():
    pid = _pid()
    stories.limpar_temporarios(pid)
    return {"pid": pid, "itens": stories.lista(pid)}


@router.post("/api/stories/arquivo")
async def stories_arquivo(request: Request):
    """Um vídeo ou foto. Cabeçalho x-filename."""
    _limites(minutos=False)
    pid = _pid()
    nome = unquote(request.headers.get("x-filename", "arquivo"))
    nome = re.sub(r"[\\/:*?\"<>|]+", "_", nome).strip() or "arquivo"
    kind = montagem.tipo_por_extensao(nome)
    if kind not in ("video", "image"):
        if nome.lower().endswith((".heic", ".heif")):
            raise HTTPException(400, "Foto HEIC do iPhone ainda não é aceita. No iPhone: Ajustes > Câmera > Formatos > "
                                     "\"Mais compatível\" (ou envie a foto pelo WhatsApp, que vira JPG).")
        raise HTTPException(400, "Envie um vídeo ou uma foto (JPG, PNG, WEBP).")
    dest = stories.pasta(pid) / "src" / f"up{secrets.token_hex(4)}_{nome}"
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
        try:
            modificado = float(request.headers.get("x-modificado") or 0) or None
        except ValueError:
            modificado = None
        try:
            fuso = int(request.headers.get("x-fuso")) if request.headers.get("x-fuso") not in (None, "") else None
        except ValueError:
            fuso = None
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(stories.receber, pid, dest, nome, modificado, fuso)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    except ValueError as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, str(e))
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, f"Não consegui usar esse arquivo: {str(e)[:200]}")


@router.delete("/api/stories/itens/{iid}")
def stories_apagar(iid: str):
    try:
        stories.apagar_item(_pid(), iid)
    except FileNotFoundError:
        pass
    return {"ok": True}


@router.get("/api/stories/itens/{iid}/quadro")
def stories_quadro(iid: str):
    pid = _pid()
    try:
        it = stories.item(pid, iid)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    f = stories.pasta(pid) / "src" / it["quadro"]
    if not f.exists():
        raise HTTPException(404, "Sem imagem")
    return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})


@router.post("/api/stories/previa")
def stories_previa(data: dict = Body(...)):
    pid = _pid()
    iid = str(data.get("item") or "")
    try:
        jpg = stories.previa(pid, iid, _opcoes(data))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(400, f"Não consegui fazer a prévia: {str(e)[-300:]}")
    return Response(jpg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.post("/api/stories/criar")
def stories_criar(data: dict = Body(...)):
    pid = _pid()
    iids = [str(x) for x in (data.get("itens") or [])][:30]
    if not iids:
        raise HTTPException(400, "Escolha pelo menos um vídeo ou foto.")
    op = _opcoes(data)
    if not op["destaque"]:
        raise HTTPException(400, "Escolha o evento (ou escreva o nome em destaque).")
    postar = [n for n in (data.get("postar") or []) if n in ("instagram_story", "facebook_story")]
    if postar:  # confere antes de gastar tempo renderizando
        remotas = _pelo_online(postar)
        st = publish.public_status()
        off = [publish.NETWORKS[n]["name"] for n in postar if n not in remotas and not st[n]["connected"]]
        if off:
            raise HTTPException(400, "Conecte antes em Redes sociais: " + ", ".join(off))
    quando = data.get("quando") if data.get("quando") in ("now", "at") else "now"
    at = data.get("at")
    legenda = str(data.get("legenda") or "")[:2200]

    def tarefa(pr):
        res = stories.gerar(pid, iids, op, lambda x, m="": pr(x * (0.97 if postar else 1), m))
        if postar:
            pr(0.98, "Mandando para os Stories…")
            enviados, falhas = [], []
            for s in res["saidas"]:
                pedido = {"nets": postar, "when": quando, "at": at, "caption": legenda, "title": "",
                          "privacy": "public", "label": s["label"]}
                try:
                    remotas = _pelo_online(postar)
                    if remotas:
                        online.publicar(pid, s["file"], {**pedido, "nets": remotas}, lambda x, m="": pr(0.98, m))
                    locais = [n for n in postar if n not in remotas]
                    if locais:
                        _enfileirar(pid, s["file"], {**pedido, "nets": locais})
                    enviados.append(s["file"])
                except Exception as e:  # o story fica pronto em Exportados; dá para publicar depois
                    falhas.append(str(getattr(e, "detail", e))[:200])
            res["postados"] = len(enviados)
            if falhas:
                res["aviso"] = "Os stories ficaram prontos, mas não consegui mandar para as redes: " + falhas[0]
        return res
    j = jobs.submit("stories", pid, tarefa, queue="render", label="Stories: " + (op["destaque"] or "story"))
    return {"pid": pid, "job": j["id"]}


# ---------- logos das igrejas (vários: sede e congregações) ----------

@router.get("/api/stories/logos")
def stories_logos():
    return stories.logos()


@router.post("/api/stories/logos")
async def stories_logo_enviar(request: Request):
    dados = await request.body()
    nome = unquote(request.headers.get("x-filename", "Logo"))
    try:
        from starlette.concurrency import run_in_threadpool
        novo = await run_in_threadpool(stories.salvar_logo, dados, nome)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"novo": novo, "logos": stories.logos()}


@router.delete("/api/stories/logos/{lid}")
def stories_logo_apagar(lid: str):
    stories.apagar_logo(lid)
    return stories.logos()


@router.get("/api/stories/logos/{lid}")
def stories_logo_ver(lid: str):
    f = stories.arquivo_logo(lid)
    if not f:
        raise HTTPException(404, "Sem logo")
    return FileResponse(f, media_type="image/png", headers={"Cache-Control": "no-cache"})


# ---------- v1.15.1: excluir stories prontos ----------

@router.delete("/api/stories/prontos/{arquivo}")
def stories_pronto_apagar(arquivo: str):
    pid = _pid()
    try:
        ok = stories.apagar_pronto(pid, arquivo)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not ok:
        raise HTTPException(409, "Este story está agendado em Publicações. Cancele a publicação lá antes de excluir.")
    return {"ok": True}


@router.post("/api/stories/prontos/limpar")
def stories_prontos_limpar(data: dict = Body(default={})):
    """Exclui vários de uma vez (ou todos). Os que estão na fila de publicação ficam."""
    pid = _pid()
    proj = store.load(pid)
    todos = [r["file"] for r in proj.get("renders") or [] if str(r.get("file", "")).startswith("story-")]
    alvo = [str(x) for x in (data.get("arquivos") or todos) if str(x) in todos]
    apagados, ficaram = 0, 0
    for f in alvo:
        try:
            if stories.apagar_pronto(pid, f):
                apagados += 1
            else:
                ficaram += 1
        except ValueError:
            pass
    return {"apagados": apagados, "ficaram": ficaram}


# ---------- v1.15.1: Resumo do Culto com os arquivos dos stories ----------

@router.post("/api/stories/resumo")
def stories_resumo(data: dict = Body(...)):
    from ..core import resumo as _rs
    _limites(minutos=False)
    pid_st = _pid()
    iids = [str(x) for x in (data.get("itens") or [])][:200]
    if not iids:
        raise HTTPException(400, "Não há vídeos ou fotos para o resumo.")
    o = data.get("opcoes") if isinstance(data.get("opcoes"), dict) else {}
    ev_st = str(o.get("evento") or "")
    titulo = str(o.get("titulo") or "").strip()[:60] or "Resumo do Culto"
    formato = o.get("formato") if o.get("formato") in montagem.FORMATOS else "9:16"
    marca = (store.BRAND_DIR / "logo.png").exists()
    opts = {"formato": formato, "duracao": str(o.get("duracao") or "60"), "ritmo": o.get("ritmo") or "calmo",
            "evento": stories.EVENTO_RESUMO.get(ev_st, "culto"), "data": str(o.get("data") or "")[:10],
            "musica": "__auto__", "cor": o.get("cor") or "cinema", "enquadramento": "auto", "som_original": True,
            "legenda": True, "legenda_estilo": "palavra_ativa", "rotulos": True, "abertura": True,
            "encerramento": True, "logo": marca, "ordem": "hora", "usar_ia": True, "titulo": titulo}
    proj = montagem.projeto_em_branco(titulo, formato)
    pid = proj["id"]
    store.update(pid, lambda p: p.update(resumo={"criado": time.time(), "de_stories": True}))

    def tarefa(pr):
        def prog(x, msg=""):
            pr(x, msg)
            if msg:
                store.update(pid, lambda p: p.update(progress={"pct": round(x, 3), "msg": msg}))
        store.update(pid, lambda p: p.update(status="processando", progress={"pct": 0, "msg": "Juntando os arquivos…"}))
        prog(0.01, "Juntando os vídeos e fotos do culto…")
        n = stories.juntar_no_resumo(pid_st, iids, pid)
        if not n:
            store.update(pid, lambda p: p.update(status="pronto", progress={"pct": 1, "msg": ""}))
            raise RuntimeError("Os arquivos dos stories não estão mais aqui (foram apagados).")
        _previas_pendentes(pid, montagem.carregar(pid))
        try:
            r = _rs.criar(pid, opts, prog)
        except Exception as e:
            store.update(pid, lambda p: p.update(status="pronto", progress={"pct": 1, "msg": str(e)[:300]}))
            raise
        store.update(pid, lambda p: p.update(status="pronto", progress={"pct": 1, "msg": ""}))
        return {**(r or {}), "arquivos": n}
    j = jobs.submit("resumo", pid, tarefa, queue="analysis", label="Resumo do culto (dos stories)")
    return {"id": pid, "job": j["id"]}

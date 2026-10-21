"""Autopostagem: redes conectadas, login das redes (OAuth), destinos próprios e fila de publicações."""
from __future__ import annotations

from fastapi import APIRouter

from .comum import *  # noqa: F401,F403

router = APIRouter()


# ---------- autopostagem ----------

@router.get("/api/publish/status")
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
    dests = destinos.publicos() if not contas.conta_propria() else []  # destinos (web TV...) são do responsável
    if contas.conta_propria():
        apps = {k: {"client_id": "", "secret_set": False, "system": v["system"]} for k, v in apps.items()}
    targets = dict(nets)
    for d in dests:  # no diálogo de publicar, os destinos próprios aparecem junto das redes
        targets["dest:" + d["id"]] = {"name": d["name"], "connected": True, "account": destinos.descricao(d),
                                      "dest": d["kind"]}
    return {"networks": nets, "apps": apps, "slots": c["slots"], "destinos": dests, "targets": targets,
            "tipos_destino": destinos.TIPOS, "online": online_info}


@router.post("/api/publish/online-login/{app_name}")
def publish_online_login(app_name: str):
    """Programa do PC: link de login da rede no online (a conta fica salva lá e o acesso é renovado sozinho)."""
    try:
        return {"url": online.link_login(app_name)}
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@router.put("/api/publish/config")
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


@router.post("/api/oauth/{app_name}/ticket")
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


@router.get("/api/oauth/{app_name}/start")
def oauth_start(app_name: str, request: Request, desk: str = "", ticket: str = ""):
    # Começar um login troca a conta conectada: só quem está logado no editor (ou tem um link assinado) pode.
    conta_t = _ticket_conta(app_name, ticket) if ticket else None
    papel_u = (contas.eu() or {}).get("papel")
    if _senha_base() and not (hmac.compare_digest(request.cookies.get("editor_auth", ""), _token())
                              or papel_u in ("admin", "igreja") or conta_t is not None):
        return Response(_DONE_PAGE.format(title="Link expirado", color="#f87171",
                                          msg="Este link de login vale por 10 minutos. Volte ao VOX Editor e clique "
                                              "em Conectar de novo."), media_type="text/html", status_code=403)
    # v1.16: de quem é este login (o link assinado vale mais; senão, a conta Igreja que está logada)
    dona = conta_t if conta_t is not None else contas.conta_propria()
    try:
        with publish.com_conta(dona):
            r = RedirectResponse(publish.auth_url(app_name, _redirect_uri(request, app_name)))
    except Exception as e:
        from urllib.parse import quote
        return RedirectResponse(f"/#/redes?erro={quote(str(e))}")
    if desk:  # login aberto no navegador a partir do programa do PC: no fim, mostra só "pode voltar ao programa"
        r.set_cookie("oauth_desk", "1", max_age=900, httponly=True, samesite="lax")
    return r


@router.get("/api/oauth/{app_name}/callback")
def oauth_callback(app_name: str, request: Request, code: str = "", state: str = "", error: str = "",
                   error_description: str = ""):
    if error or not code:
        return _oauth_done(request, False, error_description or error or "Login cancelado")
    app_st, dona = publish.check_state_conta(state)
    if app_st != app_name:
        return _oauth_done(request, False, "Login expirado. Tente conectar de novo.")
    try:
        with publish.com_conta(dona):  # a conta conectada fica com quem começou o login
            publish.finish_login(app_name, code, _redirect_uri(request, app_name))
    except Exception as e:
        return _oauth_done(request, False, str(e)[:300])
    return _oauth_done(request, True, "", app_name)


@router.post("/api/publish/destinos")
def destino_salvar(data: dict = Body(...)):
    try:
        destinos.salvar(data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return publish_status()


@router.delete("/api/publish/destinos/{did}")
def destino_remover(did: str):
    destinos.remover(did)
    return publish_status()


@router.post("/api/publish/destinos/{did}/testar")
def destino_testar(did: str):
    try:
        return {"ok": True, "msg": destinos.testar(did)}
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(400, "Não deu certo: " + publish.friendly_error(e)[:300])


@router.get("/api/publico/{token}")
def link_publico(token: str):
    try:
        f = destinos.abrir_link(token)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    return FileResponse(f, filename=f.name)


@router.post("/api/publish/page")
def publish_page(data: dict = Body(...)):
    if _app_via_online("meta"):
        online.escolher_pagina(str(data.get("page_id", "")))
    else:
        publish.select_page(str(data.get("page_id", "")))
    return publish_status()


@router.delete("/api/publish/account/{app_name}")
def publish_disconnect(app_name: str):
    if _app_via_online(app_name):
        try:
            online.desconectar(app_name)
        except RuntimeError as e:
            raise HTTPException(400, str(e))
    else:
        publish.remove_account(app_name)
    return publish_status()


@router.get("/api/publish/queue")
def publish_queue():
    names = {p["id"]: p["name"] for p in store.list_projects()}
    minha = contas.conta_propria()
    out = []
    for it in publish.queue():
        if minha and (it.get("conta") or "") != minha:
            continue  # v1.16: a conta Igreja só vê as publicações dela
        out.append({**it, "project_name": names.get(it["project"], "Projeto apagado")})
    if not PASSWORD and online.configurado():
        for it in online.fila_online():
            out.append({**it, "id": ON + str(it.get("id")), "online": True,
                        "project_name": (it.get("project_name") or "") + " · pelo online"})
    return sorted(out, key=lambda x: -x["when"] if x["status"] in ("publicado", "erro", "cancelado") else x["when"])


@router.post("/api/publish/queue")
def publish_add(data: dict = Body(...)):
    pid, file = str(data.get("project", "")), str(data.get("file", ""))
    if "/" in file or "\\" in file or not (store.pdir(pid) / "renders" / file).exists():
        raise HTTPException(404, "Vídeo exportado não encontrado")
    try:
        if not contas.pode_ver(store.load(pid)):  # v1.16: cada conta só publica os vídeos dela
            raise HTTPException(404, "Vídeo exportado não encontrado")
    except FileNotFoundError:
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


@router.post("/api/publish/receber")
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
    proj = next((p for p in store.list_projects(todos=True) if p.get("recebidos")), None)
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


def _minha_publicacao(iid: str) -> None:
    """v1.16: conta Igreja só mexe nas publicações dela."""
    minha = contas.conta_propria()
    if minha and not any(it["id"] == iid and (it.get("conta") or "") == minha for it in publish.queue()):
        raise HTTPException(404, "Publicação não encontrada")


@router.delete("/api/publish/queue/{iid}")
def publish_remove(iid: str):
    if iid.startswith(ON):
        online.fila_acao("DELETE", f"/api/publish/queue/{iid[len(ON):]}")
        return {"ok": True}
    _minha_publicacao(iid)
    with publish._lock:
        q = [it for it in publish.queue() if not (it["id"] == iid and it["status"] != "publicando")]
        publish._save_queue(q)
    return {"ok": True}


@router.post("/api/publish/queue/{iid}/retry")
def publish_retry(iid: str):
    if iid.startswith(ON):
        online.fila_acao("POST", f"/api/publish/queue/{iid[len(ON):]}/retry")
        return {"ok": True}
    _minha_publicacao(iid)
    publish.update_item(iid, status="agendado", when=time.time(), error="", msg="", pct=0)
    return {"ok": True}


@router.put("/api/publish/queue/{iid}")
def publish_edit(iid: str, data: dict = Body(...)):
    if iid.startswith(ON):
        online.fila_acao("PUT", f"/api/publish/queue/{iid[len(ON):]}", data)
        return {"ok": True}
    _minha_publicacao(iid)
    fields = {}
    if "when" in data:
        fields["when"] = float(data["when"])
    for k in ("caption", "title"):
        if k in data:
            fields[k] = str(data[k])[:2200]
    publish.update_item(iid, **fields)
    return {"ok": True}

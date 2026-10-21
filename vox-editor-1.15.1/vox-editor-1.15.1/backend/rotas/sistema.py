"""Sistema, entrada (login), contas de pessoas e configurações."""
from __future__ import annotations

from fastapi import APIRouter

from .comum import *  # noqa: F401,F403

router = APIRouter()


# ---------- sistema / login / configurações ----------

@router.get("/api/status")
def status():
    try:
        encs = ff.available_encoders()
        ff_ok = True
    except Exception:
        encs, ff_ok = {}, False
    return {"version": VERSION, "ffmpeg": ff_ok, "encoders": encs,
            "encoder": ff.best_encoder() if ff_ok else None, "local_transcription": transcribe.local_available(),
            "gpu_transcription": transcribe._cuda_available(), "login_required": bool(_senha_base()),
            "online_mode": bool(PASSWORD), "contas": bool(PASSWORD),
            "name": store.load_config()["app"].get("name", "Editor IA"),
            "tagline": store.load_config()["app"].get("tagline", ""),
            "accent": store.load_config()["app"].get("accent", "#FF8A3D"),
            "app_logo": (store.BRAND_DIR / "app_logo.png").exists()}


@router.get("/api/meta")
def meta():
    fonts = sorted({f.stem for f in store.FONTS.glob("*.[ot]tf")})
    return {"platforms": platforms.PLATFORMS, "durations": platforms.DURATIONS,
            "styles": {k: {"name": v["name"], "desc": v["desc"], "font": v["font"]} for k, v in subtitles.STYLES.items()},
            "style_defaults": subtitles.STYLES, "fonts": subtitles.FONTS, "font_files": fonts,
            "face_detection": reframe.available(), "layouts": frames.LAYOUTS,
            "geometry": {k: frames.geometry(k, 1080, 1920) for k in frames.LAYOUTS},
            "socials": socials.NETS, "platform_net": socials.PLATFORM_NET,
            "icons": sorted(f.stem for f in (store.BRAND_DIR / "icones").glob("*.png"))}


@router.post("/api/login")
def login(request: Request, data: dict = Body(...)):
    # na internet: depois de 5 senhas erradas em 15 minutos, o IP espera antes de tentar de novo
    ip = request.client.host if request.client else "?"
    agora = time.time()
    falhas = [t for t in _FALHAS.get(ip, []) if agora - t < 900]
    if len(falhas) >= 5:
        espera = int(900 - (agora - falhas[0])) // 60 + 1
        raise HTTPException(429, f"Muitas tentativas erradas. Tente de novo em {espera} min.")
    pw = str(data.get("password", ""))
    email = str(data.get("email", "") or "").strip()
    if email.lower() in ("admin", "administrador", "dono"):
        email = ""  # o responsável entra como "admin" (ou com o usuário vazio)
    if email and PASSWORD:  # v1.7: pessoa com conta (equipe ou cliente) entra com e-mail e senha
        try:
            u = contas.autenticar(email, pw)
        except PermissionError as e:
            raise HTTPException(403, str(e))
        if not u:
            falhas.append(agora)
            _FALHAS[ip] = falhas
            time.sleep(1)
            raise HTTPException(401, "E-mail ou senha incorretos")
        _FALHAS.pop(ip, None)
        r = JSONResponse({"ok": True, "papel": u["papel"]})
        r.delete_cookie("editor_auth")
        r.set_cookie("vox_sessao", contas.token(u, SECRET), httponly=True, samesite="lax", secure=HTTPS,
                     max_age=60 * 60 * 24 * 30)
        return r
    certo = _senha_dono_confere(pw)
    if not certo:
        falhas.append(agora)
        _FALHAS[ip] = falhas
        time.sleep(1)
        raise HTTPException(401, "Senha incorreta")
    _FALHAS.pop(ip, None)
    r = _cookie(JSONResponse({"ok": True, "papel": "dono"}))
    r.delete_cookie("vox_sessao")
    return r


@router.post("/api/logout")
def logout():
    r = JSONResponse({"ok": True})
    r.delete_cookie("editor_auth")
    r.delete_cookie("vox_sessao")
    return r


@router.get("/api/eu")
def eu():
    return _eu_view()


@router.post("/api/eu/senha")
def eu_senha(data: dict = Body(...)):
    u = contas.eu()
    if not u or u["papel"] == "dono":
        raise HTTPException(400, "A senha do dono é a que foi definida na instalação da VPS.")
    try:
        contas.trocar_senha(u["id"], str(data.get("atual", "")), str(data.get("nova", "")))
    except PermissionError as e:
        time.sleep(1)
        raise HTTPException(401, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    full = contas._buscar(u["id"])
    r = JSONResponse({"ok": True})  # a sessão antiga caiu com a troca: entrega uma nova
    r.set_cookie("vox_sessao", contas.token(full, SECRET), httponly=True, samesite="lax", secure=HTTPS,
                 max_age=60 * 60 * 24 * 30)
    return r


@router.get("/api/usuarios")
def usuarios():
    _so_online_contas()
    projetos: dict[str, int] = {}
    for p in store.list_projects(todos=True):
        projetos[p.get("owner") or ""] = projetos.get(p.get("owner") or "", 0) + 1
    lista = []
    for u in contas.listar():
        lista.append({**u, "papel_nome": contas.NOMES_PAPEIS.get(u["papel"], u["papel"]), "uso": contas.uso(u),
                      "projetos": projetos.get(u["id"], 0)})
    return {"usuarios": lista, "projetos_do_dono": projetos.get("", 0)}


@router.post("/api/usuarios")
def usuario_criar(data: dict = Body(...)):
    _so_online_contas()
    try:
        return contas.criar(data)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/api/usuarios/{uid}")
def usuario_editar(uid: str, data: dict = Body(...)):
    _so_online_contas()
    try:
        return contas.editar(uid, data)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/api/usuarios/{uid}")
def usuario_remover(uid: str, projetos: str = "manter"):
    """Remove a conta. Os projetos da pessoa passam para o dono (projetos=manter) ou são apagados (projetos=apagar)."""
    _so_online_contas()
    if not contas._buscar(uid):
        raise HTTPException(404, "Conta não encontrada.")
    for p in store.list_projects(todos=True):
        if p.get("owner") == uid:
            if projetos == "apagar":
                store.delete_project(p["id"])
            else:
                store.update(p["id"], lambda x: x.pop("owner", None))
            _DONO_PROJ.pop(p["id"], None)
    contas.remover(uid)
    contas.esquecer_espaco(uid)
    return {"ok": True}


@router.post("/api/security/password")
def set_pc_password(data: dict = Body(...)):
    """Troca a senha do admin (o responsável), no PC e no online. No primeiro acesso com a senha padrão,
    não precisa da atual. No online a senha nunca fica vazia; no PC, vazio tira a senha."""
    atual, nova = str(data.get("current", "")), str(data.get("new", ""))
    if (contas.eu() or contas.DONO)["papel"] != "dono":
        raise HTTPException(403, "Só o admin troca a senha do admin.")
    primeira = store.precisa_trocar_senha()
    if _senha_base() and not primeira and not _senha_dono_confere(atual):
        time.sleep(1)
        raise HTTPException(401, "A senha atual não confere.")
    if PASSWORD and not nova:
        raise HTTPException(400, "Na versão online o admin precisa de senha.")
    if nova and len(nova) < 6:
        raise HTTPException(400, "A senha precisa ter pelo menos 6 caracteres.")
    if nova and nova == SENHA_PADRAO:
        raise HTTPException(400, "Escolha uma senha diferente da senha padrão.")
    store.set_password(nova)
    r = JSONResponse({"ok": True, "password_set": bool(nova)})
    return _cookie(r) if nova else r


@router.get("/api/settings")
def get_settings():
    cfg = store.public_config(store.load_config())
    if not contas.manda_em_tudo():  # equipe e clientes não precisam ver chaves, destinos nem os dados das páginas
        for sec in ("online", "legal", "security"):
            cfg.pop(sec, None)
        if not contas.pode_publicar():
            cfg["publish"] = {}
        else:
            cfg["publish"] = {k: v for k, v in (cfg.get("publish") or {}).items() if k in ("slots", "destinos")}
    return cfg


@router.put("/api/settings")
def put_settings(data: dict = Body(...)):
    return store.public_config(store.save_config(data))


@router.post("/api/settings/test-ai")
def test_ai():
    from ..engine.smartcuts import _call_llm
    cfg = store.load_config()["ai"]
    if cfg.get("provider") in (None, "none"):
        return {"ok": True, "msg": "Sem IA externa: os cortes usam a análise local."}
    try:
        txt = _call_llm("Responda apenas: OK", cfg)
        return {"ok": True, "msg": f"Conectado. Resposta: {txt.strip()[:40]}"}
    except Exception as e:
        return {"ok": False, "msg": str(e)[:300]}


# ---------- v1.8: manutenção automática (cópia diária e limpeza) ----------

def _so_responsavel():
    u = contas.eu()
    if u and u["papel"] not in ("dono", "admin"):
        raise HTTPException(403, "Só o responsável pela conta pode ver as cópias de segurança.")


@router.get("/api/maintenance/status")
def manutencao_status():
    _so_responsavel()
    e = manutencao.estado()
    return {"backup": e.get("backup"), "backup_erro": e.get("backup_erro"), "limpeza": e.get("limpeza"),
            "copias": manutencao.listar_backups(), "guardar": manutencao.GUARDAR_COPIAS, "hora": manutencao.HORA,
            "fila": jobs.resumo()}


@router.post("/api/maintenance/backup")
def manutencao_agora():
    _so_responsavel()
    return manutencao.rodar_agora("pedido pelo painel")


@router.get("/api/maintenance/backups/{nome}")
def manutencao_baixar(nome: str):
    _so_responsavel()
    f = manutencao.caminho_backup(nome)
    if not f:
        raise HTTPException(404, "Cópia não encontrada")
    return FileResponse(f, filename=nome, media_type="application/gzip")

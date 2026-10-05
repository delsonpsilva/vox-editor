"""Autopostagem: contas conectadas pelos logins oficiais (OAuth), fila de publicação, agenda de horários
e envio para YouTube, Instagram, Facebook e TikTok pelas APIs oficiais. Senhas nunca são guardadas;
apenas as chaves de acesso que cada rede devolve depois do login, e só neste computador/servidor."""
from __future__ import annotations

import json
import math
import os
import secrets
import threading
import time
import traceback
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from . import store

ACCOUNTS = store.DATA / "contas.json"
SISTEMA = store.DATA / "apps-sistema.json"   # apps oficiais do VOX (cadastrados uma vez com: sudo vox-apps)
QUEUE = store.DATA / "publicacoes.json"
_lock = threading.RLock()
_states: dict[str, tuple[str, float]] = {}
GRAPH = "https://graph.facebook.com/v21.0"

NETWORKS = {
    "youtube": {"name": "YouTube Shorts", "app": "youtube"},
    "instagram": {"name": "Instagram Reels", "app": "meta"},
    "facebook": {"name": "Facebook Reels", "app": "meta"},
    "tiktok": {"name": "TikTok", "app": "tiktok"},
}


# ----------------------------- armazenamento -----------------------------

def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def accounts() -> dict:
    with _lock:
        return _read(ACCOUNTS, {})


def save_account(app: str, data: dict) -> None:
    with _lock:
        acc = _read(ACCOUNTS, {})
        acc[app] = {**data, "connected": time.time()}
        _write(ACCOUNTS, acc)


def remove_account(app: str) -> None:
    with _lock:
        acc = _read(ACCOUNTS, {})
        acc.pop(app, None)
        _write(ACCOUNTS, acc)


def queue() -> list[dict]:
    with _lock:
        return _read(QUEUE, [])


def _save_queue(items: list[dict]) -> None:
    with _lock:
        _write(QUEUE, items)


def update_item(iid: str, **fields) -> None:
    with _lock:
        items = queue()
        for it in items:
            if it["id"] == iid:
                it.update(fields)
        _save_queue(items)


def cfg() -> dict:
    c = store.load_config().get("publish") or {}
    c.setdefault("slots", [{"days": [0, 1, 2, 3, 4, 5, 6], "time": "19:00"}])
    return c


# ----------------------------- apps das redes -----------------------------

def _sistema() -> dict:
    """Apps oficiais do VOX: arquivo apps-sistema.json (comando vox-apps) ou variáveis VOX_APP_<REDE>_ID/SECRET.
    Nunca vão para o navegador."""
    s = _read(SISTEMA, {}) if SISTEMA.exists() else {}
    for app in ("youtube", "meta", "tiktok"):
        cid = os.environ.get(f"VOX_APP_{app.upper()}_ID")
        sec = os.environ.get(f"VOX_APP_{app.upper()}_SECRET")
        if cid and sec:
            s[app] = {"client_id": cid, "client_secret": sec}
    return s


def app_cred(app: str, via: str | None = None) -> dict:
    """Credenciais do app da rede. Quem preencheu o próprio app usa o dele; senão, usa o app oficial do VOX.
    Uma conta conectada guarda por qual app entrou ("via"), para renovar o acesso sempre pelo mesmo app."""
    proprio = cfg().get(app) or {}
    sist = _sistema().get(app) or {}
    tem = lambda c: bool(c.get("client_id") and c.get("client_secret"))  # noqa: E731
    if via == "sistema" and tem(sist):
        return {**sist, "via": "sistema"}
    if via == "proprio" and tem(proprio):
        return {**proprio, "via": "proprio"}
    if tem(proprio):
        return {**proprio, "via": "proprio"}
    if tem(sist):
        return {**sist, "via": "sistema"}
    return {}


def public_status() -> dict:
    """O que o painel pode ver: quem está conectado (sem chaves)."""
    acc, c = accounts(), cfg()
    out = {}
    for net, info in NETWORKS.items():
        a = acc.get(info["app"]) or {}
        cred = app_cred(info["app"])
        ready = bool(cred)
        entry = {"name": info["name"], "app": info["app"], "app_ready": ready, "connected": False, "account": "",
                 "system_app": cred.get("via") == "sistema"}
        if net == "youtube" and a.get("refresh_token"):
            entry.update(connected=True, account=a.get("channel", ""))
        if net == "tiktok" and a.get("refresh_token"):
            entry.update(connected=True, account=a.get("user", ""))
        if net in ("instagram", "facebook") and a.get("pages"):
            page = next((p for p in a["pages"] if p["id"] == a.get("page_id")), a["pages"][0])
            if net == "facebook":
                entry.update(connected=True, account=page["name"])
            elif page.get("ig_id"):
                entry.update(connected=True, account="@" + (page.get("ig_user") or "instagram"))
            else:
                entry.update(connected=False, account="", warn="A página escolhida não tem um Instagram profissional ligado.")
            entry["pages"] = [{"id": p["id"], "name": p["name"], "ig": p.get("ig_user")} for p in a["pages"]]
            entry["page_id"] = page["id"]
        out[net] = entry
    return out


# ----------------------------- login oficial (OAuth) -----------------------------

def new_state(app: str) -> str:
    st = secrets.token_urlsafe(24)
    _states[st] = (app, time.time())
    return st


def check_state(st: str) -> str | None:
    app, t = _states.pop(st, (None, 0))
    return app if app and time.time() - t < 900 else None


def auth_url(app: str, redirect: str) -> str:
    c = app_cred(app)
    cid = c.get("client_id")
    if not cid or not c.get("client_secret"):
        raise RuntimeError("Esta rede ainda não tem app configurado. Peça ao administrador para rodar: sudo vox-apps")
    st = new_state(app)
    from urllib.parse import urlencode
    if app == "youtube":
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
            "client_id": cid, "redirect_uri": redirect, "response_type": "code", "access_type": "offline",
            "prompt": "consent", "state": st,
            "scope": "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"})
    if app == "meta":
        return "https://www.facebook.com/v21.0/dialog/oauth?" + urlencode({
            "client_id": cid, "redirect_uri": redirect, "state": st, "response_type": "code",
            "scope": "pages_show_list,pages_read_engagement,pages_manage_posts,business_management,"
                     "instagram_basic,instagram_content_publish"})
    if app == "tiktok":
        return "https://www.tiktok.com/v2/auth/authorize/?" + urlencode({
            "client_key": cid, "redirect_uri": redirect, "state": st, "response_type": "code",
            "scope": "user.info.basic,video.publish"})
    raise RuntimeError("Rede desconhecida")


def finish_login(app: str, code: str, redirect: str) -> None:
    c = app_cred(app)
    cid, sec, via = c.get("client_id"), c.get("client_secret"), c.get("via")
    if app == "youtube":
        r = httpx.post("https://oauth2.googleapis.com/token", data={
            "code": code, "client_id": cid, "client_secret": sec, "redirect_uri": redirect,
            "grant_type": "authorization_code"}, timeout=30)
        js = _ok(r, "Google")
        acc = {"refresh_token": js.get("refresh_token"), "access_token": js["access_token"],
               "expires": time.time() + js.get("expires_in", 3600) - 60, "via": via}
        ch = httpx.get("https://www.googleapis.com/youtube/v3/channels", params={"part": "snippet", "mine": "true"},
                       headers={"Authorization": f"Bearer {acc['access_token']}"}, timeout=30)
        items = (ch.json() or {}).get("items") or [] if ch.status_code == 200 else []
        acc["channel"] = items[0]["snippet"]["title"] if items else "Canal do YouTube"
        if not acc["refresh_token"]:
            raise RuntimeError("O Google não devolveu acesso permanente. Remova o acesso do app na sua conta Google e conecte de novo.")
        save_account("youtube", acc)
    elif app == "meta":
        r = httpx.get(f"{GRAPH}/oauth/access_token", params={"client_id": cid, "client_secret": sec,
                                                              "redirect_uri": redirect, "code": code}, timeout=30)
        short = _ok(r, "Facebook")["access_token"]
        r = httpx.get(f"{GRAPH}/oauth/access_token", params={"grant_type": "fb_exchange_token", "client_id": cid,
                                                              "client_secret": sec, "fb_exchange_token": short}, timeout=30)
        long_tok = _ok(r, "Facebook")["access_token"]
        r = httpx.get(f"{GRAPH}/me/accounts", params={"access_token": long_tok, "limit": 100,
                                                        "fields": "id,name,access_token,instagram_business_account{id,username}"}, timeout=30)
        pages = []
        for pg in _ok(r, "Facebook").get("data", []):
            ig = pg.get("instagram_business_account") or {}
            pages.append({"id": pg["id"], "name": pg["name"], "token": pg["access_token"],
                          "ig_id": ig.get("id"), "ig_user": ig.get("username")})
        if not pages:
            raise RuntimeError("Nenhuma página do Facebook encontrada nesta conta. O Instagram precisa estar ligado a uma página.")
        best = next((p for p in pages if p.get("ig_id")), pages[0])
        save_account("meta", {"user_token": long_tok, "pages": pages, "page_id": best["id"], "via": via})
    elif app == "tiktok":
        r = httpx.post("https://open.tiktokapis.com/v2/oauth/token/", data={
            "client_key": cid, "client_secret": sec, "code": code, "grant_type": "authorization_code",
            "redirect_uri": redirect}, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
        js = _ok(r, "TikTok")
        acc = {"access_token": js["access_token"], "refresh_token": js["refresh_token"],
               "expires": time.time() + js.get("expires_in", 86400) - 120, "open_id": js.get("open_id"), "via": via}
        u = httpx.get("https://open.tiktokapis.com/v2/user/info/", params={"fields": "display_name"},
                      headers={"Authorization": f"Bearer {acc['access_token']}"}, timeout=30)
        acc["user"] = ((u.json().get("data") or {}).get("user") or {}).get("display_name", "TikTok") if u.status_code == 200 else "TikTok"
        save_account("tiktok", acc)


def select_page(page_id: str) -> None:
    with _lock:
        acc = _read(ACCOUNTS, {})
        if "meta" in acc and any(p["id"] == page_id for p in acc["meta"]["pages"]):
            acc["meta"]["page_id"] = page_id
            _write(ACCOUNTS, acc)


def _ok(r: httpx.Response, who: str) -> dict:
    try:
        js = r.json()
    except Exception:
        js = {}
    if r.status_code >= 400 or (isinstance(js, dict) and js.get("error") and not (isinstance(js.get("error"), dict) and js["error"].get("code") == "ok") and not js.get("access_token")):
        err = js.get("error") if isinstance(js, dict) else None
        msg = (err.get("message") if isinstance(err, dict) else None) or js.get("error_description") or \
            (err if isinstance(err, str) else None) or r.text[:300]
        raise RuntimeError(f"{who} recusou: {msg}")
    return js


def _google_token() -> str:
    acc = accounts().get("youtube") or {}
    if acc.get("access_token") and acc.get("expires", 0) > time.time():
        return acc["access_token"]
    c = app_cred("youtube", acc.get("via"))
    r = httpx.post("https://oauth2.googleapis.com/token", data={
        "client_id": c.get("client_id"), "client_secret": c.get("client_secret"),
        "refresh_token": acc.get("refresh_token"), "grant_type": "refresh_token"}, timeout=30)
    js = _ok(r, "Google")
    acc.update(access_token=js["access_token"], expires=time.time() + js.get("expires_in", 3600) - 60)
    save_account("youtube", acc)
    return acc["access_token"]


def _tiktok_token() -> str:
    acc = accounts().get("tiktok") or {}
    if acc.get("access_token") and acc.get("expires", 0) > time.time():
        return acc["access_token"]
    c = app_cred("tiktok", acc.get("via"))
    r = httpx.post("https://open.tiktokapis.com/v2/oauth/token/", data={
        "client_key": c.get("client_id"), "client_secret": c.get("client_secret"),
        "grant_type": "refresh_token", "refresh_token": acc.get("refresh_token")},
        headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
    js = _ok(r, "TikTok")
    acc.update(access_token=js["access_token"], refresh_token=js.get("refresh_token", acc.get("refresh_token")),
               expires=time.time() + js.get("expires_in", 86400) - 120)
    save_account("tiktok", acc)
    return acc["access_token"]


def _meta_page() -> dict:
    acc = accounts().get("meta") or {}
    if not acc.get("pages"):
        raise RuntimeError("Conecte o Facebook/Instagram em Redes sociais.")
    return next((p for p in acc["pages"] if p["id"] == acc.get("page_id")), acc["pages"][0])


# ----------------------------- envio para cada rede -----------------------------

def post_youtube(path: Path, it: dict, log) -> str:
    tok = _google_token()
    size = path.stat().st_size
    title = (it.get("title") or "Vídeo")[:95]
    desc = it.get("caption") or ""
    if it.get("shorts", True) and "#shorts" not in desc.lower():
        desc = (desc + "\n\n#shorts").strip()
    meta = {"snippet": {"title": title, "description": desc[:4900], "categoryId": "22"},
            "status": {"privacyStatus": it.get("privacy", "public"), "selfDeclaredMadeForKids": False}}
    r = httpx.post("https://www.googleapis.com/upload/youtube/v3/videos",
                   params={"uploadType": "resumable", "part": "snippet,status"},
                   headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=UTF-8",
                            "X-Upload-Content-Length": str(size), "X-Upload-Content-Type": "video/mp4"},
                   json=meta, timeout=60)
    _ok(r, "YouTube")
    url = r.headers.get("Location")
    log(0.2, "Enviando o vídeo para o YouTube…")
    with open(path, "rb") as fh:
        r = httpx.put(url, content=fh, headers={"Content-Length": str(size), "Content-Type": "video/mp4"}, timeout=None)
    vid = _ok(r, "YouTube").get("id")
    return f"https://youtube.com/shorts/{vid}" if vid else ""


def post_instagram(path: Path, it: dict, log) -> str:
    page = _meta_page()
    if not page.get("ig_id"):
        raise RuntimeError("A página escolhida não tem um Instagram profissional ligado.")
    tok, ig = page["token"], page["ig_id"]
    r = httpx.post(f"{GRAPH}/{ig}/media", data={"media_type": "REELS", "upload_type": "resumable",
                                                "caption": (it.get("caption") or "")[:2200], "share_to_feed": "true",
                                                "access_token": tok}, timeout=60)
    cid = _ok(r, "Instagram")["id"]
    size = path.stat().st_size
    log(0.2, "Enviando o vídeo para o Instagram…")
    with open(path, "rb") as fh:
        r = httpx.post(f"https://rupload.facebook.com/ig-api-upload/v21.0/{cid}", content=fh,
                       headers={"Authorization": f"OAuth {tok}", "offset": "0", "file_size": str(size)}, timeout=None)
    _ok(r, "Instagram")
    for k in range(30):  # o Instagram processa o vídeo antes de publicar
        log(0.5 + k / 70, "O Instagram está processando o vídeo…")
        st = httpx.get(f"{GRAPH}/{cid}", params={"fields": "status_code,status", "access_token": tok}, timeout=30).json()
        code = st.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"O Instagram não aceitou o vídeo: {st.get('status', code)}")
        time.sleep(20)
    else:
        raise RuntimeError("O Instagram demorou demais para processar o vídeo. Tente de novo mais tarde.")
    r = httpx.post(f"{GRAPH}/{ig}/media_publish", data={"creation_id": cid, "access_token": tok}, timeout=60)
    mid = _ok(r, "Instagram")["id"]
    link = httpx.get(f"{GRAPH}/{mid}", params={"fields": "permalink", "access_token": tok}, timeout=30).json()
    return link.get("permalink", "")


def post_facebook(path: Path, it: dict, log) -> str:
    page = _meta_page()
    tok, pid = page["token"], page["id"]
    r = httpx.post(f"{GRAPH}/{pid}/video_reels", data={"upload_phase": "start", "access_token": tok}, timeout=60)
    vid = _ok(r, "Facebook")["video_id"]
    size = path.stat().st_size
    log(0.2, "Enviando o vídeo para o Facebook…")
    with open(path, "rb") as fh:
        r = httpx.post(f"https://rupload.facebook.com/video-upload/v21.0/{vid}", content=fh,
                       headers={"Authorization": f"OAuth {tok}", "offset": "0", "file_size": str(size)}, timeout=None)
    _ok(r, "Facebook")
    r = httpx.post(f"{GRAPH}/{pid}/video_reels", data={"upload_phase": "finish", "video_id": vid,
                                                       "video_state": "PUBLISHED", "access_token": tok,
                                                       "description": (it.get("caption") or "")[:2200]}, timeout=60)
    _ok(r, "Facebook")
    return f"https://www.facebook.com/reel/{vid}"


def post_tiktok(path: Path, it: dict, log) -> str:
    tok = _tiktok_token()
    h = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=UTF-8"}
    info = _ok(httpx.post("https://open.tiktokapis.com/v2/post/publish/creator_info/query/", headers=h, timeout=30), "TikTok")
    opts = ((info.get("data") or {}).get("privacy_level_options")) or ["SELF_ONLY"]
    want = "PUBLIC_TO_EVERYONE" if it.get("privacy", "public") == "public" else "SELF_ONLY"
    privacy = want if want in opts else ("SELF_ONLY" if "SELF_ONLY" in opts else opts[0])
    size = path.stat().st_size
    chunk = size if size <= 64 * 1024 * 1024 else 10 * 1024 * 1024
    total = 1 if chunk == size else max(1, size // chunk)
    body = {"post_info": {"title": (it.get("caption") or it.get("title") or "")[:2200], "privacy_level": privacy,
                          "disable_duet": False, "disable_comment": False, "disable_stitch": False},
            "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": total}}
    _u = "https://open.tiktokapis.com/v2/post/publish/video/init/"
    _r = httpx.post(_u, headers=h, json=body, timeout=60)
    if _r.status_code >= 400 and privacy != "SELF_ONLY":  # app ainda nao aprovado: TikTok so aceita privado
        privacy = body["post_info"]["privacy_level"] = "SELF_ONLY"
        _r = httpx.post(_u, headers=h, json=body, timeout=60)
    js = _ok(_r, "TikTok")
    data = js.get("data") or {}
    url, pub = data.get("upload_url"), data.get("publish_id")
    with open(path, "rb") as fh:
        for k in range(total):
            start = k * chunk
            end = size - 1 if k == total - 1 else start + chunk - 1
            fh.seek(start)
            part = fh.read(end - start + 1)
            log(0.2 + 0.6 * k / total, "Enviando o vídeo para o TikTok…")
            r = httpx.put(url, content=part, headers={"Content-Range": f"bytes {start}-{end}/{size}",
                                                      "Content-Type": "video/mp4", "Content-Length": str(len(part))}, timeout=None)
            if r.status_code >= 400:
                raise RuntimeError(f"TikTok recusou o envio: {r.text[:200]}")
    for _ in range(30):
        st = _ok(httpx.post("https://open.tiktokapis.com/v2/post/publish/status/fetch/", headers=h,
                            json={"publish_id": pub}, timeout=30), "TikTok").get("data") or {}
        if st.get("status") == "PUBLISH_COMPLETE":
            break
        if st.get("status") == "FAILED":
            raise RuntimeError(f"O TikTok não publicou: {st.get('fail_reason', 'erro')}")
        time.sleep(10)
    if privacy != "PUBLIC_TO_EVERYONE":
        it["_note"] = "Publicado como privado: o app ainda não foi aprovado pelo TikTok."
    return ""


POSTERS = {"youtube": post_youtube, "instagram": post_instagram, "facebook": post_facebook, "tiktok": post_tiktok}


# ----------------------------- fila e agenda -----------------------------

def next_slot(net: str, after: float | None = None) -> float:
    """Próximo horário livre da agenda para esta rede."""
    slots = cfg()["slots"] or [{"days": list(range(7)), "time": "19:00"}]
    taken = {round(it["when"]) for it in queue() if it["net"] == net and it["status"] in ("agendado", "publicando")}
    now = datetime.fromtimestamp(after or time.time())
    for day in range(0, 60):
        d = now + timedelta(days=day)
        cands = []
        for sl in slots:
            if d.weekday() in sl.get("days", []):
                hh, mm = (sl.get("time") or "19:00").split(":")
                t = d.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
                if t.timestamp() > time.time() + 60:
                    cands.append(t.timestamp())
        for t in sorted(cands):
            if round(t) not in taken:
                return t
    return time.time() + 3600


def add(items: list[dict]) -> list[dict]:
    with _lock:
        q = queue()
        q.extend(items)
        _save_queue(q)
    return items


def new_item(project: str, file: str, net: str, when: float, caption: str, title: str, privacy: str,
             label: str) -> dict:
    return {"id": uuid.uuid4().hex[:10], "project": project, "file": file, "net": net, "when": when,
            "caption": caption, "title": title, "privacy": privacy, "label": label, "status": "agendado",
            "created": time.time(), "url": "", "error": "", "pct": 0.0, "msg": ""}


def friendly_error(e: Exception) -> str:
    """Explica em português os erros mais comuns, mantendo o detalhe técnico no fim."""
    t = str(e) or e.__class__.__name__
    low = t.lower()
    if isinstance(e, (httpx.ConnectError, httpx.TimeoutException)) or "timed out" in low:
        return "Sem conexão com a rede social (internet caiu ou demorou demais). Tente de novo. — " + t
    if "401" in low or "expired" in low or "invalid_grant" in low or "session has" in low or "oauth" in low:
        return "O login dessa rede expirou ou foi cancelado. Vá em Redes sociais e conecte de novo. — " + t
    if "403" in low or "forbidden" in low or "permission" in low or "scope" in low:
        return "A rede recusou a permissão. Confira se o app tem as permissões de publicação aprovadas e conecte de novo. — " + t
    if "429" in low or "limit" in low or "quota" in low:
        return "Limite de postagens da rede atingido por hoje. Tente mais tarde. — " + t
    return t


def _run(it: dict) -> None:
    path = store.pdir(it["project"]) / "renders" / it["file"]
    if not path.exists():
        raise RuntimeError("O vídeo exportado não existe mais (foi apagado).")

    def log(p, m):
        update_item(it["id"], pct=round(p, 2), msg=m)
    if it["net"].startswith("dest:"):  # destino próprio: web TV, site, servidor, pasta
        from . import destinos
        url = destinos.enviar(it["net"][5:], path, it, log)
    else:
        url = POSTERS[it["net"]](path, it, log)
    update_item(it["id"], status="publicado", url=url, posted=time.time(), pct=1.0, msg=it.get("_note") or "Publicado")


def _loop() -> None:
    while True:
        try:
            due = [it for it in queue() if it["status"] == "agendado" and it["when"] <= time.time()]
            for it in sorted(due, key=lambda x: x["when"])[:1]:
                update_item(it["id"], status="publicando", msg="Começando…", pct=0.05)
                try:
                    _run(it)
                except Exception as e:  # o erro fica visível no painel, com opção de tentar de novo
                    traceback.print_exc()
                    update_item(it["id"], status="erro", error=friendly_error(e)[:400], msg="Erro")
        except Exception:
            traceback.print_exc()
        time.sleep(15)


_started = False


def start() -> None:
    global _started
    if _started:
        return
    _started = True
    # itens que estavam "publicando" quando o programa fechou voltam para a fila
    with _lock:
        q = queue()
        for it in q:
            if it["status"] == "publicando":
                it["status"] = "agendado"
        _save_queue(q)
    threading.Thread(target=_loop, daemon=True, name="autopostagem").start()

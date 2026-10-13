"""Peças compartilhadas pelas rotas (v1.8: saíram do app.py): configuração, senha, quem está pedindo,
permissões e funções de apoio. As rotas importam tudo daqui com `from .comum import *`."""
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

from ..core import (bancos, contas, destinos, importer, jobs, legal, manutencao, montagem, online, pacote, pipeline,
                    publish, store, trilhas)
from ..engine import avaliacao, capitulos, edits, frames, platforms, redes, reframe, socials, subtitles, transcribe
from ..engine import ffmpeg_tools as ff


def _versao() -> str:
    """A versão fica escrita só no app.py (os instaladores leem de lá)."""
    try:
        txt = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
        return (re.search(r'^VERSION = "(.+)"', txt, re.M) or [None, "0"])[1]
    except Exception:
        return "0"


VERSION = _versao()
FRONT = store.ROOT / "frontend"
PASSWORD = os.environ.get("APP_PASSWORD", "")
SECRET = os.environ.get("APP_SECRET") or secrets.token_hex(16)
MAX_UPLOAD_GB = float(os.environ.get("MAX_UPLOAD_GB", "20"))
HTTPS = (os.environ.get("PUBLIC_URL") or "").startswith("https://")
_FALHAS: dict[str, list[float]] = {}  # tentativas de senha erradas por IP (versão online)


# Senha: na versão online vem do instalador (APP_PASSWORD); no PC é opcional, criada em Configurações.
INTERNO = secrets.token_hex(16)  # a janela do PC (mesmo processo) usa este código para baixar arquivos
_LIVRES = ("/api/login", "/api/logout", "/api/status", "/api/meta")
_RE_OAUTH = re.compile(r"^/api/oauth/[a-z]+/(start|callback)$")  # o login das redes abre no navegador
SENHA_PADRAO = "admin123"  # v1.7: senha inicial do admin no PC; o programa pede para trocar no primeiro acesso


def _senha_base() -> str:
    # a senha trocada pelo painel (guardada só em "hash") vale mais que a do instalador da VPS
    return store.password_hash() or PASSWORD


def _senha_dono_confere(pw: str) -> bool:
    if store.password_hash():
        return store.check_password(pw)
    return bool(PASSWORD) and hmac.compare_digest(pw, PASSWORD)


def _token() -> str:
    return hmac.new(SECRET.encode(), _senha_base().encode(), hashlib.sha256).hexdigest()


def _local(request: Request) -> bool:
    return (request.client.host if request.client else "") in ("127.0.0.1", "::1", "localhost")


# ---------- contas (v1.7): quem pode o quê ----------
# Só o dono (senha do instalador) e os administradores mexem nisso; a equipe e os clientes recebem 403.
_SO_DONO = [
    ("PUT", re.compile(r"^/api/settings$")), ("POST", re.compile(r"^/api/settings/test-ai$")),
    ("*", re.compile(r"^/api/app/logo$"), ("POST", "DELETE")), ("*", re.compile(r"^/api/brand/"), ("POST", "DELETE")),
    ("*", re.compile(r"^/api/musicas"), ("POST", "DELETE")), ("PUT", re.compile(r"^/api/defaults$")),
    ("POST", re.compile(r"^/api/maintenance/")), ("*", re.compile(r"^/api/sync/")), ("*", re.compile(r"^/api/online/")),
    ("*", re.compile(r"^/api/security/")), ("PUT", re.compile(r"^/api/publish/config$")),
    ("*", re.compile(r"^/api/publish/destinos"), ("POST", "DELETE", "PUT")),
    ("*", re.compile(r"^/api/publish/(page|account|online-login)")), ("POST", re.compile(r"^/api/oauth/[a-z]+/ticket$")),
    ("POST", re.compile(r"^/api/trilhas/[^/]+/guardar$")), ("*", re.compile(r"^/api/usuarios")),
    ("POST", re.compile(r"^/api/publish/receber$")),
]


_RE_PROJ = re.compile(r"^/api/(?:projects|jobs)/([0-9a-f]{12})(?:/|$)")
_DONO_PROJ: dict[str, tuple[float, str]] = {}  # pid -> (quando leu, dono), para não abrir o project.json a cada pedido


def _bate(regra: tuple, metodo: str, path: str) -> bool:
    m, rx = regra[0], regra[1]
    if not rx.match(path):
        return False
    if m == "*":
        return len(regra) < 3 or metodo in regra[2]
    return metodo == m


def _dono_do_projeto(pid: str) -> str | None:
    hit = _DONO_PROJ.get(pid)
    if hit and time.time() - hit[0] < 30:
        return hit[1]
    try:
        dono = contas.dono_do_projeto(store.load(pid))
    except Exception:
        return None
    _DONO_PROJ[pid] = (time.time(), dono)
    return dono


def _quem(request: Request) -> dict | None:
    """Quem está pedindo: DONO (senha do instalador, programa do PC, janela do PC), uma pessoa com conta, ou None."""
    if not _senha_base():
        return contas.DONO  # programa do PC sem senha
    interno = request.headers.get("x-vox-interno", "")
    if (interno and _local(request) and hmac.compare_digest(interno, INTERNO)) \
            or hmac.compare_digest(request.cookies.get("editor_auth", ""), _token()):
        return contas.DONO
    if PASSWORD:
        return contas.da_sessao(request.cookies.get("vox_sessao", ""), SECRET)
    return None


def _negado(msg: str, code: int = 403) -> JSONResponse:
    return JSONResponse({"detail": msg}, status_code=code)


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


# ---------- contas: a própria conta e o cadastro de pessoas (v1.7) ----------

def _eu_view() -> dict:
    u = contas.eu() or contas.DONO
    out = {"id": u["id"], "nome": u["nome"], "email": u.get("email", ""), "papel": u["papel"],
           "papel_nome": contas.NOMES_PAPEIS.get(u["papel"], u["papel"]), "contas": bool(PASSWORD),
           "pode_publicar": contas.pode_publicar(), "manda_em_tudo": contas.manda_em_tudo(),
           "login": bool(_senha_base()),
           "trocar_senha": u["papel"] == "dono" and store.precisa_trocar_senha()}
    if u["papel"] != "dono":
        out["uso"] = contas.uso(contas._buscar(u["id"]) or u)
    return out


def _so_online_contas():
    if not PASSWORD:
        raise HTTPException(400, "As contas de pessoas são da versão online.")


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


def _limites(minutos: bool = True) -> None:
    """v1.7: confere o espaço e os minutos do mês da pessoa antes de receber vídeo novo."""
    try:
        contas.conferir_espaco()
        if minutos:
            contas.conferir_minutos()
    except PermissionError as e:
        raise HTTPException(403, str(e))


def _trabalho_analise(pid: str):
    """A análise em segundo plano. v1.7: na primeira análise que dá certo, os minutos contam no mês do dono do projeto."""
    def work(progress):
        try:
            res = pipeline.analyze(pid, progress)
        except Exception as e:
            pipeline._set(pid, "erro", None, str(e))
            raise
        try:
            proj = store.load(pid)
            if proj.get("owner") and not proj.get("minutos_contados"):
                contas.somar_minutos(proj["owner"], float((proj.get("media") or {}).get("duration") or 0) / 60)
                store.update(pid, lambda p: p.update(minutos_contados=True))
        except Exception:
            pass
        return res
    return work


def _start_analysis(pid: str) -> None:
    work = _trabalho_analise(pid)
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


def _is_local(request: Request) -> bool:
    return not PASSWORD and _local(request)


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


# ---------- músicas de fundo ----------

_AUDIO_OK = (".mp3", ".m4a", ".aac", ".wav", ".ogg", ".opus", ".flac")


def _app_via_online(app_name: str) -> bool:
    if PASSWORD or not online.configurado():
        return False
    st = publish.public_status()
    return not any(n["connected"] for n in st.values() if n["app"] == app_name)


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


ON = "on_"  # itens da fila que estão no online (vistos daqui do PC)


def _pelo_online(nets: list[str]) -> list[str]:
    """Redes que, neste PC, saem pelas contas conectadas no online (o PC não tem a conta, o online tem)."""
    if PASSWORD or not online.configurado():
        return []
    local = publish.public_status()
    on = (online.status_online() or {}).get("networks") or {}
    return [n for n in nets if n in publish.NETWORKS and not local[n]["connected"] and (on.get(n) or {}).get("connected")]


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


# ---------- páginas públicas exigidas pelas redes (abrem sem senha) ----------

def _pagina_legal(slug: str, request: Request) -> Response:
    base = (os.environ.get("PUBLIC_URL") or str(request.base_url)).rstrip("/")
    return Response(legal.pagina(slug, base), media_type="text/html; charset=utf-8",
                    headers={"Cache-Control": "no-cache"})


__all__ = [n for n in list(globals()) if not n.startswith("__")]

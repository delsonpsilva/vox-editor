"""Bancos de vídeos e fotos grátis (Pexels e Pixabay) direto na Biblioteca da Montagem.

As duas licenças permitem uso comercial, sem pagar e sem pedir permissão (inclusive em vídeos monetizados).
Crédito não é obrigatório, mas o editor guarda o texto pronto ("Vídeo: Fulano / Pexels") para quem quiser
colocar na descrição. Cada banco pede uma chave grátis, colocada uma vez em Inteligência artificial (no menu).

Para não virar um "baixador da internet" no servidor, só baixa arquivos que vieram de uma busca feita aqui."""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Callable, Optional

import httpx

from . import store

UA = {"User-Agent": "VOXEditor/1.2 (editor de video; contato: suporte@voxapps.app)"}
MAX_MB = 400
FONTES = {"pexels": "Pexels", "pixabay": "Pixabay"}

_cache: dict[str, tuple[float, dict]] = {}
_vistos: dict[str, dict] = {}


def chaves() -> dict:
    cfg = store.load_config()
    return {f: ((cfg.get(f) or {}).get("api_key") or "").strip() for f in FONTES}


def status() -> dict:
    ch = chaves()
    return {f: bool(ch[f]) for f in FONTES}


def _limpa(s, n: int = 120) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()[:n]


def _escolhe_video(arquivos: list[dict]) -> dict | None:
    """O maior arquivo com até 1920 de lado maior (Full HD); se não houver, o menor acima disso."""
    bons = [a for a in arquivos if a.get("url") and a.get("w") and a.get("h")]
    if not bons:
        return None
    ate_hd = [a for a in bons if max(a["w"], a["h"]) <= 1920]
    if ate_hd:
        return max(ate_hd, key=lambda a: a["w"] * a["h"])
    return min(bons, key=lambda a: a["w"] * a["h"])


def _pexels(tipo: str, q: str, pagina: int, orient: str, chave: str) -> tuple[list[dict], bool]:
    url = "https://api.pexels.com/videos/search" if tipo == "video" else "https://api.pexels.com/v1/search"
    params = {"query": q, "per_page": 24, "page": pagina, "locale": "pt-BR"}
    if orient in ("landscape", "portrait", "square"):
        params["orientation"] = orient
    r = httpx.get(url, params=params, headers={**UA, "Authorization": chave}, timeout=15.0)
    if r.status_code in (401, 403):
        raise RuntimeError("A chave do Pexels não foi aceita. Confira em Inteligência artificial (no menu).")
    if r.status_code == 429:
        raise RuntimeError("O Pexels pediu uma pausa (muitas buscas). Espere um pouco e tente de novo.")
    r.raise_for_status()
    d = r.json()
    out = []
    if tipo == "video":
        for v in d.get("videos") or []:
            arqs = [{"url": f.get("link"), "w": f.get("width"), "h": f.get("height")} for f in v.get("video_files") or []
                    if (f.get("file_type") or "").endswith("mp4")]
            esc = _escolhe_video(arqs)
            menor = min([a for a in arqs if a.get("w")], key=lambda a: a["w"] * a["h"], default=None)
            if not esc:
                continue
            autor = _limpa((v.get("user") or {}).get("name"), 60)
            out.append({"id": f"pexels-v-{v['id']}", "fonte": "pexels", "tipo": "video", "thumb": v.get("image"),
                        "previa": (menor or esc)["url"], "w": esc["w"], "h": esc["h"], "dur": v.get("duration"),
                        "autor": autor, "link": v.get("url"), "baixar": esc["url"], "ext": ".mp4",
                        "credito": f"Vídeo: {autor or 'autor'} / Pexels ({v.get('url')})"})
    else:
        for f in d.get("photos") or []:
            src = f.get("src") or {}
            autor = _limpa(f.get("photographer"), 60)
            out.append({"id": f"pexels-f-{f['id']}", "fonte": "pexels", "tipo": "foto", "thumb": src.get("medium"),
                        "previa": src.get("large"), "w": f.get("width"), "h": f.get("height"), "dur": None,
                        "autor": autor, "link": f.get("url"), "baixar": src.get("large2x") or src.get("original"),
                        "ext": ".jpg", "credito": f"Foto: {autor or 'autor'} / Pexels ({f.get('url')})",
                        "nome": _limpa(f.get("alt"), 60)})
    return out, bool(d.get("next_page"))


def _pixabay(tipo: str, q: str, pagina: int, orient: str, chave: str) -> tuple[list[dict], bool]:
    url = "https://pixabay.com/api/videos/" if tipo == "video" else "https://pixabay.com/api/"
    params = {"key": chave, "q": q[:100], "per_page": 24, "page": pagina, "safesearch": "true", "lang": "pt"}
    if tipo != "video":
        params["image_type"] = "photo"
        if orient in ("landscape", "portrait"):
            params["orientation"] = "horizontal" if orient == "landscape" else "vertical"
    r = httpx.get(url, params=params, headers=UA, timeout=15.0)
    if r.status_code in (400, 401, 403) and "key" in r.text.lower():
        raise RuntimeError("A chave do Pixabay não foi aceita. Confira em Inteligência artificial (no menu).")
    if r.status_code == 429:
        raise RuntimeError("O Pixabay pediu uma pausa (muitas buscas). Espere um pouco e tente de novo.")
    r.raise_for_status()
    d = r.json()
    out = []
    for h in d.get("hits") or []:
        autor = _limpa(h.get("user"), 60)
        if tipo == "video":
            vs = h.get("videos") or {}
            arqs = [{"url": (vs.get(k) or {}).get("url"), "w": (vs.get(k) or {}).get("width"),
                     "h": (vs.get(k) or {}).get("height")} for k in ("large", "medium", "small", "tiny")]
            esc = _escolhe_video(arqs)
            if not esc:
                continue
            if orient == "portrait" and esc["w"] > esc["h"] or orient == "landscape" and esc["h"] > esc["w"]:
                continue
            peq = vs.get("tiny") or vs.get("small") or {}
            out.append({"id": f"pixabay-v-{h['id']}", "fonte": "pixabay", "tipo": "video",
                        "thumb": peq.get("thumbnail") or (vs.get("medium") or {}).get("thumbnail"),
                        "previa": peq.get("url") or esc["url"], "w": esc["w"], "h": esc["h"], "dur": h.get("duration"),
                        "autor": autor, "link": h.get("pageURL"), "baixar": esc["url"], "ext": ".mp4",
                        "credito": f"Vídeo: {autor or 'autor'} / Pixabay ({h.get('pageURL')})",
                        "nome": _limpa(h.get("tags"), 60)})
        else:
            out.append({"id": f"pixabay-f-{h['id']}", "fonte": "pixabay", "tipo": "foto",
                        "thumb": h.get("webformatURL") or h.get("previewURL"), "previa": h.get("webformatURL"),
                        "w": h.get("imageWidth"), "h": h.get("imageHeight"), "dur": None, "autor": autor,
                        "link": h.get("pageURL"), "baixar": h.get("largeImageURL") or h.get("webformatURL"),
                        "ext": ".jpg", "credito": f"Foto: {autor or 'autor'} / Pixabay ({h.get('pageURL')})",
                        "nome": _limpa(h.get("tags"), 60)})
    total = int(d.get("totalHits") or 0)
    return out, pagina * 24 < min(total, 500)


def buscar(fonte: str, tipo: str, q: str, pagina: int = 1, orient: str = "") -> dict:
    tipo = "video" if tipo == "video" else "foto"
    q = _limpa(q, 80) or ("natureza" if tipo == "foto" else "céu nuvens")
    pagina = max(1, min(20, int(pagina or 1)))
    ch = chaves()
    fontes = [f for f in (FONTES if fonte in ("", "todos") else [fonte]) if f in FONTES and ch.get(f)]
    if not fontes:
        raise RuntimeError("Coloque uma chave grátis do Pexels ou do Pixabay em Inteligência artificial (no menu) "
                           "para buscar vídeos e fotos livres.")
    chave = f"{','.join(fontes)}|{tipo}|{q}|{pagina}|{orient}"
    hit = _cache.get(chave)
    if hit and time.time() - hit[0] < 1800:
        return hit[1]
    listas, mais, erros = [], False, []
    for f in fontes:
        try:
            itens, m = (_pexels if f == "pexels" else _pixabay)(tipo, q, pagina, orient, ch[f])
            listas.append(itens)
            mais = mais or m
        except RuntimeError as e:
            erros.append(str(e))
        except httpx.HTTPError:
            erros.append(f"O {FONTES[f]} não respondeu agora. Tente de novo em instantes.")
    if not listas and erros:
        raise RuntimeError(erros[0])
    itens = []
    for k in range(max([len(x) for x in listas] + [0])):  # intercala os bancos
        for lst in listas:
            if k < len(lst):
                itens.append(lst[k])
    for it in itens:
        _vistos[it["id"]] = it
    resp = {"itens": itens, "mais": mais, "pagina": pagina, "termo": q, "avisos": erros}
    _cache[chave] = (time.time(), resp)
    return resp


def item(bid: str) -> dict:
    it = _vistos.get(bid)
    if not it:
        raise FileNotFoundError("Item não encontrado. Faça a busca de novo.")
    return it


def baixar(bid: str, pasta: Path, progress: Optional[Callable[[float, str], None]] = None) -> tuple[Path, dict]:
    it = item(bid)
    pasta.mkdir(parents=True, exist_ok=True)
    dest = pasta / f"{bid}{it['ext']}"
    if dest.exists() and dest.stat().st_size > 0:
        return dest, it
    tmp = dest.with_suffix(".baixando")
    feito = 0
    try:
        with httpx.stream("GET", it["baixar"], headers=UA, timeout=httpx.Timeout(20.0, read=120.0),
                          follow_redirects=True) as r:
            if r.status_code != 200:
                raise RuntimeError(f"O banco não entregou o arquivo (erro {r.status_code}). Tente outro.")
            total = int(r.headers.get("content-length") or 0)
            with open(tmp, "wb") as fh:
                for b in r.iter_bytes(512 * 1024):
                    feito += len(b)
                    if feito > MAX_MB * 1024 * 1024:
                        raise RuntimeError(f"Arquivo maior que {MAX_MB} MB.")
                    fh.write(b)
                    if progress and total:
                        progress(min(0.98, feito / total), "Baixando do banco grátis…")
        if feito < 5_000:
            raise RuntimeError("O arquivo veio vazio. Tente outro.")
        tmp.replace(dest)
    except httpx.HTTPError:
        raise RuntimeError("A conexão caiu durante o download. Tente de novo.")
    finally:
        tmp.unlink(missing_ok=True)
    return dest, it

"""Trilhas sonoras livres para o fundo dos vídeos.

Busca no Openverse (catálogo aberto da Fundação WordPress que reúne músicas com licença Creative Commons do
Jamendo, ccMixter, Freesound e Wikimedia). Só entram licenças que permitem uso comercial e mistura com a voz:
CC0 (domínio público), CC BY e CC BY-SA. Nas duas últimas é obrigatório dar o crédito: o editor monta o texto
pronto para colar na descrição do vídeo.

Para não virar um "baixador da internet" no servidor, só baixa arquivos que vieram de uma busca feita aqui."""
from __future__ import annotations

import re
import time
from pathlib import Path

import httpx

API = "https://api.openverse.org/v1/audio/"
UA = {"User-Agent": "VOXEditor/1.1 (editor de video; contato: suporte@voxapps.app)"}
LICENCAS = "cc0,by,by-sa"
NOMES_LICENCA = {"cc0": "Domínio público (CC0)", "by": "CC BY", "by-sa": "CC BY-SA"}
MAX_MB = 40

# humor -> busca em inglês (o catálogo é quase todo em inglês)
HUMORES = [
    {"id": "inspirador", "nome": "Inspirador", "q": "inspirational"},
    {"id": "oracao", "nome": "Calmo / Oração", "q": "calm ambient"},
    {"id": "piano", "nome": "Piano", "q": "piano"},
    {"id": "epico", "nome": "Épico", "q": "epic cinematic"},
    {"id": "alegre", "nome": "Alegre", "q": "happy upbeat"},
    {"id": "acustico", "nome": "Violão", "q": "acoustic guitar"},
    {"id": "louvor", "nome": "Adoração", "q": "worship"},
    {"id": "orquestra", "nome": "Orquestra", "q": "orchestral"},
    {"id": "lofi", "nome": "Lo-fi", "q": "lofi chill"},
    {"id": "corporativo", "nome": "Corporativo", "q": "corporate"},
    {"id": "suspense", "nome": "Suspense", "q": "suspense dark"},
    {"id": "emocionante", "nome": "Emocionante", "q": "emotional"},
]

_cache: dict[str, tuple[float, dict]] = {}   # busca -> (hora, resposta)
_vistos: dict[str, dict] = {}                # id -> faixa (o que pode ser baixado)


def _limpa(s: str, n: int = 120) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()[:n]


def credito(f: dict) -> str:
    """Texto do crédito para a descrição do vídeo (obrigatório em CC BY e CC BY-SA)."""
    lic = NOMES_LICENCA.get(f.get("license", ""), (f.get("license") or "").upper())
    ver = f" {f['license_version']}" if f.get("license_version") and f.get("license") != "cc0" else ""
    autor = f" — {f['creator']}" if f.get("creator") else ""
    link = f" ({f['link']})" if f.get("link") else ""
    return f"Música: \"{f.get('title') or 'sem título'}\"{autor}{link} · {lic}{ver}"


def _normaliza(r: dict) -> dict | None:
    url = r.get("url") or ""
    lic = (r.get("license") or "").lower()
    if not url.startswith("https://") or lic not in NOMES_LICENCA:
        return None
    dur = r.get("duration")
    f = {"id": str(r.get("id") or ""), "title": _limpa(r.get("title")), "creator": _limpa(r.get("creator"), 80),
         "license": lic, "license_version": _limpa(r.get("license_version"), 8), "url": url,
         "link": r.get("foreign_landing_url") or r.get("detail_url") or "",
         "duration": round(dur / 1000, 1) if isinstance(dur, (int, float)) and dur else None,
         "source": _limpa(r.get("source") or r.get("provider"), 30), "genres": (r.get("genres") or [])[:4],
         "filetype": _limpa(r.get("filetype"), 6) or "mp3"}
    if not f["id"]:
        return None
    f["credito"] = credito(f)
    f["exige_credito"] = lic != "cc0"
    return f


def buscar(q: str = "", humor: str = "", pagina: int = 1) -> dict:
    termo = _limpa(q, 80) or next((h["q"] for h in HUMORES if h["id"] == humor), "background music")
    pagina = max(1, min(10, int(pagina or 1)))
    chave = f"{termo}|{pagina}"
    hit = _cache.get(chave)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    params = {"q": termo, "license": LICENCAS, "category": "music", "page_size": 20, "page": pagina,
              "mature": "false"}
    try:
        r = httpx.get(API, params=params, headers=UA, timeout=15.0, follow_redirects=True)
    except httpx.HTTPError:
        raise RuntimeError("Não consegui buscar as músicas agora. Confira a internet e tente de novo.")
    if r.status_code == 429:
        raise RuntimeError("Muitas buscas seguidas. Espere um minuto e tente de novo.")
    if r.status_code != 200:
        raise RuntimeError(f"A biblioteca de músicas não respondeu (erro {r.status_code}). Tente mais tarde.")
    dados = r.json()
    faixas = []
    for item in dados.get("results") or []:
        f = _normaliza(item)
        if f:
            faixas.append(f)
            _vistos[f["id"]] = f
    resp = {"termo": termo, "pagina": pagina, "faixas": faixas,
            "mais": pagina < int(dados.get("page_count") or 1) and pagina < 10}
    _cache[chave] = (time.time(), resp)
    return resp


def faixa(tid: str) -> dict:
    f = _vistos.get(tid)
    if not f:
        raise FileNotFoundError("Música não encontrada. Faça a busca de novo.")
    return f


def baixar(tid: str, pasta: Path) -> tuple[Path, dict]:
    """Baixa a música (só as que vieram de uma busca daqui) para a pasta. Devolve (arquivo, faixa)."""
    f = faixa(tid)
    pasta.mkdir(parents=True, exist_ok=True)
    ext = f["filetype"].lower() if f["filetype"].lower() in ("mp3", "ogg", "wav", "flac", "m4a", "opus") else "mp3"
    nome = re.sub(r"[^\w\- ]+", "", f"{f['title'] or 'musica'} - {f['creator'] or 'autor'}")[:70].strip() or "musica"
    dest = pasta / f"{nome}-{f['id'][:6]}.{ext}"
    if dest.exists() and dest.stat().st_size > 0:
        return dest, f
    tmp = dest.with_suffix(".baixando")
    total = 0
    try:
        with httpx.stream("GET", f["url"], headers=UA, timeout=httpx.Timeout(20.0, read=120.0),
                          follow_redirects=True) as r:
            if r.status_code != 200:
                raise RuntimeError(f"O site da música não entregou o arquivo (erro {r.status_code}).")
            with open(tmp, "wb") as fh:
                for b in r.iter_bytes(256 * 1024):
                    total += len(b)
                    if total > MAX_MB * 1024 * 1024:
                        raise RuntimeError(f"Música maior que {MAX_MB} MB.")
                    fh.write(b)
        if total < 10_000:
            raise RuntimeError("O arquivo da música veio vazio.")
        tmp.replace(dest)
    except httpx.HTTPError:
        raise RuntimeError("A conexão caiu ao baixar a música. Tente de novo.")
    finally:
        tmp.unlink(missing_ok=True)
    return dest, f

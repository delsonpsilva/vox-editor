"""v1.12 — Montagem com som e legenda (Super Pacote 2, parte 1).

- Legenda automática da fala: transcreve só os trechos usados na linha do tempo (com cache por mídia) e monta a
  legenda animada nos estilos do editor, no tempo da montagem. O vídeo principal reaproveita a transcrição da análise.
- Forma de onda das mídias com som (para desenhar nos pedaços da linha do tempo).
- Narração gravada direto na Montagem (o arquivo do navegador vira .m4a, com a duração certa).
- Congelar quadro: a imagem exata daquele ponto do vídeo, em tamanho original.
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from . import montagem, store
from ..engine import ffmpeg_tools as ff

Progresso = Optional[Callable[[float, str], None]]
MAX_PALAVRAS = 30000


# ---------------------------------------------------------------- legenda automática

def _juntar(faixas: list[list[float]], folga: float = 0.0) -> list[list[float]]:
    out: list[list[float]] = []
    for a, b in sorted(faixas):
        if out and a <= out[-1][1] + folga:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _faltam(precisa: list[list[float]], cobertas: list[list[float]]) -> list[list[float]]:
    """Trechos de `precisa` que ainda não estão em `cobertas` (meio segundo de tolerância)."""
    out = []
    for a, b in precisa:
        cur = a
        for ca, cb in cobertas:
            if cb <= cur + 0.5 or ca >= b:
                continue
            if ca > cur + 0.5:
                out.append([cur, ca])
            cur = max(cur, cb)
            if cur >= b - 0.5:
                break
        if b - cur > 0.5:
            out.append([cur, b])
    return out


def itens_com_fala(m: dict) -> list[dict]:
    """Pedaços que entram no som exportado: vídeo/áudio com som, volume ligado, trilha sem silenciar
    (trilha de vídeo escondida também não entra no arquivo final)."""
    tmap = {t["id"]: t for t in m.get("tracks") or []}
    midias = {x["id"]: x for x in m.get("media") or []}
    out = []
    for it in m.get("items") or []:
        if it.get("type") not in ("video", "audio"):
            continue
        tr = tmap.get(it.get("track")) or {}
        md = midias.get(it.get("src"))
        if not md or tr.get("muted") or (it["type"] == "video" and tr.get("hidden")):
            continue
        if float(it.get("volume", 1)) <= 0.01 or not (md.get("has_audio") or md.get("kind") == "audio"):
            continue
        out.append(it)
    return out


def _cache_palavras(pid: str, mid: str) -> Path:
    d = store.pdir(pid) / "cache" / "mont"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{mid}.palavras.json"


def _transcrever_trecho(src: Path, a: float, b: float, pasta: Path, progress: Progresso) -> list[dict]:
    from . import historia
    wav = pasta / f"trecho_{uuid.uuid4().hex[:8]}.wav"
    try:
        ff.run([ff.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}",
                "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)])
        if not wav.exists() or wav.stat().st_size < 3200:
            return []
        tr = historia._transcrever(str(wav), progress)
    finally:
        wav.unlink(missing_ok=True)
    out = []
    for w in tr.get("words") or []:
        t = str(w.get("w") or "").strip()
        if t:
            out.append({"w": t, "s": round(float(w["s"]) + a, 3), "e": round(float(w["e"]) + a, 3)})
    return out


def palavras_da_midia(pid: str, md: dict, precisa: list[list[float]], progress: Progresso = None,
                      contar: Optional[Callable[[float], None]] = None) -> list[dict]:
    """Palavras (no tempo do arquivo) dos trechos pedidos. Transcreve só o que ainda não foi transcrito."""
    if md["id"] == montagem.ORIGINAL:
        proj = store.load(pid)
        if proj.get("words"):
            return proj["words"]
    arq = _cache_palavras(pid, md["id"])
    cache = {"ranges": [], "words": []}
    if arq.exists():
        try:
            cache = json.loads(arq.read_text(encoding="utf-8"))
        except Exception:
            pass
    dur = float(md.get("duration") or 0) or 1e9
    falta = _juntar([[max(0.0, a - 0.6), min(dur, b + 0.6)] for a, b in _faltam(precisa, cache["ranges"])], 1.5)
    total = sum(b - a for a, b in falta) or 1
    feito = 0.0
    src = store.pdir(pid) / md["file"]
    for a, b in falta:
        if b - a < 0.3:
            continue
        def pr(x, msg, a=a, b=b, base=feito):
            if progress:
                progress(min(0.999, (base + x * (b - a)) / total), msg)
        novas = _transcrever_trecho(src, a, b, arq.parent, pr)
        # tira as palavras antigas que estavam dentro deste trecho (a transcrição nova manda)
        cache["words"] = [w for w in cache["words"] if not (a <= (w["s"] + w["e"]) / 2 <= b)] + novas
        cache["words"].sort(key=lambda w: w["s"])
        cache["ranges"] = _juntar(cache["ranges"] + [[a, b]])
        store._write_json(arq, cache)
        feito += b - a
        if contar:
            contar(b - a)
    return cache["words"]


def palavras_na_linha_do_tempo(m: dict, por_midia: dict[str, list[dict]]) -> list[dict]:
    """Leva cada palavra do arquivo para o tempo da montagem (pedaço por pedaço, com a velocidade de cada um)."""
    out = []
    for it in itens_com_fala(m):
        ws = por_midia.get(it["src"]) or []
        a, sp, st, du = float(it["in"]), float(it.get("speed") or 1), float(it["start"]), float(it["dur"])
        b = a + du * sp
        for w in ws:
            meio = (w["s"] + w["e"]) / 2
            if not (a <= meio < b):
                continue
            s = st + (w["s"] - a) / sp
            e = st + (w["e"] - a) / sp
            s, e = max(st, s), min(st + du, e)
            if e - s < 0.02:
                e = s + 0.02
            out.append({"w": str(w["w"]).strip(), "s": round(s, 3), "e": round(e, 3)})
    out.sort(key=lambda w: (w["s"], w["e"]))
    limpo: list[dict] = []
    for w in out:  # dois pedaços tocando a mesma fala ao mesmo tempo: fica uma vez só
        if limpo and w["s"] < limpo[-1]["e"] - 0.5 * (w["e"] - w["s"]):
            continue
        limpo.append(w)
    return limpo[:MAX_PALAVRAS]


def montar_legenda(words: list[dict], cfg_in: dict | None, vertical: bool) -> dict | None:
    """Legenda animada a partir das palavras (no tempo da montagem): mesmo motor da História → Vídeo e da
    edição automática. Guarda as palavras junto, para trocar o estilo e corrigir sem transcrever de novo."""
    from ..engine import subtitles as sb
    cfg_in = cfg_in if isinstance(cfg_in, dict) else {}
    estilo = cfg_in.get("style") if cfg_in.get("style") in sb.STYLES else "palavra_ativa"
    cfg = {**sb.STYLES[estilo], "style": estilo, "keywords": True, "size_pct": 125 if vertical else 110}
    if not vertical and cfg["max_chars"] < 26 and estilo != "uma_palavra":
        cfg["max_chars"] = 30
    for k in ("position", "size_pct", "highlight", "color", "keyword_color", "keywords", "uppercase", "font"):
        if k in cfg_in and cfg_in[k] is not None:
            cfg[k] = cfg_in[k]
    ws = []
    for w in (words or [])[:MAX_PALAVRAS]:
        if isinstance(w, dict) and str(w.get("w") or "").strip():
            s = float(w.get("s") or 0)
            ws.append({"w": str(w["w"]).strip()[:40], "s": round(s, 3), "e": round(max(float(w.get("e") or 0), s + 0.02), 3),
                       **({"kw": True} if w.get("kw") else {})})
    ws.sort(key=lambda x: x["s"])
    if not ws:
        return None
    caps = sb.build_captions(ws, None, cfg)
    if not caps:
        return None
    lv = {"cfg": cfg, "caps": caps, "words": ws, "auto": True}
    return montagem.legenda_viva_limpa(lv)


def gerar_legenda(pid: str, cfg_in: dict | None, progress: Progresso = None) -> dict:
    """Transcreve a fala da linha do tempo e grava a legenda animada na montagem."""
    from ..engine import destaques
    def p(x, msg):
        if progress:
            progress(x, msg)
    p(0.01, "Vendo onde tem fala na linha do tempo…")
    m = montagem.carregar(pid)
    itens = itens_com_fala(m)
    if not itens:
        raise RuntimeError("Não há vídeo ou áudio com som na linha do tempo (confira o volume e as trilhas silenciadas).")
    midias = {x["id"]: x for x in m["media"]}
    precisa: dict[str, list[list[float]]] = {}
    for it in itens:
        a = float(it["in"])
        precisa.setdefault(it["src"], []).append([a, a + float(it["dur"]) * float(it.get("speed") or 1)])
    precisa = {k: _juntar(v, 0.3) for k, v in precisa.items()}
    proj = store.load(pid)
    contado = {"s": 0.0}
    por_midia = {}
    n = len(precisa)
    for k, (mid, faixas) in enumerate(precisa.items()):
        nome = (midias[mid].get("name") or "mídia")[:40]
        por_midia[mid] = palavras_da_midia(
            pid, midias[mid], faixas,
            lambda x, msg, k=k: p(0.03 + 0.9 * (k + x) / n, f"Transcrevendo “{nome}”… {int(x * 100)}%"),
            lambda seg: contado.__setitem__("s", contado["s"] + seg))
    p(0.94, "Montando a legenda…")
    words = palavras_na_linha_do_tempo(m, por_midia)
    if len(words) < 1:
        raise RuntimeError("Não encontrei fala nos trechos da linha do tempo.")
    try:
        words = destaques.marcar(words, destaques.locais(words))
    except Exception:
        pass
    antiga = m.get("legenda_viva") or {}
    cfg = dict(antiga.get("cfg") or {})
    cfg.update({k: v for k, v in (cfg_in or {}).items() if v is not None})
    if (cfg_in or {}).get("style") and (cfg_in or {}).get("style") != (antiga.get("cfg") or {}).get("style"):
        for k in ("highlight", "color", "font", "uppercase"):  # estilo novo: as cores e a letra dele
            if k not in (cfg_in or {}):
                cfg.pop(k, None)
    lv = montar_legenda(words, cfg, m["h"] > m["w"])
    if not lv:
        raise RuntimeError("Não deu para montar a legenda com essa fala.")
    with store.lock(pid):
        atual = montagem.carregar(pid)
        atual["legenda_viva"] = lv
        store._write_json(montagem.arquivo(pid), atual)
    if contado["s"] > 0 and proj.get("owner"):  # minutos transcritos contam no mês do dono do projeto
        try:
            from . import contas
            contas.somar_minutos(proj["owner"], contado["s"] / 60)
        except Exception:
            pass
    p(1.0, "Legenda pronta!")
    return {"legenda_viva": lv, "palavras": len(words), "minutos_transcritos": round(contado["s"] / 60, 1)}


# ---------------------------------------------------------------- forma de onda

ONDA_PPS = 25  # valores por segundo


def onda(pid: str, mid: str) -> dict:
    """Picos do som (0 a 255, ONDA_PPS por segundo), em base64. Guardado em cache."""
    m = montagem.carregar(pid)
    md = next((x for x in m["media"] if x["id"] == mid), None)
    if not md or md.get("kind") == "image":
        raise FileNotFoundError("Mídia sem som")
    if not (md.get("has_audio") or md.get("kind") == "audio"):
        return {"pps": ONDA_PPS, "peaks": ""}
    src = store.pdir(pid) / md["file"]
    out = store.pdir(pid) / "cache" / "mont" / f"{mid}.onda.json"
    if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
        try:
            return json.loads(out.read_text(encoding="utf-8"))
        except Exception:
            pass
    out.parent.mkdir(parents=True, exist_ok=True)
    sr = 8000
    passo = sr // ONDA_PPS
    proc = subprocess.Popen([ff.ffmpeg(), "-hide_banner", "-loglevel", "error", "-i", str(src), "-vn", "-ac", "1",
                             "-ar", str(sr), "-f", "s16le", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            creationflags=ff.CREATE_FLAGS, **ff._POPEN_EXTRA)
    picos: list[np.ndarray] = []
    sobra = b""
    bloco = passo * 2 * 400
    try:
        while True:
            dado = proc.stdout.read(bloco)
            if not dado:
                break
            dado = sobra + dado
            n = (len(dado) // (passo * 2)) * passo * 2
            sobra = dado[n:]
            if n:
                a = np.frombuffer(dado[:n], dtype=np.int16).reshape(-1, passo)
                picos.append(np.abs(a.astype(np.int32)).max(axis=1))
        if len(sobra) >= 2:
            a = np.frombuffer(sobra[: len(sobra) // 2 * 2], dtype=np.int16)
            picos.append(np.array([int(np.abs(a.astype(np.int32)).max())]))
    finally:
        proc.stdout.close()
        proc.wait()
    v = (np.concatenate(picos) if picos else np.zeros(0)).astype(np.float32) / 32768.0
    if len(v):
        ref = max(0.05, float(np.percentile(v, 99.5)))
        v = np.clip(np.sqrt(np.clip(v / ref, 0, 1)), 0, 1)  # raiz: a fala baixa também aparece
    dados = {"pps": ONDA_PPS, "peaks": base64.b64encode((v * 255).astype(np.uint8).tobytes()).decode("ascii")}
    store._write_json(out, dados)
    return dados


# ---------------------------------------------------------------- narração e congelar quadro

def narracao(pid: str, bruto: Path) -> dict:
    """Gravação do microfone (WebM/Ogg do navegador) → .m4a com a duração certa, nas mídias da montagem."""
    pasta = montagem.pasta_midias(pid)
    m = montagem.carregar(pid)
    n = 1 + sum(1 for x in m["media"] if str(x.get("name") or "").startswith("Narração"))
    dest = pasta / f"narracao_{uuid.uuid4().hex[:8]}.m4a"
    try:
        ff.run([ff.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(bruto), "-vn", "-ac", "1",
                "-ar", "48000", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(dest)])
    finally:
        bruto.unlink(missing_ok=True)
    info = ff.probe(str(dest))
    if not info.get("has_audio") or float(info.get("duration") or 0) < 0.2:
        dest.unlink(missing_ok=True)
        raise ValueError("A gravação ficou vazia. Confira o microfone e grave de novo.")
    return montagem.adicionar_midia(pid, dest, f"Narração {n}.m4a")


def congelar(pid: str, src_id: str, t: float) -> dict:
    """Quadro exato do vídeo naquele ponto (tempo do arquivo), em PNG no tamanho original."""
    m = montagem.carregar(pid)
    md = next((x for x in m["media"] if x["id"] == src_id), None)
    if not md or md.get("kind") != "video":
        raise FileNotFoundError("Vídeo não encontrado")
    dur = float(md.get("duration") or 0)
    t = max(0.0, min(float(t), max(0.0, dur - 0.05)))
    src = store.pdir(pid) / md["file"]
    dest = montagem.pasta_midias(pid) / f"congelado_{uuid.uuid4().hex[:8]}.png"
    dec = ["-c:v", "libvpx-vp9"] if md.get("alpha") else []
    ff.run([ff.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}"] + dec +
           ["-i", str(src), "-frames:v", "1", "-pix_fmt", "rgba" if md.get("alpha") else "rgb24", str(dest)])
    if not dest.exists() or dest.stat().st_size == 0:
        raise RuntimeError("Não consegui tirar a imagem desse ponto do vídeo.")
    base = re.sub(r"\.[^.]+$", "", md.get("name") or "vídeo")[:70]
    mm, ss = divmod(int(t), 60)
    return montagem.adicionar_midia(pid, dest, f"{base} (quadro {mm}:{ss:02d}).png")

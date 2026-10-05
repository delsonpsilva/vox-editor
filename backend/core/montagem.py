"""Montagem (editor manual multicamadas): a linha do tempo do projeto com trilhas de vídeo, imagem, texto,
cor e áudio. Fica em montagem.json, dentro da pasta do projeto, junto com as mídias enviadas (pasta midias).

Tudo que a tela mostra na prévia é refeito aqui pelo FFmpeg na exportação, com as mesmas contas de posição,
tamanho, giro, transparência e esmaecimento — o que se vê é o que sai."""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

from . import efeitos as fxm
from . import store
from ..engine import edits
from ..engine import ffmpeg_tools as ff

VERSAO = 1
ORIGINAL = "original"          # id fixo da mídia principal do projeto (o vídeo analisado)
FORMATOS = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080), "4:5": (1080, 1350)}
FONTES = {  # nome mostrado na tela -> arquivo em /fontes
    "Poppins ExtraBold": "Poppins-ExtraBold.ttf",
    "Poppins": "Poppins-Bold.ttf",
    "Anton": "Anton-Regular.ttf",
    "Bebas Neue": "BebasNeue-Regular.ttf",
    "Archivo Black": "ArchivoBlack-Regular.ttf",
}
EXT_VIDEO = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".mts", ".3gp"}
EXT_IMAGEM = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
EXT_AUDIO = {".mp3", ".m4a", ".aac", ".wav", ".ogg", ".opus", ".flac", ".wma"}
TIPOS_ITEM = {"video", "image", "text", "color", "audio", "tarja"}
TIPOS_TRILHA = {"video", "text", "audio"}
MAX_ITENS = 4000


def arquivo(pid: str) -> Path:
    return store.pdir(pid) / "montagem.json"


def pasta_midias(pid: str) -> Path:
    d = store.pdir(pid) / "midias"
    d.mkdir(exist_ok=True)
    return d


def _id(prefix: str) -> str:
    return prefix + uuid.uuid4().hex[:8]


def _par(n: float) -> int:
    return max(2, int(round(n / 2)) * 2)


def tipo_por_extensao(nome: str) -> str | None:
    ext = Path(nome).suffix.lower()
    if ext in EXT_VIDEO:
        return "video"
    if ext in EXT_IMAGEM:
        return "image"
    if ext in EXT_AUDIO:
        return "audio"
    return None


# ---------------------------------------------------------------- modelo

def trilhas_padrao() -> list[dict]:
    # a ordem da lista é a ordem na tela: a primeira trilha fica por cima de todas
    return [
        {"id": "t_texto", "kind": "text", "name": "Texto 1", "hidden": False, "muted": False, "locked": False},
        {"id": "t_v2", "kind": "video", "name": "Vídeo 2", "hidden": False, "muted": False, "locked": False},
        {"id": "t_v1", "kind": "video", "name": "Vídeo 1", "hidden": False, "muted": False, "locked": False,
         "main": True},
        {"id": "t_audio", "kind": "audio", "name": "Áudio 1", "hidden": False, "muted": False, "locked": False},
    ]


def midia_original(proj: dict) -> dict | None:
    media = proj.get("media") or {}
    if not proj.get("source") or not media:
        return None
    return {"id": ORIGINAL, "name": proj.get("name") or "Vídeo principal", "file": proj["source"],
            "kind": "video" if media.get("has_video") else "audio", "duration": media.get("duration", 0),
            "w": media.get("width", 0), "h": media.get("height", 0), "has_audio": bool(media.get("has_audio")),
            "fps": media.get("fps", 30), "preview": proj.get("preview") or proj["source"], "main": True}


def nova(proj: dict, formato: str | None = None, com_edicao: bool = True) -> dict:
    """Montagem nova. Se o projeto já tem vídeo analisado, ele entra na trilha principal com os cortes
    automáticos já aplicados (cada trecho mantido vira um item)."""
    media = proj.get("media") or {}
    orig = midia_original(proj)
    if not formato:
        formato = "9:16" if media.get("height", 0) > media.get("width", 1) else "16:9"
    w, h = FORMATOS.get(formato, FORMATOS["16:9"])
    fps = 30
    if media.get("fps"):
        fps = 60 if media["fps"] > 45 else (25 if abs(media["fps"] - 25) < 0.5 else 30)
    m = {"v": VERSAO, "formato": formato, "w": w, "h": h, "fps": fps, "bg": "#000000", "suave": "suave",
         "tracks": trilhas_padrao(), "items": [], "media": [orig] if orig else [], "updated": time.time()}
    if orig and orig["kind"] == "video" and com_edicao:
        keeps = []
        if proj.get("status") == "pronto" and proj.get("words") is not None:
            try:
                keeps = edits.build_edit(proj)["keeps"]
            except Exception:
                keeps = []
        if not keeps:
            keeps = [[0.0, float(orig["duration"] or 0)]]
        keeps = edits.snap_keeps(keeps, fps)
        t = 0.0
        for s, e in keeps:
            d = round(e - s, 4)
            if d < 1.0 / fps:
                continue
            m["items"].append(_item_base("video", "t_v1", ORIGINAL, t, d, s, fit="cover"))
            t = round(t + d, 4)
    elif orig and orig["kind"] == "audio" and com_edicao:
        m["items"].append(_item_base("audio", "t_audio", ORIGINAL, 0.0, float(orig["duration"] or 0), 0.0))
    return m


def _item_base(kind: str, track: str, src: str | None, start: float, dur: float, src_in: float = 0.0, **kw) -> dict:
    it = {"id": _id("i"), "type": kind, "track": track, "src": src, "start": round(start, 4), "dur": round(dur, 4),
          "in": round(src_in, 4), "x": 0.5, "y": 0.5, "scale": 1.0, "rot": 0.0, "opacity": 1.0, "volume": 1.0,
          "fadeIn": 0.0, "fadeOut": 0.0, "speed": 1.0, "fit": "contain"}
    it.update(kw)
    return it


def carregar(pid: str) -> dict:
    """Lê a montagem do projeto (cria na primeira vez). Mantém a mídia principal sempre atualizada."""
    proj = store.load(pid)
    f = arquivo(pid)
    with store.lock(pid):
        if f.exists():
            try:
                m = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                m = nova(proj)
        else:
            m = nova(proj, proj.get("formato"))
            store._write_json(f, m)
        orig = midia_original(proj)
        lista = [x for x in m.get("media") or [] if x.get("id") != ORIGINAL]
        m["media"] = ([orig] if orig else []) + lista
        return m


def _num(v, padrao: float, lo: float, hi: float) -> float:
    try:
        v = float(v)
        if math.isnan(v) or math.isinf(v):
            return padrao
        return max(lo, min(hi, v))
    except (TypeError, ValueError):
        return padrao


def _cor(v, padrao: str) -> str:
    return v if isinstance(v, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", v) else padrao


def limpar(m: dict, atual: dict) -> dict:
    """Valida o que veio da tela antes de gravar (nunca confia no navegador)."""
    formato = m.get("formato") if m.get("formato") in FORMATOS else atual.get("formato", "16:9")
    w, h = FORMATOS[formato]
    fps = int(m.get("fps") or atual.get("fps") or 30)
    fps = fps if fps in (24, 25, 30, 50, 60) else 30
    midias = {x["id"]: x for x in atual.get("media") or []}
    tracks = []
    for t in (m.get("tracks") or [])[:40]:
        if not isinstance(t, dict) or t.get("kind") not in TIPOS_TRILHA:
            continue
        tracks.append({"id": str(t.get("id") or _id("t"))[:24], "kind": t["kind"],
                       "name": str(t.get("name") or "Trilha")[:40], "hidden": bool(t.get("hidden")),
                       "muted": bool(t.get("muted")), "locked": bool(t.get("locked")),
                       **({"main": True} if t.get("main") else {})})
    if not tracks:
        tracks = trilhas_padrao()
    tids = {t["id"]: t for t in tracks}
    items = []
    for it in (m.get("items") or [])[:MAX_ITENS]:
        if not isinstance(it, dict) or it.get("type") not in TIPOS_ITEM or it.get("track") not in tids:
            continue
        k = it["type"]
        src = it.get("src")
        if k in ("video", "image", "audio"):
            if src not in midias:
                continue
        else:
            src = None
        novo = {
            "id": str(it.get("id") or _id("i"))[:24], "type": k, "track": it["track"], "src": src,
            "start": round(_num(it.get("start"), 0, 0, 36000), 4),
            "dur": round(_num(it.get("dur"), 3, 1 / 120, 36000), 4),
            "in": round(_num(it.get("in"), 0, 0, 36000), 4),
            "x": _num(it.get("x"), 0.5, -2, 3), "y": _num(it.get("y"), 0.5, -2, 3),
            "scale": _num(it.get("scale"), 1, 0.02, 20), "rot": _num(it.get("rot"), 0, -360, 360),
            "opacity": _num(it.get("opacity"), 1, 0, 1), "volume": _num(it.get("volume"), 1, 0, 4),
            "fadeIn": _num(it.get("fadeIn"), 0, 0, 30), "fadeOut": _num(it.get("fadeOut"), 0, 0, 30),
            "speed": _num(it.get("speed"), 1, 0.25, 4), "fit": "cover" if it.get("fit") == "cover" else "contain",
        }
        if k == "text":
            novo.update(text=str(it.get("text") or "")[:600], font=it.get("font") if it.get("font") in FONTES else
                        "Poppins ExtraBold", size=_num(it.get("size"), 0.07, 0.01, 0.6),
                        color=_cor(it.get("color"), "#FFFFFF"), stroke=_cor(it.get("stroke"), "#000000"),
                        strokeW=_num(it.get("strokeW"), 0, 0, 0.3), box=_cor(it.get("box"), "#000000"),
                        boxOn=bool(it.get("boxOn")), boxAlpha=_num(it.get("boxAlpha"), 0.6, 0, 1),
                        upper=bool(it.get("upper")))
        if k == "tarja":
            from . import tarjas as _tj
            ids = {x["id"] for x in _tj.spec()["modelos"]}
            pal = _tj.spec()["paletas"][0]
            novo.update(tpl=it.get("tpl") if it.get("tpl") in ids else next(iter(ids)),
                        l1=str(it.get("l1") or "")[:120], l2=str(it.get("l2") or "")[:120],
                        **{c: _cor(it.get(c), pal[c]) for c in ("c1", "c2", "t1", "t2")})
        if k == "color":
            novo.update(color=_cor(it.get("color"), "#1B1C21"), w=_num(it.get("w"), 1, 0.01, 4),
                        h=_num(it.get("h"), 1, 0.01, 4))
        if k == "image":
            novo["speed"] = 1.0
        if k == "audio":
            novo["duck"] = bool(it.get("duck"))
        # 1.2: filtros de cor, fundo verde, transição de entrada e animação por quadros-chave
        if k in ("video", "image"):
            fx = fxm.fx_limpo(it.get("fx"))
            if fx:
                novo["fx"] = fx
            ch = fxm.chroma_limpo(it.get("chroma"))
            if ch:
                novo["chroma"] = ch
        if k in ("video", "image", "color") and tids[it["track"]]["kind"] == "video":
            tr = fxm.tr_limpa(it.get("tr"), novo["dur"])
            if tr:
                novo["tr"] = tr
        if k in ("video", "image", "color", "text"):
            kf = fxm.kf_limpo(it.get("kf"), novo)
            if kf:
                novo["kf"] = kf
        items.append(novo)
    return {"v": VERSAO, "formato": formato, "w": w, "h": h, "fps": fps, "bg": _cor(m.get("bg"), "#000000"),
            "suave": m.get("suave") if m.get("suave") in SUAVE_MONTAGEM else "suave",
            "tracks": tracks, "items": items, "media": atual.get("media") or [], "updated": time.time()}


def salvar(pid: str, m: dict) -> dict:
    with store.lock(pid):
        atual = carregar(pid)
        limpo = limpar(m, atual)
        store._write_json(arquivo(pid), limpo)
        return limpo


def recomecar(pid: str, formato: str | None = None) -> dict:
    proj = store.load(pid)
    with store.lock(pid):
        atual = carregar(pid)
        m = nova(proj, formato or atual.get("formato"))
        m["media"] = atual.get("media") or m["media"]
        store._write_json(arquivo(pid), m)
        return m


# ---------------------------------------------------------------- mídias

def adicionar_midia(pid: str, origem: Path, nome: str, extra: dict | None = None) -> dict:
    """Registra um arquivo já gravado em midias/. Descobre duração e tamanho; prepara prévia se precisar."""
    kind = tipo_por_extensao(nome) or "video"
    info = ff.probe(str(origem))
    if kind == "video" and not info.get("has_video"):
        kind = "audio"
    if kind == "audio" and not info.get("has_audio"):
        raise ValueError("Esse arquivo não tem som.")
    if kind == "image" and not info.get("width"):
        raise ValueError("Não consegui abrir essa imagem.")
    item = {"id": _id("m"), "name": nome[:120], "file": "midias/" + origem.name, "kind": kind,
            "duration": round(info.get("duration") or 0, 3) if kind != "image" else 0,
            "w": info.get("width", 0), "h": info.get("height", 0), "has_audio": bool(info.get("has_audio")),
            "fps": info.get("fps", 30), "size": origem.stat().st_size, "added": time.time()}
    if extra:  # ex.: crédito e licença de uma trilha da biblioteca livre
        item.update({k: v for k, v in extra.items() if k in ("credito", "licenca", "trilha", "banco", "alpha",
                                                              "substitui", "semfundo")})
    if kind == "image" and Path(nome).suffix.lower() == ".gif":
        item["kind"] = "image"
    if kind == "video" and item.get("alpha"):
        item["preview"] = item["file"]  # WebM com transparência: o navegador mostra direto (a cópia leve perderia o fundo)
    elif kind == "video" and not ff.browser_friendly(info, str(origem)):
        item["preview"] = None  # a prévia leve é feita em segundo plano (vídeos do iPhone, .mkv, 4K...)
        item["needs_proxy"] = True
    else:
        item["preview"] = item["file"]
    with store.lock(pid):
        m = carregar(pid)
        m["media"].append(item)
        store._write_json(arquivo(pid), m)
    return item


def gerar_previa(pid: str, mid: str, progress: Optional[Callable[[float, str], None]] = None) -> dict:
    """Cópia leve (720p, H.264) para tocar no navegador e no celular. A exportação usa sempre o original."""
    m = carregar(pid)
    it = next((x for x in m["media"] if x["id"] == mid), None)
    if not it:
        raise FileNotFoundError("Mídia não encontrada")
    folder = store.pdir(pid)
    src = folder / it["file"]
    out = folder / "midias" / f"previa_{mid}.mp4"
    tmp = out.with_suffix(".tmp.mp4")
    ff.run_with_progress([ff.ffmpeg(), "-y", "-i", str(src), "-vf",
                          "scale='if(gt(iw,ih),-2,720)':'if(gt(iw,ih),720,-2)',format=yuv420p", "-c:v", "libx264",
                          "-preset", "veryfast", "-crf", "24", "-g", "30", "-c:a", "aac", "-b:a", "128k",
                          "-movflags", "+faststart", str(tmp)], it.get("duration") or 1,
                         lambda x: progress and progress(x, "Preparando prévia da mídia…"))
    os.replace(tmp, out)
    with store.lock(pid):
        m = carregar(pid)
        for x in m["media"]:
            if x["id"] == mid:
                x["preview"] = "midias/" + out.name
                x.pop("needs_proxy", None)
        store._write_json(arquivo(pid), m)
    return {"media": mid}


def remover_midia(pid: str, mid: str) -> dict:
    if mid == ORIGINAL:
        raise ValueError("O vídeo principal do projeto não pode ser removido daqui.")
    folder = store.pdir(pid)
    with store.lock(pid):
        m = carregar(pid)
        it = next((x for x in m["media"] if x["id"] == mid), None)
        if not it:
            raise FileNotFoundError("Mídia não encontrada")
        for rel in {it.get("file"), it.get("preview")}:
            if rel and rel.startswith("midias/"):
                (folder / rel).unlink(missing_ok=True)
        m["media"] = [x for x in m["media"] if x["id"] != mid]
        m["items"] = [x for x in m["items"] if x.get("src") != mid]
        store._write_json(arquivo(pid), m)
        return m


def sem_fundo(pid: str, item_id: str, progress: Optional[Callable[[float, str], None]] = None) -> dict:
    """Tira o fundo (IA) da mídia de um pedaço da linha do tempo. Só processa o trecho usado (vídeo).
    A mídia nova fica marcada com "substitui": a tela troca o pedaço por ela assim que vê (montagem.js)."""
    from . import fundo_ia
    if not fundo_ia.disponivel():
        raise RuntimeError("A remoção de fundo precisa do componente de IA (onnxruntime). No PC, rode o ATUALIZAR.bat.")
    m = carregar(pid)
    it = next((x for x in m["items"] if x["id"] == item_id), None)
    if not it or it["type"] not in ("video", "image"):
        raise FileNotFoundError("Pedaço não encontrado. Salve a montagem e tente de novo.")
    md = next((x for x in m["media"] if x["id"] == it["src"]), None)
    if not md:
        raise FileNotFoundError("Mídia não encontrada")
    folder = store.pdir(pid)
    origem = folder / md["file"]
    base = re.sub(r"\.[^.]+$", "", md.get("name") or "midia")[:80]
    if it["type"] == "image":
        destino = pasta_midias(pid) / f"semfundo_{uuid.uuid4().hex[:8]}.png"
        fundo_ia.foto(origem, destino, progress)
        nova_m = adicionar_midia(pid, destino, f"{base} (sem fundo).png",
                                 {"semfundo": True, "substitui": {"item": item_id, "src": md["id"], "in": 0.0}})
    else:
        info = ff.probe(str(origem))
        ini = max(0.0, it["in"] - 0.3)
        fim = min(float(info.get("duration") or md.get("duration") or 0), it["in"] + it["dur"] * it["speed"] + 0.3)
        if fim - ini > fundo_ia.MAX_SEG:
            raise RuntimeError("Esse pedaço é muito longo para tirar o fundo de uma vez (máximo 10 minutos). "
                               "Divida o pedaço e tente por partes.")
        destino = pasta_midias(pid) / f"semfundo_{uuid.uuid4().hex[:8]}.webm"
        fundo_ia.video(origem, ini, fim - ini, destino, info, progress)
        nova_m = adicionar_midia(pid, destino, f"{base} (sem fundo).webm",
                                 {"semfundo": True, "alpha": True,
                                  "substitui": {"item": item_id, "src": md["id"], "in": round(ini, 4)}})
    return {"media": nova_m, "item": item_id}


def substituicao_aplicada(pid: str, mid: str) -> dict:
    with store.lock(pid):
        m = carregar(pid)
        for x in m["media"]:
            if x["id"] == mid:
                x.pop("substitui", None)
        store._write_json(arquivo(pid), m)
        return m


def caminho_midia(pid: str, mid: str, previa: bool) -> Path:
    m = carregar(pid)
    it = next((x for x in m["media"] if x["id"] == mid), None)
    if not it:
        raise FileNotFoundError("Mídia não encontrada")
    rel = (it.get("preview") if previa else None) or it["file"]
    f = (store.pdir(pid) / rel).resolve()
    if store.pdir(pid).resolve() not in f.parents or not f.exists():
        raise FileNotFoundError("Arquivo da mídia não encontrado")
    return f


def miniatura(pid: str, mid: str, t: float = 0.0) -> Path:
    """Quadro pequeno (para a linha do tempo e a lista de mídias), guardado em cache."""
    m = carregar(pid)
    it = next((x for x in m["media"] if x["id"] == mid), None)
    if not it or it["kind"] == "audio":
        raise FileNotFoundError("Sem imagem")
    t = round(max(0.0, min(t, max(0.0, (it.get("duration") or 0) - 0.1))), 1)
    out = store.pdir(pid) / "cache" / "mont" / f"{mid}_{t:.1f}.jpg"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        src = caminho_midia(pid, mid, previa=True)
        ff.run([ff.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error"] + (["-ss", f"{t:.2f}"] if t > 0 else [])
               + ["-i", str(src), "-frames:v", "1", "-vf", "scale=-2:120", "-q:v", "5", str(out)])
    return out


# ---------------------------------------------------------------- exportação

def duracao(m: dict) -> float:
    return max([it["start"] + it["dur"] for it in m.get("items") or []] + [0.0])


def _tamanho(it: dict, midia: dict | None, W: int, H: int) -> tuple[int, int]:
    """Mesmas contas da prévia: encaixa a mídia na tela (inteira ou preenchendo) e aplica a escala."""
    if it["type"] == "color":
        return _par(W * it.get("w", 1) * it["scale"]), _par(H * it.get("h", 1) * it["scale"])
    aw, ah = (midia or {}).get("w") or W, (midia or {}).get("h") or H
    k = (max if it.get("fit") == "cover" else min)(W / aw, H / ah) * it["scale"]
    return _par(aw * k), _par(ah * k)


# suavidade das emendas de áudio da montagem (as janelas ficam em engine/render.py: SUAVIDADE)
SUAVE_MONTAGEM = {"seca": 0.0, "suave": 0.035, "bem_suave": 0.07}


def _atempo(speed: float) -> str:
    parts, s = [], speed
    while s > 2.0:
        parts.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        parts.append("atempo=0.5")
        s /= 0.5
    parts.append(f"atempo={s:.5f}")
    return ",".join(parts)



def _linhas(it: dict) -> list[str]:
    t = it.get("text") or ""
    if it.get("upper"):
        t = t.upper()
    return [ln for ln in t.split("\n")] or [""]


def _mesclavel(a: dict, b: dict, fps: float) -> bool:
    """Dois trechos seguidos do mesmo vídeo, com o mesmo enquadramento: viram uma só entrada no FFmpeg."""
    if a["src"] != b["src"] or a["type"] != "video":
        return False
    if a.get("kf") or b.get("kf") or a.get("tr") or b.get("tr") or a.get("_ext") or b.get("_ext"):
        return False
    if a.get("fx") != b.get("fx") or a.get("chroma") != b.get("chroma"):
        return False
    for k in ("x", "y", "scale", "rot", "opacity", "fit", "volume"):
        if abs(float(a[k]) - float(b[k])) > 1e-6 if k != "fit" else a[k] != b[k]:
            return False
    if a["speed"] != 1 or b["speed"] != 1 or a["fadeIn"] or a["fadeOut"] or b["fadeIn"] or b["fadeOut"]:
        return False
    if abs((a["start"] + a["dur"]) - b["start"]) > 0.6 / fps:
        return False
    return b["in"] >= a["in"] + a["dur"] - 0.6 / fps and b["in"] - (a["in"] + a["dur"]) < 30.0


def _grupos(items: list[dict], fps: float) -> list[list[dict]]:
    out: list[list[dict]] = []
    for it in sorted(items, key=lambda x: x["start"]):
        if out and _mesclavel(out[-1][-1], it, fps):
            out[-1].append(it)
        else:
            out.append([it])
    return out


def _alfa(it: dict, lt: float) -> float:
    """Transparência do item no tempo local lt: opacidade (com quadros-chave) x entrada/saída suave x transição.
    Mesma conta da prévia (alfaK no montagem.js)."""
    a = max(0.0, min(1.0, fxm.valor(it, "opacity", lt)))
    dur = it["dur"]
    if it.get("fadeIn", 0) > 0:
        a *= max(0.0, min(1.0, lt / it["fadeIn"]))
    if it.get("fadeOut", 0) > 0:
        a *= max(0.0, min(1.0, (dur - lt) / it["fadeOut"]))
    tr = it.get("tr")
    if tr:
        a *= fxm.tr_entrada(tr["tipo"], lt / tr["dur"], 1, 1)["a"]
    return a


def _texto_png(it: dict, W: int, H: int, escala: float, destino: Path) -> tuple[int, int]:
    """Desenha o texto (mesmas fontes e contas da prévia) num PNG transparente, recortado em volta do centro.
    O FFmpeg não mistura bem a transparência ao escrever num fundo vazio, então o texto é desenhado duas vezes
    (fundo preto e fundo branco) e a transparência sai da diferença entre as duas — fica exato."""
    import cv2
    import numpy as np
    fonte = (store.FONTS / FONTES.get(it.get("font"), "Poppins-ExtraBold.ttf")).as_posix()
    fonte = fonte.replace(":", "\\:").replace("'", "\\'")
    linhas = _linhas(it)
    tam = it["size"] * min(W, H) * escala
    lh = tam * 1.18
    y0 = H / 2 - lh * len(linhas) / 2
    pasta = destino.parent
    filtros = []
    for li, ln in enumerate(linhas):
        if not ln.strip():
            continue
        extra = ""
        if it.get("strokeW", 0) > 0:
            extra += f":borderw={max(1, int(round(it['strokeW'] * tam)))}:bordercolor={it['stroke']}"
        if it.get("boxOn"):
            extra += (f":box=1:boxcolor={it['box']}@{it.get('boxAlpha', 0.6):.2f}"
                      f":boxborderw={max(2, int(tam * 0.22))}")
        tf = destino.with_suffix(f".l{li}.txt")
        tf.write_text(ln, encoding="utf-8")
        yl = y0 + li * lh + (lh - tam) / 2
        filtros.append(f"drawtext=fontfile='{fonte}':textfile='{tf.name}':expansion=none:fontsize={tam:.2f}:"
                       f"fontcolor={it['color']}:x={W / 2:.2f}-text_w/2:y={yl:.2f}{extra}")
    if not filtros:
        filtros = ["null"]
    imgs = []
    for fundo in ("black", "white"):
        out = destino.with_suffix(f".{fundo}.png")
        ff.run([ff.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                f"color=c={fundo}:s={W}x{H}:d=1,format=rgb24", "-vf", ",".join(filtros), "-frames:v", "1",
                out.name], cwd=str(pasta))
        imgs.append(cv2.imread(str(out), cv2.IMREAD_COLOR).astype("float32"))
        out.unlink(missing_ok=True)
    for f in pasta.glob(destino.stem + ".l*.txt"):
        f.unlink(missing_ok=True)
    preto, branco = imgs
    a = np.clip(1 - (branco - preto).mean(axis=2) / 255.0, 0, 1)
    cor = np.where(a[..., None] > 1e-3, preto / np.maximum(a[..., None], 1e-3), 0)
    rgba = np.dstack([np.clip(cor, 0, 255), a * 255]).astype("uint8")
    ys, xs = np.nonzero(rgba[..., 3] > 0)
    if len(xs) == 0:
        rgba, hx, hy = np.zeros((2, 2, 4), "uint8"), 1, 1
    else:  # recorte simétrico em volta do centro do quadro (o centro do texto continua sendo o centro do PNG)
        hx = int(max(W / 2 - xs.min(), xs.max() + 1 - W / 2)) + 2
        hy = int(max(H / 2 - ys.min(), ys.max() + 1 - H / 2)) + 2
        hx, hy = min(hx, W // 2), min(hy, H // 2)
        rgba = rgba[H // 2 - hy:H // 2 + hy, W // 2 - hx:W // 2 + hx]
    cv2.imwrite(str(destino), rgba)
    return rgba.shape[1], rgba.shape[0]


def _comandos(caminho: Path, alvo: str, valores: list[tuple[float, float]]) -> None:
    """Arquivo do sendcmd: muda um parâmetro de filtro quadro a quadro (só quando o valor muda)."""
    linhas, ultimo = [], None
    for t, v in valores:
        if ultimo is None or abs(v - ultimo) > 0.002:
            linhas.append(f"{t:.4f} [enter] {alvo} {v:.4f};")
            ultimo = v
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def exportar(pid: str, opts: dict, progress: Optional[Callable[[float, str], None]] = None) -> dict:
    def p(x, msg):
        if progress:
            progress(x, msg)

    p(0.01, "Preparando a montagem…")
    m = carregar(pid)
    folder = store.pdir(pid)
    cfg = store.load_config()
    W, H, fps = m["w"], m["h"], m["fps"]
    total = round(duracao(m), 4)
    if total <= 0:
        raise RuntimeError("A linha do tempo está vazia.")
    midias = {x["id"]: x for x in m["media"]}
    trilhas = m["tracks"]
    ordem = {t["id"]: i for i, t in enumerate(trilhas)}
    tmap = {t["id"]: t for t in trilhas}

    stamp = time.strftime("%Y%m%d-%H%M%S")
    tag = f"mont_{stamp}"
    n_txt = 0
    args = [ff.ffmpeg(), "-y"]
    n_in = 0
    graph: list[str] = [f"color=c={m['bg']}:s={W}x{H}:r={fps}:d={total:.4f},format=yuv420p[base0]"]
    cur = "[base0]"
    audios: list[str] = []
    fundo: list[str] = []   # trilhas marcadas "abaixar quando falam"
    eps = 0.25 / fps

    def entrada(extra: list[str]) -> int:
        nonlocal n_in, args
        args += extra
        n_in += 1
        return n_in - 1

    def novo(prefixo: str = "k") -> str:
        return f"[{prefixo}{len(graph)}_{n_in}]"

    def sobrepor(label: str, x_c, y_c, s0: float, s1: float):
        """x_c / y_c: número (fração da tela, o centro do item) ou expressão pronta em pixels."""
        nonlocal cur
        nxt = f"[b{len(graph)}]"
        xs = f"{x_c * W:.2f}" if isinstance(x_c, (int, float)) else x_c
        ys = f"{y_c * H:.2f}" if isinstance(y_c, (int, float)) else y_c
        graph.append(f"{cur}{label}overlay=x='{xs}-w/2':y='{ys}-h/2':eof_action=pass:"
                     f"enable='between(t,{s0:.4f},{s1:.4f})'{nxt}")
        cur = nxt

    def cor_filtros(it: dict, w: int, h: int) -> list[str]:
        """Fundo verde e filtros de cor (no tamanho final do item, antes de girar)."""
        return fxm.chroma_ffmpeg(it.get("chroma")) + fxm.filtros_ffmpeg(it.get("fx"), W, H)

    def vinheta(lab: str, it: dict, w: int, h: int) -> str:
        forca = (it.get("fx") or {}).get("vinheta", 0)
        if forca <= 0.005:
            return lab
        import cv2
        arq = folder / f"tmp_{tag}.v{len(graph)}.png"
        cv2.imwrite(str(arq), fxm.vinheta_mascara(w, h, forca))
        idx = entrada(["-loop", "1", "-framerate", str(fps), "-i", arq.name])
        a, b, al, c, out = (f"[vg{len(graph)}{s}]" for s in ("a", "b", "l", "c", "o"))
        graph.append(f"{lab}split{a}{b}")
        graph.append(f"{b}alphaextract{al}")
        graph.append(f"{a}[{idx}:v]overlay=format=rgb:shortest=1{c}")
        graph.append(f"{c}{al}alphamerge,format=rgba{out}")
        return out

    def efeitos_fim(it: dict, dur: float) -> list[str]:
        """Giro, transparência e esmaecimento (no tempo local do item) — caminho sem animação."""
        f = []
        if abs(it["rot"]) > 0.01:
            r = it["rot"] * math.pi / 180
            f.append(f"rotate={r:.6f}:ow='rotw({r:.6f})':oh='roth({r:.6f})':c=none")
        if it["opacity"] < 0.999:
            f.append(f"colorchannelmixer=aa={it['opacity']:.4f}")
        if it["fadeIn"] > 0:
            f.append(f"fade=t=in:st=0:d={min(it['fadeIn'], dur):.3f}:alpha=1")
        if it["fadeOut"] > 0:
            fo = min(it["fadeOut"], dur)
            f.append(f"fade=t=out:st={max(0.0, dur - fo):.3f}:d={fo:.3f}:alpha=1")
        return f

    def cadeia(inicio: str, it: dict, w: int, h: int, dur: float, s0: float) -> str:
        """inicio: '[n:v]filtros...' (sem a escala). Devolve o rótulo pronto para sobrepor."""
        pre = [f"scale={w}:{h}:flags=lanczos", "format=rgba"] + cor_filtros(it, w, h)
        lab = novo()
        graph.append(inicio + "," + ",".join(pre) + lab)
        lab = vinheta(lab, it, w, h)
        fim = efeitos_fim(it, dur) + [f"setpts=PTS-STARTPTS+{s0:.4f}/TB"]
        out = novo()
        graph.append(lab + ",".join(fim) + out)
        return out

    def audio_de(idx: int, it: dict, dur: float, s0: float, trims: list[tuple[float, float]] | None = None,
                 destino: list | None = None, fonte_abs: tuple[str, float] | None = None):
        vol = it["volume"]
        if vol <= 0.001:
            return
        lab = f"[a{len(audios)}]"
        feito = False
        if trims and len(trims) > 1 and fonte_abs is not None:
            # Emendas suaves: o áudio do grupo é montado amostra por amostra (o mesmo motor da edição automática):
            # em cada emenda os dois lados se cruzam, sem mudar a duração, então a sincronia com a imagem fica exata.
            # (Fazer isso com filtros do FFmpeg travava as versões novas dele.)
            from ..engine import render as _rd
            arq_fonte, base_t = fonte_abs
            raw = folder / "audio48k.raw" if it.get("src") == ORIGINAL else folder / "cache" / "mont" / f"{it['src']}.raw"
            raw.parent.mkdir(parents=True, exist_ok=True)
            _rd.ensure_render_audio(arq_fonte, raw)
            pedaco = folder / f"tmp_{tag}.a{len(audios) + len(fundo)}.raw"
            _rd.build_audio(raw, [[a + base_t, b + base_t] for a, b in trims], [], pedaco, m.get("suave", "suave"))
            idx_raw = entrada(["-f", "s16le", "-ar", "48000", "-ac", "2", "-i", str(pedaco)])
            base = f"[{idx_raw}:a]"
            chain = ["asetpts=PTS-STARTPTS", "afade=t=in:d=0.006", f"volume={vol:.3f}"]
            feito = True
        if feito:
            pass
        elif trims:  # vários trechos do mesmo arquivo: cortes exatos na amostra, com 6 ms de suavização
            parts = []
            src = f"[z{len(audios)}]"
            graph.append(f"[{idx}:a]asetpts=PTS-STARTPTS{src}")
            if len(trims) > 1:
                graph.append(f"{src}asplit={len(trims)}" + "".join(f"[s{len(audios)}_{k}]" for k in range(len(trims))))
                srcs = [f"[s{len(audios)}_{k}]" for k in range(len(trims))]
            else:
                srcs = [src]
            for k, (a, b) in enumerate(trims):
                d = b - a
                fd = min(0.006, d / 3)
                parts.append(f"{srcs[k]}atrim=start={a:.5f}:end={b:.5f},asetpts=PTS-STARTPTS,"
                             f"afade=t=in:d={fd:.4f},afade=t=out:st={max(0.0, d - fd):.4f}:d={fd:.4f}[t{len(audios)}_{k}]")
            graph.extend(parts)
            if len(trims) > 1:
                graph.append("".join(f"[t{len(audios)}_{k}]" for k in range(len(trims))) +
                             f"concat=n={len(trims)}:v=0:a=1[c{len(audios)}]")
                base = f"[c{len(audios)}]"
            else:
                base = f"[t{len(audios)}_0]"
            chain = [f"volume={vol:.3f}"]
        else:
            base = f"[{idx}:a]"
            chain = ["asetpts=PTS-STARTPTS"]
            if it["speed"] != 1:
                chain.append(_atempo(it["speed"]))
            chain.append(f"atrim=0:{dur:.4f}")
            chain.append(f"volume={vol:.3f}")
            if it["fadeIn"] > 0:
                chain.append(f"afade=t=in:d={min(it['fadeIn'], dur):.3f}")
            if it["fadeOut"] > 0:
                fo = min(it["fadeOut"], dur)
                chain.append(f"afade=t=out:st={max(0.0, dur - fo):.3f}:d={fo:.3f}")
        chain += ["aresample=48000", "aformat=sample_fmts=fltp:channel_layouts=stereo",
                  f"adelay={int(round(s0 * 1000))}:all=1"]
        graph.append(base + ",".join(chain) + lab)
        (audios if destino is None else destino).append(lab)

    def entrada_video(midia: dict, extra: list[str]) -> int:
        """Vídeo sem fundo (WebM com transparência) precisa do decodificador VP9 que lê a transparência."""
        dec = ["-c:v", "libvpx-vp9"] if midia.get("alpha") else []
        return entrada(extra[:-2] + dec + extra[-2:])

    # ---- animação, transições e texto animado (1.2)
    def camada_animada(it: dict, midia: dict | None, mudo: bool):
        nonlocal n_txt
        s0, dur = it["start"], it["dur"]
        ext, tro = it.get("_ext", 0.0), it.get("_tro")
        vis = dur + ext
        s1 = s0 + vis
        tr = it.get("tr")
        k_tr_max = 1.4 if tr and tr["tipo"] == "zoom_out" else 1.0
        anima_geo = fxm.kf_anima(it, "scale") or fxm.kf_anima(it, "rot") or \
            bool(tr and tr["tipo"] in ("zoom_in", "zoom_out", "giro"))
        smax = max(0.02, fxm.kf_max(it, "scale")) * k_tr_max if anima_geo else fxm.valor(it, "scale", 0)
        # tamanho de base (escala 1) e fonte das imagens
        if it["type"] == "text":
            n_txt += 1
            png = folder / f"tmp_{tag}.txt{n_txt}.png"
            pw, ph = _texto_png(it, W, H, smax, png)
            idx = entrada(["-loop", "1", "-framerate", str(fps), "-t", f"{vis:.4f}", "-i", png.name])
            inicio = f"[{idx}:v]fps={fps},trim=0:{vis:.4f},setpts=PTS-STARTPTS"
            w, h = _par(pw), _par(ph)
        else:
            if it["type"] == "color":
                w0, h0 = W * it.get("w", 1), H * it.get("h", 1)
            else:
                aw, ah = (midia or {}).get("w") or W, (midia or {}).get("h") or H
                k = (max if it.get("fit") == "cover" else min)(W / aw, H / ah)
                w0, h0 = aw * k, ah * k
            w, h = _par(w0 * smax), _par(h0 * smax)
            if it["type"] == "color":
                inicio = f"color=c={it['color']}:s={w}x{h}:r={fps}:d={vis:.4f}"
            elif it["type"] == "image":
                idx = entrada(["-loop", "1", "-framerate", str(fps), "-t", f"{vis:.4f}", "-i",
                               str(folder / midia["file"])])
                inicio = f"[{idx}:v]fps={fps},trim=0:{vis:.4f},setpts=PTS-STARTPTS"
            else:
                a = it["in"]
                span_v = vis * it["speed"]
                seek = max(0.0, a - 0.5 / fps)
                src = str(folder / midia["file"])
                idx = entrada_video(midia, (["-ss", f"{seek:.5f}"] if seek > 0 else []) +
                                    ["-t", f"{span_v + 0.5:.4f}", "-i", src])
                vf = ["setpts=PTS-STARTPTS", f"trim=start={a - seek:.5f}:duration={span_v:.5f}", "setpts=PTS-STARTPTS"]
                if it["speed"] != 1:
                    vf.append(f"setpts=PTS/{it['speed']:.5f}")
                vf.append(f"fps={fps}")
                sobra = (midia.get("duration") or 0) - a
                if ext > 0 and sobra < span_v + 1.0 / fps:  # o vídeo acaba antes do fim da transição: segura o último quadro
                    vf.append(f"tpad=stop_mode=clone:stop_duration={ext + 0.5:.3f}")
                    vf.append(f"trim=duration={vis:.5f}")
                inicio = f"[{idx}:v]" + ",".join(vf)
                if midia.get("has_audio") and not mudo:
                    span_a = dur * it["speed"]
                    if it["speed"] == 1 and not it["fadeIn"] and not it["fadeOut"]:
                        audio_de(idx, it, dur, s0, [(a - seek, a - seek + span_a)])
                    else:
                        idx2 = entrada(["-ss", f"{a:.5f}", "-t", f"{span_a:.4f}", "-i", src])
                        audio_de(idx2, it, dur, s0)
        pre = [f"scale={w}:{h}:flags=lanczos", "format=rgba"]
        if it["type"] != "text":
            pre += cor_filtros(it, w, h)
        lab = novo()
        graph.append(inicio + "," + ",".join(pre) + lab)
        if it["type"] != "text":
            lab = vinheta(lab, it, w, h)
        # transparência quadro a quadro (opacidade animada, entrada/saída suave e transição)
        n_q = int(math.ceil(vis * fps)) + 1
        cmd = folder / f"tmp_{tag}.c{len(graph)}.cmd"
        nome_mix = f"colorchannelmixer@al{len(graph)}"
        _comandos(cmd, f"{nome_mix} aa", [(q / fps, _alfa(it, q / fps)) for q in range(n_q)])
        fim = [f"sendcmd=f={cmd.name}", f"{nome_mix}=aa={_alfa(it, 0):.4f}"]
        T = f"(in/{fps})"
        if anima_geo or abs(fxm.valor(it, "rot", 0)) > 0.01 or fxm.kf_anima(it, "rot"):
            gira = fxm.kf_anima(it, "rot") or abs(fxm.valor(it, "rot", 0)) > 0.01 or (tr and tr["tipo"] == "giro")
            Dw, Dh = (_par(math.ceil(math.hypot(w, h))),) * 2 if gira else (w, h)
            if (Dw, Dh) != (w, h):
                fim.append(f"pad={Dw}:{Dh}:(ow-iw)/2:(oh-ih)/2:color=black@0")
            ex_tr = fxm.tr_expr_entrada(tr["tipo"], tr["dur"], T, W, H) if tr else {"k": "1", "r": "0"}
            kx = f"(({fxm.kf_expr(it, 'scale', T)})*{ex_tr['k']}/{smax:.5f})"
            th = f"((({fxm.kf_expr(it, 'rot', T)})+{ex_tr['r']})*PI/180)"
            cx, cy = Dw / 2, Dh / 2
            cantos = []
            for i, (px, py) in enumerate(((0, 0), (Dw, 0), (0, Dh), (Dw, Dh))):
                dx, dy = px - cx, py - cy
                cantos.append(f"x{i}='{cx}+{kx}*({dx}*cos({th})-({dy})*sin({th}))'")
                cantos.append(f"y{i}='{cy}+{kx}*({dx}*sin({th})+({dy})*cos({th}))'")
            fim += ["format=yuva444p", "perspective=" + ":".join(cantos) + ":sense=destination:eval=frame"]
        fim.append(f"setpts=PTS-STARTPTS+{s0:.4f}/TB")
        out = novo()
        graph.append(lab + ",".join(fim) + out)
        # posição: quadros-chave + deslocamento da transição de entrada e de saída (empurrar)
        Tm = f"(t-{s0:.4f})"
        xe = f"(({fxm.kf_expr(it, 'x', Tm)})*{W})"
        ye = f"(({fxm.kf_expr(it, 'y', Tm)})*{H})"
        if tr:
            ex = fxm.tr_expr_entrada(tr["tipo"], tr["dur"], Tm, W, H)
            xe += f"+{ex['dx']}"
            ye += f"+{ex['dy']}"
        if ext > 0 and tro:
            xe += "+" + fxm.tr_expr_saida(tro, ext, f"(t-{s0 + dur:.4f})", W)
        sobrepor(out, xe, ye, s0, s1)
        # passar pelo preto/branco: a tela escurece (ou clareia) por cima deste item durante o tempo extra
        if ext > 0 and tro in ("preto", "branco"):
            cmd2 = folder / f"tmp_{tag}.d{len(graph)}.cmd"
            nm = f"colorchannelmixer@dp{len(graph)}"
            _comandos(cmd2, f"{nm} aa", [(q / fps, fxm.tr_saida(tro, q / fps / ext, W)["ca"])
                                          for q in range(int(math.ceil(ext * fps)) + 1)])
            lab2 = novo("d")
            graph.append(f"color=c={'black' if tro == 'preto' else 'white'}:s={W}x{H}:r={fps}:d={ext:.4f},format=rgba,"
                         f"sendcmd=f={cmd2.name},{nm}=aa=0,setpts=PTS-STARTPTS+{s0 + dur:.4f}/TB{lab2}")
            sobrepor(lab2, 0.5, 0.5, s0 + dur, s1)

    # camadas de baixo para cima: a última trilha da lista é a do fundo
    visuais = [dict(it) for it in m["items"] if it["type"] in ("video", "image", "text", "color", "tarja")
               and not tmap[it["track"]].get("hidden")]
    # transição: o item de antes continua por baixo durante a transição do seguinte (mesma trilha, colados)
    por_trilha: dict[str, list[dict]] = {}
    for it in sorted(visuais, key=lambda x: x["start"]):
        por_trilha.setdefault(it["track"], []).append(it)
    for lst in por_trilha.values():
        for a, b in zip(lst, lst[1:]):
            if b.get("tr") and a["type"] in ("video", "image", "color") and \
                    abs(a["start"] + a["dur"] - b["start"]) < 0.6 / fps:
                a["_ext"], a["_tro"] = min(b["tr"]["dur"], b["dur"]), b["tr"]["tipo"]
    trilhas_baixo_cima = sorted(por_trilha, key=lambda t: -ordem[t])

    def animado(it: dict) -> bool:
        return bool(it.get("kf") or it.get("tr") or it.get("_ext"))

    p(0.03, "Montando as camadas…")
    for tid in trilhas_baixo_cima:
        mudo = tmap[tid].get("muted")
        for grupo in _grupos(por_trilha[tid], fps):
            it = grupo[0]
            s0 = it["start"]
            s1 = grupo[-1]["start"] + grupo[-1]["dur"]
            dur = s1 - s0
            if it["type"] != "tarja" and animado(it):
                midia = midias.get(it["src"]) if it.get("src") else None
                if it["type"] in ("video", "image") and not midia:
                    continue
                camada_animada(it, midia, bool(mudo))
                continue
            if it["type"] == "color":
                w, h = _tamanho(it, None, W, H)
                lab = cadeia(f"color=c={it['color']}:s={w}x{h}:r={fps}:d={dur:.4f},null", it, w, h, dur, s0)
                sobrepor(lab, it["x"], it["y"], s0, s1)
                continue
            if it["type"] == "tarja":
                from . import tarjas as _tj
                cur, n = _tj.filtros(it, W, H, fps, cur, graph, folder, tag, n_txt + 1000)
                n_txt += n
                continue
            if it["type"] == "text":
                fonte = (store.FONTS / FONTES.get(it.get("font"), "Poppins-ExtraBold.ttf")).as_posix()
                fonte = fonte.replace(":", "\\:").replace("'", "\\'")
                linhas = _linhas(it)
                tam = it["size"] * min(W, H) * it["scale"]  # letra relativa ao lado menor (igual à prévia)
                lh = tam * 1.18
                y0 = it["y"] * H - lh * len(linhas) / 2
                op = it["opacity"]
                fi, fo = it["fadeIn"], it["fadeOut"]
                a_expr = f"{op:.3f}"
                if fi > 0 or fo > 0:
                    termos = [f"{op:.3f}"]
                    if fi > 0:
                        termos.append(f"clip((t-{s0:.4f})/{fi:.3f},0,1)")
                    if fo > 0:
                        termos.append(f"clip(({s1:.4f}-t)/{fo:.3f},0,1)")
                    a_expr = "*".join(termos)
                for li, ln in enumerate(linhas):
                    if not ln.strip():
                        continue
                    extra = ""
                    if it.get("strokeW", 0) > 0:
                        extra += f":borderw={max(1, int(round(it['strokeW'] * tam)))}:bordercolor={it['stroke']}"
                    if it.get("boxOn"):
                        extra += (f":box=1:boxcolor={it['box']}@{it.get('boxAlpha', 0.6):.2f}"
                                  f":boxborderw={max(2, int(tam * 0.22))}")
                    yl = y0 + li * lh + (lh - tam) / 2
                    n_txt += 1
                    tf = f"tmp_{tag}.t{n_txt}.txt"  # texto por arquivo: acentos, aspas e dois-pontos sem problema
                    (folder / tf).write_text(ln, encoding="utf-8")
                    nxt = f"[b{len(graph)}]"
                    graph.append(f"{cur}drawtext=fontfile='{fonte}':textfile='{tf}':expansion=none:fontsize={tam:.2f}:"
                                 f"fontcolor={it['color']}:x={it['x'] * W:.2f}-text_w/2:y={yl:.2f}:"
                                 f"alpha='{a_expr}'{extra}:enable='between(t,{s0:.4f},{s1:.4f})'{nxt}")
                    cur = nxt
                continue
            midia = midias.get(it["src"])
            if not midia:
                continue
            src = str(folder / midia["file"])
            w, h = _tamanho(it, midia, W, H)
            if it["type"] == "image":
                idx = entrada(["-loop", "1", "-framerate", str(fps), "-t", f"{dur:.4f}", "-i", src])
                lab = cadeia(f"[{idx}:v]fps={fps},trim=0:{dur:.4f}", it, w, h, dur, s0)
                sobrepor(lab, it["x"], it["y"], s0, s1)
                continue
            # vídeo: uma entrada por grupo de trechos seguidos (busca rápida no arquivo)
            if len(grupo) == 1:
                a = it["in"]
                span = it["dur"] * it["speed"]
                seek = max(0.0, a - 0.5 / fps)
                idx = entrada_video(midia, (["-ss", f"{seek:.5f}"] if seek > 0 else []) +
                                    ["-t", f"{span + 0.5:.4f}", "-i", src])
                vf = ["setpts=PTS-STARTPTS", f"trim=start={a - seek:.5f}:duration={span:.5f}", "setpts=PTS-STARTPTS"]
                if it["speed"] != 1:
                    vf.append(f"setpts=PTS/{it['speed']:.5f}")
                vf.append(f"fps={fps}")
                lab = cadeia(f"[{idx}:v]" + ",".join(vf), it, w, h, it["dur"], s0)
                sobrepor(lab, it["x"], it["y"], s0, s1)
                if midia.get("has_audio") and not mudo:
                    # o áudio usa a mesma entrada: tempo local já começa em "seek"
                    audios_trim = [(a - seek, a - seek + span)]
                    if it["speed"] == 1 and not it["fadeIn"] and not it["fadeOut"]:
                        audio_de(idx, it, it["dur"], s0, audios_trim)
                    else:
                        idx2 = entrada(["-ss", f"{a:.5f}", "-t", f"{span:.4f}", "-i", src])
                        audio_de(idx2, it, it["dur"], s0)
                continue
            g_in = min(x["in"] for x in grupo)
            g_out = max(x["in"] + x["dur"] for x in grupo)
            k0 = max(0, int((g_in - 1.0) * fps))
            offset = k0 / fps
            seek = max(0.0, offset - 0.5 / fps) if k0 > 0 else 0.0
            idx = entrada_video(midia, (["-ss", f"{seek:.5f}"] if seek > 0 else []) +
                                ["-t", f"{g_out - offset + 1.0:.3f}", "-i", src])
            termos = ff.soma_expr([f"gte(t,{x['in'] - offset - eps:.4f})*lt(t,{x['in'] + x['dur'] - offset - eps:.4f})"
                                   for x in grupo])
            lab = cadeia(f"[{idx}:v]setpts=PTS-STARTPTS,fps={fps},select='{termos}',setpts=N/({fps})/TB",
                         it, w, h, dur, s0)
            sobrepor(lab, it["x"], it["y"], s0, s1)
            if midia.get("has_audio") and not mudo:
                base_t = seek if seek > 0 else 0.0
                audio_de(idx, it, dur, s0, [(x["in"] - base_t, x["in"] + x["dur"] - base_t) for x in grupo],
                         fonte_abs=(src, base_t))

    p(0.05, "Mixando o áudio…")
    for it in sorted([x for x in m["items"] if x["type"] == "audio"], key=lambda x: x["start"]):
        if tmap[it["track"]].get("muted"):
            continue
        midia = midias.get(it["src"])
        if not midia:
            continue
        span = it["dur"] * it["speed"]
        idx = entrada((["-ss", f"{it['in']:.5f}"] if it["in"] > 0 else []) + ["-t", f"{span + 0.2:.4f}", "-i",
                                                                             str(folder / midia["file"])])
        audio_de(idx, it, it["dur"], it["start"], destino=fundo if it.get("duck") else None)

    graph.append(f"{cur}null[vout]")

    def junta(labs: list[str], saida: str):
        mix = "".join(labs) + (f"amix=inputs={len(labs)}:normalize=0:dropout_transition=0" if len(labs) > 1
                               else "anull")
        graph.append(mix + f",apad,atrim=0:{total:.4f}{saida}")

    if fundo and audios:
        # trilha de fundo abaixa sozinha quando alguém fala e volta a subir nas pausas
        junta(audios, "[voz]")
        junta(fundo, "[mus]")
        graph.append("[voz]asplit=2[voz1][vozsc]")
        graph.append("[mus][vozsc]sidechaincompress=threshold=0.03:ratio=8:attack=25:release=500:makeup=1[musd]")
        graph.append("[voz1][musd]amix=inputs=2:normalize=0:dropout_transition=0,"
                     "alimiter=limit=0.95:level=disabled[aout]")
    elif audios or fundo:
        junta(audios or fundo, "[mx]")
        graph.append("[mx]alimiter=limit=0.95:level=disabled[aout]")
    else:
        graph.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{total:.4f}[aout]")

    out_name = f"montagem-{stamp}.mp4"
    out = folder / "renders" / out_name
    out.parent.mkdir(exist_ok=True)
    args += ff.filter_script_args(";".join(graph), str(folder / f"tmp_{tag}.filter"))
    encoder = ff.best_encoder(cfg["render"].get("encoder", "auto"))
    args += ["-map", "[vout]", "-map", "[aout]"] + ff.encoder_args(encoder, opts.get("quality") or
                                                                     cfg["render"].get("quality", "alta"))
    args += ["-r", str(fps), "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.4f}", "-movflags", "+faststart", str(out)]
    label = "CPU" if encoder == "libx264" else "GPU"
    t0 = time.time()
    try:
        ff.run_with_progress(args, total, lambda x: p(0.06 + 0.93 * x, f"Exportando a montagem ({label})…"),
                             cwd=str(folder))
    except RuntimeError:
        if encoder == "libx264":
            raise
        # placa de vídeo recusou algum tamanho fora do padrão: refaz pelo processador
        enc_i = args.index("-c:v")
        fim = args.index("-r")
        args = args[:enc_i] + ff.encoder_args("libx264", opts.get("quality") or "alta") + args[fim:]
        encoder = "libx264"
        ff.run_with_progress(args, total, lambda x: p(0.06 + 0.93 * x, "Exportando a montagem (CPU)…"),
                             cwd=str(folder))
    finally:
        for tmp in folder.glob(f"tmp_{tag}.*"):
            tmp.unlink(missing_ok=True)
    item = {"file": out_name, "created": time.time(), "duration": round(total, 2),
            "seconds": round(time.time() - t0, 1), "encoder": encoder, "vertical": H > W,
            "platform": None, "label": f"Montagem {m['formato']}", "subtitles": False,
            "size": out.stat().st_size, "montagem": True}
    store.update(pid, lambda pr: pr.setdefault("renders", []).insert(0, item))
    return item


def projeto_em_branco(nome: str, formato: str) -> dict:
    """Projeto novo só de montagem (sem vídeo principal para analisar)."""
    proj = store.new_project(nome or "Montagem sem título")
    pid = proj["id"]
    store.update(pid, lambda p: p.update(status="pronto", kind="montagem", formato=formato,
                                         progress={"pct": 1, "msg": ""}))
    m = nova(store.load(pid), formato if formato in FORMATOS else "9:16", com_edicao=False)
    store._write_json(arquivo(pid), m)
    return store.load(pid)

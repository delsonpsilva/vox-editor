"""História → Vídeo (v1.9): cria uma Montagem pronta a partir de um TEXTO, de um ÁUDIO ou da NARRAÇÃO AO VIVO.

Como funciona (tudo no próprio aparelho; a IA paga é opcional):
1. A fala vira palavras com tempo: o áudio é transcrito pelo Whisper (o mesmo da edição automática); o texto
   ganha uma voz (Microsoft grátis pela internet, ou a voz do Windows sem internet) e o tempo vem da própria voz.
2. As frases são agrupadas em CENAS de ~6 a 14 segundos. Com a IA ligada, ela escolhe as cenas, a imagem de cada
   uma, um título de destaque e, quando há números, um gráfico. Sem IA, a divisão e as palavras de busca são locais.
3. Cada cena ganha uma foto ou um vídeo dos bancos grátis (Pexels/Pixabay) — ou um fundo colorido, se não houver
   chave — com movimento suave (zoom), transição, legenda palavra a palavra, título e música de fundo.
4. Tudo vira uma Montagem comum: dá para ver, trocar imagens, mexer em textos e exportar como qualquer outra.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import wave
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from . import bancos, montagem, pipeline, store
from ..engine import audio as aud
from ..engine import ffmpeg_tools as ff
from ..engine import transcribe

Progresso = Optional[Callable[[float, str], None]]

VOZES = {  # id -> (motor, voz, nome mostrado)
    "francisca": ("edge", "pt-BR-FranciscaNeural", "Francisca — feminina (internet, grátis)"),
    "antonio": ("edge", "pt-BR-AntonioNeural", "Antônio — masculina (internet, grátis)"),
    "thalita": ("edge", "pt-BR-ThalitaMultilingualNeural", "Thalita — feminina (internet, grátis)"),
    "windows": ("sapi", "", "Voz do Windows (sem internet)"),
    "nenhuma": ("none", "", "Sem narração (só imagens e textos)"),
}
VISUAIS = {"fotos": "Fotos dos bancos grátis", "videos": "Vídeos dos bancos grátis", "cores": "Fundos coloridos"}
MAX_TEXTO = 60_000

STOP = set("""a o as os um uma uns umas de da do das dos em na no nas nos por pela pelo pelas pelos para pra pro
com sem sob sobre e ou mas que se como quando onde porque pois já não sim muito muita muitos muitas mais menos tão
também só ainda então lá aqui ali isso isto aquilo esse essa esses essas este esta estes estas aquele aquela aqueles
aquelas ele ela eles elas eu tu você vocês nós vos me te lhe nos lhes meu minha meus minhas seu sua seus suas nosso
nossa nossos nossas dele dela deles delas ao aos à às foi era é são ser estar está estava estão estavam tinha tem têm
ter tinham havia há vai ia iam fez faz fazer disse diz dizia todo toda todos todas cada outro outra outros outras
mesmo mesma depois antes até entre desde durante enquanto num numa aí né tipo coisa coisas vez vezes bem mal agora
sempre nunca hoje assim qual quais quem cujo cuja sua tudo nada algo alguém ninguém foram seria será sido sendo pode
podia poder deve devia vamos vou eram estou estamos fica ficou então porém contudo todavia aquilo daquele daquela
nele nela neles nelas desse dessa deste desta nesse nessa neste nesta logo lhe cá dele uns depois ainda muito""".split())

PALETAS = [((32, 24, 64), (210, 90, 40)), ((10, 40, 70), (40, 160, 170)), ((60, 20, 40), (230, 140, 60)),
           ((20, 50, 30), (150, 190, 80)), ((40, 30, 20), (220, 170, 90)), ((15, 25, 55), (120, 90, 200))]


# ---------------------------------------------------------------- texto

def _limpa_texto(t: str) -> str:
    t = (t or "").replace("\r", "")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{2,}", "\n\n", t)
    return t.strip()[:MAX_TEXTO]


def palavras_do_texto(texto: str) -> list[dict]:
    """O texto vira a mesma lista de palavras da transcrição (ainda sem tempo). Quebra de parágrafo conta como fim de frase."""
    out = []
    for par in _limpa_texto(texto).split("\n"):
        toks = par.split()
        for k, tok in enumerate(toks):
            w = tok
            if k == len(toks) - 1 and w[-1:] not in ".?!…:;":
                w += "."  # fim de linha/parágrafo = fim de frase (títulos e versos sem ponto)
            out.append({"w": w, "s": 0.0, "e": 0.0})
    return out


def _fim_frase(w: str) -> bool:
    return w.rstrip("\"'”’)»")[-1:] in ".?!…:;"


def frases(words: list[dict], max_palavras: int = 32) -> list[list[int]]:
    """Faixas [i0, i1] (índices de palavras) de cada frase. Frase muito longa quebra na vírgula (ou no meio)."""
    out, i0 = [], 0
    for i, w in enumerate(words):
        n = i - i0 + 1
        quebra_virgula = n >= max_palavras * 0.6 and w["w"].endswith(",")
        if _fim_frase(w["w"]) or quebra_virgula or n >= max_palavras or i == len(words) - 1:
            out.append([i0, i])
            i0 = i + 1
    return out


def palavras_chave(texto: str, n: int = 2) -> str:
    """Palavras de busca sem IA: as palavras com conteúdo (não as "de", "que", "ele"...) mais repetidas e mais longas."""
    toks = [re.sub(r"[^\wÀ-ÿ-]", "", t.lower()) for t in texto.split()]
    toks = [t for t in toks if len(t) >= 4 and t not in STOP and not t.isdigit()]
    if not toks:
        return "natureza paisagem"
    cont: dict[str, int] = {}
    for t in toks:
        cont[t] = cont.get(t, 0) + 1
    ordem = sorted(cont, key=lambda t: (-cont[t], -len(t), toks.index(t)))
    return " ".join(ordem[:n])


def _txt(words: list[dict], i0: int, i1: int) -> str:
    return " ".join(w["w"] for w in words[i0:i1 + 1]).strip()


def cenas_por_regra(words: list[dict], fr: list[list[int]], formato: str) -> list[dict]:
    """Junta frases até ~22 palavras (vertical, cortes rápidos) ou ~32 (horizontal)."""
    alvo = 22 if formato == "9:16" else 32
    cenas, atual = [], None
    for a, b in fr:
        if atual is None:
            atual = [a, b]
        elif (atual[1] - atual[0] + 1) + (b - a + 1) <= alvo * 1.35 and (atual[1] - atual[0] + 1) < alvo:
            atual[1] = b
        else:
            cenas.append(atual)
            atual = [a, b]
    if atual:
        cenas.append(atual)
    return [{"i0": a, "i1": b, "busca": palavras_chave(_txt(words, a, b)), "destaque": "", "grafico": None}
            for a, b in cenas]


PROMPT_CENAS = """Você é diretor de vídeos narrados em português (histórias, devocionais, explicações) para {destino}.
Abaixo está o texto, dividido em frases numeradas. Divida-o em CENAS, na ordem, cobrindo TODAS as frases sem pular
nenhuma. Cada cena tem de 1 a 4 frases (mais ou menos {seg} segundos de fala) e muda quando muda a imagem que
combina com o que está sendo dito.

Para cada cena informe:
- "inicio" e "fim": número da primeira e da última frase da cena;
- "busca": 2 a 4 palavras EM PORTUGUÊS descrevendo uma FOTO concreta que combine com a cena (pessoas, lugares,
  objetos, paisagens, ações). Nada de nomes próprios nem ideias abstratas. Ex.: "pastor ovelhas campo", "mãe abraçando filho";
- "destaque": um título curto de até 5 palavras para aparecer na tela, SÓ nas cenas que pedem (começo, virada,
  frase marcante). Nas outras, "";
- "grafico": só se a cena citar números comparáveis (porcentagens, quantidades, anos), no formato
  {{"titulo": "...", "rotulos": ["...", "..."], "valores": [10, 20]}}. Senão, null.

Responda só com JSON (uma lista), sem nada antes ou depois:
[{{"inicio": 0, "fim": 1, "busca": "...", "destaque": "...", "grafico": null}}]

Frases:
{frases}"""


def cenas_por_ia(words: list[dict], fr: list[list[int]], formato: str, ai: dict) -> list[dict]:
    from ..engine.smartcuts import _call_llm
    linhas = "\n".join(f"[{k}] {_txt(words, a, b)}" for k, (a, b) in enumerate(fr))
    raw = _call_llm(PROMPT_CENAS.format(destino="Reels/Shorts/TikTok" if formato == "9:16" else "YouTube",
                                        seg="6 a 9" if formato == "9:16" else "8 a 14", frases=linhas[:200_000]), ai)
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        raise RuntimeError("A IA não devolveu as cenas no formato esperado.")
    lst = [x for x in json.loads(m.group(0)) if isinstance(x, dict)]
    n = len(fr)
    cenas, prox = [], 0
    for x in sorted(lst, key=lambda x: int(x.get("inicio") or 0)):
        try:
            fim = int(x.get("fim"))
        except (TypeError, ValueError):
            continue
        fim = min(n - 1, fim)
        if fim < prox:
            continue
        cenas.append({"i0": fr[prox][0], "i1": fr[fim][1],
                      "busca": re.sub(r"\s+", " ", str(x.get("busca") or "")).strip()[:60],
                      "destaque": re.sub(r"\s+", " ", str(x.get("destaque") or "")).strip()[:48],
                      "grafico": _grafico_limpo(x.get("grafico"))})
        prox = fim + 1
    if not cenas:
        raise RuntimeError("A IA não devolveu cenas.")
    if prox < n:  # o que a IA esqueceu no fim entra na última cena
        cenas[-1]["i1"] = fr[-1][1]
    for c in cenas:
        if not c["busca"]:
            c["busca"] = palavras_chave(_txt(words, c["i0"], c["i1"]))
    return cenas


def _grafico_limpo(g) -> dict | None:
    if not isinstance(g, dict):
        return None
    rot = [str(x)[:22] for x in (g.get("rotulos") or [])][:8]
    val = []
    for v in (g.get("valores") or [])[:8]:
        try:
            val.append(float(str(v).replace(",", ".").replace("%", "")))
        except ValueError:
            return None
    if len(rot) < 2 or len(rot) != len(val) or max(val) <= 0:
        return None
    return {"titulo": str(g.get("titulo") or "")[:60], "rotulos": rot, "valores": val}


def planejar(words: list[dict], formato: str, usar_ia: bool, progress: Progresso = None) -> tuple[list[dict], str]:
    fr = frases(words)
    if not fr:
        raise RuntimeError("Não há texto para virar vídeo.")
    ai = store.load_config().get("ai") or {}
    if usar_ia and ai.get("provider") not in (None, "none") and ai.get("api_key"):
        if progress:
            progress(0.0, "A IA está dividindo a história em cenas…")
        try:
            return cenas_por_ia(words, fr, formato, ai), "ia"
        except Exception as e:  # a IA nunca trava o vídeo: segue pela divisão local
            if progress:
                progress(0.0, f"IA indisponível ({str(e)[:80]}). Dividindo as cenas sem IA…")
    return cenas_por_regra(words, fr, formato), "local"


# ---------------------------------------------------------------- voz

def _voz_edge(texto: str, voz: str, destino: Path, velocidade: int) -> Path:
    import edge_tts
    out = destino.with_suffix(".mp3")
    rate = f"{'+' if velocidade >= 0 else ''}{int(velocidade)}%"

    async def _go():
        await edge_tts.Communicate(texto, voz, rate=rate).save(str(out))
    asyncio.run(_go())
    if not out.exists() or out.stat().st_size < 1000:
        raise RuntimeError("A voz veio vazia.")
    return out


PS_SAPI = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$v = $s.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -like 'pt*' } | Select-Object -First 1
if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }
$s.Rate = [int]$env:VOX_RATE
$s.SetOutputToWaveFile($env:VOX_OUT)
$s.Speak([IO.File]::ReadAllText($env:VOX_TXT, [Text.Encoding]::UTF8))
$s.Dispose()
"""


def _voz_windows(texto: str, destino: Path, velocidade: int) -> Path:
    if os.name != "nt":
        raise RuntimeError("A voz do Windows só existe no programa do PC.")
    out = destino.with_suffix(".wav")
    txt = destino.with_suffix(".txt")
    txt.write_text(texto, encoding="utf-8")
    env = {**os.environ, "VOX_OUT": str(out), "VOX_TXT": str(txt), "VOX_RATE": str(max(-10, min(10, velocidade // 10)))}
    try:
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", PS_SAPI], env=env,
                       capture_output=True, timeout=300, creationflags=0x08000000)
    finally:
        txt.unlink(missing_ok=True)
    if not out.exists() or out.stat().st_size < 1000:
        raise RuntimeError("A voz do Windows não gerou o áudio.")
    return out


def narrar(texto: str, voz: str, destino: Path, velocidade: int = 0) -> Path | None:
    """Gera a narração de um trecho. Se a voz da internet falhar, tenta a do Windows."""
    motor, nome, _ = VOZES.get(voz, VOZES["francisca"])
    if motor == "none":
        return None
    if motor == "edge":
        try:
            return _voz_edge(texto, nome, destino, velocidade)
        except Exception as e:
            if os.name != "nt":
                raise RuntimeError(f"Não consegui gerar a voz pela internet: {str(e)[:120]}")
    return _voz_windows(texto, destino, velocidade)


# ---------------------------------------------------------------- imagens

def _orient(formato: str) -> str:
    return "portrait" if formato in ("9:16", "4:5") else "square" if formato == "1:1" else "landscape"


def _fundo_cor(pid: str, k: int, W: int, H: int) -> dict:
    import cv2
    a, b = PALETAS[k % len(PALETAS)]
    w, h = W // 2, H // 2
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    t = np.clip((xx / w * 0.45 + yy / h * 0.55), 0, 1)[..., None]
    img = (np.array(a, np.float32) * (1 - t) + np.array(b, np.float32) * t)
    luz = np.exp(-(((xx - w * 0.3) / (w * 0.6)) ** 2 + ((yy - h * 0.25) / (h * 0.5)) ** 2))[..., None]
    img = np.clip(img + luz * 40, 0, 255).astype(np.uint8)
    arq = montagem.pasta_midias(pid) / f"fundo_{k:03d}.png"
    cv2.imwrite(str(arq), img[..., ::-1])
    return montagem.adicionar_midia(pid, arq, f"Fundo {k + 1}.png")


def visual_da_cena(pid: str, k: int, cena: dict, dur: float, formato: str, visual: str, usados: set) -> dict:
    """Mídia de fundo da cena: vídeo ou foto do banco grátis (sem repetir), ou um fundo colorido."""
    W, H = montagem.FORMATOS[formato]
    if visual in ("fotos", "videos") and any(bancos.status().values()):
        for tipo in (["video", "foto"] if visual == "videos" else ["foto"]):
            try:
                res = bancos.buscar("todos", tipo, cena["busca"], 1, _orient(formato))
            except Exception:
                continue
            for it in res.get("itens") or []:
                if it["id"] in usados or (tipo == "video" and (it.get("dur") or 0) < dur + 0.5):
                    continue
                try:
                    arq, info = bancos.baixar(it["id"], montagem.pasta_midias(pid))
                    md = montagem.adicionar_midia(pid, arq, f"{cena['busca'][:60]} — {info['autor'] or info['fonte']}"
                                                  f"{info['ext']}", {"credito": info["credito"],
                                                                     "licenca": bancos.FONTES[info["fonte"]],
                                                                     "banco": it["id"]})
                    usados.add(it["id"])
                    return md
                except Exception:
                    continue
    return _fundo_cor(pid, k, W, H)


def grafico_png(pid: str, k: int, g: dict, formato: str) -> dict | None:
    """Gráfico de barras com a fonte do programa, em PNG transparente (entra numa camada por cima da cena)."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None
    W, H = montagem.FORMATOS[formato]
    cw, ch = int(W * 0.86), int(min(H * 0.62, W * 0.62))
    img = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, cw - 1, ch - 1], radius=int(ch * 0.06), fill=(14, 15, 18, 215))
    fb = str(store.FONTS / "Poppins-ExtraBold.ttf")
    fr = str(store.FONTS / "Poppins-Bold.ttf")
    t_tit, t_rot = int(ch * 0.085), int(ch * 0.055)
    ft, fl = ImageFont.truetype(fb, t_tit), ImageFont.truetype(fr, t_rot)
    pad = int(ch * 0.07)
    d.text((pad, pad), g.get("titulo") or "", font=ft, fill=(255, 255, 255, 255))
    topo, base = pad * 2 + t_tit, ch - pad - t_rot * 2
    n = len(g["valores"])
    larg = (cw - pad * 2) / n
    vmax = max(g["valores"])
    cor = store.load_config().get("brand", {}).get("color") or "#FF8A3D"
    rgb = tuple(int(cor[i:i + 2], 16) for i in (1, 3, 5)) if re.fullmatch(r"#[0-9a-fA-F]{6}", cor) else (255, 138, 61)
    for i, (r, v) in enumerate(zip(g["rotulos"], g["valores"])):
        bw = min(larg * 0.64, ch * 0.32)
        x0 = pad + i * larg + (larg - bw) / 2
        x1 = x0 + bw
        alt = (base - topo - t_rot * 1.6) * (v / vmax)
        y0 = base - alt
        d.rounded_rectangle([x0, min(y0, base - 4), x1, base], radius=max(2, min(int(bw * 0.1), int(alt / 2))), fill=rgb + (255,))
        val = f"{v:g}"
        tw = d.textlength(val, font=fl)
        d.text(((x0 + x1) / 2 - tw / 2, y0 - t_rot * 1.4), val, font=fl, fill=(255, 255, 255, 255))
        while d.textlength(r, font=fl) > larg * 0.95 and len(r) > 3:
            r = r[:-2] + "…"
        tw = d.textlength(r, font=fl)
        d.text((pad + i * larg + larg / 2 - tw / 2, base + t_rot * 0.4), r, font=fl, fill=(200, 202, 208, 255))
    arq = montagem.pasta_midias(pid) / f"grafico_{k:03d}.png"
    img.save(arq)
    return montagem.adicionar_midia(pid, arq, f"Gráfico {k + 1}.png")


# ---------------------------------------------------------------- legenda e montagem

def _quebra(texto: str, max_c: int) -> str:
    linhas, atual = [], ""
    for p in texto.split():
        if atual and len(atual) + 1 + len(p) > max_c:
            linhas.append(atual)
            atual = p
        else:
            atual = (atual + " " + p).strip()
    if atual:
        linhas.append(atual)
    return "\n".join(linhas[:3])


def blocos_legenda(words: list[dict], max_p: int = 4, max_c: int = 24) -> list[dict]:
    """Legenda em pedaços curtos (2 a 4 palavras), quebrando na pontuação, cada um com início e fim."""
    out, atual = [], []
    for w in words:
        atual.append(w)
        txt = " ".join(x["w"] for x in atual)
        if len(atual) >= max_p or len(txt) >= max_c or _fim_frase(w["w"]) or w["w"].endswith(","):
            out.append(atual)
            atual = []
    if atual:
        out.append(atual)
    blocos = []
    for k, g in enumerate(out):
        s = g[0]["s"]
        e = g[-1]["e"] + 0.3
        if k + 1 < len(out):
            prox = out[k + 1][0]["s"]
            e = prox if prox - g[-1]["e"] < 0.7 else min(e, prox)
        texto = " ".join(x["w"] for x in g).strip().rstrip(",.;:")
        if e - s >= 0.15 and texto:
            blocos.append({"s": round(s, 3), "e": round(e, 3), "t": texto})
    return blocos


def trilhas() -> list[dict]:
    base = {"hidden": False, "muted": False, "locked": False}
    return [{"id": "t_legenda", "kind": "text", "name": "Legenda", **base},
            {"id": "t_titulo", "kind": "text", "name": "Títulos", **base},
            {"id": "t_v2", "kind": "video", "name": "Gráficos", **base},
            {"id": "t_v1", "kind": "video", "name": "Cenas", "main": True, **base},
            {"id": "t_audio", "kind": "audio", "name": "Narração", **base},
            {"id": "t_musica", "kind": "audio", "name": "Música", **base}]


def _item(kind: str, track: str, src: str | None, start: float, dur: float, **kw) -> dict:
    return montagem._item_base(kind, track, src, start, dur, 0.0, **kw)


def montar(pid: str, words: list[dict], cenas: list[dict], visuais: list[dict], graficos: list[dict | None],
           narracoes: list[tuple[str, float, float]], total: float, opts: dict) -> dict:
    """Escreve a Montagem: cenas com zoom e transição, títulos, gráficos, legenda, narração e música."""
    formato = opts["formato"]
    W, H = montagem.FORMATOS[formato]
    vertical = H > W
    m = montagem.carregar(pid)
    m.update(formato=formato, w=W, h=H, tracks=trilhas(), items=[], markers=[])
    itens = []
    for k, c in enumerate(cenas):
        s, e = c["s"], c["e"]
        dur = max(0.5, e - s)
        md = visuais[k]
        zoom_in = k % 2 == 0
        dx = 0.015 if k % 3 == 1 else (-0.015 if k % 3 == 2 else 0.0)
        kw = {"fit": "cover", "volume": 0.0}
        if md["kind"] == "image":
            kw["kf"] = [{"t": 0, "scale": 1.0 if zoom_in else 1.14, "x": 0.5 - dx, "y": 0.5, "e": "linear"},
                        {"t": round(dur, 3), "scale": 1.14 if zoom_in else 1.0, "x": 0.5 + dx, "y": 0.5, "e": "linear"}]
        if k > 0:
            kw["tr"] = {"tipo": "dissolver", "dur": 0.6}
        itens.append(_item(md["kind"], "t_v1", md["id"], s, dur, **kw))
        if c.get("destaque"):
            dd = min(3.2, dur)
            itens.append(_item("text", "t_titulo", None, s + (0.15 if k == 0 else 0.3), max(0.8, dd - 0.3),
                               text=_quebra(c["destaque"], 14 if vertical else 26), font="Anton",
                               size=0.12 if vertical else 0.1, color="#FFFFFF", stroke="#000000", strokeW=0.0,
                               boxOn=True, box="#000000", boxAlpha=0.45, upper=True, y=0.2 if vertical else 0.18,
                               fadeIn=0.3, fadeOut=0.3))
        if graficos[k]:
            itens.append(_item("image", "t_v2", graficos[k]["id"], s + 0.4, max(0.8, dur - 0.6), fit="contain",
                               scale=0.95, y=0.46, fadeIn=0.4, fadeOut=0.3))
    if opts.get("legenda", True):
        for b in blocos_legenda(words):
            itens.append(_item("text", "t_legenda", None, b["s"], b["e"] - b["s"],
                               text=_quebra(b["t"], 18 if vertical else 34), font="Poppins ExtraBold",
                               size=0.068 if vertical else 0.06, color="#FFFFFF", stroke="#000000", strokeW=0.14,
                               upper=True, y=0.72 if vertical else 0.84))
    for mid, ini, d in narracoes:
        itens.append(_item("audio", "t_audio", mid, ini, d, volume=1.0))
    mus = opts.get("musica_id")
    if mus:
        md = next((x for x in m["media"] if x["id"] == mus), None)
        if md and md.get("duration"):
            t = 0.0
            while t < total - 0.2:
                d = min(md["duration"], total - t)
                itens.append(_item("audio", "t_musica", mus, t, d, volume=0.14, duck=True,
                                   fadeIn=1.0 if t == 0 else 0.0, fadeOut=2.0 if t + d >= total - 0.3 else 0.0))
                t += d
    m["items"] = itens
    return montagem.salvar(pid, m)


# ---------------------------------------------------------------- etapas comuns

def _musica(pid: str, nome: str) -> str | None:
    src = pipeline.musica_path(nome or "")
    if not src:
        return None
    dest = montagem.pasta_midias(pid) / f"musica_{Path(src).name}"
    shutil.copy(src, dest)
    try:
        return montagem.adicionar_midia(pid, dest, Path(src).name)["id"]
    except Exception:
        return None


def _salva_estado(pid: str, **kw) -> None:
    store.update(pid, lambda p: p.setdefault("historia", {}).update(kw))


def _visuais(pid: str, cenas: list[dict], opts: dict, p) -> tuple[list[dict], list]:
    usados: set = set()
    vis, gfs = [], []
    for k, c in enumerate(cenas):
        p(0.55 + 0.35 * k / max(1, len(cenas)), f"Escolhendo a imagem da cena {k + 1} de {len(cenas)}: “{c['busca']}”…")
        vis.append(visual_da_cena(pid, k, c, c["e"] - c["s"], opts["formato"], opts.get("visual", "fotos"), usados))
        gfs.append(grafico_png(pid, k, c["grafico"], opts["formato"]) if c.get("grafico") else None)
    return vis, gfs


def _opts(o: dict) -> dict:
    formato = o.get("formato") if o.get("formato") in montagem.FORMATOS else "9:16"
    return {"formato": formato, "voz": o.get("voz") if o.get("voz") in VOZES else "francisca",
            "visual": o.get("visual") if o.get("visual") in VISUAIS else "fotos",
            "legenda": o.get("legenda", True) is not False, "usar_ia": bool(o.get("usar_ia", True)),
            "musica": str(o.get("musica") or "")[:200], "velocidade": max(-50, min(50, int(o.get("velocidade") or 0)))}


def novo_projeto(nome: str, formato: str, origem: str) -> str:
    proj = montagem.projeto_em_branco(nome or "História", formato)
    pid = proj["id"]
    store.update(pid, lambda p: p.update(historia={"origem": origem, "criado": time.time()}))
    return pid


def _finaliza(pid: str, words, cenas, vis, gfs, narr, total, opts, modo) -> dict:
    o = dict(opts)
    o["musica_id"] = _musica(pid, opts.get("musica"))
    m = montar(pid, words, cenas, vis, gfs, narr, total, o)
    _salva_estado(pid, cenas=[{k: c[k] for k in ("s", "e", "busca", "destaque")} for c in cenas],
                  modo=modo, duracao=round(total, 2), opcoes=opts, texto=" ".join(w["w"] for w in words)[:MAX_TEXTO])
    return {"id": pid, "cenas": len(cenas), "duracao": round(total, 2), "itens": len(m["items"]), "modo": modo}


# ---------------------------------------------------------------- 1) TEXTO

def criar_de_texto(pid: str, texto: str, opts: dict, progress: Progresso = None) -> dict:
    def p(x, msg):
        if progress:
            progress(x, msg)
    opts = _opts(opts)
    words = palavras_do_texto(texto)
    if len(words) < 3:
        raise RuntimeError("Escreva pelo menos uma frase.")
    p(0.02, "Lendo a história…")
    cenas, modo = planejar(words, opts["formato"], opts["usar_ia"], p)
    pasta = montagem.pasta_midias(pid)
    narr, t = [], 0.0
    aviso = ""
    for k, c in enumerate(cenas):
        txt = _txt(words, c["i0"], c["i1"])
        n = c["i1"] - c["i0"] + 1
        dur_fala = 0.0
        md = None
        if opts["voz"] != "nenhuma":
            p(0.08 + 0.45 * k / len(cenas), f"Gravando a narração da cena {k + 1} de {len(cenas)}…")
            try:
                arq = narrar(txt, opts["voz"], pasta / f"voz_{k:03d}", opts["velocidade"])
                md = montagem.adicionar_midia(pid, arq, f"Narração {k + 1}{arq.suffix}")
                dur_fala = float(md["duration"] or 0)
            except Exception as e:
                aviso = str(e)[:160]
                opts["voz"] = "nenhuma"  # sem voz para o resto: o vídeo sai mesmo assim
        if not dur_fala:
            dur_fala = max(2.5, n / 2.6)  # tempo de leitura na tela
        inicio = t + (0.25 if md else 0.0)
        # tempo de cada palavra proporcional ao tamanho dela (a fala é contínua dentro da cena)
        pesos = [len(w["w"]) + 2 for w in words[c["i0"]:c["i1"] + 1]]
        tot = sum(pesos)
        acc = 0.0
        for j, w in enumerate(words[c["i0"]:c["i1"] + 1]):
            w["s"] = round(inicio + dur_fala * acc / tot, 3)
            acc += pesos[j]
            w["e"] = round(inicio + dur_fala * acc / tot, 3)
        if md:
            narr.append((md["id"], inicio, dur_fala))
        c["s"], c["e"] = t, inicio + dur_fala + 0.35
        t = c["e"]
    vis, gfs = _visuais(pid, cenas, opts, p)
    p(0.93, "Montando a linha do tempo…")
    r = _finaliza(pid, words, cenas, vis, gfs, narr, t, opts, modo)
    if aviso:
        r["aviso"] = f"A narração parou: {aviso}"
        _salva_estado(pid, aviso=r["aviso"])
    p(1.0, "Pronto!")
    return r


# ---------------------------------------------------------------- 2) ÁUDIO (arquivo ou gravação ao vivo)

def _transcrever(wav: str, progress: Progresso = None, prompt: str = "") -> dict:
    cfg = store.load_config()["transcription"]
    if (cfg.get("provider") or "local") == "none":
        cfg = {**cfg, "provider": "local"}
    samples = aud.read_wav_mono(wav)
    dur = len(samples) / aud.SR
    if (cfg.get("provider") or "local") == "api":
        return transcribe.transcribe_api(wav, cfg, np.zeros(1), dur, progress)
    return transcribe.transcribe_local(wav, cfg, str(store.MODELS), progress, dur)


def _cenas_com_tempo(words: list[dict], cenas: list[dict], total: float) -> None:
    """Cada cena começa um pouco antes da primeira palavra dela e vai até o começo da próxima (sem buracos)."""
    inicios = [0.0] + [max(0.0, words[c["i0"]]["s"] - 0.15) for c in cenas[1:]]
    for k in range(1, len(inicios)):
        inicios[k] = max(inicios[k], inicios[k - 1] + 0.6)
    for k, c in enumerate(cenas):
        c["s"] = inicios[k]
        c["e"] = inicios[k + 1] if k + 1 < len(cenas) else max(total, inicios[k] + 0.6)


def criar_de_audio(pid: str, arquivo_audio: Path, opts: dict, progress: Progresso = None,
                   words: list[dict] | None = None) -> dict:
    """Áudio já gravado (arquivo enviado ou narração ao vivo). Se as palavras já vieram (ao vivo), não transcreve de novo."""
    def p(x, msg):
        if progress:
            progress(x, msg)
    opts = _opts(opts)
    md = montagem.adicionar_midia(pid, arquivo_audio, "Narração" + arquivo_audio.suffix)
    total = float(md["duration"] or 0)
    if total < 1:
        raise RuntimeError("O áudio é curto demais.")
    if not words:
        wav = store.pdir(pid) / "historia16k.wav"
        aud.extract_analysis_audio(str(arquivo_audio), str(wav))
        p(0.02, "Transcrevendo a narração…")
        tr = _transcrever(str(wav), lambda x, msg: p(0.02 + 0.4 * x, msg))
        words = [w for w in tr["words"] if w["w"].strip()]
        wav.unlink(missing_ok=True)
    if len(words) < 3:
        raise RuntimeError("Não entendi fala nesse áudio. Confira se ele tem narração.")
    cenas, modo = planejar(words, opts["formato"], opts["usar_ia"], p)
    _cenas_com_tempo(words, cenas, total)
    vis, gfs = _visuais(pid, cenas, opts, p)
    p(0.93, "Montando a linha do tempo…")
    r = _finaliza(pid, words, cenas, vis, gfs, [(md["id"], 0.0, total)], total, opts, modo)
    p(1.0, "Pronto!")
    return r


# ---------------------------------------------------------------- 3) AO VIVO

def pasta_ao_vivo(pid: str) -> Path:
    d = store.pdir(pid) / "ao_vivo"
    d.mkdir(exist_ok=True)
    return d


def _estado_vivo(pid: str) -> dict:
    f = pasta_ao_vivo(pid) / "estado.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"words": [], "bytes": 0}


def pedaco_ao_vivo(pid: str, pcm: bytes) -> dict:
    """Recebe um pedaço da gravação (PCM 16 bits, 16 kHz, mono), guarda e devolve as palavras dele já com o tempo
    certo dentro da gravação inteira."""
    if len(pcm) % 2:
        pcm = pcm[:-1]
    pasta = pasta_ao_vivo(pid)
    with store.lock(pid):
        st = _estado_vivo(pid)
        inicio = st["bytes"] / 2 / aud.SR
        with open(pasta / "gravacao.pcm", "ab") as fh:
            fh.write(pcm)
        st["bytes"] += len(pcm)
        (pasta / "estado.json").write_text(json.dumps(st), encoding="utf-8")
    novas: list[dict] = []
    amostras = np.frombuffer(pcm, dtype=np.int16)
    if len(amostras) > aud.SR * 0.4 and np.abs(amostras).max() > 300:  # silêncio puro não vai para o Whisper
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "pedaco.wav"
            with wave.open(str(wav), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(aud.SR)
                w.writeframes(pcm)
            tr = _transcrever(str(wav))
        for w in tr["words"]:
            if w["w"].strip():
                novas.append({"w": w["w"].strip(), "s": round(w["s"] + inicio, 3), "e": round(w["e"] + inicio, 3)})
    with store.lock(pid):
        st = _estado_vivo(pid)
        st["words"].extend(novas)
        (pasta / "estado.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    return {"palavras": novas, "inicio": round(inicio, 3), "gravado": round(st["bytes"] / 2 / aud.SR, 2)}


def aquecer() -> None:
    """Carrega o modelo de transcrição antes da primeira fala (a primeira frase ao vivo não fica esperando)."""
    try:
        cfg = store.load_config()["transcription"]
        if (cfg.get("provider") or "local") == "api":
            return
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "aquecer.wav"
            with wave.open(str(wav), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(aud.SR)
                w.writeframes((np.random.randn(aud.SR) * 30).astype(np.int16).tobytes())
            _transcrever(str(wav))
    except Exception:
        pass


def terminar_ao_vivo(pid: str, opts: dict, progress: Progresso = None) -> dict:
    pasta = pasta_ao_vivo(pid)
    pcm = pasta / "gravacao.pcm"
    if not pcm.exists() or pcm.stat().st_size < aud.SR * 2:
        raise RuntimeError("A gravação ficou vazia.")
    st = _estado_vivo(pid)
    dest = montagem.pasta_midias(pid) / "narracao_ao_vivo.wav"
    with wave.open(str(dest), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(aud.SR)
        with open(pcm, "rb") as fh:
            while True:
                b = fh.read(1 << 20)
                if not b:
                    break
                w.writeframes(b)
    words = st["words"]
    if opts.get("retranscrever"):
        words = None  # transcreve a gravação inteira de novo (mais preciso, mais lento)
    r = criar_de_audio(pid, dest, opts, progress, words=words)
    shutil.rmtree(pasta, ignore_errors=True)
    return r


def previa_cena(texto: str, formato: str) -> dict:
    """Para a tela ao vivo: palavras de busca e uma foto do banco para o trecho que acabou de ser falado."""
    q = palavras_chave(texto)
    out = {"busca": q, "imagem": None}
    if any(bancos.status().values()):
        try:
            res = bancos.buscar("todos", "foto", q, 1, _orient(formato))
            itens = res.get("itens") or []
            if itens:
                i = abs(hash(texto)) % min(4, len(itens))
                out["imagem"] = itens[i].get("previa") or itens[i].get("thumb")
        except Exception:
            pass
    return out


def status() -> dict:
    try:
        import edge_tts  # noqa: F401
        edge = True
    except Exception:
        edge = False
    try:
        import PIL  # noqa: F401
        pil = True
    except Exception:
        pil = False
    ai = store.load_config().get("ai") or {}
    mus = sorted(f.name for f in pipeline.MUSICAS.glob("*") if f.is_file() and f.suffix.lower() in montagem.EXT_AUDIO) \
        if pipeline.MUSICAS.exists() else []
    return {"vozes": [{"id": k, "nome": v[2], "ok": (v[0] != "edge" or edge) and (v[0] != "sapi" or os.name == "nt")}
                      for k, v in VOZES.items()],
            "visuais": VISUAIS, "bancos": any(bancos.status().values()), "graficos": pil,
            "ia": ai.get("provider") not in (None, "none") and bool(ai.get("api_key")),
            "transcricao": transcribe.local_available(), "musicas": mus, "pc": os.name == "nt"}

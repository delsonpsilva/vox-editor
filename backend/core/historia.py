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
    "faber": ("piper", "pt_BR-faber-medium", "Faber — masculina, natural (sem internet)"),
    "windows": ("sapi", "", "Voz do Windows (sem internet)"),
    "nenhuma": ("none", "", "Sem narração (só imagens e textos)"),
}
VISUAIS = {"fotos": "Fotos grátis (Pexels, Pixabay e Openverse)", "videos": "Vídeos grátis (Pexels e Pixabay)",
           "ia": "Imagens criadas por IA (Gemini)", "cores": "Fundos coloridos (sem internet)"}
MUSICA_AUTO = "__auto__"
UA = {"User-Agent": "VOXEditor/1.9 (editor de video; contato: suporte@voxapps.app)"}
GEMINI = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_TEXTO = "gemini-flash-latest"
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
    return [{"i0": a, "i1": b, "busca": palavras_chave(_txt(words, a, b)), "destaque": "",
             "grafico": grafico_por_regra(_txt(words, a, b))} for a, b in cenas]


HUMORES_IDS = ("inspirador", "oracao", "piano", "epico", "alegre", "acustico", "louvor", "orquestra", "lofi",
               "corporativo", "suspense", "emocionante")


def humor_por_regra(texto: str) -> str:
    """Clima da música sem IA, pelas palavras da história."""
    t = texto.lower()
    def tem(*ps):
        return sum(t.count(p) for p in ps)
    if tem("deus", "jesus", "senhor", "oração", "orou", "oraram", "fé ", "igreja", "bíblia", "pastor", "graça") >= 2:
        return "oracao"
    if tem("tempestade", "medo", "escuro", "perigo", "noite", "morte", "guerra", "monstro") >= 2:
        return "suspense"
    if tem("alegria", "festa", "riu", "feliz", "brincar", "divertid") >= 2:
        return "alegre"
    if tem("empresa", "venda", "cliente", "mercado", "negócio", "lucro", "produto") >= 2:
        return "corporativo"
    return "emocionante" if tem("lágrima", "chorou", "saudade", "perdão", "abraço") else "inspirador"


PROMPT_CENAS = """Você é diretor de vídeos narrados em português (histórias, devocionais, explicações) para {destino}.
Abaixo está o texto, dividido em frases numeradas. Divida-o em CENAS, na ordem, cobrindo TODAS as frases sem pular
nenhuma. Cada cena tem de 1 a 4 frases (mais ou menos {seg} segundos de fala) e muda quando muda a imagem que
combina com o que está sendo dito.

Para cada cena informe:
- "inicio" e "fim": número da primeira e da última frase da cena;
- "busca": 2 a 4 palavras EM PORTUGUÊS descrevendo uma FOTO concreta que combine com a cena (pessoas, lugares,
  objetos, paisagens, ações). Nada de nomes próprios nem ideias abstratas. Ex.: "pastor ovelhas campo";
- "busca_en": as mesmas palavras de busca, em inglês. Ex.: "shepherd sheep field";
- "imagem": uma descrição EM INGLÊS, de 1 ou 2 frases, para um ilustrador desenhar a cena (quem aparece, onde,
  o que faz, luz e clima), coerente com as outras cenas (mesmos personagens, mesma época e lugar);
- "destaque": um título curto de até 5 palavras para aparecer na tela, SÓ nas cenas que pedem (começo, virada,
  frase marcante). Nas outras, "";
- "grafico": só se a cena citar números, no formato
  {{"tipo": "barras|pizza|linha|numero", "titulo": "...", "rotulos": ["...", "..."], "valores": [10, 20], "sufixo": "%"}}.
  Use "barras" para comparar quantidades, "pizza" para partes de um todo (somam 100%), "linha" para evolução ao
  longo do tempo (anos, meses) e "numero" para um único dado forte (um valor e um rótulo curto). Senão, null.

Escolha também o "humor" da música de fundo, um destes: {humores}.

Responda só com JSON, sem nada antes ou depois:
{{"humor": "inspirador", "cenas": [{{"inicio": 0, "fim": 1, "busca": "...", "busca_en": "...", "imagem": "...", "destaque": "...", "grafico": null}}]}}

Frases:
{frases}"""


def _ler_json(raw: str):
    for padrao in (r"\{.*\}", r"\[.*\]"):
        m = re.search(padrao, raw, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                continue
    raise RuntimeError("A IA não devolveu as cenas no formato esperado.")


def cenas_por_ia(words: list[dict], fr: list[list[int]], formato: str, ai: dict) -> tuple[list[dict], str]:
    from ..engine.smartcuts import _call_llm
    linhas = "\n".join(f"[{k}] {_txt(words, a, b)}" for k, (a, b) in enumerate(fr))
    raw = _call_llm(PROMPT_CENAS.format(destino="Reels/Shorts/TikTok" if formato == "9:16" else "YouTube",
                                        seg="6 a 9" if formato == "9:16" else "8 a 14", humores=", ".join(HUMORES_IDS),
                                        frases=linhas[:200_000]), ai)
    js = _ler_json(raw)
    humor = ""
    if isinstance(js, dict):
        humor = str(js.get("humor") or "")
        js = js.get("cenas") or []
    lst = [x for x in js if isinstance(x, dict)] if isinstance(js, list) else []
    n = len(fr)
    cenas, prox = [], 0
    for x in sorted(lst, key=lambda x: int(x.get("inicio") or 0) if str(x.get("inicio") or 0).isdigit() else 0):
        try:
            fim = int(x.get("fim"))
        except (TypeError, ValueError):
            continue
        fim = min(n - 1, fim)
        if fim < prox:
            continue
        limpa = lambda k, n_: re.sub(r"\s+", " ", str(x.get(k) or "")).strip()[:n_]  # noqa: E731
        cenas.append({"i0": fr[prox][0], "i1": fr[fim][1], "busca": limpa("busca", 60), "busca_en": limpa("busca_en", 60),
                      "imagem": limpa("imagem", 600), "destaque": limpa("destaque", 48),
                      "grafico": _grafico_limpo(x.get("grafico"))})
        prox = fim + 1
    if not cenas:
        raise RuntimeError("A IA não devolveu cenas.")
    if prox < n:  # o que a IA esqueceu no fim entra na última cena
        cenas[-1]["i1"] = fr[-1][1]
    for c in cenas:
        if not c["busca"]:
            c["busca"] = palavras_chave(_txt(words, c["i0"], c["i1"]))
    texto = _txt(words, 0, len(words) - 1)
    return cenas, humor if humor in HUMORES_IDS else humor_por_regra(texto)


TIPOS_GRAFICO = ("barras", "pizza", "linha", "numero")


def _grafico_limpo(g) -> dict | None:
    """Gráfico pedido pela IA: barras (comparar), pizza (partes de um todo), linha (evolução no tempo) ou número
    (um dado grande que conta de 0 até o valor)."""
    if not isinstance(g, dict):
        return None
    tipo = g.get("tipo") if g.get("tipo") in TIPOS_GRAFICO else "barras"
    rot = [str(x)[:22] for x in (g.get("rotulos") or [])][:8]
    val = []
    for v in (g.get("valores") or [])[:8]:
        try:
            val.append(float(str(v).replace(",", ".").replace("%", "").strip()))
        except ValueError:
            return None
    suf = str(g.get("sufixo") or "")[:6]
    if tipo == "numero":
        if not val:
            return None
        return {"tipo": "numero", "titulo": str(g.get("titulo") or "")[:60], "rotulos": rot[:1] or [""],
                "valores": val[:1], "sufixo": suf}
    if len(rot) < 2 or len(rot) != len(val) or max(val) <= 0 or min(val) < 0:
        return None
    return {"tipo": tipo, "titulo": str(g.get("titulo") or "")[:60], "rotulos": rot, "valores": val, "sufixo": suf}


def grafico_por_regra(texto: str) -> dict | None:
    """Sem IA: uma porcentagem na cena vira um número grande animado ("70%")."""
    achados = re.findall(r"(\d{1,3}(?:[.,]\d+)?)\s?(%|por cento)", texto)
    if len(achados) != 1:
        return None
    v = float(achados[0][0].replace(",", "."))
    depois = texto.split(achados[0][0], 1)[1]
    depois = re.sub(r"^\s?(%|por cento)", "", depois).strip(" ,.;:")
    rot = " ".join(depois.split()[:5])
    return {"tipo": "numero", "titulo": "", "rotulos": [rot], "valores": [v], "sufixo": "%"}


def planejar(words: list[dict], formato: str, usar_ia: bool, progress: Progresso = None) -> tuple[list[dict], str, str]:
    """Cenas, como foram feitas ("ia" ou "local") e o humor da música."""
    fr = frases(words)
    if not fr:
        raise RuntimeError("Não há texto para virar vídeo.")
    ai = store.load_config().get("ai") or {}
    if usar_ia and ai.get("provider") not in (None, "none") and ai.get("api_key"):
        if progress:
            progress(0.0, "A IA está dividindo a história em cenas…")
        try:
            cenas, humor = cenas_por_ia(words, fr, formato, ai)
            return cenas, "ia", humor
        except Exception as e:  # a IA nunca trava o vídeo: segue pela divisão local
            if progress:
                progress(0.0, f"IA indisponível ({str(e)[:80]}). Dividindo as cenas sem IA…")
    return cenas_por_regra(words, fr, formato), "local", humor_por_regra(_txt(words, 0, len(words) - 1))


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


PIPER_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/{nome}/{qual}/pt_BR-{nome}-{qual}{ext}?download=true"
_PIPER: dict = {}


def piper_disponivel() -> bool:
    try:
        import piper  # noqa: F401
        return True
    except Exception:
        return False


def _modelo_piper(voz: str) -> Path:
    """Baixa a voz (uns 60 MB) na primeira vez e guarda em dados/modelos/piper. Depois funciona sem internet."""
    import httpx
    pasta = store.MODELS / "piper"
    pasta.mkdir(parents=True, exist_ok=True)
    _, nome, qual = voz.split("-")
    for ext in (".onnx.json", ".onnx"):
        arq = pasta / f"{voz}{ext}"
        if arq.exists() and arq.stat().st_size > 1000:
            continue
        tmp = arq.with_suffix(arq.suffix + ".baixando")
        try:
            with httpx.stream("GET", PIPER_URL.format(nome=nome, qual=qual, ext=ext), headers=UA, follow_redirects=True,
                              timeout=httpx.Timeout(20.0, read=120.0)) as r:
                if r.status_code != 200:
                    raise RuntimeError(f"não consegui baixar a voz (erro {r.status_code})")
                with open(tmp, "wb") as fh:
                    for b in r.iter_bytes(1 << 20):
                        fh.write(b)
            tmp.replace(arq)
        finally:
            tmp.unlink(missing_ok=True)
    return pasta / f"{voz}.onnx"


def _voz_piper(texto: str, voz: str, destino: Path, velocidade: int) -> Path:
    from piper import PiperVoice
    try:
        from piper import SynthesisConfig
    except Exception:
        SynthesisConfig = None
    if voz not in _PIPER:
        _PIPER[voz] = PiperVoice.load(str(_modelo_piper(voz)))
    v = _PIPER[voz]
    out = destino.with_suffix(".wav")
    with wave.open(str(out), "wb") as wf:
        cfg = SynthesisConfig(length_scale=max(0.6, min(1.6, 1 - velocidade / 100))) if SynthesisConfig else None
        if hasattr(v, "synthesize_wav"):
            v.synthesize_wav(texto, wf, syn_config=cfg)
        else:  # piper-tts antigo (1.2)
            v.synthesize(texto, wf, length_scale=max(0.6, min(1.6, 1 - velocidade / 100)))
    if not out.exists() or out.stat().st_size < 1000:
        raise RuntimeError("A voz offline não gerou o áudio.")
    return out


def narrar(texto: str, voz: str, destino: Path, velocidade: int = 0) -> Path | None:
    """Gera a narração de um trecho. Se a voz da internet falhar, tenta a do Windows."""
    motor, nome, _ = VOZES.get(voz, VOZES["francisca"])
    if motor == "none":
        return None
    if motor == "piper":
        try:
            return _voz_piper(texto, nome, destino, velocidade)
        except Exception as e:
            if os.name != "nt":
                raise RuntimeError(f"A voz offline falhou: {str(e)[:120]}")
            return _voz_windows(texto, destino, velocidade)
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


def _do_banco(pid: str, cena: dict, dur: float, formato: str, visual: str, usados: set) -> dict | None:
    """Pexels/Pixabay (precisa de chave grátis). Vídeo mais curto que a cena entra em câmera lenta (até 0,55×)."""
    if not any(bancos.status().values()):
        return None
    termos = [t for t in (cena.get("busca"), cena.get("busca_en")) if t]
    for tipo in (["video", "foto"] if visual == "videos" else ["foto"]):
        for termo in termos:
            try:
                res = bancos.buscar("todos", tipo, termo, 1, _orient(formato))
            except Exception:
                continue
            for it in res.get("itens") or []:
                d_clip = float(it.get("dur") or 0)
                if it["id"] in usados or (tipo == "video" and d_clip < dur * 0.55 + 0.3):
                    continue
                try:
                    arq, info = bancos.baixar(it["id"], montagem.pasta_midias(pid))
                    md = montagem.adicionar_midia(pid, arq, f"{termo[:60]} — {info['autor'] or info['fonte']}"
                                                  f"{info['ext']}", {"credito": info["credito"],
                                                                     "licenca": bancos.FONTES[info["fonte"]],
                                                                     "banco": it["id"]})
                except Exception:
                    continue
                usados.add(it["id"])
                if md["kind"] == "video":
                    real = float(md.get("duration") or d_clip)
                    md = {**md, "_speed": 1.0 if real >= dur + 0.3 else max(0.55, round((real - 0.2) / dur, 3))}
                return md
    return None


OPENVERSE = "https://api.openverse.org/v1/images/"


def _openverse(pid: str, cena: dict, formato: str, usados: set) -> dict | None:
    """Fotos livres sem chave nenhuma (Openverse: Flickr, Wikimedia e outros, só licenças de uso comercial)."""
    import httpx
    o = _orient(formato)
    for termo in [t for t in (cena.get("busca_en"), cena.get("busca")) if t]:
        try:
            r = httpx.get(OPENVERSE, params={"q": termo, "license_type": "commercial,modification", "page_size": 20,
                                             "mature": "false", "size": "large",
                                             "aspect_ratio": {"portrait": "tall", "landscape": "wide"}.get(o, "square")},
                          headers=UA, timeout=15.0, follow_redirects=True)
            if r.status_code != 200:
                continue
            itens = r.json().get("results") or []
        except Exception:
            continue
        for it in itens:
            iid, url = "ov-" + str(it.get("id") or ""), it.get("url") or ""
            if iid in usados or not url.startswith("https://"):
                continue
            arq = montagem.pasta_midias(pid) / f"{iid[:40]}.jpg"
            try:
                with httpx.stream("GET", url, headers=UA, timeout=httpx.Timeout(15.0, read=60.0),
                                  follow_redirects=True) as rr:
                    if rr.status_code != 200:
                        continue
                    dados = b""
                    for b in rr.iter_bytes(256 * 1024):
                        dados += b
                        if len(dados) > 15 * 1024 * 1024:
                            raise RuntimeError("grande demais")
                import cv2
                img = cv2.imdecode(np.frombuffer(dados, np.uint8), cv2.IMREAD_COLOR)
                if img is None or min(img.shape[:2]) < 400:
                    continue
                cv2.imwrite(str(arq), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
                autor = re.sub(r"\s+", " ", str(it.get("creator") or "autor"))[:60]
                lic = f"{str(it.get('license') or '').upper()} {it.get('license_version') or ''}".strip()
                credito = f"Foto: {autor} / {it.get('source') or 'Openverse'} ({it.get('foreign_landing_url') or ''}) · {lic}"
                md = montagem.adicionar_midia(pid, arq, f"{termo[:60]} — {autor}.jpg",
                                              {"credito": credito, "licenca": lic, "banco": iid})
            except Exception:
                arq.unlink(missing_ok=True)
                continue
            usados.add(iid)
            return md
    return None


def chave_gemini() -> str:
    cfg = store.load_config()
    k = ((cfg.get("gemini") or {}).get("api_key") or "").strip()
    ai = cfg.get("ai") or {}
    if not k and "generativelanguage.googleapis.com" in (ai.get("base_url") or ""):
        k = (ai.get("api_key") or "").strip()
    return k


def prompt_imagem(cena: dict, texto: str, estilo: str) -> str:
    base = cena.get("imagem") or f"Uma cena desta história: {texto[:400]}"
    return (f"{base}\n\nStyle: {estilo}. Vertical composition safe for subtitles at the bottom. "
            "No text, no letters, no captions, no watermark, no logos.")


ESTILOS = {"realista": "cinematic realistic photo, soft natural light, shallow depth of field",
           "biblico": "cinematic realistic biblical era scene, ancient Middle East, warm golden light",
           "pintura": "classic oil painting, rich colors, dramatic light",
           "desenho": "colorful 2D illustrated storybook, clean shapes, friendly",
           "3d": "3D animated movie style, soft lighting, expressive characters"}


def _gemini_imagem(pid: str, k: int, prompt: str, formato: str) -> dict:
    import base64
    import httpx
    chave = chave_gemini()
    if not chave:
        raise RuntimeError("Coloque a chave do Gemini (grátis no Google AI Studio) para criar imagens com IA.")
    modelo = (store.load_config().get("gemini") or {}).get("img_model") or "gemini-2.5-flash-image"
    corpo = {"contents": [{"parts": [{"text": prompt}]}],
             "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": formato}}}
    url = f"{GEMINI}/models/{modelo}:generateContent"
    h = {"x-goog-api-key": chave, "Content-Type": "application/json"}
    r = httpx.post(url, headers=h, json=corpo, timeout=180)
    if r.status_code == 400 and "imageConfig" in r.text:  # modelo antigo sem a opção de proporção
        corpo["generationConfig"].pop("imageConfig")
        r = httpx.post(url, headers=h, json=corpo, timeout=180)
    if r.status_code == 429:
        raise PermissionError("A cota de imagens do Gemini acabou (o Google libera imagens só com faturamento ativo "
                              "no AI Studio). As outras cenas usam fotos grátis.")
    if r.status_code != 200:
        raise RuntimeError(f"Gemini respondeu {r.status_code}: {r.text[:200]}")
    for cand in r.json().get("candidates") or []:
        for part in (cand.get("content") or {}).get("parts") or []:
            dado = part.get("inlineData") or part.get("inline_data")
            if dado and dado.get("data"):
                ext = ".png" if "png" in (dado.get("mimeType") or dado.get("mime_type") or "") else ".jpg"
                arq = montagem.pasta_midias(pid) / f"ia_{k:03d}{ext}"
                arq.write_bytes(base64.b64decode(dado["data"]))
                return montagem.adicionar_midia(pid, arq, f"Imagem IA {k + 1}{ext}", {"credito": "Imagem criada por IA (Gemini)"})
    raise RuntimeError("O Gemini não devolveu imagem para esta cena (pode ter sido barrada pelo filtro).")


def visual_da_cena(pid: str, k: int, cena: dict, dur: float, formato: str, visual: str, usados: set,
                   texto: str = "", estado: dict | None = None) -> dict:
    """Mídia de fundo da cena. Ordem: IA (se escolhida) → Pexels/Pixabay → Openverse (sem chave) → fundo colorido."""
    estado = estado if estado is not None else {}
    W, H = montagem.FORMATOS[formato]
    if visual == "ia" and not estado.get("ia_parou"):
        try:
            return _gemini_imagem(pid, k, prompt_imagem(cena, texto, ESTILOS.get(estado.get("estilo"), ESTILOS["realista"])),
                                  formato)
        except PermissionError as e:
            estado["ia_parou"] = str(e)
        except Exception as e:
            estado.setdefault("falhas_ia", []).append(str(e)[:160])
    if visual != "cores":
        md = _do_banco(pid, cena, dur, formato, visual, usados)
        if md:
            return md
        md = _openverse(pid, cena, formato, usados)
        if md:
            return md
        estado["coloridas"] = estado.get("coloridas", 0) + 1
    return _fundo_cor(pid, k, W, H)


CORES_GRAFICO = ["#FF8A3D", "#2EE6FF", "#FACC15", "#4ADE80", "#C084FC", "#F87171", "#60A5FA", "#F472B6"]


def _rgb(h: str) -> tuple[int, int, int]:
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5)) if re.fullmatch(r"#[0-9a-fA-F]{6}", h or "") else (255, 138, 61)


def _fmt_num(v: float, suf: str = "") -> str:
    if abs(v - round(v)) < 1e-6:
        txt = f"{int(round(v)):,}".replace(",", ".")
    else:
        txt = f"{v:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return txt + suf


def quadro_grafico(g: dict, cw: int, ch: int, p: float, cor_marca: str):
    """Um quadro do gráfico com a animação em p (0 = começo, 1 = completo). Imagem RGBA."""
    from PIL import Image, ImageDraw, ImageFont
    p = max(0.0, min(1.0, p))
    e = 1 - (1 - p) ** 3  # desacelerando
    img = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, cw - 1, ch - 1], radius=int(min(cw, ch) * 0.06), fill=(14, 15, 18, 220))
    fb, fr = str(store.FONTS / "Poppins-ExtraBold.ttf"), str(store.FONTS / "Poppins-Bold.ttf")
    t_tit, t_rot = int(ch * 0.085), int(ch * 0.055)
    ft, fl = ImageFont.truetype(fb, t_tit), ImageFont.truetype(fr, t_rot)
    pad = int(ch * 0.07)
    cores = [_rgb(cor_marca)] + [_rgb(c) for c in CORES_GRAFICO[1:]]
    suf = g.get("sufixo") or ""
    tipo = g.get("tipo") or "barras"
    if g.get("titulo") and tipo != "numero":
        d.text((pad, pad), g["titulo"], font=ft, fill=(255, 255, 255, 255))
    topo = pad * 2 + (t_tit if g.get("titulo") else 0)
    vals, rots = g["valores"], g["rotulos"]

    def corta(txt, fonte, larg):
        while d.textlength(txt, font=fonte) > larg and len(txt) > 3:
            txt = txt[:-2] + "…"
        return txt

    if tipo == "numero":
        inteiro = abs(vals[0] - round(vals[0])) < 1e-6
        v = vals[0] if p >= 1 else vals[0] * e
        fn = ImageFont.truetype(fb, int(ch * 0.34))
        txt = _fmt_num(round(v) if inteiro else round(v, 1), suf)
        tw = d.textlength(txt, font=fn)
        y = ch * 0.22
        if g.get("titulo"):
            tt = corta(g["titulo"], ft, cw - pad * 2)
            d.text((cw / 2 - d.textlength(tt, font=ft) / 2, pad), tt, font=ft, fill=(200, 202, 208, 255))
            y = ch * 0.26
        d.text((cw / 2 - tw / 2, y), txt, font=fn, fill=cores[0] + (255,))
        if rots and rots[0]:
            rr = corta(rots[0], ft, cw - pad * 2)
            d.text((cw / 2 - d.textlength(rr, font=ft) / 2, ch * 0.74), rr, font=ft, fill=(255, 255, 255, 255))
        return img

    if tipo == "pizza":
        tot = sum(vals) or 1
        r = min(ch - topo - pad, cw * 0.42) / 2
        cx, cy = pad + r + cw * 0.02, topo + (ch - topo - pad) / 2
        ang = -90.0
        for i, v in enumerate(vals):
            fatia = 360.0 * v / tot * e
            d.pieslice([cx - r, cy - r, cx + r, cy + r], ang, ang + fatia, fill=cores[i % len(cores)] + (255,))
            ang += fatia
        d.ellipse([cx - r * 0.55, cy - r * 0.55, cx + r * 0.55, cy + r * 0.55], fill=(14, 15, 18, 255))
        x0 = cx + r + pad
        lh = t_rot * 1.7
        y0 = cy - lh * len(vals) / 2
        for i, (rot, v) in enumerate(zip(rots, vals)):
            a = int(255 * min(1.0, max(0.0, e * len(vals) - i)))
            yy = y0 + i * lh
            d.rounded_rectangle([x0, yy + t_rot * 0.2, x0 + t_rot, yy + t_rot * 1.2], radius=4,
                                fill=cores[i % len(cores)] + (a,))
            pct = f"{100 * v / tot:.0f}%"
            d.text((x0 + t_rot * 1.5, yy), corta(f"{rot} — {pct}", fl, cw - x0 - t_rot * 1.5 - pad), font=fl,
                   fill=(255, 255, 255, a))
        return img

    base = ch - pad - t_rot * 2
    larg_util = cw - pad * 2
    n = len(vals)
    vmax = max(vals) or 1
    alt_max = base - topo - t_rot * 1.6
    if tipo == "linha":
        xs = [pad + larg_util * (i + 0.5) / n for i in range(n)]
        ys = [base - alt_max * (v / vmax) for v in vals]
        d.line([(pad, base), (cw - pad, base)], fill=(80, 84, 94, 255), width=2)
        alcance = e * (n - 1)
        pts = []
        for i in range(n):
            if i <= alcance:
                pts.append((xs[i], ys[i]))
            elif i - 1 < alcance:
                f = alcance - (i - 1)
                pts.append((xs[i - 1] + (xs[i] - xs[i - 1]) * f, ys[i - 1] + (ys[i] - ys[i - 1]) * f))
        if len(pts) >= 2:
            d.line(pts, fill=cores[0] + (255,), width=max(4, int(ch * 0.012)), joint="curve")
        for i in range(n):
            if i <= alcance + 1e-6:
                rr = max(6, int(ch * 0.016))
                d.ellipse([xs[i] - rr, ys[i] - rr, xs[i] + rr, ys[i] + rr], fill=(255, 255, 255, 255))
                val = _fmt_num(vals[i], suf)
                d.text((xs[i] - d.textlength(val, font=fl) / 2, ys[i] - t_rot * 1.7), val, font=fl, fill=(255, 255, 255, 255))
            rot = corta(rots[i], fl, larg_util / n * 0.95)
            d.text((xs[i] - d.textlength(rot, font=fl) / 2, base + t_rot * 0.4), rot, font=fl, fill=(200, 202, 208, 255))
        return img

    larg = larg_util / n
    for i, (rot, v) in enumerate(zip(rots, vals)):
        passo = min(0.12, 0.6 / max(1, n - 1))  # cada barra começa um pouco depois da anterior
        q = max(0.0, min(1.0, (p - i * passo) / (1 - (n - 1) * passo)))
        ei = 1 - (1 - q) ** 3
        bw = min(larg * 0.64, ch * 0.32)
        x0 = pad + i * larg + (larg - bw) / 2
        x1 = x0 + bw
        alt = alt_max * (v / vmax) * ei
        y0 = base - alt
        if alt > 1:
            d.rounded_rectangle([x0, min(y0, base - 2), x1, base], radius=max(2, min(int(bw * 0.1), int(alt / 2))),
                                fill=cores[0] + (255,))
        vv = v if ei >= 1 else v * ei
        val = _fmt_num(round(vv) if abs(v - round(v)) < 1e-6 else round(vv, 1), suf)
        d.text(((x0 + x1) / 2 - d.textlength(val, font=fl) / 2, y0 - t_rot * 1.4), val, font=fl,
               fill=(255, 255, 255, int(255 * min(1, ei * 3))))
        rr = corta(rot, fl, larg * 0.95)
        d.text((pad + i * larg + larg / 2 - d.textlength(rr, font=fl) / 2, base + t_rot * 0.4), rr, font=fl,
               fill=(200, 202, 208, 255))
    return img


def _tamanho_grafico(g: dict, formato: str) -> tuple[int, int]:
    W, H = montagem.FORMATOS[formato]
    if g.get("tipo") == "numero":
        return int(W * 0.8) // 2 * 2, int(min(H * 0.34, W * 0.5)) // 2 * 2
    return int(W * 0.86) // 2 * 2, int(min(H * 0.62, W * 0.62)) // 2 * 2


def grafico_png(pid: str, k: int, g: dict, formato: str) -> dict | None:
    """Gráfico parado (PNG transparente) — usado quando o vídeo animado não pode ser feito."""
    try:
        cw, ch = _tamanho_grafico(g, formato)
        img = quadro_grafico(g, cw, ch, 1.0, store.load_config().get("brand", {}).get("color") or "#FF8A3D")
    except Exception:
        return None
    arq = montagem.pasta_midias(pid) / f"grafico_{k:03d}.png"
    img.save(arq)
    return montagem.adicionar_midia(pid, arq, f"Gráfico {k + 1}.png")


def grafico_animado(pid: str, k: int, g: dict, formato: str, dur: float) -> dict | None:
    """Gráfico que se desenha na tela (barras crescendo, pizza girando, linha avançando, número contando), como
    vídeo com fundo transparente (WebM VP9 com alfa), do tamanho exato da cena. Se falhar, vira PNG parado."""
    try:
        import PIL  # noqa: F401
    except Exception:
        return None
    cw, ch = _tamanho_grafico(g, formato)
    cor = store.load_config().get("brand", {}).get("color") or "#FF8A3D"
    fps, anim = 30, 1.4
    n_anim = int(fps * anim)
    pasta = montagem.pasta_midias(pid)
    tmp = Path(tempfile.mkdtemp(dir=str(pasta)))
    arq = pasta / f"grafico_{k:03d}.webm"
    try:
        for i in range(n_anim + 1):
            quadro_grafico(g, cw, ch, i / n_anim, cor).save(tmp / f"q{i:04d}.png")
        resto = max(0.1, dur - anim)
        ff.run([ff.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-framerate", str(fps), "-i",
                str(tmp / "q%04d.png"), "-vf", f"tpad=stop_mode=clone:stop_duration={resto:.3f},format=yuva420p",
                "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "34", "-deadline", "realtime",
                "-cpu-used", "8", "-an", str(arq)])
        return montagem.adicionar_midia(pid, arq, f"Gráfico animado {k + 1}.webm", {"alpha": True})
    except Exception:
        arq.unlink(missing_ok=True)
        return grafico_png(pid, k, g, formato)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


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
            {"id": "t_logo", "kind": "video", "name": "Marca", **base},
            {"id": "t_v2", "kind": "video", "name": "Gráficos", **base},
            {"id": "t_v1", "kind": "video", "name": "Cenas", "main": True, **base},
            {"id": "t_audio", "kind": "audio", "name": "Narração", **base},
            {"id": "t_musica", "kind": "audio", "name": "Música", **base}]


def _item(kind: str, track: str, src: str | None, start: float, dur: float, **kw) -> dict:
    return montagem._item_base(kind, track, src, start, dur, 0.0, **kw)


# movimentos de câmera nas fotos (Ken Burns), em rodízio: (escala início, escala fim, x0, x1, y0, y1)
MOVIMENTOS = [(1.0, 1.14, 0.5, 0.5, 0.5, 0.5),        # aproxima
              (1.14, 1.0, 0.5, 0.5, 0.5, 0.5),        # afasta
              (1.12, 1.12, 0.535, 0.465, 0.5, 0.5),   # passeia para a direita
              (1.04, 1.16, 0.5, 0.5, 0.53, 0.47),     # sobe aproximando
              (1.12, 1.12, 0.465, 0.535, 0.5, 0.5),   # passeia para a esquerda
              (1.16, 1.04, 0.5, 0.5, 0.47, 0.52)]     # desce afastando

ESTILOS_LEGENDA = ("palavra_ativa", "caixa_ativa", "destaque", "uma_palavra", "impacto", "neon", "caixa", "classico")


def legenda_viva(words: list[dict], estilo: str, vertical: bool) -> dict | None:
    """Legenda animada nos estilos do editor (palavra em foco, karaokê...), com as palavras-chave coloridas."""
    from ..engine import destaques, subtitles as sb
    if estilo not in sb.STYLES:
        estilo = "palavra_ativa"
    try:
        ws = destaques.marcar(words, destaques.locais(words))
    except Exception:
        ws = words
    cfg = {**sb.STYLES[estilo], "style": estilo, "keywords": True, "size_pct": 125}
    if not vertical and cfg["max_chars"] < 26 and estilo != "uma_palavra":
        cfg["max_chars"] = 30
    caps = sb.build_captions(ws, None, cfg)
    return {"cfg": cfg, "caps": caps} if caps else None


def montar(pid: str, words: list[dict], cenas: list[dict], visuais: list[dict], graficos: list[dict | None],
           narracoes: list[tuple[str, float, float]], total: float, opts: dict) -> dict:
    """Escreve a Montagem: cenas com movimento e transição, títulos animados, gráficos, legenda, narração, música,
    logo e encerramento com a marca."""
    formato = opts["formato"]
    W, H = montagem.FORMATOS[formato]
    vertical = H > W
    m = montagem.carregar(pid)
    m.update(formato=formato, w=W, h=H, tracks=trilhas(), items=[], markers=[], legenda_viva=None)
    itens = []
    if opts.get("abertura", True) and cenas and not cenas[0].get("destaque") and opts.get("titulo"):
        cenas[0]["destaque"] = opts["titulo"][:48]
    for k, c in enumerate(cenas):
        s, e = c["s"], c["e"]
        dur = max(0.5, e - s)
        md = visuais[k]
        kw = {"fit": "cover", "volume": 0.0}
        if md["kind"] == "video":
            kw["speed"] = md.get("_speed", 1.0)
        if md["kind"] == "image":
            s0, s1, x0, x1, y0, y1 = MOVIMENTOS[k % len(MOVIMENTOS)]
            kw["kf"] = [{"t": 0, "scale": s0, "x": x0, "y": y0, "e": "linear"},
                        {"t": round(dur, 3), "scale": s1, "x": x1, "y": y1, "e": "linear"}]
        if k > 0:
            kw["tr"] = {"tipo": "dissolver", "dur": 0.6}
        itens.append(_item(md["kind"], "t_v1", md["id"], s, dur, **kw))
        if c.get("destaque"):
            ini = s + (0.2 if k == 0 else 0.35)
            dd = max(0.9, min(3.2, dur) - 0.35)
            y = 0.2 if vertical else 0.18
            itens.append(_item("text", "t_titulo", None, ini, dd,
                               text=_quebra(c["destaque"], 14 if vertical else 26), font="Anton",
                               size=0.12 if vertical else 0.1, color="#FFFFFF", stroke="#000000", strokeW=0.0,
                               boxOn=True, box="#000000", boxAlpha=0.45, upper=True, y=y, fadeOut=0.3,
                               kf=[{"t": 0, "scale": 0.7, "opacity": 0, "y": y + 0.02, "e": "entrada"},
                                   {"t": 0.35, "scale": 1.06, "opacity": 1, "y": y, "e": "saida"},
                                   {"t": 0.5, "scale": 1.0, "opacity": 1, "y": y, "e": "suave"}]))
        g = graficos[k]
        if g:
            gd = max(0.8, dur - 0.6)
            itens.append(_item(g["kind"], "t_v2", g["id"], s + 0.4, gd, fit="contain", scale=0.95,
                               y=0.42 if vertical else 0.46, fadeIn=0.3, fadeOut=0.3, volume=0.0))
    fim = total
    marca = store.load_config().get("brand") or {}
    logo = store.marca_dir() / "logo.png"
    logo_md = None
    if logo.exists() and (opts.get("logo") or opts.get("encerramento")):
        dest = montagem.pasta_midias(pid) / "marca_logo.png"
        shutil.copy(logo, dest)
        try:
            logo_md = montagem.adicionar_midia(pid, dest, "Logo.png")
        except Exception:
            logo_md = None
    if opts.get("encerramento") and (logo_md or marca.get("handle")):
        d_fim = 3.0
        cor = marca.get("bg") if re.fullmatch(r"#[0-9a-fA-F]{6}", marca.get("bg") or "") else "#101114"
        itens.append(_item("color", "t_v1", None, total, d_fim, color=cor, w=1.0, h=1.0, tr={"tipo": "dissolver", "dur": 0.6}))
        if logo_md:
            itens.append(_item("image", "t_v2", logo_md["id"], total + 0.3, d_fim - 0.3, fit="contain",
                               scale=0.32 if vertical else 0.26, y=0.4, fadeIn=0.4,
                               kf=[{"t": 0, "scale": 0.24 if vertical else 0.2, "e": "entrada"},
                                   {"t": 0.6, "scale": 0.32 if vertical else 0.26, "e": "suave"}]))
        handle = (marca.get("handle") or "").strip()
        if handle and not handle.startswith("@"):
            handle = "@" + handle
        chamada = "Siga para mais histórias" if vertical else "Inscreva-se e ative o sininho"
        y_txt = 0.62 if logo_md else 0.5
        if handle:
            itens.append(_item("text", "t_titulo", None, total + 0.5, d_fim - 0.5, text=handle, font="Poppins ExtraBold",
                               size=0.075 if vertical else 0.06, color=marca.get("color") or "#FF8A3D", y=y_txt, fadeIn=0.3))
        itens.append(_item("text", "t_legenda", None, total + 0.8, d_fim - 0.8, text=chamada, font="Poppins",
                           size=0.045 if vertical else 0.04, color="#FFFFFF", y=y_txt + (0.07 if vertical else 0.09),
                           fadeIn=0.3))
        fim = total + d_fim
    if opts.get("logo") and logo_md:
        itens.append(_item("image", "t_logo", logo_md["id"], 0.0, total, fit="contain", scale=0.13 if vertical else 0.1,
                           x=0.86 if vertical else 0.92, y=0.06 if vertical else 0.09, opacity=0.85))
    if opts.get("legenda", True):
        estilo = opts.get("legenda_estilo") or "palavra_ativa"
        lv = legenda_viva(words, estilo, vertical) if estilo != "texto" else None
        if lv:
            m["legenda_viva"] = lv
        else:
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
            while t < fim - 0.2:
                d = min(md["duration"], fim - t)
                itens.append(_item("audio", "t_musica", mus, t, d, volume=0.14, duck=True,
                                   fadeIn=1.0 if t == 0 else 0.0, fadeOut=2.0 if t + d >= fim - 0.3 else 0.0))
                t += d
    m["items"] = itens
    return montagem.salvar(pid, m)


# ---------------------------------------------------------------- etapas comuns

def _musica(pid: str, nome: str, humor: str, avisos: list[str]) -> str | None:
    """Música escolhida das "Minhas músicas" ou, no automático, uma faixa livre da biblioteca (Openverse) pelo humor."""
    if nome == MUSICA_AUTO:
        from . import trilhas as tl
        try:
            res = tl.buscar("", humor or "inspirador")
            faixas = [f for f in res.get("faixas") or [] if (f.get("duration") or 0) >= 45] or res.get("faixas") or []
            if not faixas:
                raise RuntimeError("nenhuma música encontrada")
            faixas.sort(key=lambda f: (f.get("license") != "cc0", -(f.get("duration") or 0)))
            for f in faixas[:5]:
                try:
                    arq, info = tl.baixar(f["id"], montagem.pasta_midias(pid))
                    md = montagem.adicionar_midia(pid, arq, f"{info['title'] or 'Música'} — {info['creator'] or 'autor'}{arq.suffix}",
                                                  {"credito": info["credito"], "licenca": info["license"], "trilha": info["id"]})
                    _salva_estado(pid, musica={"titulo": info["title"], "credito": info["credito"], "humor": humor})
                    return md["id"]
                except Exception:
                    continue
            raise RuntimeError("não consegui baixar")
        except Exception as e:
            avisos.append(f"Música automática indisponível agora ({str(e)[:80]}).")
            return None
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


def _visuais(pid: str, words: list[dict], cenas: list[dict], opts: dict, p, avisos: list[str]) -> tuple[list[dict], list]:
    usados: set = set()
    estado = {"estilo": opts.get("estilo")}
    vis, gfs = [], []
    for k, c in enumerate(cenas):
        o_que = "Criando a imagem" if opts.get("visual") == "ia" and not estado.get("ia_parou") else "Escolhendo a imagem"
        p(0.55 + 0.35 * k / max(1, len(cenas)), f"{o_que} da cena {k + 1} de {len(cenas)}: “{c['busca']}”…")
        vis.append(visual_da_cena(pid, k, c, c["e"] - c["s"], opts["formato"], opts.get("visual", "fotos"), usados,
                                  _txt(words, c["i0"], c["i1"]), estado))
        if c.get("grafico"):
            p(0.55 + 0.35 * (k + 0.5) / max(1, len(cenas)), f"Desenhando o gráfico da cena {k + 1}…")
            gfs.append(grafico_animado(pid, k, c["grafico"], opts["formato"], max(0.8, c["e"] - c["s"] - 0.6)))
        else:
            gfs.append(None)
    if estado.get("ia_parou"):
        avisos.append(estado["ia_parou"])
    elif estado.get("falhas_ia"):
        avisos.append(f"{len(estado['falhas_ia'])} imagem(ns) da IA falharam e viraram foto grátis: {estado['falhas_ia'][0]}")
    if estado.get("coloridas"):
        sem = "" if any(bancos.status().values()) else " Coloque a chave grátis do Pexels para ter mais opções."
        avisos.append(f"{estado['coloridas']} cena(s) ficaram com fundo colorido (não achei imagem).{sem}")
    return vis, gfs


def _opts(o: dict) -> dict:
    formato = o.get("formato") if o.get("formato") in montagem.FORMATOS else "9:16"
    return {"formato": formato, "voz": o.get("voz") if o.get("voz") in VOZES else "francisca",
            "visual": o.get("visual") if o.get("visual") in VISUAIS else "fotos",
            "estilo": o.get("estilo") if o.get("estilo") in ESTILOS else "realista",
            "legenda": o.get("legenda", True) is not False, "usar_ia": bool(o.get("usar_ia", True)),
            "musica": str(o.get("musica") if o.get("musica") is not None else MUSICA_AUTO)[:200],
            "velocidade": max(-50, min(50, int(o.get("velocidade") or 0))),
            "legenda_estilo": o.get("legenda_estilo") if o.get("legenda_estilo") in ESTILOS_LEGENDA + ("texto",)
            else "palavra_ativa",
            "abertura": o.get("abertura", True) is not False, "encerramento": bool(o.get("encerramento", True)),
            "logo": bool(o.get("logo", False)), "titulo": str(o.get("titulo") or "")[:80],
            "retranscrever": bool(o.get("retranscrever", False))}


def novo_projeto(nome: str, formato: str, origem: str) -> str:
    proj = montagem.projeto_em_branco(nome or "História", formato)
    pid = proj["id"]
    store.update(pid, lambda p: p.update(historia={"origem": origem, "criado": time.time()}))
    return pid


def _finaliza(pid: str, words, cenas, vis, gfs, narr, total, opts, modo, humor, avisos) -> dict:
    o = dict(opts)
    o["musica_id"] = _musica(pid, opts.get("musica"), humor, avisos)
    m = montar(pid, words, cenas, vis, gfs, narr, total, o)
    _salva_estado(pid, cenas=[{k: c.get(k, "") for k in ("s", "e", "busca", "destaque")} for c in cenas],
                  modo=modo, duracao=round(total, 2), opcoes=opts, texto=" ".join(w["w"] for w in words)[:MAX_TEXTO],
                  avisos=avisos)
    imgs = {"image": 0, "video": 0}
    for md in vis:
        if not str(md.get("file", "")).split("/")[-1].startswith("fundo_"):
            imgs[md["kind"]] = imgs.get(md["kind"], 0) + 1
    r = {"id": pid, "cenas": len(cenas), "duracao": round(total, 2), "itens": len(m["items"]), "modo": modo,
         "humor": humor, "fotos": imgs.get("image", 0), "videos": imgs.get("video", 0), "musica": bool(o["musica_id"])}
    if avisos:
        r["aviso"] = " ".join(avisos)
    return r


# ---------------------------------------------------------------- 1) TEXTO

def roteiro(texto: str, opts: dict) -> dict:
    """Só o planejamento (rápido): as cenas para a pessoa revisar antes de montar."""
    opts = _opts(opts)
    words = palavras_do_texto(texto)
    if len(words) < 3:
        raise RuntimeError("Escreva pelo menos uma frase.")
    cenas, modo, humor = planejar(words, opts["formato"], opts["usar_ia"])
    return {"modo": modo, "humor": humor, "humores": list(HUMORES_IDS),
            "cenas": [{"texto": _txt(words, c["i0"], c["i1"]), "busca": c.get("busca", ""),
                       "busca_en": c.get("busca_en", ""), "imagem": c.get("imagem", ""),
                       "destaque": c.get("destaque", ""), "grafico": c.get("grafico")} for c in cenas]}


def cenas_revisadas(lst: list) -> tuple[list[dict], list[dict]]:
    """Cenas que voltaram da revisão: o texto de cada uma vira as palavras, na ordem."""
    words, cenas = [], []
    for x in (lst or [])[:300]:
        if not isinstance(x, dict):
            continue
        ws = palavras_do_texto(str(x.get("texto") or ""))
        if not ws:
            continue
        i0 = len(words)
        words.extend(ws)
        limpa = lambda k, n_: re.sub(r"\s+", " ", str(x.get(k) or "")).strip()[:n_]  # noqa: E731
        txt = _txt(words, i0, len(words) - 1)
        cenas.append({"i0": i0, "i1": len(words) - 1, "busca": limpa("busca", 60) or palavras_chave(txt),
                      "busca_en": limpa("busca_en", 60), "imagem": limpa("imagem", 600),
                      "destaque": limpa("destaque", 48), "grafico": _grafico_limpo(x.get("grafico"))})
    return words, cenas


def criar_de_texto(pid: str, texto: str, opts: dict, progress: Progresso = None, cenas_prontas: list | None = None) -> dict:
    def p(x, msg):
        if progress:
            progress(x, msg)
    humor_pedido = opts.get("humor")
    opts = _opts(opts)
    if cenas_prontas:
        words, cenas = cenas_revisadas(cenas_prontas)
        if len(words) < 3:
            raise RuntimeError("As cenas ficaram vazias.")
        modo = "revisado"
        humor = humor_pedido if humor_pedido in HUMORES_IDS else humor_por_regra(_txt(words, 0, len(words) - 1))
    else:
        words = palavras_do_texto(texto)
        if len(words) < 3:
            raise RuntimeError("Escreva pelo menos uma frase.")
        p(0.02, "Lendo a história…")
        cenas, modo, humor = planejar(words, opts["formato"], opts["usar_ia"], p)
    pasta = montagem.pasta_midias(pid)
    narr, t = [], 0.0
    avisos: list[str] = []
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
                avisos.append(f"A narração parou: {str(e)[:160]}")
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
    vis, gfs = _visuais(pid, words, cenas, opts, p, avisos)
    p(0.93, "Montando a linha do tempo e a música…")
    r = _finaliza(pid, words, cenas, vis, gfs, narr, t, opts, modo, humor, avisos)
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
    cenas, modo, humor = planejar(words, opts["formato"], opts["usar_ia"], p)
    _cenas_com_tempo(words, cenas, total)
    avisos: list[str] = []
    vis, gfs = _visuais(pid, words, cenas, opts, p, avisos)
    p(0.93, "Montando a linha do tempo e a música…")
    r = _finaliza(pid, words, cenas, vis, gfs, [(md["id"], 0.0, total)], total, opts, modo, humor, avisos)
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
    """Para a tela ao vivo: palavras de busca e uma foto para o trecho que acabou de ser falado."""
    import httpx
    q = palavras_chave(texto)
    out = {"busca": q, "imagem": None}
    i = abs(hash(texto)) % 4
    if any(bancos.status().values()):
        try:
            itens = bancos.buscar("todos", "foto", q, 1, _orient(formato)).get("itens") or []
            if itens:
                it = itens[i % len(itens)]
                out["imagem"] = it.get("previa") or it.get("thumb")
                return out
        except Exception:
            pass
    try:
        o = _orient(formato)
        r = httpx.get(OPENVERSE, params={"q": q, "license_type": "commercial,modification", "page_size": 8,
                                         "mature": "false", "aspect_ratio": {"portrait": "tall", "landscape": "wide"}.get(o, "square")},
                      headers=UA, timeout=8.0)
        itens = r.json().get("results") or [] if r.status_code == 200 else []
        if itens:
            it = itens[i % len(itens)]
            out["imagem"] = it.get("thumbnail") or it.get("url")
    except Exception:
        pass
    return out


def salvar_chaves(dados: dict) -> dict:
    """Chaves grátis direto na tela da História. A do Gemini também liga a IA do programa (se não houver outra)."""
    up: dict = {}
    for sec in ("pexels", "pixabay"):
        v = str(dados.get(sec) or "").strip()
        if v:
            up[sec] = {"api_key": v}
    g = str(dados.get("gemini") or "").strip()
    if g:
        up["gemini"] = {"api_key": g}
        ai = store.load_config().get("ai") or {}
        if ai.get("provider") in (None, "none") or not ai.get("api_key") or dados.get("gemini_como_ia"):
            up["ai"] = {"provider": "openai_compat", "api_key": g, "model": GEMINI_TEXTO,
                        "base_url": GEMINI + "/openai"}
    if up:
        store.save_config(up)
    return status()


def testar_gemini() -> dict:
    import httpx
    k = chave_gemini()
    if not k:
        return {"ok": False, "msg": "Sem chave do Gemini."}
    try:
        r = httpx.get(f"{GEMINI}/models", headers={"x-goog-api-key": k}, timeout=15)
    except Exception as e:
        return {"ok": False, "msg": f"Sem conexão com o Google: {str(e)[:100]}"}
    if r.status_code != 200:
        return {"ok": False, "msg": f"O Google recusou a chave (erro {r.status_code})."}
    return {"ok": True, "msg": "Chave do Gemini funcionando."}


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
    cfg = store.load_config()
    ai = cfg.get("ai") or {}
    mus = sorted(f.name for f in pipeline.MUSICAS.glob("*") if f.is_file() and f.suffix.lower() in montagem.EXT_AUDIO) \
        if pipeline.MUSICAS.exists() else []
    ia_nome = ""
    if ai.get("provider") == "anthropic":
        ia_nome = "Claude"
    elif ai.get("provider") == "openai_compat":
        ia_nome = "Gemini" if "generativelanguage" in (ai.get("base_url") or "") else "GPT/compatível"
    pip = piper_disponivel()
    return {"vozes": [{"id": k, "nome": v[2], "ok": (v[0] != "edge" or edge) and (v[0] != "sapi" or os.name == "nt")
                       and (v[0] != "piper" or pip)} for k, v in VOZES.items()],
            "estilos_legenda": {"palavra_ativa": "Palavra em foco (animada)", "caixa_ativa": "Caixa na palavra",
                                "destaque": "Karaokê", "uma_palavra": "Uma palavra por vez", "impacto": "Impacto",
                                "neon": "Neon", "caixa": "Faixa de fundo", "classico": "Clássica",
                                "texto": "Texto simples (editável na Montagem)"},
            "marca": {"logo": (store.marca_dir() / "logo.png").exists(),
                      "handle": bool((cfg.get("brand") or {}).get("handle"))},
            "visuais": VISUAIS, "estilos": {"realista": "Foto realista", "biblico": "Época bíblica (realista)",
                                            "pintura": "Pintura a óleo", "desenho": "Desenho de livro infantil",
                                            "3d": "Animação 3D"},
            "bancos": any(bancos.status().values()), "pexels": bancos.status().get("pexels", False),
            "pixabay": bancos.status().get("pixabay", False), "gemini": bool(chave_gemini()), "graficos": pil,
            "ia": ai.get("provider") not in (None, "none") and bool(ai.get("api_key")), "ia_nome": ia_nome,
            "transcricao": transcribe.local_available(), "musicas": mus, "pc": os.name == "nt"}

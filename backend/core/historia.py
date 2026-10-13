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
    return [{"i0": a, "i1": b, "busca": palavras_chave(_txt(words, a, b)), "destaque": "", "grafico": None}
            for a, b in cenas]


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
- "grafico": só se a cena citar números comparáveis (porcentagens, quantidades, anos), no formato
  {{"titulo": "...", "rotulos": ["...", "..."], "valores": [10, 20]}}. Senão, null.

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
        if md["kind"] == "video":
            kw["speed"] = md.get("_speed", 1.0)
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
        gfs.append(grafico_png(pid, k, c["grafico"], opts["formato"]) if c.get("grafico") else None)
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
            "velocidade": max(-50, min(50, int(o.get("velocidade") or 0)))}


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

def criar_de_texto(pid: str, texto: str, opts: dict, progress: Progresso = None) -> dict:
    def p(x, msg):
        if progress:
            progress(x, msg)
    opts = _opts(opts)
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
    return {"vozes": [{"id": k, "nome": v[2], "ok": (v[0] != "edge" or edge) and (v[0] != "sapi" or os.name == "nt")}
                      for k, v in VOZES.items()],
            "visuais": VISUAIS, "estilos": {"realista": "Foto realista", "biblico": "Época bíblica (realista)",
                                            "pintura": "Pintura a óleo", "desenho": "Desenho de livro infantil",
                                            "3d": "Animação 3D"},
            "bancos": any(bancos.status().values()), "pexels": bancos.status().get("pexels", False),
            "pixabay": bancos.status().get("pixabay", False), "gemini": bool(chave_gemini()), "graficos": pil,
            "ia": ai.get("provider") not in (None, "none") and bool(ai.get("api_key")), "ia_nome": ia_nome,
            "transcricao": transcribe.local_available(), "musicas": mus, "pc": os.name == "nt"}

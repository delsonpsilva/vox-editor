"""Resumo do Culto (v1.14): vários vídeos e fotos do culto viram um "resumão" pronto, com música, na Montagem.

Como funciona (tudo no próprio aparelho; a IA paga é opcional e só melhora as escolhas):
1. Cada arquivo ganha a HORA em que foi gravado (dados do celular/câmera; se não houver, a data do arquivo), para o
   resumo seguir a ordem do culto.
2. O SOM de cada vídeo é medido segundo a segundo: música/canto (som contínuo), fala (com as pausas entre as palavras)
   ou silêncio. Os trechos de fala mais fortes são transcritos (Whisper, o mesmo da edição automática) e viram
   ORAÇÃO ou PREGAÇÃO pelas palavras usadas — ou pela IA, se ligada.
3. A IMAGEM é conferida nos quadros-chave: escura, tremida ou fora de foco perde pontos. Nas fotos, as repetidas
   (rajadas) saem e as com rostos ganham pontos.
4. A Montagem é escrita com: abertura (título e data), os melhores pedaços de cada vídeo e as melhores fotos na ordem
   do culto, os MOMENTOS com som original (uma frase forte da pregação com legenda, um trecho do louvor), o nome de
   cada parte (Louvor, Oração, Palavra), música de fundo que abaixa sozinha nos momentos, cortes no ritmo da música
   e o encerramento com a marca. Depois é só ajustar e exportar como qualquer montagem.
"""
from __future__ import annotations

import calendar
import json
import math
import re
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from . import montagem, montagem_som, pipeline, store
from ..engine import audio as aud
from ..engine import ffmpeg_tools as ff

Progresso = Optional[Callable[[float, str], None]]

CACHE_VERSAO = 3  # muda quando a análise muda (refaz o cache dos arquivos)

EVENTOS = {  # id -> (nome, título padrão, rótulos das partes)
    "culto": ("Culto", "Culto de Domingo", {"louvor": "Louvor", "oracao": "Oração", "pregacao": "Palavra"}),
    "conferencia": ("Conferência / congresso", "Conferência", {"louvor": "Louvor", "oracao": "Oração", "pregacao": "Palavra"}),
    "batismo": ("Batismo", "Culto de Batismo", {"louvor": "Louvor", "oracao": "Oração", "pregacao": "Palavra"}),
    "santa_ceia": ("Santa Ceia", "Culto de Santa Ceia", {"louvor": "Louvor", "oracao": "Oração", "pregacao": "Palavra"}),
    "jovens": ("Culto de jovens", "Culto de Jovens", {"louvor": "Louvor", "oracao": "Oração", "pregacao": "Palavra"}),
    "casamento": ("Casamento", "Nosso Casamento", {"louvor": "Música", "oracao": "Oração", "pregacao": "Mensagem"}),
    "aniversario": ("Aniversário", "Aniversário", {"louvor": "Música", "oracao": "Oração", "pregacao": "Mensagem"}),
    "evento": ("Outro evento", "Resumo do Evento", {"louvor": "Música", "oracao": "Oração", "pregacao": "Mensagem"}),
}
DURACOES = {"30": 30.0, "60": 60.0, "90": 90.0, "180": 180.0}
RITMOS = {  # duração alvo de cada pedaço (s), transição e câmera lenta
    "calmo": {"video": 3.4, "foto": 2.6, "tr": 0.55, "lenta": True},
    "animado": {"video": 2.2, "foto": 1.6, "tr": 0.3, "lenta": False},
}
CORES = {"natural": None, "vivo": "vivo", "cinema": "cinema", "quente": "quente", "dourado": "dourado", "suave": "suave"}
ENQUADRAMENTOS = ("auto", "preencher", "desfocado")
MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro")
MAX_LADO_FOTO = 3200  # fotos gigantes (50 MP) deixam a exportação lenta: ficam com no máximo este lado


# ---------------------------------------------------------------- hora em que foi gravado

def _iso_para_epoch(s: str) -> float | None:
    s = (s or "").strip()
    if not s or s.startswith("1970") or s.startswith("1904"):
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.timestamp()
    except ValueError:
        return None


def _hora_video(path: Path) -> float | None:
    """creation_time gravado pelo celular/câmera (em UTC)."""
    try:
        p = ff.run([ff.ffprobe(), "-v", "error", "-print_format", "json", "-show_entries",
                    "format_tags=creation_time,com.apple.quicktime.creationdate:stream_tags=creation_time", str(path)],
                   check=False)
        d = json.loads(p.stdout or "{}")
    except Exception:
        return None
    tags = (d.get("format") or {}).get("tags") or {}
    for k in ("com.apple.quicktime.creationdate", "creation_time"):
        t = _iso_para_epoch(tags.get(k, ""))
        if t:
            return t
    for st in d.get("streams") or []:
        t = _iso_para_epoch(((st.get("tags") or {}).get("creation_time")) or "")
        if t:
            return t
    return None


def _hora_exif(img, fuso_min: int | None) -> float | None:
    """DateTimeOriginal da foto. Vem na hora LOCAL: usa o fuso da própria foto ou o do aparelho de quem enviou."""
    try:
        ex = img.getexif()
        sub = ex.get_ifd(0x8769) if hasattr(ex, "get_ifd") else {}
        bruto = sub.get(36867) or sub.get(36868) or ex.get(306)
        if not bruto:
            return None
        d = datetime.strptime(str(bruto).strip()[:19], "%Y:%m:%d %H:%M:%S")
        base = calendar.timegm(d.timetuple())
        off = sub.get(36881) or sub.get(36880)
        if off and re.fullmatch(r"[+-]\d{2}:\d{2}", str(off).strip()):
            o = str(off).strip()
            mins = int(o[1:3]) * 60 + int(o[4:6])
            return base - (mins if o[0] == "+" else -mins) * 60
        if fuso_min is not None:  # getTimezoneOffset do navegador: 180 no Brasil (UTC-3)
            return base + fuso_min * 60
        return time.mktime(d.timetuple())  # sem fuso: a hora local deste aparelho
    except Exception:
        return None


def preparar_foto(path: Path, fuso_min: int | None) -> float | None:
    """Endireita a foto (orientação do celular), diminui as gigantes e devolve a hora em que foi tirada.
    Assim a prévia, a análise e a exportação veem a foto do mesmo jeito."""
    try:
        from PIL import Image, ImageOps
    except Exception:
        return None
    try:
        with Image.open(path) as img:
            quando = _hora_exif(img, fuso_min)
            ori = img.getexif().get(274, 1)
            grande = max(img.size) > MAX_LADO_FOTO
            if (ori and ori != 1) or grande:
                im = ImageOps.exif_transpose(img)
                if grande:
                    im.thumbnail((MAX_LADO_FOTO, MAX_LADO_FOTO))
                fmt = (img.format or "JPEG").upper()
                if fmt in ("JPEG", "MPO"):
                    im.convert("RGB").save(path, "JPEG", quality=92)
                elif fmt in ("PNG", "WEBP", "BMP"):
                    im.save(path, fmt)
            return quando
    except Exception:
        return None


def hora_da_midia(path: Path, kind: str, modificado_ms: float | None, fuso_min: int | None) -> float | None:
    t = None
    if kind == "video":
        t = _hora_video(path)
    elif kind == "image":
        t = preparar_foto(path, fuso_min)
    if not t and modificado_ms and modificado_ms > 946684800000:  # depois do ano 2000
        t = modificado_ms / 1000.0
    return round(t, 3) if t else None


# ---------------------------------------------------------------- análise do som

def _janelas_som(db: np.ndarray, voz: np.ndarray | None) -> dict:
    """Mede, segundo a segundo (janela de 3 s), o que tem no som: música/canto, fala, ruído ou silêncio."""
    fps = 100  # quadros de 10 ms
    n = len(db)
    segs = max(1, int(math.ceil(n / fps)))
    piso = float(np.percentile(db, 5))
    topo = float(np.percentile(db, 97))
    alto, pausa, mod, vozf = (np.zeros(segs, dtype=np.float32) for _ in range(4))
    freqs = np.fft.rfftfreq(300, 1 / fps)
    banda = (freqs >= 2.5) & (freqs <= 8.0)
    tudo = (freqs >= 0.5) & (freqs <= 20.0)
    for i in range(segs):
        a, b = max(0, i * fps - fps), min(n, i * fps + 2 * fps)
        w = db[a:b]
        if w.size < 30:
            alto[i] = piso
            continue
        p90 = float(np.percentile(w, 90))
        alto[i] = p90
        pausa[i] = float(np.mean(w < p90 - 15))
        env = np.power(10.0, w / 20.0)
        env = env - env.mean()
        if env.size < 300:
            env = np.pad(env, (0, 300 - env.size))
        pw = np.abs(np.fft.rfft(env[:300])) ** 2
        mod[i] = float(pw[banda].sum() / (pw[tudo].sum() + 1e-12))
        if voz is not None and voz.size == n:
            vozf[i] = float(voz[a:b].mean())
    tipo = []
    for i in range(segs):
        if alto[i] < -50 or (alto[i] < piso + 10 and alto[i] < -36) or alto[i] < topo - 38:
            tipo.append("s")  # silêncio (um vídeo só de música tem o "piso" alto: por isso o limite fixo)
        elif pausa[i] < 0.09 and mod[i] < 0.5:
            tipo.append("m")  # música/canto: som contínuo, sem as pausas da fala
        elif pausa[i] >= 0.12 or vozf[i] > 0.35:
            tipo.append("f")  # fala
        else:
            tipo.append("m" if mod[i] < 0.42 else "f")
    # suaviza: cada segundo vira o que mais aparece nos 5 s em volta
    suave = []
    for i in range(segs):
        viz = tipo[max(0, i - 2):i + 3]
        suave.append(max("mfs", key=viz.count))
    return {"tipo": "".join(suave), "alto": [round(float(x), 1) for x in alto], "piso": round(piso, 1),
            "topo": round(topo, 1), "pausa": [round(float(x), 2) for x in pausa]}


def _trechos(tipo: str, minimo: int = 3) -> list[dict]:
    """Junta os segundos iguais em trechos; trechos curtos demais viram o vizinho."""
    runs = []
    for i, c in enumerate(tipo):
        if runs and runs[-1]["tipo"] == c:
            runs[-1]["e"] = i + 1
        else:
            runs.append({"tipo": c, "s": i, "e": i + 1})
    mudou = True
    while mudou and len(runs) > 1:
        mudou = False
        for k, r in enumerate(runs):
            if r["e"] - r["s"] < minimo:
                viz = runs[k - 1] if k > 0 else runs[k + 1]
                if k > 0 and k + 1 < len(runs) and runs[k + 1]["e"] - runs[k + 1]["s"] > viz["e"] - viz["s"]:
                    viz = runs[k + 1]
                viz["s"], viz["e"] = min(viz["s"], r["s"]), max(viz["e"], r["e"])
                runs.pop(k)
                mudou = True
                break
        # junta vizinhos iguais
        k = 0
        while k + 1 < len(runs):
            if runs[k]["tipo"] == runs[k + 1]["tipo"]:
                runs[k]["e"] = runs[k + 1]["e"]
                runs.pop(k + 1)
                mudou = True
            else:
                k += 1
    return runs


def analisar_som(src: Path, pasta: Path) -> dict | None:
    wav = pasta / f"res_{uuid.uuid4().hex[:8]}.wav"
    try:
        aud.extract_analysis_audio(str(src), str(wav))
        samples = aud.read_wav_mono(str(wav))
    except Exception:
        return None
    finally:
        wav.unlink(missing_ok=True)
    if samples.size < aud.SR:
        return None
    feat = aud.compute_features(samples)
    db = feat["db"]
    voz = None
    try:
        voz = aud.speech_mask(samples, len(db))
        if not voz.any():
            voz = None
    except Exception:
        voz = None
    r = _janelas_som(db, voz)
    r["trechos"] = _trechos(r["tipo"])
    return r


# ---------------------------------------------------------------- análise da imagem

def _metricas(img: np.ndarray) -> tuple[float, float]:
    try:
        import cv2
        nit = float(cv2.Laplacian(img, cv2.CV_64F).var())
    except Exception:
        f = img.astype(np.float32)
        lap = -4 * f[1:-1, 1:-1] + f[:-2, 1:-1] + f[2:, 1:-1] + f[1:-1, :-2] + f[1:-1, 2:]
        nit = float(lap.var())
    return float(img.mean()), nit


def nota_quadro(brilho: float, nitidez: float, movimento: float | None) -> float:
    """0 a 1: boa luz, foco e câmera firme."""
    if brilho < 30:
        luz = 0.1
    elif brilho < 55:
        luz = 0.55
    elif brilho > 235:
        luz = 0.35
    else:
        luz = 1.0
    foco = min(1.0, math.log1p(max(0.0, nitidez)) / math.log1p(500))
    if movimento is None:
        firme = 0.7
    elif movimento < 2:
        firme = 0.75  # parado demais (tela fixa, mão no bolso)
    elif movimento <= 20:
        firme = 1.0
    elif movimento <= 35:
        firme = 0.6
    else:
        firme = 0.2  # tremendo ou virando rápido
    return round(0.45 * luz + 0.35 * foco + 0.2 * firme, 3)


def analisar_imagem_video(src: Path) -> list[dict]:
    """Quadros-chave (rápido, sem decodificar o vídeo todo) em 160x120 cinza: luz, foco e movimento."""
    W, H = 160, 120
    sync = ["-fps_mode", "passthrough"] if ff.ffmpeg_version() >= (5, 1) else ["-vsync", "0"]
    try:
        p = subprocess.run([ff.ffmpeg(), "-hide_banner", "-loglevel", "info", "-skip_frame", "nokey", "-i", str(src),
                            "-an", "-vf", f"scale={W}:{H},showinfo,format=gray", *sync, "-f", "rawvideo", "-"],
                           capture_output=True, creationflags=ff.CREATE_FLAGS, timeout=1800)
    except Exception:
        return []
    tempos = [float(x) for x in re.findall(rb"pts_time:\s*(-?[\d.]+)", p.stderr)]
    tam = W * H
    n = min(len(tempos), len(p.stdout) // tam)
    out, ant, t_ant = [], None, None
    for k in range(n):
        img = np.frombuffer(p.stdout[k * tam:(k + 1) * tam], dtype=np.uint8).reshape(H, W)
        b, s = _metricas(img)
        mv = None
        if ant is not None and t_ant is not None and 0 < tempos[k] - t_ant <= 4.0:
            mv = float(np.mean(np.abs(img.astype(np.int16) - ant.astype(np.int16)))) / max(0.5, tempos[k] - t_ant)
        out.append({"t": round(tempos[k], 2), "q": nota_quadro(b, s, mv), "b": round(b, 1)})
        ant, t_ant = img, tempos[k]
    return out


def _dhash(img) -> int:
    from PIL import Image
    p = np.asarray(img.convert("L").resize((9, 8), Image.BILINEAR), dtype=np.int16)
    bits = (p[:, 1:] > p[:, :-1]).flatten()
    return int("".join("1" if x else "0" for x in bits), 2)


def analisar_foto(src: Path) -> dict | None:
    try:
        from PIL import Image, ImageOps
        with Image.open(src) as im0:
            im = ImageOps.exif_transpose(im0).convert("L")
            im.thumbnail((256, 256))
            g = np.asarray(im, dtype=np.uint8)
            h = _dhash(im)
    except Exception:
        return None
    b, s = _metricas(g)
    rostos = 0
    try:
        from ..engine import reframe
        if reframe.available():
            casc = reframe._cascades()[0]
            rostos = len(casc.detectMultiScale(g, scaleFactor=1.15, minNeighbors=6, minSize=(18, 18)))
    except Exception:
        rostos = 0
    q = nota_quadro(b, s, 8.0)
    q = round(min(1.0, q + (0.08 if rostos else 0) + (0.04 if rostos >= 3 else 0)), 3)
    return {"q": q, "hash": h, "rostos": int(rostos), "b": round(b, 1)}


def _parecidas(h1: int, h2: int) -> bool:
    return bin(h1 ^ h2).count("1") <= 10


# ---------------------------------------------------------------- cache por arquivo

def _cache(pid: str, mid: str) -> Path:
    d = store.pdir(pid) / "cache" / "resumo"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{mid}.json"


def analisar_midia(pid: str, md: dict) -> dict:
    """Análise de um arquivo (fica guardada: refazer o resumo com outras opções é rápido)."""
    arq = _cache(pid, md["id"])
    if arq.exists():
        try:
            c = json.loads(arq.read_text(encoding="utf-8"))
            if c.get("v") == CACHE_VERSAO:
                return c
        except Exception:
            pass
    src = store.pdir(pid) / md["file"]
    r: dict = {"v": CACHE_VERSAO, "kind": md["kind"]}
    if md["kind"] == "image":
        r["foto"] = analisar_foto(src)
    elif md["kind"] == "video":
        r["quadros"] = analisar_imagem_video(src)
        r["som"] = analisar_som(src, arq.parent) if md.get("has_audio") else None
    store._write_json(arq, r)
    return r


# ---------------------------------------------------------------- falas: oração, pregação e frases fortes

def _sem_acento(t: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")


_ORACAO = ("senhor", "pai", "amem", "oramos", "oracao", "abencoa", "abencoe", "gloria", "te louvamos", "te agradecemos",
           "obrigado", "clamamos", "derrama", "em nome de jesus", "sangue de jesus", "receba", "toca", "cura", "liberta",
           "te pedimos", "pedimos", "aleluia", "espirito santo", "tua presenca", "tua gloria", "teu nome", "te adoramos")
_PREGACAO = ("biblia", "versiculo", "capitulo", "irmaos", "igreja", "voces", "voce", "livro", "apostolo", "paulo",
             "mensagem", "palavra de deus", "leia", "lemos", "esta escrito", "diz a palavra", "texto", "porque",
             "quando", "quero", "hoje", "povo", "historia")


def _conta(texto: str, termos: tuple) -> int:
    t = " " + re.sub(r"[^a-z0-9 ]+", " ", _sem_acento(texto)) + " "
    return sum(t.count(" " + k + " ") for k in termos)


def categoria_da_fala(texto: str, dur: float) -> str:
    """Oração ou pregação pelas palavras usadas. Sem texto: fala longa é pregação."""
    if len(texto.split()) < 6:
        return "pregacao" if dur >= 60 else "fala"
    o, p = _conta(texto, _ORACAO), _conta(texto, _PREGACAO)
    n = max(1, len(texto.split()))
    if o >= 3 and o / n > 0.03 and o >= p * 1.1:
        return "oracao"
    if p >= 2 or dur >= 45:
        return "pregacao"
    return "oracao" if o >= 2 else "fala"


def parece_fala(ws: list[dict]) -> bool:
    """Trecho transcrito com cara de fala: muitas palavras por segundo e pouca repetição (canto repete o refrão)."""
    if len(ws) < 12:
        return False
    dur = max(1.0, ws[-1]["e"] - ws[0]["s"])
    unicas = len({_sem_acento(re.sub(r"[^\w]", "", w["w"])) for w in ws}) / len(ws)
    return len(ws) / dur >= 2.2 and unicas >= 0.62


def frases_de(words: list[dict], lo: float = 3.5, hi: float = 12.0) -> list[dict]:
    """Frases completas (do ponto ao ponto, ou entre pausas) que cabem num momento com som original."""
    from ..engine import smartcuts
    out, cur = [], []

    def fecha():
        if not cur:
            return
        s, e = cur[0]["s"], cur[-1]["e"]
        txt = " ".join(w["w"] for w in cur).strip()
        if lo <= e - s <= hi and len(txt.split()) >= 6:
            out.append({"s": round(s, 3), "e": round(e, 3), "texto": txt, "words": list(cur),
                        "nota": round(smartcuts._score(txt, e - s), 2)})
    for k, w in enumerate(words):
        if cur and (w["s"] - cur[-1]["e"] > 0.75 or w["e"] - cur[0]["s"] > hi):
            fecha()
            cur = []
        cur.append(w)
        if re.search(r"[.!?…]$", w["w"]):
            fecha()
            cur = []
    fecha()
    return out


# ---------------------------------------------------------------- IA (opcional): tipos e melhores frases

PROMPT_IA = """Você é editor de vídeos de igreja. Vou te passar o que foi gravado num {evento}, em ordem, com o tipo
que o som indica e a transcrição das falas. Faça um RESUMO de uns {dur} segundos.

Responda SÓ com JSON, assim:
{{"titulo": "<título curto e bonito para o resumo, até 40 letras, em português>",
  "tipos": {{"<id do trecho>": "louvor|oracao|pregacao|testemunho|avisos|outro"}},
  "frases": ["<ids das frases mais fortes e completas para ouvir com o som original, até {nf}>"],
  "louvor": ["<ids dos trechos de música mais bonitos para ouvir, até {nl}>"]}}

Regras: escolha frases que façam sentido sozinhas (sem "como eu disse", sem nomes de pessoas soltos), com fé,
esperança ou uma verdade bíblica. Não escolha avisos, ofertas nem frases cortadas. Música/canto é "louvor".
Uma fala com "Senhor", "Pai", "em nome de Jesus" e "amém" é "oracao".

TRECHOS:
{trechos}

FRASES (candidatas):
{frases}"""


def _ia(trechos: list[dict], frases: list[dict], opts: dict, nf: int, nl: int) -> dict | None:
    from ..engine import smartcuts
    ai = store.load_config().get("ai") or {}
    if not opts.get("usar_ia") or ai.get("provider") not in ("anthropic", "openai_compat") or not ai.get("api_key"):
        return None
    lt = []
    for t in trechos[:160]:
        tx = (t.get("texto") or "")[:400]
        lt.append(f"[{t['id']}] arquivo {t['arq']} {t['s']:.0f}-{t['e']:.0f}s ({t['e'] - t['s']:.0f}s) som: "
                  f"{'música/canto' if t['tipo'] == 'm' else 'fala'}" + (f' — "{tx}"' if tx else ""))
    lf = [f"[{f['id']}] ({f['e'] - f['s']:.0f}s) {f['texto'][:300]}" for f in frases[:120]]
    nome_ev = EVENTOS.get(opts.get("evento"), EVENTOS["culto"])[0].lower()
    prompt = PROMPT_IA.format(evento=nome_ev, dur=int(opts["duracao"]), nf=nf, nl=nl,
                              trechos="\n".join(lt) or "(nenhum)", frases="\n".join(lf) or "(nenhuma)")
    raw = smartcuts._call_llm(prompt, ai)
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict):
        return None
    tipos = {str(k): str(v) for k, v in (d.get("tipos") or {}).items()
             if str(v) in ("louvor", "oracao", "pregacao", "testemunho", "avisos", "outro")}
    return {"titulo": re.sub(r"\s+", " ", str(d.get("titulo") or "")).strip()[:48], "tipos": tipos,
            "frases": [str(x) for x in d.get("frases") or []][:nf], "louvor": [str(x) for x in d.get("louvor") or []][:nl]}


# ---------------------------------------------------------------- ritmo da música (batidas)

def batidas(arquivo: Path, pasta: Path) -> tuple[float, float] | None:
    """Tempo da batida (s) e onde cai a primeira, para os cortes caírem no ritmo. None se não der para saber."""
    wav = pasta / f"bat_{uuid.uuid4().hex[:8]}.wav"
    try:
        ff.run([ff.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-t", "150", "-i", str(arquivo), "-vn",
                "-ac", "1", "-ar", str(aud.SR), "-c:a", "pcm_s16le", str(wav)])
        s = aud.read_wav_mono(str(wav))
    except Exception:
        return None
    finally:
        wav.unlink(missing_ok=True)
    if s.size < aud.SR * 8:
        return None
    db = aud.compute_features(s)["db"]
    on = np.maximum(0.0, np.diff(db))
    on = np.convolve(on, np.ones(3) / 3, mode="same")
    on = on - on.mean()
    if not np.any(on):
        return None
    ac = np.correlate(on, on, mode="full")[len(on) - 1:]
    lo, hi = 40, 86  # 70 a 150 batidas por minuto (quadros de 10 ms)
    faixa = ac[lo:hi + 1]
    lag = int(np.argmax(faixa)) + lo
    if faixa.mean() <= 0 or ac[lag] / (np.abs(faixa).mean() + 1e-9) < 1.25:
        return None
    soma = [float(on[f::lag].sum()) for f in range(lag)]
    fase = int(np.argmax(soma))
    return lag / 100.0, fase / 100.0


# ---------------------------------------------------------------- escolher os pedaços

def _nota_janela(quadros: list[dict], a: float, b: float) -> float:
    if not quadros:
        return 0.6
    qs = [x["q"] for x in quadros if a - 0.5 <= x["t"] <= b + 0.5]
    if not qs:
        x = min(quadros, key=lambda x: abs(x["t"] - (a + b) / 2))
        return x["q"] * 0.9
    return float(np.mean(qs)) * 0.7 + float(min(qs)) * 0.3


def _som_janela(som: dict | None, a: float, b: float) -> tuple[float, str]:
    """Força do som (0..1) e o tipo que mais aparece na janela."""
    if not som:
        return 0.3, "s"
    i0, i1 = int(a), max(int(a) + 1, int(math.ceil(b)))
    tp = som["tipo"][i0:i1] or "s"
    al = som["alto"][i0:i1] or [som["piso"]]
    forca = (float(np.mean(al)) - som["piso"]) / max(6.0, som["topo"] - som["piso"])
    return max(0.0, min(1.0, forca)), max("mfs", key=tp.count)


def _cat_em(fonte: dict, t: float) -> str | None:
    for r in fonte.get("runs") or []:
        if r["s"] <= t < r["e"]:
            return r.get("cat")
    return None


def _contagem_momentos(T: float) -> int:
    return 1 if T <= 35 else 2 if T <= 65 else 3 if T <= 95 else 5


def planejar(fontes: list[dict], opts: dict, batida: tuple[float, float] | None = None,
             ia: dict | None = None) -> list[dict]:
    """Escolhe os pedaços (vídeos, fotos e momentos com som original) e o tempo de cada um."""
    T = float(opts["duracao"])
    rit = RITMOS[opts["ritmo"]]
    enc = 3.0 if opts.get("_tem_encerramento") else 0.0
    corpo = max(8.0, T - enc)
    Lv, Lf = rit["video"], rit["foto"]
    if batida:  # pedaços com um número inteiro de batidas
        per = batida[0]
        Lv = max(per * 2, round(Lv / per) * per)
        Lf = max(per * 2, round(Lf / per) * per)
    videos = [f for f in fontes if f["kind"] == "video" and f["dur"] >= 0.8]
    fotos = [f for f in fontes if f["kind"] == "image" and f.get("foto")]

    # 1) momentos com som original
    momentos: list[dict] = []
    if opts.get("som_original", True):
        k = _contagem_momentos(T)
        hi_frase = 9.0 if T <= 35 else 12.0
        cand_f = []
        for f in videos:
            for fr in f.get("frases") or []:
                if fr["e"] - fr["s"] > hi_frase:
                    continue
                vis = _nota_janela(f["quadros"], fr["s"], fr["e"])
                forca, _ = _som_janela(f.get("som"), fr["s"], fr["e"])
                nota = fr["nota"] + 2.0 * vis + 1.5 * forca + (1.0 if fr.get("cat") == "pregacao" else 0.0)
                if ia and fr.get("id") in ia.get("frases", []):
                    nota += 10 - ia["frases"].index(fr["id"])
                cand_f.append((nota, f, fr))
        cand_l = []
        for f in videos:
            for r in f.get("runs") or []:
                if r["tipo"] != "m" or r["e"] - r["s"] < 6:
                    continue
                d = 7.0 if opts["ritmo"] == "calmo" else 6.0
                melhor = None
                a = r["s"] + 1.0
                while a + d <= min(r["e"], f["dur"] - 0.2):
                    forca, _ = _som_janela(f.get("som"), a, a + d)
                    nota = 2.0 * _nota_janela(f["quadros"], a, a + d) + 1.5 * forca
                    if melhor is None or nota > melhor[0]:
                        melhor = (nota, a)
                    a += 1.0
                if melhor:
                    nota = melhor[0] + (10 if ia and r.get("id") in ia.get("louvor", []) else 0)
                    cand_l.append((nota, f, {"s": melhor[1], "e": melhor[1] + d}))
        cand_f.sort(key=lambda x: -x[0])
        cand_l.sort(key=lambda x: -x[0])
        nf = min(len(cand_f), max(1 if cand_f else 0, (k + 1) // 2 + (0 if cand_l else k)))
        nl = min(len(cand_l), k - nf)
        nf = min(len(cand_f), k - nl)
        usados: list[tuple[str, float, float]] = []

        def livre(f, s, e):
            return all(not (u[0] == f["mid"] and s < u[2] + 4 and e > u[1] - 4) for u in usados)
        for lista, n, tipo in ((cand_f, nf, "frase"), (cand_l, nl, "louvor")):
            pegos = 0
            for nota, f, j in lista:
                if pegos >= n:
                    break
                if not livre(f, j["s"], j["e"]):
                    continue
                s = max(0.0, j["s"] - (0.25 if tipo == "frase" else 0.0))
                e = min(f["dur"] - 0.05, j["e"] + (0.35 if tipo == "frase" else 0.0))
                if sum(x["dur"] for x in momentos) + (e - s) > corpo * 0.45:
                    continue
                usados.append((f["mid"], s, e))
                cat = j.get("cat") or ("louvor" if tipo == "louvor" else _cat_em(f, (s + e) / 2)) or "pregacao"
                momentos.append({"kind": "video", "mid": f["mid"], "in": s, "dur": round(e - s, 3), "speed": 1.0,
                                 "t": f["t0"] + s, "cat": cat, "som": True, "momento": tipo,
                                 "words": j.get("words") or [], "texto": j.get("texto", ""), "fonte": f})
                pegos += 1

    # 2) pedaços sem som original (b-roll) e fotos
    resto = corpo - sum(x["dur"] for x in momentos)
    ocupado = [(x["mid"], x["in"], x["in"] + x["dur"]) for x in momentos]
    cand_v: dict[str, list] = {}
    for f in videos:
        lst = []
        lento = rit["lenta"] and f.get("fps", 30) >= 48
        if f["dur"] < Lv + 0.8:
            a, d = 0.15, max(0.6, f["dur"] - 0.3)
            vis = _nota_janela(f["quadros"], a, a + d)
            lst.append({"in": a, "span": d, "nota": vis, "lento": False})
        else:
            a = 0.4
            while a + Lv <= f["dur"] - 0.3:
                span = Lv * (0.5 if lento else 1.0)
                b = a + span
                if not any(o[0] == f["mid"] and a < o[2] + 1 and b > o[1] - 1 for o in ocupado):
                    vis = _nota_janela(f["quadros"], a, b)
                    forca, tp = _som_janela(f.get("som"), a, b)
                    nota = 0.65 * vis + 0.25 * forca + (0.1 if tp == "m" else 0.0)
                    lst.append({"in": a, "span": span, "nota": nota, "lento": lento and tp != "f"})
                a += 1.0
        if lst:
            cand_v[f["mid"]] = lst
    # fotos: tira as repetidas (rajada) e as ruins
    boas = []
    for f in sorted(fotos, key=lambda x: -x["foto"]["q"]):
        if f["foto"]["q"] < 0.35:
            continue
        if any(_parecidas(f["foto"]["hash"], g["foto"]["hash"]) and abs(f["t0"] - g["t0"]) < 600 for g in boas):
            continue
        boas.append(f)
    nv_max = sum(min(len(v), max(1, int(f["dur"] // (Lv * 2)) + 1)) for f in videos
                 for v in [cand_v.get(f["mid"], [])])
    P = len(boas)
    if not cand_v:
        share = 1.0
    elif not P:
        share = 0.0
    else:
        share = min(0.5, P / (P + 2.0 * len(cand_v)))
    S = resto / (share * Lf + (1 - share) * Lv)
    x = min(P, int(round(share * S)))
    y = int(max(0, resto - x * Lf) // Lv) if cand_v else 0
    if y > nv_max:  # pouco vídeo: as fotos ganham o tempo que sobra
        y = nv_max
        x = min(P, int(max(0, resto - y * Lv) // Lf))
    # distribui os pedaços entre os vídeos (todos aparecem, os maiores e melhores aparecem mais)
    pesos = {f["mid"]: math.sqrt(max(1.0, f["dur"])) * (0.5 + np.mean([c["nota"] for c in cand_v[f["mid"]]]))
             for f in videos if f["mid"] in cand_v}
    cota = {m: 0 for m in pesos}
    ordem = sorted(pesos, key=lambda m: -pesos[m])
    for m in ordem[:y]:
        cota[m] = 1
    sobra = y - sum(cota.values())
    while sobra > 0:
        m = max(ordem, key=lambda m: pesos[m] / (cota[m] + 1) if cota[m] < len(cand_v[m]) else -1)
        if cota[m] >= len(cand_v[m]):
            break
        cota[m] += 1
        sobra -= 1
    pecas = list(momentos)
    for f in videos:
        n = cota.get(f["mid"], 0)
        if not n:
            continue
        sep = max(Lv * 1.5, f["dur"] / (n + 1) * 0.6)
        pegos: list[dict] = []
        for c in sorted(cand_v[f["mid"]], key=lambda c: -c["nota"]):
            if len(pegos) >= n:
                break
            if any(abs(c["in"] - p["in"]) < sep for p in pegos):
                continue
            pegos.append(c)
        for c in pegos:
            speed = 0.5 if c["lento"] else 1.0
            dur = c["span"] / speed if f["dur"] >= Lv + 0.8 else c["span"]
            pecas.append({"kind": "video", "mid": f["mid"], "in": c["in"], "dur": round(min(dur, Lv), 3)
                          if f["dur"] >= Lv + 0.8 else round(dur, 3), "speed": speed, "t": f["t0"] + c["in"],
                          "cat": _cat_em(f, c["in"] + 0.5), "som": False, "fonte": f})
    for f in sorted(boas, key=lambda x: -x["foto"]["q"])[:x]:
        pecas.append({"kind": "image", "mid": f["mid"], "in": 0.0, "dur": Lf, "speed": 1.0, "t": f["t0"],
                      "cat": None, "som": False, "fonte": f})
    if not pecas:
        return []

    # 3) ordem do culto
    if opts.get("ordem") == "envio":
        pecas.sort(key=lambda p: (p["fonte"]["ordem"], p["in"]))
    else:
        pecas.sort(key=lambda p: (p["t"], p["in"]))
    # foto sem parte definida herda a do vídeo mais perto no tempo
    for k, p in enumerate(pecas):
        if p["cat"] is None and p["kind"] == "image":
            viz = [q for q in pecas if q["kind"] == "video" and q.get("cat")]
            if viz:
                q = min(viz, key=lambda q: abs(q["t"] - p["t"]))
                if abs(q["t"] - p["t"]) < 900:
                    p["cat"] = q["cat"]
    # não começa falando (o título entra por cima) e dois momentos não ficam colados
    if pecas[0].get("som"):
        k = next((k for k, p in enumerate(pecas) if not p.get("som")), None)
        if k:
            pecas.insert(0, pecas.pop(k))
    k = 1
    while k < len(pecas):
        if pecas[k].get("som") and pecas[k - 1].get("som"):
            j = next((j for j in range(k + 1, len(pecas)) if not pecas[j].get("som")), None)
            if j is not None:
                pecas.insert(k, pecas.pop(j))
        k += 1
    # cabe no tempo pedido: corta os pedaços sem som de menor nota até caber
    while sum(p["dur"] for p in pecas) > corpo + 0.5 and any(not p.get("som") for p in pecas[1:]):
        cand = [p for p in pecas[1:] if not p.get("som")]
        pior = min(cand, key=lambda p: _nota_peca(p))
        pecas.remove(pior)

    # 4) tempo de cada um (no ritmo da música, quando dá)
    t = 0.0
    for k, p in enumerate(pecas):
        d = p["dur"]
        if batida and k < len(pecas):
            per, fase = batida
            fim = t + d
            n = round((fim - fase) / per)
            alvo = fase + n * per
            if p.get("som"):  # momento: nunca corta a fala, só estende até a próxima batida
                if alvo < fim - 0.02:
                    alvo += per
            if alvo - t >= max(0.8, d * 0.6):
                d = alvo - t
        d = round(d, 3)
        if p["kind"] == "video":
            f = p["fonte"]
            span = d * p["speed"]
            if p["in"] + span > f["dur"] - 0.05:
                p["in"] = max(0.0, f["dur"] - 0.05 - span)
                if p["in"] + span > f["dur"] - 0.05:
                    span = f["dur"] - 0.05 - p["in"]
                    d = round(span / p["speed"], 3)
        p["start"], p["dur"] = round(t, 3), d
        t += d
    return pecas


def _nota_peca(p: dict) -> float:
    f = p["fonte"]
    if p["kind"] == "image":
        return f["foto"]["q"]
    return _nota_janela(f.get("quadros") or [], p["in"], p["in"] + p["dur"] * p["speed"])


# ---------------------------------------------------------------- escrever a Montagem

MOVIMENTOS = [(1.0, 1.12, 0.5, 0.5, 0.5, 0.5), (1.12, 1.0, 0.5, 0.5, 0.5, 0.5), (1.1, 1.1, 0.53, 0.47, 0.5, 0.5),
              (1.04, 1.14, 0.5, 0.5, 0.52, 0.48), (1.1, 1.1, 0.47, 0.53, 0.5, 0.5), (1.14, 1.04, 0.5, 0.5, 0.48, 0.52)]
TR_ANIMADO = ("zoom_in", "empurrar_e", "branco", "empurrar_d", "zoom_out")


def trilhas() -> list[dict]:
    base = {"hidden": False, "muted": False, "locked": False}
    return [{"id": "t_legenda", "kind": "text", "name": "Legenda", **base},
            {"id": "t_titulo", "kind": "text", "name": "Títulos", **base},
            {"id": "t_logo", "kind": "video", "name": "Marca", **base},
            {"id": "t_v1", "kind": "video", "name": "Vídeos e fotos", "main": True, **base},
            {"id": "t_musica", "kind": "audio", "name": "Música", **base}]


def _item(kind: str, track: str, src: str | None, start: float, dur: float, src_in: float = 0.0, **kw) -> dict:
    return montagem._item_base(kind, track, src, start, dur, src_in, **kw)


def _data_por_extenso(t: float | None, data_txt: str = "") -> str:
    if data_txt and re.fullmatch(r"\d{4}-\d{2}-\d{2}", data_txt):
        y, m, d = (int(x) for x in data_txt.split("-"))
    else:
        lt = time.localtime(t or time.time())
        y, m, d = lt.tm_year, lt.tm_mon, lt.tm_mday
    if not 1 <= m <= 12:
        return ""
    return f"{d} de {MESES[m - 1]} de {y}"


def _quebra(texto: str, max_c: int) -> str:
    linhas, cur = [], ""
    for p in texto.split():
        if cur and len(cur) + 1 + len(p) > max_c:
            linhas.append(cur)
            cur = p
        else:
            cur = (cur + " " + p).strip()
    if cur:
        linhas.append(cur)
    return "\n".join(linhas[:3])


def _enquadrar(p: dict, md: dict, W: int, H: int, modo: str) -> dict:
    """Preencher a tela (seguindo o rosto, nos vídeos) ou mostrar inteiro com o fundo desfocado atrás."""
    aw, ah = md.get("w") or W, md.get("h") or H
    r_m, r_t = aw / max(1, ah), W / max(1, H)
    diferente = (r_m > 1.15 * r_t) or (r_m < r_t / 1.15)
    if not diferente or modo == "preencher":
        usar = "cover"
    elif modo == "desfocado":
        usar = "desf"
    else:  # automático: foto deitada no vertical (ou em pé no horizontal) aparece inteira; vídeo segue o rosto
        usar = "desf" if (p["kind"] == "image" or r_m < r_t) else "cover"
    if usar == "desf":
        return {"fit": "contain", "fundoDesf": True}
    kw = {"fit": "cover"}
    if p["kind"] == "video" and r_m > r_t * 1.15:
        try:
            from ..engine import reframe
            if reframe.available():
                fx = reframe.face_x(str(store.pdir(p["fonte"]["pid"]) / md["file"]), p["in"] + p["dur"] * p["speed"] / 2,
                                    aw, ah)
                if fx is not None:
                    iw = aw * max(W / aw, H / ah)
                    x = 0.5 + (0.5 - fx) * iw / W
                    lim = iw / (2 * W)
                    kw["x"] = round(max(1 - lim, min(lim, x)), 4)
        except Exception:
            pass
    return kw


def escrever(pid: str, pecas: list[dict], opts: dict, musica: dict | None, titulo: str, data_txt: str,
             logo_md: dict | None) -> dict:
    formato = opts["formato"]
    W, H = montagem.FORMATOS[formato]
    vertical = H > W
    rit = RITMOS[opts["ritmo"]]
    m = montagem.carregar(pid)
    midias = {x["id"]: x for x in m["media"]}
    m.update(formato=formato, w=W, h=H, tracks=trilhas(), items=[], markers=[], legenda_viva=None)
    itens: list[dict] = []
    fx = CORES.get(opts.get("cor") or "natural")
    from . import efeitos as fxm
    filtro = dict(fxm.FILTROS.get(fx) or {}) if fx else None
    total = pecas[-1]["start"] + pecas[-1]["dur"] if pecas else 0.0
    sem_musica = not musica
    rotulos = EVENTOS.get(opts.get("evento"), EVENTOS["culto"])[2]
    palavras_tl: list[dict] = []
    marcadores = []
    ultima_parte, k_foto = None, 0
    for k, p in enumerate(pecas):
        md = midias.get(p["mid"])
        if not md:
            continue
        kw = _enquadrar(p, md, W, H, opts.get("enquadramento") or "auto")
        if filtro:
            kw["fx"] = filtro
        # transição de entrada
        if k > 0:
            if opts["ritmo"] == "calmo" or p.get("som") or pecas[k - 1].get("som"):
                kw["tr"] = {"tipo": "dissolver", "dur": rit["tr"] if not p.get("som") else 0.45}
            elif k % 5 == 0:
                kw["tr"] = {"tipo": TR_ANIMADO[(k // 5) % len(TR_ANIMADO)], "dur": rit["tr"]}
        if p["kind"] == "image":
            s0, s1, x0, x1, y0, y1 = MOVIMENTOS[k_foto % len(MOVIMENTOS)]
            k_foto += 1
            if kw.get("fundoDesf"):
                s0, s1, x0, x1, y0, y1 = (1.0, 1.05, 0.5, 0.5, 0.5, 0.5) if k_foto % 2 else (1.05, 1.0, 0.5, 0.5, 0.5, 0.5)
            kw["kf"] = [{"t": 0, "scale": s0, "x": x0, "y": y0, "e": "linear"},
                        {"t": round(p["dur"], 3), "scale": s1, "x": x1, "y": y1, "e": "linear"}]
            kw["volume"] = 0.0
            itens.append(_item("image", "t_v1", md["id"], p["start"], p["dur"], **kw))
        else:
            if p.get("som"):
                vol = 1.0
            else:
                vol = 0.0 if not sem_musica else 0.8
            itens.append(_item("video", "t_v1", md["id"], p["start"], p["dur"], p["in"], speed=p["speed"],
                               volume=vol if md.get("has_audio") else 0.0, **kw))
        if k == 0 and opts.get("fade_inicio", True):
            itens[-1]["fadeIn"] = 0.4
        # palavras da frase (legenda) no tempo da linha do tempo
        if p.get("momento") == "frase" and p.get("words"):
            for w in p["words"]:
                ts = p["start"] + (w["s"] - p["in"]) / p["speed"]
                te = p["start"] + (w["e"] - p["in"]) / p["speed"]
                if p["start"] <= ts < p["start"] + p["dur"]:
                    palavras_tl.append({"w": w["w"], "s": round(ts, 3), "e": round(min(te, p["start"] + p["dur"]), 3)})
        if p.get("som"):
            marcadores.append({"t": p["start"], "nome": "Frase" if p.get("momento") == "frase" else rotulos["louvor"],
                               "cor": "#FACC15"})
        # nome da parte (Louvor, Oração, Palavra) quando ela começa
        cat = p.get("cat")
        if opts.get("rotulos", True) and cat in rotulos and cat != ultima_parte:
            ini = p["start"] + 0.25
            if opts.get("abertura", True) and ini < 3.6:
                ini = 3.6
            fim_parte = p["start"] + p["dur"]
            j = k + 1
            while j < len(pecas) and pecas[j].get("cat") in (cat, None):
                fim_parte = pecas[j]["start"] + pecas[j]["dur"]
                j += 1
            dd = min(2.0, fim_parte - ini - 0.2)
            if dd >= 1.0:
                y = 0.1 if vertical else 0.11
                cor = (store.load_config().get("brand") or {}).get("color") or "#FF8A3D"
                itens.append(_item("text", "t_titulo", None, ini, dd, text=rotulos[cat], font="Anton",
                                   size=0.05 if vertical else 0.045, color="#FFFFFF", boxOn=True,
                                   box=cor if re.fullmatch(r"#[0-9a-fA-F]{6}", cor) else "#FF8A3D", boxAlpha=0.92,
                                   upper=True, x=0.5, y=y, fadeOut=0.25,
                                   kf=[{"t": 0, "scale": 0.6, "opacity": 0, "y": y - 0.015, "e": "entrada"},
                                       {"t": 0.3, "scale": 1.05, "opacity": 1, "y": y, "e": "saida"},
                                       {"t": 0.45, "scale": 1.0, "opacity": 1, "y": y, "e": "suave"}]))
            ultima_parte = cat
    # abertura: título e data por cima dos primeiros segundos
    if opts.get("abertura", True) and titulo and total > 2:
        d_tit = min(3.2, total - 0.4)
        y = 0.42 if vertical else 0.4
        itens.append(_item("text", "t_titulo", None, 0.25, d_tit, text=_quebra(titulo, 16 if vertical else 28),
                           font="Anton", size=0.1 if vertical else 0.09, color="#FFFFFF", boxOn=True, box="#000000",
                           boxAlpha=0.4, upper=True, y=y, fadeOut=0.35,
                           kf=[{"t": 0, "scale": 0.75, "opacity": 0, "y": y + 0.02, "e": "entrada"},
                               {"t": 0.4, "scale": 1.04, "opacity": 1, "y": y, "e": "saida"},
                               {"t": 0.6, "scale": 1.0, "opacity": 1, "y": y, "e": "suave"}]))
        if data_txt:
            y2 = y + (0.1 if vertical else 0.13) + (0.05 if "\n" in _quebra(titulo, 16 if vertical else 28) else 0)
            itens.append(_item("text", "t_legenda", None, 0.7, max(0.8, d_tit - 0.45), text=data_txt,
                               font="Poppins", size=0.042 if vertical else 0.038, color="#FFFFFF", stroke="#000000",
                               strokeW=0.1, y=y2, fadeIn=0.35, fadeOut=0.35))
    # encerramento com a marca
    fim = total
    marca = store.load_config().get("brand") or {}
    if opts.get("_tem_encerramento"):
        d_fim = 3.0
        cor = marca.get("bg") if re.fullmatch(r"#[0-9a-fA-F]{6}", marca.get("bg") or "") else "#101114"
        itens.append(_item("color", "t_v1", None, total, d_fim, color=cor, w=1.0, h=1.0,
                           tr={"tipo": "dissolver", "dur": 0.6}))
        if logo_md:
            itens.append(_item("image", "t_logo", logo_md["id"], total + 0.3, d_fim - 0.3, fit="contain",
                               scale=0.32 if vertical else 0.26, y=0.4, fadeIn=0.4,
                               kf=[{"t": 0, "scale": 0.24 if vertical else 0.2, "e": "entrada"},
                                   {"t": 0.6, "scale": 0.32 if vertical else 0.26, "e": "suave"}]))
        handle = (marca.get("handle") or "").strip()
        if handle and not handle.startswith("@"):
            handle = "@" + handle
        igreja = opts.get("evento") not in ("casamento", "aniversario", "evento")
        chamada = (("Siga e acompanhe os cultos" if vertical else "Inscreva-se e acompanhe os cultos") if igreja
                   else "Obrigado por fazer parte!")
        y_txt = 0.62 if logo_md else 0.5
        if handle:
            itens.append(_item("text", "t_titulo", None, total + 0.5, d_fim - 0.5, text=handle,
                               font="Poppins ExtraBold", size=0.075 if vertical else 0.06,
                               color=marca.get("color") or "#FF8A3D", y=y_txt, fadeIn=0.3))
        itens.append(_item("text", "t_legenda", None, total + 0.8, d_fim - 0.8, text=chamada, font="Poppins",
                           size=0.045 if vertical else 0.04, color="#FFFFFF",
                           y=y_txt + (0.07 if vertical else 0.09), fadeIn=0.3))
        fim = total + d_fim
    if opts.get("logo") and logo_md:
        itens.append(_item("image", "t_logo", logo_md["id"], 0.0, total, fit="contain",
                           scale=0.13 if vertical else 0.1, x=0.86 if vertical else 0.92,
                           y=0.06 if vertical else 0.09, opacity=0.85))
    # legenda animada das frases
    if opts.get("legenda", True) and palavras_tl:
        from . import historia
        lv = historia.legenda_viva(palavras_tl, opts.get("legenda_estilo") or "palavra_ativa", vertical)
        if lv:
            m["legenda_viva"] = lv
    # música: repete até o fim, abaixa sozinha nos momentos com som original
    if musica and musica.get("duration"):
        t = 0.0
        while t < fim - 0.2:
            d = min(musica["duration"], fim - t)
            itens.append(_item("audio", "t_musica", musica["id"], t, d, volume=0.85, duck=True,
                               fadeIn=0.6 if t == 0 else 0.0, fadeOut=2.5 if t + d >= fim - 0.3 else 0.0))
            t += d
    m["items"] = itens
    m["markers"] = marcadores[:60]
    return montagem.salvar(pid, m)


# ---------------------------------------------------------------- o passo a passo

ESTILOS_LEGENDA = {"palavra_ativa": "Palavra em foco (animada)", "caixa_ativa": "Caixa na palavra", "destaque": "Karaokê",
                   "uma_palavra": "Uma palavra por vez", "impacto": "Impacto", "neon": "Neon", "caixa": "Faixa de fundo",
                   "classico": "Clássica"}
MUSICA_AUTO, MUSICA_ENVIADA = "__auto__", "__enviada__"


def opcoes(o: dict) -> dict:
    o = o if isinstance(o, dict) else {}
    pick = lambda k, ok, pad: o.get(k) if o.get(k) in ok else pad  # noqa: E731
    return {"formato": pick("formato", montagem.FORMATOS, "9:16"),
            "duracao": DURACOES.get(str(o.get("duracao")), 60.0),
            "ritmo": pick("ritmo", RITMOS, "calmo"), "evento": pick("evento", EVENTOS, "culto"),
            "cor": pick("cor", CORES, "natural"), "enquadramento": pick("enquadramento", ENQUADRAMENTOS, "auto"),
            "musica": str(o.get("musica") if o.get("musica") is not None else MUSICA_AUTO)[:200],
            "som_original": o.get("som_original", True) is not False, "legenda": o.get("legenda", True) is not False,
            "legenda_estilo": pick("legenda_estilo", ESTILOS_LEGENDA, "palavra_ativa"),
            "rotulos": o.get("rotulos", True) is not False, "abertura": o.get("abertura", True) is not False,
            "encerramento": o.get("encerramento", True) is not False, "logo": bool(o.get("logo", False)),
            "usar_ia": o.get("usar_ia", True) is not False, "ordem": pick("ordem", ("hora", "envio"), "hora"),
            "titulo": re.sub(r"\s+", " ", str(o.get("titulo") or "")).strip()[:60],
            "data": str(o.get("data") or "")[:10] if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(o.get("data") or "")) else ""}


def _arquivos(m: dict) -> tuple[list[dict], list[dict]]:
    """Os vídeos e fotos enviados para o resumo e os áudios enviados (que podem virar a música)."""
    vis = [x for x in m["media"] if x["kind"] in ("video", "image") and not x.get("auto") and x["id"] != montagem.ORIGINAL]
    sons = [x for x in m["media"] if x["kind"] == "audio" and not x.get("auto") and not x.get("trilha")]
    return vis, sons


def _ordem_no_tempo(midias: list[dict]) -> dict[str, float]:
    """Hora de cada arquivo. Os sem hora ficam logo depois do arquivo enviado antes deles."""
    por_envio = sorted(midias, key=lambda x: x.get("added") or 0)
    tem = [x for x in por_envio if x.get("quando")]
    if not tem:
        return {x["id"]: float(x.get("added") or k) for k, x in enumerate(por_envio)}
    out, ult = {}, None
    primeiro = min(x["quando"] for x in tem)
    for k, x in enumerate(por_envio):
        if x.get("quando"):
            ult = float(x["quando"])
            out[x["id"]] = ult
        else:
            out[x["id"]] = (ult if ult is not None else primeiro - 1) + 0.001 * (k + 1)
    return out


def _musica(pid: str, escolha: str, opts: dict, enviadas: list[dict], avisos: list[str]) -> dict | None:
    m = montagem.carregar(pid)
    por_id = {x["id"]: x for x in m["media"]}
    if escolha == MUSICA_ENVIADA:
        if enviadas:
            return enviadas[-1]
        escolha = MUSICA_AUTO
    if not escolha:
        return None
    if escolha == MUSICA_AUTO:
        humores = ["louvor", "inspirador", "piano"] if opts["ritmo"] == "calmo" else ["inspirador", "epico", "alegre"]
        if opts["evento"] in ("casamento",):
            humores = ["piano", "emocionante", "acustico"]
        if opts["evento"] in ("aniversario",):
            humores = ["alegre", "acustico", "inspirador"]
        ant = (store.load(pid).get("resumo") or {}).get("musica_auto") or {}
        if ant.get("mid") in por_id and ant.get("humor") in humores[:1]:
            return por_id[ant["mid"]]
        from . import trilhas as tl
        erro = ""
        for humor in humores:
            try:
                res = tl.buscar("", humor)
            except Exception as e:
                erro = str(e)
                continue
            faixas = [f for f in res.get("faixas") or [] if (f.get("duration") or 0) >= min(60, opts["duracao"])]
            faixas.sort(key=lambda f: (f.get("license") != "cc0", -(f.get("duration") or 0)))
            for f in faixas[:5]:
                try:
                    arq, info = tl.baixar(f["id"], montagem.pasta_midias(pid))
                    md = montagem.adicionar_midia(
                        pid, arq, f"{info['title'] or 'Música'} — {info['creator'] or 'autor'}{arq.suffix}",
                        {"credito": info["credito"], "licenca": info["license"], "trilha": info["id"], "auto": "musica"})
                    store.update(pid, lambda p: p.setdefault("resumo", {}).update(
                        musica_auto={"mid": md["id"], "humor": humor, "credito": info["credito"]}))
                    return md
                except Exception as e:
                    erro = str(e)
                    continue
        avisos.append("Não consegui baixar a música automática agora" + (f" ({erro[:80]})" if erro else "") +
                      ". O resumo saiu com o som dos vídeos — escolha uma música na Montagem ou em Minhas músicas.")
        return None
    src = pipeline.musica_path(escolha)
    if not src:
        avisos.append("A música escolhida não foi encontrada. O resumo saiu com o som dos vídeos.")
        return None
    ja = next((x for x in m["media"] if x.get("auto") == "musica" and x.get("name") == Path(src).name), None)
    if ja:
        return ja
    dest = montagem.pasta_midias(pid) / f"musica_{uuid.uuid4().hex[:6]}_{Path(src).name}"
    shutil.copy(src, dest)
    try:
        return montagem.adicionar_midia(pid, dest, Path(src).name, {"auto": "musica"})
    except Exception:
        return None


def _logo(pid: str) -> dict | None:
    logo = store.BRAND_DIR / "logo.png"
    if not logo.exists():
        return None
    m = montagem.carregar(pid)
    ja = next((x for x in m["media"] if x.get("auto") == "logo"), None)
    if ja:
        return ja
    dest = montagem.pasta_midias(pid) / "resumo_logo.png"
    shutil.copy(logo, dest)
    try:
        return montagem.adicionar_midia(pid, dest, "Logo.png", {"auto": "logo"})
    except Exception:
        return None


def _transcrever_falas(pid: str, fontes: list[dict], T: float, p, avisos: list[str]) -> bool:
    """Transcreve só os trechos de fala mais fortes (cabe num orçamento de tempo): oração/pregação e as frases."""
    orc = min(420.0, max(90.0, 60.0 + 2.0 * T))
    cand = []
    for f in fontes:
        som = f.get("som")
        if f["kind"] != "video" or not som:
            continue
        med = float(np.median(som["alto"])) if som["alto"] else 0
        for r in f["runs"]:
            if r["tipo"] != "f" or r["e"] - r["s"] < 4:
                continue
            a = float(r["s"])
            while a < r["e"] - 2:
                b = min(float(r["e"]), a + 30.0)
                al = som["alto"][int(a):int(b)] or [med]
                prio = float(np.mean(al)) - med + (2.0 if r["e"] - r["s"] > 40 else 0.0)
                cand.append((prio, f, a, b))
                a = b
    # amostras curtas das músicas longas: confere se é mesmo canto (e não pregação com teclado ao fundo)
    amostras = []
    for f in fontes:
        if f["kind"] != "video" or not f.get("som"):
            continue
        for r in f["runs"]:
            if r["tipo"] == "m" and r["e"] - r["s"] >= 15:
                amostras.append((r["e"] - r["s"], f, float(r["s"]) + 2.0, float(r["s"]) + 14.0))
    amostras.sort(key=lambda x: -x[0])
    if not cand and not amostras:
        return False
    cand.sort(key=lambda x: -x[0])
    escolhidos: dict[str, list] = {}
    soma = 0.0
    for prio, f, a, b in cand:
        if soma + (b - a) > orc and soma > 0:
            continue
        escolhidos.setdefault(f["mid"], []).append([a, b])
        soma += b - a
    for _, f, a, b in amostras[:4]:
        escolhidos.setdefault(f["mid"], []).append([a, b])
        soma += b - a
    feito = 0.0
    try:
        for f in fontes:
            rs = escolhidos.get(f["mid"])
            if not rs:
                continue
            tam = sum(b - a for a, b in rs)

            def pr(x, msg="", base=feito, tam=tam):
                p(0.45 + 0.3 * min(1.0, (base + x * tam) / max(1.0, soma)),
                  f"Ouvindo as falas ({int(min(soma, base + x * tam))} de {int(soma)} s)…")
            ws = montagem_som.palavras_da_midia(pid, f["md"], sorted(rs), pr)
            f["words"] = ws
            feito += tam
    except Exception as e:
        avisos.append(f"Não consegui transcrever as falas ({str(e)[:120]}). O resumo saiu sem as frases com legenda.")
        return False
    return True


def criar(pid: str, o: dict, progress: Progresso = None) -> dict:
    def p(x, msg):
        if progress:
            progress(min(0.999, x), msg)
    opts = opcoes(o)
    m = montagem.carregar(pid)
    vis, sons = _arquivos(m)
    if not vis:
        raise RuntimeError("Envie pelo menos um vídeo ou uma foto do culto.")
    avisos: list[str] = []
    horas = _ordem_no_tempo(vis)
    ordem_envio = {x["id"]: k for k, x in enumerate(sorted(vis, key=lambda x: x.get("added") or 0))}
    fontes = []
    for k, md in enumerate(vis):
        nome = md.get("name") or "arquivo"
        p(0.02 + 0.43 * k / len(vis), f"Olhando {'o vídeo' if md['kind'] == 'video' else 'a foto'} {k + 1} de {len(vis)}: {nome[:40]}…")
        an = analisar_midia(pid, md)
        f = {"pid": pid, "mid": md["id"], "md": md, "kind": md["kind"], "dur": float(md.get("duration") or 0),
             "fps": float(md.get("fps") or 30), "t0": horas[md["id"]], "ordem": ordem_envio[md["id"]],
             "quadros": an.get("quadros") or [], "som": an.get("som"), "foto": an.get("foto"),
             "runs": [dict(r) for r in ((an.get("som") or {}).get("trechos") or [])]}
        fontes.append(f)
    # falas: transcreve as mais fortes e separa oração / pregação
    transcreveu = False
    if opts["som_original"] or opts["rotulos"]:
        p(0.45, "Ouvindo as falas…")
        transcreveu = _transcrever_falas(pid, fontes, opts["duracao"], p, avisos)
    for f in fontes:  # "música" que na verdade é fala (pregação com fundo musical, igreja com eco)
        ws = f.get("words") or []
        for r in f["runs"]:
            if r["tipo"] == "m" and ws and parece_fala([w for w in ws if r["s"] <= w["s"] < r["e"]]):
                r["tipo"] = "f"
    trechos, frases = [], []
    nt = nf = 0
    for ia_k, f in enumerate(sorted(fontes, key=lambda f: f["t0"])):
        ws = f.get("words") or []
        for r in f["runs"]:
            if r["tipo"] == "s":
                continue
            r["id"] = f"t{nt}"
            nt += 1
            if r["tipo"] == "m":
                r["cat"] = "louvor"
                letra = " ".join(w["w"] for w in ws if r["s"] <= w["s"] < r["e"])
                trechos.append({"id": r["id"], "arq": ia_k + 1, "s": r["s"], "e": r["e"], "tipo": "m",
                                "texto": letra})
                continue
            dentro = [w for w in ws if r["s"] - 0.5 <= w["s"] < r["e"] + 0.5]
            txt = " ".join(w["w"] for w in dentro)
            r["cat"] = categoria_da_fala(txt, r["e"] - r["s"])
            trechos.append({"id": r["id"], "arq": ia_k + 1, "s": r["s"], "e": r["e"], "tipo": "f", "texto": txt})
        fr_lista = []
        for fr in frases_de(ws):
            fr["id"] = f"f{nf}"
            nf += 1
            fr["cat"] = _cat_em(f, (fr["s"] + fr["e"]) / 2) or "pregacao"
            fr_lista.append(fr)
            frases.append(fr)
        f["frases"] = fr_lista
    ia = None
    if opts["usar_ia"] and (trechos or frases):
        p(0.76, "A IA está escolhendo os melhores momentos…")
        k = _contagem_momentos(opts["duracao"])
        try:
            ia = _ia(trechos, frases, opts, (k + 1) // 2 + 1, k // 2 + 1)
        except Exception as e:
            avisos.append(f"A IA não respondeu ({str(e)[:120]}); as escolhas foram feitas pelo programa.")
            ia = None
        if ia:
            for f in fontes:
                for r in f["runs"]:
                    t = ia["tipos"].get(r.get("id", ""))
                    if t:
                        r["cat"] = t
                for fr in f.get("frases") or []:
                    fr["cat"] = _cat_em(f, (fr["s"] + fr["e"]) / 2) or fr["cat"]
                # frases de avisos e ofertas não entram
                f["frases"] = [fr for fr in f.get("frases") or [] if fr["cat"] not in ("avisos",)]
    # música e ritmo
    p(0.8, "Escolhendo a música…")
    musica = _musica(pid, opts["musica"], opts, sons, avisos)
    batida = None
    if musica:
        p(0.86, "Achando o ritmo da música…")
        batida = batidas(store.pdir(pid) / musica["file"], store.pdir(pid) / "cache")
    marca = store.load_config().get("brand") or {}
    logo_md = _logo(pid) if (opts["logo"] or opts["encerramento"]) else None
    opts["_tem_encerramento"] = bool(opts["encerramento"] and (logo_md or (marca.get("handle") or "").strip()))
    p(0.9, "Escolhendo os pedaços…")
    pecas = planejar(fontes, opts, batida, ia)
    if not pecas:
        raise RuntimeError("Não achei pedaços bons nos arquivos enviados (vídeos muito escuros ou curtos demais?).")
    titulo = opts["titulo"] or (ia or {}).get("titulo") or EVENTOS[opts["evento"]][1]
    primeira = min((f["t0"] for f in fontes if f["md"].get("quando")), default=None)
    data_txt = _data_por_extenso(primeira, opts["data"])
    p(0.94, "Montando a linha do tempo…")
    mt = escrever(pid, pecas, opts, musica, titulo, data_txt, logo_md)
    dur = montagem.duracao(mt)
    partes = []
    rot = EVENTOS[opts["evento"]][2]
    for pc in pecas:
        c = pc.get("cat")
        if c in rot and rot[c] not in partes:
            partes.append(rot[c])
    res = {"id": pid, "duracao": round(dur, 2), "pecas": len(pecas),
           "videos": sum(1 for x in pecas if x["kind"] == "video" and not x.get("som")),
           "fotos": sum(1 for x in pecas if x["kind"] == "image"),
           "momentos": sum(1 for x in pecas if x.get("som")),
           "frases": sum(1 for x in pecas if x.get("momento") == "frase"), "partes": partes,
           "musica": bool(musica), "ritmo_musica": bool(batida), "ia": bool(ia), "titulo": titulo,
           "transcreveu": transcreveu, "arquivos": len(vis)}
    if dur < opts["duracao"] - 6:
        avisos.append(f"Com o material enviado, o resumo ficou com {int(round(dur))} s "
                      f"(menos que os {int(opts['duracao'])} s pedidos). Envie mais vídeos ou fotos para aumentar.")
    if avisos:
        res["aviso"] = " ".join(avisos)
    salvar = {k: v for k, v in opts.items() if not k.startswith("_")}
    store.update(pid, lambda pr: pr.setdefault("resumo", {}).update(opcoes=salvar, titulo=titulo,
                                                                     feito=time.time(), resultado=res))
    p(1.0, "Pronto!")
    return res


# ---------------------------------------------------------------- telas

def status() -> dict:
    from ..engine import transcribe
    cfg = store.load_config()
    ai = cfg.get("ai") or {}
    ia_nome = ""
    if ai.get("provider") == "anthropic":
        ia_nome = "Claude"
    elif ai.get("provider") == "openai_compat":
        ia_nome = "Gemini" if "generativelanguage" in (ai.get("base_url") or "") else "GPT/compatível"
    mus = sorted(f.name for f in pipeline.MUSICAS.glob("*") if f.is_file() and f.suffix.lower() in montagem.EXT_AUDIO) \
        if pipeline.MUSICAS.exists() else []
    tr = cfg.get("transcription") or {}
    return {"eventos": {k: v[0] for k, v in EVENTOS.items()}, "titulos": {k: v[1] for k, v in EVENTOS.items()},
            "estilos_legenda": ESTILOS_LEGENDA, "musicas": mus,
            "ia": ai.get("provider") not in (None, "none") and bool(ai.get("api_key")), "ia_nome": ia_nome,
            "transcricao": tr.get("provider") == "api" or transcribe.local_available(),
            "marca": {"logo": (store.BRAND_DIR / "logo.png").exists(),
                      "handle": bool((cfg.get("brand") or {}).get("handle"))}}


def lista() -> list[dict]:
    out = []
    for x in store.list_projects():
        if not x.get("resumo"):
            continue
        try:
            pr = store.load(x["id"])
            m = montagem.carregar(x["id"])
        except Exception:
            continue
        vis, sons = _arquivos(m)
        r = pr.get("resumo") or {}
        out.append({"id": x["id"], "name": x["name"], "updated": x["updated"], "status": x["status"],
                    "arquivos": len(vis), "videos": sum(1 for v in vis if v["kind"] == "video"),
                    "fotos": sum(1 for v in vis if v["kind"] == "image"), "opcoes": r.get("opcoes"),
                    "resultado": r.get("resultado"), "feito": r.get("feito")})
    return out[:30]

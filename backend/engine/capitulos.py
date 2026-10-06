"""Capítulos automáticos para o YouTube (e para navegar no vídeo longo).

Sem IA: divide a fala por assunto, medindo quando o vocabulário muda (método do "TextTiling": compara as palavras
de cada janela com as da janela seguinte; onde a semelhança cai mais, começa outro assunto). O título vem da frase
mais representativa de cada parte.
Com IA (Claude ou compatível): a IA só dá nome aos capítulos (custo de centavos), a divisão continua local.

Os tempos ficam guardados no tempo ORIGINAL do vídeo e são convertidos para o vídeo editado na hora de mostrar,
então os capítulos continuam certos mesmo depois de mexer na edição."""
from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter

from .smartcuts import _needs_context, sentences, short_hook

# Palavras que não dizem o assunto (artigos, pronomes, verbos de ligação, muletas da fala)
_STOP = set("""
a o as os um uma uns umas de da do das dos em na no nas nos por pela pelo pelas pelos para pra pro pros com sem sob
sobre entre ate até e ou mas porem porém que se nao não sim ja já so só mais menos muito muita muitos muitas pouco
eu tu ele ela nos nós vos vós eles elas me te lhe nos lhes meu minha meus minhas teu tua seu sua seus suas nosso
nossa nossos nossas dele dela deles delas este esta estes estas esse essa esses essas aquele aquela aqueles aquelas
isto isso aquilo aqui ali la lá aí ai cá entao então tambem também quando onde como porque pois assim tudo nada
todo toda todos todas cada outro outra outros outras mesmo mesma qual quais quem cujo ser sou é era foi são somos
estar estou está esta estamos estão estava ter tenho tem temos têm tinha tive teve haver há havia fazer faz fez
vai vou vamos ir vem veio dar deu dizer disse diz falar falou ver viu olha olhe ok né ne tipo bom bem agora hoje
ainda sempre nunca já gente coisa coisas vez vezes dia ano anos aqui algo alguem alguém ninguem ninguém pode
podemos poder quer quero queremos sabe sei saber acho acha então daí dai aí hum hã ah eh é éé obrigado obrigada
""".split())


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def _raiz(w: str) -> str:
    """Raiz simples (português): junta "oração/orações/orar", "promessa/promessas"."""
    w = _sem_acento(w)
    for suf in ("mente", "coes", "cao", "oes", "ões", "ais", "eis", "es", "as", "os", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            w = w[: -len(suf)]
            break
    return w[:7]


def _termos(texto: str) -> list[str]:
    out = []
    for w in re.findall(r"[a-zà-ÿ]+", texto.lower()):
        if len(w) < 3 or w in _STOP or _sem_acento(w) in _STOP:
            continue
        out.append(_raiz(w))
    return out


def _cos(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    num = sum(v * b.get(k, 0) for k, v in a.items())
    den = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return num / den if den else 0.0


def _blocos(sents: list[dict], alvo: float = 40.0) -> list[dict]:
    """Junta frases em blocos de ~40 s (unidade de comparação)."""
    out, cur = [], []
    for s in sents:
        cur.append(s)
        if cur[-1]["e"] - cur[0]["s"] >= alvo:
            out.append(cur)
            cur = []
    if cur:
        if out and cur[-1]["e"] - cur[0]["s"] < alvo / 2:
            out[-1].extend(cur)
        else:
            out.append(cur)
    return [{"s": b[0]["s"], "e": b[-1]["e"], "sents": b, "bag": Counter(t for x in b for t in _termos(x["text"]))}
            for b in out]


def quantos(duracao: float) -> int:
    """Quantidade de capítulos que fica boa para o tamanho do vídeo (1 a cada ~6 min, de 3 a 12)."""
    return int(max(3, min(12, round(duracao / 360.0))))


def dividir(words: list[dict], segments: list[dict] | None = None, n: int | None = None,
            minimo: float = 90.0) -> list[dict]:
    """Capítulos no tempo original: [{"s", "e", "sents"}]. Sempre começa no início da fala."""
    sents = [s for s in sentences(segments or [], words) if s.get("text", "").strip()]
    if not sents:
        return []
    dur = sents[-1]["e"] - sents[0]["s"]
    if dur < minimo * 2:
        return [{"s": sents[0]["s"], "e": sents[-1]["e"], "sents": sents}]
    n = n or quantos(dur)
    bl = _blocos(sents)
    if len(bl) < 3:
        return [{"s": sents[0]["s"], "e": sents[-1]["e"], "sents": sents}]
    k = 2  # janelas de 2 blocos (~80 s) de cada lado da fronteira
    sim = []
    for i in range(1, len(bl)):
        esq = sum((b["bag"] for b in bl[max(0, i - k):i]), Counter())
        dir_ = sum((b["bag"] for b in bl[i:i + k]), Counter())
        sim.append(_cos(esq, dir_))
    # profundidade do "vale": quanto a semelhança cai em relação aos picos dos dois lados
    prof = []
    for i, v in enumerate(sim):
        pe = max(sim[max(0, i - 3):i + 1])
        pd = max(sim[i:i + 4])
        prof.append((pe - v) + (pd - v))
    # frase que abre o bloco começando com "e/mas/isso..." não é bom começo de capítulo
    for i in range(len(prof)):
        if _needs_context(bl[i + 1]["sents"][0]["text"]):
            prof[i] *= 0.6
    ordem = sorted(range(len(prof)), key=lambda i: -prof[i])
    cortes: list[int] = []
    for i in ordem:
        t = bl[i + 1]["s"]
        if t - sents[0]["s"] < minimo or sents[-1]["e"] - t < minimo:
            continue
        if any(abs(t - bl[j + 1]["s"]) < minimo for j in cortes):
            continue
        cortes.append(i)
        if len(cortes) >= n - 1:
            break
    limites = sorted(bl[i + 1]["s"] for i in cortes)
    caps, ini = [], sents[0]["s"]
    for t in limites + [sents[-1]["e"] + 1]:
        grupo = [s for s in sents if ini <= s["s"] < t]
        if grupo:
            caps.append({"s": grupo[0]["s"], "e": grupo[-1]["e"], "sents": grupo})
        ini = t
    return caps


def _titulo_local(cap: dict, geral: Counter, total_caps: int) -> str:
    """Frase mais representativa do capítulo, encurtada (palavras do capítulo que pouco aparecem no resto)."""
    local = Counter(t for s in cap["sents"] for t in _termos(s["text"]))
    if not local:
        return short_hook(cap["sents"][0]["text"], 48)
    peso = {t: c * math.log(1 + total_caps * sum(geral.values()) / (1 + geral[t] * total_caps)) for t, c in local.items()}
    melhor, nota = cap["sents"][0], -1.0
    for s in cap["sents"]:
        ts = _termos(s["text"])
        if len(ts) < 2 or len(s["text"]) > 160:
            continue
        sc = sum(peso.get(t, 0) for t in set(ts)) / (len(set(ts)) ** 0.5)
        sc *= 0.7 if _needs_context(s["text"]) else 1.0
        if sc > nota:
            melhor, nota = s, sc
    t = short_hook(melhor["text"], 48).rstrip(".…,;:!? ")
    return (t[:1].upper() + t[1:]) if t else "Parte"


PROMPT = """Você dá nome a capítulos de vídeo do YouTube em português do Brasil.
O vídeo é uma {tipo}. Abaixo estão os capítulos já divididos, cada um com um trecho da fala.
Para cada capítulo, escreva um título curto (de 2 a 6 palavras), claro e atraente, que diga o assunto daquela parte.
Sem numeração, sem aspas, sem emojis, sem ponto final. O primeiro capítulo pode se chamar algo como "Abertura" se for
só uma introdução.

Responda SOMENTE com JSON válido: ["título 1", "título 2", ...] (exatamente {n} títulos, na mesma ordem).

CAPÍTULOS:
{texto}"""


def titulos_ia(caps: list[dict], ai: dict, tipo: str = "pregação ou palestra") -> list[str]:
    from .smartcuts import _call_llm
    partes = []
    for i, c in enumerate(caps):
        fala = " ".join(s["text"] for s in c["sents"])
        if len(fala) > 1800:  # começo e fim de cada capítulo bastam para dar nome
            fala = fala[:1300] + " (...) " + fala[-450:]
        partes.append(f"[{i + 1}] {fala}")
    raw = _call_llm(PROMPT.format(tipo=tipo, n=len(caps), texto="\n\n".join(partes)), ai)
    m = re.search(r"\[.*\]", raw, re.S)
    lista = json.loads(m.group(0)) if m else []
    out = [str(x).strip().strip('"').rstrip(".")[:70] for x in lista]
    if len(out) != len(caps) or not all(out):
        raise RuntimeError("A IA não devolveu os títulos certinho. Tente de novo.")
    return out


def gerar(project: dict, ai: dict | None = None) -> dict:
    """Divide e dá nome. Devolve {"itens": [{"t", "titulo"}], "fonte": "ia" | "local"} no tempo original."""
    words = project.get("words") or []
    if not words:
        raise RuntimeError("Este projeto ainda não tem a fala transcrita.")
    caps = dividir(words, project.get("segments"))
    if not caps:
        raise RuntimeError("Não encontrei fala suficiente para dividir em capítulos.")
    geral = Counter(t for c in caps for s in c["sents"] for t in _termos(s["text"]))
    titulos, fonte, aviso = None, "local", ""
    if ai and ai.get("provider") not in (None, "none") and ai.get("api_key"):
        try:
            titulos, fonte = titulos_ia(caps, ai), "ia"
        except Exception as e:  # sem internet/crédito: fica com os títulos locais e avisa
            aviso = f"Títulos feitos sem IA ({str(e)[:140]})"
    if not titulos:
        titulos = [_titulo_local(c, geral, len(caps)) for c in caps]
        if len(titulos) > 1 and caps[0]["e"] - caps[0]["s"] < 150:
            titulos[0] = titulos[0] or "Abertura"
    itens = [{"t": round(c["s"], 2), "titulo": titulos[i]} for i, c in enumerate(caps)]
    return {"itens": itens, "fonte": fonte, "aviso": aviso}


def no_editado(itens: list[dict], keeps: list[list[float]]) -> list[dict]:
    """Converte para o tempo do vídeo editado. O primeiro sempre em 0:00 (regra do YouTube).
    Capítulos que caíram num corte vão para o começo do próximo trecho mantido; se ficarem a menos de 10 s um do
    outro, o YouTube recusa, então junta."""
    from .edits import TimeMap
    tm = TimeMap(keeps) if keeps else None
    out = []
    for i, it in enumerate(sorted(itens, key=lambda x: x["t"])):
        t = it["t"]
        if tm is None:
            te = t
        else:
            te = tm.to_out(t)
            if te is None:
                prox = [s for s, e in keeps if s >= t]
                te = tm.to_out(prox[0]) if prox else None
        if te is None:
            continue
        te = 0.0 if not out else te
        if out and te - out[-1]["t_editado"] < 10:
            continue
        out.append({**it, "t_editado": round(te, 2)})
    return out


def fmt_tempo(t: float, longo: bool) -> str:
    t = int(round(t))
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if longo else f"{m:02d}:{s:02d}"


def texto(itens_editados: list[dict]) -> str:
    """Bloco pronto para colar na descrição do YouTube."""
    if not itens_editados:
        return ""
    longo = itens_editados[-1]["t_editado"] >= 3600
    return "\n".join(f"{fmt_tempo(x['t_editado'], longo)} {x['titulo']}" for x in itens_editados)

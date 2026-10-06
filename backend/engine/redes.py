"""Título, legenda e hashtags sugeridos para cada rede (YouTube Shorts, Instagram Reels, TikTok e Facebook Reels).

Sem IA: tudo sai da própria fala do corte (assunto, frase de abertura, frase marcante), com o tamanho e o jeito de cada
rede. Com a IA ligada, o Claude escreve títulos e legendas mais criativos (centavos por corte)."""
from __future__ import annotations

import json
import re
import unicodedata

from .smartcuts import _STOP, _call_llm, short_hook

REDES = {
    "youtube": {"nome": "YouTube Shorts", "titulo_max": 100, "legenda_max": 4900, "tags": (3, 5), "fixa": ["#shorts"]},
    "instagram": {"nome": "Instagram Reels", "titulo_max": 0, "legenda_max": 2200, "tags": (3, 5), "fixa": ["#reels"],
                  "teto": 5},  # o Instagram aceita no máximo 5 hashtags por publicação
    "tiktok": {"nome": "TikTok", "titulo_max": 0, "legenda_max": 2200, "tags": (3, 5), "fixa": ["#fyp", "#paravocê"]},
    "facebook": {"nome": "Facebook Reels", "titulo_max": 0, "legenda_max": 2200, "tags": (2, 3), "fixa": ["#reels"]},
}
ORDEM = list(REDES)

# assunto → hashtags (a primeira de cada lista é a mais forte)
TEMAS = [
    (("deus", "jesus", "senhor", "cristo", "espírito santo", "bíblia", "biblia", "versículo", "evangelho", "igreja", "pastor",
      "pregação", "pregacao", "culto", "louvor", "glória", "gloria", "salvação"),
     ["#fé", "#deus", "#jesus", "#palavradedeus", "#pregação", "#gospel", "#cristão"]),
    (("oração", "oracao", "orar", "ore ", "orando", "jejum"), ["#oração", "#fé"]),
    (("família", "familia", "filhos", "filho", "filha", "casamento", "marido", "esposa", "pais", "mãe", "pai "),
     ["#família", "#casamento", "#pais"]),
    (("ansiedade", "medo", "depressão", "depressao", "tristeza", "angústia", "paz", "cura", "ferida", "dor"),
     ["#ansiedade", "#paz", "#cura"]),
    (("sonho", "vitória", "vitoria", "vencer", "propósito", "proposito", "esperança", "esperanca", "coragem", "força", "desistir"),
     ["#motivação", "#propósito", "#esperança"]),
    (("perdão", "perdao", "perdoar", "mágoa", "magoa"), ["#perdão", "#cura"]),
    (("amor", "amar", "ame "), ["#amor"]),
    (("dinheiro", "finanças", "financas", "dívida", "divida", "investir", "salário", "salario", "economizar"),
     ["#finanças", "#dinheiro", "#educaçãofinanceira"]),
    (("empresa", "negócio", "negocio", "cliente", "vendas", "vender", "empreender", "marketing"),
     ["#empreendedorismo", "#negócios", "#vendas"]),
    (("aula", "aprender", "estudo", "estudar", "escola", "professor", "aluno", "prova", "concurso"),
     ["#educação", "#aprendizado", "#estudos"]),
    (("saúde", "saude", "corpo", "treino", "academia", "alimentação", "alimentacao", "dieta"), ["#saúde", "#bemestar"]),
    (("música", "musica", "cantar", "canção", "cancao"), ["#música"]),
]
CTA = {
    "youtube": "Inscreva-se para ver mais.",
    "instagram": "Salve e envie para alguém que precisa ouvir isso.",
    "tiktok": "Manda para quem precisa ver isso.",
    "facebook": "Compartilhe com quem precisa ouvir.",
}
_EXTRA_STOP = _STOP | {"não", "nao", "sim", "isso", "esse", "essa", "este", "esta", "aqui", "ali", "então", "entao", "porque",
                       "quando", "onde", "muito", "muita", "mais", "menos", "também", "tambem", "ainda", "sobre", "depois",
                       "antes", "agora", "sempre", "nunca", "tudo", "nada", "coisa", "coisas", "gente", "vocês", "voces",
                       "você", "voce", "eles", "elas", "nós", "nos", "dele", "dela", "tinha", "estava", "vamos", "vai", "foi",
                       "está", "esta", "estão", "pode", "fazer", "falar", "dizer", "disse", "assim", "porém", "pois",
                       "aquele", "aquela", "outro", "outra", "todos", "todas", "cada", "mesmo", "mesma", "minha", "nossa",
                       "nosso", "seus", "suas", "pela", "pelo", "pelas", "pelos", "num", "numa", "entre", "até", "ate",
                       "sabe", "olha", "tipo", "então", "aí", "daí", "né", "hoje", "dia", "vez", "vezes", "quer", "tem",
                       "têm", "ser", "ter", "era", "são", "sao", "estou", "tenho", "fica", "ficar", "lugar", "parte"}


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def tag(palavra: str) -> str:
    """'Palavra de Deus' → '#palavradedeus' (mantém acentos, que todas as redes aceitam)."""
    p = re.sub(r"[^\wÀ-ÿ]+", "", str(palavra).strip().lstrip("#").lower())
    return ("#" + p) if len(p) >= 2 else ""


def limpar_tags(lista, limite: int = 30) -> list[str]:
    out, vistos = [], set()
    for x in lista or []:
        for parte in re.split(r"[\s,;]+", str(x)):
            t = tag(parte)
            k = _sem_acento(t)
            if t and k not in vistos:
                vistos.add(k)
                out.append(t)
    return out[:limite]


def _temas(low: str) -> list[str]:
    pontos = []
    for chaves, tags in TEMAS:
        n = sum(low.count(k) for k in chaves)
        if n:
            pontos.append((n, tags))
    pontos.sort(key=lambda x: -x[0])
    out = []
    for _, tags in pontos:
        out += tags
    return limpar_tags(out)


def _frequentes(texto: str, n: int = 2) -> list[str]:
    cont: dict[str, int] = {}
    for w in re.findall(r"[A-Za-zÀ-ÿ]+", texto.lower()):
        if len(w) >= 5 and w not in _EXTRA_STOP:
            cont[w] = cont.get(w, 0) + 1
    melhores = sorted((c, w) for w, c in cont.items() if c >= 2)
    return [tag(w) for c, w in sorted(melhores, key=lambda x: (-x[0], x[1]))[:n]]


def _frases(texto: str) -> list[str]:
    return [f.strip() for f in re.split(r"(?<=[.?!…])\s+", texto or "") if len(f.strip().split()) >= 3]


def _capitular(s: str) -> str:
    s = s.strip()
    return s[:1].upper() + s[1:] if s else s


def _sem_ponto(s: str) -> str:
    return s.strip().rstrip(".;,:…").strip()


def local(clip: dict, texto: str, marca: dict | None = None) -> dict:
    """Sugestões por rede sem IA, a partir do título do corte e da própria fala."""
    marca = marca or {}
    titulo = _sem_ponto(clip.get("title") or clip.get("hook") or short_hook(texto, 70)) or "Assista até o fim"
    gancho = _sem_ponto(clip.get("hook") or titulo)
    frases = _frases(texto)
    tw = set(re.findall(r"\w+", titulo.lower()))

    def parecida(f: str) -> bool:  # frase que só repete o título
        fw = set(re.findall(r"\w+", f.lower()))
        return bool(fw) and len(fw & tw) / len(fw) > 0.6

    marcante = next((f for f in frases if 5 <= len(f.split()) <= 18 and not parecida(f)),
                    next((f for f in frases if not parecida(f)), ""))
    low = (texto + " " + titulo).lower()
    tema = _temas(low)
    freq = [t for t in _frequentes(texto) if _sem_acento(t) not in {_sem_acento(x) for x in tema}]
    base = tema + freq
    handle = (marca.get("handle") or "").strip()
    pergunta = titulo.endswith("?")

    out = {}
    for net, cfg in REDES.items():
        mn, mx = cfg["tags"]
        tags = limpar_tags(base[: mx - len(cfg["fixa"])] + cfg["fixa"]) if base else limpar_tags(cfg["fixa"] + ["#viral"])
        if len(tags) < mn:
            tags = limpar_tags(tags + ["#viral", "#reflexão"])[:mx]
        tags = tags[:mx]
        if net == "youtube":
            t = titulo if len(titulo) <= 95 else short_hook(titulo, 90)
            legenda = "\n\n".join(x for x in [_capitular(marcante), CTA[net] + (f" {handle}" if handle else "")] if x)
        elif net == "instagram":
            t = ""
            topo = gancho.upper() if len(gancho) <= 60 else gancho
            legenda = "\n\n".join(x for x in [topo + ("" if pergunta else " 👇"), _capitular(marcante), CTA[net]] if x)
        elif net == "tiktok":
            t = ""
            legenda = _capitular(gancho) + ("" if pergunta or gancho.endswith("!") else "…")
        else:  # facebook
            t = ""
            legenda = "\n\n".join(x for x in [_capitular(titulo) + ("" if pergunta else "."), _capitular(marcante), CTA[net]] if x)
        out[net] = {"titulo": t[: cfg["titulo_max"]] if cfg["titulo_max"] else "", "legenda": legenda[: cfg["legenda_max"]],
                    "hashtags": tags}
    return out


def texto_final(item: dict, fixas: list[str] | None = None, net: str = "") -> str:
    """Legenda pronta para colar: legenda + hashtags (as fixas da marca vão no fim, sem repetir)."""
    proprias, fx = limpar_tags(item.get("hashtags")), limpar_tags(fixas)
    teto = REDES.get(net, {}).get("teto")
    if teto:  # as fixas da marca têm prioridade; corta as últimas sugeridas
        fx = fx[:teto]
        chaves = {_sem_acento(x) for x in fx}
        proprias = [x for x in proprias if _sem_acento(x) not in chaves][: max(0, teto - len(fx))]
    tags = limpar_tags(proprias + fx)
    leg = (item.get("legenda") or "").strip()
    if not tags:
        return leg
    return (leg + ("\n\n" if leg else "") + " ".join(tags)).strip()[: REDES.get(net, {}).get("legenda_max", 2200)]


def normalizar(dado: dict | None, reserva: dict | None = None) -> dict:
    """Garante as 4 redes com titulo/legenda/hashtags; o que faltar vem da reserva (sugestão local)."""
    dado = dado if isinstance(dado, dict) else {}
    reserva = reserva or {}
    out = {}
    for net, cfg in REDES.items():
        d = dado.get(net) if isinstance(dado.get(net), dict) else {}
        r = reserva.get(net) or {"titulo": "", "legenda": "", "hashtags": []}
        titulo = str(d.get("titulo") or "").strip()[: cfg["titulo_max"]] if cfg["titulo_max"] else ""
        if cfg["titulo_max"] and not titulo:
            titulo = r.get("titulo", "")
        legenda = str(d.get("legenda") if d.get("legenda") is not None else "").strip()[: cfg["legenda_max"]] or r.get("legenda", "")
        tags = limpar_tags(d.get("hashtags")) if d.get("hashtags") else list(r.get("hashtags") or [])
        out[net] = {"titulo": titulo, "legenda": legenda, "hashtags": tags[:15]}
    return out


def de_ia_curto(curto: dict, clip: dict, texto: str, marca: dict | None = None) -> dict:
    """Converte o formato curto que vem junto da geração dos cortes ({yt, ig, tt, fb, tags}) nas 4 redes completas."""
    base = local(clip, texto, marca)
    tags = limpar_tags(curto.get("tags"))
    if not (curto.get("yt") or curto.get("ig") or curto.get("tt") or curto.get("fb") or tags):
        return base
    out = {}
    for net, cfg in REDES.items():
        b = dict(base[net])
        mx = cfg["tags"][1]
        if tags:
            b["hashtags"] = limpar_tags(tags[: mx - len(cfg["fixa"])] + cfg["fixa"])[:mx]
        if net == "youtube" and curto.get("yt"):
            b["titulo"] = _sem_ponto(curto["yt"])[:95]
        if net == "instagram" and curto.get("ig"):
            resto = b["legenda"].split("\n\n", 1)[1] if "\n\n" in b["legenda"] else ""
            b["legenda"] = "\n\n".join(x for x in [curto["ig"].strip(), resto] if x)
        if net == "tiktok" and curto.get("tt"):
            b["legenda"] = curto["tt"].strip()[:300]
        if net == "facebook" and curto.get("fb"):
            b["legenda"] = "\n\n".join(x for x in [curto["fb"].strip(), CTA[net]] if x)
        out[net] = b
    return out


# ----------------------------- com IA -----------------------------

PROMPT = """Você é social media de um criador de vídeos curtos no Brasil.
Abaixo está a fala de um corte de vídeo (vai virar Shorts, Reels e TikTok). {extra}
Escreva o texto de publicação para CADA rede, em português do Brasil, fiel ao que é dito (não invente fatos):
- youtube: "titulo" chamativo de até 70 caracteres (sem hashtags), "legenda" de 1 a 2 frases para a descrição,
  "hashtags" com 3 a 5 (inclua #shorts).
- instagram: "legenda" com uma primeira linha que prende (até 8 palavras), depois 1 ou 2 frases e uma chamada para salvar
  ou compartilhar; "hashtags" com 3 a 5 (inclua #reels).
- tiktok: "legenda" curta e direta (até 100 caracteres); "hashtags" com 3 a 5 (inclua #fyp).
- facebook: "legenda" de 1 a 3 frases, tom de conversa, com chamada para compartilhar; "hashtags" com 2 ou 3.
Hashtags em minúsculas, sem espaços, sobre o ASSUNTO do vídeo.

Responda SOMENTE com JSON válido:
{{"youtube": {{"titulo": "", "legenda": "", "hashtags": []}}, "instagram": {{"legenda": "", "hashtags": []}},
"tiktok": {{"legenda": "", "hashtags": []}}, "facebook": {{"legenda": "", "hashtags": []}}}}

TÍTULO ATUAL DO CORTE: {titulo}
FALA DO CORTE:
{texto}"""


def com_ia(clip: dict, texto: str, ai: dict, instrucoes: str = "") -> dict:
    extra = ("Instruções do editor: " + instrucoes.strip()[:500]) if instrucoes.strip() else ""
    raw = _call_llm(PROMPT.format(extra=extra, titulo=clip.get("title") or "", texto=texto[:6000]), ai)
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise RuntimeError("A IA não respondeu no formato esperado. Tente de novo.")
    try:
        dado = json.loads(m.group(0))
    except json.JSONDecodeError:
        raise RuntimeError("A IA não respondeu no formato esperado. Tente de novo.")
    return dado

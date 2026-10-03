"""Destaques do vídeo: palavras-chave coloridas na legenda, emojis que aparecem nos momentos certos e
os "momentos fortes" (ênfase na voz) onde a câmera aproxima sozinha.

Sem chave de IA tudo funciona pela análise local (lista de palavras e volume da voz).
Com IA, a escolha das palavras e dos emojis fica bem mais esperta — e o resultado fica guardado no projeto,
então cada trecho só é perguntado à IA uma vez."""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import numpy as np

from .edits import TimeMap, norm_word

EMOJI_DIR = Path(__file__).resolve().parents[2] / "assets" / "emojis"


def catalogo() -> list[dict]:
    try:
        return json.loads((EMOJI_DIR / "emojis.json").read_text(encoding="utf-8"))
    except Exception:
        return []


def arquivo_emoji(e: str) -> Path | None:
    for it in catalogo():
        if it["e"] == e:
            f = EMOJI_DIR / it["arquivo"]
            return f if f.exists() else None
    return None


def _sem_acento(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


# palavra (sem acento, minúscula) → emoji. Pensado para pregações, aulas e vídeos de fé.
_EMOJI_DE = {
    "deus": "🙏", "senhor": "🙏", "orar": "🙏", "oracao": "🙏", "ore": "🙏", "orando": "🙏", "obrigado": "🙏", "gratidao": "🙏",
    "jesus": "✝️", "cristo": "✝️", "cruz": "✝️", "salvacao": "✝️", "salvador": "✝️", "calvario": "✝️",
    "amor": "❤️", "ama": "❤️", "amar": "❤️", "coracao": "❤️", "amou": "❤️",
    "fogo": "🔥", "poder": "🔥", "avivamento": "🔥", "uncao": "🔥",
    "biblia": "📖", "palavra": "📖", "escritura": "📖", "escrituras": "📖", "versiculo": "📖", "livro": "📖",
    "espirito": "🕊️", "paz": "🕊️", "pomba": "🕊️",
    "rei": "👑", "reino": "👑", "coroa": "👑", "autoridade": "👑",
    "milagre": "✨", "milagres": "✨", "gloria": "✨", "maravilha": "✨",
    "familia": "👨‍👩‍👧", "filhos": "👨‍👩‍👧", "filho": "👨‍👩‍👧", "pais": "👨‍👩‍👧",
    "dinheiro": "💰", "financas": "💰", "riqueza": "💰", "prosperidade": "💰", "dizimo": "💰",
    "tempo": "⏰", "hoje": "⏰", "agora": "⏰",
    "proposito": "🎯", "alvo": "🎯", "foco": "🎯", "chamado": "📣",
    "protecao": "🛡️", "escudo": "🛡️", "batalha": "⚔️", "guerra": "⚔️", "inimigo": "⚔️", "luta": "⚔️",
    "semente": "🌱", "plantar": "🌱", "crescer": "🌱", "crescimento": "📈",
    "pao": "🍞", "ceia": "🍷", "agua": "💧", "mar": "🌊", "tempestade": "🌊",
    "luz": "☀️", "sol": "☀️", "escuridao": "🌙", "noite": "🌙", "trevas": "🌙",
    "monte": "⛰️", "montanha": "⛰️", "chave": "🔑", "segredo": "🔑", "porta": "🚪", "portas": "🚪",
    "casa": "🏠", "lar": "🏠", "ouvir": "👂", "ouca": "👂", "olhe": "👀", "veja": "👀", "olhar": "👀",
    "alianca": "🤝", "uniao": "🤝", "juntos": "🤝", "decepcao": "💔", "magoa": "💔", "ferida": "💔",
    "chorar": "😭", "choro": "😭", "lagrimas": "😭", "alegria": "😊", "feliz": "😊", "sorriso": "😊",
    "vitoria": "🏆", "vencer": "🏆", "venceu": "🏆", "conquista": "🏆", "premio": "🏆",
    "forca": "💪", "forte": "💪", "coragem": "🦁", "leao": "🦁",
    "louvor": "🙌", "adoracao": "🙌", "aleluia": "🙌", "gloria a deus": "🙌", "musica": "🎵", "cantar": "🎵",
    "mundo": "🌍", "nacoes": "🌍", "missoes": "🌍", "igreja": "⛪", "culto": "⛪",
    "casamento": "💍", "esposa": "💍", "marido": "💍", "fruto": "🍇", "frutos": "🍇", "colheita": "🍇",
    "ovelha": "🐑", "ovelhas": "🐑", "pastor": "🐑", "crianca": "👶", "criancas": "👶",
    "mente": "🧠", "sabedoria": "🧠", "pensamento": "🧠", "esperar": "⏳", "espera": "⏳", "paciencia": "⏳",
    "caminho": "🛤️", "direcao": "🧭", "passos": "👣", "promessa": "🌈", "promessas": "🌈",
    "valor": "💎", "precioso": "💎", "tesouro": "💎", "santo": "😇", "santidade": "😇",
    "ira": "😡", "raiva": "😡", "cuidado": "⚠️", "perigo": "⚠️", "atencao": "❗", "importante": "❗",
    "verdade": "💯", "certeza": "💯", "sim": "✅", "nunca": "❌", "jamais": "❌",
}
# palavras que viram destaque na legenda mesmo sem emoji
_CHAVE = set(_EMOJI_DE) | {"fe", "graca", "vida", "eterna", "perdao", "esperanca", "cura", "libertacao", "fiel",
                           "fidelidade", "obediencia", "arrependimento", "pecado", "ceu", "inferno", "eternidade",
                           "sangue", "ressurreicao", "transformacao", "destino", "sonho", "sonhos", "bencao", "bencaos",
                           "misericordia", "justica", "humildade", "orgulho", "medo", "ansiedade", "nunca", "sempre",
                           "tudo", "nada", "todos", "ninguem", "primeiro", "ultimo", "unico", "maior", "melhor"}
_PARADA = {"que", "de", "do", "da", "em", "no", "na", "um", "uma", "os", "as", "o", "a", "e", "é", "pra", "para",
           "com", "por", "se", "eu", "ele", "ela", "nos", "voce", "isso", "esse", "essa", "mas", "mais", "foi",
           "tem", "ter", "ser", "esta", "estao", "muito", "ja", "nao", "quando", "como", "porque", "entao"}


def _limpa(w: str) -> str:
    return _sem_acento(norm_word(w))


def locais(words: list[dict]) -> dict[int, dict]:
    """Escolha sem IA: palavras da lista + números. Devolve {índice: {"kw": True, "e": emoji|None}}."""
    out = {}
    for i, w in enumerate(words):
        n = _limpa(w.get("w", ""))
        if not n or n in _PARADA:
            continue
        if n in _CHAVE or re.fullmatch(r"\d+([.,]\d+)?", n) or (len(n) >= 3 and n.isdigit()):
            out[i] = {"kw": True, "e": _EMOJI_DE.get(n)}
    return out


def _prompt(words: list[dict], idxs: list[int], cat: list[dict]) -> str:
    texto = " ".join(f"[{i}]{words[i]['w']}" for i in idxs)
    lista = "; ".join(f"{c['e']} = {c['sentido']}" for c in cat)
    return (
        "Você edita vídeos curtos (Reels/Shorts) de pregações e falas em português. Abaixo está a transcrição, "
        "com o número de cada palavra entre colchetes.\n"
        "1) Escolha as PALAVRAS-CHAVE que merecem cor de destaque na legenda: as que carregam o sentido da frase "
        "(substantivos fortes, verbos de ação, números, nomes). No máximo 1 a cada 6 palavras. Nunca artigos ou "
        "preposições.\n"
        "2) Escolha poucos EMOJIS para aparecer junto de palavras marcantes: no máximo 1 a cada 15 palavras, só "
        "quando combinar de verdade com o sentido. Use SOMENTE emojis desta lista:\n"
        f"{lista}\n\n"
        "Responda só com JSON, sem texto antes ou depois, no formato:\n"
        '{"palavras": [12, 30], "emojis": [{"i": 30, "e": "🔥"}]}\n\n'
        f"Transcrição:\n{texto}"
    )


def com_ia(words: list[dict], idxs: list[int], ai: dict) -> dict[int, dict]:
    """Pergunta à IA (Claude ou compatível) quais palavras destacar e onde pôr emojis."""
    from .smartcuts import _call_llm
    cat = catalogo()
    validos = {c["e"] for c in cat}
    out: dict[int, dict] = {}
    for k in range(0, len(idxs), 900):  # pedaços de até 900 palavras
        parte = idxs[k:k + 900]
        raw = _call_llm(_prompt(words, parte, cat), ai)
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            continue
        try:
            js = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        ok = set(parte)
        for i in js.get("palavras") or []:
            if isinstance(i, int) and i in ok:
                out.setdefault(i, {"kw": True, "e": None})
        for it in js.get("emojis") or []:
            i, e = it.get("i"), it.get("e")
            if isinstance(i, int) and i in ok and e in validos:
                out.setdefault(i, {"kw": True, "e": None})["e"] = e
    return out


def palavras_do_trecho(words: list[dict], keeps: list[list[float]]) -> list[int]:
    tm = TimeMap(keeps)
    return [i for i, w in enumerate(words) if tm.find((w["s"] + w["e"]) / 2) is not None]


def marcar(words: list[dict], mapa: dict) -> list[dict]:
    """Cópia das palavras com "kw" (destaque) para a legenda."""
    out = []
    for i, w in enumerate(words):
        d = mapa.get(str(i)) or mapa.get(i)
        out.append({**w, "kw": True} if d and d.get("kw") else w)
    return out


def eventos_emoji(words: list[dict], mapa: dict, keeps: list[list[float]], max_n: int = 25,
                  espaco: float = 3.5) -> list[dict]:
    """Emojis no tempo do vídeo final: [{e, s, fim}] — um de cada vez, com espaço entre eles."""
    tm = TimeMap(keeps)
    evs, ultimo = [], -99.0
    for k in sorted(mapa, key=lambda x: int(x)):
        d = mapa[k]
        if not d.get("e"):
            continue
        i = int(k)
        if i >= len(words):
            continue
        w = words[i]
        t = tm.to_out((w["s"] + w["e"]) / 2)
        if t is None or t - ultimo < espaco:
            continue
        evs.append({"e": d["e"], "s": round(max(0.0, t - 0.15), 3), "fim": round(min(tm.total, t + 1.6), 3)})
        ultimo = t
        if len(evs) >= max_n:
            break
    return evs


def momentos_fortes(words: list[dict], feats: dict | None, keeps: list[list[float]], mapa: dict | None = None,
                    espaco: float = 5.0, max_n: int = 30) -> list[list[float]]:
    """Onde a voz enfatiza (fala mais forte que o normal ao redor): devolve [início, fim] no vídeo final,
    para a câmera aproximar devagar e voltar."""
    if not words:
        return []
    tm = TimeMap(keeps)
    db = feats.get("db") if feats else None
    nivel = []
    for w in words:
        if db is None or not len(db):
            nivel.append(None)
            continue
        a, b = int(w["s"] * 100), max(int(w["s"] * 100) + 1, int(w["e"] * 100))
        seg = db[a:b]
        nivel.append(float(np.percentile(seg, 80)) if len(seg) else None)
    cand = []
    for i, w in enumerate(words):
        t = tm.to_out((w["s"] + w["e"]) / 2)
        if t is None:
            continue
        n = _limpa(w.get("w", ""))
        if len(n) < 3 or n in _PARADA:
            continue
        score = 0.0
        if nivel[i] is not None:
            viz = [x for x in nivel[max(0, i - 40):i + 40] if x is not None]
            if len(viz) >= 8:
                score = nivel[i] - float(np.median(viz))
        if mapa and (mapa.get(str(i)) or mapa.get(i) or {}).get("e"):
            score += 2.0  # palavra que a IA achou marcante
        if w.get("w", "").rstrip()[-1:] in "!":
            score += 2.0
        if score >= 4.0:
            cand.append((score, t))
    cand.sort(reverse=True)
    escolhidos: list[float] = []
    for _, t in cand:
        if all(abs(t - x) >= espaco for x in escolhidos):
            escolhidos.append(t)
        if len(escolhidos) >= max_n:
            break
    out = []
    for t in sorted(escolhidos):
        a, b = max(0.0, t - 0.35), min(tm.total, t + 1.8)
        if b - a > 0.8:
            out.append([round(a, 3), round(b, 3)])
    return out


def expr_zoom(momentos: list[list[float]], forca: float = 0.12, rampa: float = 0.35) -> str:
    """Expressão do FFmpeg (variável t) que vale 1 fora dos momentos e sobe suave até 1+forca dentro deles."""
    if not momentos:
        return "1"
    termos = "+".join(f"clip((t-{a:.3f})/{rampa},0,1)*clip(({b:.3f}-t)/{rampa},0,1)" for a, b in momentos)
    return f"(1+{forca:.3f}*min(1,{termos}))"

"""Cortes inteligentes e resumos para redes sociais.
- Cortes: trechos contínuos que funcionam sozinhos (30/60/90 s…).
- Resumos: os melhores momentos do vídeo inteiro, juntos num vídeo curto e impactante, abrindo com um gancho.
Com chave de IA usa um modelo de linguagem (Claude ou compatível com OpenAI); sem chave, usa análise local."""
from __future__ import annotations

import json
import re

KEYWORDS = ["segredo", "erro", "dica", "nunca", "sempre", "ninguém", "verdade", "como", "por que", "porque",
            "importante", "problema", "resultado", "mudou", "aprendi", "primeiro", "melhor", "pior", "imagina",
            "olha", "atenção", "cuidado", "simples", "história", "descobri", "deus", "vida", "amor", "fé", "graça",
            "coração", "família", "sonho", "milagre", "transform", "poder", "promessa", "esperança", "jesus",
            "nunca mais", "o mais", "a maior", "o maior", "você precisa", "você pode"]


def sentences(segments: list[dict], words: list[dict]) -> list[dict]:
    """Frases completas: termina em ponto final/interrogação/exclamação ou numa pausa longa.
    Nunca quebra em vírgula (isso picotava as ideias e gerava emendas sem sentido)."""
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        txt = w["w"].strip()
        nxt_gap = (words[i + 1]["s"] - w["e"]) if i + 1 < len(words) else 9.0
        dur = cur[-1]["e"] - cur[0]["s"]
        if (txt[-1:] in ".?!…" and len(cur) >= 3) or (nxt_gap > 0.9 and len(cur) >= 4) or dur > 30:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    sents = [{"s": c[0]["s"], "e": c[-1]["e"], "text": " ".join(x["w"].strip() for x in c)} for c in out]
    if not sents and segments:
        sents = [s for s in segments if s.get("text")]
    return sents


CONNECTIVES = ("e ", "mas ", "então ", "porque ", "porém ", "aí ", "daí ", "isso ", "ele ", "ela ", "eles ", "também ",
               "por isso", "assim ", "pois ", "que ")


def _needs_context(text: str) -> bool:
    """Frase que depende da anterior (começa com "e", "mas", "isso", "ele"...) não deve abrir um trecho."""
    return text.strip().lower().startswith(CONNECTIVES)


_STOP = {"o", "a", "os", "as", "de", "da", "do", "das", "dos", "e", "que", "para", "pra", "em", "no", "na", "um",
         "uma", "com", "por", "se", "ao", "à", "mas", "como", "seu", "sua", "meu", "minha"}


def short_hook(text: str, limit: int = 64) -> str:
    """Gancho curto, cortado sempre entre palavras e nunca terminando em "o", "de", "que"..."""
    t = re.split(r"(?<=[.?!])\s", text.strip())[0].strip()
    if len(t) <= limit:
        return t
    words = t[:limit + 1].split()[:-1] if t[limit:limit + 1] != " " else t[:limit].split()
    while len(words) > 3 and words[-1].lower().strip(",;:") in _STOP:
        words.pop()
    return " ".join(words).rstrip(",;:") + "…"


def _fmt(t: float) -> str:
    m, s = divmod(int(t), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _score(text: str, dur: float) -> float:
    low = text.lower()
    words = len(text.split())
    wps = words / max(dur, 0.5)
    sc = sum(low.count(k) for k in KEYWORDS) * 2.0 + low.count("?") * 1.5 + low.count("!") * 1.2
    sc += min(wps, 3.5)
    if dur < 2.0 or words < 5:
        sc -= 3
    return sc


def _title_of(text: str) -> str:
    return short_hook(text, 70)


# ----------------------------- análise local (sem IA) -----------------------------

def heuristic_cuts(sents: list[dict], lo: float, hi: float, count: int, avoid: list | None = None) -> list[dict]:
    cands = []
    for i in range(len(sents)):
        text, j = "", i
        while j < len(sents) and sents[j]["e"] - sents[i]["s"] <= hi:
            text += " " + sents[j]["text"]
            dur = sents[j]["e"] - sents[i]["s"]
            if dur >= lo:
                score = sum(_score(sents[k]["text"], sents[k]["e"] - sents[k]["s"]) for k in range(i, j + 1)) / (j - i + 1)
                score += 2.5 if sents[i]["text"].rstrip().endswith("?") else 0
                score -= 3.0 if _needs_context(sents[i]["text"]) else 0
                score += 1.5 if sents[j]["text"].rstrip()[-1:] in ".!" else 0
                cands.append((score, sents[i]["s"], sents[j]["e"], text.strip()))
            j += 1
    cands.sort(reverse=True)
    chosen = []
    for score, s, e, text in cands:
        if all(e <= c["segments"][0][0] or s >= c["segments"][0][1] for c in chosen):
            chosen.append({"kind": "corte", "segments": [[round(s, 2), round(e, 2)]], "title": _title_of(text),
                           "reason": "trecho com mais ganchos e ritmo", "score": round(min(99, 40 + score * 8)),
                           "hook": short_hook(text), "post": ""})
        if len(chosen) >= count:
            break
    return sorted(chosen, key=lambda c: c["segments"][0][0])


def heuristic_summaries(sents: list[dict], lo: float, hi: float, count: int) -> list[dict]:
    """Resumo por BLOCOS de ideia (frases seguidas), não por frases soltas: soa como uma fala contínua."""
    target = (lo + hi) / 2
    blocks = []
    for i in range(len(sents)):
        if _needs_context(sents[i]["text"]):
            continue
        j, dur = i, 0.0
        while j < len(sents):
            dur = sents[j]["e"] - sents[i]["s"]
            if dur >= 7 and sents[j]["text"].rstrip()[-1:] in ".?!…":
                break
            if dur > 22:
                break
            j += 1
        j = min(j, len(sents) - 1)
        dur = sents[j]["e"] - sents[i]["s"]
        if 4 <= dur <= 24:
            sc = sum(_score(sents[k]["text"], sents[k]["e"] - sents[k]["s"]) for k in range(i, j + 1)) / (j - i + 1)
            blocks.append((sc, i, j))
    blocks.sort(reverse=True)
    used: set[int] = set()
    out = []
    for _ in range(count):
        pick, total = [], 0.0
        for sc, i, j in blocks:
            if any(k in used for k in range(i - 1, j + 2)) or any(not (j < a - 1 or i > b + 1) for a, b in pick):
                continue
            d = sents[j]["e"] - sents[i]["s"]
            if total + d > hi:
                continue
            pick.append((i, j))
            total += d
            if total >= target:
                break
        if not pick or total < lo * 0.6:
            break
        for i, j in pick:
            used.update(range(i, j + 1))
        hook = pick[0]
        rest = sorted(p for p in pick if p != hook)
        order = [hook] + rest
        segs = [[round(sents[i]["s"], 2), round(sents[j]["e"], 2)] for i, j in order]
        out.append({"kind": "resumo", "segments": segs, "title": _title_of(sents[hook[0]]["text"]),
                    "reason": f"{len(order)} blocos de ideia, abrindo com o mais forte",
                    "score": 60, "hook": short_hook(sents[hook[0]]["text"]), "post": ""})
    return out


# ----------------------------- com IA -----------------------------

PROMPT_CUTS = """Você é um editor de vídeo especialista em conteúdo viral para {platform}.
Abaixo está a transcrição de um vídeo, frase por frase: [número] (início, duração) texto.
{extra}
Escolha os {count} MELHORES trechos CONTÍNUOS para virar cortes independentes de {lo} a {hi} segundos cada.
Critérios: gancho forte nos primeiros 3 segundos, ideia completa (começo, meio e fim), emoção, curiosidade,
utilidade prática ou frase marcante. Precisa fazer sentido sozinho, sem o resto do vídeo. Não sobreponha trechos.

Responda SOMENTE com JSON válido, sem texto antes ou depois:
[{{"inicio": <nº da primeira frase>, "fim": <nº da última frase>, "titulo": "<título curto e chamativo>",
"gancho": "<título de até 8 palavras para a tarja no topo do vídeo>", "selo": "<chamada de 2 a 4 palavras em MAIÚSCULAS que dá vontade de assistir, ex.: PALAVRA DE HOJE, ASSISTA ATÉ O FIM, ISSO MUDA TUDO>",
"motivo": "<por que funciona, até 8 palavras>",
"nota": <0 a 100>, "post": "<texto curto para a publicação, com 3 a 5 hashtags>",
"redes": {{"yt": "<título para o YouTube Shorts, até 70 caracteres>", "ig": "<primeira linha da legenda do Instagram, até 8 palavras>",
"tt": "<legenda curta para o TikTok, até 100 caracteres>", "fb": "<legenda de 1 a 2 frases para o Facebook>",
"tags": ["<3 a 5 hashtags sobre o assunto, minúsculas, sem espaço>"]}}}}]

TRANSCRIÇÃO:
{transcript}"""

PROMPT_SUMMARY = """Você é um editor de vídeo especialista em resumos impactantes para {platform}.
Abaixo está a transcrição de um vídeo longo, frase por frase: [número] (início, duração) texto.
{extra}
Crie {count} RESUMO(S) diferente(s). Cada resumo é formado por 2 a 5 TRECHOS; cada trecho é uma sequência de frases
SEGUIDAS do vídeo (de "inicio" a "fim") que forma uma ideia COMPLETA, com pelo menos 6 segundos.
O resumo inteiro deve somar de {lo} a {hi} segundos e soar como uma fala contínua e coerente, não como frases soltas.
Regras:
- O PRIMEIRO trecho é o gancho mais forte (pode vir de qualquer parte do vídeo); os demais seguem a ordem do vídeo.
- Nenhum trecho pode começar com palavra que dependa do que veio antes ("e", "mas", "então", "isso", "ele", "porque").
- Cada trecho termina no fim de uma frase, nunca no meio de um raciocínio.
- O último trecho fecha a mensagem (conclusão, aplicação ou apelo).
- Resumos diferentes não repetem frases.

Responda SOMENTE com JSON válido, sem texto antes ou depois:
[{{"trechos": [{{"inicio": <nº>, "fim": <nº>}}, ...], "titulo": "<título curto e chamativo>",
"gancho": "<título de até 8 palavras para a tarja no topo do vídeo>", "selo": "<chamada de 2 a 4 palavras em MAIÚSCULAS que dá vontade de assistir>",
"motivo": "<o que o resumo transmite, até 10 palavras>",
"nota": <0 a 100>, "post": "<texto curto para a publicação, com 3 a 5 hashtags>",
"redes": {{"yt": "<título para o YouTube Shorts, até 70 caracteres>", "ig": "<primeira linha da legenda do Instagram, até 8 palavras>",
"tt": "<legenda curta para o TikTok, até 100 caracteres>", "fb": "<legenda de 1 a 2 frases para o Facebook>",
"tags": ["<3 a 5 hashtags sobre o assunto, minúsculas, sem espaço>"]}}}}]

TRANSCRIÇÃO:
{transcript}"""


def _api_error(who: str, r) -> RuntimeError:
    """Erros da API explicados em português."""
    t = r.text[:300]
    low = t.lower()
    if r.status_code == 401 or "invalid x-api-key" in low or "incorrect api key" in low or "invalid_api_key" in low:
        return RuntimeError(f"{who}: a chave da API está errada. Copie de novo no site e cole aqui.")
    if "credit balance" in low or "insufficient_quota" in low or "billing" in low:
        return RuntimeError(f"{who}: a conta está sem crédito. Coloque crédito no site do provedor.")
    if r.status_code == 404 or "model_not_found" in low or "not_found_error" in low:
        return RuntimeError(f"{who}: esse modelo não existe ou não está liberado na sua conta. Escolha outro da lista.")
    if r.status_code == 429:
        return RuntimeError(f"{who}: muitas chamadas seguidas (limite da conta). Espere um minuto e tente de novo.")
    if r.status_code >= 500 or r.status_code == 529:
        return RuntimeError(f"{who}: o serviço está instável agora. Tente de novo em alguns minutos.")
    return RuntimeError(f"{who} respondeu {r.status_code}: {t}")


def _call_llm(prompt: str, ai: dict) -> str:
    import httpx

    provider = ai.get("provider")
    key = ai.get("api_key") or ""
    if not key:
        raise RuntimeError("Chave de IA não configurada.")
    if provider == "anthropic":
        r = httpx.post("https://api.anthropic.com/v1/messages",
                       headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                       json={"model": ai.get("model") or "claude-haiku-4-5-20251001", "max_tokens": 8000,
                             "messages": [{"role": "user", "content": prompt}]}, timeout=300)
        if r.status_code != 200:
            raise _api_error("Claude", r)
        return "".join(b.get("text", "") for b in r.json().get("content", []))
    base = (ai.get("base_url") or "https://api.openai.com/v1").rstrip("/")
    r = httpx.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {key}"},
                   json={"model": ai.get("model") or "gpt-4o-mini", "temperature": 0.3,
                         "messages": [{"role": "user", "content": prompt}]}, timeout=300)
    if r.status_code != 200:
        raise _api_error("IA", r)
    return r.json()["choices"][0]["message"]["content"]


def _transcript(sents: list[dict]) -> str:
    lines = [f"[{i}] ({_fmt(s['s'])}, {s['e'] - s['s']:.0f}s) {s['text']}" for i, s in enumerate(sents)]
    txt = "\n".join(lines)
    return txt[:500_000]


def _parse(raw: str) -> list[dict]:
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    return [d for d in data if isinstance(d, dict)]


def _common(it: dict) -> dict:
    try:
        nota = max(0, min(100, int(float(it.get("nota") or 0))))
    except (TypeError, ValueError):
        nota = 0
    out = {"title": short_hook(str(it.get("titulo", "")), 90), "hook": short_hook(str(it.get("gancho", ""))),
           "reason": str(it.get("motivo", ""))[:90], "score": nota, "score_fonte": "ia" if nota else "",
           "post": str(it.get("post", ""))[:600], "kicker": str(it.get("selo", "")).upper()[:34]}
    rd = it.get("redes")
    if isinstance(rd, dict):  # textos curtos por rede vindos da IA (completados depois pelo módulo redes)
        out["redes_ia"] = {k: str(rd.get(k) or "")[:300] for k in ("yt", "ig", "tt", "fb")}
        tags = rd.get("tags")
        out["redes_ia"]["tags"] = [str(x)[:40] for x in tags[:6]] if isinstance(tags, list) else []
    return out


def llm_cuts(sents, lo, hi, count, ai, platform, extra) -> list[dict]:
    raw = _call_llm(PROMPT_CUTS.format(count=count, lo=int(lo), hi=int(hi), platform=platform, extra=extra,
                                       transcript=_transcript(sents)), ai)
    out = []
    for it in _parse(raw):
        try:
            a, b = int(it["inicio"]), int(it["fim"])
        except (KeyError, ValueError, TypeError):
            continue
        a, b = sorted((max(0, min(a, len(sents) - 1)), max(0, min(b, len(sents) - 1))))
        while sents[b]["e"] - sents[a]["s"] > hi + 10 and b > a:
            b -= 1
        out.append({"kind": "corte", "segments": [[round(sents[a]["s"], 2), round(sents[b]["e"], 2)]], **_common(it)})
    return sorted(out, key=lambda c: c["segments"][0][0])


def llm_summaries(sents, lo, hi, count, ai, platform, extra) -> list[dict]:
    raw = _call_llm(PROMPT_SUMMARY.format(count=count, lo=int(lo), hi=int(hi), platform=platform, extra=extra,
                                          transcript=_transcript(sents)), ai)
    n = len(sents)
    out = []
    for it in _parse(raw):
        ranges = []
        for tr in it.get("trechos") or []:
            try:
                a, b = int(tr["inicio"]), int(tr["fim"])
            except (KeyError, ValueError, TypeError):
                continue
            a, b = sorted((max(0, min(a, n - 1)), max(0, min(b, n - 1))))
            ranges.append((a, b))
        if not ranges:  # formato antigo: lista de frases
            for x in it.get("frases") or []:
                try:
                    i = int(x)
                except (ValueError, TypeError):
                    continue
                if 0 <= i < n:
                    ranges.append((i, i))
        if not ranges:
            continue
        # respeita a duração máxima tirando trechos do meio, se precisar
        while sum(sents[b]["e"] - sents[a]["s"] for a, b in ranges) > hi + 10 and len(ranges) > 2:
            ranges.pop(-2)
        segs = [[round(sents[a]["s"], 2), round(sents[b]["e"], 2)] for a, b in ranges]
        out.append({"kind": "resumo", "segments": segs, **_common(it)})
    return out


def merge_adjacent(segs: list[list[float]]) -> list[list[float]]:
    """Junta frases vizinhas que já estão em sequência no vídeo (menos emendas)."""
    out: list[list[float]] = []
    for s, e in segs:
        if out and 0 <= s - out[-1][1] < 1.2:
            out[-1][1] = e
        else:
            out.append([s, e])
    return out


def generate(project: dict, studio: dict, lo: float, hi: float, ai: dict, platform_name: str) -> tuple[list[dict], str]:
    sents = sentences(project.get("segments") or [], project.get("words") or [])
    if not sents:
        return [], "sem transcrição"
    mode = studio.get("mode", "cortes")
    count = max(1, min(15, int(studio.get("count") or 5)))
    extra = ""
    if (studio.get("instructions") or "").strip():
        extra = "Instruções do editor (siga com prioridade): " + studio["instructions"].strip()[:800]
    n_sum = max(1, min(5, count // 2 if mode == "ambos" else count)) if mode in ("resumo", "ambos") else 0
    n_cut = count if mode == "cortes" else (count - n_sum if mode == "ambos" else 0)
    use_ai = ai.get("provider") in ("anthropic", "openai_compat") and ai.get("api_key")
    how, clips = ("IA" if use_ai else "análise local"), []
    try:
        if use_ai:
            if n_cut:
                clips += llm_cuts(sents, lo, hi, n_cut, ai, platform_name, extra)
            if n_sum:
                clips += llm_summaries(sents, lo, hi, n_sum, ai, platform_name, extra)
    except Exception as exc:
        how = f"análise local (a IA falhou: {str(exc)[:120]})"
        clips = []
    if not clips:
        if n_cut:
            clips += heuristic_cuts(sents, lo, hi, n_cut)
        if n_sum:
            clips += heuristic_summaries(sents, lo, hi, n_sum)
    for c in clips:
        if c["kind"] == "resumo":
            c["segments"] = merge_adjacent(c["segments"])
    return clips, how

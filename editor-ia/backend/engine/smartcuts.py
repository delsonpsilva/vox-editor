"""Cortes inteligentes: escolhe os melhores trechos para Reels/Shorts.
Com chave de API usa um modelo de linguagem (Claude ou compatível com OpenAI); sem chave, usa heurística local."""
from __future__ import annotations

import json
import re

KEYWORDS = ["segredo", "erro", "dica", "nunca", "sempre", "ninguém", "verdade", "como", "por que", "porque",
            "importante", "problema", "resultado", "dinheiro", "mudou", "aprendi", "primeiro", "melhor", "pior",
            "imagina", "olha", "atenção", "cuidado", "simples", "rápido", "história", "descobri"]


def _sentences(segments: list[dict], words: list[dict]) -> list[dict]:
    if segments:
        return [s for s in segments if s.get("text")]
    # Sem segmentos: agrupa palavras por pontuação
    out, cur = [], []
    for w in words:
        cur.append(w)
        if w["w"][-1:] in ".?!" or len(cur) > 30:
            out.append({"s": cur[0]["s"], "e": cur[-1]["e"], "text": " ".join(x["w"] for x in cur)})
            cur = []
    if cur:
        out.append({"s": cur[0]["s"], "e": cur[-1]["e"], "text": " ".join(x["w"] for x in cur)})
    return out


def _fmt(t: float) -> str:
    m, s = divmod(int(t), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def heuristic_clips(sents: list[dict], cfg: dict) -> list[dict]:
    lo, hi, count = cfg.get("min", 30), cfg.get("max", 60), cfg.get("count", 5)
    cands = []
    for i in range(len(sents)):
        text, j = "", i
        while j < len(sents) and sents[j]["e"] - sents[i]["s"] <= hi:
            text += " " + sents[j]["text"]
            dur = sents[j]["e"] - sents[i]["s"]
            if dur >= lo:
                low = text.lower()
                wps = len(text.split()) / max(dur, 1)
                score = (sum(low.count(k) for k in KEYWORDS) * 2 + low.count("?") * 1.5 + low.count("!")
                         + min(wps, 3.5) + (2 if sents[i]["text"].rstrip().endswith("?") else 0))
                cands.append((score, sents[i]["s"], sents[j]["e"], text.strip()))
            j += 1
    cands.sort(reverse=True)
    chosen = []
    for score, s, e, text in cands:
        if all(e <= c["s"] or s >= c["e"] for c in chosen):
            first = re.split(r"(?<=[.?!])\s", text)[0]
            chosen.append({"s": round(s, 2), "e": round(e, 2), "title": first[:70] + ("…" if len(first) > 70 else ""),
                           "reason": "trecho com mais ganchos e ritmo", "score": round(min(99, score * 6), 0)})
        if len(chosen) >= count:
            break
    return sorted(chosen, key=lambda c: c["s"])


PROMPT = """Você é um editor de vídeo especialista em cortes virais para Reels, TikTok e Shorts.
Abaixo está a transcrição de um vídeo, frase por frase, com o número da frase e o tempo de início.

Escolha os {count} MELHORES trechos para virar cortes independentes, cada um com duração entre {lo} e {hi} segundos.
Critérios: gancho forte nos primeiros 3 segundos, ideia completa (começo, meio e fim), emoção, curiosidade,
utilidade prática ou frase marcante. O trecho deve fazer sentido sozinho, sem contexto do vídeo inteiro.
Não sobreponha trechos.

Responda SOMENTE com JSON válido, sem texto antes ou depois, neste formato:
[{{"inicio": <número da primeira frase>, "fim": <número da última frase>, "titulo": "<título curto e chamativo em português>", "motivo": "<por que funciona, até 8 palavras>", "nota": <0 a 100>}}]

TRANSCRIÇÃO:
{transcript}"""


def _call_llm(prompt: str, ai: dict) -> str:
    import httpx

    provider = ai.get("provider")
    key = ai.get("api_key") or ""
    if not key:
        raise RuntimeError("Chave de IA não configurada.")
    if provider == "anthropic":
        r = httpx.post("https://api.anthropic.com/v1/messages",
                       headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                       json={"model": ai.get("model") or "claude-haiku-4-5-20251001", "max_tokens": 2000,
                             "messages": [{"role": "user", "content": prompt}]}, timeout=180)
        if r.status_code != 200:
            raise RuntimeError(f"API Claude respondeu {r.status_code}: {r.text[:300]}")
        return "".join(b.get("text", "") for b in r.json().get("content", []))
    base = (ai.get("base_url") or "https://api.openai.com/v1").rstrip("/")
    r = httpx.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {key}"},
                   json={"model": ai.get("model") or "gpt-4o-mini", "temperature": 0.3,
                         "messages": [{"role": "user", "content": prompt}]}, timeout=180)
    if r.status_code != 200:
        raise RuntimeError(f"API de IA respondeu {r.status_code}: {r.text[:300]}")
    return r.json()["choices"][0]["message"]["content"]


def llm_clips(sents: list[dict], cfg: dict, ai: dict) -> list[dict]:
    lo, hi, count = cfg.get("min", 30), cfg.get("max", 60), cfg.get("count", 5)
    lines = [f"[{i}] ({_fmt(s['s'])}) {s['text']}" for i, s in enumerate(sents)]
    transcript = "\n".join(lines)
    if len(transcript) > 400_000:
        transcript = transcript[:400_000]
    raw = _call_llm(PROMPT.format(count=count, lo=lo, hi=hi, transcript=transcript), ai)
    m = re.search(r"\[.*\]", raw, re.S)
    items = json.loads(m.group(0)) if m else []
    out = []
    for it in items:
        try:
            a, b = int(it["inicio"]), int(it["fim"])
        except (KeyError, ValueError, TypeError):
            continue
        a, b = max(0, min(a, len(sents) - 1)), max(0, min(b, len(sents) - 1))
        if b < a:
            a, b = b, a
        s, e = sents[a]["s"], sents[b]["e"]
        while e - s > hi + 8 and b > a:  # respeita a duração máxima
            b -= 1
            e = sents[b]["e"]
        out.append({"s": round(s, 2), "e": round(e, 2), "title": str(it.get("titulo", ""))[:90],
                    "reason": str(it.get("motivo", ""))[:80], "score": it.get("nota", 0)})
    return sorted(out, key=lambda c: c["s"])


def find_clips(project: dict, cfg: dict, ai: dict) -> tuple[list[dict], str]:
    sents = _sentences(project.get("segments") or [], project.get("words") or [])
    if not sents:
        return [], "sem transcrição"
    if ai.get("provider") in ("anthropic", "openai_compat") and ai.get("api_key"):
        try:
            clips = llm_clips(sents, cfg, ai)
            if clips:
                return _ids(clips), "ia"
        except Exception as exc:  # cai para a heurística, mas avisa
            return _ids(heuristic_clips(sents, cfg)), f"heurística (IA falhou: {str(exc)[:120]})"
    return _ids(heuristic_clips(sents, cfg)), "heurística"


def _ids(clips: list[dict]) -> list[dict]:
    for i, c in enumerate(clips):
        c["id"] = f"clip{i + 1}"
    return clips

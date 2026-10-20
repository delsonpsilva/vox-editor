"""Limpeza da fala com IA: a IA lê a transcrição e aponta o que pode sair sem mudar a mensagem
(recomeços, correções, gaguejos, repetições e comentários fora do assunto). O corte final é sempre
encaixado numa pausa real do áudio; o que não der para emendar limpo é descartado."""
from __future__ import annotations

import json
import re

from .smartcuts import _call_llm

PROMPT = """Você é um editor de vídeo cuidadoso. Abaixo está a transcrição de uma fala, palavra por palavra, no
formato número:palavra. Marque APENAS os trechos que podem ser removidos sem mudar a mensagem:
- recomeço: a pessoa começa uma frase, para e começa de novo (corte a tentativa abandonada);
- correção: a pessoa erra e se corrige ("na terça, quer dizer, na quarta" → corte "na terça, quer dizer,");
- gaguejo: sílabas ou palavras quebradas;
- repetição: palavra ou expressão dita duas vezes seguidas sem intenção;
- fora do assunto: comentários técnicos ou paralelos que não fazem parte da mensagem ("liga o som aí", "tá me ouvindo?").
NÃO marque repetições usadas de propósito para dar ênfase, citações, versículos, orações nem palavras necessárias
para a frase fazer sentido. Na dúvida, não marque. Cada trecho tem no máximo 25 palavras.

Responda SOMENTE com JSON válido, sem texto antes ou depois:
[{{"inicio": <nº da primeira palavra>, "fim": <nº da última palavra>, "tipo": "recomeço|correção|gaguejo|repetição|fora do assunto", "motivo": "<até 8 palavras>"}}]
Se não houver nada para cortar, responda [].

TRANSCRIÇÃO:
{texto}"""


def analyze(words: list[dict], ai: dict, progress=None, chunk: int = 2500) -> list[dict]:
    cuts = []
    n = len(words)
    for c0 in range(0, n, chunk):
        c1 = min(n, c0 + chunk)
        if progress:
            progress(c0 / max(n, 1), f"A IA está lendo a fala ({c0 // chunk + 1} de {(n - 1) // chunk + 1})…")
        texto = " ".join(f"{i}:{words[i]['w'].strip()}" for i in range(c0, c1))
        raw = _call_llm(PROMPT.format(texto=texto), ai)
        m = re.search(r"\[.*\]", raw, re.S)
        try:
            items = json.loads(m.group(0)) if m else []
        except json.JSONDecodeError:
            items = []
        for it in items:
            try:
                a, b = int(it["inicio"]), int(it["fim"])
            except (KeyError, TypeError, ValueError):
                continue
            a, b = sorted((a, b))
            if a < c0 or b >= c1 or b - a > 25:
                continue
            nxt = words[b + 1]["s"] if b + 1 < n else words[b]["e"] + 0.3
            cuts.append({"s": round(words[a]["s"] - 0.03, 3), "e": round(max(words[b]["e"] + 0.03, min(nxt - 0.04, words[b]["e"] + 0.25)), 3),
                         "word": a, "words": [a, b], "label": " ".join(w["w"].strip() for w in words[a:b + 1])[:120],
                         "kind": str(it.get("tipo", ""))[:20], "reason": str(it.get("motivo", ""))[:80]})
    return cuts

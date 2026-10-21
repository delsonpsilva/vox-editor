"""Edição automática 2.0 (parte 2): nota de cada corte com os motivos.

Tudo é calculado no próprio aparelho, sem API, a partir das palavras da transcrição que ficam no corte:
- gancho: como o corte abre (pergunta, frase forte, número, palavra que prende) e se não começa no meio de uma ideia;
- ideia completa: começa no início de uma frase e termina no fim de uma frase;
- emoção: palavras fortes, exclamações e frases marcantes;
- ritmo: velocidade da fala e quanto tempo fica em silêncio;
- duração: se cabe na rede escolhida.
Quando a IA também deu nota (cortes gerados com o Claude ligado), as duas notas são combinadas."""
from __future__ import annotations

import bisect
import re

from .smartcuts import CONNECTIVES

# palavras que prendem quem está rolando a tela
GANCHO = ("segredo", "nunca", "ninguém", "ninguem", "verdade", "você precisa", "voce precisa", "imagina", "olha",
          "atenção", "atencao", "cuidado", "pare", "para de", "erro", "o maior", "a maior", "o mais", "a mais",
          "o pior", "a pior", "o melhor", "a melhor", "descobri", "aprendi", "deixa eu te", "sabia que", "você sabia",
          "por que", "porque você", "o que", "como", "jamais", "isso muda", "mudou", "milagre", "deus", "jesus",
          "escuta", "presta atenção", "ouça", "veja")
FORTES = ("deus", "jesus", "senhor", "fé", "amor", "graça", "milagre", "vida", "morte", "coração", "família",
          "sonho", "promessa", "esperança", "poder", "vitória", "lágrima", "chorei", "chorou", "dor", "perdão",
          "medo", "coragem", "propósito", "transform", "liberdade", "salvação", "glória", "eterno", "nunca mais",
          "nunca", "sempre", "tudo", "verdade", "incrível", "impossível", "urgente", "importante", "segredo")
NUM = re.compile(r"\b(\d+|dois|duas|três|tres|quatro|cinco|sete|dez|cem|mil)\b", re.I)

ROTULOS = [(80, "otimo", "Ótimo"), (65, "bom", "Bom"), (50, "medio", "Médio"), (0, "fraco", "Fraco")]


def _texto(ws: list[dict]) -> str:
    return " ".join(w["w"].strip() for w in ws).strip()


def _fim_de_frase(w: dict | None) -> bool:
    return bool(w) and w["w"].strip()[-1:] in ".?!…"


def _palavras(words: list[dict], starts: list[float], faixas: list[list[float]]) -> list[list[dict]]:
    """Palavras de cada faixa (pelo meio da palavra), usando busca binária: rápido mesmo em vídeos de horas."""
    out = []
    for s, e in faixas:
        i = max(0, bisect.bisect_left(starts, s - 2.0))
        grupo = []
        while i < len(words) and words[i]["s"] <= e:
            w = words[i]
            if s <= (w["s"] + w["e"]) / 2 <= e:
                grupo.append(w)
            i += 1
        out.append(grupo)
    return out


def avaliar(words: list[dict], clip: dict, keeps: list[list[float]] | None = None, plat: dict | None = None,
            starts: list[float] | None = None) -> dict:
    """Nota de 0 a 100 + motivos (bons e alertas) de um corte ou resumo."""
    plat = plat or {}
    faixas = [list(x) for x in (keeps or clip.get("segments") or [])]
    if starts is None:
        starts = [w["s"] for w in words]
    grupos = [g for g in _palavras(words, starts, faixas) if g]
    ws = [w for g in grupos for w in g]
    motivos: list[dict] = []
    if len(ws) < 4:
        return {"nota": 0, "nivel": "fraco", "rotulo": "Fraco", "motivos": [{"t": "quase sem fala", "ok": False,
                "dica": "Este trecho tem pouca fala para virar um corte."}], "criterios": {}}

    dur = sum(e - s for s, e in faixas) or (ws[-1]["e"] - ws[0]["s"])
    texto = _texto(ws)
    low = texto.lower()

    # ---------------- gancho (até 30) ----------------
    t0 = ws[0]["s"]
    abertura = []
    for w in ws:
        abertura.append(w)
        if (w["e"] - t0 > 3.5 and len(abertura) >= 4) or (_fim_de_frase(w) and len(abertura) >= 4):
            break
    abre = _texto(abertura)
    abre_low = abre.lower()
    gancho = 8.0
    pergunta = "?" in abre or abre_low.startswith(("por que", "você sabia", "voce sabia", "sabia que", "o que", "como"))
    forte = any(k in abre_low for k in GANCHO) or bool(NUM.search(abre_low)) or "!" in abre
    meio = abre_low.startswith(CONNECTIVES)
    if pergunta:
        gancho += 14
        motivos.append({"t": "pergunta que prende", "ok": True, "dica": f"Abre com uma pergunta: “{abre[:80]}”"})
    if forte:
        gancho += 10 if not pergunta else 6
        if not pergunta:
            motivos.append({"t": "gancho forte", "ok": True, "dica": f"Os primeiros segundos prendem: “{abre[:80]}”"})
    if len(abre.split()) <= 12 and not meio:
        gancho += 4  # frase de abertura curta e direta
    if meio:
        gancho -= 10
        motivos.append({"t": "começa no meio de uma ideia", "ok": False,
                        "dica": f"Abre com “{abre.split()[0]}”, que depende do que veio antes. Puxe o começo um pouco para trás."})
    gancho = max(0.0, min(30.0, gancho))

    # ---------------- ideia completa (até 25) ----------------
    i0 = bisect.bisect_left(starts, ws[0]["s"])
    antes = words[i0 - 1] if i0 > 0 else None
    comeca_bem = (antes is None or _fim_de_frase(antes) or ws[0]["s"] - antes["e"] > 0.7) and not meio
    termina_bem = _fim_de_frase(ws[-1])
    if not termina_bem:
        i1 = bisect.bisect_left(starts, ws[-1]["s"]) + 1
        depois = words[i1] if i1 < len(words) else None
        termina_bem = depois is None or depois["s"] - ws[-1]["e"] > 0.8
    ideia = (12 if comeca_bem else 3) + (13 if termina_bem else 2)
    if comeca_bem and termina_bem:
        motivos.append({"t": "ideia completa", "ok": True, "dica": "Começa no início de uma frase e termina no fim dela: faz sentido sozinho."})
    elif not termina_bem:
        motivos.append({"t": "termina no meio da frase", "ok": False,
                        "dica": "O corte acaba antes de a frase terminar. Estique o fim até a pausa seguinte."})

    # ---------------- emoção e frases marcantes (até 20) ----------------
    n_fortes = sum(low.count(k) for k in FORTES)
    excl = texto.count("!")
    frases = [f.strip() for f in re.split(r"(?<=[.?!…])\s+", texto) if f.strip()]
    def forte_frase(f: str) -> bool:
        return 4 <= len(f.split()) <= 14 and (any(k in f.lower() for k in FORTES) or f.endswith("!"))
    # a frase marcante de preferência não é a mesma da abertura (essa já conta no gancho)
    marcante = next((f for f in frases if forte_frase(f) and f[:25] not in abre and abre[:25] not in f), "") \
        or next((f for f in frases if forte_frase(f)), "")
    dens = n_fortes / max(1.0, dur / 10)  # palavras fortes a cada 10 s
    emocao = min(12.0, dens * 4.0) + min(4.0, excl * 1.5) + (4 if marcante else 0)
    emocao = max(0.0, min(20.0, emocao))
    if marcante and emocao >= 10:
        motivos.append({"t": "frase marcante", "ok": True, "dica": f"“{marcante[:90]}”"})
    elif emocao >= 12:
        motivos.append({"t": "emoção", "ok": True, "dica": "Fala com palavras fortes e intensidade."})

    # ---------------- ritmo (até 15) ----------------
    fala = sum(w["e"] - w["s"] for w in ws)
    wps = len(ws) / max(1.0, dur)
    pausas = 0.0
    for g in grupos:
        for a, b in zip(g, g[1:]):
            if b["s"] - a["e"] > 0.6:
                pausas += b["s"] - a["e"]
    pausa_pct = pausas / max(1.0, dur)
    ritmo = 15.0
    if wps < 1.6:
        ritmo -= 7
    elif wps < 2.0:
        ritmo -= 3
    if wps > 4.2:
        ritmo -= 3
    if pausa_pct > 0.25:
        ritmo -= 6
    elif pausa_pct > 0.15:
        ritmo -= 3
    ritmo = max(0.0, ritmo)
    if ritmo >= 13:
        motivos.append({"t": "ritmo bom", "ok": True, "dica": f"Fala corrida, {wps * 60:.0f} palavras por minuto e poucas pausas."})
    elif wps < 1.6 or pausa_pct > 0.25:
        motivos.append({"t": "muitas pausas", "ok": False,
                        "dica": "A fala é lenta ou tem pausas longas. A edição automática com o perfil Reels dinâmico ajuda."})

    # ---------------- duração (até 10) ----------------
    lo, hi = float(plat.get("lo") or 0), float(plat.get("hi") or 0)
    pmax = float(plat.get("max") or 0)
    duracao = 10.0
    nome = plat.get("short") or plat.get("name") or ""
    if hi and dur > hi + 8:
        duracao = 4.0
        if pmax and dur > pmax + 0.5:
            motivos.append({"t": "longo para a rede", "ok": False,
                            "dica": f"Tem {dur:.0f} s; {nome or 'a rede'} aceita até {pmax:.0f} s (vai em partes)."})
    elif lo and dur < lo * 0.7:
        duracao = 5.0
        motivos.append({"t": "curto demais", "ok": False, "dica": f"Tem só {dur:.0f} s. Cortes muito curtos rendem menos."})
    elif lo or hi:
        motivos.append({"t": "duração certa", "ok": True, "dica": f"{dur:.0f} s, dentro do ideal{' para ' + nome if nome else ''}."})

    if clip.get("kind") == "resumo" and len(faixas) > 1:
        motivos.append({"t": f"{len(faixas)} momentos costurados", "ok": True, "dica": "Junta os melhores momentos abrindo com o mais forte."})

    local = round(gancho + ideia + emocao + ritmo + duracao)
    nota = local
    ia = clip.get("score") if clip.get("score_fonte") == "ia" else None
    if isinstance(ia, (int, float)) and ia > 0:
        nota = round(0.6 * float(ia) + 0.4 * local)
    nota = int(max(0, min(99, nota)))
    nivel, rotulo = next((n, r) for lim, n, r in ROTULOS if nota >= lim)
    # bons primeiro, depois alertas; no máximo 5
    motivos = [m for m in motivos if m["ok"]] + [m for m in motivos if not m["ok"]]
    return {"nota": nota, "nivel": nivel, "rotulo": rotulo, "motivos": motivos[:5], "local": local,
            "ia": int(ia) if ia else None,
            "criterios": {"gancho": round(gancho), "ideia": round(ideia), "emocao": round(emocao),
                          "ritmo": round(ritmo), "duracao": round(duracao)},
            "abertura": abre[:120], "segundos": round(dur, 1), "texto": texto[:1500]}

"""Monta a lista de cortes e atenuações a partir da análise + configurações, e o mapa de tempo resultante."""
from __future__ import annotations

import bisect
import re

DEFAULT_SETTINGS = {
    "silence": {"enabled": True, "auto": True, "threshold_db": -40.0, "min_dur": 0.5, "pad": 0.15, "rhythm": "natural"},
    "breath": {"enabled": True, "mode": "attenuate", "reduce_db": 18.0},
    "fillers": {"enabled": True, "words": ["é", "éé", "ééé", "hã", "hum", "humm", "hmm", "ahn", "ah", "eh", "uh", "um"],
                "repetitions": True, "speech_errors": True, "ai_cleanup": True},
    "subtitles": {"enabled": True, "style": "palavra_ativa", "max_chars": 18, "lines": 2, "uppercase": True,
                  "font": "Poppins ExtraBold", "color": "#FFFFFF", "highlight": "#FFD400", "position": "baixo",
                  "size": "m", "size_pct": 100, "y_pct": 18},
    "audio": {"normalize": True, "target_lufs": -14.0},
    "render": {"quality": "alta"},
    "clips": {"min": 30, "max": 60, "count": 5},
    "studio": {"platform": "ig_reels", "mode": "cortes", "duration": "60", "min": 20, "max": 90, "count": 5,
               "instructions": "", "layout": "face", "title_mode": "inicio", "subtitles": True, "zoom_cuts": True,
               "enhance": "auto", "frame": "cheia"},
}

# Fornecedor das "emendas inteligentes" (definido pelo pipeline: carrega a análise de áudio do projeto)
SEAMS_PROVIDER = None

_PUNCT = re.compile(r"[^\wÀ-ÿ]+", re.UNICODE)

# Palavras que também são palavras normais ("Qual É o segredo", "AH, entendi", "TIPO assim").
# Só viram vício quando estão isoladas por pausas, alongadas ou escritas com reticências.
AMBIGUOUS = {"é", "eh", "ah", "tipo", "né", "então", "bom", "aí", "assim"}


def norm_word(w: str) -> str:
    return _PUNCT.sub("", w.lower())


def merged_settings(s: dict | None) -> dict:
    out = {}
    s = s or {}
    for k, v in DEFAULT_SETTINGS.items():
        out[k] = {**v, **(s.get(k) or {})}
    return out


def find_fillers(words: list[dict], cfg: dict) -> list[dict]:
    lst = {norm_word(x) for x in cfg.get("words", []) if norm_word(x)}
    cuts = []
    n = len(words)
    for i, w in enumerate(words):
        nw = norm_word(w["w"])
        if not nw:
            continue
        is_filler = nw in lst
        if is_filler and nw in AMBIGUOUS:
            gap_b = w["s"] - (words[i - 1]["e"] if i > 0 else -1)
            gap_a = (words[i + 1]["s"] if i + 1 < n else w["e"] + 1) - w["e"]
            stretched = (w["e"] - w["s"]) > 0.45 or "..." in w["w"] or "…" in w["w"]
            is_filler = stretched or (gap_b > 0.2 and gap_a > 0.15) or (gap_a > 0.35)
        is_rep = False
        if cfg.get("repetitions") and i + 1 < n and len(nw) > 1:
            nxt = words[i + 1]
            if norm_word(nxt["w"]) == nw and nxt["s"] - w["e"] < 0.6:
                is_rep = True
        if not (is_filler or is_rep):
            continue
        prev_e = words[i - 1]["e"] if i > 0 else 0.0
        next_s = words[i + 1]["s"] if i + 1 < n else w["e"] + 0.3
        s = max(w["s"] - 0.03, prev_e + 0.04)
        e = max(w["e"] + 0.03, min(next_s - 0.08, w["e"] + 0.3))
        if e - s > 0.05:
            cuts.append({"s": round(s, 3), "e": round(e, 3), "type": "repeticao" if is_rep and not is_filler else "vicio",
                         "word": i, "label": w["w"]})
    return cuts


def find_speech_errors(words: list[dict]) -> list[dict]:
    """Erros de fala sem IA: palavra começada e abandonada ("fu- fui", "pro... problema") e frase repetida
    logo em seguida ("eu vou, eu vou falar"). Corta a primeira tentativa e mantém a que ficou certa."""
    cuts, n = [], len(words)
    norm = [norm_word(w["w"]) for w in words]
    used = set()
    # frase repetida (2 a 5 palavras)
    for size in (5, 4, 3, 2):
        for i in range(0, n - 2 * size + 1):
            if any(k in used for k in range(i, i + 2 * size)):
                continue
            a, b = norm[i:i + size], norm[i + size:i + 2 * size]
            if all(a) and a == b and words[i + size]["s"] - words[i + size - 1]["e"] < 0.8:
                s0, e0 = words[i]["s"] - 0.03, words[i + size]["s"] - 0.04
                cuts.append({"s": round(s0, 3), "e": round(max(e0, words[i + size - 1]["e"] + 0.03), 3),
                             "type": "repeticao", "word": i, "label": " ".join(w["w"] for w in words[i:i + size])})
                used.update(range(i, i + size))
    # palavra cortada: termina em "-" / "…" ou é o começo da palavra seguinte
    for i in range(n - 1):
        if i in used or not norm[i]:
            continue
        raw, nxt = words[i]["w"].strip(), norm[i + 1]
        abandoned = raw.endswith(("-", "…", "...")) and len(norm[i]) <= 6
        nxt2 = norm[i + 2] if i + 2 < n else ""
        if i >= 1 and norm[i - 1] and norm[i - 1] == nxt and nxt2.startswith(norm[i]) and len(norm[i]) < len(nxt2):
            nxt = nxt2  # "o pro- o problema": compara com a palavra depois do artigo repetido
        prefix = (2 <= len(norm[i]) < len(nxt) and nxt.startswith(norm[i]) and len(norm[i]) <= 4
                  and (words[i].get("p", 1) < 0.6 or raw.endswith(("-", "…", "..."))))
        if (abandoned or prefix) and words[i + 1]["s"] - words[i]["e"] < 0.9:
            start = i
            # "o pro- o problema": o recomeço repete a palavra de antes; corta "o pro-" inteiro
            if i >= 1 and i + 2 < n and norm[i - 1] and norm[i - 1] == norm[i + 1] and norm[i + 2].startswith(norm[i]):
                start = i - 1
                nxt_i = i + 1
            else:
                nxt_i = i + 1
            cuts.append({"s": round(words[start]["s"] - 0.03, 3), "e": round(words[nxt_i]["s"] - 0.04, 3),
                         "type": "gaguejo", "word": start, "label": " ".join(w["w"] for w in words[start:i + 1])})
            used.update(range(start, i + 1))
    return [c for c in cuts if c["e"] - c["s"] > 0.05]


def merge_intervals(iv: list[list[float]], gap: float = 0.0) -> list[list[float]]:
    out: list[list[float]] = []
    for s, e in sorted(iv):
        if out and s <= out[-1][1] + gap:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def build_edit(project: dict, seams=None) -> dict:
    """Calcula cortes (com id estável), atenuações, trechos mantidos e estatísticas.
    Todo corte é encaixado numa pausa real do áudio; cortes que ficariam "secos" são descartados."""
    from .seams import pause_cut, remove_islands
    if seams is None and SEAMS_PROVIDER is not None:
        try:
            seams = SEAMS_PROVIDER(project)
        except Exception:
            seams = None
    st = merged_settings(project.get("settings"))
    an = project.get("analysis") or {}
    words = project.get("words") or []
    dur = float(project.get("media", {}).get("duration") or 0)
    ov = project.get("overrides") or {}
    restored = set(ov.get("restored", []))

    cuts = []

    def add(s, e, typ, extra=None):
        cid = f"{typ}-{int(round(s * 100))}"
        c = {"id": cid, "s": round(max(0.0, s), 3), "e": round(min(dur, e), 3), "type": typ,
             "active": cid not in restored}
        if extra:
            c.update(extra)
        if c["e"] - c["s"] > 0.02:
            cuts.append(c)

    ends = [w["e"] for w in words]
    if st["silence"]["enabled"]:
        for s, e in an.get("silences", []):
            if an.get("v", 0) < 3:  # análise antiga (já com margens)
                add(s, e, "silencio")
                continue
            i = bisect.bisect_right(ends, s + 0.15) - 1
            sentence_end = i >= 0 and words[i]["w"].rstrip()[-1:] in ".?!…"
            pc = pause_cut(seams, s, e, st["silence"].get("rhythm", "natural"), sentence_end,
                           at_start=s <= 0.05, at_end=e >= dur - 0.05)
            if pc:
                add(pc[0], pc[1], "silencio")
    if st["fillers"]["enabled"]:
        extra = find_speech_errors(words) if st["fillers"].get("speech_errors", True) else []
        taken = {c["word"] for c in extra}
        for f in [x for x in find_fillers(words, st["fillers"]) if x["word"] not in taken] + extra:
            snapped = seams.snap_cut(f["s"], f["e"]) if seams is not None else (f["s"], f["e"])
            if snapped is None:
                continue  # cortar aqui deixaria a fala "picotada": melhor manter a palavra
            add(snapped[0], snapped[1], f["type"], {"word": f["word"], "label": f["label"]})
    ducks = []
    if st["breath"]["enabled"]:
        for s, e in an.get("breaths", []):
            if st["breath"]["mode"] == "cut":
                add(s, e, "respiracao")
            else:
                cid = f"respiracao-{int(round(s * 100))}"
                ducks.append({"id": cid, "s": s, "e": e, "db": -abs(st["breath"]["reduce_db"]),
                              "active": cid not in restored})
    if st["fillers"].get("ai_cleanup", True):
        for c in project.get("ai_cuts") or []:
            sn = seams.snap_cut(c["s"], c["e"], wide=True) if seams is not None else (c["s"], c["e"])
            if sn is None:
                continue
            add(sn[0], sn[1], "ia", {"label": c.get("label", ""), "reason": c.get("reason", ""), "word": c.get("word")})
    for m in ov.get("manual", []):
        sn = seams.snap_cut(m["s"], m["e"], wide=True) if seams is not None else None
        a, b = sn if sn else (m["s"], m["e"])
        add(a, b, "manual")
        cuts[-1]["id"] = m["id"]
        cuts[-1]["active"] = m["id"] not in restored

    active = merge_intervals([[c["s"], c["e"]] for c in cuts if c["active"]], gap=0.08)
    keeps = []
    t = 0.0
    for s, e in active:
        if s - t >= 0.1:
            keeps.append([round(t, 3), round(s, 3)])
        t = max(t, e)
    if dur - t >= 0.1:
        keeps.append([round(t, 3), round(dur, 3)])
    if not keeps and dur > 0:
        keeps = [[0.0, round(dur, 3)]]
    keeps = remove_islands(keeps, seams)

    # Atenuações só valem dentro do que foi mantido
    act_ducks = []
    for d in ducks:
        if d["active"] and not any(s <= d["s"] and d["e"] <= e for s, e in active):
            act_ducks.append([d["s"], d["e"], d["db"]])

    new_dur = sum(e - s for s, e in keeps)
    removed = {}
    for c in cuts:
        if c["active"]:
            removed[c["type"]] = removed.get(c["type"], 0) + 1
    return {
        "cuts": sorted(cuts, key=lambda c: c["s"]),
        "ducks": ducks,
        "active_ducks": act_ducks,
        "keeps": keeps,
        "stats": {"original": round(dur, 2), "final": round(new_dur, 2), "removed_s": round(dur - new_dur, 2),
                  "counts": removed, "breaths": len([d for d in ducks if d["active"]])},
    }


def intersect(keeps: list[list[float]], segments: list[list[float]]) -> list[list[float]]:
    """Partes mantidas (após cortes) dentro de cada trecho, preservando a ordem dos trechos."""
    out = []
    for a, b in segments:
        for s, e in keeps:
            if e <= a or s >= b:
                continue
            x, y = max(s, a), min(e, b)
            if y - x > 0.05:
                out.append([round(x, 3), round(y, 3)])
    return out


def snap_keeps(keeps: list[list[float]], fps: float) -> list[list[float]]:
    """Alinha cortes à grade de quadros para áudio e vídeo terminarem exatamente juntos."""
    out = []
    for s, e in keeps:
        fs, fe = round(s * fps), round(e * fps)
        if fe > fs:
            out.append([fs / fps, fe / fps])
    return out


class TimeMap:
    """Converte tempo original → tempo no vídeo final. Aceita trechos em qualquer ordem (montagens/resumos)."""

    def __init__(self, keeps: list[list[float]]):
        self.keeps = keeps
        acc, items = 0.0, []
        for s, e in keeps:
            items.append((s, e, acc))
            acc += e - s
        self.total = acc
        self.items = sorted(items)
        self.starts = [i[0] for i in self.items]

    def find(self, t: float):
        i = bisect.bisect_right(self.starts, t) - 1
        if i < 0:
            return None
        s, e, off = self.items[i]
        return (s, e, off) if t <= e else None

    def to_out(self, t: float):
        seg = self.find(t)
        return None if seg is None else seg[2] + (t - seg[0])

    def clamp_in(self, t: float, seg) -> float:
        s, e, off = seg
        return off + (min(max(t, s), e) - s)

    def boundaries(self) -> list[float]:
        """Tempos (na saída) onde cada trecho começa."""
        acc, out = 0.0, []
        for s, e in self.keeps:
            out.append(acc)
            acc += e - s
        return out

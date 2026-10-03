"""Monta a lista de cortes e atenuações a partir da análise + configurações, e o mapa de tempo resultante."""
from __future__ import annotations

import bisect
import re

DEFAULT_SETTINGS = {
    "silence": {"enabled": True, "auto": True, "threshold_db": -40.0, "min_dur": 0.6, "pad": 0.15},
    "breath": {"enabled": True, "mode": "attenuate", "reduce_db": 18.0},
    "fillers": {"enabled": True, "words": ["é", "éé", "ééé", "hã", "hum", "humm", "hmm", "ahn", "ah", "eh", "uh", "um"],
                "repetitions": True},
    "subtitles": {"enabled": True, "style": "destaque", "max_chars": 32, "lines": 2, "uppercase": False,
                  "font": "Arial", "color": "#FFFFFF", "highlight": "#FFD400", "position": "baixo"},
    "audio": {"normalize": True, "target_lufs": -14.0},
    "render": {"quality": "alta"},
    "clips": {"min": 30, "max": 60, "count": 5},
}

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


def merge_intervals(iv: list[list[float]], gap: float = 0.0) -> list[list[float]]:
    out: list[list[float]] = []
    for s, e in sorted(iv):
        if out and s <= out[-1][1] + gap:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def build_edit(project: dict) -> dict:
    """Calcula cortes (com id estável), atenuações, trechos mantidos e estatísticas."""
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

    if st["silence"]["enabled"]:
        for s, e in an.get("silences", []):
            add(s, e, "silencio")
    if st["fillers"]["enabled"]:
        for f in find_fillers(words, st["fillers"]):
            add(f["s"], f["e"], f["type"], {"word": f["word"], "label": f["label"]})
    ducks = []
    if st["breath"]["enabled"]:
        for s, e in an.get("breaths", []):
            if st["breath"]["mode"] == "cut":
                add(s, e, "respiracao")
            else:
                cid = f"respiracao-{int(round(s * 100))}"
                ducks.append({"id": cid, "s": s, "e": e, "db": -abs(st["breath"]["reduce_db"]),
                              "active": cid not in restored})
    for m in ov.get("manual", []):
        add(m["s"], m["e"], "manual")
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


def snap_keeps(keeps: list[list[float]], fps: float) -> list[list[float]]:
    """Alinha cortes à grade de quadros para áudio e vídeo terminarem exatamente juntos."""
    out = []
    for s, e in keeps:
        fs, fe = round(s * fps), round(e * fps)
        if fe > fs:
            out.append([fs / fps, fe / fps])
    return out


class TimeMap:
    """Converte tempo original → tempo no vídeo editado."""

    def __init__(self, keeps: list[list[float]]):
        self.keeps = keeps
        self.starts = [k[0] for k in keeps]
        self.offsets = []
        acc = 0.0
        for s, e in keeps:
            self.offsets.append(acc)
            acc += e - s
        self.total = acc

    def to_out(self, t: float):
        i = bisect.bisect_right(self.starts, t) - 1
        if i < 0:
            return None
        s, e = self.keeps[i]
        if t > e:
            return None
        return self.offsets[i] + (t - s)

    def clamp_out(self, t: float) -> float:
        i = bisect.bisect_right(self.starts, t) - 1
        if i < 0:
            return 0.0
        s, e = self.keeps[i]
        return self.offsets[i] + (min(t, e) - s)

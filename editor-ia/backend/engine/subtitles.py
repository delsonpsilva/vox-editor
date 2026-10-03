"""Legendas: agrupa palavras em blocos legíveis e gera SRT (edição) e ASS (queimar no vídeo, com destaque por palavra)."""
from __future__ import annotations

from .edits import TimeMap


def build_captions(words: list[dict], tmap: TimeMap | None, cfg: dict,
                   window: tuple[float, float] | None = None) -> list[dict]:
    """Retorna blocos [{s, e, lines:[[{w,s,e}]]}] no tempo de SAÍDA."""
    max_chars = int(cfg.get("max_chars", 32))
    n_lines = int(cfg.get("lines", 2))
    upper = bool(cfg.get("uppercase"))
    out_words = []
    for w in words:
        mid = (w["s"] + w["e"]) / 2
        if window and not (window[0] <= mid <= window[1]):
            continue
        if tmap:
            if tmap.to_out(mid) is None:
                continue
            s, e = tmap.clamp_out(w["s"]), tmap.clamp_out(w["e"])
        else:
            off = window[0] if window else 0.0
            s, e = w["s"] - off, w["e"] - off
        text = w["w"].strip()
        if not text:
            continue
        out_words.append({"w": text.upper() if upper else text, "s": max(0.0, s), "e": max(s + 0.04, e)})

    blocks, cur = [], []
    limit = max_chars * n_lines

    def flush():
        if cur:
            blocks.append(list(cur))
            cur.clear()

    for w in out_words:
        if cur:
            chars = sum(len(x["w"]) + 1 for x in cur) + len(w["w"])
            gap = w["s"] - cur[-1]["e"]
            dur = w["e"] - cur[0]["s"]
            ends_sentence = cur[-1]["w"][-1:] in ".?!…"
            if chars > limit or gap > 0.7 or dur > 4.0 or (ends_sentence and len(cur) >= 3):
                flush()
        cur.append(w)
    flush()

    caps = []
    for i, b in enumerate(blocks):
        e = b[-1]["e"] + 0.25
        if i + 1 < len(blocks):
            e = min(e, blocks[i + 1][0]["s"] - 0.01)
        caps.append({"s": b[0]["s"], "e": max(e, b[-1]["e"]), "lines": _split_lines(b, max_chars, n_lines)})
    return caps


def _split_lines(block: list[dict], max_chars: int, n_lines: int) -> list[list[dict]]:
    text_len = sum(len(w["w"]) + 1 for w in block)
    if n_lines < 2 or text_len <= max_chars:
        return [block]
    # Quebra equilibrada: escolhe o ponto que deixa as duas linhas com tamanho mais parecido
    best, best_i = 1e9, 1
    acc = 0
    for i in range(1, len(block)):
        acc += len(block[i - 1]["w"]) + 1
        diff = abs(acc - (text_len - acc))
        if diff < best:
            best, best_i = diff, i
    return [block[:best_i], block[best_i:]]


def _ts_srt(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(caps: list[dict]) -> str:
    out = []
    for i, c in enumerate(caps, 1):
        text = "\n".join(" ".join(w["w"] for w in line) for line in c["lines"])
        out.append(f"{i}\n{_ts_srt(c['s'])} --> {_ts_srt(c['e'])}\n{text}\n")
    return "\n".join(out)


def _ts_ass(t: float) -> str:
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_color(hexc: str, alpha: int = 0) -> str:
    hexc = (hexc or "#FFFFFF").lstrip("#")
    if len(hexc) != 6:
        hexc = "FFFFFF"
    r, g, b = hexc[0:2], hexc[2:4], hexc[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _esc(t: str) -> str:
    return t.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def to_ass(caps: list[dict], cfg: dict, width: int, height: int) -> str:
    style = cfg.get("style", "destaque")
    vertical = height > width
    size = int(min(width, height) * (0.075 if vertical else 0.058))
    font = cfg.get("font") or "Arial"
    base = _ass_color(cfg.get("color", "#FFFFFF"))
    hl = _ass_color(cfg.get("highlight", "#FFD400"))
    pos = cfg.get("position", "baixo")
    align = 5 if pos == "meio" else 8 if pos == "topo" else 2
    margin_v = int(height * (0.22 if vertical else 0.07)) if align != 5 else 0
    border_style, outline, shadow, back = 1, max(2, size // 14), max(1, size // 30), "&H80000000"
    if style == "caixa":
        border_style, outline, shadow, back = 3, max(6, size // 6), 0, "&H64000000"
    primary, secondary = (hl, base) if style == "destaque" else (base, base)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{size},{primary},{secondary},&H00000000,{back},-1,0,0,0,100,100,0,0,{border_style},{outline},{shadow},{align},{int(width * 0.06)},{int(width * 0.06)},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for c in caps:
        parts = []
        cursor = c["s"]
        for li, line in enumerate(c["lines"]):
            words_txt = []
            for w in line:
                if style == "destaque":
                    lead = max(0, int(round((w["s"] - cursor) * 100)))
                    dur = max(1, int(round((w["e"] - w["s"]) * 100)))
                    if lead:
                        words_txt.append(f"{{\\k{lead}}}")
                    words_txt.append(f"{{\\kf{dur}}}{_esc(w['w'])} ")
                    cursor = w["e"]
                else:
                    words_txt.append(_esc(w["w"]) + " ")
            parts.append("".join(words_txt).rstrip())
        text = "\\N".join(parts)
        lines.append(f"Dialogue: 0,{_ts_ass(c['s'])},{_ts_ass(c['e'])},Default,,0,0,0,,{text}")
    return header + "\n".join(lines) + "\n"

"""Legendas: agrupa palavras em blocos e gera SRT e ASS com estilos animados (destaque, palavra em foco, caixa…)."""
from __future__ import annotations

from .edits import TimeMap

FONTS = ["Poppins ExtraBold", "Poppins", "Anton", "Bebas Neue", "Archivo Black", "Arial"]

# Estilos prontos. Ao escolher um estilo, o painel aplica estes padrões (o usuário pode ajustar depois).
STYLES = {
    "palavra_ativa": {"name": "Palavra em foco", "desc": "A palavra falada cresce e muda de cor. O mais usado em Reels.",
                      "font": "Poppins ExtraBold", "uppercase": True, "max_chars": 18, "lines": 2,
                      "color": "#FFFFFF", "highlight": "#FFD400", "position": "baixo"},
    "caixa_ativa": {"name": "Caixa na palavra", "desc": "Uma caixa colorida acompanha a palavra falada.",
                    "font": "Poppins ExtraBold", "uppercase": True, "max_chars": 18, "lines": 2,
                    "color": "#FFFFFF", "highlight": "#FF8A3D", "position": "baixo"},
    "destaque": {"name": "Karaokê", "desc": "As palavras vão sendo pintadas conforme a fala.",
                 "font": "Poppins ExtraBold", "uppercase": False, "max_chars": 26, "lines": 2,
                 "color": "#FFFFFF", "highlight": "#FFD400", "position": "baixo"},
    "uma_palavra": {"name": "Uma palavra por vez", "desc": "Palavras grandes, uma de cada vez, com efeito de pulo.",
                    "font": "Anton", "uppercase": True, "max_chars": 1, "lines": 1,
                    "color": "#FFFFFF", "highlight": "#FFD400", "position": "meio"},
    "impacto": {"name": "Impacto", "desc": "Letras altas e condensadas, contorno grosso. Forte e direto.",
                "font": "Bebas Neue", "uppercase": True, "max_chars": 16, "lines": 2,
                "color": "#FFFFFF", "highlight": "#39E75F", "position": "baixo"},
    "neon": {"name": "Neon", "desc": "Brilho colorido em volta das letras. Bom em fundos escuros.",
             "font": "Poppins ExtraBold", "uppercase": True, "max_chars": 18, "lines": 2,
             "color": "#FFFFFF", "highlight": "#2EE6FF", "position": "baixo"},
    "caixa": {"name": "Faixa de fundo", "desc": "Texto sobre uma faixa escura. Leitura fácil em qualquer imagem.",
              "font": "Poppins", "uppercase": False, "max_chars": 30, "lines": 2,
              "color": "#FFFFFF", "highlight": "#FFFFFF", "position": "baixo"},
    "classico": {"name": "Clássica", "desc": "Branca com contorno, estilo de filme. Discreta e elegante.",
                 "font": "Poppins", "uppercase": False, "max_chars": 34, "lines": 2,
                 "color": "#FFFFFF", "highlight": "#FFFFFF", "position": "baixo"},
    "minimalista": {"name": "Minimalista", "desc": "Pequena, com sombra suave. Para vídeos mais sóbrios.",
                    "font": "Poppins", "uppercase": False, "max_chars": 34, "lines": 2,
                    "color": "#FFFFFF", "highlight": "#FFFFFF", "position": "baixo"},
}
PER_WORD = {"palavra_ativa", "caixa_ativa", "neon"}


def build_captions(words: list[dict], tmap: TimeMap | None, cfg: dict,
                   window: tuple[float, float] | None = None) -> list[dict]:
    """Retorna blocos [{s, e, lines:[[{w,s,e}]]}] no tempo de SAÍDA."""
    style = cfg.get("style", "palavra_ativa")
    max_chars = int(cfg.get("max_chars") or 26)
    n_lines = int(cfg.get("lines") or 2)
    if style == "uma_palavra":
        max_chars, n_lines = 1, 1
    upper = bool(cfg.get("uppercase"))
    out_words = []
    for w in words:
        mid = (w["s"] + w["e"]) / 2
        if window and not (window[0] <= mid <= window[1]):
            continue
        if tmap:
            seg = tmap.find(mid)
            if seg is None:
                continue
            s, e = tmap.clamp_in(w["s"], seg), tmap.clamp_in(w["e"], seg)
        else:
            off = window[0] if window else 0.0
            s, e = w["s"] - off, w["e"] - off
        text = w["w"].strip()
        if not text:
            continue
        out_words.append({"w": text.upper() if upper else text, "s": max(0.0, s), "e": max(s + 0.04, e)})
    out_words.sort(key=lambda x: x["s"])

    blocks, cur = [], []
    limit = max_chars * n_lines

    for w in out_words:
        if cur:
            chars = sum(len(x["w"]) + 1 for x in cur) + len(w["w"])
            gap = w["s"] - cur[-1]["e"]
            dur = w["e"] - cur[0]["s"]
            ends_sentence = cur[-1]["w"][-1:] in ".?!…"
            if chars > limit or gap > 0.7 or dur > 4.0 or (ends_sentence and len(cur) >= 3):
                blocks.append(cur)
                cur = []
        cur.append(w)
    if cur:
        blocks.append(cur)

    caps = []
    for i, b in enumerate(blocks):
        e = b[-1]["e"] + (0.12 if style == "uma_palavra" else 0.25)
        if i + 1 < len(blocks):
            e = min(e, blocks[i + 1][0]["s"] - 0.01)
        caps.append({"s": b[0]["s"], "e": max(e, b[-1]["e"]), "lines": _split_lines(b, max_chars, n_lines)})
    return caps


def _split_lines(block: list[dict], max_chars: int, n_lines: int) -> list[list[dict]]:
    text_len = sum(len(w["w"]) + 1 for w in block)
    if n_lines < 2 or text_len <= max_chars or len(block) < 2:
        return [block]
    best, best_i, acc = 1e9, 1, 0
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
    cs = int(round(max(0.0, t) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _c(hexc: str) -> str:
    """#RRGGBB → &HBBGGRR& (cor ASS, sem alfa)."""
    hexc = (hexc or "#FFFFFF").lstrip("#")
    if len(hexc) != 6:
        hexc = "FFFFFF"
    return f"&H{hexc[4:6]}{hexc[2:4]}{hexc[0:2]}&".upper()


def _style_color(hexc: str, alpha: int = 0) -> str:
    c = _c(hexc)[2:-1]
    return f"&H{alpha:02X}{c}"


def _esc(t: str) -> str:
    return t.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def _wrap_title(text: str, width: int = 22) -> str:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    if len(lines) > 3:  # nunca corta palavra: encerra na 3ª linha com reticências
        lines = lines[:3]
        lines[2] = lines[2].rstrip(".,;:") + "…"
    return "\\N".join(_esc(x) for x in lines)


def to_ass(caps: list[dict], cfg: dict, width: int, height: int, title: str | None = None,
           title_mode: str = "nao", total: float = 0.0, frame: dict | None = None) -> str:
    """frame = {"styles": [...], "events": [...], "sub_pos": (x, y) | None, "band_title": bool} (molduras)."""
    frame = frame or {}
    style = cfg.get("style", "palavra_ativa")
    if style not in STYLES:
        style = "palavra_ativa"
    vertical = height > width
    base = min(width, height)
    factor = {"uma_palavra": 0.13, "impacto": 0.095, "minimalista": 0.05, "caixa": 0.056,
              "classico": 0.056}.get(style, 0.066)
    if not vertical:
        factor *= 0.78
    pct = cfg.get("size_pct")
    if pct is None:  # configurações antigas: P / M / G
        pct = {"p": 82, "m": 100, "g": 120}.get(cfg.get("size", "m"), 100)
    factor *= max(40, min(180, float(pct))) / 100
    size = int(base * factor)
    font = cfg.get("font") or STYLES[style]["font"]
    col, hl = cfg.get("color", "#FFFFFF"), cfg.get("highlight", "#FFD400")
    pos = cfg.get("position", "baixo")
    align = 5 if pos == "meio" else 8 if pos == "topo" else 2
    if align == 2:
        margin_v = int(height * (0.2 if vertical else 0.08))
    elif align == 8:
        margin_v = int(height * (0.2 if vertical else 0.08))
    else:
        margin_v = 0
    ml = int(width * 0.07)

    outline, shadow, border, back, outc = max(3, size // 12), max(2, size // 28), 1, "&H90000000", "&H00000000"
    if style == "caixa":
        border, outline, shadow, back, outc = 3, max(8, size // 4), 0, "&H40000000", "&H40000000"
    elif style == "minimalista":
        outline, shadow, back = 0, max(2, size // 14), "&H70000000"
    elif style == "impacto":
        outline = max(5, size // 9)
    elif style == "neon":
        outline, shadow, outc = max(3, size // 14), 0, _style_color(hl)
    elif style == "uma_palavra":
        outline = max(5, size // 11)
    primary, secondary = _style_color(col), _style_color(col)
    if style == "destaque":
        primary, secondary = _style_color(hl), _style_color(col)
    box_pad = max(8, size // 7)
    title_size = int(base * (0.062 if vertical else 0.048))

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{size},{primary},{secondary},{outc},{back},0,0,0,0,100,100,{1 if style == "impacto" else 0},0,{border},{outline},{shadow},{align},{ml},{ml},{margin_v},1
Style: Box,{font},{size},{_style_color(col)},{_style_color(col)},{_style_color(hl)},&H00000000,0,0,0,0,100,100,0,0,3,{box_pad},0,{align},{ml},{ml},{margin_v},1
Style: Title,{font},{title_size},&H00111111,&H00111111,{_style_color(hl)},&H00000000,0,0,0,0,100,100,0,0,3,{max(10, title_size // 3)},0,8,{ml},{ml},{int(height * (0.105 if vertical else 0.06))},1
{chr(10).join(frame.get("styles", []))}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = list(frame.get("events", []))
    sub_pos = frame.get("sub_pos")
    # altura personalizada (0 = bem embaixo, 100 = no topo): vale quando a moldura não tem faixa própria de legenda
    y_pct = cfg.get("y_pct")
    if not sub_pos and y_pct is not None:
        y = height * (1 - (0.08 + 0.84 * max(0.0, min(100.0, float(y_pct))) / 100))
        sub_pos = (width // 2, int(y))
    elif sub_pos and cfg.get("band_offset"):
        sub_pos = (sub_pos[0], int(sub_pos[1] + float(cfg["band_offset"]) * height / 1920))
    pos_tag = f"\\an5\\pos({sub_pos[0]},{sub_pos[1]})" if sub_pos else ""
    hlc = _c(hl)
    blur = "\\blur6" if style == "neon" else ""

    def line_text(c, active=None, mode=""):
        """Monta o texto do bloco. active = índice global da palavra falada."""
        parts, idx = [], 0
        for line in c["lines"]:
            ws = []
            for w in line:
                t = _esc(w["w"])
                if active is None:
                    ws.append(t)
                elif mode == "palavra_ativa":
                    ws.append(f"{{\\c{hlc}\\fscx112\\fscy112}}{t}{{\\r}}" if idx == active else t)
                elif mode == "neon":
                    ws.append(f"{{\\c{hlc}\\blur10}}{t}{{\\r\\blur6}}" if idx == active else t)
                elif mode == "box_front":  # palavra ativa visível, demais invisíveis (camada da caixa)
                    ws.append(f"{{\\alpha&H00&}}{t}{{\\alpha&HFF&}}" if idx == active else t)
                elif mode == "box_back":  # demais visíveis, palavra ativa invisível
                    ws.append(f"{{\\alpha&HFF&}}{t}{{\\alpha&H00&\\4a&H90&}}" if idx == active else t)
                idx += 1
            parts.append(" ".join(ws))
        return "\\N".join(parts)

    for c in caps:
        flat = [w for line in c["lines"] for w in line]
        if style in PER_WORD:
            for i, w in enumerate(flat):
                s = c["s"] if i == 0 else w["s"]
                e = flat[i + 1]["s"] if i + 1 < len(flat) else c["e"]
                if e - s < 0.02:
                    continue
                if style == "caixa_ativa":
                    ev.append(f"Dialogue: 1,{_ts_ass(s)},{_ts_ass(e)},Box,,0,0,0,,{{\\alpha&HFF&}}{line_text(c, i, 'box_front')}")
                    ev.append(f"Dialogue: 0,{_ts_ass(s)},{_ts_ass(e)},Default,,0,0,0,,{line_text(c, i, 'box_back')}")
                else:
                    pre = f"{{{blur}}}" if blur else ""
                    ev.append(f"Dialogue: 0,{_ts_ass(s)},{_ts_ass(e)},Default,,0,0,0,,{pre}{line_text(c, i, style)}")
        elif style == "destaque":
            cursor, parts = c["s"], []
            for line in c["lines"]:
                ws = []
                for w in line:
                    lead = max(0, int(round((w["s"] - cursor) * 100)))
                    dur = max(1, int(round((w["e"] - w["s"]) * 100)))
                    ws.append((f"{{\\k{lead}}}" if lead else "") + f"{{\\kf{dur}}}{_esc(w['w'])} ")
                    cursor = w["e"]
                parts.append("".join(ws).rstrip())
            ev.append(f"Dialogue: 0,{_ts_ass(c['s'])},{_ts_ass(c['e'])},Default,,0,0,0,," + "\\N".join(parts))
        elif style == "uma_palavra":
            w = flat[0]
            strong = len(w["w"].strip(".,!?…")) >= 6
            color = f"\\c{hlc}" if strong else ""
            ev.append(f"Dialogue: 0,{_ts_ass(c['s'])},{_ts_ass(c['e'])},Default,,0,0,0,,"
                      f"{{{color}\\fscx70\\fscy70\\t(0,90,\\fscx108\\fscy108)\\t(90,170,\\fscx100\\fscy100)}}{_esc(w['w'])}")
        else:
            fade = "{\\fad(60,60)}" if style in ("minimalista", "classico") else ""
            ev.append(f"Dialogue: 0,{_ts_ass(c['s'])},{_ts_ass(c['e'])},Default,,0,0,0,,{fade}{line_text(c)}")

    if pos_tag:
        n0 = len(frame.get("events", []))
        for i in range(n0, len(ev)):
            head, sep, txt = ev[i].partition(",,0,0,0,,")
            ev[i] = head + sep + "{" + pos_tag + "}" + txt
    if title and title_mode in ("inicio", "fixo") and not frame.get("band_title"):
        end = total if title_mode == "fixo" and total > 0 else min(4.0, total or 4.0)
        ev.append(f"Dialogue: 2,{_ts_ass(0)},{_ts_ass(end)},Title,,0,0,0,,{{\\fad(150,200)}}{_wrap_title(title)}")
    return header + "\n".join(ev) + "\n"

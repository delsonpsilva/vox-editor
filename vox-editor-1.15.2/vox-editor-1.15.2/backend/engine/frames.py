"""Molduras (templates) para Reels/Shorts/Status: tarja de título, selo chamativo, faixa de legenda,
@perfil, logo e barra de progresso. Tudo desenhado em ASS (libass), o mesmo motor das legendas."""
from __future__ import annotations

LAYOUTS = {
    "cheia": {"name": "Tela cheia", "desc": "Vídeo na tela toda, com o título flutuando no topo."},
    "faixa_topo": {"name": "Tarja no topo", "desc": "Faixa colorida em cima com selo e título. Chama atenção sem esconder o vídeo."},
    "moldura": {"name": "Moldura podcast", "desc": "Título em cima, vídeo no meio e a legenda numa faixa embaixo. Perde menos qualidade."},
    "rodape": {"name": "Rodapé", "desc": "Vídeo em tela cheia com uma faixa embaixo onde a legenda passa por dentro."},
    "cartao": {"name": "Cartão", "desc": "Vídeo em destaque sobre o próprio fundo desfocado, título em cima e legenda embaixo."},
}

VERSION = 5  # muda quando o desenho das molduras muda (renova o cache das prévias)

DEFAULT_BRAND = {"handle": "", "kicker": "", "color": "#FF8A3D", "text": "#FFFFFF", "bg": "#101114",
                 "progress": True, "logo": "", "logo_pos": "auto", "logo_size": "m", "logo_opacity": 1.0,
                 "socials": {}, "social_mode": "destino", "social_every": 12, "social_side": "direita"}


def geometry(layout: str, W: int, H: int) -> dict:
    """Áreas da moldura em pixels do quadro final (W×H)."""
    g = {"layout": layout, "canvas": (W, H), "box": (0, 0, W, H), "bg": "none", "bands": [], "title": None,
         "kicker": None, "sub": None, "handle": (W // 2, int(H * 0.962)), "progress": (H - 12, 12),
         "logo": None, "outline": None}
    if W >= H or layout not in LAYOUTS or layout == "cheia":
        g["layout"] = "cheia"
        g["logo"] = (int(W * 0.04), int(H * 0.035), int(H * 0.05))
        if H > W:
            g["kicker"] = (W // 2, int(H * 0.066))
        return g
    if layout == "faixa_topo":
        g.update(box=(0, 440, W, H - 440), bg="color", bands=[(0, 0, W, 440, "color", 0)],
                 kicker=(W // 2, 88), title=(W // 2, 252, W - 120, 262, "text"), handle=(W // 2, 414),
                 logo=(40, 30, 90))
    elif layout == "moldura":
        g.update(box=(0, 560, W, 800), bg="color", bands=[(0, 0, W, 560, "bg", 0), (0, 1360, W, 560, "bg", 0),
                                                         (W // 2 - 70, 486, 140, 8, "color", 0)],
                 kicker=(W // 2, 110), title=(W // 2, 300, W - 120, 330, "text"), sub=(W // 2, 1580),
                 handle=(W // 2, 1830), progress=(1360, 10), logo=(40, 40, 96))
    elif layout == "rodape":
        g.update(bands=[(0, 1390, W, 530, "bg", 0x38)], sub=(W // 2, 1580), handle=(W // 2, 1838),
                 kicker=(W // 2, int(H * 0.066)), title=None, logo=(40, 40, 96))
    elif layout == "cartao":
        g.update(box=(60, 520, W - 120, 900), bg="blur", kicker=(W // 2, 150),
                 title=(W // 2, 340, W - 120, 300, "text"), sub=(W // 2, 1640), handle=(W // 2, 1838),
                 outline=(60, 520, W - 120, 900), logo=(40, 40, 96))
    return g


def _c(hexc: str) -> str:
    hexc = (hexc or "#FFFFFF").lstrip("#")
    if len(hexc) != 6:
        hexc = "FFFFFF"
    return f"&H{hexc[4:6]}{hexc[2:4]}{hexc[0:2]}&".upper()


def _sc(hexc: str, alpha: int = 0) -> str:
    return f"&H{alpha:02X}{_c(hexc)[2:-1]}"


def _esc(t: str) -> str:
    return t.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def _ts(t: float) -> str:
    cs = int(round(max(0.0, t) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _wrap(text: str, width: int, max_lines: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(".,;:") + "…"
    return lines


def _rect(x, y, w, h, color, alpha=0, layer=0, start=0.0, end=0.0) -> str:
    return (f"Dialogue: {layer},{_ts(start)},{_ts(end)},Draw,,0,0,0,,"
            f"{{\\an7\\pos({x},{y})\\1c{_c(color)}\\1a&H{alpha:02X}&\\bord0\\shad0\\p1}}m 0 0 l {w} 0 {w} {h} 0 {h}{{\\p0}}")


def _highlight(lines: list[str], color_tag: str, base_tag: str) -> list[str]:
    """Pinta a palavra mais forte (a mais longa) do título com a cor de destaque."""
    words = [w for ln in lines for w in ln.split()]
    if not words:
        return lines
    key = max(words, key=lambda w: len(w.strip(".,!?…:;")))
    done, out = False, []
    for ln in lines:
        parts = []
        for w in ln.split():
            if not done and w == key:
                parts.append(f"{{\\c{color_tag}}}{_esc(w)}{{\\c{base_tag}}}")
                done = True
            else:
                parts.append(_esc(w))
        out.append(" ".join(parts))
    return out


def overlay(g: dict, brand: dict, title: str, kicker: str, total: float, font: str,
            title_mode: str = "inicio", cover: bool = False) -> tuple[list[str], list[str]]:
    """Retorna (estilos, eventos) ASS da moldura. cover=True: versão capa (título grande, sem barra)."""
    W, H = g["canvas"]
    b = {**DEFAULT_BRAND, **(brand or {})}
    end = max(total, 0.5)
    col = {"color": b["color"], "bg": b["bg"], "text": b["text"]}
    vertical = H > W
    base = min(W, H)
    styles = [
        f"Style: Draw,Arial,10,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1",
        f"Style: Kicker,{font},{int(base * 0.042)},{_sc('#111111' if g['layout'] != 'faixa_topo' else b['text'])},&H00000000,"
        f"{_sc(b['color'] if g['layout'] != 'faixa_topo' else b['bg'])},&H00000000,0,0,0,0,100,100,2,0,3,{int(base * 0.016)},0,5,0,0,0,1",
        f"Style: Handle,{font},{int(base * 0.034)},{_sc(b['text'], 0x30)},&H00000000,&H90000000,&H00000000,0,0,0,0,100,100,1,0,1,2,0,5,0,0,0,1",
        f"Style: BandTitle,{font},{int(base * 0.07)},{_sc(b['text'])},&H00000000,&H80000000,&H00000000,0,0,0,0,100,100,0,0,1,"
        f"{0 if g['bg'] != 'blur' else 3},{0 if g['bg'] != 'blur' else 2},5,0,0,0,1",
    ]
    ev = []
    for (x, y, w, h, key, alpha) in g["bands"]:
        ev.append(_rect(x, y, w, h, col[key], alpha, 0, 0, end))
    if g.get("outline"):
        x, y, w, h = g["outline"]
        t = 6
        for rx, ry, rw, rh in ((x - t, y - t, w + 2 * t, t), (x - t, y + h, w + 2 * t, t), (x - t, y, t, h), (x + w, y, t, h)):
            ev.append(_rect(rx, ry, rw, rh, "#FFFFFF", 0x10, 1, 0, end))
    styles.append(f"Style: Cover,Anton,{int(base * 0.13)},{_sc('#FFFFFF')},&H00000000,&H00000000,&H90000000,0,0,0,0,"
                  f"100,100,1,0,1,{int(base * 0.007)},{int(base * 0.006)},5,0,0,0,1")
    if cover and title:
        hl = _c("#111111") if g["layout"] == "faixa_topo" else _c(b["color"] if b["color"].upper() != "#FFFFFF" else "#FFD400")
        if g.get("title"):
            cx, cy, tw, th, _ = g["title"]
            sz, top = int(base * 0.095), None
        else:
            cx, cy, tw, sz = W // 2, int(H * 0.66), W - 100, int(base * 0.13)
            top = True
        maxl = 3 if g.get("title") else 4
        for _ in range(8):
            full = _wrap(title.upper(), max(8, int(tw / (sz * 0.47))), 99)
            if len(full) <= maxl and len(full) * sz * 1.05 <= (th if g.get("title") else H * 0.4):
                break
            sz = int(sz * 0.9)
        lines = _wrap(title.upper(), max(8, int(tw / (sz * 0.47))), maxl)
        if top:  # faixa escura atrás do título grande (leitura garantida em qualquer imagem)
            bh = int(len(lines) * sz * 1.08 + sz * 0.8)
            ev.append(_rect(0, cy - bh // 2, W, bh, "#000000", 0x50, 1, 0, end))
            if g.get("kicker"):
                g = {**g, "kicker": (W // 2, cy - bh // 2 - int(base * 0.05))}
        color = _c(b["text"]) if g.get("title") else _c("#FFFFFF")
        txt = "\\N".join(_highlight(lines, hl, color))
        ev.append(f"Dialogue: 2,{_ts(0)},{_ts(end)},Cover,,0,0,0,,{{\\an5\\pos({cx},{cy})\\fs{sz}\\c{color}"
                  f"{'\\bord0\\shad0' if g.get('title') and g['bg'] != 'blur' else ''}}}{txt}")
        title = ""  # já desenhado
        b = {**b, "progress": False}
    # título na tarja (fica o tempo todo)
    if g.get("title") and title:
        cx, cy, tw, th, _ = g["title"]
        size = int(base * 0.07)
        for max_lines, sz in ((3, size), (4, int(size * 0.82))):
            lines = _wrap(title, max(12, int(tw / (sz * 0.56))), max_lines)
            if len(lines) <= 3 or max_lines == 4:
                break
        txt = "\\N".join(_esc(x) for x in lines)
        ev.append(f"Dialogue: 2,{_ts(0)},{_ts(end)},BandTitle,,0,0,0,,{{\\an5\\pos({cx},{cy})\\fs{sz}\\fad(200,0)}}{txt}")
    # selo chamativo
    if g.get("kicker") and kicker:
        kx, ky = g["kicker"]
        k = _esc(kicker.upper()[:34])
        if g["layout"] in ("cheia", "rodape"):
            k_end = end if title_mode == "fixo" else min(end, 4.0)
            ev.append(f"Dialogue: 3,{_ts(0)},{_ts(k_end)},Kicker,,0,0,0,,{{\\an5\\pos({kx},{ky})\\fad(150,200)}}{k}")
        else:
            ev.append(f"Dialogue: 3,{_ts(0)},{_ts(end)},Kicker,,0,0,0,,{{\\an5\\pos({kx},{ky})\\fad(200,0)}}{k}")
    # @perfil
    if b.get("handle"):
        hx, hy = g["handle"]
        h = b["handle"].strip()
        if not h.startswith("@") and " " not in h:
            h = "@" + h
        ev.append(f"Dialogue: 3,{_ts(0)},{_ts(end)},Handle,,0,0,0,,{{\\an5\\pos({hx},{hy})}}{_esc(h)}")
    # barra de progresso (mostra que o vídeo é curto e segura a pessoa até o fim)
    if b.get("progress") and vertical:
        py, ph = g["progress"]
        ev.append(_rect(0, py, W, ph, "#FFFFFF", 0xB0, 4, 0, end))
        ev.append(f"Dialogue: 5,{_ts(0)},{_ts(end)},Draw,,0,0,0,,{{\\an7\\pos(0,{py})\\1c{_c(b['color'])}\\bord0\\shad0"
                  f"\\fscx0\\t(0,{int(end * 1000)},\\fscx100)\\p1}}m 0 0 l {W} 0 {W} {ph} 0 {ph}{{\\p0}}")
    return styles, ev

"""Selos das redes sociais (entram e saem com o seu @ e um convite para seguir) e logo pessoal (marca d'água).
O selo usa um ícone genérico de "seguir"; o ícone oficial de cada rede pode ser enviado pelo usuário."""
from __future__ import annotations

from .frames import _c, _esc, _ts

NETS = {
    "instagram": {"name": "Instagram", "cta": "SIGA NO INSTAGRAM", "color": "#E1306C"},
    "tiktok": {"name": "TikTok", "cta": "SIGA NO TIKTOK", "color": "#25F4EE"},
    "youtube": {"name": "YouTube", "cta": "INSCREVA-SE NO YOUTUBE", "color": "#FF3040"},
    "facebook": {"name": "Facebook", "cta": "CURTA NO FACEBOOK", "color": "#3B8CFF"},
    "whatsapp": {"name": "WhatsApp", "cta": "FALE NO WHATSAPP", "color": "#25D366"},
    "site": {"name": "Site", "cta": "ACESSE O SITE", "color": "#FFFFFF"},
}

# rede que combina com cada destino de exportação
PLATFORM_NET = {"tiktok": "tiktok", "ig_reels": "instagram", "ig_stories": "instagram", "yt_shorts": "youtube",
                "horizontal": "youtube", "fb_reels": "facebook", "whatsapp": "whatsapp"}

ENTER = 0.35  # duração da animação de entrada/saída (s)


def enabled(brand: dict) -> list[str]:
    soc = brand.get("socials") or {}
    return [k for k in NETS if (soc.get(k) or {}).get("on") and (soc.get(k) or {}).get("handle", "").strip()]


def schedule(total: float, brand: dict, platform: str | None) -> list[tuple[float, float, str]]:
    """Quando cada selo aparece: [(início, fim, rede)]."""
    mode = brand.get("social_mode", "destino")
    nets = enabled(brand)
    if mode == "off" or not nets or total < 3:
        return []
    if mode == "destino":
        dest = PLATFORM_NET.get(platform or "")
        nets = [dest] if dest in nets else nets[:1]
    every = max(6.0, float(brand.get("social_every") or 12))
    dur = 4.0
    out, t, i = [], 1.5, 0
    while t + dur <= total - 0.4:
        out.append((round(t, 2), round(t + dur, 2), nets[i % len(nets)]))
        t += every
        i += 1
    if not out and total > 3:
        out.append((1.0, round(min(total - 0.3, 5.0), 2), nets[0]))
    return out


def _badge_y(g: dict) -> int:
    W, H = g["canvas"]
    if W >= H:
        return int(H * 0.15)
    return {"faixa_topo": 440 + 110, "moldura": 560 + 82, "cartao": 520 + 82}.get(g["layout"], int(H * 0.30))


def badge_layout(g: dict, brand: dict, net: str) -> dict:
    """Medidas do selo (em px do quadro final)."""
    W, H = g["canvas"]
    k = min(W, H) / 1080
    info = NETS[net]
    soc = (brand.get("socials") or {}).get(net) or {}
    cta = (soc.get("cta") or info["cta"]).upper()[:28]
    handle = soc.get("handle", "").strip()
    if net not in ("whatsapp", "site") and handle and not handle.startswith("@"):
        handle = "@" + handle
    s1, s2 = int(29 * k), int(38 * k)
    icon, pad, gap, ph = int(66 * k), int(18 * k), int(16 * k), int(104 * k)
    tw = max(len(cta) * s1 * 0.6, len(handle) * s2 * 0.56)
    pw = int(pad + icon + gap + tw + pad * 1.6)
    side = brand.get("social_side", "direita")
    xi = int(W - 36 * k - pw) if side != "esquerda" else int(36 * k)
    xo = int(W + 20 * k) if side != "esquerda" else int(-pw - 20 * k)
    return {"cta": cta, "handle": handle, "s1": s1, "s2": s2, "icon": icon, "pad": pad, "gap": gap, "ph": ph,
            "pw": pw, "xi": xi, "xo": xo, "y": _badge_y(g), "color": info["color"]}


def _rr(w: int, h: int, r: int) -> str:
    """Retângulo de cantos arredondados (desenho ASS)."""
    return (f"m {r} 0 l {w - r} 0 b {w} 0 {w} 0 {w} {r} l {w} {h - r} b {w} {h} {w} {h} {w - r} {h} "
            f"l {r} {h} b 0 {h} 0 {h} 0 {h - r} l 0 {r} b 0 0 0 0 {r} 0")


def _circle(d: int) -> str:
    r = d / 2
    c = r * 0.5523
    return (f"m {r:.0f} 0 b {r + c:.0f} 0 {d} {r - c:.0f} {d} {r:.0f} b {d} {r + c:.0f} {r + c:.0f} {d} {r:.0f} {d} "
            f"b {r - c:.0f} {d} 0 {r + c:.0f} 0 {r:.0f} b 0 {r - c:.0f} {r - c:.0f} 0 {r:.0f} 0")


def badge_events(g: dict, brand: dict, platform: str | None, total: float, font: str,
                 icons: dict | None = None) -> tuple[list[str], list[str]]:
    """Eventos ASS dos selos (fundo, ícone genérico, convite e @)."""
    icons = icons or {}
    styles = [f"Style: SocialA,{font},30,&H00FFFFFF,&H00000000,&H00000000,&H00000000,0,0,0,0,100,100,1,0,1,0,0,4,0,0,0,1",
              f"Style: SocialB,{font},38,&H00FFFFFF,&H00000000,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,4,0,0,0,1"]
    ev = []
    ms = int(ENTER * 1000)
    for a, b, net in schedule(total, brand, platform):
        L = badge_layout(g, brand, net)
        y0 = L["y"] - L["ph"] // 2
        mid = b - ENTER
        elems = [  # (dx, dy, texto/desenho, estilo, layer)
            (0, y0, f"{{\\an7\\1c&H000000&\\1a&H30&\\bord0\\shad0\\p1}}{_rr(L['pw'], L['ph'], L['ph'] // 2)}{{\\p0}}", "Draw", 20),
        ]
        ix, iy = L["pad"], L["y"] - L["icon"] // 2
        if net not in icons:  # ícone genérico de "seguir": círculo com +
            d = L["icon"]
            bar, ln = max(4, d // 11), int(d * 0.46)
            elems.append((ix, iy, f"{{\\an7\\1c{_c(L['color'])}\\bord0\\shad0\\p1}}{_circle(d)}{{\\p0}}", "Draw", 21))
            elems.append((ix + (d - ln) // 2, iy + (d - bar) // 2, f"{{\\an7\\1c&HFFFFFF&\\bord0\\shad0\\p1}}m 0 0 l {ln} 0 {ln} {bar} 0 {bar}{{\\p0}}", "Draw", 22))
            elems.append((ix + (d - bar) // 2, iy + (d - ln) // 2, f"{{\\an7\\1c&HFFFFFF&\\bord0\\shad0\\p1}}m 0 0 l {bar} 0 {bar} {ln} 0 {ln}{{\\p0}}", "Draw", 22))
        tx = L["pad"] + L["icon"] + L["gap"]
        elems.append((tx, L["y"] - int(L["s2"] * 0.55), f"{{\\an4\\fs{L['s1']}\\1c{_c(L['color'] if L['color'] != '#FFFFFF' else brand.get('color', '#FF8A3D'))}}}{_esc(L['cta'])}", "SocialA", 23))
        elems.append((tx, L["y"] + int(L["s2"] * 0.42), f"{{\\an4\\fs{L['s2']}}}{_esc(L['handle'])}", "SocialB", 23))
        for dx, yy, txt, st, layer in elems:
            x_in, x_out = L["xi"] + dx, L["xo"] + dx
            tag = txt[:1] == "{" and txt.index("}")
            head, body = txt[1:tag], txt[tag + 1:]
            ev.append(f"Dialogue: {layer},{_ts(a)},{_ts(mid)},{st},,0,0,0,,{{\\move({x_out},{yy},{x_in},{yy},0,{ms}){head}}}{body}")
            ev.append(f"Dialogue: {layer},{_ts(mid)},{_ts(b)},{st},,0,0,0,,{{\\move({x_in},{yy},{x_out},{yy},0,{ms}){head}}}{body}")
    return styles, ev


def icon_overlays(g: dict, brand: dict, platform: str | None, total: float, icons: dict) -> list[dict]:
    """Ícones oficiais enviados pelo usuário: sobreposições animadas em sincronia com o selo."""
    out = []
    for a, b, net in schedule(total, brand, platform):
        if net not in icons:
            continue
        L = badge_layout(g, brand, net)
        dx = L["pad"]
        xi, xo = L["xi"] + dx, L["xo"] + dx
        y = L["y"] - L["icon"] // 2
        mid = b - ENTER
        x = (f"if(lt(t,{a + ENTER:.3f}),{xo}+({xi}-{xo})*(t-{a:.3f})/{ENTER},"
             f"if(gt(t,{mid:.3f}),{xi}+({xo}-{xi})*(t-{mid:.3f})/{ENTER},{xi}))")
        out.append({"path": icons[net], "x": x, "y": str(y), "h": L["icon"], "opacity": 1.0,
                    "enable": f"between(t,{a:.3f},{b:.3f})"})
    return out


def logo_overlay(g: dict, brand: dict, logo_path: str | None) -> dict | None:
    """Logo pessoal / marca d'água (estilo logo de TV): posição, tamanho e transparência."""
    if not logo_path:
        return None
    W, H = g["canvas"]
    k = min(W, H) / 1080
    size = {"p": 70, "m": 100, "g": 140}.get(brand.get("logo_size", "m"), 100) * k
    pos = brand.get("logo_pos", "auto")
    m = int(36 * k)
    if pos == "auto" and g.get("logo"):
        x, y, h = g["logo"]
        return {"path": logo_path, "x": str(x), "y": str(y), "h": int(size), "opacity": float(brand.get("logo_opacity", 1.0)), "enable": ""}
    bottom = int(H - size - (70 * k if H > W else 40 * k))
    xy = {"sup_esq": (str(m), str(m)), "sup_dir": (f"W-w-{m}", str(m)),
          "inf_esq": (str(m), str(bottom)), "inf_dir": (f"W-w-{m}", str(bottom))}.get(pos, (str(m), str(m)))
    return {"path": logo_path, "x": xy[0], "y": xy[1], "h": int(size), "opacity": float(brand.get("logo_opacity", 1.0)), "enable": ""}

"""Contas compartilhadas da Montagem 1.2: filtros de cor, vinheta, transições e quadros-chave (animação).

A prévia (frontend/montagem.js) faz exatamente as mesmas contas: o que se vê na tela é o que sai no vídeo.
Se mudar alguma fórmula aqui, mude também lá (procure por "efeitos.py" no montagem.js)."""
from __future__ import annotations

import math

# ---------------------------------------------------------------- filtros de cor

FX_PADRAO = {"brilho": 0.0, "contraste": 1.0, "saturacao": 1.0, "temperatura": 0.0, "pb": 0.0, "sepia": 0.0,
             "desfoque": 0.0, "vinheta": 0.0}
FX_LIMITES = {"brilho": (-0.8, 0.8), "contraste": (0.3, 2.0), "saturacao": (0.0, 3.0), "temperatura": (-1.0, 1.0),
              "pb": (0.0, 1.0), "sepia": (0.0, 1.0), "desfoque": (0.0, 1.0), "vinheta": (0.0, 1.0)}

# filtros prontos (os mesmos aparecem na tela, em montagem.js: FILTROS)
FILTROS = {
    "nenhum": {},
    "vivo": {"saturacao": 1.35, "contraste": 1.1},
    "cinema": {"contraste": 1.15, "saturacao": 0.85, "temperatura": -0.15, "vinheta": 0.35},
    "quente": {"temperatura": 0.4, "saturacao": 1.1},
    "frio": {"temperatura": -0.4, "saturacao": 0.95},
    "dourado": {"temperatura": 0.6, "saturacao": 1.2, "contraste": 1.05, "brilho": 0.03},
    "vintage": {"sepia": 0.4, "contraste": 0.92, "brilho": 0.04, "vinheta": 0.4},
    "pb": {"pb": 1.0, "contraste": 1.15},
    "drama": {"contraste": 1.35, "saturacao": 0.7, "brilho": -0.04, "vinheta": 0.5},
    "suave": {"contraste": 0.88, "brilho": 0.06, "saturacao": 0.9},
}


def fx_limpo(fx) -> dict | None:
    """Valida os filtros vindos da tela. Devolve None quando tudo está no padrão (sem filtro)."""
    if not isinstance(fx, dict):
        return None
    out = {}
    for k, padrao in FX_PADRAO.items():
        lo, hi = FX_LIMITES[k]
        try:
            v = float(fx.get(k, padrao))
            v = padrao if math.isnan(v) or math.isinf(v) else max(lo, min(hi, v))
        except (TypeError, ValueError):
            v = padrao
        out[k] = round(v, 4)
    if all(abs(out[k] - FX_PADRAO[k]) < 1e-4 for k in out):
        return None
    if fx.get("preset") in FILTROS:
        out["preset"] = fx["preset"]
    return out


def _mul(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def matriz_cor(fx: dict) -> list[list[float]]:
    """Matriz 3x3 aplicada depois de brilho/contraste: saturação -> preto e branco -> sépia -> temperatura.
    Mesmas fórmulas das funções saturate(), grayscale() e sepia() do CSS."""
    s = fx.get("saturacao", 1.0)
    sat = [[0.213 + 0.787 * s, 0.715 - 0.715 * s, 0.072 - 0.072 * s],
           [0.213 - 0.213 * s, 0.715 + 0.285 * s, 0.072 - 0.072 * s],
           [0.213 - 0.213 * s, 0.715 - 0.715 * s, 0.072 + 0.928 * s]]
    g = 1 - fx.get("pb", 0.0)
    gray = [[0.2126 + 0.7874 * g, 0.7152 - 0.7152 * g, 0.0722 - 0.0722 * g],
            [0.2126 - 0.2126 * g, 0.7152 + 0.2848 * g, 0.0722 - 0.0722 * g],
            [0.2126 - 0.2126 * g, 0.7152 - 0.7152 * g, 0.0722 + 0.9278 * g]]
    p = 1 - fx.get("sepia", 0.0)
    sep = [[0.393 + 0.607 * p, 0.769 - 0.769 * p, 0.189 - 0.189 * p],
           [0.349 - 0.349 * p, 0.686 + 0.314 * p, 0.168 - 0.168 * p],
           [0.272 - 0.272 * p, 0.534 - 0.534 * p, 0.131 + 0.869 * p]]
    t = fx.get("temperatura", 0.0)
    temp = [[1 + 0.15 * t, 0, 0], [0, 1 + 0.03 * t, 0], [0, 0, 1 - 0.15 * t]]
    return _mul(temp, _mul(sep, _mul(gray, sat)))


# vinheta: escurece as bordas. Paradas do degradê (distância normalizada -> força); o canto vale 1.
VINHETA_PARADAS = [(0.0, 0.0), (0.45, 0.0), (0.6, 0.12), (0.75, 0.38), (0.88, 0.7), (1.0, 1.0)]


def desfoque_sigma(fx: dict, W: int, H: int) -> float:
    """Desfoque em pixels do quadro final (o mesmo valor do blur() da prévia, antes da escala da tela)."""
    return fx.get("desfoque", 0.0) * 0.02 * min(W, H)


def filtros_ffmpeg(fx: dict | None, W: int, H: int) -> list[str]:
    """Filtros FFmpeg (em RGBA) para o fx do item. A vinheta é feita à parte (precisa do tamanho do item)."""
    if not fx:
        return []
    f = []
    k, c = 1 + fx.get("brilho", 0.0), fx.get("contraste", 1.0)
    if abs(k - 1) > 1e-4 or abs(c - 1) > 1e-4:
        e = f"clip((clip(val*{k:.4f},0,255)-128)*{c:.4f}+128,0,255)"
        f.append(f"lutrgb=r='{e}':g='{e}':b='{e}'")
    m = matriz_cor(fx)
    ident = all(abs(m[i][j] - (1 if i == j else 0)) < 1e-4 for i in range(3) for j in range(3))
    if not ident:
        nomes = "rgb"
        f.append("colorchannelmixer=" + ":".join(f"{nomes[i]}{nomes[j]}={m[i][j]:.5f}"
                                                  for i in range(3) for j in range(3)))
    sg = desfoque_sigma(fx, W, H)
    if sg > 0.3:
        f.append(f"gblur=sigma={sg:.2f}")
    return f


def vinheta_mascara(w: int, h: int, forca: float):
    """Imagem RGBA (preta, com transparência crescendo para as bordas) do tamanho do item."""
    import numpy as np
    ys, xs = np.mgrid[0:h, 0:w].astype("float32")
    nx = (xs + 0.5 - w / 2) / (w / 2)
    ny = (ys + 0.5 - h / 2) / (h / 2)
    r = np.clip(np.sqrt(nx * nx + ny * ny) / math.sqrt(2), 0, 1)
    xp = [p[0] for p in VINHETA_PARADAS]
    fp = [p[1] for p in VINHETA_PARADAS]
    a = np.interp(r, xp, fp) * forca
    img = np.zeros((h, w, 4), dtype="uint8")
    img[..., 3] = np.clip(a * 255 + 0.5, 0, 255).astype("uint8")
    return img


# ---------------------------------------------------------------- chroma key (fundo verde)

def chroma_limpo(ch) -> dict | None:
    if not isinstance(ch, dict) or not ch.get("on"):
        return None
    cor = ch.get("cor") if isinstance(ch.get("cor"), str) and len(ch["cor"]) == 7 and ch["cor"].startswith("#") \
        else "#00FF00"

    def n(k, d, lo, hi):
        try:
            return round(max(lo, min(hi, float(ch.get(k, d)))), 3)
        except (TypeError, ValueError):
            return d
    return {"on": True, "cor": cor.upper(), "tol": n("tol", 0.3, 0.01, 0.8), "suave": n("suave", 0.08, 0.0, 0.5)}


def chroma_ffmpeg(ch: dict | None) -> list[str]:
    if not ch:
        return []
    return ["format=yuva444p", f"chromakey=color=0x{ch['cor'][1:]}:similarity={ch['tol']:.3f}:blend={ch['suave']:.3f}",
            "format=rgba"]


# ---------------------------------------------------------------- transições

TRANSICOES = {
    "dissolver": "Dissolver", "preto": "Passar pelo preto", "branco": "Passar pelo branco",
    "deslizar_e": "Deslizar da esquerda", "deslizar_d": "Deslizar da direita", "deslizar_c": "Descer de cima",
    "deslizar_b": "Subir de baixo", "empurrar_e": "Empurrar para a esquerda", "empurrar_d": "Empurrar para a direita",
    "zoom_in": "Zoom de entrada", "zoom_out": "Zoom de saída", "giro": "Girar",
}


def tr_limpa(tr, dur_item: float) -> dict | None:
    if not isinstance(tr, dict) or tr.get("tipo") not in TRANSICOES:
        return None
    try:
        d = float(tr.get("dur", 0.5))
    except (TypeError, ValueError):
        d = 0.5
    d = max(0.1, min(3.0, d, max(0.1, dur_item * 0.9)))
    return {"tipo": tr["tipo"], "dur": round(d, 3)}


def _eo(p: float) -> float:  # desacelerando (ease-out cúbico)
    p = max(0.0, min(1.0, p))
    return 1 - (1 - p) ** 3


def tr_entrada(tipo: str, p: float, W: int, H: int) -> dict:
    """O que a transição faz no item que ENTRA, com p de 0 a 1: alfa, deslocamento (px), escala e giro extras."""
    p = max(0.0, min(1.0, p))
    e = _eo(p)
    out = {"a": 1.0, "dx": 0.0, "dy": 0.0, "k": 1.0, "r": 0.0}
    if tipo == "dissolver":
        out["a"] = p
    elif tipo in ("preto", "branco"):
        out["a"] = max(0.0, min(1.0, (p - 0.5) * 2))
    elif tipo == "deslizar_e":
        out["dx"] = -W * (1 - e)
    elif tipo == "deslizar_d" or tipo == "empurrar_e":
        out["dx"] = W * (1 - e)
    elif tipo == "empurrar_d":
        out["dx"] = -W * (1 - e)
    elif tipo == "deslizar_c":
        out["dy"] = -H * (1 - e)
    elif tipo == "deslizar_b":
        out["dy"] = H * (1 - e)
    elif tipo == "zoom_in":
        out["k"], out["a"] = 0.6 + 0.4 * e, min(1.0, p * 2)
    elif tipo == "zoom_out":
        out["k"], out["a"] = 1.4 - 0.4 * e, min(1.0, p * 2)
    elif tipo == "giro":
        out["k"], out["r"], out["a"] = 0.5 + 0.5 * e, -90 * (1 - e), min(1.0, p * 2)
    return out


def tr_saida(tipo: str, q: float, W: int) -> dict:
    """O que acontece com o item que SAI, no tempo extra em que ele continua por baixo (q de 0 a 1)."""
    q = max(0.0, min(1.0, q))
    out = {"dx": 0.0, "cor": None, "ca": 0.0}
    if tipo in ("preto", "branco"):
        out["cor"], out["ca"] = ("#000000" if tipo == "preto" else "#FFFFFF"), min(1.0, q * 2)
    elif tipo == "empurrar_e":
        out["dx"] = -W * _eo(q)
    elif tipo == "empurrar_d":
        out["dx"] = W * _eo(q)
    return out


def tr_expr_entrada(tipo: str, d: float, T: str, W: int, H: int) -> dict:
    """As mesmas contas de tr_entrada, como expressões do FFmpeg (T = tempo local do item, em segundos)."""
    p = f"clip(({T})/{d:.4f},0,1)"
    e = f"(1-pow(1-{p},3))"
    ne = f"pow(1-{p},3)"  # 1 - e
    vazio = {"dx": "0", "dy": "0", "k": "1", "r": "0"}
    if tipo == "deslizar_e" or tipo == "empurrar_d":
        return {**vazio, "dx": f"(-{W}*{ne})"}
    if tipo in ("deslizar_d", "empurrar_e"):
        return {**vazio, "dx": f"({W}*{ne})"}
    if tipo == "deslizar_c":
        return {**vazio, "dy": f"(-{H}*{ne})"}
    if tipo == "deslizar_b":
        return {**vazio, "dy": f"({H}*{ne})"}
    if tipo == "zoom_in":
        return {**vazio, "k": f"(0.6+0.4*{e})"}
    if tipo == "zoom_out":
        return {**vazio, "k": f"(1.4-0.4*{e})"}
    if tipo == "giro":
        return {**vazio, "k": f"(0.5+0.5*{e})", "r": f"(-90*{ne})"}
    return vazio


def tr_expr_saida(tipo: str, ext: float, T: str, W: int) -> str:
    """Deslocamento horizontal do item que sai (T = tempo local passado do fim do item)."""
    q = f"clip(({T})/{ext:.4f},0,1)"
    if tipo == "empurrar_e":
        return f"(-{W}*(1-pow(1-{q},3)))"
    if tipo == "empurrar_d":
        return f"({W}*(1-pow(1-{q},3)))"
    return "0"


# ---------------------------------------------------------------- quadros-chave (animação)

KF_CHAVES = ("x", "y", "scale", "rot", "opacity")
KF_LIMITES = {"x": (-2, 3), "y": (-2, 3), "scale": (0.02, 20), "rot": (-720, 720), "opacity": (0, 1)}
SUAVIZACOES = ("linear", "suave", "entrada", "saida")


def kf_limpo(kf, it: dict) -> list[dict] | None:
    if not isinstance(kf, list) or not kf:
        return None
    out = []
    for k in kf[:200]:
        if not isinstance(k, dict):
            continue
        try:
            t = max(0.0, min(float(k.get("t", 0)), float(it.get("dur", 1))))
        except (TypeError, ValueError):
            continue
        q = {"t": round(t, 4), "e": k.get("e") if k.get("e") in SUAVIZACOES else "suave"}
        for c in KF_CHAVES:
            lo, hi = KF_LIMITES[c]
            try:
                v = float(k.get(c, it.get(c)))
                v = it.get(c, 0) if math.isnan(v) or math.isinf(v) else max(lo, min(hi, v))
            except (TypeError, ValueError):
                v = it.get(c, 0)
            q[c] = round(v, 5)
        out.append(q)
    out.sort(key=lambda x: x["t"])
    dedup = []
    for q in out:  # dois quadros no mesmo instante: fica o último
        if dedup and abs(dedup[-1]["t"] - q["t"]) < 1e-3:
            dedup[-1] = q
        else:
            dedup.append(q)
    return dedup or None


def suaviza(e: str, p: float) -> float:
    p = max(0.0, min(1.0, p))
    if e == "linear":
        return p
    if e == "entrada":  # chega devagar (ease-out)
        return 1 - (1 - p) ** 3
    if e == "saida":    # sai devagar (ease-in)
        return p ** 3
    return 4 * p ** 3 if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2


def valor(it: dict, chave: str, lt: float) -> float:
    """Valor de x, y, scale, rot ou opacity no tempo local lt (segundos desde o começo do item)."""
    kf = it.get("kf")
    if not kf:
        return float(it.get(chave, 0))
    if lt <= kf[0]["t"]:
        return kf[0][chave]
    for a, b in zip(kf, kf[1:]):
        if lt < b["t"]:
            span = b["t"] - a["t"]
            p = (lt - a["t"]) / span if span > 1e-6 else 1.0
            return a[chave] + (b[chave] - a[chave]) * suaviza(a.get("e", "suave"), p)
    return kf[-1][chave]


def _suaviza_expr(e: str, p: str) -> str:
    if e == "linear":
        return p
    if e == "entrada":
        return f"(1-pow(1-{p},3))"
    if e == "saida":
        return f"pow({p},3)"
    return f"if(lt({p},0.5),4*pow({p},3),1-pow(-2*{p}+2,3)/2)"


def kf_expr(it: dict, chave: str, T: str) -> str:
    """valor() como expressão do FFmpeg, em função do tempo local T."""
    kf = it.get("kf")
    if not kf:
        return f"{float(it.get(chave, 0)):.5f}"
    expr = f"{kf[-1][chave]:.5f}"
    for a, b in reversed(list(zip(kf, kf[1:]))):
        span = max(1e-6, b["t"] - a["t"])
        p = f"clip((({T})-{a['t']:.4f})/{span:.4f},0,1)"
        dv = b[chave] - a[chave]
        seg = f"({a[chave]:.5f}+({dv:.5f})*{_suaviza_expr(a.get('e', 'suave'), p)})" if abs(dv) > 1e-9 \
            else f"{a[chave]:.5f}"
        expr = f"if(lt({T},{b['t']:.4f}),{seg},{expr})"
    return expr


def kf_anima(it: dict, chave: str) -> bool:
    kf = it.get("kf") or []
    return len(kf) > 1 and max(k[chave] for k in kf) - min(k[chave] for k in kf) > 1e-6


def kf_max(it: dict, chave: str) -> float:
    kf = it.get("kf")
    if not kf:
        return float(it.get(chave, 0))
    return max(k[chave] for k in kf)

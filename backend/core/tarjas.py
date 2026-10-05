"""Tarjas (lower thirds): nome e cargo, versículo, redes sociais, "ao vivo"...

Os modelos ficam em frontend/tarjas.json e valem para os dois lados: a prévia (canvas, montagem.js) e a
exportação (FFmpeg, aqui) fazem exatamente as mesmas contas de posição, tamanho, entrada e saída.

Unidades do modelo:
  x           fração da largura
  y           texto: meio da linha; faixa: topo. A distância até a "ancora" (fração da altura) é medida em
              lado menor, para as linhas ficarem juntinhas também no vertical
  tam, w, h   fração do lado MENOR da tela (fica igual no vertical e no horizontal); "lw": w em fração da largura
  recuo       empurra o texto para a direita, em fração do lado menor (para encostar num bloco)
  dx, dy      de onde a camada vem ao entrar (fração da largura / altura); sai pelo mesmo caminho
  atraso      segundos depois do início da tarja"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from . import store

ARQ = Path(__file__).resolve().parents[2] / "frontend" / "tarjas.json"
FONTES = {"Poppins ExtraBold": "Poppins-ExtraBold.ttf", "Poppins": "Poppins-Bold.ttf", "Anton": "Anton-Regular.ttf",
          "Bebas Neue": "BebasNeue-Regular.ttf", "Archivo Black": "ArchivoBlack-Regular.ttf"}
PAPEIS = ("c1", "c2", "t1", "t2")
# largura média de uma letra, em "em", de cada fonte (para encolher o texto que não cabe na tela).
# A prévia usa exatamente a mesma conta, então o que cabe na prévia cabe no vídeo.
LARGURA = {"Poppins ExtraBold": 0.6, "Poppins": 0.58, "Anton": 0.44, "Bebas Neue": 0.38, "Archivo Black": 0.68}


def cabe(texto: str, tam: float, fonte: str, maxw: float) -> float:
    """Tamanho da letra que faz o texto caber em maxw pixels (nunca aumenta)."""
    f = LARGURA.get(fonte, 0.6) * (1.12 if texto.isupper() else 1.0)
    est = max(1, len(texto)) * tam * f
    return tam if est <= maxw else tam * maxw / est


@lru_cache
def spec() -> dict:
    return json.loads(ARQ.read_text(encoding="utf-8"))


def modelo(tid: str) -> dict:
    s = spec()
    return next((m for m in s["modelos"] if m["id"] == tid), s["modelos"][0])


def _cor(c: str, it: dict) -> str:
    return (it.get(c) if c in PAPEIS else c) or "#FFFFFF"


def _ff_cor(c: str) -> str:
    return "0x" + c.lstrip("#")


def _esc(p: str) -> str:
    return p.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def filtros(it: dict, W: int, H: int, fps: int, cur: str, graph: list[str], folder: Path, tag: str,
            n0: int) -> tuple[str, int]:
    """Acrescenta ao grafo as camadas da tarja. Devolve (rótulo atual, quantos arquivos de texto criou)."""
    s = spec()
    m = modelo(it.get("tpl", ""))
    s0, dur = it["start"], it["dur"]
    s1 = s0 + dur
    ent, sai = float(s["entrada"]), float(s["saida"])
    menor = min(W, H) * it.get("scale", 1.0)
    sobe = float(s.get("sobe_vertical", 0)) if H > W else 0.0
    A = float(s.get("ancora", 0.83))

    def ypx(y: float) -> float:
        return (A - sobe) * H + (y - A) * menor + oy
    ox, oy = (it.get("x", 0.5) - 0.5) * W, (it.get("y", 0.5) - 0.5) * H
    op = float(it.get("opacity", 1.0))
    n_txt = 0
    for li, c in enumerate(m["camadas"]):
        atraso = float(c.get("atraso", 0))
        S = s0 + atraso
        e_in = f"(1-pow(1-clip((t-{S:.4f})/{ent:.3f},0,1),3))"
        e_out = f"(1-pow(1-clip(({s1:.4f}-t)/{sai:.3f},0,1),3))"
        anda = f"((1-{e_in})+(1-{e_out}))"
        dx, dy = float(c.get("dx", 0)) * W, float(c.get("dy", 0)) * H
        alfa = f"{op:.3f}*min(clip((t-{S:.4f})/{ent:.3f},0,1),clip(({s1:.4f}-t)/{sai:.3f},0,1))"
        en = f"between(t,{s0:.4f},{s1:.4f})"
        nxt = f"[tj{n0 + li}_{len(graph)}]"
        if c["k"] == "r":
            w = max(2, int(round(c["w"] * (W if c.get("lw") else menor))))
            h = max(2, int(round(c["h"] * menor)))
            x0 = c["x"] * W + ox
            y0 = ypx(c["y"])
            a_fixo = float(c.get("alfa", 1.0)) * op
            lab = f"[tjr{n0 + li}_{len(graph)}]"
            cadeia = [f"color=c={_ff_cor(_cor(c['cor'], it))}:s={w}x{h}:r={fps}:d={dur:.4f}", "format=rgba"]
            if a_fixo < 0.999:
                cadeia.append(f"colorchannelmixer=aa={a_fixo:.3f}")
            d_in = min(ent, max(0.05, dur - atraso))
            cadeia.append(f"fade=t=in:st={atraso:.3f}:d={d_in:.3f}:alpha=1")
            cadeia.append(f"fade=t=out:st={max(0.0, dur - sai):.3f}:d={min(sai, dur):.3f}:alpha=1")
            graph.append(",".join(cadeia) + f",setpts=PTS-STARTPTS+{s0:.4f}/TB{lab}")
            graph.append(f"{cur}{lab}overlay=x='{x0:.2f}+{dx:.2f}*{anda}':y='{y0:.2f}+{dy:.2f}*{anda}':"
                         f"eof_action=pass:enable='{en}'{nxt}")
            cur = nxt
            continue
        texto = (it.get("l1") if c.get("linha", 1) == 1 else it.get("l2")) or ""
        if c.get("maius"):
            texto = texto.upper()
        texto = texto.replace("\r", "").split("\n")[0].strip()
        if not texto:
            continue
        tam = float(c["tam"]) * menor
        fonte = _esc((store.FONTS / FONTES.get(c.get("fonte"), "Poppins-ExtraBold.ttf")).as_posix())
        n_txt += 1
        tf = f"tmp_{tag}.tj{n0}_{n_txt}.txt"
        (folder / tf).write_text(texto, encoding="utf-8")
        bx = c["x"] * W + ox + float(c.get("recuo", 0)) * menor
        centro = c.get("alinha") == "centro"
        tam = cabe(texto, tam, c.get("fonte", ""), W * 0.9 if centro else max(W * 0.2, W * 0.95 - bx))
        top = ypx(c["y"]) - tam / 2
        xexpr = f"{bx:.2f}" + ("-text_w/2" if centro else "") + f"+{dx:.2f}*{anda}"
        yexpr = f"{top:.2f}+{dy:.2f}*{anda}"
        extra = ""
        if c.get("contorno"):
            extra += f":borderw={max(1, int(round(float(c['contorno']) * tam)))}:bordercolor=black@0.85"
        if c.get("caixa"):
            pad = max(2, int(round(float(c.get("pad", 0.28)) * tam)))
            extra += (f":box=1:boxcolor={_ff_cor(_cor(c['caixa'], it))}@{float(c.get('alfa', 1.0)):.2f}"
                      f":boxborderw={pad}")
        graph.append(f"{cur}drawtext=fontfile='{fonte}':textfile='{tf}':expansion=none:fontsize={tam:.2f}:"
                     f"fontcolor={_ff_cor(_cor(c['cor'], it))}:x='{xexpr}':y='{yexpr}':alpha='{alfa}'{extra}:"
                     f"enable='{en}'{nxt}")
        cur = nxt
    return cur, n_txt

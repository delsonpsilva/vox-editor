"""Testes da v1.8 na Montagem: máscara (círculo/retângulo, suave, invertida) na exportação de verdade e igual à
prévia, marcadores salvos, exportação em 4K e em 720p, 50 quadros por segundo."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DADOS = Path(tempfile.mkdtemp()) / "dados"
os.environ["EDITOR_DATA"] = str(DADOS)
os.environ["VOX_SEM_MANUTENCAO"] = "1"
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import app as appmod  # noqa: E402
from backend.core import efeitos as fxm  # noqa: E402
from backend.engine import ffmpeg_tools as ff  # noqa: E402

c = TestClient(appmod.app)
falhas = 0


def check(cond, msg):
    global falhas
    print(("OK   " if cond else "FALHOU ") + msg)
    if not cond:
        falhas += 1


tmp = Path(tempfile.mkdtemp())
F = ff.ffmpeg()
subprocess.run([F, "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=640x360:r=30:d=3", "-f", "lavfi",
                "-i", "sine=f=330:d=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                str(tmp / "vermelho.mp4")], check=True)
cv2.imwrite(str(tmp / "foto.png"), np.full((400, 400, 3), (240, 200, 40), "uint8"))  # BGR: azul-claro

r = c.post("/api/montagem/novo", json={"name": "Teste 1.8", "formato": "16:9"})
pid = r.json()["id"]
m = c.get(f"/api/projects/{pid}/montagem").json()
ids = {}
for nome in ("vermelho.mp4", "foto.png"):
    r = c.post(f"/api/projects/{pid}/midias", content=(tmp / nome).read_bytes(), headers={"x-filename": nome})
    ids[nome] = r.json()["id"]


def base(**kw):
    it = {"id": kw.pop("id"), "type": "video", "track": "t_v1", "x": 0.5, "y": 0.5, "scale": 1, "rot": 0,
          "opacity": 1, "volume": 1, "fadeIn": 0, "fadeOut": 0, "speed": 1, "fit": "cover", "in": 0}
    it.update(kw)
    return it


# ---------- salvar: máscara limpa e marcadores ----------
m["bg"] = "#000000"
m["items"] = [base(id="a", src=ids["vermelho.mp4"], start=0, dur=3,
                   mask={"forma": "circulo", "cx": 0.5, "cy": 0.5, "w": 0.5, "h": 0.5 * 16 / 9, "suave": 0,
                         "lixo": "x"})]
m["markers"] = [{"t": 2.0, "nome": "Segundo ponto", "cor": "#16A34A"}, {"t": 1.0, "nome": "x" * 200, "cor": "roxo"},
                {"t": -5}, "lixo"]
m["res"] = "4k"
salvo = c.put(f"/api/projects/{pid}/montagem", json=m).json()
mk = salvo["items"][0].get("mask")
check(mk and mk["forma"] == "circulo" and "lixo" not in mk, f"máscara salva e limpa: {mk}")
mks = salvo["markers"]
check([x["t"] for x in mks] == [0.0, 1.0, 2.0], f"marcadores salvos em ordem de tempo ({[x['t'] for x in mks]})")
check(len(mks[1]["nome"]) == 60 and mks[1]["cor"] == "#FF8A3D", "nome longo cortado e cor inválida trocada")
check(salvo["res"] == "4k", "resolução escolhida fica guardada")
ruim = dict(m, items=[base(id="z", src=ids["vermelho.mp4"], start=0, dur=3, mask={"forma": "estrela"})], res="8k")
r2 = c.put(f"/api/projects/{pid}/montagem", json=ruim).json()
check("mask" not in r2["items"][0] and r2["res"] == "1080", "forma inválida e resolução inválida são ignoradas")
salvo = c.put(f"/api/projects/{pid}/montagem", json=dict(m, res="1080")).json()


def exporta(nome, **opts):
    r = c.post(f"/api/projects/{pid}/montagem/exportar", json={"quality": "rapida", **opts})
    check(r.status_code == 200, f"exportação começou ({nome})")
    for _ in range(1200):
        js = c.get(f"/api/jobs/{pid}").json()
        j = next((x for x in js if x["kind"] == "montagem"), None)
        if j and j["status"] in ("concluido", "erro", "cancelado"):
            break
        time.sleep(0.25)
    check(j and j["status"] == "concluido", f"exportou ({nome}) {'' if not j else (j.get('error') or '')[:400]}")
    P = c.get(f"/api/projects/{pid}").json()
    return DADOS / "projetos" / pid / "renders" / P["renders"][0]["file"]


def quadro(arq, t):
    out = tmp / f"q{time.time_ns()}.png"
    subprocess.run([F, "-loglevel", "error", "-y", "-ss", f"{t}", "-i", str(arq), "-frames:v", "1", str(out)], check=True)
    return cv2.imread(str(out))


def cor(img, x=0.5, y=0.5):
    h, w = img.shape[:2]
    return tuple(int(v) for v in img[int(h * y), int(w * x)][::-1])


# ---------- círculo no meio ----------
arq = exporta("círculo")
q = quadro(arq, 1.5)
centro, canto, borda_fora = cor(q, 0.5, 0.5), cor(q, 0.05, 0.05), cor(q, 0.5, 0.05)
check(centro[0] > 200 and centro[1] < 60, f"dentro do círculo aparece o vídeo (vermelho) {centro}")
check(max(canto) < 30 and max(borda_fora) < 30, f"fora do círculo aparece o fundo (preto) {canto} {borda_fora}")
# o círculo cobre metade da largura: x = 0.27 está fora, 0.30 dentro
check(max(cor(q, 0.22, 0.5)) < 40 and cor(q, 0.30, 0.5)[0] > 180, "o raio do círculo bate com a largura escolhida")
info = ff.probe(str(arq))
check((info["width"], info["height"]) == (1920, 1080), f"exportação padrão em Full HD ({info['width']}x{info['height']})")

# ---------- retângulo invertido com borda suave, numa foto por cima do vídeo ----------
m2 = dict(salvo)
m2["items"] = [base(id="a", src=ids["vermelho.mp4"], start=0, dur=3),
               base(id="f", type="image", track="t_v2", src=ids["foto.png"], start=0, dur=3, fit="cover",
                    mask={"forma": "retangulo", "cx": 0.5, "cy": 0.5, "w": 0.5, "h": 0.5, "raio": 0.2, "suave": 0.05,
                          "inverter": True})]
c.put(f"/api/projects/{pid}/montagem", json=m2)
arq = exporta("retângulo invertido")
q = quadro(arq, 1.5)
meio, fora = cor(q, 0.5, 0.5), cor(q, 0.08, 0.5)
check(meio[0] > 200 and meio[2] < 60, f"invertido: no meio o buraco mostra o vídeo de baixo (vermelho) {meio}")
check(fora[2] > 200 and fora[0] < 80, f"invertido: fora aparece a foto (azul-claro) {fora}")
# borda suave: na beira do retângulo a cor é uma mistura
x_beira = 0.25
mist = cor(q, x_beira, 0.5)
check(60 < mist[0] < 230 and 30 < mist[2] < 230, f"borda suave mistura as duas camadas {mist}")

# ---------- prévia igual à exportação: a conta do JavaScript bate com a do Python ----------
js = (ROOT / "frontend" / "montagem.js").read_text(encoding="utf-8")
ini = js.index("  function mascaraCanvas(")
fim = js.index("  function secChroma(")
codigo = js[ini:fim]
if shutil.which("node"):
    for caso in ({"forma": "circulo", "cx": 0.4, "cy": 0.55, "w": 0.6, "h": 0.5, "raio": 0.15, "suave": 0.06, "inverter": False},
                 {"forma": "retangulo", "cx": 0.5, "cy": 0.5, "w": 0.7, "h": 0.4, "raio": 0.3, "suave": 0.02, "inverter": True},
                 {"forma": "retangulo", "cx": 0.6, "cy": 0.4, "w": 0.3, "h": 0.9, "raio": 0.0, "suave": 0.0, "inverter": False}):
        prog = ("const clamp=(v,a,b)=>Math.min(b,Math.max(a,v));const MKC=new Map();"
                "const document={createElement:()=>({getContext:()=>({createImageData:(w,h)=>({data:new Uint8ClampedArray(w*h*4)}),"
                "putImageData(im){this.im=im}})})};" + codigo +
                f"const cv=mascaraCanvas(96,54,{json.dumps(caso)});const ctx=cv.getContext();"
                "const c2=document.createElement('canvas');"
                # pega o resultado direto do ImageData calculado
                )
        prog = prog.replace("x.putImageData(im, 0, 0);", "x.putImageData(im, 0, 0); globalThis.__d = Array.from(d.filter((_, i) => i % 4 === 3));")
        prog += "process.stdout.write(JSON.stringify(globalThis.__d));"
        out = subprocess.run(["node", "-e", prog], capture_output=True, text=True)
        if out.returncode != 0:
            check(False, "conta da prévia roda no node: " + out.stderr[-300:])
            continue
        a_js = np.array(json.loads(out.stdout), dtype="float32").reshape(54, 96)
        a_py = fxm.mascara_imagem(96, 54, fxm.mascara_limpa(caso)).astype("float32")
        dif = float(np.abs(a_js - a_py).max())
        check(dif <= 1.0, f"máscara {caso['forma']}{' invertida' if caso['inverter'] else ''}: prévia = exportação (dif. máx {dif})")
else:
    print("(node não instalado: pulei a comparação prévia x exportação)")

# ---------- 4K e 720p, 50 fps ----------
m3 = dict(salvo)
m3["items"] = [base(id="a", src=ids["vermelho.mp4"], start=0, dur=2,
                    mask={"forma": "circulo", "cx": 0.5, "cy": 0.5, "w": 0.5, "h": 0.5 * 16 / 9, "suave": 0.02})]
m3["fps"] = 50
c.put(f"/api/projects/{pid}/montagem", json=m3)
arq4 = exporta("4K", resolucao="4k")
i4 = ff.probe(str(arq4))
check((i4["width"], i4["height"]) == (3840, 2160), f"exporta em 4K ({i4['width']}x{i4['height']})")
check(abs(i4["fps"] - 50) < 0.5, f"50 quadros por segundo ({i4['fps']})")
arq1 = exporta("1080 para comparar", resolucao="1080")
a4 = cv2.resize(quadro(arq4, 1.0), (480, 270), interpolation=cv2.INTER_AREA).astype("float32")
a1 = cv2.resize(quadro(arq1, 1.0), (480, 270), interpolation=cv2.INTER_AREA).astype("float32")
dif = float(np.abs(a4 - a1).mean())
check(dif < 4.0, f"4K tem o mesmo enquadramento do Full HD (diferença média {dif:.2f})")
# texto, tarja e animação também ficam iguais em 4K (nada preso a pixels de 1080)
m5 = dict(m3, fps=30)
m5["items"] = m3["items"] + [
    {"id": "t", "type": "text", "track": "t_texto", "start": 0, "dur": 2, "x": 0.5, "y": 0.3, "scale": 1, "rot": 8,
     "opacity": 1, "volume": 1, "fadeIn": 0, "fadeOut": 0, "speed": 1, "fit": "contain", "text": "VOX 4K",
     "font": "Anton", "size": 0.12, "color": "#FFFFFF", "strokeW": 0.08, "stroke": "#000000",
     "kf": [{"t": 0, "x": 0.3, "y": 0.3, "scale": 1, "rot": 8, "opacity": 1, "e": "linear"},
            {"t": 2, "x": 0.7, "y": 0.3, "scale": 1.4, "rot": 8, "opacity": 1}]},
    {"id": "g", "type": "tarja", "track": "t_texto", "start": 0, "dur": 2, "x": 0.5, "y": 0.5, "scale": 1, "rot": 0,
     "opacity": 1, "volume": 1, "fadeIn": 0, "fadeOut": 0, "speed": 1, "fit": "contain", "l1": "Pr. Fulano", "l2": "Igreja"}]
c.put(f"/api/projects/{pid}/montagem", json=m5)
b4 = cv2.resize(quadro(exporta("4K com texto e tarja", resolucao="4k"), 1.2), (640, 360), interpolation=cv2.INTER_AREA).astype("float32")
b1 = cv2.resize(quadro(exporta("1080 com texto e tarja", resolucao="1080"), 1.2), (640, 360), interpolation=cv2.INTER_AREA).astype("float32")
dif = float(np.abs(b4 - b1).mean())
check(dif < 6.0, f"texto animado e tarja em 4K iguais ao Full HD (diferença média {dif:.2f})")
cv2.imwrite(str(tmp / "comparar_4k_1080.png"), np.hstack([b1, b4]).astype("uint8"))
print("   imagem de comparação:", tmp / "comparar_4k_1080.png")

arq7 = exporta("720p", resolucao="720")
i7 = ff.probe(str(arq7))
check((i7["width"], i7["height"]) == (1280, 720), f"exporta em 720p ({i7['width']}x{i7['height']})")
c.put(f"/api/projects/{pid}/montagem", json=dict(m3, formato="9:16", res="4k"))
arqv = exporta("vertical 4K (resolução guardada no projeto)")
iv = ff.probe(str(arqv))
check((iv["width"], iv["height"]) == (2160, 3840), f"vertical em 4K usa a resolução guardada ({iv['width']}x{iv['height']})")

print("\nRESULTADO:", "TUDO OK" if not falhas else f"{falhas} FALHA(S)")
sys.exit(1 if falhas else 0)

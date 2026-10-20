"""Testes da v1.12 (Super Pacote 2, parte 1) na Montagem: legenda automática da fala (trechos usados, cache,
tempo depois dos cortes e da velocidade, troca de estilo e correção), forma de onda, narração gravada, congelar
quadro, voz de estúdio e áudio separado na exportação de verdade."""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DADOS = Path(tempfile.mkdtemp()) / "dados"
os.environ["EDITOR_DATA"] = str(DADOS)
os.environ["VOX_SEM_MANUTENCAO"] = "1"
sys.path.insert(0, str(ROOT))

import base64  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import app as appmod  # noqa: E402
from backend.core import historia  # noqa: E402
from backend.engine import ffmpeg_tools as ff  # noqa: E402

c = TestClient(appmod.app)
falhas = 0


def check(cond, msg):
    global falhas
    print(("OK   " if cond else "FALHOU ") + msg)
    if not cond:
        falhas += 1


# ---- transcrição de mentira: uma "palavra" a cada 0,5 s, com o número do segundo do arquivo (mostra o tempo)
CHAMADAS = []


def falso_transcrever(wav, progress=None, prompt=""):
    with wave.open(wav, "rb") as w:
        dur = w.getnframes() / w.getframerate()
    CHAMADAS.append(round(dur, 2))
    words, t = [], 0.1
    while t + 0.3 < dur:
        words.append({"w": f"p{len(words)}", "s": round(t, 3), "e": round(t + 0.3, 3)})
        t += 0.5
    return {"words": words, "segments": []}


historia._transcrever = falso_transcrever

tmp = Path(tempfile.mkdtemp())
F = ff.ffmpeg()
subprocess.run([F, "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=640x360:r=30:d=8", "-f", "lavfi",
                "-i", "sine=f=330:d=8", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                str(tmp / "vermelho.mp4")], check=True)
# gravação do microfone como o navegador manda (WebM/Opus, sem duração no cabeçalho)
subprocess.run([F, "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=f=500:d=2.5", "-c:a", "libopus",
                "-f", "webm", str(tmp / "mic.webm")], check=True)

r = c.post("/api/montagem/novo", json={"name": "Teste 1.12", "formato": "16:9"})
pid = r.json()["id"]
c.get(f"/api/projects/{pid}/montagem")
r = c.post(f"/api/projects/{pid}/midias", content=(tmp / "vermelho.mp4").read_bytes(), headers={"x-filename": "vermelho.mp4"})
vid = r.json()["id"]
check(r.status_code == 200, "vídeo enviado para a montagem")

# ---------- forma de onda ----------
r = c.get(f"/api/projects/{pid}/midias/{vid}/onda")
d = r.json()
picos = np.frombuffer(base64.b64decode(d["peaks"]), dtype=np.uint8)
check(r.status_code == 200 and abs(len(picos) - 8 * d["pps"]) <= 2, f"forma de onda: {len(picos)} valores para 8 s ({d['pps']}/s)")
check(picos[5:-5].min() > 150, f"onda do tom constante fica alta (mínimo {picos[5:-5].min()})")
check((DADOS / "projetos" / pid / "cache" / "mont" / f"{vid}.onda.json").exists(), "onda guardada em cache")

# ---------- narração ----------
r = c.post(f"/api/projects/{pid}/montagem/narracao", content=(tmp / "mic.webm").read_bytes())
nar = r.json()
check(r.status_code == 200 and nar.get("kind") == "audio" and nar["file"].endswith(".m4a"),
      f"narração vira áudio .m4a ({r.status_code} {str(nar)[:120]})")
check(abs(float(nar.get("duration") or 0) - 2.5) < 0.2, f"narração com a duração certa ({nar.get('duration')} s)")
check(nar.get("name") == "Narração 1.m4a", f"nome da narração: {nar.get('name')}")
r = c.post(f"/api/projects/{pid}/montagem/narracao", content=b"x" * 50)
check(r.status_code == 400, "gravação vazia é recusada com aviso")

# ---------- congelar quadro ----------
r = c.post(f"/api/projects/{pid}/montagem/congelar", json={"src": vid, "t": 3.2})
cg = r.json()
check(r.status_code == 200 and cg.get("kind") == "image" and cg.get("w") == 640 and cg.get("h") == 360,
      f"quadro congelado em tamanho original ({str(cg)[:120]})")
img = cv2.imread(str(DADOS / "projetos" / pid / cg["file"]))
check(img is not None and img[180, 320, 2] > 200 and img[180, 320, 1] < 60, "quadro congelado é a imagem do vídeo (vermelho)")
check("quadro 0:03" in cg.get("name", ""), f"nome mostra o ponto do quadro: {cg.get('name')}")
r = c.post(f"/api/projects/{pid}/montagem/congelar", json={"src": "nao-existe", "t": 1})
check(r.status_code == 404, "congelar mídia que não existe dá 404")


# ---------- legenda automática ----------
def item(**kw):
    it = {"id": kw.pop("id"), "type": "video", "track": "t_v1", "x": 0.5, "y": 0.5, "scale": 1, "rot": 0,
          "opacity": 1, "volume": 1, "fadeIn": 0, "fadeOut": 0, "speed": 1, "fit": "cover", "in": 0}
    it.update(kw)
    return it


m = c.get(f"/api/projects/{pid}/montagem").json()
m["items"] = [
    item(id="v1", src=vid, start=0, dur=2, **{"in": 1.0}),                 # arquivo 1–3 s → montagem 0–2 s
    item(id="v2", src=vid, start=2, dur=1.5, speed=2, **{"in": 5.0}),      # arquivo 5–8 s em 2× → montagem 2–3,5 s
    item(id="cg", type="image", src=cg["id"], start=3.5, dur=1),
    item(id="n1", type="audio", track="t_audio", src=nar["id"], start=4.5, dur=2.5),
]
m = c.put(f"/api/projects/{pid}/montagem", json=m).json()


def espera(kind):
    j = None
    for _ in range(600):
        js = c.get(f"/api/jobs/{pid}").json()
        j = next((x for x in js if x["kind"] == kind), None)
        if j and j["status"] in ("concluido", "erro", "cancelado"):
            break
        time.sleep(0.1)
    return j


r = c.post(f"/api/projects/{pid}/montagem/legenda", json={"cfg": {"style": "destaque"}})
check(r.status_code == 200 and r.json().get("job"), "legenda começou")
j = espera("legenda_mont")
check(j and j["status"] == "concluido", f"legenda pronta {'' if not j else (j.get('error') or '')[:300]}")
res = j["result"]
lv = res["legenda_viva"]
check(len(CHAMADAS) == 2, f"transcreveu uma vez por mídia, juntando trechos próximos: {len(CHAMADAS)} trechos {CHAMADAS}")
check(sum(CHAMADAS) <= 8 + 2.5 + 0.2, f"não transcreveu nada além das mídias usadas (total {sum(CHAMADAS):.1f} s)")
from backend.core import montagem_som as _ms  # noqa: E402
check(_ms._faltam([[0, 10]], [[2, 5]]) == [[0, 2], [5, 10]], "conta do que falta transcrever (trecho no meio já feito)")
check(_ms._faltam([[0, 10]], [[0, 9.8]]) == [], "sobra menor que meio segundo não é transcrita de novo")
check(_ms._faltam([[0, 30]], [[0, 5], [12, 20]]) == [[5, 12], [20, 30]], "conta do que falta com dois trechos feitos")
ws = lv["words"]
check(lv["cfg"]["style"] == "destaque" and lv.get("auto"), "estilo escolhido e marcada como automática")
check(all(0 <= w["s"] < 7.0 for w in ws), "todas as palavras dentro da linha do tempo")
check(not any(3.5 <= (w["s"] + w["e"]) / 2 < 4.5 for w in ws), "sem palavra no quadro congelado (imagem não fala)")
# o trecho 2× tem as palavras com metade do tempo
p2 = [w for w in ws if 2.0 <= w["s"] < 3.5]
check(p2 and all(abs((w["e"] - w["s"]) - 0.15) < 0.02 for w in p2), f"pedaço em 2× tem palavras 2× mais curtas ({[round(w['e'] - w['s'], 3) for w in p2][:4]})")
p1 = [w for w in ws if w["s"] < 2.0]
check(len(p1) >= 3, f"pedaço 1 legendado ({len(p1)} palavras)")
pn = [w for w in ws if w["s"] >= 4.5]
check(len(pn) >= 3, f"narração legendada ({len(pn)} palavras)")
salvo = json.loads((DADOS / "projetos" / pid / "montagem.json").read_text(encoding="utf-8"))
check(salvo.get("legenda_viva") and salvo["legenda_viva"].get("words"), "legenda gravada na montagem (com as palavras)")

# refazer: nada novo para transcrever
antes = len(CHAMADAS)
c.post(f"/api/projects/{pid}/montagem/legenda", json={})
c.get(f"/api/jobs/{pid}")
time.sleep(0.2)
j = None
for _ in range(300):
    js = c.get(f"/api/jobs/{pid}").json()
    lst = [x for x in js if x["kind"] == "legenda_mont"]
    if lst and all(x["status"] in ("concluido", "erro", "cancelado") for x in lst):
        j = max(lst, key=lambda x: x["created"])
        break
    time.sleep(0.1)
check(j and j["status"] == "concluido" and len(CHAMADAS) == antes, f"refazer usa o que já foi transcrito ({len(CHAMADAS) - antes} trechos novos)")
check(j and j["result"]["legenda_viva"]["cfg"]["style"] == "destaque", "refazer mantém o estilo escolhido")

# esticar o pedaço 1 para mais cedo: só o pedacinho novo é transcrito
m = c.get(f"/api/projects/{pid}/montagem").json()
for it in m["items"]:
    if it["id"] == "v1":
        it["in"], it["dur"] = 0.0, 3.0
    elif it["id"] != "n1":
        it["start"] += 1.0
m = c.put(f"/api/projects/{pid}/montagem", json=m).json()
antes = len(CHAMADAS)
c.post(f"/api/projects/{pid}/montagem/legenda", json={})
for _ in range(300):
    js = c.get(f"/api/jobs/{pid}").json()
    lst = [x for x in js if x["kind"] == "legenda_mont"]
    if all(x["status"] in ("concluido", "erro", "cancelado") for x in lst):
        break
    time.sleep(0.1)
check(len(CHAMADAS) == antes, f"mudou o corte para um trecho já transcrito: nada novo ({CHAMADAS[antes:]})")

# trocar o estilo sem transcrever
lv = c.get(f"/api/projects/{pid}/montagem").json()["legenda_viva"]
r = c.post(f"/api/projects/{pid}/montagem/legenda/montar", json={"words": lv["words"], "cfg": {**lv["cfg"], "style": "uma_palavra"}})
lv2 = r.json()
check(r.status_code == 200 and len(lv2["caps"]) == len(lv["words"]), f"estilo 'uma palavra por vez': um bloco por palavra ({len(lv2['caps'])})")
check(lv2["cfg"]["position"] == lv["cfg"]["position"], "trocar o estilo mantém a posição")
# corrigir uma palavra
ws2 = [dict(w) for w in lv["words"]]
ws2[0]["w"] = "Jesus"
r = c.post(f"/api/projects/{pid}/montagem/legenda/montar", json={"words": ws2, "cfg": lv["cfg"]})
check(r.json()["caps"][0]["lines"][0][0]["w"] == "Jesus", "correção de palavra aparece na legenda")
r = c.post(f"/api/projects/{pid}/montagem/legenda/montar", json={"words": [], "cfg": lv["cfg"]})
check(r.status_code == 400, "legenda sem palavras é recusada")

# salvar pela tela mantém palavras, desligada e a voz de estúdio
m = c.get(f"/api/projects/{pid}/montagem").json()
m["legenda_viva"]["off"] = True
for it in m["items"]:
    if it["id"] == "n1":
        it["voz"] = True
    if it["id"] == "cg":
        it["voz"] = True  # imagem não tem som: não guarda
m2 = c.put(f"/api/projects/{pid}/montagem", json=m).json()
check(m2["legenda_viva"].get("off") and m2["legenda_viva"].get("words"), "legenda desligada continua com as palavras")
m["legenda_viva"]["marca"] = "1a2b3c"
check(c.put(f"/api/projects/{pid}/montagem", json=m).json()["legenda_viva"].get("marca") == "1a2b3c", "marca dos cortes guardada com a legenda")
m["legenda_viva"]["marca"] = "<script>"
check("marca" not in c.put(f"/api/projects/{pid}/montagem", json=m).json()["legenda_viva"], "marca inválida é descartada")
check(next(i for i in m2["items"] if i["id"] == "n1").get("voz") is True, "voz de estúdio guardada no áudio")
check("voz" not in next(i for i in m2["items"] if i["id"] == "cg"), "imagem não guarda voz de estúdio")


# ---------- exportação: legenda queimada, voz de estúdio e áudio separado ----------
def exportar(nome):
    r = c.post(f"/api/projects/{pid}/montagem/exportar", json={"quality": "rapida"})
    check(r.status_code == 200, f"exportação começou ({nome})")
    j = None
    for _ in range(1200):
        js = c.get(f"/api/jobs/{pid}").json()
        j = next((x for x in js if x["kind"] == "montagem" and x["status"] in ("concluido", "erro", "cancelado")
                  and x["id"] not in FEITOS), None)
        if j:
            break
        time.sleep(0.25)
    if j:
        FEITOS.add(j["id"])
    check(j and j["status"] == "concluido", f"exportou ({nome}) {'' if not j else (j.get('error') or '')[:400]}")
    P = c.get(f"/api/projects/{pid}").json()
    return DADOS / "projetos" / pid / "renders" / P["renders"][0]["file"]


FEITOS = set()


def quadro(arq, t):
    out = tmp / f"q{time.time_ns()}.png"
    subprocess.run([F, "-loglevel", "error", "-y", "-ss", f"{t}", "-i", str(arq), "-frames:v", "1", str(out)], check=True)
    return cv2.imread(str(out))


def volume_medio(arq, a, b):
    p = subprocess.run([F, "-hide_banner", "-ss", str(a), "-t", str(b - a), "-i", str(arq), "-af", "volumedetect",
                        "-f", "null", "-"], capture_output=True, text=True)
    mm = re.search(r"mean_volume: (-?[\d.]+) dB", p.stderr)
    if not mm and "-91" not in p.stderr:
        print("   (volumedetect:", " | ".join(p.stderr.strip().splitlines()[-4:]), ")")
    return float(mm.group(1)) if mm else -999.0


m = c.get(f"/api/projects/{pid}/montagem").json()
m["legenda_viva"].pop("off", None)
m["legenda_viva"]["cfg"]["position"] = "meio"
m["legenda_viva"]["cfg"]["style"] = "caixa"  # faixa escura atrás do texto: fácil de ver no quadro
c.put(f"/api/projects/{pid}/montagem", json=m)
arq = exportar("com legenda e voz de estúdio")
cap = next(cp for cp in m["legenda_viva"]["caps"] if cp["s"] < 2.5)
q_leg = quadro(arq, (cap["s"] + cap["e"]) / 2)
faixa = q_leg[440:640, :, :]
check(q_leg is not None and (faixa.min(axis=2) > 200).mean() > 0.003 and (faixa.max(axis=2) < 90).mean() > 0.01,
      "legenda aparece no vídeo exportado (no meio da tela)")
vn = volume_medio(arq, 5.6, 7.8)
check(vn > -40, f"narração com voz de estúdio tem som ({vn} dB)")

# separar o áudio: vídeo fica mudo e um pedaço de áudio do mesmo vídeo toca no lugar
m = c.get(f"/api/projects/{pid}/montagem").json()
m["legenda_viva"]["off"] = True
v1 = next(i for i in m["items"] if i["id"] == "v1")
v1["volume"] = 0
m["items"].append(item(id="sep", type="audio", track="t_audio", src=vid, start=v1["start"], dur=v1["dur"], **{"in": v1["in"]}))
for it in m["items"]:
    if it["id"] == "n1":
        it["start"] = 7.0
m = c.put(f"/api/projects/{pid}/montagem", json=m).json()
check(any(i["id"] == "sep" and i["src"] == vid for i in m["items"]), "pedaço de áudio do próprio vídeo é aceito")
arq2 = exportar("áudio separado")
check(volume_medio(arq2, 0.3, 2.7) > -40, f"áudio separado toca ({volume_medio(arq2, 0.3, 2.7)} dB)")
m["items"] = [i for i in m["items"] if i["id"] != "sep"]
c.put(f"/api/projects/{pid}/montagem", json=m)
arq3 = exportar("vídeo com volume zero e sem o áudio separado")
check(volume_medio(arq3, 0.3, 2.7) < -60, f"vídeo com volume zero fica mudo ({volume_medio(arq3, 0.3, 2.7)} dB)")

# o vídeo principal (projeto analisado) reaproveita a transcrição da análise
from backend.core import montagem_som, store  # noqa: E402
proj = store.new_project("Pregação")
store.update(proj["id"], lambda p: p.update(status="pronto", source="video.mp4", words=[
    {"w": "Graça", "s": 1.0, "e": 1.4}, {"w": "e", "s": 1.5, "e": 1.6}, {"w": "paz", "s": 1.7, "e": 2.0}],
    media={"duration": 8, "has_video": True, "has_audio": True, "width": 640, "height": 360, "fps": 30}))
md = {"id": "original", "kind": "video", "file": "video.mp4", "duration": 8, "has_audio": True}
antes = len(CHAMADAS)
ws = montagem_som.palavras_da_midia(proj["id"], md, [[0, 8]])
check(len(ws) == 3 and len(CHAMADAS) == antes, "vídeo principal usa as palavras da análise (sem transcrever)")

print()
print("RESULTADO:", "TUDO OK" if falhas == 0 else f"{falhas} FALHA(S)")
sys.exit(1 if falhas else 0)

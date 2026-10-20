"""Testes da v1.14 — Resumo do Culto: vídeos e fotos viram um resumão com música, na ordem do culto, e exporta de verdade."""
import json
import os
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

import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import app as appmod  # noqa: E402
from backend.core import montagem, montagem_som, resumo, store  # noqa: E402
from backend.engine import ffmpeg_tools as ff  # noqa: E402

c = TestClient(appmod.app)
falhas = 0
TMP = Path(tempfile.mkdtemp())
SR = 48000


def check(cond, msg):
    global falhas
    print(("OK   " if cond else "FALHOU ") + msg)
    if not cond:
        falhas += 1


def espera(pid, jid, limite=600):
    t0 = time.time()
    while time.time() - t0 < limite:
        js = {j["id"]: j for j in c.get(f"/api/jobs/{pid}").json()}
        j = js.get(jid)
        if j and j["status"] in ("concluido", "erro", "cancelado"):
            return j
        time.sleep(0.3)
    return {"status": "tempo esgotado"}


# ---------------------------------------------------------------- material de teste (sintético)

rng = np.random.default_rng(7)


def fala(seg: float) -> np.ndarray:
    """Parece fala: sílabas de ruído com voz (200-3000 Hz) e pausas entre palavras e frases."""
    out = np.zeros(int(seg * SR), dtype=np.float32)
    t = 0.0
    while t < seg - 0.5:
        for _ in range(rng.integers(2, 5)):  # palavra
            d = rng.uniform(0.1, 0.22)
            n = int(d * SR)
            i = int(t * SR)
            if i + n >= out.size:
                break
            tt = np.arange(n) / SR
            f0 = rng.uniform(110, 180)
            sil = sum(np.sin(2 * np.pi * f0 * h * tt) / h for h in range(1, 8)) * np.hanning(n)
            out[i:i + n] += 0.25 * sil.astype(np.float32)
            t += d + rng.uniform(0.03, 0.08)
        t += rng.uniform(0.18, 0.35)
        if rng.random() < 0.15:
            t += 0.6
    return out


def musica(seg: float, bpm: float = 0.0) -> np.ndarray:
    """Acordes contínuos (canto/instrumentos), com bumbo opcional no tempo."""
    n = int(seg * SR)
    t = np.arange(n) / SR
    out = np.zeros(n, dtype=np.float32)
    for k, f in enumerate((220.0, 277.2, 329.6, 440.0)):
        out += (0.12 * np.sin(2 * np.pi * f * t * (1 + 0.003 * np.sin(2 * np.pi * 5 * t)))).astype(np.float32)
    out *= (0.85 + 0.15 * np.sin(2 * np.pi * 0.2 * t)).astype(np.float32)
    if bpm:
        per = 60.0 / bpm
        kick = np.sin(2 * np.pi * 60 * np.arange(int(0.12 * SR)) / SR) * np.exp(-np.arange(int(0.12 * SR)) / (0.03 * SR))
        b = 0.25
        while b < seg - 0.2:
            i = int(b * SR)
            out[i:i + kick.size] += 0.6 * kick[: max(0, min(kick.size, n - i))].astype(np.float32)
            b += per
    return out


def grava_wav(sig: np.ndarray, caminho: Path):
    s = np.clip(sig, -1, 1)
    with wave.open(str(caminho), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((s * 32767).astype(np.int16).tobytes())


def video(nome: str, w: int, h: int, sig: np.ndarray, quando: str, fonte: str = "testsrc2", fps: int = 30) -> Path:
    wav = TMP / (nome + ".wav")
    grava_wav(sig, wav)
    dur = sig.size / SR
    out = TMP / (nome + ".mp4")
    vf = {"testsrc2": f"testsrc2=size={w}x{h}:rate={fps}",
          "escuro": f"testsrc2=size={w}x{h}:rate={fps},eq=brightness=-0.85",
          "tremido": f"nullsrc=size={w}x{h}:rate={fps},geq=random(1)*255:128:128"}[fonte]
    subprocess.run([ff.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", vf, "-i", str(wav),
                    "-t", f"{dur:.2f}", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-metadata", f"creation_time={quando}", "-shortest", str(out)], check=True)
    return out


def foto(nome: str, w: int, h: int, cor, quando_local: str, orient: int = 1, ruido: int = 0) -> Path:
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (w, h), cor)
    d = ImageDraw.Draw(im)
    for k in range(12):
        x, y = (k * 97) % w, (k * 53) % h
        d.ellipse([x, y, x + w // 6, y + h // 6], fill=((k * 40) % 255, 200, 255 - (k * 30) % 255))
        d.rectangle([w // 3, h // 3 + k * 6, w // 3 + 120, h // 3 + k * 6 + 3], fill=(255, 255, 255))
    if ruido:
        a = np.asarray(im).astype(np.int16) + rng.integers(-ruido, ruido, (h, w, 3))
        im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    ex = im.getexif()
    ex[274] = orient
    ex[306] = quando_local
    ex.get_ifd(0x8769)[36867] = quando_local
    out = TMP / (nome + ".jpg")
    im.save(out, "JPEG", quality=90, exif=ex)
    return out


print("Preparando o material de teste…")
# culto: 19:00 louvor (vídeo A), 19:20 fotos, 19:40 oração (vídeo B), 20:00 pregação (vídeo C), música enviada
vA = video("louvor", 1280, 720, np.concatenate([musica(26), fala(4)]), "2026-10-19T22:00:00Z")
vB = video("oracao", 720, 1280, fala(16), "2026-10-19T22:40:00Z")
vC = video("pregacao", 1280, 720, np.concatenate([fala(44)]), "2026-10-19T23:00:00Z")
vD = video("tremido", 1280, 720, musica(6), "2026-10-19T22:10:00Z", fonte="tremido")
vE = video("escuro", 1280, 720, musica(6), "2026-10-19T22:12:00Z", fonte="escuro")
fotos = [foto("f1", 1600, 1200, (180, 60, 40), "2026:10:19 19:20:00"),
         foto("f2", 1600, 1200, (180, 60, 40), "2026:10:19 19:20:02"),  # rajada: quase igual à f1
         foto("f3", 1600, 1200, (40, 90, 160), "2026:10:19 19:25:00", orient=6),  # deitada no arquivo
         foto("f4", 1200, 1600, (30, 140, 90), "2026:10:19 19:50:00"),
         foto("f5", 1600, 1200, (150, 150, 30), "2026:10:19 20:30:00")]
mus = TMP / "trilha.wav"
grava_wav(musica(75, bpm=120) * 0.8, mus)
mus_mp3 = TMP / "trilha.mp3"
subprocess.run([ff.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(mus), "-c:a", "libmp3lame", "-b:a",
                "128k", str(mus_mp3)], check=True)

# falas "transcritas" (o Whisper não roda no teste): oração no vídeo B e pregação no C
ORACAO = ("Senhor nosso Pai nós te agradecemos. Abençoa esta igreja em nome de Jesus. "
          "Derrama a tua presença sobre cada vida aqui, Senhor. Amém, aleluia, glória a Deus.").split()
PREGACAO = ("Irmãos, a Bíblia diz no capítulo oito que todas as coisas cooperam para o bem. "
            "Deus não desistiu de você e a sua história ainda não acabou. "
            "Leia o versículo com a igreja, porque a palavra de Deus é viva e eficaz. "
            "Quando você entrega o seu caminho ao Senhor, ele mesmo cuida do resto. "
            "Hoje é o dia de recomeçar com fé e esperança no coração.").split()


def falso_transcrever(src, a, b, pasta, progress):
    nome = Path(src).name
    texto = ORACAO if "oracao" in nome else PREGACAO if "pregacao" in nome else ["la", "la", "la"]
    out, t, k = [], a + 0.3, 0
    while t < b - 0.4:
        w = texto[k % len(texto)]
        d = 0.18 + 0.03 * len(w)
        out.append({"w": w, "s": round(t, 3), "e": round(t + d, 3)})
        t += d + (0.35 if w.endswith(".") else 0.08)
        k += 1
    return out


montagem_som._transcrever_trecho = falso_transcrever

# ---------------------------------------------------------------- análise do som (unidade)
an = resumo.analisar_som(vA, TMP)
check(an is not None, "análise do som do vídeo do louvor")
tp = an["tipo"]
check(tp[2:24].count("m") >= 18, f"louvor reconhecido como música/canto ({tp[2:24]})")
vM = video("so_musica", 640, 360, musica(12), "2026-10-19T22:05:00Z")
anM = resumo.analisar_som(vM, TMP)
check(anM["tipo"].count("m") >= 10, f"vídeo só de música (sem nenhuma pausa) é música, não silêncio ({anM['tipo']})")
anC = resumo.analisar_som(vC, TMP)
check(anC["tipo"][2:42].count("f") >= 32, f"pregação reconhecida como fala ({anC['tipo'][2:42]})")
q = resumo.analisar_imagem_video(vD)
q2 = resumo.analisar_imagem_video(vA)
q3 = resumo.analisar_imagem_video(vE)
check(q and q2 and q3, f"quadros-chave lidos ({len(q)}, {len(q2)}, {len(q3)})")
check(np.mean([x["q"] for x in q3]) < np.mean([x["q"] for x in q2]) - 0.15, "vídeo escuro ganha nota menor")
check(resumo.categoria_da_fala(" ".join(ORACAO), 20) == "oracao", "fala com Senhor/Pai/amém vira oração")
check(resumo.categoria_da_fala(" ".join(PREGACAO), 40) == "pregacao", "fala com Bíblia/irmãos vira pregação")
bt = resumo.batidas(mus, TMP)
check(bt is not None and abs(bt[0] - 0.5) < 0.03, f"ritmo da música achado (120 bpm → 0,5 s): {bt}")

# ---------------------------------------------------------------- pela API
st = c.get("/api/resumo/status").json()
check("culto" in st["eventos"] and "palavra_ativa" in st["estilos_legenda"], "status do resumo")
r = c.post("/api/resumo/novo", json={"name": "Teste", "formato": "9:16"}).json()
pid = r["id"]
check(bool(pid), "projeto do resumo criado")


def envia(p: Path, mod_ms=None, proj=None):
    h = {"x-filename": p.name, "x-fuso": "180"}
    if mod_ms:
        h["x-modificado"] = str(mod_ms)
    return c.post(f"/api/resumo/{proj or pid}/arquivo", content=p.read_bytes(), headers=h)


# envia fora de ordem (a hora de gravação decide)
ids = {}
for p in [vC, fotos[3], vA, fotos[0], fotos[1], vB, fotos[2], vD, vE, fotos[4], mus_mp3]:
    rr = envia(p)
    check(rr.status_code == 200, f"enviou {p.name}" + ("" if rr.status_code == 200 else f": {rr.text[:200]}"))
    if rr.status_code == 200:
        ids[p.name] = rr.json()
check(abs((ids["louvor.mp4"].get("quando") or 0) - 1792447200) < 2, "hora do vídeo lida dos dados do celular")
check(abs((ids["f1.jpg"].get("quando") or 0) - 1792448400) < 2, "hora da foto (EXIF, fuso do Brasil)")
check(ids["f3.jpg"]["h"] > ids["f3.jpg"]["w"], "foto deitada no arquivo foi endireitada (em pé)")
rr = c.post(f"/api/resumo/{pid}/arquivo", content=b"x", headers={"x-filename": "IMG_1.HEIC"})
check(rr.status_code == 400 and "iPhone" in rr.json()["detail"], "HEIC explica o que fazer")

r = c.post(f"/api/resumo/{pid}/criar", json={"name": "Culto da Família", "opcoes": {
    "duracao": "60", "formato": "9:16", "ritmo": "calmo", "musica": "__enviada__", "evento": "culto",
    "cor": "cinema", "data": "2026-10-19"}}).json()
j = espera(pid, r["job"])
check(j["status"] == "concluido", "resumo montado" + ("" if j["status"] == "concluido" else f": {j.get('error')}"))
res = j.get("result") or {}
print("     resultado:", json.dumps({k: v for k, v in res.items() if k != "id"}, ensure_ascii=False))
m = c.get(f"/api/projects/{pid}/montagem").json()
dur = montagem.duracao(m)
check(50 <= dur <= 66, f"duração perto do pedido (60 s): {dur:.1f} s")
v1 = sorted([x for x in m["items"] if x["track"] == "t_v1" and x["type"] in ("video", "image")], key=lambda x: x["start"])
check(len(v1) >= 10, f"pedaços na trilha principal: {len(v1)}")
med = {x["id"]: x for x in m["media"]}
nomes = [med[x["src"]]["name"] for x in v1]
check(any(n.startswith("louvor") for n in nomes) and any(n.startswith("pregacao") for n in nomes)
      and any(n.endswith(".jpg") for n in nomes), "entraram vídeos do louvor, da pregação e fotos")
check(not ("f1.jpg" in nomes and "f2.jpg" in nomes), "foto repetida (rajada) entrou só uma vez")
# ordem do culto: louvor (19:00) antes da oração (19:40) antes da pregação (20:00)
pos = {}
for k, n in enumerate(nomes):
    pos.setdefault(n.split(".")[0], k)
check(pos.get("louvor", 99) < pos.get("oracao", 99) < pos.get("pregacao", 99) if "oracao" in pos
      else pos.get("louvor", 99) < pos.get("pregacao", 99), f"segue a ordem do culto ({list(pos)})")
starts = [x["start"] for x in v1]
check(all(abs(starts[k + 1] - (starts[k] + v1[k]["dur"])) < 0.01 for k in range(len(v1) - 1)), "sem buracos entre os pedaços")
com_som = [x for x in v1 if x["type"] == "video" and x["volume"] > 0]
check(1 <= len(com_som) <= 3, f"momentos com som original: {len(com_som)}")
check(res.get("frases", 0) >= 1 and m.get("legenda_viva"), "frase da pregação com legenda animada")
mus_it = [x for x in m["items"] if x["track"] == "t_musica"]
check(mus_it and all(x["duck"] for x in mus_it), "música de fundo que abaixa nos momentos")
check(abs(sum(x["dur"] for x in mus_it) - dur) < 0.3, "a música cobre o vídeo todo")
check(res.get("ritmo_musica"), "cortes no ritmo da música")
# cortes caem nas batidas (0,5 s)
fase = resumo.batidas(store.pdir(pid) / med[mus_it[0]["src"]]["file"], TMP)
if fase:
    fora = [round(((s - fase[1]) / fase[0]) % 1, 2) for s in starts[1:]]
    check(sum(1 for f in fora if min(f, 1 - f) < 0.12) >= len(fora) * 0.8, f"cortes nas batidas ({fora[:8]}…)")
textos = [x for x in m["items"] if x["type"] == "text"]
check(any("CULTO" in x["text"].upper() for x in textos), "abertura com o título")
check(any("19 de outubro de 2026" == x["text"] for x in textos), "data por extenso na abertura")
rot = {x["text"] for x in textos}
check(rot & {"Louvor", "Palavra", "Oração"}, f"nome das partes na tela ({sorted(rot & {'Louvor', 'Palavra', 'Oração'})})")
check(all(x.get("fx") for x in v1), "cor de cinema em todos os pedaços")
fotos_it = [x for x in v1 if x["type"] == "image"]
check(fotos_it and all(x.get("kf") for x in fotos_it), "fotos com movimento suave")
check(any(x.get("fundoDesf") for x in fotos_it), "foto deitada no vertical aparece inteira com fundo desfocado")
nm_trem = [n for n in nomes if n.startswith("tremido")]
nm_esc = [n for n in nomes if n.startswith("escuro")]
check(len(nm_esc) <= 1 and len(nm_trem) <= 1, "vídeo escuro e tremido aparecem pouco")
check(store.load(pid)["name"] == "Culto da Família", "nome do resumo trocado")
check(m.get("markers"), "marcadores nos momentos")

# refazer com outras opções (a análise fica guardada: rápido)
t0 = time.time()
r = c.post(f"/api/resumo/{pid}/criar", json={"opcoes": {"duracao": "30", "formato": "16:9", "ritmo": "animado",
                                                        "musica": "", "rotulos": False, "abertura": False}}).json()
j = espera(pid, r["job"])
gasto = time.time() - t0
check(j["status"] == "concluido", f"refez em 16:9, 30 s, animado, sem música ({gasto:.1f} s)")
m2 = c.get(f"/api/projects/{pid}/montagem").json()
d2 = montagem.duracao(m2)
check(24 <= d2 <= 34 and m2["formato"] == "16:9", f"refeito: {d2:.1f} s em {m2['formato']}")
check(not [x for x in m2["items"] if x["track"] == "t_musica"], "sem música quando pedido")
check(all(x["volume"] > 0 for x in m2["items"] if x["type"] == "video" and med[x["src"]].get("has_audio")),
      "sem música, os vídeos ficam com o som deles")
check(not [x for x in m2["items"] if x["type"] == "text" and x["text"] in ("Louvor", "Palavra", "Oração")],
      "sem nomes das partes quando desligado")
lst = c.get("/api/resumo/lista").json()
check(lst and lst[0]["id"] == pid and lst[0]["arquivos"] == 10, f"lista de resumos ({lst[0]['arquivos'] if lst else 0} arquivos)")

# exporta de verdade (volta para a versão de 60 s com música)
r = c.post(f"/api/resumo/{pid}/criar", json={"opcoes": {"duracao": "60", "musica": "__enviada__", "data": "2026-10-19"}}).json()
j = espera(pid, r["job"])
check(j["status"] == "concluido", "refeito com música para exportar")
m3 = c.get(f"/api/projects/{pid}/montagem").json()
m3["res"] = "720"
c.put(f"/api/projects/{pid}/montagem", json=m3)
r = c.post(f"/api/projects/{pid}/montagem/exportar", json={"quality": "rapida"})
check(r.status_code == 200, "exportação começou")
jid = next(x["id"] for x in c.get(f"/api/jobs/{pid}").json() if x["kind"] == "montagem")
j = espera(pid, jid, 900)
check(j["status"] == "concluido", "exportou o resumo" + ("" if j["status"] == "concluido" else f": {j.get('error')}"))
if j["status"] == "concluido":
    out = store.pdir(pid) / "renders" / j["result"]["file"]
    info = ff.probe(str(out))
    print("     arquivo:", out)
    check(abs(info["duration"] - montagem.duracao(m3)) < 0.6, f"vídeo final com {info['duration']:.1f} s")
    check(info["width"] < info["height"], "vídeo final em pé (9:16)")
    check(info["has_audio"], "vídeo final com som")

# só fotos (sem vídeo nenhum) também funciona
r = c.post("/api/resumo/novo", json={"name": "Só fotos"}).json()
pid2 = r["id"]
for p in fotos:
    envia(p, proj=pid2)
r = c.post(f"/api/resumo/{pid2}/criar", json={"opcoes": {"duracao": "30", "musica": ""}}).json()
j = espera(pid2, r["job"])
check(j["status"] == "concluido", "resumo só com fotos")
check("aviso" in (j.get("result") or {}), "avisa que ficou mais curto que o pedido")
# sem arquivo nenhum: erro explicado
r = c.post("/api/resumo/novo", json={}).json()
r = c.post(f"/api/resumo/{r['id']}/criar", json={}).json()
j = espera(r["id"], r["job"])
check(j["status"] == "erro" and "Envie" in (j.get("error") or ""), "sem arquivos: explica o que fazer")

print("\nRESULTADO:", "TUDO OK" if not falhas else f"{falhas} FALHA(S)")
sys.exit(1 if falhas else 0)

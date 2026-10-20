"""Testes da v1.6: nota de cada corte com os motivos e título/legenda/hashtags sugeridos para cada rede."""
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["EDITOR_DATA"] = str(ROOT / "teste_dados")
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend import app as appmod  # noqa: E402
from backend.core import publish, store  # noqa: E402
from backend.engine import avaliacao, redes, smartcuts  # noqa: E402

c = TestClient(appmod.app)
falhas = 0


def check(cond, msg):
    global falhas
    print(("OK   " if cond else "FALHOU ") + msg)
    if not cond:
        falhas += 1


# fala com pontuação: um trecho forte (pergunta + frases marcantes) e um trecho fraco (começa com "e", pausas longas)
FALA = [
    ("Bom dia igreja, sejam bem-vindos ao culto de hoje.", 0.3),
    ("Hoje vamos falar sobre a oração e a fé.", 0.4),
    ("Você sabia que Deus escuta cada oração que você faz?", 0.25),
    ("Nunca subestime o poder de uma oração sincera!", 0.25),
    ("A fé muda o coração de quem ora.", 0.25),
    ("Jesus se retirava para orar porque sabia que a oração é a força da vida.", 0.25),
    ("Quando você ora, a esperança volta para dentro da sua casa.", 0.25),
    ("Ore pela sua família todos os dias.", 0.9),
    ("e aí a gente foi andando", 2.2),
    ("depois disso", 2.5),
    ("a gente chegou lá e ficou um tempo", 2.4),
    ("e então voltou para casa no fim da tarde", 2.0),
    ("Que Deus abençoe a todos.", 1.0),
]
words, t, limites = [], 0.0, []
for frase, pausa in FALA:
    ini = t
    for w in frase.split():
        d = 0.16 + 0.025 * len(w) / 4
        words.append({"w": w, "s": round(t, 2), "e": round(t + d, 2), "p": 0.95})
        t += d + 0.07
    limites.append((ini, round(t - 0.07, 2)))
    t += pausa
dur = t + 2

p = store.new_project("Pregação de teste (cortes 1.6)")
pid = p["id"]
forte = [limites[2][0], limites[7][1]]
fraco = [limites[8][0], limites[11][1] - 0.6]  # termina antes da última palavra
p.update(status="pronto", words=words, segments=[], media={"duration": dur, "has_video": True},
         analysis={"v": 3, "silences": [], "breaths": []},
         clips=[{"id": "cA", "kind": "corte", "segments": [forte], "title": "Deus escuta cada oração que você faz?",
                 "hook": "Deus escuta cada oração?", "reason": "", "score": 40, "post": ""},
                {"id": "cB", "kind": "corte", "segments": [fraco], "title": "a gente foi andando", "hook": "", "reason": "",
                 "score": 90, "post": ""}])
store.save(p)

# ---------- nota e motivos ----------
v = c.get(f"/api/projects/{pid}").json()
cl = {x["id"]: x for x in v["clips"]}
a, b = cl["cA"]["avaliacao"], cl["cB"]["avaliacao"]
check(0 <= a["nota"] <= 99 and 0 <= b["nota"] <= 99, f"notas de 0 a 99 (forte {a['nota']}, fraco {b['nota']})")
check(a["nota"] >= b["nota"] + 20, "o trecho forte tem nota bem maior que o fraco")
ta = [m["t"] for m in a["motivos"] if m["ok"]]
check("pergunta que prende" in ta or "gancho forte" in ta, "forte: motivo de gancho (" + ", ".join(ta) + ")")
check("ideia completa" in ta, "forte: ideia completa")
check(any(m["t"] == "frase marcante" or m["t"] == "emoção" for m in a["motivos"]), "forte: frase marcante ou emoção")
tb = [m["t"] for m in b["motivos"] if not m["ok"]]
check("começa no meio de uma ideia" in tb, "fraco: avisa que começa no meio de uma ideia (" + ", ".join(tb) + ")")
check("termina no meio da frase" in tb, "fraco: avisa que termina no meio da frase")
check("muitas pausas" in tb, "fraco: avisa das pausas longas")
check(a["rotulo"] in ("Ótimo", "Bom") and b["rotulo"] in ("Fraco", "Médio"), f"rótulos: {a['rotulo']} / {b['rotulo']}")
check(all(m.get("dica") for m in a["motivos"] + b["motivos"]), "cada motivo tem uma explicação")
check(all(k in a["criterios"] for k in ("gancho", "ideia", "emocao", "ritmo", "duracao")), "mostra a nota por critério")
check("texto" not in a, "a fala do corte não vai para a tela a cada atualização")
check(len(a["motivos"]) <= 5, "no máximo 5 motivos")

# nota da IA combinada com a local
cl2 = dict(p["clips"][1], score=95, score_fonte="ia")
av = avaliacao.avaliar(words, cl2, cl2["segments"], {"lo": 20, "hi": 60})
check(av["ia"] == 95 and av["nota"] == round(0.6 * 95 + 0.4 * av["local"]), "combina a nota da IA (60%) com a local (40%)")

# ---------- textos por rede ----------
rd = cl["cA"]["redes"]
check(set(rd) == {"youtube", "instagram", "tiktok", "facebook"}, "sugere texto para as 4 redes")
check(cl["cA"]["redes_fonte"] == "auto", "sem IA: sugestão automática")
check(0 < len(rd["youtube"]["titulo"]) <= 100, "título do YouTube com até 100 caracteres: " + rd["youtube"]["titulo"])
check("#shorts" in rd["youtube"]["hashtags"], "YouTube leva #shorts")
check("#reels" in rd["instagram"]["hashtags"] and len(rd["instagram"]["hashtags"]) <= 5, "Instagram: #reels e até 5 hashtags")
check("#fyp" in rd["tiktok"]["hashtags"], "TikTok leva #fyp")
check(len(rd["facebook"]["hashtags"]) <= 3, "Facebook: até 3 hashtags")
check("#fé" in rd["instagram"]["hashtags"] or "#oração" in rd["instagram"]["hashtags"],
      "hashtags do assunto: " + " ".join(rd["instagram"]["hashtags"]))
check(all(h.startswith("#") and " " not in h for n in rd for h in rd[n]["hashtags"]), "hashtags bem formadas")
check(len({rd[n]["legenda"] for n in rd}) >= 3, "cada rede tem um texto do seu jeito")
check(redes.tag("Palavra de Deus") == "#palavradedeus" and redes.tag("#Fé!") == "#fé", "monta hashtag a partir de palavras")
check(redes.limpar_tags(["#fe", "#fé", "fe"]) == ["#fe"], "não repete hashtag (com ou sem acento)")

# hashtags fixas da marca vão no fim, sem repetir
c.put("/api/settings", json={"brand": {"hashtags": "#minhaigreja, #fé"}})
r = c.get(f"/api/projects/{pid}/clips/cA/redes").json()
check(r["fixas"] == ["#minhaigreja", "#fé"], "lê as hashtags fixas da marca")
leg = r["prontos"]["instagram"]["legenda"]
check(leg.endswith("#minhaigreja") or "#minhaigreja" in leg.splitlines()[-1], "legenda pronta termina com as hashtags (fixas no fim)")
check(leg.count("#fé") <= 1, "não repete #fé")
check(r["prontos"]["youtube"]["titulo"] == rd["youtube"]["titulo"], "título pronto do YouTube")
ig = redes.texto_final({"legenda": "x", "hashtags": ["#a1", "#b2", "#c3", "#d4", "#reels"]}, ["#minhaigreja", "#fé"], "instagram")
check(ig.split("\n")[-1].split() == ["#a1", "#b2", "#c3", "#minhaigreja", "#fé"], "Instagram: no máximo 5 hashtags, as fixas da marca ficam")

# edição à mão
novo = json.loads(json.dumps(rd))
novo["tiktok"]["legenda"] = "Deus ouve você 🙏"
novo["tiktok"]["hashtags"] = ["oração", "#fé fyp"]
v = c.put(f"/api/projects/{pid}/clips/cA", json={"redes": novo}).json()
x = next(k for k in v["clips"] if k["id"] == "cA")
check(x["redes"]["tiktok"]["legenda"] == "Deus ouve você 🙏" and x["redes_fonte"] == "editado", "salva o texto editado")
check(x["redes"]["tiktok"]["hashtags"] == ["#oração", "#fé", "#fyp"], "hashtags digitadas soltas viram hashtags")
check(x["redes"]["youtube"]["titulo"] == rd["youtube"]["titulo"], "não mexe nas outras redes")
r = c.post(f"/api/projects/{pid}/clips/cA/redes", json={"ia": False}).json()
check(r["fonte"] == "auto" and r["redes"]["tiktok"]["legenda"] != "Deus ouve você 🙏", "volta às sugestões automáticas")
check(c.post(f"/api/projects/{pid}/clips/cA/redes", json={"ia": True}).status_code == 400, "sem IA ligada: avisa")

# com IA (simulada)
cfg = store.load_config()
store.save_config({"ai": {"provider": "anthropic", "api_key": "teste", "model": "claude-haiku-4-5-20251001"}})
redes._call_llm = lambda prompt, ai: json.dumps({
    "youtube": {"titulo": "Deus ouve a sua oração", "legenda": "Uma palavra sobre oração.", "hashtags": ["#fé", "#oração", "#shorts"]},
    "instagram": {"legenda": "DEUS ESCUTA VOCÊ\n\nSalve este vídeo.", "hashtags": ["#fé", "#reels"]},
    "tiktok": {"legenda": "Ele escuta 🙏", "hashtags": ["#fé", "#fyp"]},
    "facebook": {"legenda": "Compartilhe com quem precisa.", "hashtags": ["#fé"]}})
r = c.post(f"/api/projects/{pid}/clips/cA/redes", json={"ia": True}).json()
check(r["fonte"] == "ia" and r["redes"]["youtube"]["titulo"] == "Deus ouve a sua oração", "reescreve com IA")
check(r["redes"]["tiktok"]["legenda"] == "Ele escuta 🙏", "IA: texto do TikTok")

# geração dos cortes com IA traz os textos curtos por rede
smartcuts._call_llm = lambda prompt, ai: json.dumps([{
    "inicio": 2, "fim": 7, "titulo": "Deus escuta a sua oração", "gancho": "Deus escuta você", "selo": "PALAVRA DE HOJE",
    "motivo": "pergunta forte e conclusão", "nota": 88, "post": "Ore sempre #fé",
    "redes": {"yt": "Deus ESCUTA cada oração", "ig": "Ele ouve você", "tt": "Você sabia disso?", "fb": "Uma palavra para hoje.",
              "tags": ["fé", "oração", "#deus"]}}])
from backend.core import pipeline  # noqa: E402
sents = smartcuts.sentences([], words)
check("max_tokens\": 8000" in Path(smartcuts.__file__).read_text(encoding="utf-8"), "resposta da IA com espaço para os textos por rede")
res = pipeline.regenerate_clips(pid, lambda *a: None)
check(res["count"] == 1 and res["source"] == "IA", "gera cortes com IA (simulada)")
v = c.get(f"/api/projects/{pid}").json()
x = v["clips"][-1]
check(x["redes_fonte"] == "ia" and x["redes"]["youtube"]["titulo"] == "Deus ESCUTA cada oração", "corte da IA já vem com título do YouTube")
check(x["redes"]["instagram"]["legenda"].startswith("Ele ouve você"), "e com a primeira linha do Instagram")
check(x["redes"]["tiktok"]["hashtags"][:3] == ["#fé", "#oração", "#deus"] and "#fyp" in x["redes"]["tiktok"]["hashtags"],
      "hashtags do assunto (IA) + as de cada rede")
check(x["avaliacao"]["ia"] == 88, "a nota da IA entra na conta")
check("redes_ia" not in x, "o formato curto da IA não vai para a tela")
store.save_config({"ai": cfg["ai"]})

# ---------- publicar com texto próprio de cada rede ----------
capt = []
publish.public_status = lambda: {n: {"connected": True, "name": publish.NETWORKS[n]["name"]} for n in publish.NETWORKS}
publish.add = lambda items: capt.extend(items)
(store.pdir(pid) / "renders").mkdir(parents=True, exist_ok=True)
(store.pdir(pid) / "renders" / "x.mp4").write_bytes(b"0")
r = c.post("/api/publish/queue", json={"project": pid, "file": "x.mp4", "nets": ["youtube", "tiktok"], "when": "now",
                                        "caption": "geral", "title": "Título geral",
                                        "textos": {"tiktok": {"caption": "só do tiktok #fyp"}, "youtube": {"title": "Só do YouTube", "caption": "desc yt"}}})
check(r.status_code == 200, "aceita textos por rede na fila")
por = {it["net"]: it for it in capt}
check(por["tiktok"]["caption"] == "só do tiktok #fyp", "TikTok sai com o texto dele")
check(por["youtube"]["title"] == "Só do YouTube" and por["youtube"]["caption"] == "desc yt", "YouTube sai com título e descrição dele")
capt.clear()
c.post("/api/publish/queue", json={"project": pid, "file": "x.mp4", "nets": ["facebook"], "when": "now", "caption": "geral", "title": "T"})
check(capt and capt[0]["caption"] == "geral", "sem textos por rede: continua igual à versão anterior")

store.save_config({"brand": {"hashtags": ""}})
store.delete_project(pid)
print("\nFALHAS:", falhas)
shutil.rmtree(ROOT / "teste_dados", ignore_errors=True) if os.environ.get("LIMPAR") else None
sys.exit(1 if falhas else 0)

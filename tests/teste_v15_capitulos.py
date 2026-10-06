"""Testes da v1.5: capítulos automáticos (divisão por assunto, tempo do vídeo editado, regras do YouTube)
e perfis da edição automática."""
import os
import random
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["EDITOR_DATA"] = str(ROOT / "teste_dados")
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend import app as appmod  # noqa: E402
from backend.core import store  # noqa: E402
from backend.engine import capitulos, edits  # noqa: E402

c = TestClient(appmod.app)
falhas = 0


def check(cond, msg):
    global falhas
    print(("OK   " if cond else "FALHOU ") + msg)
    if not cond:
        falhas += 1


random.seed(7)
ASSUNTOS = [
    ["A oração muda o coração de quem ora.", "Quando você ora, Deus escuta a sua oração.", "Orar todos os dias é um hábito.",
     "Jesus se retirava para orar no monte.", "A oração da manhã prepara o dia inteiro.", "Ore pela sua família."],
    ["O perdão liberta a alma ferida.", "Perdoar não é esquecer, é decidir soltar a mágoa.", "A mágoa prende quem não perdoa.",
     "Pedro perguntou quantas vezes devia perdoar.", "Setenta vezes sete é perdão sem limite.", "Perdoe quem te feriu."],
    ["A generosidade abre as janelas do céu.", "Dar com alegria é sinal de um coração grato.", "A oferta não é sobre dinheiro.",
     "A viúva deu tudo o que tinha no gazofilácio.", "Quem semeia com fartura colhe com fartura.", "Seja generoso com o próximo."],
    ["A família é o primeiro ministério.", "Pais e filhos precisam de tempo juntos à mesa.", "O casamento se constrói no dia a dia.",
     "Josué disse: eu e a minha casa serviremos ao Senhor.", "Cuide da sua casa antes de tudo.", "Abrace os seus filhos hoje."],
]
words, t = [], 0.0
limites_reais = []
for k, frases in enumerate(ASSUNTOS):
    limites_reais.append(t)
    fim = t + 330  # ~5,5 min por assunto
    while t < fim:
        for w in random.choice(frases).split():
            d = 0.18 + 0.03 * len(w) / 4
            words.append({"w": w, "s": round(t, 2), "e": round(t + d, 2), "p": 0.95})
            t += d + 0.08
        t += 0.6
dur = t + 2

p = store.new_project("Pregação de teste (capítulos)")
pid = p["id"]
p.update(status="pronto", words=words, segments=[], media={"duration": dur, "has_video": True},
         analysis={"v": 3, "silences": [[limites_reais[2] - 0.55, limites_reais[2] - 0.05]], "breaths": []})
store.save(p)

caps = capitulos.dividir(words)
check(3 <= len(caps) <= 6, f"divide em {len(caps)} capítulos (vídeo de {dur / 60:.0f} min, 4 assuntos)")
inicios = [x["s"] for x in caps]
check(inicios[0] == words[0]["s"], "o primeiro capítulo começa no início da fala")
acertos = sum(1 for lr in limites_reais[1:] if any(abs(lr - i) < 60 for i in inicios))
check(acertos >= 2, f"acha as trocas de assunto ({acertos} de 3 dentro de 1 minuto)")
check(all(b - a >= 90 for a, b in zip(inicios, inicios[1:])), "capítulos com pelo menos 1min30")

r = c.post(f"/api/projects/{pid}/capitulos", json={"ia": False})
check(r.status_code == 200, "gera pela API sem IA")
j = r.json()
check(j["itens"][0]["t_editado"] == 0.0, "primeiro capítulo em 0:00 (regra do YouTube)")
check(j["valido_youtube"], "pelo menos 3 capítulos (regra do YouTube)")
check(j["texto"].splitlines()[0].startswith("00:00 "), "texto pronto para a descrição: " + j["texto"].splitlines()[0])
check(all(x["titulo"] and len(x["titulo"]) <= 60 for x in j["itens"]), "todos têm título curto: "
      + " | ".join(x["titulo"] for x in j["itens"]))
# o corte de silêncio antes do 3º assunto puxa os capítulos seguintes para trás no vídeo editado
ed = [x for x in j["itens"] if x["t"] > limites_reais[2]]
check(not ed or all(x["t_editado"] < x["t"] for x in ed), "tempos convertidos para o vídeo editado")

itens = [{"t": x["t"], "titulo": x["titulo"]} for x in j["itens"]]
itens[1]["titulo"] = "O poder do perdão"
r = c.put(f"/api/projects/{pid}/capitulos", json={"itens": itens})
check(r.json()["itens"][1]["titulo"] == "O poder do perdão", "salva título editado à mão")
r = c.put(f"/api/projects/{pid}/capitulos", json={"itens": itens[:1] + [{"t": itens[0]["t"] + 3, "titulo": "Perto demais"}] + itens[1:]})
check(all(b["t_editado"] - a["t_editado"] >= 10 for a, b in zip(r.json()["itens"], r.json()["itens"][1:])),
      "junta capítulos a menos de 10 s (regra do YouTube)")

# perfis
r = c.get(f"/api/projects/{pid}/perfis").json()
check(len(r["perfis"]) == 5 and all("final" in x for x in r["perfis"]), "lista 5 perfis com prévia da duração")
r = c.post(f"/api/projects/{pid}/perfil", json={"perfil": "reels"}).json()
check(r["settings"]["silence"]["rhythm"] == "rapido" and r["settings"]["breath"]["mode"] == "cut", "aplica o perfil Reels")
check(c.get(f"/api/projects/{pid}/perfis").json()["atual"] == "reels", "reconhece o perfil aplicado")
check(r["settings"]["subtitles"]["style"] == edits.DEFAULT_SETTINGS["subtitles"]["style"], "não mexe na legenda")
r = c.post(f"/api/projects/{pid}/perfil", json={"perfil": "leve", "padrao": True})
check(store.load_config()["defaults"]["silence"]["min_dur"] == 1.5, "salva como padrão dos projetos novos")
check(c.post(f"/api/projects/{pid}/perfil", json={"perfil": "xyz"}).status_code == 400, "recusa perfil desconhecido")
cfg = store.load_config()
cfg["defaults"] = {}
store._write_json(store.CONFIG_FILE, cfg)

store.delete_project(pid)
print("\nFALHAS:", falhas)
shutil.rmtree(ROOT / "teste_dados", ignore_errors=True) if os.environ.get("LIMPAR") else None
sys.exit(1 if falhas else 0)

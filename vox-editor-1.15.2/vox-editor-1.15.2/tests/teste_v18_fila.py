"""Testes da v1.8: fila com limite, prioridade, posição na fila e cancelamento (inclusive encerrando o FFmpeg)."""
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.update(EDITOR_DATA=str(Path(tempfile.mkdtemp()) / "fila"), VOX_RENDERS="2", VOX_ANALISES="1")
sys.path.insert(0, str(ROOT))

from backend.core import jobs  # noqa: E402
from backend.engine import ffmpeg_tools as ff  # noqa: E402

falhas = 0


def check(cond, msg):
    global falhas
    print(("OK   " if cond else "FALHOU ") + msg)
    if not cond:
        falhas += 1


def espera(cond, seg=15):
    fim = time.time() + seg
    while time.time() < fim:
        if cond():
            return True
        time.sleep(0.05)
    return False


# 1) limite: 2 renders ao mesmo tempo, o terceiro espera
check(jobs.LIMITES["render"] == 2 and jobs.LIMITES["analysis"] == 1, f"limites lidos do ambiente: {jobs.LIMITES}")
pico = {"agora": 0, "max": 0}
import threading  # noqa: E402
trava = threading.Lock()


def lento(pr):
    with trava:
        pico["agora"] += 1
        pico["max"] = max(pico["max"], pico["agora"])
    for i in range(10):
        pr(i / 10, "trabalhando")
        time.sleep(0.05)
    with trava:
        pico["agora"] -= 1
    return {"ok": True}


js = [jobs.submit("render", "p1", lento, queue="render") for _ in range(5)]
time.sleep(0.1)
esperando = [j for j in js if j["status"] == "na fila"]
check(len(esperando) == 3, f"5 renders: 2 rodando e 3 na fila ({len(esperando)} na fila)")
check(sorted(j["posicao"] for j in esperando) == [1, 2, 3], "cada um mostra a posição na fila")
check(espera(lambda: all(j["status"] == "concluido" for j in js)), "todos os 5 terminam")
check(pico["max"] == 2, f"nunca passou de 2 ao mesmo tempo (pico {pico['max']})")

# 2) prioridade: com a fila cheia, quem tem prioridade 0 passa na frente de quem tem 2
ordem = []


def marca(nome):
    def f(pr):
        ordem.append(nome)
        time.sleep(0.15)
        return {}
    return f


bloqueio = jobs.submit("analise", "p2", marca("primeiro"), queue="analysis")
time.sleep(0.05)
c = jobs.submit("analise", "p2", marca("cliente"), queue="analysis", prioridade=2)
a = jobs.submit("analise", "p2", marca("admin"), queue="analysis", prioridade=0)
check(a["posicao"] == 1 and c["posicao"] == 2, "administrador fica na frente do cliente na fila")
espera(lambda: c["status"] == "concluido")
check(ordem == ["primeiro", "admin", "cliente"], f"ordem de execução por prioridade: {ordem}")

# 3) cancelar na fila: sai na hora e nem roda
rodou = []
b1 = jobs.submit("analise", "p3", marca("b1"), queue="analysis")
b2 = jobs.submit("analise", "p3", lambda pr: rodou.append(1) or {}, queue="analysis")
jobs.cancelar(b2["id"])
check(b2["status"] == "cancelado", "tarefa na fila cancelada na hora")
espera(lambda: b1["status"] == "concluido")
time.sleep(0.3)
check(not rodou, "tarefa cancelada não chegou a rodar")

# 4) cancelar rodando: encerra o FFmpeg na hora
procs = []
orig = jobs.registrar


def espia(p):
    procs.append(p)
    orig(p)


jobs.registrar = espia


def ffmpeg_longo(pr):
    ff.run_with_progress([ff.ffmpeg(), "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30", "-t", "600",
                          "-f", "null", "-"], 600, lambda x: pr(x, "exportando"))
    return {}


r = jobs.submit("render", "p4", ffmpeg_longo, queue="render")
check(espera(lambda: procs and r["pct"] > 0, 20), "FFmpeg começou e está mandando progresso")
t0 = time.time()
jobs.cancelar(r["id"])
check(espera(lambda: r["status"] == "cancelado", 10), f"tarefa rodando ficou 'cancelado' ({time.time() - t0:.1f}s)")
check(procs and procs[0].poll() is not None, "o processo do FFmpeg foi encerrado")

# 5) cancelar dentro de ff.run (sem progresso)
procs.clear()
r2 = jobs.submit("render", "p4", lambda pr: ff.run([ff.ffmpeg(), "-y", "-f", "lavfi", "-i", "testsrc", "-t", "600",
                                                     "-f", "null", "-"]) and {}, queue="render")
check(espera(lambda: procs, 10), "ff.run registrou o processo")
jobs.cancelar(r2["id"])
check(espera(lambda: r2["status"] == "cancelado", 10), "ff.run cancelado também para na hora")

# 6) erro continua aparecendo como erro, e a consulta não expõe campos internos
e = jobs.submit("render", "p5", lambda pr: 1 / 0, queue="render")
espera(lambda: e["status"] != "na fila" and e["status"] != "processando")
check(e["status"] == "erro" and "division" in (e["error"] or ""), "erro comum continua como 'erro'")
pub = jobs.for_project("p5")[0]
check("_fn" not in pub and "cancelar" not in pub and "_seq" not in pub, "consulta sem campos internos")
check(jobs.resumo()["filas"]["render"]["limite"] == 2, "resumo da fila para o administrador")

print("\nRESULTADO:", "TUDO OK" if not falhas else f"{falhas} FALHA(S)")
sys.exit(1 if falhas else 0)

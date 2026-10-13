"""Fila de tarefas em segundo plano (v1.8: fila com limite, prioridade e cancelamento).

Três filas, cada uma com um limite de tarefas rodando ao mesmo tempo:
  - analysis (análise/transcrição): 1 por vez  (VOX_ANALISES)
  - render   (exportações):         2 por vez quando há 4 núcleos ou mais, senão 1  (VOX_RENDERS)
  - download (baixar, prévias, envios): 2 por vez  (VOX_DOWNLOADS)

Quem espera na fila sai por ordem de prioridade (responsável e administradores primeiro, depois a equipe,
depois os clientes) e, dentro da mesma prioridade, por ordem de chegada. Cada tarefa mostra a posição na fila.

Cancelar: uma tarefa na fila sai na hora; uma tarefa rodando para no próximo aviso de progresso e os processos
do FFmpeg/yt-dlp que ela abriu são encerrados na mesma hora (eles se registram aqui com `registrar`)."""
from __future__ import annotations

import os
import subprocess
import threading
import time
import traceback
import uuid
from typing import Callable

STATUS_ATIVOS = ("na fila", "processando")


class Cancelado(Exception):
    """Levantada dentro da tarefa quando alguém clica em Cancelar."""

    def __init__(self, msg: str = "Cancelado por você."):
        super().__init__(msg)


def _env_int(nome: str, padrao: int) -> int:
    v = os.environ.get(nome, "").strip()
    return int(v) if v.isdigit() and int(v) > 0 else padrao


def _padrao_renders() -> int:
    try:
        from ..engine.ffmpeg_tools import cpu_threads
        n = cpu_threads()
    except Exception:
        n = os.cpu_count() or 2
    return 2 if n >= 4 else 1


LIMITES = {"analysis": _env_int("VOX_ANALISES", 1), "render": _env_int("VOX_RENDERS", _padrao_renders()),
           "download": _env_int("VOX_DOWNLOADS", 2)}
PRIORIDADE = {"dono": 0, "admin": 0, "equipe": 1, "cliente": 2}
GUARDAR_HORAS = 24  # tarefas terminadas ficam visíveis por um dia e depois saem da memória

JOBS: dict[str, dict] = {}
_lock = threading.RLock()
_espera: dict[str, list[dict]] = {q: [] for q in LIMITES}   # tarefas esperando, por fila
_rodando: dict[str, int] = {q: 0 for q in LIMITES}          # quantas estão rodando agora, por fila
_procs: dict[str, set] = {}                                 # id da tarefa -> processos abertos por ela
_local = threading.local()                                  # qual tarefa a thread atual está executando
_seq = 0


def _fila(nome: str) -> str:
    return nome if nome in LIMITES else "analysis"


def _quem_pede() -> tuple[str | None, int]:
    try:
        from . import contas
        u = contas.atual.get()
    except Exception:
        u = None
    if not u:
        return None, 0
    return u.get("id"), PRIORIDADE.get(u.get("papel"), 1)


def submit(kind: str, project_id: str, fn: Callable[[Callable[[float, str], None]], dict], queue: str = "analysis",
           label: str = "", prioridade: int | None = None) -> dict:
    global _seq
    jid = uuid.uuid4().hex[:10]
    dono, prio = _quem_pede()
    if prioridade is not None:
        prio = prioridade
    q = _fila(queue)
    job = {"id": jid, "kind": kind, "project": project_id, "label": label, "status": "na fila", "pct": 0.0,
           "msg": "Aguardando na fila…", "result": None, "error": None, "created": time.time(), "fila": q,
           "prioridade": prio, "pedido_por": dono, "posicao": 0, "cancelar": False, "_fn": fn}
    with _lock:
        _seq += 1
        job["_seq"] = _seq
        JOBS[jid] = job
        _espera[q].append(job)
        _limpar_antigos()
    _despachar(q)
    return job


def _proximo(q: str) -> dict | None:
    lst = _espera[q]
    if not lst:
        return None
    lst.sort(key=lambda j: (j["prioridade"], j["_seq"]))
    return lst.pop(0)


def _atualizar_posicoes(q: str) -> None:
    lst = sorted(_espera[q], key=lambda j: (j["prioridade"], j["_seq"]))
    for i, j in enumerate(lst, 1):
        j["posicao"] = i
        j["msg"] = "Na fila — é o próximo" if i == 1 else f"Na fila — posição {i}"


def _despachar(q: str) -> None:
    iniciar = []
    with _lock:
        while _rodando[q] < LIMITES[q]:
            job = _proximo(q)
            if job is None:
                break
            _rodando[q] += 1
            job["status"], job["posicao"], job["msg"] = "processando", 0, "Começando…"
            iniciar.append(job)
        _atualizar_posicoes(q)
    for job in iniciar:
        threading.Thread(target=_executar, args=(job,), name=f"{q}-{job['id']}", daemon=True).start()


def _executar(job: dict) -> None:
    q = job["fila"]
    fn = job.pop("_fn", None)
    _local.job = job

    def progress(pct: float, msg: str = ""):
        if job["cancelar"]:
            raise Cancelado()
        job["pct"] = round(max(0.0, min(1.0, pct)), 4)
        if msg:
            job["msg"] = msg

    try:
        if job["cancelar"]:
            raise Cancelado()
        job["inicio"] = time.time()
        job["result"] = fn(progress) if fn else None
        if job["cancelar"]:
            raise Cancelado()
        job["status"], job["pct"], job["msg"] = "concluido", 1.0, "Concluído"
    except Exception as exc:
        if job["cancelar"] or isinstance(exc, Cancelado):
            job["status"], job["error"], job["msg"] = "cancelado", None, "Cancelado"
        else:  # o erro aparece no painel, com detalhe no terminal
            traceback.print_exc()
            job["status"], job["error"], job["msg"] = "erro", str(exc), "Erro"
    finally:
        job["fim"] = time.time()
        _local.job = None
        with _lock:
            _procs.pop(job["id"], None)
            _rodando[q] = max(0, _rodando[q] - 1)
        _despachar(q)


def cancelar(jid: str) -> dict | None:
    """Cancela uma tarefa: na fila sai na hora; rodando, encerra os processos dela e para no próximo progresso."""
    with _lock:
        job = JOBS.get(jid)
        if not job or job["status"] not in STATUS_ATIVOS:
            return job
        job["cancelar"] = True
        if job["status"] == "na fila":
            q = job["fila"]
            if job in _espera[q]:
                _espera[q].remove(job)
            job.pop("_fn", None)
            job["status"], job["msg"], job["fim"] = "cancelado", "Cancelado", time.time()
            _atualizar_posicoes(q)
            return job
        job["msg"] = "Cancelando…"
        procs = list(_procs.get(jid, ()))
    for p in procs:
        _encerrar(p)
    return job


def _encerrar(p) -> None:
    try:
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=3)
            except Exception:
                p.kill()
    except Exception:
        pass


# ---------- processos abertos pelas tarefas (para o Cancelar encerrar na hora) ----------

def tarefa_atual() -> dict | None:
    return getattr(_local, "job", None)


def registrar(proc: subprocess.Popen) -> None:
    """Chamado logo depois de abrir um processo (FFmpeg, yt-dlp): se a tarefa já foi cancelada, encerra."""
    job = tarefa_atual()
    if not job:
        return
    with _lock:
        _procs.setdefault(job["id"], set()).add(proc)
    if job["cancelar"]:
        _encerrar(proc)


def liberar(proc: subprocess.Popen) -> None:
    job = tarefa_atual()
    if not job:
        return
    with _lock:
        s = _procs.get(job["id"])
        if s:
            s.discard(proc)


def conferir_cancelado() -> None:
    """Para quem roda laços longos sem progresso: levanta Cancelado se a tarefa atual foi cancelada."""
    job = tarefa_atual()
    if job and job["cancelar"]:
        raise Cancelado()


# ---------- consultas ----------

def _publico(j: dict) -> dict:
    return {k: v for k, v in j.items() if not k.startswith("_") and k != "cancelar"}


def _limpar_antigos() -> None:
    limite = time.time() - GUARDAR_HORAS * 3600
    for jid in [k for k, j in JOBS.items() if j["status"] not in STATUS_ATIVOS and j.get("fim", j["created"]) < limite]:
        JOBS.pop(jid, None)


def get(jid: str) -> dict | None:
    with _lock:
        j = JOBS.get(jid)
        return _publico(j) if j else None


def for_project(pid: str) -> list[dict]:
    with _lock:
        jobs = [_publico(j) for j in JOBS.values() if j["project"] == pid]
    return sorted(jobs, key=lambda j: -j["created"])[:20]


def ativos() -> int:
    with _lock:
        return sum(1 for j in JOBS.values() if j["status"] in STATUS_ATIVOS)


def atividade(janela: float = 600.0) -> list[dict]:
    """Trabalhos de todos os projetos: os que estão andando e os que terminaram há pouco (barra de atividade do topo)."""
    agora = time.time()
    with _lock:
        lista = [_publico(j) for j in JOBS.values()
                 if j["status"] in STATUS_ATIVOS or agora - j.get("fim", j["created"]) < janela]
    for j in lista:
        j.pop("result", None)
    return sorted(lista, key=lambda j: (j["status"] not in STATUS_ATIVOS, -j["created"]))[:30]


def resumo() -> dict:
    """Situação da fila para a área do administrador."""
    with _lock:
        filas = {q: {"limite": LIMITES[q], "rodando": _rodando[q], "esperando": len(_espera[q])} for q in LIMITES}
    return {"filas": filas}

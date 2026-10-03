"""Fila de tarefas em segundo plano (análise e renderização em filas separadas)."""
from __future__ import annotations

import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

_analysis = ThreadPoolExecutor(max_workers=1, thread_name_prefix="analise")
_render = ThreadPoolExecutor(max_workers=1, thread_name_prefix="render")
JOBS: dict[str, dict] = {}
_lock = threading.Lock()


def submit(kind: str, project_id: str, fn: Callable[[Callable[[float, str], None]], dict], queue: str = "analysis",
           label: str = "") -> dict:
    jid = uuid.uuid4().hex[:10]
    job = {"id": jid, "kind": kind, "project": project_id, "label": label, "status": "na fila", "pct": 0.0,
           "msg": "Aguardando na fila…", "result": None, "error": None, "created": time.time()}
    with _lock:
        JOBS[jid] = job

    def progress(pct: float, msg: str = ""):
        job["pct"] = round(max(0.0, min(1.0, pct)), 4)
        if msg:
            job["msg"] = msg

    def run():
        job["status"] = "processando"
        try:
            job["result"] = fn(progress)
            job["status"], job["pct"], job["msg"] = "concluido", 1.0, "Concluído"
        except Exception as exc:  # o erro aparece no painel, com detalhe no terminal
            traceback.print_exc()
            job["status"], job["error"], job["msg"] = "erro", str(exc), "Erro"

    (_render if queue == "render" else _analysis).submit(run)
    return job


def for_project(pid: str) -> list[dict]:
    with _lock:
        jobs = [j for j in JOBS.values() if j["project"] == pid]
    return sorted(jobs, key=lambda j: -j["created"])[:20]

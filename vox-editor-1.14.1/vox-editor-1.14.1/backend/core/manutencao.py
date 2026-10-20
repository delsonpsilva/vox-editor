"""Manutenção automática (v1.8): cópia de segurança diária e limpeza de arquivos temporários.

Roda sozinha em segundo plano, no PC e no online, uma vez por dia (de madrugada, ou assim que o programa abrir
se passou mais de um dia da última vez). Também pode ser chamada pelo responsável em Configurações.

Cópia diária (dados/backups/diario-AAAAMMDD.tar.gz, guarda as últimas 7):
  configurações, contas das redes, contas de pessoas (vox.db, copiado com segurança mesmo em uso), fila de
  publicações, marca e os .json de cada projeto (edição, cortes, montagem). Os vídeos ficam de fora: são grandes
  e o original continua na pasta do projeto.

Limpeza automática (nunca toca em vídeo original, exportado que aparece na lista ou mídia da montagem):
  - restos de exportação/renderização interrompida (tmp_*) com mais de 6 horas;
  - downloads pela metade (*.part, *.ytdl) com mais de 1 dia;
  - exportados "órfãos" (arquivo na pasta renders que não está na lista do projeto, de exportação cancelada
    ou que falhou) com mais de 1 dia;
  - miniaturas e prévias do cache sem uso há mais de 30 dias (o sistema refaz quando precisar)."""
from __future__ import annotations

import json
import os
import sqlite3
import tarfile
import tempfile
import threading
import time
import traceback
from pathlib import Path

from . import store

PASTA_BACKUP = store.DATA / "backups"
ESTADO = store.DATA / "manutencao.json"
GUARDAR_COPIAS = int(os.environ.get("VOX_BACKUPS_DIAS", "7") or 7)
HORA = int(os.environ.get("VOX_MANUTENCAO_HORA", "3") or 3)  # 3h da manhã (hora do servidor/PC)
HORAS = 3600
DIA = 24 * HORAS

_lock = threading.Lock()
_iniciado = False


# ---------- estado (última cópia, última limpeza) ----------

def estado() -> dict:
    try:
        return json.loads(ESTADO.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _gravar_estado(**campos) -> None:
    e = estado()
    e.update(campos)
    tmp = ESTADO.with_suffix(".tmp")
    tmp.write_text(json.dumps(e, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, ESTADO)


# ---------- cópia de segurança ----------

def _copia_banco(origem: Path, destino: Path) -> bool:
    """Copia o SQLite com a API de backup (consistente mesmo com o sistema gravando ao mesmo tempo)."""
    try:
        src = sqlite3.connect(str(origem), timeout=15)
        try:
            dst = sqlite3.connect(str(destino))
            with dst:
                src.backup(dst)
            dst.close()
        finally:
            src.close()
        return True
    except Exception:
        traceback.print_exc()
        return False


def _arquivos_da_copia() -> list[tuple[Path, str]]:
    """(arquivo, nome dentro da cópia). Sem vídeos, sem a própria pasta de cópias, sem modelos de IA."""
    out: list[tuple[Path, str]] = []
    base = store.DATA
    pular = {PASTA_BACKUP.resolve(), store.MODELS.resolve()}
    for raiz, pastas, arquivos in os.walk(base):
        r = Path(raiz)
        pastas[:] = [p for p in pastas if (r / p).resolve() not in pular and p not in ("cache", "renders", "midias")]
        for nome in arquivos:
            f = r / nome
            rel = f.relative_to(base).as_posix()
            if nome.endswith(".json") or rel.startswith("marca/"):
                if not nome.endswith(".tmp"):
                    out.append((f, rel))
    return out


def fazer_backup(motivo: str = "automático") -> dict:
    """Cria dados/backups/diario-AAAAMMDD.tar.gz (substitui a do mesmo dia) e apaga as mais antigas."""
    with _lock:
        PASTA_BACKUP.mkdir(parents=True, exist_ok=True)
        nome = time.strftime("diario-%Y%m%d.tar.gz")
        destino = PASTA_BACKUP / nome
        tmp = destino.with_suffix(".tmp")
        t0 = time.time()
        n = 0
        with tempfile.TemporaryDirectory() as td:
            with tarfile.open(tmp, "w:gz") as tar:
                for f, rel in _arquivos_da_copia():
                    try:
                        tar.add(str(f), arcname=rel)
                        n += 1
                    except (OSError, FileNotFoundError):
                        pass  # arquivo sumiu no meio (projeto apagado): segue
                db = store.DATA / "vox.db"
                if db.exists():
                    copia = Path(td) / "vox.db"
                    if _copia_banco(db, copia):
                        tar.add(str(copia), arcname="vox.db")
                        n += 1
            os.replace(tmp, destino)
        antigas = sorted(PASTA_BACKUP.glob("diario-*.tar.gz"), key=lambda p: p.name, reverse=True)[GUARDAR_COPIAS:]
        for a in antigas:
            a.unlink(missing_ok=True)
        info = {"arquivo": nome, "quando": time.time(), "tamanho": destino.stat().st_size, "itens": n,
                "segundos": round(time.time() - t0, 1), "motivo": motivo}
        _gravar_estado(backup=info)
        return info


def listar_backups() -> list[dict]:
    if not PASTA_BACKUP.exists():
        return []
    return [{"arquivo": p.name, "tamanho": p.stat().st_size, "quando": p.stat().st_mtime}
            for p in sorted(PASTA_BACKUP.glob("diario-*.tar.gz"), key=lambda p: p.name, reverse=True)]


def caminho_backup(nome: str) -> Path | None:
    if "/" in nome or "\\" in nome or not nome.startswith("diario-") or not nome.endswith(".tar.gz"):
        return None
    f = PASTA_BACKUP / nome
    return f if f.is_file() else None


# ---------- limpeza ----------

def _velho(f: Path, idade: float, agora: float) -> bool:
    try:
        st = f.stat()
        return agora - max(st.st_mtime, getattr(st, "st_atime", 0) if f.parent.name == "cache" else 0) > idade
    except OSError:
        return False


def _apagar(f: Path) -> int:
    try:
        n = f.stat().st_size
        f.unlink()
        return n
    except OSError:
        return 0


def limpar(motivo: str = "automático") -> dict:
    """Apaga só o que o sistema não usa mais (ver o topo do arquivo). Devolve quanto espaço liberou."""
    from . import jobs
    agora = time.time()
    liberado, apagados = 0, 0
    if jobs.ativos():  # com exportação rodando, não mexe em tmp_ de jeito nenhum (só no que é bem antigo)
        idade_tmp = 2 * DIA
    else:
        idade_tmp = 6 * HORAS
    for pasta in list(store.PROJECTS.iterdir()) if store.PROJECTS.exists() else []:
        if not pasta.is_dir():
            continue
        try:
            proj = json.loads((pasta / "project.json").read_text(encoding="utf-8"))
        except Exception:
            proj = None
        # restos de renderização e downloads pela metade
        for padrao, idade in (("tmp_*", idade_tmp), ("renders/tmp_*", idade_tmp), ("*.part", DIA),
                              ("*.ytdl", DIA), ("*.part-Frag*", DIA), ("midias/*.tmp.*", idade_tmp)):
            for f in pasta.glob(padrao):
                if f.is_file() and _velho(f, idade, agora):
                    liberado += _apagar(f)
                    apagados += 1
        # exportados órfãos (não estão na lista do projeto): exportação cancelada ou que falhou
        rd = pasta / "renders"
        if proj is not None and rd.is_dir():
            listados = {r.get("file") for r in proj.get("renders", []) if isinstance(r, dict)}
            for f in rd.iterdir():
                if f.is_file() and f.name not in listados and not f.name.startswith(".") \
                        and f.suffix.lower() in (".mp4", ".m4a", ".mov", ".webm") and _velho(f, DIA, agora):
                    liberado += _apagar(f)
                    apagados += 1
        # cache sem uso há 30 dias
        cache = pasta / "cache"
        if cache.is_dir():
            for f in cache.iterdir():
                if f.is_file() and _velho(f, 30 * DIA, agora):
                    liberado += _apagar(f)
                    apagados += 1
    info = {"quando": agora, "liberado": liberado, "arquivos": apagados, "motivo": motivo}
    _gravar_estado(limpeza=info)
    return info


# ---------- agendador ----------

def _hora_de_rodar(agora: float) -> bool:
    e = estado()
    ultima = max((e.get("backup") or {}).get("quando", 0), 0)
    if agora - ultima > 26 * HORAS:  # ficou desligado: roda assim que abrir
        return True
    lt = time.localtime(agora)
    return lt.tm_hour == HORA and agora - ultima > 20 * HORAS


def rodar_agora(motivo: str = "automático") -> dict:
    out = {}
    try:
        out["backup"] = fazer_backup(motivo)
    except Exception as e:
        traceback.print_exc()
        out["backup_erro"] = str(e)
        _gravar_estado(backup_erro={"quando": time.time(), "erro": str(e)[:300]})
    try:
        out["limpeza"] = limpar(motivo)
    except Exception as e:
        traceback.print_exc()
        out["limpeza_erro"] = str(e)
    return out


def _laco() -> None:
    time.sleep(int(os.environ.get("VOX_MANUTENCAO_ESPERA", "90") or 90))  # deixa o programa abrir primeiro
    while True:
        try:
            if _hora_de_rodar(time.time()):
                rodar_agora()
        except Exception:
            traceback.print_exc()
        time.sleep(15 * 60)


def iniciar() -> None:
    global _iniciado
    if _iniciado or os.environ.get("VOX_SEM_MANUTENCAO") == "1":
        return
    _iniciado = True
    threading.Thread(target=_laco, name="manutencao", daemon=True).start()

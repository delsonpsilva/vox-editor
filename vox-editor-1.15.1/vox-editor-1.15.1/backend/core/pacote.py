"""Pacote do projeto (.vox): leva um projeto inteiro de uma instalação para outra (PC ↔ versão online),
sem perder nada e sem analisar de novo — vídeo, transcrição, análise, cortes, edições e vídeos exportados.

É um .zip sem compressão (vídeo já é comprimido), gerado em fluxo: não precisa de espaço extra em disco."""
from __future__ import annotations

import json
import shutil
import time
import uuid
import zipfile
from pathlib import Path
from typing import Callable, Iterator, Optional

from . import store

FORMATO = 1
# refeitos sozinhos quando faltam: não vale a pena levar
_PULAR_PASTAS = {"cache"}
_PULAR_ARQUIVOS = {"audio48k.raw"}


def arquivos(pid: str, com_exportados: bool = True) -> list[tuple[Path, str]]:
    folder = store.pdir(pid)
    out = []
    for f in sorted(folder.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(folder)
        if rel.parts[0] in _PULAR_PASTAS or rel.name in _PULAR_ARQUIVOS or rel.suffix == ".tmp":
            continue
        if not com_exportados and rel.parts[0] == "renders":
            continue
        out.append((f, rel.as_posix()))
    return out


def tamanho(pid: str, com_exportados: bool = True) -> int:
    return sum(f.stat().st_size for f, _ in arquivos(pid, com_exportados))


class _Saida:
    """Arquivo "só de escrita" que guarda os bytes até o gerador entregar (zip em fluxo)."""

    def __init__(self):
        self.buf = bytearray()
        self.pos = 0

    def write(self, b):
        self.buf += b
        self.pos += len(b)
        return len(b)

    def tell(self):
        return self.pos

    def flush(self):
        pass

    def pegar(self) -> bytes:
        b = bytes(self.buf)
        self.buf.clear()
        return b


def gerar(pid: str, com_exportados: bool = True, progresso: Optional[Callable[[int, int], None]] = None,
          bloco: int = 4 * 1024 * 1024) -> Iterator[bytes]:
    """Gera o .vox em pedaços (para baixar ou enviar direto pela internet)."""
    proj = store.load(pid)
    lista = arquivos(pid, com_exportados)
    total = sum(f.stat().st_size for f, _ in lista)
    feito = 0
    saida = _Saida()
    manifesto = {"vox_pacote": FORMATO, "nome": proj.get("name", ""), "criado": time.time(),
                 "arquivos": len(lista), "bytes": total}
    with zipfile.ZipFile(saida, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
        zf.writestr("vox-pacote.json", json.dumps(manifesto, ensure_ascii=False))
        yield saida.pegar()
        for f, rel in lista:
            with open(f, "rb") as src, zf.open("projeto/" + rel, "w", force_zip64=True) as dst:
                while True:
                    b = src.read(bloco)
                    if not b:
                        break
                    dst.write(b)
                    feito += len(b)
                    if progresso:
                        progresso(feito, total)
                    pedaco = saida.pegar()
                    if pedaco:
                        yield pedaco
            pedaco = saida.pegar()
            if pedaco:
                yield pedaco
    yield saida.pegar()


def importar(zip_path: Path) -> dict:
    """Cria um projeto novo a partir do .vox. Continua exatamente como estava (sem nova análise)."""
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile:
        raise ValueError("Esse arquivo não é um pacote de projeto do VOX Editor (.vox).")
    with zf:
        nomes = zf.namelist()
        if "vox-pacote.json" not in nomes or "projeto/project.json" not in nomes:
            raise ValueError("Esse arquivo não é um pacote de projeto do VOX Editor (.vox).")
        man = json.loads(zf.read("vox-pacote.json"))
        if int(man.get("vox_pacote", 0)) > FORMATO:
            raise ValueError("Esse pacote veio de uma versão mais nova do programa. Atualize este aqui primeiro.")
        pid = uuid.uuid4().hex[:12]
        dest = store.PROJECTS / pid
        tmp = store.PROJECTS / f"_importando-{pid}"
        tmp.mkdir(parents=True)
        try:
            raiz = tmp.resolve()
            for info in zf.infolist():
                if not info.filename.startswith("projeto/") or info.is_dir():
                    continue
                rel = info.filename[len("projeto/"):]
                alvo = (tmp / rel).resolve()
                if raiz not in alvo.parents:  # nunca grava fora da pasta do projeto
                    raise ValueError("Pacote com caminho inválido.")
                alvo.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(alvo, "wb") as dst:
                    shutil.copyfileobj(src, dst, 4 * 1024 * 1024)
            proj = json.loads((tmp / "project.json").read_text(encoding="utf-8"))
            proj["id"] = pid
            proj["imported"] = time.time()
            if proj.get("status") not in ("pronto", "erro"):  # estava no meio de algo: deixa para tentar de novo
                proj["status"] = "erro"
                proj["progress"] = {"pct": 0, "msg": "O trabalho foi interrompido na outra instalação. "
                                                     "Clique em Tentar novamente."}
            (tmp / "renders").mkdir(exist_ok=True)
            (tmp / "project.json").write_text(json.dumps(proj, ensure_ascii=False), encoding="utf-8")
            tmp.rename(dest)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
    return store.load(pid)


def nome_arquivo(proj: dict) -> str:
    import re
    base = re.sub(r"[^\w\- ]+", "", proj.get("name", "projeto"), flags=re.UNICODE).strip()[:60] or "projeto"
    return f"{base}.vox"

"""Montagem (editor manual multicamadas), trilhas sonoras, mídias, bancos grátis e remoção de fundo."""
from __future__ import annotations

from fastapi import APIRouter

from .comum import *  # noqa: F401,F403

router = APIRouter()


@router.post("/api/montagem/novo")
def montagem_novo(data: dict = Body(default={})):
    proj = montagem.projeto_em_branco(str(data.get("name") or "")[:120], data.get("formato") or "9:16")
    return {"id": proj["id"]}


@router.get("/api/projects/{pid}/montagem")
def montagem_get(pid: str):
    m = _404(lambda: montagem.carregar(pid))
    _previas_pendentes(pid, m)
    return m


@router.put("/api/projects/{pid}/montagem")
def montagem_put(pid: str, data: dict = Body(...)):
    return _404(lambda: montagem.salvar(pid, data))


@router.post("/api/projects/{pid}/montagem/recomecar")
def montagem_recomecar(pid: str, data: dict = Body(default={})):
    return _404(lambda: montagem.recomecar(pid, data.get("formato")))


# ---------- trilhas sonoras livres ----------

@router.get("/api/trilhas/humores")
def trilhas_humores():
    return trilhas.HUMORES


@router.get("/api/trilhas")
def trilhas_buscar(q: str = "", humor: str = "", pagina: int = 1):
    try:
        return trilhas.buscar(q, humor, pagina)
    except RuntimeError as e:
        raise HTTPException(502, str(e))


@router.post("/api/projects/{pid}/trilhas/{tid}")
def trilha_no_projeto(pid: str, tid: str):
    """Baixa a trilha livre para as mídias da montagem (com o crédito guardado junto)."""
    _404(lambda: store.load(pid))
    _limites(minutos=False)
    try:
        arq, f = trilhas.baixar(tid, montagem.pasta_midias(pid))
        return montagem.adicionar_midia(pid, arq, f"{f['title'] or 'Música'} — {f['creator'] or 'autor'}{arq.suffix}",
                                        {"credito": f["credito"], "licenca": f["license"], "trilha": f["id"]})
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except (RuntimeError, ValueError) as e:
        raise HTTPException(400, str(e))


@router.post("/api/projects/{pid}/minhas-musicas/{nome}")
def minha_musica_no_projeto(pid: str, nome: str):
    """Coloca uma música da biblioteca pessoal (Marca → Músicas) nas mídias da montagem."""
    import shutil
    _404(lambda: store.load(pid))
    src = pipeline.musica_path(nome)
    if not src:
        raise HTTPException(404, "Música não encontrada")
    dest = montagem.pasta_midias(pid) / f"{secrets.token_hex(4)}_{nome}"
    shutil.copy(src, dest)
    try:
        return montagem.adicionar_midia(pid, dest, nome)
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, f"Não consegui usar essa música: {str(e)[:200]}")


@router.post("/api/trilhas/{tid}/guardar")
def trilha_guardar(tid: str):
    """Guarda a trilha livre nas "Minhas músicas" (serve de fundo musical também na edição automática)."""
    try:
        arq, f = trilhas.baixar(tid, pipeline.MUSICAS)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    cred = pipeline.MUSICAS / "creditos.txt"
    linhas = cred.read_text(encoding="utf-8").splitlines() if cred.exists() else []
    linha = f"{arq.name}: {f['credito']}"
    if linha not in linhas:
        cred.write_text("\n".join(linhas + [linha]) + "\n", encoding="utf-8")
    return {"nome": arq.name, "credito": f["credito"]}


@router.post("/api/projects/{pid}/midias")
async def montagem_upload(pid: str, request: Request):
    _404(lambda: store.load(pid))
    _limites(minutos=False)
    from urllib.parse import unquote
    nome = unquote(request.headers.get("x-filename", "arquivo"))
    nome = re.sub(r"[\\/:*?\"<>|]+", "_", nome).strip() or "arquivo"
    if not montagem.tipo_por_extensao(nome):
        raise HTTPException(400, "Tipo de arquivo não aceito. Envie vídeo, imagem (JPG, PNG, WEBP) ou áudio.")
    pasta = montagem.pasta_midias(pid)
    dest = pasta / f"{secrets.token_hex(4)}_{nome}"
    size, limit = 0, MAX_UPLOAD_GB * 1024 ** 3
    try:
        with open(dest, "wb") as fh:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"Arquivo maior que {MAX_UPLOAD_GB:g} GB")
                fh.write(chunk)
        if size == 0:
            raise HTTPException(400, "Arquivo vazio")
        item = montagem.adicionar_midia(pid, dest, nome)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, f"Não consegui usar esse arquivo: {str(e)[:200]}")
    _previas_pendentes(pid, montagem.carregar(pid))
    return item


@router.get("/api/projects/{pid}/midias/{mid}")
def montagem_midia(pid: str, mid: str, original: int = 0):
    return FileResponse(_404(lambda: montagem.caminho_midia(pid, mid, previa=not original)))


@router.get("/api/projects/{pid}/midias/{mid}/thumb")
def montagem_thumb(pid: str, mid: str, t: float = 0.0):
    try:
        f = montagem.miniatura(pid, mid, t)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception:
        raise HTTPException(404, "Sem imagem")
    return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})


@router.delete("/api/projects/{pid}/midias/{mid}")
def montagem_midia_del(pid: str, mid: str):
    try:
        return _404(lambda: montagem.remover_midia(pid, mid))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/projects/{pid}/montagem/exportar")
def montagem_exportar(pid: str, data: dict = Body(default={})):
    _404(lambda: store.load(pid))
    if data.get("montagem"):
        _404(lambda: montagem.salvar(pid, data["montagem"]))
    jobs.submit("montagem", pid, lambda pr: montagem.exportar(pid, data, pr), queue="render", label="Montagem")
    return view(store.load(pid))


# ---------- 1.2: bancos grátis (Pexels e Pixabay) e remoção de fundo com IA ----------

@router.get("/api/bancos/status")
def bancos_status():
    return bancos.status()


@router.get("/api/bancos/buscar")
def bancos_buscar(fonte: str = "todos", tipo: str = "video", q: str = "", pagina: int = 1, orient: str = ""):
    try:
        return bancos.buscar(fonte, tipo, q, pagina, orient)
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@router.post("/api/projects/{pid}/bancos/{bid}")
def banco_no_projeto(pid: str, bid: str):
    """Baixa o vídeo/foto do banco grátis para as mídias da montagem (em segundo plano, com progresso)."""
    _404(lambda: store.load(pid))
    _limites(minutos=False)
    try:
        info = bancos.item(bid)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))

    def tarefa(pr):
        arq, it = bancos.baixar(bid, montagem.pasta_midias(pid), pr)
        nome = (it.get("nome") or ("Vídeo" if it["tipo"] == "video" else "Foto")) + f" — {it['autor'] or it['fonte']}"
        md = montagem.adicionar_midia(pid, arq, nome[:100] + it["ext"],
                                      {"credito": it["credito"], "licenca": bancos.FONTES[it["fonte"]], "banco": bid})
        _previas_pendentes(pid, montagem.carregar(pid))
        return md

    j = jobs.submit("banco", pid, tarefa, queue="download", label="Banco grátis")
    j["ref"] = bid
    return {"job": j["id"], "tipo": info["tipo"]}


@router.get("/api/fundo/status")
def fundo_status():
    from ..core import fundo_ia
    q = fundo_ia.qualidade()
    return {"disponivel": fundo_ia.disponivel(), "qualidade": q, "baixado": fundo_ia.modelo_baixado(q),
            "tamanho_mb": round(fundo_ia.MODELOS[q][2] / 1e6)}


@router.post("/api/projects/{pid}/montagem/sem-fundo")
def montagem_sem_fundo(pid: str, data: dict = Body(...)):
    _404(lambda: store.load(pid))
    if data.get("montagem"):
        _404(lambda: montagem.salvar(pid, data["montagem"]))
    item_id = str(data.get("item") or "")
    if any(j["kind"] == "semfundo" and j["status"] in ("na fila", "processando") and j.get("ref") == item_id
           for j in jobs.for_project(pid)):
        raise HTTPException(409, "Esse pedaço já está tirando o fundo.")
    j = jobs.submit("semfundo", pid, lambda pr: montagem.sem_fundo(pid, item_id, pr), queue="analysis",
                    label="Remover fundo (IA)")
    j["ref"] = item_id
    return {"job": j["id"]}


@router.post("/api/projects/{pid}/midias/{mid}/aplicado")
def montagem_substituicao_aplicada(pid: str, mid: str):
    return _404(lambda: montagem.substituicao_aplicada(pid, mid))


# ---------- 1.12: legenda automática da fala, forma de onda, narração e congelar quadro ----------

@router.post("/api/projects/{pid}/montagem/legenda")
def montagem_legenda(pid: str, data: dict = Body(default={})):
    """Transcreve a fala da linha do tempo (só o que ainda não foi transcrito) e monta a legenda animada."""
    from ..core import montagem_som
    _404(lambda: store.load(pid))
    _limites(minutos=True)
    if data.get("montagem"):
        _404(lambda: montagem.salvar(pid, data["montagem"]))
    if any(j["kind"] == "legenda_mont" and j["status"] in ("na fila", "processando") for j in jobs.for_project(pid)):
        raise HTTPException(409, "A legenda deste projeto já está sendo feita.")
    cfg = data.get("cfg") if isinstance(data.get("cfg"), dict) else {}
    j = jobs.submit("legenda_mont", pid, lambda pr: montagem_som.gerar_legenda(pid, cfg, pr), queue="analysis",
                    label="Legenda da fala")
    return {"job": j["id"]}


@router.post("/api/projects/{pid}/montagem/legenda/montar")
def montagem_legenda_montar(pid: str, data: dict = Body(...)):
    """Remonta a legenda a partir das palavras (trocar estilo ou corrigir palavras), sem transcrever. Não grava:
    a tela coloca na montagem e salva junto."""
    from ..core import montagem_som
    m = _404(lambda: montagem.carregar(pid))
    lv = montagem_som.montar_legenda(data.get("words") or [], data.get("cfg") or {}, m["h"] > m["w"])
    if lv is None:
        raise HTTPException(400, "A legenda ficou sem nenhuma palavra.")
    if data.get("off"):
        lv["off"] = True
    return lv


@router.get("/api/projects/{pid}/midias/{mid}/onda")
def montagem_onda(pid: str, mid: str):
    from ..core import montagem_som
    try:
        return JSONResponse(_404(lambda: montagem_som.onda(pid, mid)), headers={"Cache-Control": "max-age=3600"})
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


@router.post("/api/projects/{pid}/montagem/narracao")
async def montagem_narracao(pid: str, request: Request):
    """Gravação do microfone feita na própria Montagem."""
    from ..core import montagem_som
    _404(lambda: store.load(pid))
    _limites(minutos=False)
    bruto = montagem.pasta_midias(pid) / f"gravando_{secrets.token_hex(4)}.webm"
    size = 0
    try:
        with open(bruto, "wb") as fh:
            async for chunk in request.stream():
                size += len(chunk)
                if size > 1024 ** 3:
                    raise HTTPException(413, "Gravação grande demais (máximo 1 GB).")
                fh.write(chunk)
        if size < 200:
            raise HTTPException(400, "A gravação ficou vazia. Confira o microfone e grave de novo.")
        return montagem_som.narracao(pid, bruto)
    except HTTPException:
        bruto.unlink(missing_ok=True)
        raise
    except Exception as e:
        bruto.unlink(missing_ok=True)
        raise HTTPException(400, f"Não consegui usar a gravação: {str(e)[:200]}")


@router.post("/api/projects/{pid}/montagem/congelar")
def montagem_congelar(pid: str, data: dict = Body(...)):
    from ..core import montagem_som
    _404(lambda: store.load(pid))
    try:
        return montagem_som.congelar(pid, str(data.get("src") or ""), float(data.get("t") or 0))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except (RuntimeError, ValueError) as e:
        raise HTTPException(400, str(e))

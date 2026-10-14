"""Servidor do VOX Editor: API + painel. Roda no PC (localhost) ou numa VPS (versão online).

v1.8: as rotas ficam em backend/rotas/ (uma área por arquivo) e as peças compartilhadas em backend/rotas/comum.py.
Aqui ficam só a criação do app, a entrada, as proteções (middlewares), a ordem das rotas e a tela."""
from __future__ import annotations

# os instaladores (PUBLICAR.bat, vox-atualizar) leem a versão da linha abaixo: deixe só VERSION = "x.y.z"
VERSION = "1.11.0"

from .rotas.comum import *  # noqa: F401,F403  (senha, contas, store, jobs... usados abaixo e pelos testes)
from .rotas import ROTEADORES

app = FastAPI(title="Editor IA", version=VERSION)


@app.on_event("startup")
def _start_scheduler():
    if not PASSWORD and not store.password_hash():  # v1.7: o programa do PC nunca fica sem senha
        store.set_password(SENHA_PADRAO)
        store.marcar_troca_de_senha(True)
    publish.start()  # fila de autopostagem roda em segundo plano enquanto o programa estiver aberto
    manutencao.iniciar()  # v1.8: cópia de segurança diária e limpeza automática de temporários
    # trabalhos que estavam no meio quando o programa foi fechado ficam com aviso e botão "Tentar novamente"
    for p in store.list_projects():
        if p.get("status") in ("baixando", "processando", "na fila"):
            try:
                store.update(p["id"], lambda x: x.update(status="erro", progress={"pct": 0, "msg":
                             "Interrompido porque o programa foi fechado. Clique em Tentar novamente."}))
            except Exception:
                pass


@app.middleware("http")
async def sem_cache_da_tela(request: Request, call_next):
    """A tela (HTML, JS, CSS) é sempre conferida com o servidor: depois de atualizar, a versão nova aparece na hora."""
    resp = await call_next(request)
    p = request.url.path
    if not p.startswith("/api/") and (p == "/" or p.endswith((".html", ".js", ".css", ".webmanifest"))):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.middleware("http")
async def auth(request: Request, call_next):
    path = request.url.path
    if not path.startswith("/api/") or path in _LIVRES or _RE_OAUTH.match(path) or path.startswith("/api/publico/"):
        u = _quem(request) if path.startswith("/api/oauth/") else None  # /api/publico: link assinado do webhook
        tok = contas.atual.set(u)
        try:
            return await call_next(request)
        finally:
            contas.atual.reset(tok)
    u = _quem(request)
    if u is None:
        return _negado("login necessário", 401)
    papel, metodo = u["papel"], request.method
    if papel not in ("dono", "admin"):
        if any(_bate(r, metodo, path) for r in _SO_DONO):
            return _negado("Só o responsável pela conta do VOX Editor pode mudar isso.")
        if papel == "cliente":
            if path == "/api/publish/queue" and metodo == "GET":
                return JSONResponse([])
            if path == "/api/publish/status":
                return JSONResponse({"bloqueado": True, "networks": {}, "destinos": []})
            if path.startswith("/api/publish/"):
                return _negado("Publicar nas redes fica com o responsável pela conta. Baixe o vídeo em Exportados.")
            m = _RE_PROJ.match(path)
            if m:
                dono = _dono_do_projeto(m.group(1))
                if dono is not None and dono != u["id"]:
                    return _negado("Projeto não encontrado", 404)
    tok = contas.atual.set(u)
    try:
        return await call_next(request)
    finally:
        contas.atual.reset(tok)


for _r in ROTEADORES:  # mesma ordem de antes: a primeira rota que bate é a que vale
    app.include_router(_r)

app.mount("/fontes", StaticFiles(directory=str(store.FONTS)), name="fontes")


app.mount("/", StaticFiles(directory=str(FRONT), html=True), name="painel")


def main():
    import uvicorn
    if os.name != "nt" and os.environ.get("EDITOR_NICE"):
        try:  # no servidor, o editor cede a vez para os outros sistemas quando eles precisam do processador
            os.nice(int(os.environ["EDITOR_NICE"]))
        except Exception:
            pass
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8765"))
    if host in ("127.0.0.1", "localhost") and os.environ.get("NO_BROWSER") != "1":
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    print(f"\n  Editor IA rodando em http://{'127.0.0.1' if host == '0.0.0.0' else host}:{port}\n"
          f"  (feche esta janela para desligar)\n")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()

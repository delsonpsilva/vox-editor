"""Testes da v1.1.3: o programa do PC usa as contas das redes que ficam salvas no online.
Sobe uma "versão online" de verdade (com senha) numa porta local, finge uma conta do YouTube conectada lá
e confere: status no PC, link de login assinado, login sem link bloqueado, publicação enviada para a fila do online."""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PC_DADOS = ROOT / "teste_dados_pc"
ON_DADOS = Path(tempfile.mkdtemp()) / "online"
shutil.rmtree(PC_DADOS, ignore_errors=True)
ON_DADOS.mkdir(parents=True)
os.environ["EDITOR_DATA"] = str(PC_DADOS)
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

falhas = 0


def check(cond, msg):
    global falhas
    print(("OK   " if cond else "FALHOU ") + msg)
    if not cond:
        falhas += 1


s = socket.socket()
s.bind(("127.0.0.1", 0))
PORTA = s.getsockname()[1]
s.close()
URL = f"http://127.0.0.1:{PORTA}"
# conta do YouTube "conectada" no online + app oficial cadastrado (sem rede de verdade)
(ON_DADOS / "contas.json").write_text(json.dumps({"youtube": {"refresh_token": "x", "channel": "Canal Teste"}}))
(ON_DADOS / "apps-sistema.json").write_text(json.dumps({"youtube": {"client_id": "id", "client_secret": "sec"}}))
env = {**os.environ, "EDITOR_DATA": str(ON_DADOS), "APP_PASSWORD": "senha123", "APP_SECRET": "segredo",
       "PUBLIC_URL": URL}
srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.app:app", "--port", str(PORTA)], cwd=str(ROOT),
                       env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(60):
        try:
            httpx.get(URL + "/api/status", timeout=1)
            break
        except Exception:
            time.sleep(0.5)

    # sem login no editor e sem link assinado, ninguém começa um login de rede no online
    r = httpx.get(URL + "/api/oauth/youtube/start", follow_redirects=False)
    check(r.status_code == 403, "online: login de rede sem sessão é bloqueado")
    r = httpx.get(URL + "/api/oauth/youtube/start?ticket=123.abc", follow_redirects=False)
    check(r.status_code == 403, "online: link falso é bloqueado")
    r = httpx.post(URL + "/api/oauth/youtube/ticket", json={})
    check(r.status_code == 401, "online: pedir link exige a senha do editor")

    from backend import app as appmod  # noqa: E402
    from backend.core import store  # noqa: E402
    from backend.engine import ffmpeg_tools as ff  # noqa: E402
    c = TestClient(appmod.app)
    st = c.get("/api/publish/status").json()
    check(st["online"] is None and not st["networks"]["youtube"]["connected"], "PC sem online: nada conectado")
    r = c.put("/api/online/config", json={"url": URL, "password": "senha123"})
    check(r.status_code == 200, "PC: salva o endereço do online")
    st = c.get("/api/publish/status").json()
    yt = st["networks"]["youtube"]
    check(st["online"]["ok"] and yt["connected"] and yt.get("via_online") and yt["account"] == "Canal Teste",
          "PC mostra o YouTube conectado (salvo no online)")
    tk = st["networks"]["tiktok"]
    check(not tk["connected"] and not tk.get("via_online"), "rede sem app no online continua pedindo app")

    r = c.post("/api/publish/online-login/youtube")
    check(r.status_code == 200 and r.json()["url"].startswith(URL + "/api/oauth/youtube/start?ticket="),
          "PC recebe link de login assinado do online")
    r2 = httpx.get(r.json()["url"], follow_redirects=False)
    check(r2.status_code in (302, 307) and "accounts.google.com" in r2.headers.get("location", ""),
          "link assinado abre o login do Google")

    # publicação: o vídeo vai para a fila do online
    tmp = Path(tempfile.mkdtemp())
    subprocess.run([ff.ffmpeg(), "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x568:r=30:d=3",
                    "-pix_fmt", "yuv420p", str(tmp / "corte.mp4")], check=True)
    proj = store.new_project("Pregação de domingo")
    pid = proj["id"]
    shutil.copy(tmp / "corte.mp4", store.pdir(pid) / "renders" / "corte.mp4")
    store.update(pid, lambda p: p.update(status="pronto", kind="montagem", renders=[{"file": "corte.mp4", "created": time.time()}]))
    r = c.post("/api/publish/queue", json={"project": pid, "file": "corte.mp4", "nets": ["youtube"], "when": "at",
                                           "at": time.time() + 86400, "title": "Teste", "caption": "Legenda"})
    check(r.status_code == 200 and r.json().get("online") == ["youtube"], "PC manda a publicação para o online")
    for _ in range(60):
        jb = next((j for j in c.get(f"/api/projects/{pid}").json().get("jobs") or []
                   if j["kind"] == "publicar-online"), None)
        if jb and jb["status"] in ("concluido", "erro"):
            break
        time.sleep(0.5)
    check(jb and jb["status"] == "concluido", f"vídeo enviado ao online ({(jb or {}).get('error', '')})")
    q = c.get("/api/publish/queue").json()
    oi = [x for x in q if x.get("online")]
    check(len(oi) == 1 and oi[0]["net"] == "youtube" and oi[0]["title"] == "Teste" and oi[0]["status"] == "agendado",
          "fila do PC mostra o item agendado no online")
    r = c.delete(f"/api/publish/queue/{oi[0]['id']}")
    check(r.status_code == 200 and not [x for x in c.get("/api/publish/queue").json() if x.get("online")],
          "cancelar no PC cancela no online")
    # segundo envio reaproveita o mesmo projeto de recebidos no online
    import httpx as _hx
    oc = _hx.Client(base_url=URL)
    oc.post("/api/login", json={"password": "senha123"})
    antes = [p for p in oc.get("/api/projects").json() if p.get("recebidos")]
    r = c.post("/api/publish/queue", json={"project": pid, "file": "corte.mp4", "nets": ["youtube"], "when": "slot"})
    for _ in range(60):
        jbs = [j for j in c.get(f"/api/projects/{pid}").json().get("jobs") or [] if j["kind"] == "publicar-online"]
        if jbs and jbs[0]["status"] in ("concluido", "erro"):
            break
        time.sleep(0.5)
    depois = [p for p in oc.get("/api/projects").json() if p.get("recebidos")]
    check(len(antes) == 1 and len(depois) == 1 and depois[0]["renders"] == 2, "online guarda tudo num projeto só")
finally:
    srv.terminate()
    shutil.rmtree(PC_DADOS, ignore_errors=True)

print("\nTUDO CERTO" if not falhas else f"\n{falhas} FALHA(S)")
sys.exit(1 if falhas else 0)

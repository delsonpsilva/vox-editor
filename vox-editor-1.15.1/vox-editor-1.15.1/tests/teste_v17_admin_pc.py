"""Testes da v1.7: admin com senha padrão no programa do PC.
Programa novo (sem senha) ganha a senha padrão admin123 e pede para trocar no primeiro acesso;
o usuário "admin" entra; a troca não precisa da senha atual na primeira vez; depois precisa;
a senha padrão não pode ser escolhida de novo; sem senha no arquivo, ao abrir volta para a padrão."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DADOS = Path(tempfile.mkdtemp()) / "pc"
os.environ["EDITOR_DATA"] = str(DADOS)
os.environ.pop("APP_PASSWORD", None)
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import backend.app as A  # noqa: E402
from backend.core import store  # noqa: E402

falhas = 0


def check(cond, msg):
    global falhas
    print(("OK   " if cond else "FALHOU ") + msg)
    if not cond:
        falhas += 1


with TestClient(A.app) as c:  # "with" roda a abertura do programa (startup)
    check(c.get("/api/status").json()["login_required"] is True, "programa novo já abre pedindo senha")
    check(c.get("/api/projects").status_code == 401, "sem login: 401")
    check(c.post("/api/login", json={"email": "admin", "password": "errada"}).status_code == 401, "senha errada: 401")
    A._FALHAS.clear()
    r = c.post("/api/login", json={"email": "admin", "password": "admin123"})
    check(r.status_code == 200, "entra com admin / admin123")
    eu = c.get("/api/eu").json()
    check(eu["papel"] == "dono" and eu["trocar_senha"] is True, "primeiro acesso pede para trocar a senha")
    check(c.post("/api/security/password", json={"current": "", "new": "admin123"}).status_code == 400,
          "não aceita a senha padrão como nova")
    check(c.post("/api/security/password", json={"current": "", "new": "123"}).status_code == 400, "senha curta recusada")
    r = c.post("/api/security/password", json={"current": "", "new": "minhaSenha1"})
    check(r.status_code == 200, "primeira troca sem precisar da senha atual")
    check(c.get("/api/eu").json()["trocar_senha"] is False, "depois de trocar, não pede mais")
    check(c.get("/api/projects").status_code == 200, "continua logado depois da troca")
    check(c.post("/api/security/password", json={"current": "errada", "new": "outraSenha2"}).status_code == 401,
          "segunda troca exige a senha atual")
    c2 = TestClient(A.app)
    check(c2.post("/api/login", json={"email": "admin", "password": "admin123"}).status_code == 401, "senha padrão não entra mais")
    A._FALHAS.clear()
    check(c2.post("/api/login", json={"email": "", "password": "minhaSenha1"}).status_code == 200, "usuário vazio também é o admin")
    check(c2.post("/api/login", json={"email": "ADMIN", "password": "minhaSenha1"}).status_code == 200, "ADMIN em maiúsculas entra")

store.set_password("")  # o que o TIRAR-SENHA-DO-PC.bat faz
with TestClient(A.app) as c:
    check(store.precisa_trocar_senha(), "sem senha no arquivo: ao abrir volta para a padrão e pede troca")
    check(c.post("/api/login", json={"email": "admin", "password": "admin123"}).status_code == 200, "admin123 volta a entrar")

shutil.rmtree(DADOS.parent, ignore_errors=True)
print()
print("TUDO CERTO" if not falhas else f"{falhas} FALHA(S)")
sys.exit(1 if falhas else 0)

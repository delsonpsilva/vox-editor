"""Contas de pessoas na versão online (v1.7): equipe e clientes, cada um com o próprio login, limites e uso.

Papéis:
  - dono: quem entra com a senha do instalador (APP_PASSWORD). Vê e faz tudo.
  - admin: pessoa com conta e os mesmos poderes do dono (vê tudo, cuida das contas e das configurações).
  - equipe: vê e edita todos os projetos e pode publicar nas redes já conectadas. Não mexe em configurações nem contas.
  - cliente: vê só os próprios projetos. Edita, corta, monta e baixa. Não publica e não mexe em configurações.

As contas ficam num banco SQLite (dados/vox.db), junto dos projetos. Senhas: só o "hash" (PBKDF2), nunca a senha.
No programa do PC não há contas: ele continua com uma senha só (ou nenhuma)."""
from __future__ import annotations

import contextlib
import contextvars
import hashlib
import hmac
import os
import re
import sqlite3
import threading
import time
import uuid

from . import store

DB_FILE = store.DATA / "vox.db"
PAPEIS = ("admin", "equipe", "cliente")
NOMES_PAPEIS = {"dono": "Dono", "admin": "Administrador", "equipe": "Equipe", "cliente": "Cliente"}
DONO = {"id": "", "nome": "Dono", "email": "", "papel": "dono"}

# quem está usando agora (vale durante o pedido; nas tarefas em segundo plano fica vazio = sistema)
atual: contextvars.ContextVar[dict | None] = contextvars.ContextVar("vox_usuario", default=None)

_lock = threading.RLock()
_RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ------------------------------------------------------------------ banco

@contextlib.contextmanager
def _con():
    con = sqlite3.connect(str(DB_FILE), timeout=15, isolation_level=None)
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()


def _iniciar() -> None:
    with _lock, _con() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id TEXT PRIMARY KEY,
            nome TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            papel TEXT NOT NULL DEFAULT 'cliente',
            ativo INTEGER NOT NULL DEFAULT 1,
            limite_gb REAL NOT NULL DEFAULT 0,
            limite_min REAL NOT NULL DEFAULT 0,
            obs TEXT NOT NULL DEFAULT '',
            criado REAL NOT NULL,
            ultimo_acesso REAL NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS uso_mensal (
            usuario TEXT NOT NULL,
            mes TEXT NOT NULL,
            minutos REAL NOT NULL DEFAULT 0,
            PRIMARY KEY (usuario, mes)
        );
        """)


_iniciar()


def _hash(senha: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), salt, 200_000).hex()


def _linha(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    d["ativo"] = bool(d["ativo"])
    return d


def _publico(u: dict) -> dict:
    return {k: v for k, v in u.items() if k not in ("hash", "salt")}


def _mes() -> str:
    return time.strftime("%Y-%m")


# ------------------------------------------------------------------ cadastro

def _validar(nome: str, email: str, papel: str, senha: str | None, criando: bool) -> tuple[str, str]:
    nome, email = (nome or "").strip()[:80], (email or "").strip().lower()[:120]
    if not nome:
        raise ValueError("Coloque o nome da pessoa.")
    if not _RE_EMAIL.match(email):
        raise ValueError("Coloque um e-mail válido (é ele que a pessoa usa para entrar).")
    if papel not in PAPEIS:
        raise ValueError("Escolha o tipo de conta: administrador, equipe ou cliente.")
    if criando or senha:
        if not senha or len(senha) < 6:
            raise ValueError("A senha precisa ter pelo menos 6 caracteres.")
    return nome, email


def _num(v, padrao=0.0) -> float:
    try:
        return max(0.0, float(v or 0))
    except (TypeError, ValueError):
        return padrao


def criar(dados: dict) -> dict:
    papel = str(dados.get("papel") or "cliente")
    senha = str(dados.get("senha") or "")
    nome, email = _validar(dados.get("nome", ""), dados.get("email", ""), papel, senha, True)
    salt = os.urandom(16)
    u = {"id": uuid.uuid4().hex[:10], "nome": nome, "email": email, "hash": _hash(senha, salt), "salt": salt.hex(),
         "papel": papel, "ativo": 1, "limite_gb": _num(dados.get("limite_gb")), "limite_min": _num(dados.get("limite_min")),
         "obs": str(dados.get("obs") or "")[:300], "criado": time.time(), "ultimo_acesso": 0}
    with _lock, _con() as con:
        if con.execute("SELECT 1 FROM usuarios WHERE email=?", (email,)).fetchone():
            raise ValueError("Já existe uma conta com esse e-mail.")
        con.execute("INSERT INTO usuarios (id,nome,email,hash,salt,papel,ativo,limite_gb,limite_min,obs,criado,ultimo_acesso) "
                    "VALUES (:id,:nome,:email,:hash,:salt,:papel,:ativo,:limite_gb,:limite_min,:obs,:criado,:ultimo_acesso)", u)
    _cache.clear()
    return _publico(_linha(_buscar(u["id"])))


def editar(uid: str, dados: dict) -> dict:
    u = _buscar(uid)
    if not u:
        raise KeyError("Conta não encontrada.")
    papel = str(dados.get("papel") or u["papel"])
    senha = str(dados.get("senha") or "")
    nome, email = _validar(dados.get("nome", u["nome"]), dados.get("email", u["email"]), papel, senha, False)
    campos = {"nome": nome, "email": email, "papel": papel,
              "ativo": 1 if dados.get("ativo", u["ativo"]) else 0,
              "limite_gb": _num(dados.get("limite_gb", u["limite_gb"])),
              "limite_min": _num(dados.get("limite_min", u["limite_min"])),
              "obs": str(dados.get("obs", u["obs"]) or "")[:300], "id": uid}
    with _lock, _con() as con:
        outro = con.execute("SELECT id FROM usuarios WHERE email=? AND id<>?", (email, uid)).fetchone()
        if outro:
            raise ValueError("Já existe outra conta com esse e-mail.")
        con.execute("UPDATE usuarios SET nome=:nome,email=:email,papel=:papel,ativo=:ativo,limite_gb=:limite_gb,"
                    "limite_min=:limite_min,obs=:obs WHERE id=:id", campos)
        if senha:
            salt = os.urandom(16)
            con.execute("UPDATE usuarios SET hash=?, salt=? WHERE id=?", (_hash(senha, salt), salt.hex(), uid))
    _cache.clear()
    return _publico(_linha(_buscar(uid)))


def trocar_senha(uid: str, atual_: str, nova: str) -> None:
    u = _buscar(uid)
    if not u or not hmac.compare_digest(_hash(atual_, bytes.fromhex(u["salt"])), u["hash"]):
        raise PermissionError("A senha atual não confere.")
    if len(nova or "") < 6:
        raise ValueError("A senha nova precisa ter pelo menos 6 caracteres.")
    salt = os.urandom(16)
    with _lock, _con() as con:
        con.execute("UPDATE usuarios SET hash=?, salt=? WHERE id=?", (_hash(nova, salt), salt.hex(), uid))
    _cache.clear()


def remover(uid: str) -> None:
    with _lock, _con() as con:
        con.execute("DELETE FROM usuarios WHERE id=?", (uid,))
        con.execute("DELETE FROM uso_mensal WHERE usuario=?", (uid,))
    _cache.clear()


def _buscar(uid: str) -> dict | None:
    with _con() as con:
        return _linha(con.execute("SELECT * FROM usuarios WHERE id=?", (uid,)).fetchone())


def listar() -> list[dict]:
    with _con() as con:
        rows = [_linha(r) for r in con.execute("SELECT * FROM usuarios ORDER BY nome COLLATE NOCASE")]
    return [_publico(u) for u in rows]


def existe_alguma() -> bool:
    with _con() as con:
        return con.execute("SELECT 1 FROM usuarios LIMIT 1").fetchone() is not None


# ------------------------------------------------------------------ login e sessão

def autenticar(email: str, senha: str) -> dict | None:
    email = (email or "").strip().lower()
    with _con() as con:
        u = _linha(con.execute("SELECT * FROM usuarios WHERE email=?", (email,)).fetchone())
    if not u:
        _hash(senha or "x", b"0123456789abcdef")  # mesmo tempo de resposta com ou sem conta
        return None
    if not hmac.compare_digest(_hash(senha or "", bytes.fromhex(u["salt"])), u["hash"]):
        return None
    if not u["ativo"]:
        raise PermissionError("Esta conta está bloqueada. Fale com o responsável pelo VOX Editor.")
    with _lock, _con() as con:
        con.execute("UPDATE usuarios SET ultimo_acesso=? WHERE id=?", (time.time(), u["id"]))
    return _publico(u)


def token(u: dict, segredo: str, dias: int = 30) -> str:
    """Sessão assinada: id.validade.assinatura. Trocar a senha ou bloquear a conta derruba a sessão."""
    exp = int(time.time() + dias * 86400)
    base = f"{u['id']}.{exp}"
    full = _buscar(u["id"]) or {}
    sig = hmac.new(segredo.encode(), f"{base}.{full.get('hash', '')[:24]}".encode(), hashlib.sha256).hexdigest()[:40]
    return f"{base}.{sig}"


_cache: dict[str, tuple[float, dict | None]] = {}


def da_sessao(tok: str, segredo: str) -> dict | None:
    """Confere o cookie da sessão. Guarda a resposta por alguns segundos para não ler o banco a cada pedido."""
    if not tok or tok.count(".") != 2:
        return None
    agora = time.time()
    hit = _cache.get(tok)
    if hit and agora - hit[0] < 5:
        return hit[1]
    uid, exp, sig = tok.split(".")
    u = None
    try:
        if int(exp) > agora:
            full = _buscar(uid)
            if full and full["ativo"]:
                certo = hmac.new(segredo.encode(), f"{uid}.{exp}.{full['hash'][:24]}".encode(),
                                 hashlib.sha256).hexdigest()[:40]
                if hmac.compare_digest(certo, sig):
                    u = _publico(full)
    except ValueError:
        u = None
    if len(_cache) > 2000:
        _cache.clear()
    _cache[tok] = (agora, u)
    return u


# ------------------------------------------------------------------ permissões

def eu() -> dict | None:
    return atual.get()


def papel() -> str:
    u = atual.get()
    return u["papel"] if u else "dono"  # sem pessoa no pedido = sistema ou programa do PC


def manda_em_tudo() -> bool:
    return papel() in ("dono", "admin")


def ve_tudo() -> bool:
    return papel() in ("dono", "admin", "equipe")


def pode_publicar() -> bool:
    return papel() != "cliente"


def dono_do_projeto(proj: dict) -> str:
    return proj.get("owner") or ""


def pode_ver(proj: dict) -> bool:
    if ve_tudo():
        return True
    u = atual.get()
    return bool(u) and dono_do_projeto(proj) == u["id"]


def id_atual() -> str:
    """Quem fica como dono de um projeto criado agora ("" = o dono do sistema)."""
    u = atual.get()
    return u["id"] if u and u["papel"] != "dono" else ""


# ------------------------------------------------------------------ limites e uso

_uso_cache: dict[str, tuple[float, int]] = {}


def espaco_usado(uid: str, cache: float = 30.0) -> int:
    """Bytes ocupados pelos projetos da pessoa (guardado por alguns segundos: somar pastas grandes demora)."""
    hit = _uso_cache.get(uid)
    if hit and time.time() - hit[0] < cache:
        return hit[1]
    total = 0
    for f in store.PROJECTS.glob("*/project.json"):
        try:
            import json
            if (json.loads(f.read_text(encoding="utf-8")).get("owner") or "") == uid:
                total += store.folder_size(f.parent)
        except Exception:
            continue
    _uso_cache[uid] = (time.time(), total)
    return total


def esquecer_espaco(uid: str = "") -> None:
    if uid:
        _uso_cache.pop(uid, None)
    else:
        _uso_cache.clear()


def minutos_no_mes(uid: str) -> float:
    with _con() as con:
        r = con.execute("SELECT minutos FROM uso_mensal WHERE usuario=? AND mes=?", (uid, _mes())).fetchone()
    return float(r["minutos"]) if r else 0.0


def somar_minutos(uid: str, minutos: float) -> None:
    if not uid or minutos <= 0:
        return
    with _lock, _con() as con:
        con.execute("INSERT INTO uso_mensal (usuario, mes, minutos) VALUES (?,?,?) "
                    "ON CONFLICT(usuario, mes) DO UPDATE SET minutos = minutos + excluded.minutos",
                    (uid, _mes(), round(minutos, 2)))


def uso(u: dict) -> dict:
    gb = espaco_usado(u["id"]) / 1024 ** 3
    return {"espaco_gb": round(gb, 2), "limite_gb": u.get("limite_gb") or 0,
            "minutos_mes": round(minutos_no_mes(u["id"]), 1), "limite_min": u.get("limite_min") or 0}


def espaco_livre_bytes() -> float | None:
    """Quanto a pessoa atual ainda pode enviar (None = sem limite)."""
    u = atual.get()
    if not u or u["papel"] == "dono":
        return None
    full = _buscar(u["id"]) or u
    lim = float(full.get("limite_gb") or 0)
    if lim <= 0:
        return None
    return max(0.0, lim * 1024 ** 3 - espaco_usado(u["id"], cache=5.0))


def conferir_espaco() -> None:
    livre = espaco_livre_bytes()
    if livre is not None and livre <= 0:
        raise PermissionError("Seu espaço acabou. Apague projetos ou vídeos exportados que não usa mais, "
                              "ou fale com o responsável para aumentar o limite.")


def conferir_minutos() -> None:
    u = atual.get()
    if not u or u["papel"] == "dono":
        return
    full = _buscar(u["id"]) or u
    lim = float(full.get("limite_min") or 0)
    if lim > 0 and minutos_no_mes(u["id"]) >= lim:
        raise PermissionError(f"Você já usou os {lim:g} minutos de vídeo deste mês. O limite renova no dia 1º, "
                              "ou fale com o responsável para aumentar.")


def nomes() -> dict[str, str]:
    with _con() as con:
        return {r["id"]: r["nome"] for r in con.execute("SELECT id, nome FROM usuarios")}

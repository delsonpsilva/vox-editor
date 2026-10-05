"""Armazenamento local: configurações, projetos (um diretório por projeto) e gravação segura em JSON."""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("EDITOR_DATA") or (ROOT / "dados")).resolve()
PROJECTS = DATA / "projetos"
MODELS = DATA / "modelos"
FONTS = ROOT / "fontes"
CONFIG_FILE = DATA / "config.json"
for d in (DATA, PROJECTS, MODELS):
    d.mkdir(parents=True, exist_ok=True)

DEFAULT_CONFIG = {
    "app": {"name": "Editor IA", "tagline": "Do vídeo longo ao Reels pronto, com legenda.", "accent": "#FF8A3D"},
    "transcription": {"provider": "local", "local_model": "small", "device": "auto", "language": "pt",
                      "api_base": "https://api.groq.com/openai/v1", "api_key": "", "api_model": "whisper-large-v3-turbo"},
    "ai": {"provider": "none", "api_key": "", "model": "claude-haiku-4-5-20251001",
           "base_url": "https://api.openai.com/v1"},
    "render": {"encoder": "auto", "quality": "alta"},
    "defaults": {},
    "publish": {},
    "brand": {"handle": "", "kicker": "", "color": "#FF8A3D", "text": "#FFFFFF", "bg": "#101114", "progress": True,
              "logo": "", "logo_pos": "auto", "logo_size": "m", "logo_opacity": 1.0, "socials": {},
              "social_mode": "destino", "social_every": 12, "social_side": "direita"},
    "security": {},   # senha do programa do PC (só o "hash"); nunca vai para o navegador
    "online": {"url": "", "password": ""},  # endereço e senha da versão online, para enviar projetos do PC
}
BRAND_DIR = DATA / "marca"
BRAND_DIR.mkdir(parents=True, exist_ok=True)
(BRAND_DIR / "icones").mkdir(exist_ok=True)

_locks: dict[str, threading.RLock] = {}
_glock = threading.Lock()


def lock(pid: str) -> threading.RLock:
    with _glock:
        return _locks.setdefault(pid, threading.RLock())


def _write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if CONFIG_FILE.exists():
        try:
            saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            for k, v in saved.items():
                if isinstance(v, dict):
                    cfg.setdefault(k, {}).update(v)
        except json.JSONDecodeError:
            pass
    return cfg


def public_config(cfg: dict) -> dict:
    """Nunca devolve chaves de API ao navegador: só informa se estão definidas."""
    out = json.loads(json.dumps(cfg))
    sec_ = out.pop("security", {}) or {}
    out["security"] = {"password_set": bool(sec_.get("hash"))}
    onl = out.get("online") or {}
    out["online"] = {"url": onl.get("url", ""), "password_set": bool(onl.get("password"))}
    for app, c in (out.get("publish") or {}).items():
        if isinstance(c, dict) and "client_secret" in c:
            c["secret_set"] = bool(c.pop("client_secret"))
    for d in (out.get("publish") or {}).get("destinos") or []:  # destinos próprios: senhas e chaves ficam no servidor
        for k in ("password", "key", "token"):
            if isinstance(d, dict) and k in d:
                d[k + "_set"] = bool(d.pop(k))
    for sec in ("transcription", "ai"):
        key = out[sec].get("api_key") or ""
        out[sec]["api_key"] = ""
        out[sec]["api_key_set"] = bool(key)
        out[sec]["api_key_hint"] = ("…" + key[-4:]) if len(key) > 8 else ""
    return out


def save_config(update: dict) -> dict:
    cfg = load_config()
    for sec, vals in (update or {}).items():
        if sec not in cfg or not isinstance(vals, dict) or sec == "security":
            continue  # a senha do programa só muda por set_password (exige a senha atual)
        if sec == "online":
            if "url" in vals:
                cfg["online"]["url"] = str(vals["url"]).strip().rstrip("/")
            if vals.get("password"):
                cfg["online"]["password"] = str(vals["password"])
            continue
        for k, v in vals.items():
            if k in ("api_key_set", "api_key_hint"):
                continue
            if k == "api_key":
                if v == "__apagar__":
                    cfg[sec]["api_key"] = ""
                elif v:
                    cfg[sec]["api_key"] = str(v).strip()
                continue
            cfg[sec][k] = v
    _write_json(CONFIG_FILE, cfg)
    return cfg


# ---------- senha do programa do PC ----------

def _hash_pw(pw: str, salt: bytes) -> str:
    import hashlib
    return hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, 200_000).hex()


def password_hash() -> str:
    return (load_config().get("security") or {}).get("hash", "")


def check_password(pw: str) -> bool:
    import hmac
    sec = load_config().get("security") or {}
    if not sec.get("hash"):
        return False
    return hmac.compare_digest(_hash_pw(pw, bytes.fromhex(sec["salt"])), sec["hash"])


def set_password(new: str) -> None:
    """Grava a senha nova (vazia = sem senha). Só o "hash" fica salvo, nunca a senha."""
    cfg = load_config()
    if new:
        salt = os.urandom(16)
        cfg["security"] = {"hash": _hash_pw(new, salt), "salt": salt.hex()}
    else:
        cfg["security"] = {}
    _write_json(CONFIG_FILE, cfg)


def pdir(pid: str) -> Path:
    if not pid or any(c not in "0123456789abcdef" for c in pid):
        raise FileNotFoundError("Projeto inválido")
    return PROJECTS / pid


def new_project(name: str) -> dict:
    pid = uuid.uuid4().hex[:12]
    folder = PROJECTS / pid
    (folder / "renders").mkdir(parents=True, exist_ok=True)
    proj = {"id": pid, "name": name, "created": time.time(), "status": "enviando",
            "progress": {"pct": 0, "msg": "Recebendo arquivo…"}, "media": {}, "words": [], "segments": [],
            "analysis": {}, "settings": json.loads(json.dumps(load_config().get("defaults") or {})),
            "overrides": {"restored": [], "manual": []}, "clips": [], "renders": []}
    save(proj)
    return proj


def load(pid: str) -> dict:
    f = pdir(pid) / "project.json"
    if not f.exists():
        raise FileNotFoundError("Projeto não encontrado")
    proj = json.loads(f.read_text(encoding="utf-8"))
    for c in proj.get("clips") or []:  # projetos da versão 0.1
        if "segments" not in c and "s" in c:
            c["segments"] = [[c.pop("s"), c.pop("e")]]
            c.setdefault("kind", "corte")
            c.setdefault("hook", c.get("title", "")[:60])
    return proj


def save(proj: dict) -> None:
    _write_json(pdir(proj["id"]) / "project.json", proj)


def update(pid: str, fn) -> dict:
    with lock(pid):
        proj = load(pid)
        fn(proj)
        save(proj)
        return proj


def list_projects() -> list[dict]:
    out = []
    for f in PROJECTS.glob("*/project.json"):
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
            out.append({"id": p["id"], "name": p["name"], "created": p["created"], "status": p["status"],
                        "progress": p.get("progress"), "duration": p.get("media", {}).get("duration", 0),
                        "final": (p.get("stats") or {}).get("final"), "updated": f.stat().st_mtime,
                        "has_video": bool(p.get("media", {}).get("has_video")),
                        "clips": len(p.get("clips") or []), "renders": len(p.get("renders") or []),
                        "size": p.get("size", 0), "kind": p.get("kind") or "",
                        "montagem": (f.parent / "montagem.json").exists()})
        except Exception:
            continue
    return sorted(out, key=lambda x: -x["created"])


def folder_size(path: Path) -> int:
    total = 0
    for f in path.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            pass
    return total


def delete_project(pid: str) -> None:
    shutil.rmtree(pdir(pid), ignore_errors=True)

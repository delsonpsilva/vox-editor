"""Abre o editor como programa de verdade no Windows: janela própria (motor do Edge, o WebView2, que já vem no
Windows 10/11), com ícone e nome do programa, sem barra de endereço e sem a janela preta do terminal.

    pythonw -m backend.desktop            abre o programa
    python  -m backend.desktop --atalho   cria/atualiza os atalhos na área de trabalho e no menu Iniciar

Se o WebView2 faltar, tenta o Edge/Chrome em "modo aplicativo" (também sem barra de endereço)."""
from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IS_WIN = os.name == "nt"
PORT = int(os.environ.get("PORT", "8765"))


# ---------------------------------------------------------------- registro (pythonw não tem terminal)

def _setup_log():
    from .core import store
    log = store.DATA / "registro.txt"
    try:
        if log.exists() and log.stat().st_size > 5 * 1024 * 1024:
            log.replace(log.with_suffix(".antigo.txt"))
        fh = open(log, "a", encoding="utf-8", buffering=1)
        fh.write(f"\n===== {time.strftime('%d/%m/%Y %H:%M:%S')} abrindo o programa =====\n")
        if sys.stdout is None or "pythonw" in sys.executable.lower():
            sys.stdout = sys.stderr = fh
    except Exception:
        pass


def _app_name() -> str:
    try:
        from .core import store
        return (store.load_config().get("app") or {}).get("name") or "Editor IA"
    except Exception:
        return "Editor IA"


# ---------------------------------------------------------------- ícone

def _write_ico(pngs: list[tuple[int, bytes]], dest: Path) -> None:
    """ICO com imagens PNG dentro (aceito pelo Windows Vista em diante)."""
    head = struct.pack("<HHH", 0, 1, len(pngs))
    entries, blobs, off = b"", b"", 6 + 16 * len(pngs)
    for size, data in pngs:
        s = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", s, s, 0, 0, 1, 32, len(data), off)
        blobs += data
        off += len(data)
    dest.write_bytes(head + entries + blobs)


def icon_path() -> Path:
    """Usa a logo enviada em Marca → Logo do programa; se não houver, o ícone padrão."""
    from .core import store
    default = ROOT / "assets" / "icone.ico"
    logo = store.BRAND_DIR / "app_logo.png"
    out = store.DATA / "icone.ico"
    if not logo.exists():
        return default
    if out.exists() and out.stat().st_mtime >= logo.stat().st_mtime:
        return out
    try:
        import cv2
        import numpy as np
        img = cv2.imread(str(logo), cv2.IMREAD_UNCHANGED)
        if img is None:
            return default
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
        elif img.shape[2] == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
        h, w = img.shape[:2]
        side = max(h, w)
        sq = np.zeros((side, side, 4), np.uint8)
        sq[(side - h) // 2:(side - h) // 2 + h, (side - w) // 2:(side - w) // 2 + w] = img
        pngs = []
        for size in (256, 64, 48, 32, 16):
            r = cv2.resize(sq, (size, size), interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode(".png", r)
            if ok:
                pngs.append((size, buf.tobytes()))
        _write_ico(pngs, out)
        return out
    except Exception:
        traceback.print_exc()
        return default


def _set_window_icon(window, title: str, ico: Path) -> None:
    if not IS_WIN or not ico.exists():
        return
    try:
        import ctypes
        u = ctypes.windll.user32
        hwnd = 0
        try:
            hwnd = int(window.native.Handle.ToInt64())
        except Exception:
            for _ in range(20):
                hwnd = u.FindWindowW(None, title)
                if hwnd:
                    break
                time.sleep(0.25)
        if not hwnd:
            return
        for kind, size in ((1, 0), (0, 16)):  # ICON_BIG / ICON_SMALL
            h = u.LoadImageW(None, str(ico), 1, size, size, 0x10 | (0x40 if not size else 0))
            if h:
                u.SendMessageW(hwnd, 0x80, kind, h)
    except Exception:
        traceback.print_exc()


# ---------------------------------------------------------------- servidor interno

def _alive(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/meta", timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


def _port_free(port: int) -> bool:
    import socket
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


class Server:
    def __init__(self, port: int):
        import uvicorn
        from .app import app
        self.port = port
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                                                    log_config=None))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self):
        self.thread.start()

    def wait_ready(self, timeout=60) -> bool:
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.server.started:
                return True
            if not self.thread.is_alive():
                return False
            time.sleep(0.1)
        return False

    def stop(self):
        self.server.should_exit = True
        self.thread.join(timeout=5)


# ---------------------------------------------------------------- funções chamadas pela tela (window.pywebview.api)

class Api:
    def __init__(self):
        self.window = None
        self.force_close = False

    def info(self):
        return {"desktop": True, "version": _version()}

    def pick_video(self):
        import webview
        types = ("Vídeos e áudios (*.mp4;*.mov;*.mkv;*.webm;*.avi;*.m4v;*.mxf;*.mts;*.wmv;*.mp3;*.wav;*.m4a)",
                 "Todos os arquivos (*.*)")
        kind = getattr(getattr(webview, "FileDialog", None), "OPEN", None) or webview.OPEN_DIALOG
        r = self.window.create_file_dialog(kind, allow_multiple=False, file_types=types)
        return r[0] if r else None

    def save_file(self, url: str, name: str):
        """Botões "Baixar": abre a janela Salvar do Windows e grava o arquivo direto do programa."""
        import webview
        kind = getattr(getattr(webview, "FileDialog", None), "SAVE", None) or webview.SAVE_DIALOG
        ext = Path(name).suffix.lstrip(".") or "*"
        r = self.window.create_file_dialog(kind, save_filename=name, file_types=(f"Arquivo .{ext} (*.{ext})", "Todos os arquivos (*.*)"))
        if not r:
            return None
        dest = r if isinstance(r, str) else r[0]
        src = url if url.startswith("http") else f"http://127.0.0.1:{PORT}{url}"
        req = urllib.request.Request(src)
        try:  # com senha ligada, a janela se identifica pelo código interno (mesmo processo do servidor)
            from .app import INTERNO
            req.add_header("X-Vox-Interno", INTERNO)
        except Exception:
            pass
        with urllib.request.urlopen(req) as resp, open(dest, "wb") as fh:
            while True:
                buf = resp.read(4 * 1024 * 1024)
                if not buf:
                    break
                fh.write(buf)
        return dest

    def show_in_folder(self, path: str):
        if IS_WIN and path and Path(path).exists():
            subprocess.Popen(["explorer", "/select,", str(Path(path))])
        return True

    def open_external(self, url: str):
        if url.startswith("/"):
            url = f"http://127.0.0.1:{PORT}{url}"
        webbrowser.open(url)
        return True

    def minimize(self):
        self.window.minimize()
        return True

    def quit(self):
        self.force_close = True
        self.window.destroy()
        return True


def _version() -> str:
    try:
        from .app import VERSION
        return VERSION
    except Exception:
        return ""


def _pending_posts() -> int:
    try:
        from .core import publish
        return sum(1 for it in publish.queue() if it.get("status") in ("agendado", "publicando"))
    except Exception:
        return 0


def _busy_jobs() -> int:
    try:
        from .core import jobs
        return sum(1 for j in list(jobs.JOBS.values()) if j["status"] in ("na fila", "processando"))
    except Exception:
        return 0


SPLASH = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;height:100%;background:#0e0f13;color:#e9e9ee;font-family:Segoe UI,system-ui,sans-serif}
body{display:flex;align-items:center;justify-content:center;flex-direction:column;gap:18px}
h1{margin:0;font-size:26px;font-weight:600;letter-spacing:.2px}
p{margin:0;color:#8b8d98;font-size:13px}
.bar{width:220px;height:3px;border-radius:3px;background:#22242c;overflow:hidden}
.bar i{display:block;height:100%;width:40%;background:#FF8A3D;border-radius:3px;animation:a 1.1s ease-in-out infinite}
@keyframes a{0%{margin-left:-40%}100%{margin-left:100%}}
</style></head><body><h1>__NOME__</h1><div class="bar"><i></i></div><p>Abrindo o estúdio…</p></body></html>"""


def run_window(url: str, owns_server: Server | None, title: str) -> bool:
    """Abre a janela própria. Devolve False se o WebView2/pywebview não estiver disponível."""
    try:
        import webview
    except Exception:
        traceback.print_exc()
        return False
    from .core import store
    ico = icon_path()
    api = Api()
    try:
        webview.settings["ALLOW_DOWNLOADS"] = True
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    except Exception:
        pass
    kw = dict(width=1400, height=880, min_size=(1100, 680), background_color="#0e0f13", js_api=api, text_select=True)
    splash = SPLASH.replace("__NOME__", title.replace("<", ""))
    try:
        win = webview.create_window(title, html=splash, maximized=True, **kw)
    except TypeError:
        win = webview.create_window(title, html=splash, **kw)
    api.window = win

    def on_closing():
        if api.force_close:
            return True
        n, busy = _pending_posts(), _busy_jobs()
        if not n and not busy:
            return True
        # a tela mostra a pergunta (Minimizar e continuar / Fechar mesmo assim); o evento não pode esperar por ela
        threading.Timer(0.05, lambda: win.evaluate_js(f"window.voxConfirmClose && voxConfirmClose({n}, {busy})")).start()
        return False

    def on_shown():
        threading.Thread(target=_set_window_icon, args=(win, title, ico), daemon=True).start()

    win.events.closing += on_closing
    win.events.shown += on_shown

    def boot():
        if owns_server and not owns_server.wait_ready():
            win.evaluate_js("document.querySelector('p').textContent='Não consegui iniciar. Veja o arquivo dados/registro.txt'")
            return
        win.load_url(url)

    try:
        webview.start(boot, private_mode=False, storage_path=str(store.DATA / "janela"),
                      gui="edgechromium" if IS_WIN else None)
    except Exception:
        traceback.print_exc()
        return False
    return True


def _app_mode_browser(url: str, title: str) -> bool:
    """Plano B: Edge ou Chrome em modo aplicativo, com perfil próprio (a janela fecha = programa fecha)."""
    from .core import store
    cands = []
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            cands += [Path(base) / "Microsoft/Edge/Application/msedge.exe", Path(base) / "Google/Chrome/Application/chrome.exe"]
    for exe in cands:
        if exe.exists():
            prof = store.DATA / ("perfil-" + exe.stem)
            try:
                subprocess.run([str(exe), f"--app={url}", f"--user-data-dir={prof}", "--no-first-run",
                                "--no-default-browser-check", "--window-size=1400,880", "--start-maximized"])
                return True
            except Exception:
                traceback.print_exc()
    return False


def _message(text: str, title: str) -> None:
    if IS_WIN:
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, text, title, 0x40)
            return
        except Exception:
            pass
    print(text)


def main() -> None:
    _setup_log()
    title = _app_name()
    if IS_WIN:
        try:  # agrupa na barra de tarefas com o ícone do programa (e não com o do Python)
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Estudio.EditorIA")
        except Exception:
            pass
    os.environ["NO_BROWSER"] = "1"
    url = f"http://127.0.0.1:{PORT}/"
    server = None
    if _port_free(PORT):
        server = Server(PORT)
        server.start()
    elif not _alive(PORT):
        _message(f"A porta {PORT} está sendo usada por outro programa. Feche-o e abra o {title} de novo.", title)
        return
    # já aberto em outra janela: só abre mais uma janela ligada ao mesmo programa
    try:
        ok = run_window(url, server, title)
        if not ok:
            if server and not server.wait_ready():
                _message("Não consegui iniciar o programa. Veja o arquivo dados\\registro.txt", title)
                return
            if not _app_mode_browser(url, title):
                _message("Não encontrei o componente de janela (WebView2) nem o Edge/Chrome.\n"
                         "Instale o 'Microsoft Edge WebView2 Runtime' pelo site da Microsoft "
                         "ou use o INICIAR-NAVEGADOR.bat.", title)
    finally:
        if server:
            server.stop()


# ---------------------------------------------------------------- atalhos

def create_shortcuts() -> None:
    title = _app_name()
    ico = icon_path()
    pyw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    if not pyw.exists():
        pyw = Path(sys.executable).with_name("pythonw.exe")
    if not IS_WIN:
        print("Atalhos só no Windows.")
        return
    q = lambda s: "'" + str(s).replace("'", "''") + "'"  # noqa: E731
    safe = "".join(c for c in title if c not in '\\/:*?"<>|').strip() or "Editor IA"
    ps = f"""
$ws = New-Object -ComObject WScript.Shell
$alvos = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))
foreach ($d in $alvos) {{
  Get-ChildItem -Path $d -Filter *.lnk -ErrorAction SilentlyContinue | ForEach-Object {{
    $l = $ws.CreateShortcut($_.FullName)
    if (($l.TargetPath -like {q(str(ROOT) + '*')}) -or ($l.Arguments -like '*backend.desktop*' -and $l.WorkingDirectory -eq {q(ROOT)})) {{ Remove-Item $_.FullName -Force }}
  }}
  $lnk = $ws.CreateShortcut((Join-Path $d {q(safe + '.lnk')}))
  $lnk.TargetPath = {q(pyw)}
  $lnk.Arguments = '-m backend.desktop'
  $lnk.WorkingDirectory = {q(ROOT)}
  $lnk.IconLocation = {q(str(ico) + ',0')}
  $lnk.Description = 'Editor de vídeo com cortes por IA'
  $lnk.Save()
}}
"""
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                       capture_output=True, text=True)
    if r.returncode == 0:
        print(f"      Atalho '{safe}' criado na área de trabalho e no menu Iniciar")
    else:
        print("      Não consegui criar o atalho:", (r.stderr or "")[-300:])


if __name__ == "__main__":
    if "--atalho" in sys.argv:
        create_shortcuts()
    else:
        main()

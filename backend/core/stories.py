"""Stories do Culto (v1.15): um vídeo ou uma foto do culto vira story 9:16 com a capa do evento
(tarja desfocada, título dourado, logo da igreja) e vai direto para os Stories do Instagram e do Facebook.

Como funciona: o Python (Pillow) desenha a capa — textos, logo e a máscara da parte desfocada — em PNGs
transparentes, e o FFmpeg junta tudo com o vídeo/foto. A prévia usa exatamente o mesmo caminho, só que com
um quadro do vídeo; por isso o que aparece na prévia é o que sai no story."""
from __future__ import annotations

import hashlib
import json
import math
import random
import re
import secrets
import shutil
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from . import contas, montagem, store
from ..engine import ffmpeg_tools as ff

W, H = 1080, 1920
SEG_MAX = 59.0          # o Instagram aceita story de vídeo com até 60 s
PARTES_MAX = 15
FOTO_SEG = 7.0          # foto vira um vídeo curtinho (com zoom leve) para poder ir aos Stories
Progresso = Optional[Callable[[float, str], None]]

# --------------------------------------------------------------------------------------------
# Eventos: id -> (linha de cima, destaque). O nome que aparece na lista é a junção das duas.
# --------------------------------------------------------------------------------------------
GRUPOS = [
    ("Cultos", [
        ("celebracao", "Culto de", "Celebração"), ("acao_gracas", "Culto de", "Ação de Graças"),
        ("santa_ceia", "Culto de", "Santa Ceia"), ("doutrina", "Culto de", "Doutrina"), ("ensino", "Culto de", "Ensino"),
        ("oracao", "Culto de", "Oração"), ("libertacao", "Culto de", "Libertação"), ("cura", "Culto de", "Cura e Milagres"),
        ("missoes", "Culto de", "Missões"), ("familia", "Culto da", "Família"), ("louvor", "Noite de", "Louvor"),
        ("adoracao", "Noite de", "Adoração"), ("vigilia", "", "Vigília"), ("consagracao", "Culto de", "Consagração"),
        ("batismo", "Batismo", "nas Águas"), ("rua", "Culto na", "Rua"), ("evangelistico", "Culto", "Evangelístico"),
        ("posse", "Culto de", "Posse"), ("aniv_igreja", "Aniversário da", "Igreja"), ("obreiros", "Culto dos", "Obreiros"),
        ("ofertas", "Culto de", "Ofertas"), ("dizimos", "Culto de", "Gratidão"),
    ]),
    ("Departamentos", [
        ("jovens", "Culto de", "Jovens"), ("adolescentes", "Culto de", "Adolescentes"), ("criancas", "Culto das", "Crianças"),
        ("circulo", "Círculo de", "Oração"), ("mulheres", "Culto das", "Mulheres"), ("senhoras", "Culto das", "Senhoras"),
        ("varoes", "Culto dos", "Varões"), ("casais", "Culto de", "Casais"), ("ebd", "Escola Bíblica", "Dominical"),
        ("coral", "Apresentação do", "Coral"), ("louvor_dep", "Ministério de", "Louvor"), ("intercessao", "Ministério de", "Intercessão"),
        ("dep_missoes", "Departamento de", "Missões"), ("terceira_idade", "Culto da", "Melhor Idade"),
    ]),
    ("Encontros e congressos", [
        ("congresso", "", "Congresso"), ("congresso_jovens", "Congresso de", "Jovens"),
        ("congresso_mulheres", "Congresso de", "Mulheres"), ("congresso_adolescentes", "Congresso de", "Adolescentes"),
        ("congresso_criancas", "Congresso", "Infantil"), ("congresso_varoes", "Congresso de", "Varões"),
        ("congresso_missoes", "Congresso de", "Missões"), ("encontro_mulheres", "Encontro de", "Mulheres"),
        ("encontro_casais", "Encontro de", "Casais"), ("encontro_jovens", "Encontro de", "Jovens"),
        ("conferencia", "", "Conferência"), ("seminario", "", "Seminário"), ("retiro", "Retiro", "Espiritual"),
        ("acampamento", "", "Acampamento"), ("cruzada", "Cruzada", "Evangelística"), ("festividade", "", "Festividade"),
        ("convencao", "", "Convenção"), ("simposio", "", "Simpósio"), ("escola_lideres", "Escola de", "Líderes"),
    ]),
    ("Datas especiais", [
        ("virada", "Culto da", "Virada"), ("natal", "Culto de", "Natal"), ("cantata", "Cantata de", "Natal"),
        ("pascoa", "Culto de", "Páscoa"), ("maes", "Dia das", "Mães"), ("pais", "Dia dos", "Pais"),
        ("dia_criancas", "Dia das", "Crianças"), ("dia_pastor", "Dia do", "Pastor"), ("reforma", "Dia da", "Reforma"),
        ("biblia", "Dia da", "Bíblia"), ("aniversario", "", "Aniversário"), ("casamento", "", "Casamento"),
        ("apresentacao", "Apresentação de", "Criança"), ("formatura", "", "Formatura"), ("inauguracao", "", "Inauguração"),
        ("ordenacao", "Consagração de", "Obreiros"), ("bodas", "", "Bodas"),
    ]),
]
EVENTOS = {k: (a, b) for _, itens in GRUPOS for k, a, b in itens}

# --------------------------------------------------------------------------------------------
# Modelos da capa
# --------------------------------------------------------------------------------------------
MODELOS = {
    "ouro": {"nome": "Ouro desfocado", "desc": "Igual aos destaques: tarja desfocada embaixo e o nome brilhando"},
    "assinatura": {"nome": "Assinatura", "desc": "Letra cursiva elegante sobre a tarja desfocada"},
    "faixa": {"nome": "Faixa forte", "desc": "Letras grandes e grossas numa faixa escura"},
    "neon": {"nome": "Neon", "desc": "Brilho colorido, moderno, para jovens e louvor"},
    "vidro": {"nome": "Cartão de vidro", "desc": "Cartão transparente com o logo ao lado"},
    "topo": {"nome": "Título no topo", "desc": "Tarja desfocada em cima e o logo embaixo"},
}
CORES = {  # nome, tons do degradê (escuro -> claro), cor sólida
    "dourado": ("Dourado", ["#6E4E12", "#B8892B", "#F3D37A", "#FFF4C2", "#D9AE47", "#8A6418"], "#E8C25A"),
    "prata": ("Prata", ["#5B5F66", "#A7ADB5", "#E9EDF2", "#FFFFFF", "#B9BEC6", "#70757D"], "#DDE2E8"),
    "rose": ("Rosê", ["#7A3E3A", "#C27A6F", "#F2C2B5", "#FFE8E0", "#D9958A", "#8E4F48"], "#EBB2A6"),
    "branco": ("Branco", ["#FFFFFF", "#FFFFFF"], "#FFFFFF"),
    "azul": ("Azul", ["#0B3D91", "#2F7BFF", "#8EC5FF", "#E4F1FF", "#3B8CFF", "#123F8F"], "#3BA0FF"),
    "vermelho": ("Vermelho", ["#6D0A0A", "#C21B1B", "#FF6B6B", "#FFD1D1", "#E02424", "#7A1010"], "#FF4D4D"),
    "verde": ("Verde", ["#0D4D2A", "#1E9E57", "#7BE3A6", "#E1FFEE", "#22B866", "#0F5A31"], "#34D399"),
    "roxo": ("Roxo", ["#3B0F6E", "#7C3AED", "#C4A3FF", "#F1E8FF", "#8B5CF6", "#4C1D95"], "#A78BFA"),
}
# Letras (fontes livres, licença OFL). id -> (arquivo, nome, grupo)
FONTES = {
    "playfair": ("PlayfairDisplay-ExtraBold.ttf", "Playfair", "Elegantes"),
    "dmserif": ("DMSerifDisplay-Regular.ttf", "DM Serif", "Elegantes"),
    "abril": ("AbrilFatface-Regular.ttf", "Abril", "Elegantes"),
    "cinzel": ("Cinzel-Bold.ttf", "Cinzel", "Elegantes"),
    "cinzeldec": ("CinzelDecorative-Bold.ttf", "Cinzel Decorativa", "Elegantes"),
    "marcellus": ("Marcellus-Regular.ttf", "Marcellus", "Elegantes"),
    "greatvibes": ("GreatVibes-Regular.ttf", "Great Vibes", "Cursivas"),
    "alexbrush": ("AlexBrush-Regular.ttf", "Alex Brush", "Cursivas"),
    "allura": ("Allura-Regular.ttf", "Allura", "Cursivas"),
    "pacifico": ("Pacifico-Regular.ttf", "Pacifico", "Cursivas"),
    "lobster": ("Lobster-Regular.ttf", "Lobster", "Cursivas"),
    "kaushan": ("KaushanScript-Regular.ttf", "Kaushan", "Cursivas"),
    "anton": ("Anton-Regular.ttf", "Anton", "Fortes"),
    "bebas": ("BebasNeue-Regular.ttf", "Bebas", "Fortes"),
    "oswald": ("Oswald-Bold.ttf", "Oswald", "Fortes"),
    "archivo": ("ArchivoBlack-Regular.ttf", "Archivo Black", "Fortes"),
    "montserrat": ("Montserrat-ExtraBold.ttf", "Montserrat", "Fortes"),
    "poppins": ("Poppins-Bold.ttf", "Poppins", "Fortes"),
    "bangers": ("Bangers-Regular.ttf", "Bangers", "Fortes"),
    "righteous": ("Righteous-Regular.ttf", "Righteous", "Fortes"),
}


def pasta_fontes() -> Path:
    p = store.BRAND_DIR / "fontes-stories" / re.sub(r"[^\w-]", "_", _dono())
    p.mkdir(parents=True, exist_ok=True)
    return p


def fontes_minhas() -> list[dict]:
    out = []
    for f in sorted(pasta_fontes().glob("*.ttf")) + sorted(pasta_fontes().glob("*.otf")):
        meta = f.with_suffix(".json")
        nome = ""
        if meta.exists():
            try:
                nome = json.loads(meta.read_text(encoding="utf-8")).get("nome", "")
            except Exception:
                pass
        out.append({"id": "u-" + f.stem, "nome": nome or "Minha letra", "grupo": "Minhas letras", "ext": f.suffix})
    return out


def arquivo_fonte(fid: str) -> Path | None:
    """Caminho da fonte escolhida (do catálogo ou enviada pela pessoa)."""
    if not fid:
        return None
    if fid in FONTES:
        f = store.FONTS / FONTES[fid][0]
        return f if f.exists() else None
    m = re.fullmatch(r"u-([0-9a-f]{10})", fid)
    if m:
        for ext in (".ttf", ".otf"):
            f = pasta_fontes() / f"{m.group(1)}{ext}"
            if f.exists():
                return f
    return None


def salvar_fonte(dados: bytes, nome: str) -> dict:
    from PIL import ImageFont
    import io
    if not dados or len(dados) > 15 * 1024 * 1024:
        raise ValueError("Envie uma fonte .ttf ou .otf de até 15 MB")
    ext = ".otf" if (nome or "").lower().endswith(".otf") or dados[:4] == b"OTTO" else ".ttf"
    try:
        ImageFont.truetype(io.BytesIO(dados), 60)
    except Exception:
        raise ValueError("Não consegui ler essa fonte. Use um arquivo .ttf ou .otf.")
    fid = secrets.token_hex(5)
    (pasta_fontes() / f"{fid}{ext}").write_bytes(dados)
    limpo = re.sub(r"\.(ttf|otf)$", "", nome or "", flags=re.I).replace("-", " ").replace("_", " ").strip()[:30] or "Minha letra"
    (pasta_fontes() / f"{fid}.json").write_text(json.dumps({"nome": limpo}, ensure_ascii=False), encoding="utf-8")
    return {"id": "u-" + fid, "nome": limpo}


def apagar_fonte(fid: str) -> None:
    m = re.fullmatch(r"u-([0-9a-f]{10})", fid or "")
    if m:
        for ext in (".ttf", ".otf", ".json"):
            (pasta_fontes() / f"{m.group(1)}{ext}").unlink(missing_ok=True)


def _cursiva(fid: str) -> bool:
    return fid in FONTES and FONTES[fid][2] == "Cursivas"


ENQUADRAR = {"auto": "Automático", "desfocado": "Inteiro + fundo desfocado", "preencher": "Preencher a tela"}
TAMANHOS = {"partes": "Partes de 60 s (Stories)", "inicio": "Só o primeiro minuto", "inteiro": "Inteiro (só para baixar)"}
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro"]


# --------------------------------------------------------------------------------------------
# Onde as coisas ficam
# --------------------------------------------------------------------------------------------
def _dono() -> str:
    return contas.id_atual() or "dono"


def pasta_logos() -> Path:
    p = store.BRAND_DIR / "logos-stories" / re.sub(r"[^\w-]", "_", _dono())
    p.mkdir(parents=True, exist_ok=True)
    return p


def projeto() -> dict:
    """Projeto (um por pessoa) que guarda os arquivos e os stories prontos — eles aparecem em Exportados."""
    for p in store.list_projects():
        if p.get("stories_proj"):
            try:
                return store.load(p["id"])
            except Exception:
                continue
    proj = montagem.projeto_em_branco("Stories do culto", "9:16")
    return store.update(proj["id"], lambda p: p.update(stories_proj=True, stories={"itens": [], "usados": {}, "ultimo": {}}))


def pasta(pid: str) -> Path:
    p = store.pdir(pid) / "stories"
    (p / "src").mkdir(parents=True, exist_ok=True)
    (p / "tmp").mkdir(parents=True, exist_ok=True)
    return p


def _dados(proj: dict) -> dict:
    d = proj.setdefault("stories", {})
    d.setdefault("itens", [])
    d.setdefault("usados", {})
    d.setdefault("ultimo", {})
    return d


# --------------------------------------------------------------------------------------------
# Sugestão do evento pela data (o primeiro da lista já vem marcado)
# --------------------------------------------------------------------------------------------
def _pascoa(ano: int) -> date:
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    mes = (h + l_ - 7 * m + 114) // 31
    dia = ((h + l_ - 7 * m + 114) % 31) + 1
    return date(ano, mes, dia)


def _domingo_n(ano: int, mes: int, n: int) -> date:
    d = date(ano, mes, 1)
    d += timedelta(days=(6 - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def sugestao(dia: date | None = None, usados: dict | None = None, meus: set | None = None) -> list[str]:
    """Eventos mais prováveis para o dia (do mais provável para o menos)."""
    d = dia or date.today()
    out: list[str] = []
    md = (d.month, d.day)
    if md in ((12, 31), (1, 1)):
        out.append("virada")
    if md in ((12, 24), (12, 25)) or (d.month == 12 and d.day >= 15):
        out += ["natal", "cantata"]
    p = _pascoa(d.year)
    if p - timedelta(days=3) <= d <= p:
        out.append("pascoa")
    if d == _domingo_n(d.year, 5, 2) or (d.month == 5 and 6 <= d.day <= 14 and d.weekday() == 6):
        out.append("maes")
    if d == _domingo_n(d.year, 8, 2):
        out.append("pais")
    if md == (10, 12):
        out.append("dia_criancas")
    if md == (10, 31):
        out.append("reforma")
    if d.month == 12 and d.weekday() == 6 and d.day <= 14:
        out.append("biblia")
    if d.weekday() == 6:
        out += ["celebracao", "ebd", "santa_ceia"] if d.day <= 7 else ["celebracao", "ebd"]
    elif d.weekday() in (1, 2):
        out += ["doutrina", "ensino", "oracao"]
    elif d.weekday() == 3:
        out += ["libertacao", "oracao"]
    elif d.weekday() == 4:
        out += ["oracao", "circulo"]
    elif d.weekday() == 5:
        out += ["jovens", "adolescentes"]
    else:
        out += ["oracao", "circulo"]
    for k, _n in sorted((usados or {}).items(), key=lambda x: -x[1])[:4]:
        out.append(k)
    vistos, final = set(), []
    for k in out:
        if (k in EVENTOS or k in (meus or set())) and k not in vistos:
            vistos.add(k)
            final.append(k)
    return final[:6]


def data_por_extenso(iso: str) -> str:
    try:
        d = date.fromisoformat(iso)
    except (TypeError, ValueError):
        return ""
    return f"{d.day:02d} de {MESES[d.month - 1]} de {d.year}"


# --------------------------------------------------------------------------------------------
# Logos
# --------------------------------------------------------------------------------------------
def logos() -> list[dict]:
    out = []
    if (store.BRAND_DIR / "logo.png").exists():
        out.append({"id": "marca", "nome": "Logo da Marca"})
    for f in sorted(pasta_logos().glob("*.png"), key=lambda x: x.stat().st_mtime):
        meta = f.with_suffix(".json")
        nome = ""
        if meta.exists():
            try:
                nome = json.loads(meta.read_text(encoding="utf-8")).get("nome", "")
            except Exception:
                pass
        out.append({"id": f.stem, "nome": nome or "Logo"})
    return out


def arquivo_logo(lid: str) -> Path | None:
    if not lid or lid == "nenhum":
        return None
    if lid == "marca":
        f = store.BRAND_DIR / "logo.png"
        return f if f.exists() else None
    if not re.fullmatch(r"[0-9a-f]{10}", lid):
        return None
    f = pasta_logos() / f"{lid}.png"
    return f if f.exists() else None


def salvar_logo(dados: bytes, nome: str) -> dict:
    if not dados:
        raise ValueError("Arquivo vazio")
    if len(dados) > 10 * 1024 * 1024:
        raise ValueError("Logo muito grande (máx. 10 MB)")
    lid = secrets.token_hex(5)
    tmp = pasta_logos() / f"{lid}.bin"
    out = pasta_logos() / f"{lid}.png"
    tmp.write_bytes(dados)
    try:
        from PIL import Image, ImageOps
        with Image.open(tmp) as im:
            im = ImageOps.exif_transpose(im).convert("RGBA")
            im.thumbnail((700, 700))
            bb = im.getchannel("A").getbbox()  # tira a sobra transparente em volta
            if bb:
                im = im.crop(bb)
            im.save(out)
    except Exception:
        try:
            ff.run([ff.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(tmp), "-frames:v", "1",
                    "-vf", "scale='min(700,iw)':-2:flags=lanczos,format=rgba", str(out)])
        except Exception:
            raise ValueError("Não consegui ler a imagem do logo (use PNG ou JPG)")
    finally:
        tmp.unlink(missing_ok=True)
    nome = re.sub(r"\.[A-Za-z0-9]+$", "", nome or "").strip()[:40] or "Logo"
    out.with_suffix(".json").write_text(json.dumps({"nome": nome}, ensure_ascii=False), encoding="utf-8")
    return {"id": lid, "nome": nome}


def apagar_logo(lid: str) -> None:
    if re.fullmatch(r"[0-9a-f]{10}", lid or ""):
        (pasta_logos() / f"{lid}.png").unlink(missing_ok=True)
        (pasta_logos() / f"{lid}.json").unlink(missing_ok=True)


# --------------------------------------------------------------------------------------------
# Arquivos enviados
# --------------------------------------------------------------------------------------------
def receber(pid: str, caminho: Path, nome: str, modificado_ms: float | None = None, fuso: int | None = None) -> dict:
    """Confere o vídeo/foto que chegou, tira um quadro para as prévias e registra no projeto."""
    kind = montagem.tipo_por_extensao(nome)
    if kind not in ("video", "image"):
        caminho.unlink(missing_ok=True)
        raise ValueError("Envie um vídeo ou uma foto (JPG, PNG, WEBP).")
    quando = None
    try:  # hora em que foi gravado (para o resumo seguir a ordem do culto)
        from . import resumo
        quando = resumo.hora_da_midia(caminho, kind, modificado_ms, fuso)
    except Exception:
        pass
    iid = secrets.token_hex(4)
    base = pasta(pid)
    quadro = base / "src" / f"{iid}-quadro.jpg"
    info = {"duration": 0.0, "width": 0, "height": 0, "has_audio": False}
    if kind == "image":
        from PIL import Image, ImageOps
        try:
            with Image.open(caminho) as im:  # já deixa a foto em pé (EXIF) e em JPG
                im = ImageOps.exif_transpose(im).convert("RGB")
                if max(im.size) > 3000:
                    im.thumbnail((3000, 3000))
                norm = base / "src" / f"{iid}.jpg"
                im.save(norm, quality=93)
                info.update(width=im.size[0], height=im.size[1])
        except Exception:
            caminho.unlink(missing_ok=True)
            raise ValueError("Não consegui abrir essa foto. Tente JPG ou PNG.")
        if caminho != norm:
            caminho.unlink(missing_ok=True)
        caminho = norm
        shutil.copyfile(caminho, quadro)
    else:
        try:
            info = ff.probe(str(caminho))
        except Exception:
            caminho.unlink(missing_ok=True)
            raise ValueError("Não consegui ler esse vídeo.")
        if not info.get("has_video"):
            caminho.unlink(missing_ok=True)
            raise ValueError("Esse arquivo não tem imagem de vídeo.")
        t = min(2.0, max(0.0, (info.get("duration") or 0) * 0.3))
        try:
            ff.run([ff.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(caminho),
                    "-frames:v", "1", "-q:v", "3", str(quadro)])
        except Exception:
            ff.run([ff.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(caminho),
                    "-frames:v", "1", "-q:v", "3", str(quadro)])
    item = {"id": iid, "nome": nome, "tipo": kind, "arquivo": caminho.name, "quadro": quadro.name,
            "duracao": round(float(info.get("duration") or 0), 2), "w": info.get("width", 0), "h": info.get("height", 0),
            "audio": bool(info.get("has_audio")), "criado": time.time(), "quando": quando, "saidas": []}
    store.update(pid, lambda p: _dados(p)["itens"].insert(0, item))
    return item


def item(pid: str, iid: str) -> dict:
    for it in _dados(store.load(pid))["itens"]:
        if it["id"] == iid:
            return it
    raise FileNotFoundError("Arquivo não encontrado (foi apagado?)")


def apagar_item(pid: str, iid: str) -> None:
    it = item(pid, iid)
    base = pasta(pid) / "src"
    (base / it["arquivo"]).unlink(missing_ok=True)
    (base / it["quadro"]).unlink(missing_ok=True)
    store.update(pid, lambda p: _dados(p).update(itens=[x for x in _dados(p)["itens"] if x["id"] != iid]))


# --------------------------------------------------------------------------------------------
# Desenho da capa (Pillow)
# --------------------------------------------------------------------------------------------
_FONTES: dict = {}


def _fonte(nome: str, tam: int):
    from PIL import ImageFont
    chave = (nome, tam)
    if chave not in _FONTES:
        f = Path(nome) if Path(nome).is_absolute() else store.FONTS / nome
        try:
            _FONTES[chave] = ImageFont.truetype(str(f), tam)
        except Exception:
            _FONTES[chave] = ImageFont.truetype(str(store.FONTS / "Poppins-Bold.ttf"), tam)
    return _FONTES[chave]


def _hex(c: str) -> tuple:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _medir(texto: str, fonte, espaco: int = 0) -> tuple[int, int, int]:
    """largura, altura e deslocamento do topo do texto (com espaçamento entre letras)."""
    from PIL import ImageDraw, Image
    d = ImageDraw.Draw(Image.new("L", (4, 4)))
    if not espaco:
        x0, y0, x1, y1 = d.textbbox((0, 0), texto, font=fonte)
        return x1 - x0, y1 - y0, y0
    larg = 0
    for i, ch in enumerate(texto):
        larg += int(d.textlength(ch, font=fonte)) + (espaco if i < len(texto) - 1 else 0)
    x0, y0, x1, y1 = d.textbbox((0, 0), texto, font=fonte)
    return larg, y1 - y0, y0


def _mascara_texto(texto: str, fonte, espaco: int = 0, margem: int = 40):
    """Texto em branco num quadro transparente (canal L), com folga para sombra e brilho."""
    from PIL import Image, ImageDraw
    w, h, top = _medir(texto, fonte, espaco)
    asc, desc = fonte.getmetrics()
    img = Image.new("L", (w + 2 * margem, asc + desc + 2 * margem), 0)
    d = ImageDraw.Draw(img)
    if not espaco:
        x0 = d.textbbox((0, 0), texto, font=fonte)[0]
        d.text((margem - x0, margem), texto, font=fonte, fill=255)
    else:
        x = margem
        for ch in texto:
            d.text((x, margem), ch, font=fonte, fill=255)
            x += int(d.textlength(ch, font=fonte)) + espaco
    bb = img.getbbox()
    if bb:  # recorta deixando a mesma folga em volta do desenho de verdade
        img = img.crop((max(0, bb[0] - margem), max(0, bb[1] - margem), min(img.width, bb[2] + margem),
                        min(img.height, bb[3] + margem)))
    return img


def _textura(cor: str, tam: tuple[int, int], brilho: bool, semente: int):
    """Degradê metálico com pontinhos de glitter (para o destaque)."""
    import numpy as np
    from PIL import Image
    w, h = tam
    tons = [np.array(_hex(c), dtype=np.float32) for c in CORES.get(cor, CORES["dourado"])[1]]
    ys = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    # degradê na diagonal, como luz batendo no metal
    xs = np.linspace(0, 1, w, dtype=np.float32)[None, :]
    t = np.clip(ys * 0.8 + xs * 0.2, 0, 1)
    n = len(tons) - 1
    idx = np.minimum((t * n).astype(int), n - 1)
    frac = (t * n - idx)[..., None]
    a = np.stack(tons)[idx]
    b = np.stack(tons)[idx + 1]
    rgb = a + (b - a) * frac
    if brilho and len(tons) > 2:
        rng = np.random.default_rng(semente)
        ruido = rng.normal(0, 1, (h, w)).astype(np.float32)
        rgb = rgb * (1 + 0.10 * ruido[..., None])            # granulado de glitter
        faisca = rng.random((h, w)) > 0.985                  # pontinhos que brilham
        rgb[faisca] = rgb[faisca] * 0.35 + 255 * 0.65
        escuro = rng.random((h, w)) > 0.975
        rgb[escuro] = rgb[escuro] * 0.55
    return Image.fromarray(np.clip(rgb, 0, 255).astype("uint8"), "RGB")


def _camada_destaque(texto: str, fonte, cor: str, estilo: str, semente: int = 7):
    """Destaque pronto em RGBA (com sombra/brilho)."""
    from PIL import Image, ImageFilter, ImageChops
    m = _mascara_texto(texto, fonte, margem=60)
    w, h = m.size
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if estilo == "neon":
        cor_s = _hex(CORES.get(cor, CORES["azul"])[2] if cor not in ("dourado", "prata", "rose", "branco") else "#3BA0FF")
        for raio, forca in ((26, 0.9), (12, 1.0), (4, 1.0)):
            g = m.filter(ImageFilter.GaussianBlur(raio)).point(lambda v, f=forca: min(255, int(v * f * 1.6)))
            out = Image.alpha_composite(out, Image.merge("RGBA", (*[Image.new("L", (w, h), c) for c in cor_s], g)))
        branco = Image.new("RGBA", (w, h), (255, 255, 255, 0))
        branco.putalpha(m)
        return Image.alpha_composite(out, branco)
    # sombra macia embaixo
    sombra = m.filter(ImageFilter.GaussianBlur(10)).point(lambda v: int(v * 0.65))
    sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sh.putalpha(sombra)
    out.alpha_composite(sh, (0, 6) if h > 6 else (0, 0))
    if cor == "branco":
        corpo = Image.new("RGB", (w, h), (255, 255, 255))
    else:
        corpo = _textura(cor, (w, h), brilho=True, semente=semente)
    camada = corpo.convert("RGBA")
    camada.putalpha(m)
    # contorno fininho mais escuro, dá leitura em fundo claro
    if cor != "branco":
        borda = m.filter(ImageFilter.MaxFilter(3))
        borda = ImageChops.subtract(borda, m)
        cb = Image.new("RGBA", (w, h), (*_hex(CORES.get(cor, CORES["dourado"])[1][0]), 0))
        cb.putalpha(borda.point(lambda v: int(v * 0.8)))
        out = Image.alpha_composite(out, cb)
    out = Image.alpha_composite(out, camada)
    return out


def _camada_texto(texto: str, fonte, cor=(255, 255, 255), espaco: int = 0, sombra: float = 0.55):
    from PIL import Image, ImageFilter
    m = _mascara_texto(texto, fonte, espaco=espaco)
    w, h = m.size
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if sombra:
        s = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        s.putalpha(m.filter(ImageFilter.GaussianBlur(6)).point(lambda v: int(v * sombra)))
        out.alpha_composite(s, (0, 3))
    c = Image.new("RGBA", (w, h), (*cor, 0))
    c.putalpha(m)
    return Image.alpha_composite(out, c)


def _caber(texto: str, nome_fonte: str, tam: int, largura: int, minimo: int, espaco_rel: float = 0.0):
    """Maior fonte em que o texto cabe na largura."""
    while tam > minimo:
        f = _fonte(nome_fonte, tam)
        if _medir(texto, f, int(tam * espaco_rel))[0] <= largura:
            return f, tam
        tam -= 4
    return _fonte(nome_fonte, minimo), minimo


def _quebrar(texto: str) -> list[str]:
    """Divide em duas linhas equilibradas."""
    p = texto.split()
    if len(p) < 2:
        return [texto]
    melhor, dif = [texto], 10 ** 9
    for i in range(1, len(p)):
        a, b = " ".join(p[:i]), " ".join(p[i:])
        d = abs(len(a) - len(b))
        if d < dif:
            melhor, dif = [a, b], d
    return melhor


def _destaque_linhas(texto: str, nome_fonte: str, tam: int, largura: int, minimo: int, tam2: int = 0):
    """Uma linha se couber grande; senão, duas (com letra um pouco menor, para não subir demais)."""
    f, t = _caber(texto, nome_fonte, tam, largura, minimo)
    if t > minimo * 1.25 or len(texto.split()) < 2:
        return [(texto, f)]
    linhas = _quebrar(texto)
    t2 = min(_caber(x, nome_fonte, tam2 or int(tam * 0.9), largura, minimo)[1] for x in linhas)
    return [(x, _fonte(nome_fonte, t2)) for x in linhas]


def _logo_img(lid: str, maximo: tuple[int, int]):
    from PIL import Image
    f = arquivo_logo(lid)
    if not f:
        return None
    im = Image.open(f).convert("RGBA")
    im.thumbnail(maximo, Image.LANCZOS)
    return im


def _empilhar(cv, camadas: list, cx: int, topo: int, espacos: list[int]) -> int:
    """Cola as camadas centralizadas, uma embaixo da outra, e devolve onde terminou."""
    y = topo
    for i, c in enumerate(camadas):
        if c is None:
            continue
        cv.alpha_composite(c, (int(cx - c.width / 2), int(y)))
        y += c.height + (espacos[i] if i < len(espacos) else 0)
    return y


def desenhar(op: dict):
    """Devolve (overlay RGBA, máscara L da parte desfocada, escurecer 0..1)."""
    from PIL import Image, ImageDraw, ImageFilter
    modelo = op.get("modelo") if op.get("modelo") in MODELOS else "ouro"
    cor = op.get("cor") if op.get("cor") in CORES else "dourado"
    l1 = (op.get("linha1") or "").strip()
    l2 = (op.get("destaque") or "").strip() or "Culto"
    l3 = (op.get("linha3") or "").strip()
    lid = op.get("logo") or ""
    _fd, _fl = op.get("fonte_destaque") or "", op.get("fonte_linha1") or ""
    FD = str(arquivo_fonte(_fd)) if arquivo_fonte(_fd) else None   # letra escolhida para o destaque
    FL = str(arquivo_fonte(_fl)) if arquivo_fonte(_fl) else None   # letra escolhida para a linha de cima
    maius_d = not FD or (_fd in FONTES and FONTES[_fd][2] == "Fortes")  # cursiva em maiúsculas fica feia
    up1 = (lambda t: t) if (FL and (_cursiva(_fl) or _fl.startswith("u-"))) else (lambda t: t.upper())
    esp1 = 0.0 if FL and _cursiva(_fl) else None
    t1 = (lambda n: int(n * 1.6)) if esp1 == 0.0 else (lambda n: n)  # cursiva pequena precisa de letra maior
    semente = int(hashlib.md5(l2.encode()).hexdigest()[:6], 16)
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    mask = Image.new("L", (W, H), 0)
    md = ImageDraw.Draw(mask)
    LARG = 940

    def faixa_desfocada(y0: int, y1: int, pena: int = 170, de_baixo: bool = True):
        if de_baixo:
            md.rectangle((0, y0 + pena, W, y1), fill=255)
            for k in range(pena):
                md.line((0, y0 + k, W, y0 + k), fill=int(255 * (k / pena) ** 1.4))
        else:
            md.rectangle((0, y0, W, y1 - pena), fill=255)
            for k in range(pena):
                md.line((0, y1 - pena + k, W, y1 - pena + k), fill=int(255 * (1 - k / pena) ** 1.4))

    def degrade(y0: int, y1: int, maximo: int, de_baixo: bool = True):
        g = Image.new("L", (1, y1 - y0))
        for k in range(y1 - y0):
            t = k / max(1, y1 - y0 - 1)
            g.putpixel((0, k), int(maximo * (t if de_baixo else 1 - t) ** 1.2))
        g = g.resize((W, y1 - y0))
        cam = Image.new("RGBA", (W, y1 - y0), (0, 0, 0, 0))
        cam.putalpha(g)
        ov.alpha_composite(cam, (0, y0))

    kick = None
    if modelo in ("ouro", "topo", "vidro"):
        if l1:
            e1 = 0.14 if esp1 is None else esp1
            f, _ = _caber(up1(l1), FL or "Montserrat-ExtraBold.ttf", t1(66), LARG, t1(34), e1)
            kick = _camada_texto(up1(l1), f, espaco=int(f.size * e1))
    elif modelo == "assinatura":
        if l1:
            e1 = 0.10 if esp1 is None else esp1
            f, _ = _caber(up1(l1), FL or "Cinzel-Bold.ttf", t1(70), LARG, t1(36), e1)
            kick = _camada_texto(up1(l1), f, espaco=int(f.size * e1))
    sub = None
    if l3:
        f, _ = _caber(l3, "Montserrat-SemiBold.ttf", 40, LARG, 26)
        sub = _camada_texto(l3, f, cor=(240, 240, 240), sombra=0.6)

    if modelo in ("ouro", "topo"):
        linhas = _destaque_linhas(l2, FD or "PlayfairDisplay-ExtraBold.ttf", 300 if modelo == "ouro" else 250, LARG, 110, 185)
        dest = [_camada_destaque(t, f, cor, "metal", semente + i) for i, (t, f) in enumerate(linhas)]
        logo = _logo_img(lid, (190, 150))
        logo_canto = None
        if modelo == "ouro" and len(dest) > 1 and logo:  # título em 2 linhas: o logo vai para o canto (não sobe a tarja)
            logo_canto, logo = _logo_img(lid, (160, 130)), None
            ov.alpha_composite(logo_canto, (W - 50 - logo_canto.width, 240))
        if modelo == "ouro":
            altura = sum(c.height for c in dest) - 80 * (len(dest) - 1) + (kick.height - 30 if kick else 0) \
                + (sub.height - 20 if sub else 0) + (logo.height + 10 if logo else 0)
            fim = 1690
            topo = fim - altura
            faixa_desfocada(min(1240, topo - 200), H)
            degrade(min(1240, topo - 200), H, 110)
            y = topo
            if logo:
                ov.alpha_composite(logo, (W // 2 - logo.width // 2, int(y)))
                y += logo.height + 10
            if kick:
                ov.alpha_composite(kick, (W // 2 - kick.width // 2, int(y)))
                y += kick.height - 46
            for c in dest:
                ov.alpha_composite(c, (W // 2 - c.width // 2, int(y)))
                y += c.height - 80
            if sub:
                ov.alpha_composite(sub, (W // 2 - sub.width // 2, int(y + 50)))
        else:  # topo
            y = 250
            alt = (kick.height - 46 if kick else 0) + sum(c.height - 80 for c in dest) + 80 + (sub.height if sub else 0)
            faixa_desfocada(0, min(H, y + alt + 90), pena=110, de_baixo=False)
            degrade(0, min(H, y + alt + 90), 110, de_baixo=False)
            if kick:
                ov.alpha_composite(kick, (W // 2 - kick.width // 2, y))
                y += kick.height - 46
            for c in dest:
                ov.alpha_composite(c, (W // 2 - c.width // 2, int(y)))
                y += c.height - 80
            if sub:
                ov.alpha_composite(sub, (W // 2 - sub.width // 2, int(y + 50)))
            if logo:
                cx = W // 2 - logo.width // 2
                halo = Image.new("RGBA", (logo.width + 60, logo.height + 60), (0, 0, 0, 0))
                hm = logo.getchannel("A").resize((logo.width, logo.height))
                hal = Image.new("L", halo.size, 0)
                hal.paste(hm, (30, 30))
                halo.putalpha(hal.filter(ImageFilter.GaussianBlur(14)).point(lambda v: int(v * 0.6)))
                ov.alpha_composite(halo, (cx - 30, 1560 - 30))
                ov.alpha_composite(logo, (cx, 1560))
        return ov, mask, 0.12

    if modelo == "assinatura":
        linhas = _destaque_linhas(l2, FD or "GreatVibes-Regular.ttf", 320, LARG, 120, 230)
        dest = [_camada_destaque(t, f, cor, "metal", semente + i) for i, (t, f) in enumerate(linhas)]
        logo = _logo_img(lid, (150, 120))
        alt = (kick.height - 40 if kick else 0) + sum(c.height - 90 for c in dest) + 90 + (sub.height if sub else 0)
        fim = 1700
        topo = fim - alt
        faixa_desfocada(min(1240, topo - 220), H)
        degrade(min(1240, topo - 220), H, 120)
        y = topo
        if kick:
            ov.alpha_composite(kick, (W // 2 - kick.width // 2, int(y)))
            y += kick.height - 40
        for c in dest:
            ov.alpha_composite(c, (W // 2 - c.width // 2, int(y)))
            y += c.height - 90
        if sub:
            ov.alpha_composite(sub, (W // 2 - sub.width // 2, int(y + 70)))
        if logo:
            ov.alpha_composite(logo, (W - 50 - logo.width, 240))
        return ov, mask, 0.15

    if modelo == "faixa":
        cor_s = _hex(CORES[cor][2] if cor != "branco" else "#FF8A3D")
        degrade(1080, H, 235)
        linhas = _destaque_linhas(l2.upper() if maius_d else l2, FD or "Anton-Regular.ttf", 230, LARG, 110, 170)
        dest = [_camada_texto(t, f, sombra=0.5) for t, f in linhas]
        y = 1700 - sum(c.height - 40 for c in dest) - (sub.height + 10 if sub else 0)
        if l1:
            e1 = 0.12 if esp1 is None else esp1
            f, _ = _caber(up1(l1), FL or "Montserrat-ExtraBold.ttf", t1(42), 700, t1(28), e1)
            tx = _camada_texto(up1(l1), f, cor=(20, 20, 20), espaco=int(f.size * e1), sombra=0)
            pill = Image.new("RGBA", (tx.width + 6, tx.height - 10), (*cor_s, 255))
            pm = Image.new("L", pill.size, 0)
            ImageDraw.Draw(pm).rounded_rectangle((0, 0, pill.width - 1, pill.height - 1), radius=pill.height // 2, fill=255)
            pill.putalpha(pm)
            pill.alpha_composite(tx, (3, -5))
            y -= pill.height + 24
            ov.alpha_composite(pill, (W // 2 - pill.width // 2, int(y)))
            y += pill.height + 4
        for c in dest:
            ov.alpha_composite(c, (W // 2 - c.width // 2, int(y)))
            y += c.height - 40
        barra = Image.new("RGBA", (180, 10), (*cor_s, 255))
        ov.alpha_composite(barra, (W // 2 - 90, int(y + 50)))
        if sub:
            ov.alpha_composite(sub, (W // 2 - sub.width // 2, int(y + 70)))
        logo = _logo_img(lid, (170, 130))
        if logo:
            ov.alpha_composite(logo, (W - 50 - logo.width, 240))
        return ov, mask, 0.0

    if modelo == "neon":
        neon_cor = cor if cor not in ("dourado", "prata", "rose", "branco") else "azul"
        linhas = _destaque_linhas(l2.upper() if maius_d else l2, FD or "BebasNeue-Regular.ttf", 260, LARG, 120, 200)
        dest = [_camada_destaque(t, f, neon_cor, "neon") for t, f in linhas]
        k = None
        if l1:
            e1 = 0.35 if esp1 is None else esp1
            f, _ = _caber(up1(l1), FL or "Montserrat-SemiBold.ttf", t1(48), LARG, t1(28), e1)
            k = _camada_texto(up1(l1), f, cor=_hex(CORES[neon_cor][2]), espaco=int(f.size * e1), sombra=0.4)
        logo = _logo_img(lid, (160, 130))
        alt = (k.height - 30 if k else 0) + sum(c.height - 110 for c in dest) + 110 + (sub.height if sub else 0) \
            + (logo.height + 10 if logo else 0)
        topo = 1700 - alt
        faixa_desfocada(min(1220, topo - 200), H)
        degrade(min(1220, topo - 200), H, 170)
        y = topo
        if logo:
            ov.alpha_composite(logo, (W // 2 - logo.width // 2, int(y)))
            y += logo.height + 10
        if k:
            ov.alpha_composite(k, (W // 2 - k.width // 2, int(y)))
            y += k.height - 30
        for c in dest:
            ov.alpha_composite(c, (W // 2 - c.width // 2, int(y)))
            y += c.height - 110
        if sub:
            ov.alpha_composite(sub, (W // 2 - sub.width // 2, int(y + 90)))
        return ov, mask, 0.25

    # vidro: cartão transparente com o logo do lado
    logo = _logo_img(lid, (210, 210))
    larg_txt = 800 - (logo.width + 40 if logo else 0)
    linhas = _destaque_linhas(l2, FD or "PlayfairDisplay-ExtraBold.ttf", 150, larg_txt, 70)
    dest = [_camada_destaque(t, f, cor, "metal", semente + i) for i, (t, f) in enumerate(linhas)]
    if l1:
        e1 = 0.14 if esp1 is None else esp1
        f, _ = _caber(up1(l1), FL or "Montserrat-ExtraBold.ttf", t1(44), larg_txt, t1(26), e1)
        kick = _camada_texto(up1(l1), f, espaco=int(f.size * e1))
    if l3:
        f, _ = _caber(l3, "Montserrat-SemiBold.ttf", 34, larg_txt, 22)
        sub = _camada_texto(l3, f, cor=(240, 240, 240), sombra=0.6)
    alt_txt = (kick.height - 40 if kick else 0) + sum(c.height - 70 for c in dest) + 70 + (sub.height - 30 if sub else 0)
    alt = max(alt_txt, (logo.height + 20) if logo else 0) + 40
    x0, x1 = 60, W - 60
    y1 = 1700
    y0 = y1 - alt
    md.rounded_rectangle((x0, y0, x1, y1), radius=42, fill=255)
    card = Image.new("RGBA", (x1 - x0, y1 - y0), (255, 255, 255, 34))
    cm = Image.new("L", card.size, 0)
    ImageDraw.Draw(cm).rounded_rectangle((0, 0, card.width - 1, card.height - 1), radius=42, fill=34)
    card.putalpha(cm)
    borda = Image.new("RGBA", card.size, (0, 0, 0, 0))
    ImageDraw.Draw(borda).rounded_rectangle((1, 1, card.width - 2, card.height - 2), radius=42,
                                            outline=(255, 255, 255, 110), width=3)
    ov.alpha_composite(card, (x0, y0))
    ov.alpha_composite(borda, (x0, y0))
    tx = x0 + 40
    if logo:
        ov.alpha_composite(logo, (tx, int(y0 + (alt - logo.height) / 2)))
        tx += logo.width + 30
    cx = tx + larg_txt // 2
    y = y0 + (alt - alt_txt) / 2 - 10
    if kick:
        ov.alpha_composite(kick, (int(cx - kick.width / 2), int(y)))
        y += kick.height - 40
    for c in dest:
        ov.alpha_composite(c, (int(cx - c.width / 2), int(y)))
        y += c.height - 70
    if sub:
        ov.alpha_composite(sub, (int(cx - sub.width / 2), int(y + 40)))
    return ov, mask, 0.18


# --------------------------------------------------------------------------------------------
# FFmpeg: junta a base (vídeo/foto) com a parte desfocada e a capa
# --------------------------------------------------------------------------------------------
def _modo(op: dict, it: dict) -> str:
    m = op.get("enquadrar") or "auto"
    if m in ("desfocado", "preencher"):
        return m
    w, h = it.get("w") or 1, it.get("h") or 1
    return "preencher" if h / w >= 1.55 else "desfocado"


def _grafo(modo: str, escurecer: float, zoom_seg: float = 0.0, saida_previa: bool = False, para_baixo: bool = False) -> str:
    """[0] = vídeo/foto, [1] = máscara (cinza), [2] = capa (RGBA)."""
    z = ""
    if zoom_seg:  # zoom bem lento na foto (8% ao longo do story)
        z = (f",scale=w='trunc({W}*(1+0.08*t/{zoom_seg:.2f})/2)*2':h='trunc({H}*(1+0.08*t/{zoom_seg:.2f})/2)*2'"
             f":eval=frame,crop={W}:{H}")
    if modo == "preencher":
        base = f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},setsar=1{z}[base]"
    else:
        base = (f"[0:v]split=2[f0][f1];"
                f"[f0]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=18:3,"
                f"scale={W}:{H}:flags=bicubic,eq=brightness=-0.10:saturation=1.15[bg];"
                f"[f1]scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2{'+' if para_baixo else '-'}((H-h)/2)*0.18,setsar=1{z}[base]")
    # a parte desfocada: borra uma cópia pequena (rápido) e aumenta de novo
    escur = f",eq=brightness={-escurecer:.2f}" if escurecer else ""
    g = (base + ";[base]split=2[b0][b1];"
         f"[b1]scale=360:640,boxblur=14:2,scale={W}:{H}:flags=bicubic{escur}[bl];"
         "[1:v]format=gray,scale=%d:%d[m];[bl][m]alphamerge[blm];" % (W, H) +
         "[b0][blm]overlay=0:0[c];[c][2:v]overlay=0:0:format=auto")
    if saida_previa:
        g += ",scale=540:960:flags=bicubic"
    g += ",format=yuv420p[v]"
    return g


def _arquivos_capa(op: dict, destino: Path) -> tuple[Path, Path, float]:
    ov, mask, esc = desenhar(op)
    destino.mkdir(parents=True, exist_ok=True)
    chave = hashlib.md5(json.dumps({k: op.get(k) for k in ("modelo", "cor", "linha1", "destaque", "linha3", "logo", "fonte_destaque", "fonte_linha1")},
                                   sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:10]
    fo, fm = destino / f"capa-{chave}.png", destino / f"mask-{chave}.png"
    ov.save(fo)
    mask.save(fm)
    return fo, fm, esc


def previa(pid: str, iid: str, op: dict) -> bytes:
    it = item(pid, iid)
    base = pasta(pid)
    fo, fm, esc = _arquivos_capa(op, base / "tmp")
    out = base / "tmp" / f"previa-{secrets.token_hex(4)}.jpg"
    try:
        ff.run([ff.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(base / "src" / it["quadro"]),
                "-i", str(fm), "-i", str(fo), "-filter_complex", _grafo(_modo(op, it), esc, saida_previa=True, para_baixo=op.get('modelo') == 'topo'),
                "-map", "[v]", "-frames:v", "1", "-q:v", "4", str(out)])
        return out.read_bytes()
    finally:
        out.unlink(missing_ok=True)
        fo.unlink(missing_ok=True)
        fm.unlink(missing_ok=True)


def _cod_args() -> list[str]:
    cfg = store.load_config()
    enc = ff.best_encoder((cfg.get("render") or {}).get("encoder", "auto"))
    args = ff.encoder_args(enc, "alta")
    # o Instagram recusa story pesado: segura a taxa (60 s ficam com uns 70 MB no máximo)
    return args + ["-maxrate", "9M", "-bufsize", "18M"]


def _nome_saida(op: dict) -> str:
    base = " ".join(x for x in ((op.get("linha1") or ""), (op.get("destaque") or "")) if x).strip() or "story"
    base = re.sub(r"[^\w\- ]+", "", base, flags=re.UNICODE).strip().replace(" ", "-")[:50] or "story"
    return f"story-{time.strftime('%Y%m%d-%H%M%S')}-{base}"


def gerar(pid: str, iids: list[str], op: dict, progresso: Progresso = None) -> dict:
    """Gera os stories de vários arquivos com a mesma capa. Devolve a lista de arquivos prontos."""
    prog = progresso or (lambda x, m="": None)
    proj = store.load(pid)
    itens = [it for it in _dados(proj)["itens"] if it["id"] in iids]
    itens.sort(key=lambda it: iids.index(it["id"]))
    if not itens:
        raise RuntimeError("Escolha pelo menos um vídeo ou foto.")
    base = pasta(pid)
    renders = store.pdir(pid) / "renders"
    renders.mkdir(exist_ok=True)
    tamanho = op.get("tamanho") if op.get("tamanho") in TAMANHOS else "partes"
    fo, fm, esc = _arquivos_capa(op, base / "tmp")
    rotulo = " ".join(x for x in (op.get("linha1"), op.get("destaque")) if x).strip() or "Story"
    # quanto trabalho tem (para a barra de progresso)
    tarefas = []
    for it in itens:
        if it["tipo"] == "image":
            tarefas.append((it, 0.0, FOTO_SEG, 1, 1))
            continue
        dur = float(it.get("duracao") or 0)
        if tamanho == "inteiro" or dur <= SEG_MAX + 1:
            tarefas.append((it, 0.0, dur, 1, 1))
        elif tamanho == "inicio":
            tarefas.append((it, 0.0, SEG_MAX, 1, 1))
        else:
            n = min(PARTES_MAX, math.ceil(dur / SEG_MAX))
            passo = dur / n
            for k in range(n):
                tarefas.append((it, k * passo, passo if k < n - 1 else dur - k * passo, k + 1, n))
    total = sum(max(1.0, t[2]) for t in tarefas)
    feito = 0.0
    saidas = []
    cod = _cod_args()
    nome_base = _nome_saida(op)
    try:
        for i, (it, ini, dur, parte, partes) in enumerate(tarefas):
            src = base / "src" / it["arquivo"]
            if not src.exists():
                raise RuntimeError(f"O arquivo “{it['nome']}” não está mais aqui. Envie de novo.")
            sufixo = f"-{i + 1}" if len(tarefas) > 1 else ""
            nome = f"{nome_base}{sufixo}.mp4"
            alvo = renders / nome
            msg = f"Criando o story {i + 1} de {len(tarefas)}" + (f" (parte {parte} de {partes})" if partes > 1 else "") + "…"
            prog(feito / total, msg)

            def p_ff(x, d=dur, f0=feito, m=msg):
                prog(min(0.99, (f0 + x * max(1.0, d)) / total), m)
            if it["tipo"] == "image":
                args = [ff.ffmpeg(), "-y", "-loop", "1", "-framerate", "30", "-t", f"{FOTO_SEG}", "-i", str(src),
                        "-i", str(fm), "-i", str(fo), "-f", "lavfi", "-t", f"{FOTO_SEG}",
                        "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                        "-filter_complex", _grafo(_modo(op, it), esc, zoom_seg=FOTO_SEG, para_baixo=op.get('modelo') == 'topo'),
                        "-map", "[v]", "-map", "3:a", "-t", f"{FOTO_SEG}", "-r", "30"] + cod + \
                       ["-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(alvo)]
                ff.run_with_progress(args, FOTO_SEG, p_ff)
                # a foto também sai como imagem (JPG) para baixar
                jpg = renders / f"{Path(nome).stem}.jpg"
                ff.run([ff.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-i", str(fm),
                        "-i", str(fo), "-filter_complex", _grafo(_modo(op, it), esc, para_baixo=op.get('modelo') == 'topo'), "-map", "[v]", "-frames:v", "1",
                        "-q:v", "2", str(jpg)])
            else:
                fps = ["-r", "30"]
                args = [ff.ffmpeg(), "-y", "-ss", f"{ini:.3f}", "-t", f"{dur:.3f}", "-i", str(src),
                        "-loop", "1", "-i", str(fm), "-loop", "1", "-i", str(fo),
                        "-filter_complex", _grafo(_modo(op, it), esc, para_baixo=op.get('modelo') == 'topo'), "-map", "[v]"]
                if it.get("audio"):
                    args += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "160k", "-ar", "44100"]
                else:
                    args += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100", "-map", "3:a",
                             "-c:a", "aac", "-b:a", "96k"]
                args += fps + ["-t", f"{dur:.3f}"] + cod + ["-movflags", "+faststart", "-shortest", str(alvo)]
                if not it.get("audio"):  # a entrada do silêncio precisa vir antes do -filter_complex
                    args = [ff.ffmpeg(), "-y", "-ss", f"{ini:.3f}", "-t", f"{dur:.3f}", "-i", str(src),
                            "-loop", "1", "-i", str(fm), "-loop", "1", "-i", str(fo),
                            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                            "-filter_complex", _grafo(_modo(op, it), esc, para_baixo=op.get('modelo') == 'topo'), "-map", "[v]", "-map", "3:a",
                            "-c:a", "aac", "-b:a", "96k"] + fps + ["-t", f"{dur:.3f}"] + cod + \
                           ["-movflags", "+faststart", str(alvo)]
                ff.run_with_progress(args, dur, p_ff)
            feito += max(1.0, dur)
            try:
                d_real = round(ff.probe(str(alvo))["duration"], 2)
            except Exception:
                d_real = round(dur, 2)
            lab = rotulo + (f" · parte {parte}/{partes}" if partes > 1 else "") + (" · foto" if it["tipo"] == "image" else "")
            reg = {"file": nome, "created": time.time(), "duration": d_real, "label": f"Story: {lab}",
                   "size": alvo.stat().st_size, "platform": "ig_stories", "story": True,
                   "jpg": f"{Path(nome).stem}.jpg" if it["tipo"] == "image" else ""}
            saidas.append(reg)
            store.update(pid, lambda p, r=reg, iid=it["id"]: (
                p.setdefault("renders", []).insert(0, {k: v for k, v in r.items() if k != "jpg"}),
                [x.setdefault("saidas", []).insert(0, {"file": r["file"], "jpg": r["jpg"], "label": r["label"],
                                                       "created": r["created"], "duration": r["duration"]})
                 for x in _dados(p)["itens"] if x["id"] == iid]))
    finally:
        fo.unlink(missing_ok=True)
        fm.unlink(missing_ok=True)

    def lembrar(p):
        d = _dados(p)
        ev = op.get("evento") or ""
        if ev in EVENTOS or any(m["id"] == ev for m in d.get("meus_eventos") or []):
            d["usados"][ev] = int(d["usados"].get(ev, 0)) + 1
        d["ultimo"] = {k: op.get(k) for k in ("modelo", "cor", "logo", "enquadrar", "tamanho", "data_na_tela", "fonte_destaque", "fonte_linha1")}
        d["evento_atual"] = {k: op.get(k) for k in ("evento", "linha1", "destaque")} | {"quando": time.time()}
    store.update(pid, lembrar)
    prog(1.0, "Pronto!")
    return {"saidas": saidas, "quantos": len(saidas)}


def lista(pid: str) -> list[dict]:
    """Arquivos enviados (mais novos primeiro) com os stories que já saíram de cada um."""
    proj = store.load(pid)
    renders = store.pdir(pid) / "renders"
    out = []
    for it in _dados(proj)["itens"][:60]:
        saidas = [s for s in it.get("saidas", []) if (renders / s["file"]).exists()]
        out.append({k: it.get(k) for k in ("id", "nome", "tipo", "duracao", "w", "h", "criado", "quando")} | {"saidas": saidas})
    return out


def limpar_temporarios(pid: str) -> None:
    for f in (pasta(pid) / "tmp").glob("*"):
        if time.time() - f.stat().st_mtime > 3600:
            f.unlink(missing_ok=True)


def meus_eventos(pid: str) -> list[dict]:
    return list(_dados(store.load(pid)).get("meus_eventos") or [])


def salvar_evento(pid: str, ev: dict) -> dict:
    l1 = str(ev.get("linha1") or "").strip()[:40]
    l2 = str(ev.get("destaque") or "").strip()[:40]
    if not l2:
        raise ValueError("Escreva o nome em destaque do evento.")
    fd = str(ev.get("fonte_destaque") or "")
    fl = str(ev.get("fonte_linha1") or "")
    novo = {"id": "m-" + secrets.token_hex(4), "linha1": l1, "destaque": l2,
            "fonte_destaque": fd if arquivo_fonte(fd) else "", "fonte_linha1": fl if arquivo_fonte(fl) else "",
            "criado": time.time()}

    def gravar(p):
        lst = _dados(p).setdefault("meus_eventos", [])
        for x in lst:  # mesmo nome: só atualiza as letras
            if x["linha1"].lower() == l1.lower() and x["destaque"].lower() == l2.lower():
                x.update(fonte_destaque=novo["fonte_destaque"], fonte_linha1=novo["fonte_linha1"])
                novo.update(id=x["id"])
                return
        lst.insert(0, novo)
        del lst[80:]
    store.update(pid, gravar)
    return novo


def apagar_evento(pid: str, eid: str) -> None:
    store.update(pid, lambda p: _dados(p).update(
        meus_eventos=[x for x in _dados(p).get("meus_eventos") or [] if x["id"] != eid]))


def status() -> dict:
    proj = projeto()
    d = _dados(proj)
    meus = d.get("meus_eventos") or []
    grupos = [{"nome": g, "eventos": [{"id": k, "linha1": a, "destaque": b} for k, a, b in itens]} for g, itens in GRUPOS]
    if meus:
        grupos.insert(0, {"nome": "Meus eventos", "meus": True, "eventos": [
            {k: x.get(k, "") for k in ("id", "linha1", "destaque", "fonte_destaque", "fonte_linha1")} | {"meu": True}
            for x in meus]})
    fontes = [{"id": k, "nome": v[1], "grupo": v[2], "arquivo": v[0]} for k, v in FONTES.items()] + fontes_minhas()
    return {"pid": proj["id"], "grupos": grupos, "fontes": fontes,
            "modelos": [{"id": k, **v} for k, v in MODELOS.items()],
            "cores": [{"id": k, "nome": v[0], "hex": v[2]} for k, v in CORES.items()],
            "enquadrar": ENQUADRAR, "tamanhos": TAMANHOS, "logos": logos(),
            "sugestao": sugestao(usados=d.get("usados"), meus={x["id"] for x in meus}), "ultimo": d.get("ultimo") or {}}


# --------------------------------------------------------------------------------------------
# v1.15.1: excluir stories prontos e juntar os arquivos do culto num Resumo
# --------------------------------------------------------------------------------------------
def agendado(pid: str, arquivo: str) -> bool:
    from . import publish
    return any(it.get("project") == pid and it.get("file") == arquivo and it.get("status") in ("agendado", "publicando")
               for it in publish.queue())


def apagar_pronto(pid: str, arquivo: str) -> bool:
    """Apaga o story (vídeo e a foto JPG, se tiver). Devolve False se ele está na fila de publicação."""
    if "/" in arquivo or "\\" in arquivo or not arquivo.startswith("story-"):
        raise ValueError("Nome inválido")
    if agendado(pid, arquivo):
        return False
    renders = store.pdir(pid) / "renders"
    (renders / arquivo).unlink(missing_ok=True)
    (renders / f"{Path(arquivo).stem}.jpg").unlink(missing_ok=True)
    (store.pdir(pid) / "cache" / f"rt-{Path(arquivo).stem}.jpg").unlink(missing_ok=True)

    def tirar(p):
        p["renders"] = [r for r in p.get("renders") or [] if r.get("file") != arquivo]
        for it in _dados(p)["itens"]:
            it["saidas"] = [x for x in it.get("saidas") or [] if x.get("file") != arquivo]
    store.update(pid, tirar)
    return True


EVENTO_RESUMO = {  # evento dos Stories -> tipo do Resumo do Culto
    "santa_ceia": "santa_ceia", "batismo": "batismo", "casamento": "casamento", "aniversario": "aniversario",
    "bodas": "casamento", "jovens": "jovens", "adolescentes": "jovens", "congresso_jovens": "jovens",
    "congresso_adolescentes": "jovens", "encontro_jovens": "jovens", "congresso": "conferencia",
    "congresso_mulheres": "conferencia", "congresso_criancas": "conferencia", "congresso_varoes": "conferencia",
    "congresso_missoes": "conferencia", "encontro_mulheres": "conferencia", "encontro_casais": "conferencia",
    "conferencia": "conferencia", "seminario": "conferencia", "retiro": "conferencia", "acampamento": "conferencia",
    "cruzada": "conferencia", "festividade": "conferencia", "convencao": "conferencia", "simposio": "conferencia",
    "escola_lideres": "conferencia",
}


def juntar_no_resumo(pid_st: str, iids: list[str], destino: str) -> int:
    """Copia os vídeos/fotos originais (sem a capa) para o projeto do resumo, na ordem em que foram enviados."""
    import os
    proj = store.load(pid_st)
    itens = [it for it in _dados(proj)["itens"] if it["id"] in iids]
    itens.sort(key=lambda it: it.get("criado") or 0)
    n = 0
    for it in itens:
        src = pasta(pid_st) / "src" / it["arquivo"]
        if not src.exists():
            continue
        alvo = montagem.pasta_midias(destino) / f"{secrets.token_hex(4)}_{Path(it['arquivo']).name.split('_', 1)[-1]}"
        try:
            os.link(src, alvo)  # mesmo disco: não ocupa espaço de novo
        except Exception:
            shutil.copy2(src, alvo)
        extra = {"quando": it["quando"]} if it.get("quando") else None
        nome = it.get("nome") or alvo.name
        if montagem.tipo_por_extensao(nome) != it["tipo"]:
            nome = Path(nome).stem + Path(it["arquivo"]).suffix
        montagem.adicionar_midia(destino, alvo, nome, extra)
        n += 1
    return n

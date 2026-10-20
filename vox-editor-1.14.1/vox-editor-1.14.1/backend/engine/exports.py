"""Exportação para editores profissionais: EDL (CMX3600) e XML (Final Cut 7 / Premiere / DaVinci Resolve)."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape


def _tc(frames: int, fps: int) -> str:
    f = frames % fps
    s = frames // fps
    return f"{s // 3600:02d}:{(s // 60) % 60:02d}:{s % 60:02d}:{f:02d}"


def _frames(keeps: list[list[float]], fps: float) -> list[tuple[int, int]]:
    return [(int(round(s * fps)), int(round(e * fps))) for s, e in keeps if round(e * fps) > round(s * fps)]


def to_edl(keeps: list[list[float]], fps: float, src_name: str, title: str) -> str:
    base = int(round(fps))
    lines = [f"TITLE: {title}", "FCM: NON-DROP FRAME", ""]
    rec = 0
    for i, (a, b) in enumerate(_frames(keeps, fps), 1):
        n = b - a
        lines.append(f"{i:03d}  AX       AA/V  C        {_tc(a, base)} {_tc(b, base)} {_tc(rec, base)} {_tc(rec + n, base)}")
        lines.append(f"* FROM CLIP NAME: {src_name}")
        lines.append("")
        rec += n
    return "\n".join(lines)


def _path_url(path: str) -> str:
    p = str(Path(path).resolve()).replace("\\", "/")
    if not p.startswith("/"):
        p = "/" + p
    return "file://localhost" + quote(p)


def to_fcpxml7(keeps: list[list[float]], media: dict, src_path: str, title: str) -> str:
    fps = media.get("fps") or 30.0
    base = int(round(fps))
    ntsc = "TRUE" if abs(fps - base) > 0.01 else "FALSE"
    rate = f"<rate><timebase>{base}</timebase><ntsc>{ntsc}</ntsc></rate>"
    total_src = int(round(media["duration"] * fps))
    w, h = media.get("width") or 1920, media.get("height") or 1080
    name = escape(Path(src_path).name)
    fr = _frames(keeps, fps)
    seq_len = sum(b - a for a, b in fr)
    file_def = (f'<file id="file-1"><name>{name}</name><pathurl>{escape(_path_url(src_path))}</pathurl>{rate}'
                f"<duration>{total_src}</duration><media>"
                + (f"<video><samplecharacteristics>{rate}<width>{w}</width><height>{h}</height></samplecharacteristics></video>"
                   if media.get("has_video") else "")
                + "<audio><samplecharacteristics><depth>16</depth><samplerate>48000</samplerate></samplecharacteristics>"
                  "<channelcount>2</channelcount></audio></media></file>")

    def items(kind: str, track: int) -> str:
        out, rec = [], 0
        for i, (a, b) in enumerate(fr, 1):
            n = b - a
            fileref = file_def if (i == 1 and kind == "video") or (i == 1 and kind == "audio" and track == 1 and not media.get("has_video")) else '<file id="file-1"/>'
            extra = (f"<sourcetrack><mediatype>audio</mediatype><trackindex>{track}</trackindex></sourcetrack>"
                     if kind == "audio" else "")
            out.append(f'<clipitem id="{kind}{track}-{i}"><name>{name}</name><enabled>TRUE</enabled>'
                       f"<duration>{total_src}</duration>{rate}<start>{rec}</start><end>{rec + n}</end>"
                       f"<in>{a}</in><out>{b}</out>{fileref}{extra}</clipitem>")
            rec += n
        return "".join(out)

    video = (f"<video><format><samplecharacteristics>{rate}<width>{w}</width><height>{h}</height>"
             f"<pixelaspectratio>square</pixelaspectratio></samplecharacteristics></format>"
             f"<track>{items('video', 1)}</track></video>") if media.get("has_video") else ""
    audio = f"<audio><track>{items('audio', 1)}</track><track>{items('audio', 2)}</track></audio>"
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="5">'
            f'<sequence id="seq-1"><name>{escape(title)}</name><duration>{seq_len}</duration>{rate}'
            f"<timecode>{rate}<string>00:00:00:00</string><frame>0</frame><displayformat>NDF</displayformat></timecode>"
            f"<media>{video}{audio}</media></sequence></xmeml>\n")


def to_text(words: list[dict], segments: list[dict]) -> str:
    if segments:
        out = []
        for s in segments:
            m, sec = divmod(int(s["s"]), 60)
            out.append(f"[{m:02d}:{sec:02d}] {s['text']}")
        return "\n".join(out)
    return " ".join(w["w"] for w in words)

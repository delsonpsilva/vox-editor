"""Emendas inteligentes: garante que todo corte aconteça numa pausa real (vale de silêncio, sem voz),
nunca no meio de uma sílaba. A transcrição dá o horário aproximado das palavras; o som dá o lugar exato."""
from __future__ import annotations

import numpy as np

from .audio import FRAME_S

# Quanto de pausa manter em cada emenda, por ritmo (segundos):
# rabo = depois da última palavra (deixa a voz terminar e o eco morrer)
# cabeça = antes da próxima palavra (preserva a consoante inicial e a respiração curta)
# frase = pausa extra quando a frase anterior termina com ponto
RHYTHMS = {
    "natural": {"tail": 0.17, "head": 0.13, "sentence": 0.20},
    "dinamico": {"tail": 0.12, "head": 0.10, "sentence": 0.10},
    "rapido": {"tail": 0.08, "head": 0.07, "sentence": 0.04},
}


class Seams:
    def __init__(self, feat: dict, levels: dict):
        self.db = feat["db"]
        n = len(self.db)
        sp = feat.get("speech")
        self.has_vad = sp is not None and len(sp) == n and bool(np.any(sp))
        self.speech = sp.astype(bool) if self.has_vad else np.zeros(n, dtype=bool)
        floor, voice = levels["floor"], levels["speech"]
        self.voice = voice
        # "silêncio de verdade": bem abaixo da voz (o eco/ruído do ambiente fica aqui)
        self.thr = min(voice - 22.0, floor + 0.45 * (voice - floor))
        quiet = self.db < self.thr
        soft = (self.db < voice - 16.0) & ~self.speech if self.has_vad else np.zeros(n, dtype=bool)
        self.safe = quiet | soft

    def _idx(self, t: float) -> int:
        return int(min(max(round(t / FRAME_S), 0), len(self.db) - 1))

    def find(self, t: float, before: float, after: float, prefer: str = "near", min_depth: float = 20.0) -> float | None:
        """Melhor ponto de emenda perto de t (entre t-before e t+after).
        1º procura uma pausa real; se não houver (fala corrida), o vale mais fundo entre duas palavras.
        prefer="back"/"fwd": mover para trás/frente custa menos (para abrir o trecho sem comer palavra)."""
        a, b = self._idx(t - before), self._idx(t + after)
        if b <= a:
            return None
        idx = np.arange(a, b + 1)
        dt = idx * FRAME_S - t
        w_back = 12.0 if prefer == "back" else (45.0 if prefer == "fwd" else 25.0)
        w_fwd = 12.0 if prefer == "fwd" else (45.0 if prefer == "back" else 25.0)
        move = np.where(dt < 0, -dt * w_back, dt * w_fwd)
        for mask in (self.safe[idx], self.db[idx] < self.voice - min_depth):
            if mask.any():
                cand = np.flatnonzero(mask)
                cost = self.db[idx[cand]] + move[cand]
                return round(float(idx[cand[int(np.argmin(cost))]]) * FRAME_S, 3)
        return None

    def depth(self, t: float) -> float:
        """Quantos dB abaixo da voz está o ponto t (quanto maior, mais limpa a emenda)."""
        i = self._idx(t)
        return float(self.voice - self.db[max(0, i - 1):i + 2].mean())

    def is_speech(self, s: float, e: float) -> bool:
        a, b = self._idx(s), self._idx(e)
        if b <= a:
            return False
        if self.has_vad:
            return bool(self.speech[a:b].mean() > 0.3)
        return bool((self.db[a:b] > self.voice - 12).mean() > 0.3)

    # ---------- limites de um trecho (cortes e resumos) ----------

    def expand_segment(self, s: float, e: float, dur: float) -> tuple[float, float]:
        """Abre o trecho até a pausa real mais próxima: nunca começa nem termina no meio de uma palavra."""
        s2 = self.find(s, 1.2, 0.12, prefer="back")
        e2 = self.find(e, 0.12, 1.5, prefer="fwd")
        s2 = max(0.0, s2 if s2 is not None else s - 0.2)
        e2 = min(dur, e2 if e2 is not None else e + 0.25)
        return s2, max(e2, s2 + 0.1)

    # ---------- validação dos cortes de vícios e manuais ----------

    def snap_cut(self, s: float, e: float, wide: bool = False) -> tuple[float, float] | None:
        """Leva as bordas de um corte para vales de silêncio. None = não dá para cortar sem ficar seco.
        wide=True (cortes de frase da IA ou manuais): janela maior e vale um pouco menos fundo."""
        if wide:
            a = self.find(s, 0.35, 0.30, prefer="back", min_depth=24.0)
            b = self.find(e, 0.30, 0.35, prefer="fwd", min_depth=24.0)
        else:  # vícios/repetições: vale bem fundo; se não houver, a palavra fica (melhor que picotar)
            a = self.find(s, 0.22, 0.10, prefer="back", min_depth=28.0)
            b = self.find(e, 0.10, 0.22, prefer="fwd", min_depth=28.0)
        if a is None or b is None or b - a < 0.06:
            return None
        return a, b


def pause_cut(seams: Seams | None, raw_s: float, raw_e: float, rhythm: str, sentence_end: bool,
              at_start: bool, at_end: bool) -> tuple[float, float] | None:
    """Corte de uma pausa mantendo um respiro natural dos dois lados."""
    r = RHYTHMS.get(rhythm, RHYTHMS["natural"])
    tail = r["tail"] + (r["sentence"] if sentence_end else 0.0)
    head = r["head"]
    a = raw_s if at_start else raw_s + tail
    b = raw_e if at_end else raw_e - head
    if b - a < 0.08:
        return None
    return round(a, 3), round(b, 3)


def remove_islands(keeps: list[list[float]], seams: Seams | None, min_len: float = 0.25) -> list[list[float]]:
    """Tira "pedacinhos" soltos entre dois cortes que não têm voz (soam como estalos)."""
    out = []
    for i, (s, e) in enumerate(keeps):
        inner = 0 < i < len(keeps) - 1
        if inner and e - s < min_len and (seams is None or not seams.is_speech(s, e)):
            continue
        out.append([s, e])
    return out or keeps


def join_kinds(keeps: list[list[float]]) -> list[str]:
    """Tipo de cada emenda (entre o trecho i-1 e i): 'pausa' (tirou só silêncio) ou 'distante' (outra parte do vídeo)."""
    kinds = []
    for i in range(1, len(keeps)):
        gap = keeps[i][0] - keeps[i - 1][1]
        kinds.append("distante" if gap < -0.01 or gap > 2.5 else "pausa")
    return kinds

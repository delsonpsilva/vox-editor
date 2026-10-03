"""Predefinições por rede social: formato, resolução e duração máxima (com divisão automática em partes)."""

PLATFORMS = {
    "whatsapp": {"name": "Status do WhatsApp", "short": "WhatsApp", "w": 1080, "h": 1920, "max": 60, "split": True,
                 "color": "#25D366"},
    "ig_stories": {"name": "Stories do Instagram", "short": "Stories", "w": 1080, "h": 1920, "max": 60, "split": True,
                   "color": "#E1306C"},
    "ig_reels": {"name": "Reels do Instagram", "short": "Reels", "w": 1080, "h": 1920, "max": 180, "split": False,
                 "color": "#C13584"},
    "yt_shorts": {"name": "YouTube Shorts", "short": "Shorts", "w": 1080, "h": 1920, "max": 180, "split": False,
                  "color": "#FF0033"},
    "fb_reels": {"name": "Reels do Facebook", "short": "Facebook", "w": 1080, "h": 1920, "max": 90, "split": False,
                 "color": "#1877F2"},
    "tiktok": {"name": "TikTok", "short": "TikTok", "w": 1080, "h": 1920, "max": 600, "split": False,
               "color": "#25F4EE"},
    "horizontal": {"name": "YouTube / horizontal 16:9", "short": "16:9", "w": 0, "h": 0, "max": 0, "split": False,
                   "color": "#A4A7AF"},
}

DURATIONS = {"30": (20, 35), "60": (45, 65), "90": (70, 95), "120": (100, 130)}


def get(pid: str) -> dict:
    return PLATFORMS.get(pid) or PLATFORMS["ig_reels"]


def is_vertical(pid: str) -> bool:
    return get(pid)["h"] > get(pid)["w"]


def duration_range(studio: dict) -> tuple[float, float]:
    d = str(studio.get("duration", "60"))
    if d == "livre":
        lo = float(studio.get("min") or 20)
        hi = float(studio.get("max") or 90)
        return (min(lo, hi), max(lo, hi))
    return DURATIONS.get(d, (45, 65))

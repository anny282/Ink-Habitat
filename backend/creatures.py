"""Building a new creature on the server: checking the drawing, measuring battle.size, and the random
fields the AI never touches (sound voice, personality, id)."""
import math
import random
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException

# ElevenLabs default voices usable on the free API plan (library voices need a paid plan).
# A mix of deep, gruff, bright and playful; playbackRate adds the squeaky or low cartoon pitch.
VOICE_IDS = [
    "pNInz6obpgDQGcFmaJgB",  # Adam: deep
    "VR6AewLTigWG4xSOukaG",  # Arnold: gruff
    "N2lVS1w4EtoT3dr4eOWO",  # Callum: husky
    "JBFqnCBsd6RMkjVDRZzb",  # George: warm, raspy
    "FGY2WhTYpPnrIDTdsKH5",  # Laura: quirky, upbeat
    "cgSgspJ2msm6clMCkdW9",  # Jessica: playful, bright
    "TX3LPaxmHKxFdv7VOQHJ",  # Liam: young, energetic
    "IKne3meq5aSn9XLyUdCD",  # Charlie: casual, chirpy
]


def validate(creature):
    if not isinstance(creature, dict):
        raise HTTPException(400, "Creature must be a JSON object")
    settings = creature.get("settings")
    name = settings.get("name") if isinstance(settings, dict) else None
    if not isinstance(name, str) or not name.strip():
        raise HTTPException(400, "settings.name is required")
    settings["name"] = name.strip()[:16]
    parts = creature.get("parts")
    if not isinstance(parts, list) or not 1 <= len(parts) <= 8:
        raise HTTPException(400, "parts must contain 1 to 8 entries")
    for part in parts:
        points = part.get("points") if isinstance(part, dict) else None
        if not isinstance(part, dict) or not isinstance(part.get("id"), str) or not isinstance(points, list) \
                or not points or not all(isinstance(pt, list) and len(pt) == 2 and
                                         all(isinstance(v, (int, float)) for v in pt) for pt in points):
            raise HTTPException(400, "each part needs an id and a list of [x, y] points")
    return creature


def canvas_size(battle):
    """How big the creature was drawn: the drawing tool's measure (spec: 100 * sqrt(inkW * inkH) / 500),
    clamped to 5..100. None if it wasn't sent (old creatures, or a stale copy of the drawing page)."""
    size = battle.get("size") if isinstance(battle, dict) else None
    if isinstance(size, bool) or not isinstance(size, (int, float)) or size != size:
        return None
    return round(min(100, max(5, size)))


# battle.size = 5 + 95 * (half how big it was drawn + 30% body bulk + 20% ink weight). Each part is spread
# over the range real doodles cover, so sizes don't bunch up. Unknown canvas size counts as the middle.
SIZE_WEIGHTS = {"canvas": 0.5, "bulk": 0.3, "ink": 0.2}
SIZE_RANGES = {"canvas": (20, 70), "bulk": (0.05, 0.5), "ink": (0.08, 0.25)}


def polygon_area(points):
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1]))) / 2


def size_parts(creature, canvas):
    """The three measures behind battle.size, each 0..1. Bulk and ink are relative to the creature's own
    box, so they work on saved (normalized) drawings too."""
    parts = creature["parts"]
    xs = [x for p in parts for x, _ in p["points"]]
    ys = [y for p in parts for _, y in p["points"]]
    box = max(1, (max(xs) - min(xs)) * (max(ys) - min(ys)))
    body = next((p for p in parts if p.get("role") == "body"), parts[0])
    ink = sum(math.dist(a, b) * (p.get("width") or 6) for p in parts for a, b in zip(p["points"], p["points"][1:]))
    raw = {"canvas": 45 if canvas is None else canvas, "bulk": polygon_area(body["points"]) / box, "ink": ink / box}
    return {k: min(1, max(0, (v - SIZE_RANGES[k][0]) / (SIZE_RANGES[k][1] - SIZE_RANGES[k][0]))) for k, v in raw.items()}


def measure_size(creature, canvas):
    score = size_parts(creature, canvas)
    return round(5 + 95 * sum(SIZE_WEIGHTS[k] * score[k] for k in SIZE_WEIGHTS))


def roll_personality():
    return {
        "restSeconds": random.randint(2, 8),
        "speakEverySeconds": random.randint(20, 60),
        "speedPxPerSec": random.randint(30, 100),
    }


def roll_voice():
    return {
        "voiceId": random.choice(VOICE_IDS),
        "stability": round(random.uniform(0.2, 0.8), 2),
        "style": round(random.uniform(0, 0.6), 2),
        "speed": round(random.uniform(0.8, 1.2), 2),
        "playbackRate": round(random.uniform(0.75, 1.4), 2),
    }


def build_sound(settings):
    text = settings.get("sound")
    text = text.strip()[:19].rstrip() if isinstance(text, str) else ""
    if not text:
        return None
    return {"text": text, "voice": roll_voice(), "audioUrl": None}


def fill_random(creature):
    """Spec data flow step 4: plain-code fields the AI never touches."""
    creature["sound"] = build_sound(creature["settings"])
    creature["personality"] = roll_personality()
    return creature


def assign_id(creature):
    creature["version"] = 3
    creature["id"] = uuid.uuid4().hex[:12]
    creature["createdAt"] = datetime.now(timezone.utc).isoformat()
    return creature

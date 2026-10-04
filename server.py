"""Local Creature World server. Run with: python3 server.py"""
import json
import os
import random
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

import elevenlabs
import gemini

BASE = Path(__file__).resolve().parent
FRONTEND = BASE / "frontend"
DATA = BASE / "data" / "creatures"
AUDIO = BASE / "data" / "audio"
DATA.mkdir(parents=True, exist_ok=True)
AUDIO.mkdir(parents=True, exist_ok=True)
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
app = FastAPI(title="StromHacks Creature World")


def load_env():
    """Read KEY=value lines from .env without overriding real environment variables."""
    env = BASE / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and not line.lstrip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip('"\''))


load_env()

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


def path_for(creature_id: str) -> Path:
    if not ID_RE.fullmatch(creature_id):
        raise HTTPException(400, "Invalid creature id")
    return DATA / f"{creature_id}.json"


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
    creature["id"] = uuid.uuid4().hex[:12]
    creature["createdAt"] = datetime.now(timezone.utc).isoformat()
    return creature


def write(creature):
    path_for(creature["id"]).write_text(json.dumps(creature, indent=2), encoding="utf-8")
    return creature


@app.get("/api/creatures")
def list_creatures():
    creatures = []
    for path in DATA.glob("*.json"):
        try:
            creatures.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(creatures, key=lambda c: c.get("createdAt", ""))


@app.post("/api/creatures")
def create_creature(creature: dict = Body(...)):
    creature = assign_id(fill_random(gemini.enrich(validate(creature))))
    return write(elevenlabs.generate(creature, AUDIO, VOICE_IDS))


@app.delete("/api/creatures/{creature_id}")
def delete_creature(creature_id: str):
    path = path_for(creature_id)
    if not path.exists():
        raise HTTPException(404, "Creature not found")
    path.unlink()
    (AUDIO / f"{creature_id}.mp3").unlink(missing_ok=True)
    return {"deleted": creature_id}


def seed():
    example = BASE / "example_creature.json"
    if example.exists() and not any(DATA.glob("*.json")):
        write(assign_id(json.loads(example.read_text(encoding="utf-8"))))


seed()


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/world.html")


app.mount("/audio", StaticFiles(directory=AUDIO), name="audio")
app.mount("/", StaticFiles(directory=FRONTEND), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)

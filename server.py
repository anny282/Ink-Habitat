"""Local Creature World server. Run with: python3 server.py"""
import json
import os
import random
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Body, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

import auth
import db
import elevenlabs
import gemini

from rig import rig_parts

BASE = Path(__file__).resolve().parent
FRONTEND = BASE / "frontend"
AUDIO = BASE / "data" / "audio"
AUDIO.mkdir(parents=True, exist_ok=True)
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
PAGES_NEEDING_LOGIN = {"/", "/world.html", "/draw-creature.html"}
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
    creature["version"] = 3
    creature["id"] = uuid.uuid4().hex[:12]
    creature["createdAt"] = datetime.now(timezone.utc).isoformat()
    return creature


# ---------- startup ----------

@app.on_event("startup")
def startup():
    if not db.configured():
        raise RuntimeError("TiDB is not configured: set TIDB_HOST, TIDB_USER and TIDB_PASSWORD in .env")
    db.init_schema()


# ---------- accounts ----------

def current_user(request: Request):
    user_id = auth.read_token(request.cookies.get(auth.COOKIE))
    user = db.user_by_id(user_id) if user_id else None
    if not user:
        raise HTTPException(401, "Log in first")
    return user


def give_starter_creature(user):
    example = BASE / "example_creature.json"
    if example.exists():
        creature = assign_id(json.loads(example.read_text(encoding="utf-8")))
        db.save_creature(user["id"], db.with_defaults(creature))


@app.post("/api/signup")
def signup(response: Response, body: dict = Body(...)):
    username, password = body.get("username"), body.get("password")
    problem = auth.username_problem(username) or auth.password_problem(password)
    if problem:
        raise HTTPException(400, problem)
    user = db.create_user(username, auth.hash_password(password))
    if not user:
        raise HTTPException(409, "That username is taken.")
    give_starter_creature(user)
    auth.set_cookie(response, user["id"])
    return user


@app.post("/api/login")
def login(response: Response, body: dict = Body(...)):
    username, password = body.get("username"), body.get("password")
    row = db.user_by_name(username) if isinstance(username, str) else None
    if not row or not isinstance(password, str) or not auth.check_password(password, row["password_hash"]):
        raise HTTPException(401, "Wrong username or password.")
    auth.set_cookie(response, row["id"])
    return db.public_user(row)


@app.post("/api/logout")
def logout(response: Response):
    auth.clear_cookie(response)
    return {"ok": True}


@app.get("/api/me")
def me(user=Depends(current_user)):
    return db.public_user(user)


# ---------- creatures (each account sees only its own farm) ----------

@app.get("/api/creatures")
def list_creatures(user=Depends(current_user)):
    return db.get_creatures(user["id"])


@app.post("/api/creatures")
def create_creature(creature: dict = Body(...), user=Depends(current_user)):
    creature = validate(creature)
    rig_parts(creature["parts"])           # parent, pivot, z (Gemini's part summary uses the rig)
    gemini.enrich(creature)                # role, moves, locomotion, idles
    rig_parts(creature["parts"])           # redo z now that roles are known
    creature = assign_id(fill_random(creature))
    creature["drawnBy"] = {"userId": user["id"], "name": user["username"]}
    creature = db.with_defaults(creature)  # battle stats; real size and baseAttack come in phase 3
    return db.save_creature(user["id"], elevenlabs.generate(creature, AUDIO, VOICE_IDS))


@app.delete("/api/creatures/{creature_id}")
def delete_creature(creature_id: str, user=Depends(current_user)):
    if not ID_RE.fullmatch(creature_id):
        raise HTTPException(400, "Invalid creature id")
    if not db.delete_creature(user["id"], creature_id):
        raise HTTPException(404, "Creature not found")
    (AUDIO / f"{creature_id}.mp3").unlink(missing_ok=True)
    return {"deleted": creature_id}


@app.middleware("http")
async def login_redirect(request: Request, call_next):
    """Send logged-out visitors of the farm pages to the login page."""
    if request.url.path in PAGES_NEEDING_LOGIN and not auth.read_token(request.cookies.get(auth.COOKIE)):
        return RedirectResponse("/login.html")
    return await call_next(request)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/world.html")


app.mount("/audio", StaticFiles(directory=AUDIO), name="audio")
app.mount("/", StaticFiles(directory=FRONTEND), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)

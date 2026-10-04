"""Local Creature World server. Run with: python3 server.py"""
import json
import math
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
import battle
import db
import elevenlabs
import gemini

from rig import rig_parts

BASE = Path(__file__).resolve().parent
FRONTEND = BASE / "frontend"
AUDIO = BASE / "data" / "audio"
AUDIO.mkdir(parents=True, exist_ok=True)
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
PAGES_NEEDING_LOGIN = {"/", "/world.html", "/draw-creature.html", "/friends.html", "/battle.html"}
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
    canvas = canvas_size(creature.get("battle"))
    creature["battle"] = {"size": measure_size(creature, canvas), "canvasSize": canvas,
                          "wins": 0}  # wins: only the server counts them
    rig_parts(creature["parts"])           # parent, pivot, z (Gemini's part summary uses the rig)
    gemini.enrich(creature)                # role, moves, locomotion, idles, battle.baseAttack
    rig_parts(creature["parts"])           # redo z now that roles are known
    creature = assign_id(fill_random(creature))
    creature["drawnBy"] = {"userId": user["id"], "name": user["username"]}
    return db.save_creature(user["id"], elevenlabs.generate(creature, AUDIO, VOICE_IDS))


@app.delete("/api/creatures/{creature_id}")
def delete_creature(creature_id: str, user=Depends(current_user)):
    if not ID_RE.fullmatch(creature_id):
        raise HTTPException(400, "Invalid creature id")
    if not db.delete_creature(user["id"], creature_id):
        raise HTTPException(404, "Creature not found")
    (AUDIO / f"{creature_id}.mp3").unlink(missing_ok=True)
    return {"deleted": creature_id}


# ---------- friends (add by friend code; friendship is mutual) ----------

@app.get("/api/friends")
def list_friends(user=Depends(current_user)):
    return db.friends_of(user["id"])


@app.post("/api/friends")
def add_friend(body: dict = Body(...), user=Depends(current_user)):
    code = body.get("code")
    code = re.sub(r"[\s-]", "", code).upper() if isinstance(code, str) else ""
    if len(code) != 8:
        raise HTTPException(400, "A friend code is 8 letters and numbers.")
    friend, problem = db.add_friend(user["id"], code)
    if problem:
        raise HTTPException(400, problem)
    return friend


@app.delete("/api/friends/{friend_id}")
def remove_friend(friend_id: str, user=Depends(current_user)):
    if not ID_RE.fullmatch(friend_id):
        raise HTTPException(400, "Invalid friend id")
    if not db.remove_friend(user["id"], friend_id):
        raise HTTPException(404, "Friend not found")
    return {"removed": friend_id}


# ---------- practice battle (one laptop: your creatures against your creatures) ----------

@app.post("/api/practice-battle")
def practice_battle(body: dict = Body(default=None), user=Depends(current_user)):
    """Your team (3 creature ids from your farm, in fight order, or random if none are given) against
    3 random creatures from your farm. Runs the real engine. Nothing is saved."""
    farm = db.get_creatures(user["id"])
    if len(farm) < battle.TEAM_SIZE:
        raise HTTPException(400, f"You need at least {battle.TEAM_SIZE} creatures to battle. Draw a few more!")
    picks = (body or {}).get("team")
    if picks is None:
        team_a = random.sample(farm, battle.TEAM_SIZE)
    else:
        by_id = {c["id"]: c for c in farm}
        if not isinstance(picks, list) or len(picks) != battle.TEAM_SIZE or len(set(map(str, picks))) != battle.TEAM_SIZE:
            raise HTTPException(400, f"Pick exactly {battle.TEAM_SIZE} different creatures.")
        if not all(isinstance(i, str) and i in by_id for i in picks):
            raise HTTPException(400, "You can only pick creatures from your own farm.")
        team_a = [by_id[i] for i in picks]
    team_b = random.sample(farm, battle.TEAM_SIZE)
    log = battle.run_battle(team_a, team_b, random.randrange(2**31))
    log.update(battleId="practice", startAt=datetime.now(timezone.utc).isoformat(), prize=None)
    log["sides"]["a"].update(userId=user["id"], name=user["username"])
    log["sides"]["b"].update(userId=None, name="Practice")
    return {"log": log, "creatures": {c["id"]: c for c in team_a + team_b}}


@app.middleware("http")
async def login_redirect(request: Request, call_next):
    """Send logged-out visitors of the farm pages to the login page."""
    if request.url.path in PAGES_NEEDING_LOGIN and not auth.read_token(request.cookies.get(auth.COOKIE)):
        return RedirectResponse("/login.html")
    response = await call_next(request)
    if not request.url.path.startswith(("/api/", "/audio/")):
        # browsers re-check pages every load; an old cached drawing page once saved creatures without size
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/world.html")


app.mount("/audio", StaticFiles(directory=AUDIO), name="audio")
app.mount("/", StaticFiles(directory=FRONTEND), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)

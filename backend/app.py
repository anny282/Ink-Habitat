"""The web app: accounts, creatures, friends and practice battle API, voice clips, and the pages in
frontend/. Live battles (rooms.py) share the port. Start it with: python server.py"""
import json
import random
import re
from datetime import datetime, timezone

from fastapi import Body, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
import socketio

from . import ROOT, auth, battle, db, elevenlabs, gemini, rooms
from .creatures import VOICE_IDS, assign_id, canvas_size, fill_random, measure_size, validate
from .rig import rig_parts

FRONTEND = ROOT / "frontend"
AUDIO = ROOT / "data" / "audio"   # where clips were saved before they moved into TiDB (scripts/upload_audio.py)
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SCENES = {"grasslands", "desert", "ocean"}
PAGES_NEEDING_LOGIN = {"/", "/world.html", "/draw-creature.html", "/friends.html", "/battle.html"}
app = FastAPI(title="StromHacks Creature World")


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
    example = ROOT / "assets" / "example_creature.json"
    if example.exists():
        creature = assign_id(json.loads(example.read_text(encoding="utf-8")))
        creature["scene"] = "grasslands"
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
    creature["scene"] = "grasslands"
    canvas = canvas_size(creature.get("battle"))
    creature["battle"] = {"size": measure_size(creature, canvas), "canvasSize": canvas,
                          "wins": 0}  # wins: only the server counts them
    rig_parts(creature["parts"])           # parent, pivot, z (Gemini's part summary uses the rig)
    gemini.enrich(creature)                # role, moves, locomotion, idles, battle.baseAttack
    rig_parts(creature["parts"])           # redo z now that roles are known
    creature = assign_id(fill_random(creature))
    creature["drawnBy"] = {"userId": user["id"], "name": user["username"]}
    creature, audio = elevenlabs.generate(creature, VOICE_IDS)
    return db.save_creature(user["id"], creature, audio)


@app.patch("/api/creatures/{creature_id}/scene")
def move_creature(creature_id: str, payload: dict = Body(...), user=Depends(current_user)):
    """Place a creature in one scene, or remove it from the world with null."""
    if not ID_RE.fullmatch(creature_id):
        raise HTTPException(400, "Invalid creature id")
    scene = payload.get("scene")
    if scene is not None and (not isinstance(scene, str) or scene not in SCENES):
        raise HTTPException(400, "scene must be grasslands, desert, ocean, or null")
    creature = db.set_creature_scene(user["id"], creature_id, scene)
    if not creature:
        raise HTTPException(404, "Creature not found")
    return creature


@app.delete("/api/creatures/{creature_id}")
def delete_creature(creature_id: str, user=Depends(current_user)):
    if not ID_RE.fullmatch(creature_id):
        raise HTTPException(400, "Invalid creature id")
    if rooms.creature_busy(creature_id):
        raise HTTPException(409, "This creature is in a battle right now.")
    if not db.delete_creature(user["id"], creature_id):
        raise HTTPException(404, "Creature not found")
    (AUDIO / f"{creature_id}.mp3").unlink(missing_ok=True)
    return {"deleted": creature_id}


# ---------- friends (add by friend code; friendship is mutual) ----------

@app.get("/api/friends")
def list_friends(user=Depends(current_user)):
    return [{**f, "state": rooms.presence_state(f["id"]), "busy": rooms.is_busy(f["id"])} for f in db.friends_of(user["id"])]


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


@app.get("/api/friends/{friend_id}/farm")
def view_friend_farm(friend_id: str, user=Depends(current_user)):
    """Return only scene-placed, viewable creature fields for an existing friend (sound too, so a click plays it)."""
    if not ID_RE.fullmatch(friend_id) or not db.are_friends(user["id"], friend_id):
        raise HTTPException(404, "Friend not found")
    friend = db.user_by_id(friend_id)
    if not friend:
        raise HTTPException(404, "Friend not found")
    visible = []
    for creature in db.get_creatures(friend_id):
        scene = creature.get("scene", "grasslands")  # older starter creatures predate scene assignments
        if scene not in SCENES:
            continue
        shared = {key: creature[key] for key in ("id", "bounds", "parts", "locomotion", "idles", "personality", "sound") if key in creature}
        shared["scene"] = scene
        visible.append(shared)
        visible[-1]["settings"] = {"name": (creature.get("settings") or {}).get("name", "Creature")}
        visible[-1]["battle"] = {"sleepUntil": creature["battle"].get("sleepUntil")}   # so naps show on visits too
    return {"username": friend["username"], "creatures": visible}


# ---------- practice battle (one laptop: your creatures against your creatures) ----------

@app.get("/api/practice-hand")
def practice_hand(user=Depends(current_user)):
    """3 buff cards for a practice battle (2 buffs, 1 debuff, shuffled); the page shows them face-down."""
    return [battle.card_info(c) for c in battle.deal(random)]


@app.post("/api/practice-battle")
def practice_battle(body: dict = Body(default=None), user=Depends(current_user)):
    """Your team (3 awake creature ids from your farm, in fight order, or random if none are given) and buff card
    (from /api/practice-hand) against 3 random creatures from your farm with a random card from their own hand.
    Runs the real engine. Nothing is saved."""
    farm = db.get_creatures(user["id"])
    problem = rooms.team_problem(farm)
    if problem:
        raise HTTPException(400, problem if len(farm) >= battle.TEAM_SIZE else problem + " Draw a few more!")
    picks = (body or {}).get("team")
    if picks is None:
        team_a = random.sample(rooms.awake(farm), battle.TEAM_SIZE)
    else:
        by_id = {c["id"]: c for c in farm}
        if not isinstance(picks, list) or len(picks) != battle.TEAM_SIZE or len(set(map(str, picks))) != battle.TEAM_SIZE:
            raise HTTPException(400, f"Pick exactly {battle.TEAM_SIZE} different creatures.")
        if not all(isinstance(i, str) and i in by_id for i in picks):
            raise HTTPException(400, "You can only pick creatures from your own farm.")
        team_a = [by_id[i] for i in picks]
        sleepy = next((c for c in team_a if rooms.sleep_left(c)), None)
        if sleepy:
            raise HTTPException(400, f"{(sleepy.get('settings') or {}).get('name') or 'That creature'} is sleeping after a battle. "
                                     f"It wakes up in {rooms.sleep_left(sleepy)}s.")
    buff = (body or {}).get("buff")
    if buff is not None and (not isinstance(buff, str) or buff not in battle.BUFFS):
        raise HTTPException(400, "That's not a buff card.")
    team_b = random.sample(farm, battle.TEAM_SIZE)
    buffs = {"a": buff, "b": random.choice(battle.deal(random))}
    log = battle.run_battle(team_a, team_b, random.randrange(2**31), buffs)
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


@app.get("/audio/{filename}", include_in_schema=False)
def audio(filename: str):
    """A creature's voice clip from TiDB, so any server can play clips made on another one. A clip made
    before that and not uploaded yet (scripts/upload_audio.py) is still played from this laptop's data/audio."""
    creature_id = filename.removesuffix(".mp3")
    if not filename.endswith(".mp3") or not ID_RE.fullmatch(creature_id):
        raise HTTPException(404)
    mp3 = db.get_audio(creature_id)
    if mp3 is None and (AUDIO / filename).is_file():
        mp3 = (AUDIO / filename).read_bytes()
    if mp3 is None:
        raise HTTPException(404)
    return Response(mp3, media_type="audio/mpeg", headers={"Cache-Control": "public, max-age=86400"})


app.mount("/", StaticFiles(directory=FRONTEND), name="frontend")

# Live battles (rooms.py) share the port: Socket.IO answers /socket.io/, everything else goes to the app.
asgi = socketio.ASGIApp(rooms.sio, other_asgi_app=app)

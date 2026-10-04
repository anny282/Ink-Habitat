"""Live battles with friends over Socket.IO (plan phase 6).

One room per battle and one active battle per account. Battle state lives in memory in this server
process (run a single worker); finished battles are written to TiDB in one transaction.

    invite -> accept -> both pick 3 in secret and lock in -> each flips 1 of 3 face-down buff cards dealt
    by the server (the pick timer picks anything missing) -> the server runs the engine once -> both replay the same log from the same start time
    -> the winner picks a prize from the loser's team (30 s, then the server picks at random)
    -> one transaction moves the prize, adds a win to each winning creature, and saves the battle

After every change each player gets one "battle" event with their whole view of the battle, so a
reload or a reconnect simply shows the current state. A player who drops has GRACE_SECONDS to come
back; after that an invite or pick is cancelled, and a battle in progress is a forfeit.
"""
import asyncio
import random
import secrets
import time
from datetime import datetime, timezone
from http.cookies import CookieError, SimpleCookie

import socketio

import auth
import battle
import db

INVITE_SECONDS = 60
PICK_SECONDS = 60
CARD_SECONDS = 15            # locking in late still leaves at least this long to pick a card
COUNTDOWN_SECONDS = 4        # between both locking in and the replay starting
PRIZE_SECONDS = 30
GRACE_SECONDS = 10           # a player who drops (closed tab, reload) has this long to come back
KEEP_FINISHED_SECONDS = 600  # how long a finished battle can still be looked at

sio = socketio.AsyncServer(async_mode="asgi")
sockets = {}   # sid -> {"id", "name"}
online = {}    # user id -> set of sids
battles = {}   # battle id -> battle (see new_battle)
active = {}    # user id -> battle id, until that battle is finished or cancelled
_lock = None


def state_lock():
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()   # made lazily so it belongs to the server's event loop
    return _lock


def now():
    return time.time()


def ms(t):
    return None if t is None else round(t * 1000)


def other(side):
    return "b" if side == "a" else "a"


def is_online(user_id):
    return bool(online.get(user_id))


def is_busy(user_id):
    return user_id in active


def creature_busy(creature_id):
    """True while the creature is on a locked-in team of a battle that isn't finished."""
    return any(c["id"] == creature_id
               for b in battles.values() if b["stage"] in ("picking", "playing", "prize")
               for team in b["picks"].values() if team for c in team)


# ---------- battle state ----------

def new_battle(inviter, friend):
    return {
        "id": secrets.token_hex(8), "stage": "invited", "deadline": now() + INVITE_SECONDS,
        "sides": {"a": inviter, "b": friend}, "picks": {"a": None, "b": None},
        "hands": None, "cards": {"a": None, "b": None},   # each side's 3 buff ids, and the index they flipped
        "log": None, "start": None, "creatures": None, "reason": None, "error": None,
        "timer": None, "away": {},
    }


def ready(b, side):
    return b["picks"][side] is not None and b["cards"][side] is not None


def side_of(b, user_id):
    return next((s for s in "ab" if b["sides"][s]["id"] == user_id), None)


def view(b, side):
    """Everything one player may see. The opponent's picks and card, and your own cards until you flip one,
    stay hidden until the battle starts."""
    them = other(side)
    v = {"battleId": b["id"], "stage": b["stage"], "you": side, "me": b["sides"][side],
         "opponent": b["sides"][them], "serverNow": ms(now()), "deadline": ms(b["deadline"])}
    if b["stage"] == "invited":
        v["inviter"] = side == "a"
    if b["stage"] == "picking":
        v["locked"] = {"you": b["picks"][side] is not None, "opponent": ready(b, them)}
        v["myTeam"] = [c["id"] for c in b["picks"][side]] if b["picks"][side] else None
        flipped = b["cards"][side]
        v["cards"] = {"picked": flipped,
                      "hand": None if flipped is None else [battle.card_info(c) for c in b["hands"][side]]}
    if b["log"]:
        v.update(log=b["log"], creatures=b["creatures"], startAt=ms(b["start"]))
        if b["stage"] == "prize":
            v["choose"] = b["log"]["result"]["winner"] == side
    if b["stage"] == "cancelled":
        v["reason"] = b["reason"]
    if b["error"]:
        v["error"] = b["error"]
    return v


async def push(b):
    for side in "ab":
        await sio.emit("battle", view(b, side), room=f"user:{b['sides'][side]['id']}")


def set_timer(b, seconds, step):
    """Run step(b) after `seconds`, replacing any earlier timer of this battle."""
    if b["timer"]:
        b["timer"].cancel()
    b["timer"] = asyncio.create_task(_after(b, seconds, step))


async def _after(b, seconds, step):
    await asyncio.sleep(max(0, seconds))
    async with state_lock():
        if b["timer"] is not asyncio.current_task():
            return
        b["timer"] = None   # so set_timer inside step doesn't cancel the task that's running it
        await step(b)


def stop_timers(b):
    for task in [b["timer"], *b["away"].values()]:
        if task and task is not asyncio.current_task():
            task.cancel()
    b["timer"] = None
    b["away"] = {}


def release(b):
    for side in "ab":
        if active.get(b["sides"][side]["id"]) == b["id"]:
            del active[b["sides"][side]["id"]]


async def forget(b):
    battles.pop(b["id"], None)


async def cancel(b, reason):
    stop_timers(b)
    b.update(stage="cancelled", reason=reason, deadline=None)
    release(b)
    await push(b)
    set_timer(b, KEEP_FINISHED_SECONDS, forget)


# ---------- the steps ----------

async def invite_expired(b):
    await cancel(b, f"{b['sides']['b']['name']} didn't answer in time.")


async def picks_due(b):
    """Pick time is up: anyone who hasn't locked in gets 3 random creatures from their farm and a random card."""
    for side in "ab":
        if b["cards"][side] is None:
            b["cards"][side] = random.randrange(len(b["hands"][side]))
        if b["picks"][side] is None:
            farm = await asyncio.to_thread(db.get_creatures, b["sides"][side]["id"])
            if len(farm) < battle.TEAM_SIZE:
                return await cancel(b, f"{b['sides'][side]['name']} doesn't have {battle.TEAM_SIZE} creatures anymore.")
            b["picks"][side] = random.sample(farm, battle.TEAM_SIZE)
    await start_fight(b)


async def start_fight(b):
    buffs = {s: b["hands"][s][b["cards"][s]] for s in "ab"}
    log = battle.run_battle(b["picks"]["a"], b["picks"]["b"], random.randrange(2 ** 31), buffs)
    b["start"] = now() + COUNTDOWN_SECONDS
    log.update(battleId=b["id"], startAt=datetime.fromtimestamp(b["start"], timezone.utc).isoformat(), prize=None)
    for side in "ab":
        log["sides"][side].update(userId=b["sides"][side]["id"], name=b["sides"][side]["name"])
    b.update(stage="playing", deadline=None, log=log,
             creatures={c["id"]: c for side in "ab" for c in b["picks"][side]})
    set_timer(b, COUNTDOWN_SECONDS + log["duration"], replay_over)
    await push(b)


async def replay_over(b):
    if b["log"]["result"]["winner"] == "draw":
        return await finish(b, None, None)
    b.update(stage="prize", deadline=now() + PRIZE_SECONDS)
    set_timer(b, PRIZE_SECONDS, prize_due)
    await push(b)


async def prize_due(b):
    loser = other(b["log"]["result"]["winner"])
    await finish(b, random.choice(b["picks"][loser])["id"], "auto")


async def finish(b, prize_id, picked_by):
    log, winner = b["log"], b["log"]["result"]["winner"]
    users = {s: b["sides"][s]["id"] for s in "ab"}
    win_user = users.get(winner)
    lose_user = users[other(winner)] if win_user else None
    winning_ids = [c["id"] for c in b["picks"][winner]] if win_user else []
    try:
        prize = await asyncio.to_thread(db.finish_battle, log, users["a"], users["b"], win_user, lose_user,
                                        winning_ids, prize_id, picked_by)
    except Exception as e:  # the battle still ends; nobody gains or loses a creature
        print(f"[rooms] couldn't save battle {b['id']}: {e}")
        prize, b["error"] = None, "The result couldn't be saved, so no creature changed hands."
    stop_timers(b)
    b.update(stage="done", deadline=None, log={**log, "prize": prize})
    release(b)
    await push(b)
    set_timer(b, KEEP_FINISHED_SECONDS, forget)


async def player_left(b, side):
    """Called when a player leaves on purpose or doesn't come back within GRACE_SECONDS."""
    name = b["sides"][side]["name"]
    if b["stage"] == "invited":
        await cancel(b, f"{name} cancelled the invite." if side == "a" else f"{name} said no.")
    elif b["stage"] == "picking":
        await cancel(b, f"{name} left before the battle started.")
    elif b["stage"] == "playing":
        elapsed = now() - b["start"]
        if elapsed >= b["log"]["duration"] or not is_online(b["sides"][other(side)]["id"]):
            return  # it's over anyway, or both are gone: the full log stands
        b["log"] = battle.forfeit(b["log"], elapsed, side)
        set_timer(b, 0, replay_over)
        await push(b)


# ---------- connections ----------

def user_from_cookie(environ):
    try:
        morsel = SimpleCookie(environ.get("HTTP_COOKIE", "")).get(auth.COOKIE)
    except CookieError:
        return None
    return auth.read_token(morsel.value) if morsel else None


async def tell_friends(user_id, is_on):
    for friend in await asyncio.to_thread(db.friends_of, user_id):
        await sio.emit("presence", {"userId": user_id, "online": is_on}, room=f"user:{friend['id']}")


@sio.event
async def connect(sid, environ, auth_data=None):
    user_id = user_from_cookie(environ)
    row = await asyncio.to_thread(db.user_by_id, user_id) if user_id else None
    if not row:
        raise socketio.exceptions.ConnectionRefusedError("Log in first")
    async with state_lock():
        sockets[sid] = {"id": row["id"], "name": row["username"]}
        first = not online.get(row["id"])
        online.setdefault(row["id"], set()).add(sid)
        await sio.enter_room(sid, f"user:{row['id']}")
        b = battles.get(active.get(row["id"]))
        if b:
            side = side_of(b, row["id"])
            task = b["away"].pop(side, None)
            if task:
                task.cancel()
            await sio.emit("battle", view(b, side), to=sid)
    if first:
        asyncio.create_task(tell_friends(row["id"], True))   # don't hold up the connection on DB calls


@sio.event
async def disconnect(sid, reason=None):
    async with state_lock():
        user = sockets.pop(sid, None)
        if not user:
            return
        sids = online.get(user["id"], set())
        sids.discard(sid)
        if sids:
            return
        online.pop(user["id"], None)
        b = battles.get(active.get(user["id"]))
        if b:
            side = side_of(b, user["id"])
            b["away"][side] = asyncio.create_task(_gone(b, side, user["id"]))
    asyncio.create_task(tell_friends(user["id"], False))


async def _gone(b, side, user_id):
    await asyncio.sleep(GRACE_SECONDS)
    async with state_lock():
        if b["away"].get(side) is asyncio.current_task():
            del b["away"][side]
            if not is_online(user_id) and active.get(user_id) == b["id"]:
                await player_left(b, side)


# ---------- what the client can ask for (each returns {"ok": ...} or {"error": ...}) ----------

def mine(sid, data):
    """The caller and their battle (by battleId), or (user, None, None)."""
    user = sockets.get(sid)
    b = battles.get((data or {}).get("battleId")) if user else None
    side = side_of(b, user["id"]) if b else None
    return user, (b if side else None), side


@sio.event
async def invite(sid, data):
    user = sockets.get(sid)
    friend_id = (data or {}).get("friendId")
    if not user or not isinstance(friend_id, str):
        return {"error": "Who do you want to battle?"}
    # four lookups at once: each opens its own TiDB connection, so one after another is slow
    friend, friends, mine_n, theirs_n = await asyncio.gather(
        asyncio.to_thread(db.user_by_id, friend_id), asyncio.to_thread(db.are_friends, user["id"], friend_id),
        asyncio.to_thread(db.count_creatures, user["id"]), asyncio.to_thread(db.count_creatures, friend_id))
    if not friend or not friends:
        return {"error": "You can only battle your friends."}
    for n, name in ((mine_n, "You need"), (theirs_n, f"{friend['username']} needs")):
        if n < battle.TEAM_SIZE:
            return {"error": f"{name} at least {battle.TEAM_SIZE} creatures to battle."}
    async with state_lock():
        if is_busy(user["id"]):
            return {"error": "You're already in a battle."}
        if not is_online(friend_id):
            return {"error": f"{friend['username']} isn't online."}
        if is_busy(friend_id):
            return {"error": f"{friend['username']} is in another battle."}
        b = new_battle(user, {"id": friend_id, "name": friend["username"]})
        battles[b["id"]] = b
        active[user["id"]] = active[friend_id] = b["id"]
        set_timer(b, INVITE_SECONDS, invite_expired)
        await push(b)
    return {"ok": True, "battleId": b["id"]}


@sio.event
async def answer(sid, data):
    async with state_lock():
        user, b, side = mine(sid, data)
        if not b or b["stage"] != "invited" or side != "b":
            return {"error": "This invite isn't open anymore."}
        if not (data or {}).get("accept"):
            await player_left(b, "b")
            return {"ok": True}
        b.update(stage="picking", deadline=now() + PICK_SECONDS, hands={s: battle.deal(random) for s in "ab"})
        set_timer(b, PICK_SECONDS, picks_due)
        await push(b)
    return {"ok": True, "battleId": b["id"]}


@sio.event
async def lock(sid, data):
    user = sockets.get(sid)
    if not user:
        return {"error": "Log in first"}
    farm = {c["id"]: c for c in await asyncio.to_thread(db.get_creatures, user["id"])}
    async with state_lock():
        user, b, side = mine(sid, data)
        if not b or b["stage"] != "picking":
            return {"error": "Picking is over."}
        if b["picks"][side] is not None:
            return {"error": "You're already locked in."}
        team = (data or {}).get("team")
        if not isinstance(team, list) or len(team) != battle.TEAM_SIZE or len(set(map(str, team))) != battle.TEAM_SIZE:
            return {"error": f"Pick exactly {battle.TEAM_SIZE} different creatures."}
        if not all(isinstance(i, str) and i in farm for i in team):
            return {"error": "You can only pick creatures from your own farm."}
        b["picks"][side] = [farm[i] for i in team]
        if b["deadline"] - now() < CARD_SECONDS:   # locked in at the last second: still time to pick a card
            b["deadline"] = now() + CARD_SECONDS
            set_timer(b, CARD_SECONDS, picks_due)
        await push(b)
    return {"ok": True}


@sio.event
async def card(sid, data):
    """Flip one of your 3 face-down buff cards (after locking in your team)."""
    async with state_lock():
        user, b, side = mine(sid, data)
        if not b or b["stage"] != "picking":
            return {"error": "Picking is over."}
        if b["picks"][side] is None:
            return {"error": "Lock in your team first."}
        if b["cards"][side] is not None:
            return {"error": "You already picked a card."}
        index = (data or {}).get("index")
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(b["hands"][side]):
            return {"error": "Pick one of the 3 cards."}
        b["cards"][side] = index
        hand = [battle.card_info(c) for c in b["hands"][side]]   # the page flips all 3 over
        if ready(b, other(side)):
            await start_fight(b)
        else:
            await push(b)
    return {"ok": True, "hand": hand}


@sio.event
async def prize(sid, data):
    async with state_lock():
        user, b, side = mine(sid, data)
        if not b or b["stage"] != "prize" or b["log"]["result"]["winner"] != side:
            return {"error": "There's no prize for you to pick."}
        choice = (data or {}).get("creature")
        if choice not in [c["id"] for c in b["picks"][other(side)]]:
            return {"error": "Pick one of the creatures you beat."}
        await finish(b, choice, "winner")
    return {"ok": True}


@sio.event
async def leave(sid, data):
    async with state_lock():
        user, b, side = mine(sid, data)
        if b and active.get(user["id"]) == b["id"]:
            await player_left(b, side)
    return {"ok": True}


@sio.event
async def get(sid, data):
    """The caller's view of a battle (also finished or cancelled ones, for a while)."""
    async with state_lock():
        user, b, side = mine(sid, data)
        return view(b, side) if b else {"error": "This battle is over."}

"""TiDB storage: users, creatures, friendships, battles.

TiDB speaks the MySQL protocol, so this uses PyMySQL. Connection details come from .env
(TIDB_HOST, TIDB_PORT, TIDB_USER, TIDB_PASSWORD, TIDB_DATABASE). TiDB Cloud requires TLS.
"""
import json
import os
import secrets
from contextlib import contextmanager
from datetime import datetime, timezone

import certifi
import pymysql
from pymysql.cursors import DictCursor

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users (
        id            VARCHAR(32)  PRIMARY KEY,
        username      VARCHAR(20)  NOT NULL UNIQUE,
        password_hash VARCHAR(255) NOT NULL,
        friend_code   CHAR(8)      NOT NULL UNIQUE,
        created_at    DATETIME(6)  NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS creatures (
        id         VARCHAR(64) PRIMARY KEY,
        owner_id   VARCHAR(32) NOT NULL,
        drawn_by   VARCHAR(32) NULL,
        data       JSON        NOT NULL,
        created_at DATETIME(6) NOT NULL,
        INDEX idx_owner (owner_id, created_at)
    )""",
    """CREATE TABLE IF NOT EXISTS friendships (
        user_id    VARCHAR(32) NOT NULL,
        friend_id  VARCHAR(32) NOT NULL,
        created_at DATETIME(6) NOT NULL,
        PRIMARY KEY (user_id, friend_id)
    )""",
    """CREATE TABLE IF NOT EXISTS battles (
        id         VARCHAR(32) PRIMARY KEY,
        a_user     VARCHAR(32) NOT NULL,
        b_user     VARCHAR(32) NOT NULL,
        winner     VARCHAR(8)  NULL,
        log        JSON        NOT NULL,
        created_at DATETIME(6) NOT NULL,
        INDEX idx_a (a_user, created_at),
        INDEX idx_b (b_user, created_at)
    )""",
]
FRIEND_CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I mix-ups


def configured():
    return all(os.environ.get(k) for k in ("TIDB_HOST", "TIDB_USER", "TIDB_PASSWORD"))


def connect():
    return pymysql.connect(
        host=os.environ["TIDB_HOST"],
        port=int(os.environ.get("TIDB_PORT", "4000")),
        user=os.environ["TIDB_USER"],
        password=os.environ["TIDB_PASSWORD"],
        database=os.environ.get("TIDB_DATABASE", "creature_farm"),
        ssl={"ca": certifi.where()},
        cursorclass=DictCursor,
        autocommit=False,
        connect_timeout=10,
    )


@contextmanager
def transaction():
    """One connection, committed on success, rolled back on any error."""
    conn = connect()
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_schema():
    """Create the database (if the user may) and the four tables. Safe to run every start."""
    name = os.environ.get("TIDB_DATABASE", "creature_farm")
    conn = pymysql.connect(
        host=os.environ["TIDB_HOST"], port=int(os.environ.get("TIDB_PORT", "4000")),
        user=os.environ["TIDB_USER"], password=os.environ["TIDB_PASSWORD"],
        ssl={"ca": certifi.where()}, connect_timeout=10, autocommit=True,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{name}`")
            cur.execute(f"USE `{name}`")
            for statement in SCHEMA:
                cur.execute(statement)
    finally:
        conn.close()


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------- users ----------

def public_user(row):
    return {"id": row["id"], "username": row["username"], "friendCode": row["friend_code"]}


def create_user(username, password_hash):
    """Returns the new user, or None if the username is taken."""
    user_id = secrets.token_hex(8)
    with transaction() as cur:
        cur.execute("SELECT 1 FROM users WHERE username = %s", (username,))
        if cur.fetchone():
            return None
        for _ in range(5):  # friend codes are random; retry on the rare clash
            code = "".join(secrets.choice(FRIEND_CODE_CHARS) for _ in range(8))
            cur.execute("SELECT 1 FROM users WHERE friend_code = %s", (code,))
            if not cur.fetchone():
                break
        cur.execute(
            "INSERT INTO users (id, username, password_hash, friend_code, created_at) VALUES (%s, %s, %s, %s, %s)",
            (user_id, username, password_hash, code, now()),
        )
    return {"id": user_id, "username": username, "friendCode": code}


def user_by_name(username):
    with transaction() as cur:
        cur.execute("SELECT * FROM users WHERE username = %s", (username,))
        return cur.fetchone()


def user_by_id(user_id):
    with transaction() as cur:
        cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        return cur.fetchone()


# ---------- creatures ----------

def with_defaults(creature):
    """Upgrade v2 creatures on load (CREATURE_SPEC.md, v3 changes)."""
    creature.setdefault("drawnBy", None)
    battle = creature.get("battle") if isinstance(creature.get("battle"), dict) else {}
    creature["battle"] = {"size": 40, "baseAttack": 5, "wins": 0, **battle}
    return creature


def save_creature(owner_id, creature):
    drawn_by = (creature.get("drawnBy") or {}).get("userId")
    created = datetime.fromisoformat(creature["createdAt"].replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
    with transaction() as cur:
        cur.execute(
            "INSERT INTO creatures (id, owner_id, drawn_by, data, created_at) VALUES (%s, %s, %s, %s, %s)",
            (creature["id"], owner_id, drawn_by, json.dumps(creature), created),
        )
    return creature


def get_creatures(owner_id):
    with transaction() as cur:
        cur.execute("SELECT data FROM creatures WHERE owner_id = %s ORDER BY created_at", (owner_id,))
        rows = cur.fetchall()
    return [with_defaults(json.loads(r["data"])) for r in rows]


def count_creatures(owner_id):
    with transaction() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM creatures WHERE owner_id = %s", (owner_id,))
        return cur.fetchone()["n"]


def set_creature_scene(owner_id, creature_id, scene):
    """Moves a creature this user owns to a scene (None = out of the world). Returns it, or None if not theirs."""
    with transaction() as cur:
        cur.execute("SELECT data FROM creatures WHERE id = %s AND owner_id = %s FOR UPDATE", (creature_id, owner_id))
        row = cur.fetchone()
        if not row:
            return None
        creature = with_defaults(json.loads(row["data"]))
        creature["scene"] = scene
        cur.execute("UPDATE creatures SET data = %s WHERE id = %s", (json.dumps(creature), creature_id))
    return creature


def delete_creature(owner_id, creature_id):
    """Deletes only a creature this user owns. Returns True if one was deleted."""
    with transaction() as cur:
        return cur.execute("DELETE FROM creatures WHERE id = %s AND owner_id = %s", (creature_id, owner_id)) == 1


# ---------- friends (always mutual: one row each way) ----------

def friends_of(user_id):
    with transaction() as cur:
        cur.execute(
            "SELECT u.id, u.username, (SELECT COUNT(*) FROM creatures c WHERE c.owner_id = u.id) AS creatures "
            "FROM friendships f JOIN users u ON u.id = f.friend_id WHERE f.user_id = %s ORDER BY u.username",
            (user_id,),
        )
        return [{"id": r["id"], "username": r["username"], "creatures": r["creatures"]} for r in cur.fetchall()]


def add_friend(user_id, friend_code):
    """Returns (friend, problem). Adding by code makes both users friends right away."""
    with transaction() as cur:
        cur.execute("SELECT id, username FROM users WHERE friend_code = %s", (friend_code,))
        friend = cur.fetchone()
        if not friend:
            return None, "No one has that friend code."
        if friend["id"] == user_id:
            return None, "That's your own friend code."
        cur.execute("SELECT 1 FROM friendships WHERE user_id = %s AND friend_id = %s", (user_id, friend["id"]))
        if cur.fetchone():
            return None, f"You're already friends with {friend['username']}."
        created = now()
        cur.execute(
            "INSERT IGNORE INTO friendships (user_id, friend_id, created_at) VALUES (%s, %s, %s), (%s, %s, %s)",
            (user_id, friend["id"], created, friend["id"], user_id, created),
        )
    return {"id": friend["id"], "username": friend["username"]}, None


def remove_friend(user_id, friend_id):
    """Removes the friendship both ways. Returns True if there was one."""
    with transaction() as cur:
        removed = cur.execute(
            "DELETE FROM friendships WHERE (user_id = %s AND friend_id = %s) OR (user_id = %s AND friend_id = %s)",
            (user_id, friend_id, friend_id, user_id),
        )
    return removed > 0



def are_friends(user_id, other_id):
    with transaction() as cur:
        cur.execute("SELECT 1 FROM friendships WHERE user_id = %s AND friend_id = %s", (user_id, other_id))
        return cur.fetchone() is not None


# ---------- battles ----------

def finish_battle(log, a_user, b_user, winner_user, loser_user, winning_ids, prize_id, picked_by):
    """End of a live battle, all in one transaction (spec, "After the battle"): move the prize creature to
    the winner (its drawnBy stays), add 1 to battle.wins for every creature on the winning team, and save
    the battle with its log. Returns the prize actually given, or None (draw, or the creature is gone)."""
    prize = None
    with transaction() as cur:
        if prize_id and winner_user:
            cur.execute("SELECT owner_id FROM creatures WHERE id = %s FOR UPDATE", (prize_id,))
            row = cur.fetchone()
            if row and row["owner_id"] == loser_user:
                cur.execute("UPDATE creatures SET owner_id = %s WHERE id = %s", (winner_user, prize_id))
                prize = {"creature": prize_id, "pickedBy": picked_by}
        for creature_id in winning_ids:
            cur.execute("SELECT data FROM creatures WHERE id = %s FOR UPDATE", (creature_id,))
            row = cur.fetchone()
            if row:
                creature = with_defaults(json.loads(row["data"]))
                creature["battle"]["wins"] += 1
                cur.execute("UPDATE creatures SET data = %s WHERE id = %s", (json.dumps(creature), creature_id))
        log = {**log, "prize": prize}
        winner = log["result"]["winner"]
        cur.execute(
            "INSERT INTO battles (id, a_user, b_user, winner, log, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
            (log["battleId"], a_user, b_user, winner, json.dumps(log), now()),
        )
    return prize

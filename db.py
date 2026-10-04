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


def delete_creature(owner_id, creature_id):
    """Deletes only a creature this user owns. Returns True if one was deleted."""
    with transaction() as cur:
        return cur.execute("DELETE FROM creatures WHERE id = %s AND owner_id = %s", (creature_id, owner_id)) == 1

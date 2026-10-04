"""Passwords and login sessions, standard library only.

Passwords are hashed with PBKDF2-SHA256 (600k rounds) and a random salt. A login is a signed cookie
"<userId>.<expiry>.<hmac>" so the server needs no session table. SESSION_SECRET in .env
keeps people logged in across server restarts.
"""
import hashlib
import hmac
import os
import re
import secrets
import time

COOKIE = "session"
SESSION_DAYS = 14
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")
PBKDF2_ROUNDS = 600_000

_fallback_secret = secrets.token_hex(32)


def secret():
    value = os.environ.get("SESSION_SECRET")
    if not value:
        return _fallback_secret.encode()  # everyone is logged out when the server restarts
    return value.encode()


# ---------- passwords ----------

def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def check_password(password, stored):
    try:
        scheme, rounds, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256" or not rounds.isdigit():
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds))
    return hmac.compare_digest(digest.hex(), digest_hex)


def username_problem(username):
    if not isinstance(username, str) or not USERNAME_RE.fullmatch(username):
        return "Username must be 3 to 20 letters, numbers or underscores."
    return None


def password_problem(password):
    if not isinstance(password, str) or len(password) < 6:
        return "Password must be at least 6 characters."
    if len(password) > 200:
        return "Password is too long."
    return None


# ---------- session cookie ----------

def _sign(payload):
    return hmac.new(secret(), payload.encode(), hashlib.sha256).hexdigest()


def make_token(user_id):
    payload = f"{user_id}.{int(time.time()) + SESSION_DAYS * 86400}"
    return f"{payload}.{_sign(payload)}"


def read_token(token):
    """Returns the user id from a valid, unexpired token, else None."""
    try:
        user_id, expiry, signature = (token or "").split(".")
    except ValueError:
        return None
    if not hmac.compare_digest(_sign(f"{user_id}.{expiry}"), signature):
        return None
    if not expiry.isdigit() or int(expiry) < time.time():
        return None
    return user_id


def set_cookie(response, user_id):
    response.set_cookie(COOKIE, make_token(user_id), max_age=SESSION_DAYS * 86400,
                        httponly=True, samesite="lax")


def clear_cookie(response):
    response.delete_cookie(COOKIE)

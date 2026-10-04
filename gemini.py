"""Gemini step (spec data flow 3-4): part roles, moves, locomotion, idles and battle.baseAttack.

The AI only decides those five things. Everything it returns is validated and clamped here,
and if the call fails (no key, network, bad JSON) a rule-based guess fills the same fields.
"""
import json
import math
import os
import time
import urllib.error
import urllib.request

ROLES = ["body", "head", "eye", "leg", "arm", "wing", "tail", "decoration"]
LOCOMOTION = ["walk", "hop", "slither", "fly", "scoot"]
MOVING_ROLES = {"leg", "arm", "wing", "tail"}
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


# ---------- part summary sent to Gemini ----------

def body_of(parts):
    return next((p for p in parts if p.get("role") == "body"), parts[0])


def bbox(points):
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    return min(xs), min(ys), max(xs), max(ys)


def stroke_length(points):
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def sharp_corners(points):
    """Corners where the stroke turns back by more than 100 degrees: spikes, teeth, claws, zigzags."""
    count = 0
    for a, b, c in zip(points, points[1:], points[2:]):
        u, v = (b[0] - a[0], b[1] - a[1]), (c[0] - b[0], c[1] - b[1])
        lu, lv = math.hypot(*u), math.hypot(*v)
        if lu >= 4 and lv >= 4 and (u[0] * v[0] + u[1] * v[1]) / (lu * lv) < math.cos(math.radians(100)):
            count += 1
    return count


def describe(part, body_box):
    minX, minY, maxX, maxY = bbox(part["points"])
    w, h = maxX - minX, maxY - minY
    cx, cy = (minX + maxX) / 2, (minY + maxY) / 2
    if max(w, h) < 15:
        shape = "dot"
    elif h > 2 * w:
        shape = "vertical line"
    elif w > 2 * h:
        shape = "horizontal line"
    else:
        shape = "curve or blob"
    bx0, by0, bx1, by1 = body_box
    if bx0 <= cx <= bx1 and by0 <= cy <= by1:
        where = "inside the body outline"
    else:
        vert = "above" if cy < by0 else "below" if cy > by1 else ""
        horiz = "left of" if cx < bx0 else "right of" if cx > bx1 else ""
        where = " and ".join(s for s in (vert, horiz) if s) + " the body"
    return {
        "id": part["id"],
        "color": part.get("color"),
        "shape": shape,
        "where": where,
        "center": [round(cx), round(cy)],
        "size": [round(w), round(h)],
        "length": round(stroke_length(part["points"])),
        "sharp_corners": sharp_corners(part["points"]),
        "attached_to": part.get("parent"),
    }


def summarize(parts):
    body = body_of(parts)
    body_box = bbox(body["points"])
    return body["id"], [describe(p, body_box) for p in parts if p is not body]


def body_line(parts):
    body = body_of(parts)
    x0, y0, x1, y1 = bbox(body["points"])
    return f'size {round(x1 - x0)} x {round(y1 - y0)}, {sharp_corners(body["points"])} sharp corners'


# ---------- prompt and API call ----------

PROMPT = """You are animating a creature a child drew. Decide which drawn stroke is which body part
and how the creature moves. Reply with JSON only.

Coordinates: origin (0,0) is the center of the body, x goes right, y goes DOWN (negative y = up).
The body stroke is "{body_id}" ({body}). It never moves. Every other stroke:
{parts}

What the user typed (null means they left it blank, so invent something fun and fitting):
- name: {name}
- how it moves: {movement}
- behaviour 1: {b1}
- behaviour 2: {b2}

Return exactly this shape:
{{
  "parts": [{{"id": "p1", "role": "leg", "moves": true}}],
  "locomotion": {{"type": "walk", "gait": [{{"part": "p1", "rotate": {{"amp": 25, "freq": 2, "phase": 0}}}}]}},
  "idles": [
    {{"name": "short label", "duration": 2.5, "tracks": [TRACK, ...]}},
    {{"name": "short label", "duration": 2.0, "tracks": [TRACK, ...]}}
  ],
  "baseAttack": 5
}}

Rules:
- "parts": one entry for every stroke above (not the body). role is one of: head, eye, leg, arm, wing, tail, decoration.
  moves = true if it should animate (legs, arms, wings, tails usually), false if it rides along (eyes, decorations usually).
- locomotion.type is one of: walk, hop, slither, fly, scoot. Base it on "how it moves" and the parts
  (wings suggest fly, no legs suggests slither or scoot or hop).
- gait: optional swings while travelling. angle = amp * sin(2*pi*(freq*t + phase)). Alternate legs with phase 0 and 0.5.
- idles: exactly 2. idles[0] acts out behaviour 1, idles[1] acts out behaviour 2.
  TRACK = {{"part": "<id of a moving part>", "rotate": {{"amp": deg, "freq": hz, "phase": 0-1}},
            "scale": {{"amp": 0-0.4, "freq": hz, "phase": 0-1}},
            "offset": {{"ax": px, "ay": px, "freq": hz, "phase": 0-1}}}}
  Each channel is optional. Only target parts with moves = true, never the body.
- baseAttack: a whole number 1-10 for how dangerous it looks. Score it, don't guess:
  start at 5, then
    +2 if it has sharp parts: strokes with several sharp_corners (spikes, teeth, claws, horns, zigzags)
    +2 if the name, movement or behaviours sound fierce (bites, roars, charges, stomps, Fang, Rex, Doom...)
    +1 if it has many limbs or very long ones (4+ legs/arms, big wings or tail)
    -1 if it's all smooth round shapes with almost no sharp_corners
    -2 if the name or behaviours clearly sound cute or sleepy (naps, hugs, cuddles, Mochi, Puff, Bubbles...)
  Plain words (walks, jumps, waves, nods, runs) change nothing. Clamp to 1-10. A smooth blob named Mochi
  that naps is 2; a spiky clawed thing named Doomfang that bites is 10; most doodles land 4 to 7.
- Limits: rotate amp 0-60, scale amp 0-0.4, offset -30 to 30, freq 0.2-4, phase 0-1, duration 1-5 seconds.
"""


def build_prompt(settings, body_id, summary, body="no details"):
    b1, b2 = (settings.get("behaviours") or [None, None])[:2]
    return PROMPT.format(
        body_id=body_id,
        body=body,
        parts="\n".join(json.dumps(s) for s in summary) or "(none, the creature is just a body)",
        name=json.dumps(settings.get("name")),
        movement=json.dumps(settings.get("movement")),
        b1=json.dumps(b1),
        b2=json.dumps(b2),
    )


# Tried in order. Each model has its own free-tier daily quota (about 20 requests). The fast
# lite models go first; the bigger flash models are often overloaded. Override with GEMINI_MODEL=a,b,c.
DEFAULT_MODELS = [
    "gemini-flash-lite-latest",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.8-flash",
    "gemini-3.5-flash",
    "gemini-3.6-flash",
]
PER_MODEL_TIMEOUT = 12  # seconds
TOTAL_BUDGET = 30       # seconds for the whole Gemini step before falling back to rules
out_of_quota = set()    # models that said their daily quota is used up (skipped until restart)


def models():
    names = [m.strip() for m in os.environ.get("GEMINI_MODEL", "").split(",") if m.strip()]
    return [m for m in names or DEFAULT_MODELS if m not in out_of_quota]


def call_model(model, key, prompt, timeout):
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.9,
                             "thinkingConfig": {"thinkingLevel": "low"}},
    }
    req = urllib.request.Request(
        API_URL.format(model=model),
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
    )
    with urllib.request.urlopen(req, timeout=timeout) as res:
        data = json.loads(res.read())
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


def call_gemini(prompt):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    deadline = time.monotonic() + TOTAL_BUDGET
    errors = []
    for model in models():
        left = deadline - time.monotonic()
        if left < 2:
            errors.append("out of time")
            break
        try:
            ai = call_model(model, key, prompt, min(PER_MODEL_TIMEOUT, left))
            print(f"[gemini] answered by {model}")
            return ai
        except urllib.error.HTTPError as e:
            detail = e.read()[:3000].decode(errors="replace")
            errors.append(f"{model}: HTTP {e.code}")
            if e.code in (401, 403) or "API_KEY" in detail:  # bad key: other models won't help
                raise RuntimeError(f"Gemini HTTP {e.code}: {detail[:300]}") from e
            if e.code == 429 and "PerDay" in detail:
                out_of_quota.add(model)
        except (OSError, ValueError, KeyError, IndexError) as e:  # timeout, network, bad JSON
            errors.append(f"{model}: {type(e).__name__}")
    raise RuntimeError("no Gemini model answered (" + ", ".join(errors) + ")")


# ---------- validation and clamping (clamp table in CREATURE_SPEC.md) ----------

def num(v, lo, hi, default):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return default
    return round(min(hi, max(lo, v)), 3)


def clean_wave(w, amp_lo, amp_hi, amp_default):
    return {"amp": num(w.get("amp"), amp_lo, amp_hi, amp_default),
            "freq": num(w.get("freq"), 0.2, 4, 1),
            "phase": num(w.get("phase"), 0, 1, 0)}


def clean_track(t, moving_ids):
    if not isinstance(t, dict) or t.get("part") not in moving_ids:
        return None
    out = {"part": t["part"]}
    if isinstance(t.get("rotate"), dict):
        out["rotate"] = clean_wave(t["rotate"], 0, 60, 15)
    if isinstance(t.get("scale"), dict):
        out["scale"] = clean_wave(t["scale"], 0, 0.4, 0.1)
    if isinstance(t.get("offset"), dict):
        o = t["offset"]
        out["offset"] = {"ax": num(o.get("ax"), -30, 30, 0), "ay": num(o.get("ay"), -30, 30, 0),
                         "freq": num(o.get("freq"), 0.2, 4, 1), "phase": num(o.get("phase"), 0, 1, 0)}
    return out if len(out) > 1 else None


def clean_tracks(tracks, moving_ids):
    if not isinstance(tracks, list):
        return []
    return [t for t in (clean_track(t, moving_ids) for t in tracks) if t]


def apply(creature, ai):
    """Write a (possibly messy) AI answer onto the creature. Anything invalid falls back to the rules."""
    parts = creature["parts"]
    body = body_of(parts)
    guess = fallback(creature)
    answers = {p.get("id"): p for p in ai.get("parts", []) if isinstance(p, dict)} \
        if isinstance(ai.get("parts"), list) else {}

    for part in parts:
        if part is body:
            part.update(role="body", moves=False)
            continue
        a, g = answers.get(part["id"], {}), guess["roles"][part["id"]]
        role = a.get("role") if a.get("role") in ROLES and a.get("role") != "body" else g[0]
        moves = a.get("moves") if isinstance(a.get("moves"), bool) else role in MOVING_ROLES
        part.update(role=role, moves=moves)
    moving = {p["id"] for p in parts if p["moves"] and p is not body}

    loco = ai.get("locomotion") if isinstance(ai.get("locomotion"), dict) else {}
    creature["locomotion"] = {
        "type": loco.get("type") if loco.get("type") in LOCOMOTION else guess["locomotion"]["type"],
        "gait": clean_tracks(loco.get("gait"), moving),
    }

    idles = ai.get("idles") if isinstance(ai.get("idles"), list) else []
    behaviours = (creature["settings"].get("behaviours") or [None, None])[:2]
    creature["idles"] = []
    for i in range(2):
        a = idles[i] if i < len(idles) and isinstance(idles[i], dict) else {}
        g = guess["idles"][i]
        tracks = clean_tracks(a.get("tracks"), moving)
        name = a.get("name") if isinstance(a.get("name"), str) and a["name"].strip() else g["name"]
        creature["idles"].append({
            "name": name.strip()[:40],
            "source": behaviours[i] if i < len(behaviours) and behaviours[i] else "invented",
            "duration": num(a.get("duration"), 1, 5, 2),
            "tracks": tracks if tracks else clean_tracks(g["tracks"], moving),
        })

    battle = creature.setdefault("battle", {})
    battle["baseAttack"] = round(num(ai.get("baseAttack"), 1, 10, guess["baseAttack"]))
    return creature


# ---------- rule-based fallback ----------

def guess_role(desc):
    w, h = desc["size"]
    where, cy = desc["where"], desc["center"][1]
    if desc["shape"] == "dot":
        return "eye" if cy <= 0 else "decoration"
    if where.startswith("inside"):
        return "decoration"
    if where.startswith("below"):
        return "leg" if desc["shape"] == "vertical line" or h >= w else "tail"
    if where.startswith("above"):
        return "head" if desc["length"] > 80 else "decoration"
    # left or right of the body
    return "wing" if cy < 0 and w > 40 else "arm" if desc["shape"] == "horizontal line" else "tail"


def fallback(creature):
    parts = creature["parts"]
    _, summary = summarize(parts)
    roles = {}
    for desc in summary:
        role = guess_role(desc)
        roles[desc["id"]] = (role, role in MOVING_ROLES)
    moving = [pid for pid, (_, moves) in roles.items() if moves]
    loco = "fly" if any(r == "wing" for r, _ in roles.values()) else "walk" if moving else "hop"
    behaviours = (creature["settings"].get("behaviours") or [None, None])[:2]
    names = [b or d for b, d in zip(behaviours + [None, None], ["wiggles happily", "stretches"])]
    return {
        "roles": roles,
        "locomotion": {"type": loco},
        "idles": [
            {"name": names[0], "tracks": [{"part": p, "rotate": {"amp": 25, "freq": 2, "phase": (i % 2) * 0.5}}
                                          for i, p in enumerate(moving)]},
            {"name": names[1], "tracks": [{"part": p, "scale": {"amp": 0.15, "freq": 1, "phase": 0}}
                                          for p in moving]},
        ],
        "baseAttack": 5,
    }


def enrich(creature):
    """Fill role, moves, locomotion, idles and battle.baseAttack. Never raises: falls back to rules on any failure."""
    body_id, summary = summarize(creature["parts"])
    try:
        ai = call_gemini(build_prompt(creature["settings"], body_id, summary, body_line(creature["parts"])))
        if not isinstance(ai, dict):
            raise ValueError("Gemini did not return a JSON object")
    except Exception as e:  # any failure: still save a creature that moves
        print(f"[gemini] falling back to rules: {e}")
        ai = {}
    return apply(creature, ai)

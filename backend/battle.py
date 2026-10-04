"""Battle engine (docs/CREATURE_SPEC.md, "Battle log"). Pure: no database, no clock, no network.

run_battle(teamA, teamB, seed, buffs) -> log. The same teams and seed always give the same log, so the
server runs it once and both clients only play the log back. The server adds battleId, startAt,
each side's userId and name, and prize; everything else in the log comes from here.

Times are whole centiseconds inside the engine so there is no float drift, and become seconds
(rounded to 0.01) only in the log.
"""
import heapq
import math
import random

TEAM_SIZE = 3
TIME_LIMIT = 12000   # 120 s
HIT_DELAY = 30       # the hit or miss lands 0.3 s after its attack (spec)
READY = 80           # after entering, wait this long before the first attack
ENTER_GAP = 120      # after a faint, the next creature enters this much later
END_GAP = 100        # after the last faint, the end event (victory moment) this much later

# Every creature has the same hp and attacks at the same speed. Size changes the odds instead:
# big creatures crit more often, small creatures dodge more often. The dodge chance is derived from the
# crit chance so that for ANY two sizes, both sides expect the same damage per attack (big hits harder
# on average when it lands, small is harder to land on). Tuned with scripts/battle_sim.py.
SIZE_RANGE = (15, 85)        # most drawings land in here; sizes outside count as the nearest end
HP = 150
ATTACK_SECONDS = 1.3         # time between attacks, same for everyone
ATTACK_JITTER = 0.2          # each gap is +-20%, or equal speeds lock in step and both last creatures
                             # often fall together (a draw, so no prize)
CRIT_CHANCE = (0.03, 0.15)   # attacker's crit chance at size 15 .. 85
CRIT_MULTIPLIER = 2.0
MIN_DODGE = 0.02             # the biggest creature's dodge chance; smaller ones dodge more (about 12% at 15)
DAMAGE_BASE = 15
DAMAGE_PER_ATTACK = 0.5      # baseAttack 1..10 -> 15.5..20 before crits and variance; matters, doesn't decide
DAMAGE_SPREAD = 0.3          # each hit is +-30%
FIRST_ATTACK = (0.3, 0.6)    # first attack after READY + this many intervals, a bit random so sides don't sync

# Buff cards: after picking a team, each player draws one of 3 face-down cards (2 buffs, 1 debuff, shuffled).
# A card changes only its own team. Each field applies to every creature on the team:
#   hp: max hp   crit / dodge: chance, added to the size-based chance (each kept within 0..MAX_CHANCE)
#   damage: hits do this much more (-0.04 = 4% less)   speed: attacks this much more often (-0.04 = 4% slower)
#   ambush / fumble: the team's first attack of the battle always lands and crits / always misses
# Battles are long, so small edges add up: +10 hp alone wins 67%. Tuned with scripts/battle_sim.py so every buff wins
# about 60% against no card and every debuff about 36% (the mirror image, since about 4% are draws).
BUFFS = {
    "tough":    {"good": True,  "name": "Tough Hide",   "hp": 6},
    "sharp":    {"good": True,  "name": "Sharp Claws",  "crit": 0.05},
    "slippery": {"good": True,  "name": "Slippery",     "dodge": 0.04},
    "snack":    {"good": True,  "name": "Power Snack",  "damage": 0.04},
    "quick":    {"good": True,  "name": "Quick Feet",   "speed": 0.04},
    "ambush":   {"good": True,  "name": "Ambush",       "ambush": True},
    "tummy":    {"good": False, "name": "Tummy Ache",   "hp": -6},
    "clumsy":   {"good": False, "name": "Clumsy",       "crit": -0.02, "dodge": -0.02},
    "sleepy":   {"good": False, "name": "Sleepy",       "speed": -0.04},
    "noodle":   {"good": False, "name": "Noodle Arms",  "damage": -0.04},
    "fright":   {"good": False, "name": "Stage Fright", "fumble": True},
}
HAND = (2, 1)                # buffs and debuffs in each hand of 3
MAX_CHANCE = 0.5


# ---------- stats ----------

def clamp_int(v, lo, hi, default):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return default
    return round(min(hi, max(lo, v)))


def size_fraction(size):
    """0 for the smallest size that counts (15 or less), 1 for the biggest (85 or more)."""
    lo, hi = SIZE_RANGE
    return (min(hi, max(lo, size)) - lo) / (hi - lo)


def max_hp(size):
    return HP


def attack_interval(size):
    """Centiseconds between attacks."""
    return round(100 * ATTACK_SECONDS)


def crit_chance(size):
    lo, hi = CRIT_CHANCE
    return lo + (hi - lo) * size_fraction(size)


def dodge_chance(size):
    """Chosen so (1 + crit * (CRIT_MULTIPLIER - 1)) / (1 - dodge) is the same for every size: then
    attacker a against target b expects exactly what b expects against a."""
    extra = CRIT_MULTIPLIER - 1
    balance = (1 + CRIT_CHANCE[1] * extra) / (1 - MIN_DODGE)
    return 1 - (1 + crit_chance(size) * extra) / balance


def base_damage(base_attack):
    return DAMAGE_BASE + DAMAGE_PER_ATTACK * base_attack


# ---------- buff cards ----------

def describe(card):
    """What the card says once it's flipped, made from its numbers so the text can't drift from the effect."""
    pct = lambda v: f"{'+' if v > 0 else '-'}{round(abs(v) * 100)}%"
    if card.get("ambush"):
        return "Your first attack of the battle always lands and crits"
    if card.get("fumble"):
        return "Your first attack of the battle always misses"
    if "crit" in card and "dodge" in card and card["crit"] == card["dodge"]:
        return f"{pct(card['crit'])} crit and dodge chance"
    if "hp" in card:
        return f"{'+' if card['hp'] > 0 else '-'}{abs(card['hp'])} hp for every creature"
    if "crit" in card:
        return f"{pct(card['crit'])} crit chance"
    if "dodge" in card:
        return f"{pct(card['dodge'])} dodge chance"
    if "damage" in card:
        return f"Hits do {round(abs(card['damage']) * 100)}% {'more' if card['damage'] > 0 else 'less'} damage"
    if "speed" in card:
        return f"Attacks {round(abs(card['speed']) * 100)}% {'faster' if card['speed'] > 0 else 'slower'}"
    return ""


def card_info(buff_id):
    """The card as players and the log see it, or None for no card."""
    if buff_id is None:
        return None
    card = BUFFS[buff_id]
    return {"id": buff_id, "name": card["name"], "text": describe(card), "good": card["good"]}


def deal(rng):
    """A hand of 3 buff ids, face-down order: HAND[0] buffs and HAND[1] debuffs, shuffled."""
    good = [k for k, c in BUFFS.items() if c["good"]]
    bad = [k for k, c in BUFFS.items() if not c["good"]]
    hand = rng.sample(good, HAND[0]) + rng.sample(bad, HAND[1])
    rng.shuffle(hand)
    return hand


def snapshot(creature, buff_id=None):
    """The team entry saved in the log: stats frozen at battle time, the card's hp already added."""
    if not isinstance(creature, dict) or not isinstance(creature.get("id"), str):
        raise ValueError("each team member must be a creature with an id")
    battle = creature.get("battle") if isinstance(creature.get("battle"), dict) else {}
    settings = creature.get("settings") if isinstance(creature.get("settings"), dict) else {}
    size = clamp_int(battle.get("size"), 5, 100, 40)
    return {
        "creature": creature["id"],
        "name": settings.get("name") or "?",
        "size": size,
        "baseAttack": clamp_int(battle.get("baseAttack"), 1, 10, 5),
        "maxHp": max(1, max_hp(size) + (BUFFS[buff_id].get("hp", 0) if buff_id else 0)),
    }


# ---------- the fight ----------

def secs(t):
    return round(t / 100, 2)


def simulate(team_a, team_b, rng, buffs=None):
    """Fight two lists of snapshots (any length >= 1). buffs maps a side to its card id (hp is already in the
    snapshots). Returns (events, result, end time in cs)."""
    teams = {"a": team_a, "b": team_b}
    card = {s: BUFFS[(buffs or {}).get(s)] if (buffs or {}).get(s) else {} for s in teams}
    opened = set()                         # first creatures that already made their first attack
    other = {"a": "b", "b": "a"}
    hp = {s: [m["maxHp"] for m in teams[s]] for s in teams}
    slot = {"a": None, "b": None}         # who is on the field (None while waiting to enter)
    timer = {"a": 0, "b": 0}              # bumped on every re-arm, so an older queued attack is dropped
    events = []
    queue = []                             # (time, order, kind, side, data)
    counter = 0

    def push(t, order, kind, side, data=None):
        nonlocal counter
        counter += 1
        heapq.heappush(queue, (t, order, counter, kind, side, data))

    def current(side):
        return teams[side][slot[side]]

    def arm(side, t):
        """Restart this side's attack timer: a new matchup starts fresh for both creatures."""
        timer[side] += 1
        interval = interval_of(side)
        push(t + READY + round(rng.uniform(*FIRST_ATTACK) * interval), 2, "attack", side, timer[side])

    def interval_of(side):
        return attack_interval(current(side)["size"]) / (1 + card[side].get("speed", 0))

    def chance(base, side, key):
        return min(MAX_CHANCE, max(0, base + card[side].get(key, 0)))

    def emit(t, **event):
        events.append({"t": secs(t), **event})

    # same-time order: hits land, then creatures enter, then new attacks start; side a before b
    push(0, 1, "enter", "a", 0)
    push(0, 1, "enter", "b", 0)
    end = None

    while queue:
        t, _, _, kind, side, data = heapq.heappop(queue)
        if t > TIME_LIMIT:
            break
        if end and kind != "hit":
            continue                        # after a knockout, only hits already in flight still land

        if kind == "enter":
            slot[side] = data
            me = current(side)
            emit(t, type="enter", side=side, slot=data, creature=me["creature"], hp=hp[side][data])
            foe = other[side]
            if slot[foe] is not None:
                arm(side, t)
                arm(foe, t)                 # the survivor starts over too, or slow survivors get a free hit

        elif kind == "attack":
            foe = other[side]
            if timer[side] != data or slot[side] is None or slot[foe] is None:
                continue                    # replaced by a newer timer, or someone is off the field
            if t + HIT_DELAY > TIME_LIMIT:
                continue                    # no attack whose hit would land after the time limit
            me, target = current(side), current(foe)
            emit(t, type="attack", side=side, creature=me["creature"], target=target["creature"])
            opener = slot[side] == 0 and me["creature"] not in opened   # the team's very first attack
            opened.add(me["creature"])
            ambush, fumble = opener and card[side].get("ambush"), opener and card[side].get("fumble")
            # always draw both rolls, so a card never shifts the random numbers of the rest of the battle
            dodge_roll, crit_roll = rng.random(), rng.random()
            if fumble or (not ambush and dodge_roll < chance(dodge_chance(target["size"]), foe, "dodge")):
                outcome = None
            else:
                crit = ambush or crit_roll < chance(crit_chance(me["size"]), side, "crit")
                damage = base_damage(me["baseAttack"]) * rng.uniform(1 - DAMAGE_SPREAD, 1 + DAMAGE_SPREAD)
                damage *= 1 + card[side].get("damage", 0)
                outcome = (max(1, round(damage * (CRIT_MULTIPLIER if crit else 1))), crit)
            push(t + HIT_DELAY, 0, "hit", foe, (slot[foe], me["creature"], outcome))
            gap = interval_of(side) * rng.uniform(1 - ATTACK_JITTER, 1 + ATTACK_JITTER)
            push(t + round(gap), 2, "attack", side, data)

        elif kind == "hit":
            target_slot, by, outcome = data
            target = teams[side][target_slot]
            if outcome is None:
                emit(t, type="miss", side=side, creature=target["creature"], by=by)
                continue
            damage, crit = outcome
            hp[side][target_slot] = max(0, hp[side][target_slot] - damage)
            emit(t, type="hit", side=side, creature=target["creature"], by=by, damage=damage, crit=crit,
                 hp=hp[side][target_slot])
            if hp[side][target_slot] > 0:
                continue
            emit(t, type="faint", side=side, creature=target["creature"])
            slot[side] = None
            if not all(h == 0 for h in hp[side]):
                push(t + ENTER_GAP, 1, "enter", side, target_slot + 1)
            elif all(h == 0 for h in hp[other[side]]):
                end = (t + END_GAP, "draw", "knockout")  # both last creatures went down
            else:
                end = (t + END_GAP, other[side], "knockout")

    if end is None:
        share = {s: sum(hp[s]) / sum(m["maxHp"] for m in teams[s]) for s in teams}
        winner = "a" if share["a"] > share["b"] else "b" if share["b"] > share["a"] else "draw"
        end = (TIME_LIMIT, winner, "timeout")
    end_t, winner, reason = end
    emit(end_t, type="end", winner=winner, reason=reason)
    return events, {"winner": winner, "reason": reason}, end_t


def run_battle(team_a, team_b, seed, buffs=None):
    """team_a and team_b are lists of exactly 3 creatures (spec JSON), in pick order; a is the inviter.
    buffs: {"a": card id or None, "b": ...}, each side's buff card."""
    buffs = {s: (buffs or {}).get(s) for s in "ab"}
    for team in (team_a, team_b):
        if not isinstance(team, list) or len(team) != TEAM_SIZE:
            raise ValueError(f"each team must have exactly {TEAM_SIZE} creatures")
    if any(b is not None and b not in BUFFS for b in buffs.values()):
        raise ValueError("unknown buff card")
    sides = {"a": [snapshot(c, buffs["a"]) for c in team_a], "b": [snapshot(c, buffs["b"]) for c in team_b]}
    for side in sides.values():
        if len({m["creature"] for m in side}) != TEAM_SIZE:
            raise ValueError("a team can't use the same creature twice")
    events, result, end_t = simulate(sides["a"], sides["b"], random.Random(seed), buffs)
    return {
        "version": 1,
        "seed": seed,
        "duration": secs(end_t),
        "sides": {s: {"team": sides[s], "buff": card_info(buffs[s])} for s in "ab"},
        "events": events,
        "result": result,
    }


def forfeit(log, at, loser):
    """The log cut short because `loser` ("a" or "b") left at `at` seconds: events after that are dropped,
    along with any attack whose hit or miss would land after it, and the other side wins by forfeit."""
    cut = round(max(0, min(at, log["duration"])), 2)
    events = [e for e in log["events"] if e["t"] <= cut and e["type"] != "end"
              and not (e["type"] == "attack" and secs(round(e["t"] * 100) + HIT_DELAY) > cut)]
    result = {"winner": "b" if loser == "a" else "a", "reason": "forfeit"}
    return {**log, "duration": cut, "events": events + [{"t": cut, "type": "end", **result}], "result": result}

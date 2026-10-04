"""Battle engine (CREATURE_SPEC.md, "Battle log"). Pure: no database, no clock, no network.

run_battle(teamA, teamB, seed) -> log. The same teams and seed always give the same log, so the
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

# Tuned with battle_sim.py (small vs big, tiny vs huge and small vs medium all land near 50/50;
# battles average about a minute). Bigger creatures have more hp but attack slower: time between
# attacks is proportional to hp, so size changes the fighting style, not the odds.
HP_BASE = 80
HP_PER_SIZE = 1.5            # size 5..100 -> 88..230 hp
SECONDS_PER_HP = 1 / 120     # time between attacks = maxHp / 120 seconds (about 0.7 s to 1.9 s)
DAMAGE_BASE = 10
DAMAGE_PER_ATTACK = 0.35     # baseAttack 1..10 -> 10.4..13.5 damage before variance; matters, doesn't decide
DAMAGE_SPREAD = 0.3          # each hit is +-30%
FIRST_ATTACK = (0.4, 0.7)    # first attack after READY + this many intervals. Below 1 on purpose: it makes
                             # up for overkill (a slow attacker wastes more time on a target's last sliver)
MISS_CHANCE = 0.12
CRIT_CHANCE = 0.15
CRIT_MULTIPLIER = 1.5


# ---------- stats ----------

def clamp_int(v, lo, hi, default):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return default
    return round(min(hi, max(lo, v)))


def max_hp(size):
    return round(HP_BASE + HP_PER_SIZE * size)


def attack_interval(hp):
    """Centiseconds between attacks."""
    return round(100 * hp * SECONDS_PER_HP)


def base_damage(base_attack):
    return DAMAGE_BASE + DAMAGE_PER_ATTACK * base_attack


def snapshot(creature):
    """The team entry saved in the log: stats frozen at battle time."""
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
        "maxHp": max_hp(size),
    }


# ---------- the fight ----------

def secs(t):
    return round(t / 100, 2)


def simulate(team_a, team_b, rng):
    """Fight two lists of snapshots (any length >= 1). Returns (events, result, end time in cs)."""
    teams = {"a": team_a, "b": team_b}
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
        interval = attack_interval(current(side)["maxHp"])
        push(t + READY + round(rng.uniform(*FIRST_ATTACK) * interval), 2, "attack", side, timer[side])

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
            if rng.random() < MISS_CHANCE:
                outcome = None
            else:
                crit = rng.random() < CRIT_CHANCE
                damage = base_damage(me["baseAttack"]) * rng.uniform(1 - DAMAGE_SPREAD, 1 + DAMAGE_SPREAD)
                outcome = (max(1, round(damage * (CRIT_MULTIPLIER if crit else 1))), crit)
            push(t + HIT_DELAY, 0, "hit", foe, (slot[foe], me["creature"], outcome))
            push(t + attack_interval(me["maxHp"]), 2, "attack", side, data)

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


def run_battle(team_a, team_b, seed):
    """team_a and team_b are lists of exactly 3 creatures (spec JSON), in pick order; a is the inviter."""
    for team in (team_a, team_b):
        if not isinstance(team, list) or len(team) != TEAM_SIZE:
            raise ValueError(f"each team must have exactly {TEAM_SIZE} creatures")
    sides = {"a": [snapshot(c) for c in team_a], "b": [snapshot(c) for c in team_b]}
    for side in sides.values():
        if len({m["creature"] for m in side}) != TEAM_SIZE:
            raise ValueError("a team can't use the same creature twice")
    events, result, end_t = simulate(sides["a"], sides["b"], random.Random(seed))
    return {
        "version": 1,
        "seed": seed,
        "duration": secs(end_t),
        "sides": {"a": {"team": sides["a"]}, "b": {"team": sides["b"]}},
        "events": events,
        "result": result,
    }

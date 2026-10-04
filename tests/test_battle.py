"""Checks for the battle engine. Run with: python -m tests.test_battle"""
import json
import random

from backend import battle


def creature(cid, size, base_attack, name=None):
    return {"id": cid, "settings": {"name": name or cid}, "battle": {"size": size, "baseAttack": base_attack, "wins": 0}}


# Round numbers for the paper check: 100 hp, an attack every 2 s, damage 20 + baseAttack, no crits or dodges.
PAPER_NUMBERS = {"HP": 100, "ATTACK_SECONDS": 2, "DAMAGE_BASE": 20, "DAMAGE_PER_ATTACK": 1,
                 "CRIT_CHANCE": (0, 0), "MIN_DODGE": 0, "DAMAGE_SPREAD": 0, "FIRST_ATTACK": (0, 0),
                 "ATTACK_JITTER": 0}


def fixed_numbers(**overrides):
    """Pin the tuning numbers (no randomness) so paper math holds after retuning. Returns a restore function."""
    values = {**PAPER_NUMBERS, **overrides}
    saved = {k: getattr(battle, k) for k in values}
    for k, v in values.items():
        setattr(battle, k, v)
    return lambda: [setattr(battle, k, v) for k, v in saved.items()]


def test_1v1_matches_paper():
    # A (baseAttack 5) hits for 25, B (baseAttack 3) for 23, both every 2 s starting at 0.8.
    # A needs 4 hits: the 4th attack at 6.8 lands 7.1, so B faints at 7.1.
    # B's 4th attack also started at 6.8 and still lands at 7.1: A has 100 - 4 * 23 = 8 left. A wins.
    restore = fixed_numbers()
    try:
        a, b = battle.snapshot(creature("A", 20, 5)), battle.snapshot(creature("B", 70, 3))
        assert (a["maxHp"], b["maxHp"]) == (100, 100)
        assert (battle.attack_interval(20), battle.attack_interval(70)) == (200, 200)
        events, result, end = battle.simulate([a], [b], random.Random(1))
    finally:
        restore()
    hits_on_b = [e for e in events if e["type"] == "hit" and e["creature"] == "B"]
    hits_on_a = [e for e in events if e["type"] == "hit" and e["creature"] == "A"]
    assert [e["damage"] for e in hits_on_b] == [25] * 4 and [e["damage"] for e in hits_on_a] == [23] * 4
    assert [e["t"] for e in hits_on_b] == [1.1, 3.1, 5.1, 7.1] and hits_on_b[-1]["hp"] == 0
    assert hits_on_a[-1]["t"] == 7.1 and hits_on_a[-1]["hp"] == 8
    assert not any(e["type"] in ("miss",) or e.get("crit") for e in events)
    assert {"t": 7.1, "type": "faint", "side": "b", "creature": "B"} in events
    assert result == {"winner": "a", "reason": "knockout"} and end == 710 + battle.END_GAP


def test_size_odds_are_fair():
    # big crits more, small dodges more, and any two sizes expect the same damage per attack
    assert battle.crit_chance(85) > battle.crit_chance(40) > battle.crit_chance(15)
    assert battle.dodge_chance(15) > battle.dodge_chance(40) > battle.dodge_chance(85)
    assert abs(battle.dodge_chance(85) - battle.MIN_DODGE) < 1e-9
    extra = battle.CRIT_MULTIPLIER - 1
    for a in (5, 15, 35, 53, 85, 100):
        for b in (5, 15, 35, 53, 85, 100):
            a_on_b = (1 - battle.dodge_chance(b)) * (1 + battle.crit_chance(a) * extra)
            b_on_a = (1 - battle.dodge_chance(a)) * (1 + battle.crit_chance(b) * extra)
            assert abs(a_on_b - b_on_a) < 1e-9


def team(prefix, stats):
    return [creature(f"{prefix}{i}", s, atk) for i, (s, atk) in enumerate(stats)]


def check_log_rules(log):
    events = log["events"]
    assert [e["t"] for e in events] == sorted(e["t"] for e in events), "events sorted by t"
    assert events[-1]["type"] == "end" and events[-1]["t"] == log["duration"]
    assert {k: events[-1][k] for k in ("winner", "reason")} == log["result"]
    assert log["duration"] <= 120
    for i, e in enumerate(events):
        if e["type"] == "attack":  # its hit or miss lands exactly 0.3 s later
            assert any(f["type"] in ("hit", "miss") and f["by"] == e["creature"] and f["creature"] == e["target"]
                       and round(f["t"] - e["t"], 2) == 0.3 for f in events[i + 1:]), e
    entered = [(e["side"], e["slot"]) for e in events if e["type"] == "enter"]
    assert entered[:2] == [("a", 0), ("b", 0)]
    for side in "ab":
        assert [s for sd, s in entered if sd == side] == list(range(len([1 for sd, _ in entered if sd == side])))


def test_same_seed_same_log():
    ta, tb = team("a", [(30, 6), (70, 4), (50, 5)]), team("b", [(90, 3), (10, 8), (40, 5)])
    first = battle.run_battle(ta, tb, 1234)
    assert json.dumps(first) == json.dumps(battle.run_battle(ta, tb, 1234))
    assert json.dumps(first) != json.dumps(battle.run_battle(ta, tb, 4321))
    check_log_rules(first)


def test_3v3_survivor_keeps_hp():
    for seed in range(200):
        log = battle.run_battle(team("a", [(30, 6), (70, 4), (50, 5)]), team("b", [(90, 3), (10, 8), (40, 5)]), seed)
        check_log_rules(log)
        events = log["events"]
        faint = next((i for i, e in enumerate(events) if e["type"] == "faint"), None)
        if faint is None:
            continue
        loser = events[faint]["side"]
        survivor = events[faint]["by"] if "by" in events[faint] else next(
            e["by"] for e in reversed(events[:faint]) if e["type"] == "hit")
        hp_before = next(e["hp"] for e in reversed(events[:faint]) if e.get("creature") == survivor and "hp" in e)
        nxt = next(e for e in events[faint:] if e["type"] == "enter" or e["type"] == "end")
        if nxt["type"] == "enter":
            assert nxt["side"] == loser and nxt["slot"] == 1
            # the survivor's next hp change starts from what it had left, not from full
            later = next((e for e in events[faint:] if e["type"] == "hit" and e["creature"] == survivor), None)
            if later:
                assert later["hp"] == hp_before - later["damage"] or later["hp"] == 0
            return
    raise AssertionError("no seed produced a mid-battle faint")


def test_end_reasons_and_draws():
    reasons = {}
    for seed in range(300):
        log = battle.run_battle(team("a", [(50, 5)] * 3), team("b", [(50, 5)] * 3), seed)
        check_log_rules(log)
        reasons[log["result"]["reason"]] = reasons.get(log["result"]["reason"], 0) + 1
        if log["result"]["reason"] == "knockout" and log["result"]["winner"] != "draw":
            loser = "b" if log["result"]["winner"] == "a" else "a"
            assert sum(e["type"] == "faint" and e["side"] == loser for e in log["events"]) == 3
    assert reasons.get("knockout", 0) > 250, reasons

    # two walls with 1 damage can't finish in 2 minutes: timeout, decided by share of hp left
    restore = fixed_numbers(DAMAGE_BASE=0, DAMAGE_PER_ATTACK=0)  # every hit does the minimum, 1
    try:
        log = battle.run_battle(team("a", [(5, 1)] * 3), team("b", [(100, 1)] * 3), 7)
    finally:
        restore()
    check_log_rules(log)
    assert log["result"]["reason"] == "timeout" and log["duration"] == 120
    # winner = larger share of total hp left; only each side's first creature took damage
    share = {}
    for side in "ab":
        team_hp = [m["maxHp"] for m in log["sides"][side]["team"]]
        first = log["sides"][side]["team"][0]["creature"]
        left = min((e["hp"] for e in log["events"] if e["type"] == "hit" and e["creature"] == first), default=team_hp[0])
        share[side] = (left + sum(team_hp[1:])) / sum(team_hp)
    expected = "a" if share["a"] > share["b"] else "b" if share["b"] > share["a"] else "draw"
    assert log["result"]["winner"] == expected, (log["result"], share)


def test_rejects_bad_teams():
    good = team("a", [(50, 5)] * 3)
    for bad in (good[:2], good + good[:1], [good[0], good[0], good[1]], None):
        try:
            battle.run_battle(bad, good, 1)
        except ValueError:
            continue
        raise AssertionError(f"accepted a bad team: {bad}")


def test_clamps_stats():
    snap = battle.snapshot({"id": "x", "settings": {"name": "X"}, "battle": {"size": 999, "baseAttack": -4}})
    assert (snap["size"], snap["baseAttack"], snap["maxHp"]) == (100, 1, battle.max_hp(85))
    assert battle.snapshot({"id": "y"})["size"] == 40  # old creature without battle stats


def test_forfeit_cuts_the_log():
    log = battle.run_battle(team("a", [(30, 6), (70, 4), (50, 5)]), team("b", [(90, 3), (10, 8), (40, 5)]), 99)
    for at in (0, 3.05, log["duration"] / 2):
        cut = battle.forfeit(log, at, "a")
        check_log_rules(cut)
        assert cut["result"] == {"winner": "b", "reason": "forfeit"} and cut["duration"] == round(at, 2)
        assert all(e["t"] <= cut["duration"] for e in cut["events"])
    assert battle.forfeit(log, 999, "b")["duration"] == log["duration"]  # can't cut past the end


def test_buff_cards():
    rng = random.Random(5)
    for _ in range(200):  # every hand: 3 different cards, 2 buffs and 1 debuff
        hand = battle.deal(rng)
        assert len(set(hand)) == 3 and sorted(battle.BUFFS[c]["good"] for c in hand) == [False, True, True]
    assert all(battle.describe(c) for c in battle.BUFFS.values())

    ta, tb = team("a", [(30, 6), (70, 4), (50, 5)]), team("b", [(90, 3), (10, 8), (40, 5)])
    log = battle.run_battle(ta, tb, 3, {"a": "tough"})
    check_log_rules(log)
    assert log["sides"]["a"]["buff"]["name"] == "Tough Hide" and log["sides"]["b"]["buff"] is None
    assert [m["maxHp"] for m in log["sides"]["a"]["team"]] == [battle.HP + battle.BUFFS["tough"]["hp"]] * 3
    assert [m["maxHp"] for m in log["sides"]["b"]["team"]] == [battle.HP] * 3   # only your own team
    assert battle.run_battle(ta, tb, 3)["sides"]["a"]["buff"] is None

    def first_outcome(buff, seed):
        log = battle.run_battle(ta, tb, seed, {"a": buff})
        return next(e for e in log["events"] if e["type"] in ("hit", "miss") and e["by"] == "a0")
    for seed in range(20):
        assert first_outcome("ambush", seed)["type"] == "hit" and first_outcome("ambush", seed)["crit"]
        assert first_outcome("fright", seed)["type"] == "miss"

    try:
        battle.run_battle(ta, tb, 3, {"a": "not-a-card"})
    except ValueError:
        pass
    else:
        raise AssertionError("accepted an unknown card")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)

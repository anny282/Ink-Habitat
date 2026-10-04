"""Checks for the battle engine. Run with: python test_battle.py"""
import json
import random

import battle


def creature(cid, size, base_attack, name=None):
    return {"id": cid, "settings": {"name": name or cid}, "battle": {"size": size, "baseAttack": base_attack, "wins": 0}}


PAPER_NUMBERS = {"HP_BASE": 80, "HP_PER_SIZE": 1.5, "SECONDS_PER_HP": 1 / 90, "DAMAGE_BASE": 8,
                 "DAMAGE_PER_ATTACK": 1.2, "MISS_CHANCE": 0, "CRIT_CHANCE": 0, "DAMAGE_SPREAD": 0,
                 "FIRST_ATTACK": (0, 0)}


def fixed_numbers(**overrides):
    """Pin the tuning numbers (no randomness) so paper math holds after retuning. Returns a restore function."""
    values = {**PAPER_NUMBERS, **overrides}
    saved = {k: getattr(battle, k) for k in values}
    for k, v in values.items():
        setattr(battle, k, v)
    return lambda: [setattr(battle, k, v) for k, v in saved.items()]


def test_1v1_matches_paper():
    # A: size 20 -> hp 110, attacks every 1.22 s. B: size 60 -> hp 170, every 1.89 s. Both deal 14.
    # B needs 8 hits on A: last attack 0.8 + 7 * 1.89 = 14.03, lands 14.33, so A faints at 14.33. B wins.
    # A's attacks start at 0.8 + k * 1.22: k = 0..11 start before 14.33 (the 12th at 14.22 is mid-dash and
    # still lands at 14.52), so B takes 12 hits: 170 - 12 * 14 = 2 hp left.
    restore = fixed_numbers()
    try:
        a, b = battle.snapshot(creature("A", 20, 5)), battle.snapshot(creature("B", 60, 5))
        assert (a["maxHp"], b["maxHp"]) == (110, 170)
        assert (battle.attack_interval(110), battle.attack_interval(170)) == (122, 189)
        events, result, end = battle.simulate([a], [b], random.Random(1))
    finally:
        restore()
    hits_on_b = [e for e in events if e["type"] == "hit" and e["creature"] == "B"]
    hits_on_a = [e for e in events if e["type"] == "hit" and e["creature"] == "A"]
    assert all(e["damage"] == 14 and not e["crit"] for e in hits_on_a + hits_on_b)
    assert len(hits_on_a) == 8 and hits_on_a[-1]["t"] == 14.33 and hits_on_a[-1]["hp"] == 0
    assert len(hits_on_b) == 12 and hits_on_b[-1]["t"] == 14.52 and hits_on_b[-1]["hp"] == 2
    assert {"t": 14.33, "type": "faint", "side": "a", "creature": "A"} in events
    assert result == {"winner": "b", "reason": "knockout"} and end == 1433 + battle.END_GAP


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
    assert (snap["size"], snap["baseAttack"], snap["maxHp"]) == (100, 1, 230)
    assert battle.snapshot({"id": "y"})["size"] == 40  # old creature without battle stats


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)

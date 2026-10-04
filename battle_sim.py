"""Balance simulator for battle.py. Run with: python battle_sim.py [battles per test]

Fights many seeded battles and prints win rates, so the numbers at the top of battle.py
can be tuned until small and big creatures win about equally.
"""
import random
import sys
from collections import Counter

import battle

N = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
rng = random.Random(2026)


def creature(cid, size, base_attack):
    return {"id": cid, "settings": {"name": cid}, "battle": {"size": size, "baseAttack": base_attack}}


def team(prefix, sizes, attacks):
    return [creature(f"{prefix}{i}", rng.randint(*sizes), rng.randint(*attacks)) for i in range(3)]


def fight(sizes_a, sizes_b, attacks_a=(3, 8), attacks_b=(3, 8), buff_a=None, buff_b=None):
    """N battles; sides swap who is a and b each time so going first can't skew it. Returns stats for the first group."""
    outcomes, duration = Counter(), 0
    for i in range(N):
        first, second = team("x", sizes_a, attacks_a), team("y", sizes_b, attacks_b)
        flip = i % 2 == 1
        log = (battle.run_battle(second, first, i, {"a": buff_b, "b": buff_a}) if flip
               else battle.run_battle(first, second, i, {"a": buff_a, "b": buff_b}))
        winner = log["result"]["winner"]
        mine = "b" if flip else "a"
        outcomes["draw" if winner == "draw" else "win" if winner == mine else "loss"] += 1
        outcomes[log["result"]["reason"]] += 1
        duration += log["duration"]
    return outcomes, duration / N


def report(label, outcomes, avg):
    print(f"{label:<46} win {outcomes['win'] / N:6.1%}  draw {outcomes['draw'] / N:5.1%}  "
          f"timeout {outcomes['timeout'] / N:5.1%}  avg {avg:5.1f}s")


print(f"{N} battles per line (3v3, baseAttack 3-8 unless shown)\n")
print("Size balance (goal: about 50%)")
for label, small, big in [("tiny 5-20 vs huge 85-100", (5, 20), (85, 100)),
                          ("small 5-35 vs big 65-100", (5, 35), (65, 100)),
                          ("small 5-35 vs medium 36-64", (5, 35), (36, 64)),
                          ("medium 36-64 vs big 65-100", (36, 64), (65, 100))]:
    report("  " + label, *fight(small, big))
report("  any vs any (sanity: should be ~50%)", *fight((5, 100), (5, 100)))

print("\nbaseAttack should matter (goal: clearly above 50%)")
for label, strong, weak in [("attack 8-10 vs 1-3", (8, 10), (1, 3)),
                            ("attack 6-7 vs 4-5", (6, 7), (4, 5))]:
    report("  " + label, *fight((5, 100), (5, 100), strong, weak))

print("\nSmall vs big at equal attack (goal: about 50%)")
for atk in (1, 5, 10):
    report(f"  small 5-35 vs big 65-100, attack {atk}", *fight((5, 35), (65, 100), (atk, atk), (atk, atk)))

print("\nBuff cards vs no card, any sizes (goal: buffs about 60%, debuffs about 36%)")
for buff_id, card in battle.BUFFS.items():
    label = f"  {'+' if card['good'] else '-'} {card['name']}: {battle.describe(card)}"
    report(label[:44], *fight((5, 100), (5, 100), buff_a=buff_id))

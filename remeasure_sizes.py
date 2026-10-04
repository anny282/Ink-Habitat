"""Re-measure battle.size for every saved creature with the current formula (server.measure_size).

    python remeasure_sizes.py          # show what would change, write nothing
    python remeasure_sizes.py --apply  # save the new sizes

How big each creature was drawn is only known for creatures saved with battle.canvasSize, or from before
that field existed with a size other than the default 40 (that was the drawing tool's measure). For the
rest, the middle value is used and the size comes from the drawing's shape.
"""
import json
import sys

import db
import server  # loads .env

apply = "--apply" in sys.argv
with db.transaction() as cur:
    cur.execute("SELECT u.username, c.id, c.data FROM creatures c JOIN users u ON u.id = c.owner_id ORDER BY u.username, c.created_at")
    rows = cur.fetchall()
    for row in rows:
        creature = db.with_defaults(json.loads(row["data"]))
        battle = creature["battle"]
        canvas = battle["canvasSize"] if "canvasSize" in battle else (battle["size"] if battle["size"] != 40 else None)
        new = server.measure_size(creature, canvas)
        print(f'{row["username"]:<12} {creature["settings"]["name"]:<14} size {battle["size"]:>3} -> {new:>3}'
              f'   (drawn size {"unknown" if canvas is None else canvas})')
        if apply:
            battle.update(size=new, canvasSize=canvas)
            cur.execute("UPDATE creatures SET data = %s WHERE id = %s", (json.dumps(creature), row["id"]))
print(f"\nSaved {len(rows)} creatures." if apply else "\nNothing saved. Run with --apply to save these sizes.")

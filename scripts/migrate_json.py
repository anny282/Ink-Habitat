"""Move creatures saved as JSON files (before TiDB) into one account's farm.

Usage:  python -m scripts.migrate_json <username> [folder ...]
Default folders: data/creatures and assets/test-creatures. Creatures already in TiDB are skipped,
so running it twice is safe. The account must exist (sign up on the website first).
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pymysql

from backend import ROOT, db
from backend.creatures import assign_id


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    user = db.user_by_name(sys.argv[1])
    if not user:
        sys.exit(f"No account named {sys.argv[1]!r}. Sign up on the website first.")
    folders = [Path(f) for f in sys.argv[2:]] or [ROOT / "data" / "creatures", ROOT / "assets" / "test-creatures"]
    moved = skipped = 0
    for folder in folders:
        for path in sorted(folder.glob("*.json")):
            creature = json.loads(path.read_text(encoding="utf-8"))
            if not creature.get("id"):
                assign_id(creature)
            creature.setdefault("createdAt", datetime.now(timezone.utc).isoformat())
            try:
                db.save_creature(user["id"], db.with_defaults(creature))
                moved += 1
                print(f"moved   {path.name}  ({creature['settings']['name']})")
            except pymysql.err.IntegrityError:
                skipped += 1
                print(f"skipped {path.name}  (already in TiDB)")
    print(f"\n{moved} moved, {skipped} skipped, into {user['username']}'s farm.")


if __name__ == "__main__":
    main()

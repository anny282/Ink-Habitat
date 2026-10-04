"""Copy the voice clips saved on this laptop (data/audio, from before clips moved into TiDB) into TiDB,
so every server can play them. Clips already in TiDB, and clips of deleted creatures, are skipped,
so running it twice is safe. Each laptop that ever ran the server can run it once.

    python -m scripts.upload_audio
"""
from backend import db
from backend.app import AUDIO

stored = skipped = 0
for path in sorted(AUDIO.glob("*.mp3")):
    if db.add_audio(path.stem, path.read_bytes()):
        stored += 1
    else:
        skipped += 1
print(f"Uploaded {stored} clip(s); skipped {skipped} (already uploaded, or the creature was deleted).")

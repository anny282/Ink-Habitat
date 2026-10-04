"""Copy the voice clips saved on this laptop (data/audio, from before clips moved into TiDB) into TiDB,
so every server can play them. Clips already in TiDB, and clips of deleted creatures, are skipped,
so running it twice is safe. Each laptop that ever ran the server can run it once.

    python upload_audio.py
"""
import db
import server  # loads .env

stored = skipped = 0
for path in sorted(server.AUDIO.glob("*.mp3")):
    if db.add_audio(path.stem, path.read_bytes()):
        stored += 1
    else:
        skipped += 1
print(f"Uploaded {stored} clip(s); skipped {skipped} (already uploaded, or the creature was deleted).")

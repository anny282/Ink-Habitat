"""Local Creature World server. Run with: python3 server.py"""
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from rig import rig_parts

BASE = Path(__file__).resolve().parent
FRONTEND = BASE / "frontend"
DATA = BASE / "data" / "creatures"
DATA.mkdir(parents=True, exist_ok=True)
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
app = FastAPI(title="StromHacks Creature World")


def path_for(creature_id: str) -> Path:
    if not ID_RE.fullmatch(creature_id):
        raise HTTPException(400, "Invalid creature id")
    return DATA / f"{creature_id}.json"


def validate(creature):
    if not isinstance(creature, dict):
        raise HTTPException(400, "Creature must be a JSON object")
    settings = creature.get("settings")
    name = settings.get("name") if isinstance(settings, dict) else None
    if not isinstance(name, str) or not name.strip():
        raise HTTPException(400, "settings.name is required")
    settings["name"] = name.strip()[:16]
    parts = creature.get("parts")
    if not isinstance(parts, list) or not 1 <= len(parts) <= 8:
        raise HTTPException(400, "parts must contain 1 to 8 entries")
    if isinstance(creature.get("sound"), dict):
        text = creature["sound"].get("text")
        if isinstance(text, str):
            creature["sound"]["text"] = text.strip()[:19]
    return creature


def save(creature):
    creature["id"] = uuid.uuid4().hex[:12]
    creature["createdAt"] = datetime.now(timezone.utc).isoformat()
    path_for(creature["id"]).write_text(json.dumps(creature, indent=2), encoding="utf-8")
    return creature


@app.get("/api/creatures")
def list_creatures():
    creatures = []
    for path in DATA.glob("*.json"):
        try:
            creatures.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(creatures, key=lambda c: c.get("createdAt", ""))


@app.post("/api/creatures")
def create_creature(creature: dict = Body(...)):
    creature = validate(creature)
    rig_parts(creature["parts"])
    return save(creature)


@app.delete("/api/creatures/{creature_id}")
def delete_creature(creature_id: str):
    path = path_for(creature_id)
    if not path.exists():
        raise HTTPException(404, "Creature not found")
    path.unlink()
    return {"deleted": creature_id}


def seed():
    example = BASE / "example_creature.json"
    if example.exists() and not any(DATA.glob("*.json")):
        save(json.loads(example.read_text(encoding="utf-8")))


seed()


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/world.html")


app.mount("/", StaticFiles(directory=FRONTEND), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)

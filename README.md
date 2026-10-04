# StromHacks2026

A creature farm: draw a creature, give it a name and personality, then watch it wander around the island.

## Run locally

You need Python 3.9 or newer. Open a terminal in this project folder and run these commands the first time:

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows, activate the environment with `venv\Scripts\activate` instead.

Copy `.env.example` to `.env` and fill it in. You need:

- **TiDB** (`TIDB_HOST`, `TIDB_USER`, `TIDB_PASSWORD`): accounts and creatures are stored there. Create a free TiDB Cloud cluster, press **Connect**, and copy the host, user and password. The server creates the database and tables on its first start.
- **`SESSION_SECRET`**: any long random string, used to sign login cookies.
- **`GEMINI_API_KEY`** and **`ELEVENLABS_API_KEY`**: optional. Without them, creatures still save with rule-based animations and no voice clip.

Then start the local server:

```bash
python server.py
```

Open [http://localhost:8000](http://localhost:8000), sign up, and you land on your own farm (with one starter creature). The world page links to the drawing page, and a submitted creature is saved to your account and appears in the world. Each account only sees its own creatures. Stop the server with `Ctrl+C`.

Run `source venv/bin/activate` again in a new terminal before starting the server. If port 8000 is already in use, change the port in `server.py`.

## Pages and files

- `frontend/login.html` — sign up and log in.
- `frontend/friends.html` — your friend code, add friends by code, and remove friends.
- `frontend/draw-creature.html` — draw a creature and submit it to the server.
- `frontend/world.html` — view, animate, and manage saved creatures.
- `server.py` — local web server, accounts, and creature API.
- `db.py` — TiDB tables (`users`, `creatures`, `friendships`, `battles`) and queries.
- `auth.py` — password hashing and signed login cookies.
- `gemini.py`, `elevenlabs.py` — part roles and animations, and each creature's voice clip.
- `migrate_json.py` — moves creatures saved as JSON files (before TiDB) into an account.
- `rig.py` — connects strokes with parent links and swing pivots when a creature is saved.
- `data/audio/` — created automatically; stores each creature's voice clip.
- `CREATURE_SPEC.md` — creature JSON format (v3).
- `example_creature.json` — starter creature every new account gets.

The server serves only files inside `frontend/`; `.env` and saved data are not exposed as website files. When a creature is saved, the server rigs it, asks Gemini for part roles and animations (falling back to simple rules if Gemini is unavailable), and makes its voice clip with ElevenLabs. Nearby creatures greet when they come within range: they face each other, play an idle, say their sound when available, pause, then wander off. Individual and world-wide cooldowns keep greetings occasional, and pathing keeps their outlines apart.

## Troubleshooting

- If `python3` is not found, try `python`.
- If the page is blank, check the terminal for a server error and refresh the browser.
- If you change a page and do not see the update, hard refresh (`Cmd+Shift+R` on macOS or `Ctrl+Shift+R` on Windows/Linux).
- If the server stops with "TiDB is not configured", fill in the `TIDB_` lines in `.env`.
- To move creatures from the old JSON files into your account: sign up first, then run `python migrate_json.py <your username>`.

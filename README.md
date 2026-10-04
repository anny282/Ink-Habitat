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

Then set up your keys (next section) and start the server (the section after).

## Set up the API keys

All settings live in a file called `.env` in the project folder. Git ignores it, so your keys and passwords never get committed; never paste them into any other file.

### 1. Make your `.env`

```bash
cp .env.example .env
```

It already points at the team's shared TiDB cluster (next step), so most lines are filled in. Open `.env` and write each value right after the `=`, with no spaces and no quotes.

### 2. Database: the team's shared TiDB cluster (default)

Everyone uses the same cluster, so accounts, friends, creatures and battles are shared. The host, port, user and database name are already in `.env.example`:

```
TIDB_HOST=gateway01.us-east-1.prod.aws.tidbcloud.com
TIDB_PORT=4000
TIDB_USER=3P1dKMr5gGwmeJs.root
TIDB_DATABASE=creature_farm
```

The only thing missing is **`TIDB_PASSWORD`**. Ask Anny for it; it's sent privately and never committed, because this repo is public and the password gives full access to the database. Paste it after `TIDB_PASSWORD=`.

Also set **`SESSION_SECRET`** to any long random string (it signs login cookies). Make one with:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### 3. Gemini and ElevenLabs: your own keys (optional)

Each person can use their own keys. Free limits are per key, so separate keys mean more room for everyone. Without them, creatures still save, just with simple animations, attack 5 and no sound.

- **`GEMINI_API_KEY`**: go to [Google AI Studio](https://aistudio.google.com/apikey), sign in with a Google account, press **Create API key**, and copy it. Gemini picks each creature's part roles, animations and attack. The free tier allows about 20 creatures a day per model.
- **`ELEVENLABS_API_KEY`**: sign up at [elevenlabs.io](https://elevenlabs.io), open your profile menu, go to **API Keys**, press **Create API Key** (give it Text to Speech access), and copy it. ElevenLabs makes each creature's voice clip.

```
GEMINI_API_KEY=AIzaSy...your key...
ELEVENLABS_API_KEY=sk_...your key...
```

To switch to different keys later, replace these two lines and restart the server. Only the server that saves a creature uses them, so for a demo on one laptop, that laptop's keys are the ones that count.

### 4. Restart and check

If the server is already running, restart it (`Ctrl+C`, then `python server.py`); settings are only read when it starts. Then draw a creature and watch the terminal: `[gemini] answered by ...` means Gemini worked, and `[gemini] falling back to rules: ...` says why it didn't (usually a wrong key or the free daily limit). If the server stops with "TiDB is not configured", a `TIDB_` line is empty or misspelled.

### Use a different TiDB cluster

For example your own cluster for testing, or if the shared one is replaced:

1. Sign up at [tidbcloud.com](https://tidbcloud.com) and create a free **Serverless** cluster.
2. Open the cluster, press **Connect**, choose **Connect With: General** (or PyMySQL), and press **Generate Password**. Copy the password now; it's shown only once.
3. In `.env`, replace `TIDB_HOST`, `TIDB_PORT`, `TIDB_USER` and `TIDB_PASSWORD` with the new values. Keep `TIDB_DATABASE=creature_farm` (or pick any name).
4. Restart the server. It creates the database and tables on its first start.

A new cluster starts empty: accounts, friends and creatures from the old one don't come with it, and people on different clusters can't add each other or battle. To change the shared cluster for the whole team, update the four values in `.env.example`, commit that (never the password), and send everyone the new password privately.

## Start the server


```bash
python server.py
```

Open [http://localhost:8000](http://localhost:8000), sign up, and you land on your own farm (with one starter creature). The world page links to the drawing page, and a submitted creature is saved to your account and appears in the world. Each account only sees its own creatures. Stop the server with `Ctrl+C`.

Run `source venv/bin/activate` again in a new terminal before starting the server. If it stops with "Address already in use", an older copy is still running (for example in a terminal you closed); stop it with `lsof -ti tcp:8000 | xargs kill` and start again.

## Battling a friend

Add each other on the Friends page with your friend codes. When your friend is online, press **Battle**: they get a pop-up on their farm or friends page. You both secretly pick 3 creatures (60 seconds), watch the same battle at the same time, and the winner takes one creature from the loser's team (30 seconds to choose, then one is picked at random). Each player needs at least 3 creatures. Closing the tab for more than 10 seconds during a battle counts as a loss.

To try it on one computer, use two different browsers (or a normal and a private window) logged in as two accounts.

### Battling on two laptops

Live battles happen inside one running server, so both players must open the **same** server. Running `python server.py` on both laptops shares accounts and farms (same TiDB) but not battles. On the same Wi-Fi:

1. On the laptop that hosts, add `HOST=0.0.0.0` to `.env` and start the server. It prints an address like `http://192.168.1.23:8000`.
2. On the other laptop, open that address instead of `localhost:8000` and log in.
3. If it doesn't load, the host's firewall may be blocking it (macOS asks "accept incoming connections?" the first time; press **Allow**), or the Wi-Fi blocks devices from seeing each other (common on public and school networks; use a phone hotspot instead).

Only use `HOST=0.0.0.0` on a network you trust: anyone on that Wi-Fi can open the site.

## Pages and files

- `frontend/login.html` — sign up and log in.
- `frontend/friends.html` — your friend code, add friends by code, and remove friends.
- `frontend/battle.html` — live battles with a friend (`?room=<id>`: waiting room, secret picks, synced replay, prize pick), practice battles and the replay. Pick 3 creatures from your farm (or Random) to fight 3 random ones; you need at least 3. `?sample` plays the hand-written log in `frontend/sample-battle.json`; `&at=12.5` opens paused at that second; `&side=b` watches from the other side.
- `frontend/live.js` — battle invite pop-ups on the farm and friends pages.
- `frontend/draw-creature.html` — draw a creature and submit it to the server.
- `frontend/world.html` — view, animate, and manage saved creatures.
- `server.py` — local web server, accounts, and creature API.
- `db.py` — TiDB tables (`users`, `creatures`, `friendships`, `battles`) and queries.
- `auth.py` — password hashing and signed login cookies.
- `gemini.py`, `elevenlabs.py` — part roles and animations, and each creature's voice clip.
- `remeasure_sizes.py` — re-measures `battle.size` for every saved creature after the size formula changes: `python remeasure_sizes.py` shows the changes, `--apply` saves them.
- `migrate_json.py` — moves creatures saved as JSON files (before TiDB) into an account.
- `rooms.py` — live battles over Socket.IO: invites, one room per battle, secret picks, the shared replay start, disconnects and forfeits, the prize pick, and the end-of-battle transaction. Battle state is kept in memory, so run a single server process.
- `battle.py` — battle engine: `run_battle(teamA, teamB, seed)` turns two teams of 3 into a battle log (spec, "Battle log"). Same teams and seed, same log.
- `battle_sim.py` — balance simulator for the engine's numbers: `python battle_sim.py`.
- `test_battle.py` — engine checks: `python test_battle.py`.
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

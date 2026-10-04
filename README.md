# StromHacks2026

A creature farm: draw a creature, give it a name and personality, then watch it wander around the island. Add friends, visit their farms, and battle them with teams of 3.

## Run locally

You need Python 3.9 or newer. In Terminal, go to the project folder (for example, `cd ~/Desktop/StromHacks2026`) and run these commands once:

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows, activate the environment with `venv\Scripts\activate` instead.

If you already made the virtual environment and then pulled a project update, activate it and run `python -m pip install -r requirements.txt` again. This installs any dependencies added by the update; you do not need to recreate the environment.

Then set up the local settings file below, and start the server.

## Set up local settings

The server reads its settings from `.env` in the project folder. `.env.example` is the shareable template; `.env` is your private local copy and is ignored by Git. Keep passwords and API keys in `.env`, and never commit or share that file.

### 1. Create or open `.env`

The `cp` command means “copy”: it makes a new `.env` file from the template. Run it only if you do not already have `.env`:

```bash
cp .env.example .env
```

If `.env` already exists, **do not run that command**; open your existing `.env` instead, so you do not overwrite your local settings. Edit values directly after `=`. Do not add spaces around `=`. Quotes are not needed for the values in this file.

On macOS, `.env` is hidden because its name starts with a dot. To open it in TextEdit from Terminal, run:

```bash
cd ~/Desktop/StromHacks2026
open -e .env
```

If Terminal says `.env` does not exist, create it from the template and then open it:

```bash
cp .env.example .env
open -e .env
```

You can also reveal hidden files in Finder by pressing **Command + Shift + .** (period) while viewing the project folder.

### 2. Database: the team's shared TiDB cluster (default)

Everyone uses the same cluster, so accounts, friends, creatures and battles are shared. The host, port, user and database name are already in `.env.example`:

```
TIDB_HOST=gateway01.us-east-1.prod.aws.tidbcloud.com
TIDB_PORT=4000
TIDB_USER=3P1dKMr5gGwmeJs.root
TIDB_DATABASE=creature_farm
```

The required database setting is **`TIDB_PASSWORD`**. Ask Anny to send it privately, then paste it after `TIDB_PASSWORD=`. Do not put it in chat, code, or a committed file. If the team no longer uses this shared database, follow [Use a different TiDB cluster](#use-a-different-tidb-cluster) instead.

Set **`SESSION_SECRET`** to a long random string so login sessions survive server restarts. Make one with:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Copy the printed text into `.env` after `SESSION_SECRET=`. If you leave it blank, the site can still run, but everyone will be logged out whenever the server restarts.

### 3. Optional AI and voice keys

These keys are optional: without them, the server still runs and saves creatures, but Gemini-generated animation details and ElevenLabs voice clips are unavailable. Each person can use their own keys; free usage limits apply to the account that owns each key.

- **`GEMINI_API_KEY`**: go to [Google AI Studio](https://aistudio.google.com/apikey), sign in with a Google account, press **Create API key**, and copy it. Gemini picks each creature's part roles, animations and attack. The free tier allows about 20 creatures a day per model.
- **`ELEVENLABS_API_KEY`**: sign up at [elevenlabs.io](https://elevenlabs.io), open your profile menu, go to **API Keys**, press **Create API Key** (give it Text to Speech access), and copy it. ElevenLabs makes each creature's voice clip.

```
GEMINI_API_KEY=AIzaSy...your key...
ELEVENLABS_API_KEY=sk_...your key...
```

To switch to different keys later, replace these two lines and restart the server. Only the server that saves a creature uses them, so for a demo on one laptop, that laptop's keys are the ones that count.

### 4. Start the server

In the project folder, with the virtual environment activated, run:

```bash
python server.py
```

Open [http://localhost:8000](http://localhost:8000) and sign up or log in. If the server is already running after you edit `.env`, stop it with `Ctrl+C` and start it again; settings are read at startup. The terminal message `[gemini] answered by ...` means Gemini worked. `[gemini] falling back to rules: ...` means it used built-in animation rules instead.

Stop the server with `Ctrl+C`. Run `source venv/bin/activate` again in a new terminal before starting the server. If it stops with "Address already in use", an older copy is still running (for example in a terminal you closed); stop it with `lsof -ti tcp:8000 | xargs kill` and start again.

### Use a different TiDB cluster

For example your own cluster for testing, or if the shared one is replaced:

1. Sign up at [tidbcloud.com](https://tidbcloud.com) and create a free **Serverless** cluster.
2. Open the cluster, press **Connect**, choose **Connect With: General** (or PyMySQL), and press **Generate Password**. Copy the password now; it's shown only once.
3. In `.env`, replace `TIDB_HOST`, `TIDB_PORT`, `TIDB_USER` and `TIDB_PASSWORD` with the new values. Keep `TIDB_DATABASE=creature_farm` (or pick any name).
4. Restart the server. It creates the database and tables on its first start.

A new cluster starts empty: accounts, friends and creatures from the old one don't come with it, and people on different clusters can't add each other or battle. To change the shared cluster for the whole team, update the four values in `.env.example`, commit that (never the password), and send everyone the new password privately.

## Using the app

After signing in, you land on your farm with a starter creature. The world opens in Grasslands; use the scene menu to switch to Desert or Ocean. New creatures start in Grasslands. Open **Creatures** to move a creature to one scene or remove it from the world; this does not delete it. On the Friends page, choose **Visit** to view a friend's creatures in their scenes; creatures removed from the world are not shown. Creatures, accounts and scene assignments are stored in the configured TiDB database.

## Battling a friend

Add each other on the Friends page with your friend codes. Then open **Battle** from the farm: it lists your friends and whether they are online, drawing, or offline. Press **Battle** next to an online friend; they get a pop-up on whatever page they have open. Each player needs at least 3 creatures.

1. You both secretly pick 3 creatures (60 seconds). They fight in the order you pick them.
2. Each of you flips one of 3 face-down buff cards: 2 help your team and 1 hurts it (for example +6 hp, or attacks 4% slower). Locking in late still leaves 15 seconds for the card; if time runs out, one is picked at random.
3. You both watch the same battle at the same time, with each side's card shown during the countdown and on the hp panel.
4. The winner takes one creature from the loser's team (30 seconds to choose, then one is picked at random).
5. All 6 creatures that fought sleep for 1 minute: they can't battle, and they stand still on the farm with a "sleeping" tag.

Closing the tab for more than 10 seconds during a battle counts as a loss. **Practice vs computer** on the Battle page runs the same battles (with cards) against 3 random creatures from your own farm; practice saves nothing and doesn't make creatures sleep.

To try it on one computer, use two different browsers (or a normal and a private window) logged in as two accounts.

### Battling on two laptops

Live battles happen inside one running server, so both players must open the **same** server. Running `python server.py` on both laptops shares accounts and farms (same TiDB) but not battles. On the same Wi-Fi:

1. On the laptop that hosts, add `HOST=0.0.0.0` to `.env` and start the server. It prints an address like `http://192.168.1.23:8000`.
2. On the other laptop, open that address instead of `localhost:8000` and log in.
3. If it doesn't load, the host's firewall may be blocking it (macOS asks "accept incoming connections?" the first time; press **Allow**), or the Wi-Fi blocks devices from seeing each other (common on public and school networks; use a phone hotspot instead).

Only use `HOST=0.0.0.0` on a network you trust: anyone on that Wi-Fi can open the site.

## Project layout

```
server.py      start the server: python server.py
backend/       the server's code (Python)
frontend/      the web pages, served as they are
scripts/       tools you run by hand
tests/         checks for the battle engine
assets/        the starter creature and sample creatures
docs/          the creature and battle log format
data/          made by the server on this laptop (not in Git)
```

`backend/` (importing anything from it loads `.env` first):

- `app.py` — the web app: accounts, creatures, friends and practice battle API, voice clips, and the login redirect. Serves only the files in `frontend/`, so `.env` and saved data are never exposed.
- `creatures.py` — building a new creature: checking the drawing, measuring its battle size, and its random voice and personality.
- `auth.py` — passwords and signed login cookies.
- `db.py` — every TiDB query: users, creatures and their voice clips, friends, battles.
- `rooms.py` — live battles over Socket.IO (invites, picks, buff cards, prize, after-battle sleep) and who is online.
- `battle.py` — the battle engine: a pure function from two teams, their buff cards and a seed to a battle log. All battle and buff card numbers live here.
- `rig.py` — connects strokes with parent links and swing pivots when a creature is saved.
- `gemini.py` — asks Gemini for part roles, animations and attack (falls back to simple rules without a key).
- `elevenlabs.py` — makes each creature's voice clip.

`frontend/`:

- `login.html` — sign up and log in.
- `world.html` — your farm: view, animate and manage creatures across Grasslands, Desert and Ocean; `?visit=<friend id>` shows a friend's farm.
- `draw-creature.html` — draw a creature and submit it to the server.
- `friends.html` — your friend code, add or remove friends, visit their farms.
- `battle.html` — the Battle page: friends to invite and practice; `?room=<id>` is a live battle (picks, buff cards, synced replay, prize); `?practice` is a practice battle; `?sample` plays the hand-written log in `sample-battle.json` (`&at=12.5` opens paused at that second, `&side=b` watches from the other side).
- `live.js` — online status and battle invite pop-ups on every page.
- `scenes/` — the three scenes' shapes and scenery.

Other folders:

- `assets/example_creature.json` — starter creature every new account gets.
- `assets/test-creatures/` — sample creatures for `scripts/migrate_json.py`.
- `docs/CREATURE_SPEC.md` — creature JSON format (v3) and the battle log format.
- `data/audio/` — where voice clips were saved before they moved into TiDB. New clips are stored in TiDB, so every laptop's server can play them.

Tools (run from the project folder with the virtual environment active):

- `python -m tests.test_battle` — checks for the battle engine.
- `python -m scripts.battle_sim` — fights thousands of battles and prints win rates, to tune `backend/battle.py` (sizes, attack and every buff card).
- `python -m scripts.migrate_json <username>` — moves creatures from the old JSON files into an account.
- `python -m scripts.upload_audio` — copies the voice clips in this laptop's `data/audio/` into TiDB. Run it once on each laptop that ran the server before clips moved into TiDB; it's safe to run again.
- `python -m scripts.remeasure_sizes` — re-measures every creature's battle size with the current formula (add `--apply` to save).

When a creature is saved, the server rigs it, asks Gemini for part roles and animations, and makes its voice clip with ElevenLabs. Nearby creatures greet when they come within range: they face each other, play an idle, say their sound when available, pause, then wander off. Individual and world-wide cooldowns keep greetings occasional, and pathing keeps their outlines apart.

## Troubleshooting

- If `python3` is not found, try `python`.
- If the page is blank, check the terminal for a server error and refresh the browser.
- If you change a page and do not see the update, hard refresh (`Cmd+Shift+R` on macOS or `Ctrl+Shift+R` on Windows/Linux).
- If a creature is silent and the terminal shows `GET /audio/... 404`, its clip was made on another laptop before clips moved into TiDB: run `python -m scripts.upload_audio` on that laptop.
- If startup says "TiDB is not configured", check that `TIDB_HOST`, `TIDB_USER`, and `TIDB_PASSWORD` in `.env` are filled in correctly.
- If the server cannot connect to TiDB, confirm the password and cluster details with the person who provided them, and check your internet connection.
- If Python reports `ModuleNotFoundError` for a package such as `socketio`, activate `venv` and run `python -m pip install -r requirements.txt` from the project folder, then restart the server.
- To move creatures from the old JSON files into your account: sign up first, then run `python -m scripts.migrate_json <your username>`.

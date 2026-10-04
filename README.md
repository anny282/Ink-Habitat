# StromHacks2026

A creature farm: draw a creature, give it a name and personality, then watch it wander around the island.

## Run locally

You need Python 3.9 or newer. Open a terminal in this project folder and run these commands the first time:

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows, activate the environment with `venv\Scripts\activate` instead. Then start the local server:

```bash
python server.py
```

Open [http://localhost:8000](http://localhost:8000). The world opens in Grasslands; use the scene menu to switch to Desert or Ocean. New creatures start in Grasslands. Open **Creatures** to move each creature to one scene or take it out of the world. These scene assignments are saved locally and do not delete the creature. Stop the server with `Ctrl+C`.

Run `source venv/bin/activate` again in a new terminal before starting the server. If port 8000 is already in use, change the port in `server.py`.

## Pages and files

- `frontend/draw-creature.html` — draw a creature and submit it to the server.
- `frontend/world.html` — view, animate, and manage saved creatures across Grasslands, Desert, and Ocean.
- `server.py` — local web server and creature storage API.
- `rig.py` — connects strokes with parent links and swing pivots when a creature is saved.
- `data/creatures/` — created automatically; stores saved creature JSON files.
- `CREATURE_SPEC.md` — creature JSON format (v2).
- `example_creature.json` — example creature loaded on a fresh run.

The server serves only files inside `frontend/`; `.env` and saved data are not exposed as website files. The server rigs each creature as it is saved. Until Gemini role labels are available, attached unlabeled strokes get a gentle default swing. Gemini animation details and ElevenLabs audio generation are not configured yet. Nearby creatures greet when they come within range: they face each other, play an idle, say their sound when available, pause, then wander off. Individual and world-wide cooldowns keep greetings occasional, and pathing keeps their outlines apart.

## Troubleshooting

- If `python3` is not found, try `python`.
- If the page is blank, check the terminal for a server error and refresh the browser.
- If you change a page and do not see the update, hard refresh (`Cmd+Shift+R` on macOS or `Ctrl+Shift+R` on Windows/Linux).
- To start with a fresh creature collection, stop the server and remove the JSON files in `data/creatures/`. The example creature is added again on the next start.

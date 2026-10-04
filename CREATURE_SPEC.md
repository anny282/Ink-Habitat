# Creature JSON Spec (v3)

The contract between the **creation side** (drawing tool, Gemini, ElevenLabs) and the **world side** (rigging, animation, wandering), plus the **battle side** (accounts, battle engine, replay). Don't change field names without telling each other.

## What changed from v2

- `version` is now `3`.
- New top-level `drawnBy`: who drew the creature. It never changes, even when the creature is won by another player. (The current owner is a database column, not part of the JSON.)
- New `battle` object: `size` (measured by the drawing tool), `baseAttack` (picked by Gemini), and `wins` (counted by the server).
- New **Battle log** section: the format the battle engine outputs and the replay scene plays.
- The farm/world code can ignore `drawnBy` and `battle`, except for showing a crown when `battle.wins > 5`.
- Old v2 creatures are upgraded on load: `drawnBy: null`, `battle: { "size": 40, "baseAttack": 5, "wins": 0 }`.

## What changed from v1

- User input is now four textboxes: name (required), movement, two behaviours, sound (all optional except name).
- `click` is now `sound`, and it is used for both clicking and occasional random speaking. If the user leaves it blank, the creature is silent.
- Personality is now just three features with solid, concrete values (no 0 to 1 numbers).
- The body is a fixed anchor: it never animates. Only the other parts move.
- Parts have a `moves` flag, and `roll` is removed as a locomotion type.
- **Personality and voice are generated randomly by code, not by the AI.** Gemini only decides part roles, `moves`, locomotion, and the two idles.

## Rules of the road

- **Coordinates:** creature-local space. Origin `(0,0)` is the center of the body. `x` right, `y` down. The drawing tool normalizes the drawing to fit roughly a 200 x 200 box around the origin.
- **Angles** in degrees, **frequencies** in Hz, **phase** 0 to 1.
- **The world never trusts the AI.** Every number is clamped using the table at the bottom. Missing or invalid fields fall back to defaults.
- Max **8 parts** (1 body + up to 7 others).

## The user's textboxes

| Box | Required | Limit | Used for |
|---|---|---|---|
| Name | **yes** | 1 to 16 chars (suggested) | shown above the creature's head in the world |
| How it moves | no | free text | AI picks `locomotion` and `gait` |
| Behaviour 1 | no | free text | AI turns it into `idles[0]` |
| Behaviour 2 | no | free text | AI turns it into `idles[1]` |
| Sound | no | **under 20 chars (max 19)** | the text it says. Real words ("hi there") or nonsense ("diwneh") both work. Blank = silent creature. |

The UI turns empty textboxes into `null`. If movement or a behaviour is `null`, the AI invents one (that's part of the fun). If sound is `null`, nothing is invented: the creature stays silent.

## Full shape

```json
{
  "version": 3,
  "id": "string (uuid)",
  "createdAt": "ISO date string",
  "drawnBy": { "userId": "string", "name": "anny" },

  "settings": {
    "name": "Sir Noodle",
    "movement": "waddles proudly",
    "behaviours": ["bows dramatically", null],
    "sound": "Kneel!"
  },

  "bounds": { "minX": -60, "minY": -75, "maxX": 100, "maxY": 85 },

  "parts": [
    {
      "id": "p0",
      "points": [[x, y], [x, y]],
      "color": "#rrggbb",
      "width": 6,
      "parent": null,
      "pivot": [0, 0],
      "role": "body",
      "moves": false,
      "z": 0
    }
  ],

  "locomotion": {
    "type": "walk",
    "gait": [
      { "part": "p1", "rotate": { "amp": 25, "freq": 2, "phase": 0 } }
    ]
  },

  "idles": [
    { "name": "string", "source": "user text or 'invented'", "duration": 2.5, "tracks": [] },
    { "name": "string", "source": "user text or 'invented'", "duration": 2.0, "tracks": [] }
  ],

  "sound": {
    "text": "Kneel!",
    "voice": {
      "voiceId": "string",
      "stability": 0.4,
      "style": 0.3,
      "speed": 1.0,
      "playbackRate": 1.0
    },
    "audioUrl": null
  },

  "personality": {
    "restSeconds": 3,
    "speakEverySeconds": 30,
    "speedPxPerSec": 50
  },

  "battle": {
    "size": 42,
    "baseAttack": 6,
    "wins": 0
  }
}
```

If the creature has no sound, set `"sound": null`.

## Field by field

### `settings`
Exactly what the user typed (empty boxes are `null`). `name` is always present. `settings.sound` is the raw input; `sound.text` below is the trimmed version.

### `bounds` (drawing tool)
The bounding box of all parts in local space. The world draws the name label centered at `x = 0`, just above `minY` (for example at `minY - 12`).

### `parts[]`

| Field | Who fills it | Meaning |
|---|---|---|
| `id` | drawing tool | `"p0"`, `"p1"`, ... in draw order |
| `points` | drawing tool | the brush stroke as `[x, y]` pairs, simplified to about 20 points max |
| `color`, `width` | drawing tool | stroke color and thickness |
| `parent` | rigging code | `null` for the body, otherwise the `id` of the part it hangs from. The body is the largest stroke. Every other stroke attaches to the nearest already-attached part. |
| `pivot` | rigging code | point the part rotates around: its end nearest its parent. For the body, always `[0, 0]`. |
| `role` | **AI-filled** | one of: `body`, `head`, `eye`, `leg`, `arm`, `wing`, `tail`, `decoration`. The AI may pick oddly (a leg that is obviously a hat). The code goes with it. |
| `moves` | **AI-filled** | `true` if the part animates, `false` if it just rides along rigidly with its parent. Eyes and decorations are usually `false`, legs, wings and tails usually `true`. |
| `z` | rigging code | draw order inside the creature, lower is behind |

**The body rule:**
- There is exactly one `body`, it has `parent: null`, `pivot: [0,0]`, `moves: false`.
- The body never rotates, scales, or offsets. Animation tracks that target it are ignored.
- The creature's world position **is** the body's position: the world sets the body's `(x, y)` and every other part is placed relative to it.
- Rotating a part carries its whole subtree around its `pivot`.
- Only parts with `moves: true` get animation tracks applied. Tracks on `moves: false` parts are ignored.

### `locomotion` (AI-filled)

How the creature travels while walking to a spot. The body itself stays fixed in local space, so "movement feel" comes from the world code moving the whole creature plus the limbs swinging.

| `type` | World code does | Limbs do |
|---|---|---|
| `walk` | steady travel | `gait` swings |
| `hop` | travel in arcs (up and down) | `gait` swings, or none |
| `slither` | travel with a side-to-side wiggle path | `gait` swings, or none |
| `fly` | travel while floating above the shadow, gentle bob | wings flap via `gait` |
| `scoot` | smooth slide, slight tilt | usually none |

`gait` is an optional list of per-part swings used while moving: `angle = amp * sin(2π * (freq * t + phase))`. Parts not listed get a default from their `role` if `moves` is true (legs alternate, wings flap, tails wag).

Travel speed comes from `personality.speedPxPerSec`, not from `locomotion`.

### `idles[]` (AI-filled, always exactly 2)

Two short animations the creature plays at random when it stops. Index 0 comes from Behaviour 1, index 1 from Behaviour 2. If a box was blank, the AI invents one and marks `source` as `"invented"`.

- `duration`: seconds before the idle ends and the creature rests or wanders again.
- `tracks[]`: each targets one part (never the body). Every channel is optional:
  - `rotate`: `angle = amp * sin(2π * (freq * t + phase))`
  - `scale`: `s = 1 + amp * sin(...)`
  - `offset`: moves the part by `ax * sin(...)` and `ay * sin(...)`

  Each channel carries its own `freq` and `phase`, for example:

  ```json
  { "part": "p3", "rotate": { "amp": 10, "freq": 3, "phase": 0 },
                  "scale":  { "amp": 0.25, "freq": 2, "phase": 0 },
                  "offset": { "ax": 0, "ay": -8, "freq": 2, "phase": 0 } }
  ```

### `sound` (random voice + ElevenLabs)

- `null` if the user left the sound box blank. A silent creature never speaks and clicking it only plays a small reaction animation.
- `text`: the user's sound text, trimmed. Under 20 characters (max 19). No AI involved.
- `voice`: **generated randomly by code at creation time.** The AI never touches it. See below.
- `audioUrl`: starts as `null`. The backend generates the audio **once** and fills this in. The world plays this file when the creature is clicked, and also when its chattiness timer fires. If it's still `null`, show a speech bubble with no audio.

**How the random voice works.** ElevenLabs has no "pitch" setting, so variety comes from three sources: which voice, the voice settings, and a playback trick.

| Field | How it's picked | Effect |
|---|---|---|
| `voiceId` | random pick from a **fixed list of 6 to 8 hardcoded ElevenLabs voices** (mix of deep, bright, raspy, childlike, etc.) | the main source of "sharp vs low" |
| `stability` | random 0.2 to 0.8 | low = more emotional and wobbly, high = flat and steady |
| `style` | random 0 to 0.6 | how exaggerated the delivery is |
| `speed` | random 0.8 to 1.2 | fast or slow talker (sent to ElevenLabs) |
| `playbackRate` | random 0.75 to 1.4 | applied **in the browser** when the audio plays, with pitch preservation turned off (`audio.preservesPitch = false`). Below 1 = deeper and slower, above 1 = squeakier and faster. A cheap way to get cartoony pitch variety. |

`stability`, `style`, and `speed` go into the ElevenLabs request's `voice_settings`. Double-check the exact setting names and allowed ranges in the current ElevenLabs docs and which model supports `style`, since these can change. Because we generate each clip once and cache it, the voice stays the same every time that creature speaks.

### `personality` (random, three features, solid values)

The user does not enter these, and neither does the AI. **The creation code rolls them randomly** when the creature is made, uniformly within the "random range" below, then saves them.

| Feature | Field | Meaning | Random range |
|---|---|---|---|
| **Wanderiness** | `restSeconds` | how long it stays put and does idles between walks. Lower = wanders more. Each walk then lasts a random 2 to 5 seconds in a random direction (world constant, not in the JSON). | 2 to 8 |
| **Chattiness** | `speakEverySeconds` | every this many seconds it says its sound on its own. Deliberately infrequent. Ignored if `sound` is `null`. | 20 to 60 |
| **Speed** | `speedPxPerSec` | how fast it moves while walking, in pixels per second | 30 to 100 |

Use whole numbers for all three. The wider clamp ranges in the table below still apply as a safety net.

### `drawnBy` (server)

`{ "userId", "name" }` of the account that drew the creature, set by the server at creation time from the logged-in user. It never changes. When a creature is won in battle, only its owner in the database changes, so the farm can show "drawn by anny" on a creature someone else now owns. `null` for creatures made before accounts existed.

### `battle` (three fields, three owners)

| Field | Who fills it | Meaning | Range |
|---|---|---|---|
| `size` | **drawing tool** | How big the drawing was on the canvas **before** normalizing. `100 * sqrt(inkW * inkH) / 500`, where `inkW` x `inkH` is the bounding box of all strokes in the 500 x 500 logical canvas. A doodle in the corner is small, a drawing that fills the page is near 100. Whole number. | 5 to 100 |
| `baseAttack` | **AI-filled** | How strong its attacks look: claws, teeth, horns, spikes and a fierce name push it up, round soft shapes push it down. Whole number. | 1 to 10 |
| `wins` | **server** | Battles this creature was on the winning team for. Starts at 0, only the server increments it. More than 5 wins shows a crown. | 0 and up |

`size` and `baseAttack` are raw stats. The battle engine turns them into fighting numbers (hp, damage, attack speed) with formulas that live in the engine code, so they can be tuned without changing saved creatures. The intent: bigger creatures have more hp but attack slower, smaller ones have less hp but attack faster.

## Clamp table (world side always applies)

| Field | Min | Max | Default |
|---|---|---|---|
| `settings.name` length | 1 | 16 | n/a (required) |
| `sound.text` length | 1 | 19 | n/a |
| `parts` length | 1 | 8 | n/a |
| `rotate.amp` | 0 | 60 | 15 |
| `scale.amp` | 0 | 0.4 | 0.1 |
| `offset.ax`, `offset.ay` | -30 | 30 | 0 |
| `freq` | 0.2 | 4 | 1 |
| `phase` | 0 | 1 | 0 |
| `idle.duration` | 1 | 5 | 2 |
| `restSeconds` | 1 | 10 | 3 |
| `speakEverySeconds` | 15 | 90 | 30 |
| `speedPxPerSec` | 20 | 150 | 50 |
| `voice.stability` | 0 | 1 | 0.5 |
| `voice.style` | 0 | 1 | 0.3 |
| `voice.speed` | 0.7 | 1.2 | 1 |
| `voice.playbackRate` | 0.5 | 2 | 1 |
| `battle.size` | 5 | 100 | 40 |
| `battle.baseAttack` | 1 | 10 | 5 |
| `battle.wins` | 0 | n/a | 0 |

## Data flow

1. **Drawing tool** collects `settings` from the textboxes and outputs `parts` (points, color, width), `bounds`, and `battle.size` (measured before normalizing).
2. **Rigging code** fills `parent`, `pivot`, `z`.
3. **Gemini call** gets `settings` plus a summary of the parts (size, position relative to the body, orientation), and returns JSON only: each part's `role` and `moves`, then `locomotion`, `idles` and `battle.baseAttack`. That's all it decides.
4. **Backend** validates and clamps the Gemini response, then fills in the rest with plain code: `sound.text` (from the user's input, or `sound: null`), a random `personality`, a random `voice`, `drawnBy` from the logged-in account, and `battle.wins: 0`.
5. **Backend** generates the audio once if `sound` isn't null, using the random voice, fills `audioUrl`, and saves.
6. **World** loads creatures and runs them with no further AI calls. Each creature loops: rest (play a random idle) for `restSeconds`, walk to a random spot, repeat. Separately, a timer plays its sound every `speakEverySeconds`, at its `playbackRate`.

## Who owns what

- **Person A (creation side):** textboxes and `settings`, `parts[].points/color/width`, `bounds`, `battle.size`, the Gemini call (roles, `moves`, locomotion, idles, `baseAttack`), the random personality and random voice rolls, and audio generation and `audioUrl`.
- **Person B (world side):** rigging (`parent`, `pivot`, `z`), `locomotion` and `idles` playback, wander loop, name label, click and speak behavior (including applying `playbackRate`), and the clamp table. In v3, also the crown for creatures with `battle.wins > 5`.
- **Person A (battle side, v3):** accounts and database, `drawnBy`, friends, the battle engine and battle log, battle rooms, prize transfer and `wins`, and (unless Person B takes it) the 2D replay scene.

`example_creature.json` is a hand-written creature in this format for Person B to build against. Person A should make the drawing tool output the same shape.

## Battle log (v3)

The battle engine is a **pure function**: `run_battle(teamA, teamB, seed) -> log`. The same teams and the same seed always give the exact same log. The server runs it once, saves the log, and sends it to both players. Clients never simulate; they only play the log back.

### Battle rules (summary)

- Each side brings **exactly 3** creatures, in the order they picked them. A player with fewer than 3 creatures can't battle yet. The engine rejects any team that isn't exactly 3. One creature per side is on the field at a time.
- Both creatures attack on their own timers, at the same time. Each attack can hit, miss or crit (seeded randomness).
- When a creature faints, that side's next creature enters. The survivor stays in **with the hp it has left**.
- The battle ends when one side has no creatures left (`knockout`), when a player disconnects (`forfeit`), or after 2 minutes (120 seconds, `timeout`). On timeout, the side with the larger share of its total hp left wins; equal shares are a `draw`.
- The exact numbers (hp, damage, attack speed from `size` and `baseAttack`, miss and crit chance) live in the engine code and are tuned with the simulator.

### Shape

```json
{
  "version": 1,
  "battleId": "string",
  "seed": 192837465,
  "startAt": "ISO date string: when both players start the replay",
  "duration": 41.6,

  "sides": {
    "a": { "userId": "u1", "name": "anny",
           "team": [ { "creature": "c1", "name": "Sir Noodle", "size": 42, "baseAttack": 6, "maxHp": 120 } ] },
    "b": { "userId": "u2", "name": "jade",
           "team": [ { "creature": "c7", "name": "Chicken", "size": 75, "baseAttack": 3, "maxHp": 180 } ] }
  },

  "events": [
    { "t": 0.0, "type": "enter",  "side": "a", "slot": 0, "creature": "c1", "hp": 120 },
    { "t": 0.0, "type": "enter",  "side": "b", "slot": 0, "creature": "c7", "hp": 180 },
    { "t": 1.2, "type": "attack", "side": "a", "creature": "c1", "target": "c7" },
    { "t": 1.5, "type": "hit",    "side": "b", "creature": "c7", "by": "c1", "damage": 14, "crit": false, "hp": 166 },
    { "t": 2.0, "type": "attack", "side": "b", "creature": "c7", "target": "c1" },
    { "t": 2.3, "type": "miss",   "side": "a", "creature": "c1", "by": "c7" },
    { "t": 9.8, "type": "faint",  "side": "b", "creature": "c7" },
    { "t": 41.6, "type": "end", "winner": "a", "reason": "knockout" }
  ],

  "result": { "winner": "a", "reason": "knockout" },
  "prize": { "creature": "c7", "pickedBy": "winner" }
}
```

- `a` is the player who sent the invite, `b` is the one who accepted. The replay always draws the **viewer's** side on the left and mirrors the opponent on the right.
- `sides.*.team` always has exactly 3 entries (the example shows one each to stay short). It is a snapshot of the stats at battle time, so the replay and old battles don't change if a creature's stats change later. The replay loads each creature's drawing by its id.
- `t` is seconds from `startAt`, rounded to 0.01. Events are sorted by `t`. Events with the same `t` play in list order.

### Events

| `type` | Fields | Replay does |
|---|---|---|
| `enter` | `side`, `slot` (index in the team), `creature`, `hp` | creature walks in from its edge; hp bar shows `hp` out of `maxHp` |
| `attack` | `side`, `creature` (attacker), `target` | attacker dashes toward the target and back |
| `hit` | `side` and `creature` (**the target**), `by`, `damage`, `crit`, `hp` (after the hit) | target shakes, hp bar drops to `hp`, bigger effect if `crit` |
| `miss` | `side` and `creature` (**the target**), `by` | target dodges, "miss" text |
| `faint` | `side`, `creature` | creature falls over and fades out |
| `end` | `winner` (`"a"`, `"b"` or `"draw"`), `reason` (`knockout`, `timeout`, `forfeit`) | victory moment |

The `hit` or `miss` for an attack always comes 0.3 seconds after its `attack`, so the dash lands on time.

### After the battle

- `result` repeats the `end` event so the server and the lobby can read it without scanning `events`.
- `prize`: the winner picks one creature from the **loser's battle team** within 30 seconds. If they don't, the server picks one at random and sets `pickedBy: "auto"`. `null` for a draw, and `null` until the pick is made.
- In **one database transaction**, the server moves the prize creature to the winner (its `drawnBy` stays the same), adds 1 to `battle.wins` for every creature on the winning team, and saves the battle record.

# Creature JSON Spec (v2)

The contract between the **creation side** (drawing tool, Gemini, ElevenLabs) and the **world side** (rigging, animation, wandering). Don't change field names without telling each other.

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
  "version": 2,
  "id": "string (uuid)",
  "createdAt": "ISO date string",

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

## Data flow

1. **Drawing tool** collects `settings` from the textboxes and outputs `parts` (points, color, width) and `bounds`.
2. **Rigging code** fills `parent`, `pivot`, `z`.
3. **Gemini call** gets `settings` plus a summary of the parts (size, position relative to the body, orientation), and returns JSON only: each part's `role` and `moves`, then `locomotion` and `idles`. That's all it decides.
4. **Backend** validates and clamps the Gemini response, then fills in the rest with plain code: `sound.text` (from the user's input, or `sound: null`), a random `personality`, and a random `voice`.
5. **Backend** generates the audio once if `sound` isn't null, using the random voice, fills `audioUrl`, and saves.
6. **World** loads creatures and runs them with no further AI calls. Each creature loops: rest (play a random idle) for `restSeconds`, walk to a random spot, repeat. Separately, a timer plays its sound every `speakEverySeconds`, at its `playbackRate`.

## Who owns what

- **Person A (creation side):** textboxes and `settings`, `parts[].points/color/width`, `bounds`, the Gemini call (roles, `moves`, locomotion, idles), the random personality and random voice rolls, and audio generation and `audioUrl`.
- **Person B (world side):** rigging (`parent`, `pivot`, `z`), `locomotion` and `idles` playback, wander loop, name label, click and speak behavior (including applying `playbackRate`), and the clamp table.

`example_creature.json` is a hand-written creature in this format for Person B to build against. Person A should make the drawing tool output the same shape.

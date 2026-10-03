# StromHacks2026

A creature farm, just the creatures seems...

Draw a creature, give it a name, a way of moving, a couple of behaviours and a sound. AI brings it to life, and it joins the farm: wandering around, playing its idle animations, and saying its sound now and then.

## How it works

1. **Draw** a creature and fill in its textboxes in the drawing tool.
2. **Gemini** decides what each stroke is (leg, wing, tail...), how the creature moves, and its two idle animations.
3. **Code** rolls a random personality and voice.
4. **ElevenLabs** voices the creature's sound once.
5. **The world** runs every creature with no further AI calls.

The JSON format that connects all of this is in [CREATURE_SPEC.md](CREATURE_SPEC.md). Read it before changing any field.

## Project structure

| Path | What it is |
|---|---|
| `frontend/draw-creature.html` | the drawing tool |
| `example_creature.json` | a complete, hand-filled creature to build the world against |
| `test-creatures/` | raw drafts straight from the drawing tool |
| `CREATURE_SPEC.md` | the creature JSON spec (v2) |
| `.env.example` | template for the API keys |

## Setup

1. Copy the env template and add your keys:
   ```
   cp .env.example .env
   ```
   `.env` is gitignored. Never commit it.
2. Open `frontend/draw-creature.html` in a browser to try the drawing tool.

## Status

- [x] Creature spec v2
- [x] Drawing tool
- [ ] Rigging (`parent`, `pivot`, `z`)
- [ ] Backend: Gemini call, clamping, random personality and voice
- [ ] ElevenLabs audio
- [ ] World: wandering, animation, speaking

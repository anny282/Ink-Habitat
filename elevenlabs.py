"""ElevenLabs step (spec data flow 5): generate each creature's sound clip once and cache it.

Never raises: if generation fails, audioUrl stays null and the world shows a speech bubble only.
"""
import json
import os
import random
import urllib.error
import urllib.request

API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128"


def clamp(v, lo, hi):
    return min(hi, max(lo, v))


def synthesize(text, voice):
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY is not set")
    body = {
        "text": text,
        "model_id": os.environ.get("ELEVENLABS_MODEL", "eleven_multilingual_v2"),
        "voice_settings": {
            "stability": clamp(voice["stability"], 0, 1),
            "similarity_boost": 0.75,
            "style": clamp(voice["style"], 0, 1),
            "speed": clamp(voice["speed"], 0.7, 1.2),
            "use_speaker_boost": True,
        },
    }
    req = urllib.request.Request(
        API_URL.format(voice_id=voice["voiceId"]),
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Accept": "audio/mpeg", "xi-api-key": key},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return res.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"ElevenLabs HTTP {e.code}: {e.read()[:300]!r}") from e


def generate(creature, audio_dir, voice_ids):
    """Write <audio_dir>/<id>.mp3 and fill sound.audioUrl. Tries one other voice if the first fails."""
    sound = creature.get("sound")
    if not sound:
        return creature
    voices = [sound["voice"]["voiceId"]] + random.sample(
        [v for v in voice_ids if v != sound["voice"]["voiceId"]], k=1)
    for voice_id in voices:
        sound["voice"]["voiceId"] = voice_id
        try:
            audio = synthesize(sound["text"], sound["voice"])
        except Exception as e:  # keep the creature; it just speaks without audio
            print(f"[elevenlabs] voice {voice_id} failed: {e}")
            if "api_key" in str(e).lower():  # bad or missing key: another voice won't help
                break
            continue
        audio_dir.mkdir(parents=True, exist_ok=True)
        (audio_dir / f"{creature['id']}.mp3").write_bytes(audio)
        sound["audioUrl"] = f"/audio/{creature['id']}.mp3"
        break
    return creature

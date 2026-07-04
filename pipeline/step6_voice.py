"""Step 6 (optional): generate narration voice-over with Qwen-TTS.

For each scene's narration line, synthesize speech and save it under
renpy_project/game/voice/<scene>_<idx>.<ext>. Step 5 then emits a Ren'Py
`voice` statement before each narrator line when the file exists.

Resumable: existing voice files are skipped.
"""

import json

from . import config, qwen_client, media_utils


def _sniff_ext(data):
    """Guess audio container from the first bytes (for the raw download)."""
    if data[:4] == b"RIFF":
        return ".wav"
    if data[:4] == b"OggS":
        return ".ogg"
    if data[:3] == b"ID3" or data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return ".mp3"
    return ".mp3"


def voice_path(sid, idx):
    """Return the existing final .ogg voice file for a line, or None."""
    p = config.VOICE_DIR / f"{sid}_{idx}.ogg"
    return p if p.exists() else None


def run(resume=True, voice=None):
    if not config.SCENES_JSON.exists():
        raise SystemExit(f"missing {config.SCENES_JSON}; run step 2 first")
    graph = json.loads(config.SCENES_JSON.read_text(encoding="utf-8"))
    config.VOICE_DIR.mkdir(parents=True, exist_ok=True)

    # Voice the intro lines only (id "intro"); per-scene speech is the
    # character monologue, handled by step_monologue and mixed into clips.
    items = []
    if graph.get("intro", {}).get("narration"):
        items.append(("intro", {"narration": graph["intro"]["narration"]}))

    count = 0
    for sid, scene in items:
        for idx, line in enumerate(scene.get("narration", [])):
            text = str(line).strip()
            if not text:
                continue
            if resume and voice_path(sid, idx):
                print(f"[step6] {sid}_{idx}: voice exists, skipping")
                count += 1
                continue
            print(f"[step6] {sid}_{idx}: TTS ({config.TTS_MODEL}, "
                  f"{voice or config.TTS_VOICE}) ...")
            url = qwen_client.tts(text, voice=voice)
            import requests
            data = requests.get(url, timeout=120).content
            # Qwen streams WAV with a corrupt RIFF size header; transcode to clean
            # .ogg so Ren'Py can play it reliably.
            raw = config.VOICE_DIR / f"{sid}_{idx}_raw{_sniff_ext(data)}"
            raw.write_bytes(data)
            out = config.VOICE_DIR / f"{sid}_{idx}.ogg"
            media_utils.to_ogg(raw, out)
            raw.unlink(missing_ok=True)
            count += 1
            print(f"[step6] {sid}_{idx}: saved {out.name}")

    print(f"[step6] done: {count} voice lines in {config.VOICE_DIR}")


if __name__ == "__main__":
    run()

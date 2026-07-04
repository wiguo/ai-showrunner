"""Monologue stage: give the main character a first-person inner voice.

For each scene, generate 1-2 short first-person inner-monologue lines (the
protagonist's thoughts), then synthesize them in the character voice (Kai) and
concatenate per scene into build/monologue/<sid>_all.ogg. Step 5 mixes that
track into the clip so the character speaks over the video.

Stored in scenes.json as scene["monologue"] = [lines]. Idempotent.
"""

import json

from . import config, qwen_client, media_utils

SYSTEM = ("You write FIRST-PERSON inner monologue for the protagonist of a short "
          "film. These are the character's private thoughts, spoken in their own "
          "voice over each scene - not narration, not addressed to anyone.")


def _instruct(graph):
    chars = graph.get("characters", [])
    who = chars[0]["name"] if chars else "the protagonist"
    scene_lines = []
    for sid, s in graph["scenes"].items():
        scene_lines.append(f'{sid} ({s.get("duration",6)}s): {s.get("summary","")}')
    scenes_block = "\n".join(scene_lines)
    return (
        f"Protagonist: {who}.\n"
        f"Write {who}'s first-person inner monologue for EACH scene below.\n\n"
        f"{scenes_block}\n\n"
        'Return JSON: {"s1": ["line", ...], "s2": [...], ...} with an entry for '
        "every scene id.\n"
        "Rules: 1-2 short sentences per scene (first person, present/past as fits), "
        "must fit being spoken within the scene's seconds (~3 words/second). "
        "Vivid, internal, true to the character. No quotes inside lines, no names "
        "as speaker prefixes, no markdown."
    )


def run(resume=True):
    if not config.SCENES_JSON.exists():
        raise SystemExit(f"missing {config.SCENES_JSON}; run step 2 first")
    graph = json.loads(config.SCENES_JSON.read_text(encoding="utf-8"))
    config.MONO_DIR.mkdir(parents=True, exist_ok=True)

    have_all = all(graph["scenes"][s].get("monologue") for s in graph["scenes"])
    if not (resume and have_all):
        print(f"[mono] generating first-person monologue ({config.LLM_MODEL}) ...")
        result = qwen_client.chat_json(SYSTEM, _instruct(graph))
        for sid, scene in graph["scenes"].items():
            lines = [str(x).strip() for x in result.get(sid, []) if str(x).strip()]
            if lines:
                scene["monologue"] = lines
        config.SCENES_JSON.write_text(json.dumps(graph, indent=2, ensure_ascii=False),
                                      encoding="utf-8")
        print("[mono] wrote monologue lines into scenes.json")

    # Synthesize (character voice) + concat per scene + write synced subtitles.
    import requests
    for sid, scene in graph["scenes"].items():
        lines = scene.get("monologue") or []
        if not lines:
            continue
        parts = []
        for idx, line in enumerate(lines):
            part = config.MONO_DIR / f"{sid}_{idx}.ogg"
            if not (resume and part.exists()):
                print(f"[mono] {sid}_{idx}: TTS ({config.CHAR_VOICE}) ...")
                url = qwen_client.tts(line, voice=config.CHAR_VOICE)
                raw = config.MONO_DIR / f"{sid}_{idx}_raw.wav"
                raw.write_bytes(requests.get(url, timeout=120).content)
                media_utils.to_ogg(raw, part)
                raw.unlink(missing_ok=True)
            parts.append(part)

        combined = config.MONO_DIR / f"{sid}_all.ogg"
        if not (resume and combined.exists()):
            media_utils.concat_audio(parts, combined)
        _write_srt(sid, lines, parts)  # always refresh subtitles
        print(f"[mono] {sid}: audio + subtitles ready")

    print(f"[mono] done: monologue audio in {config.MONO_DIR}")
    return graph


DELAY = 0.3  # must match mux delay_ms (300ms) so subtitles sync to the voice


def _ts(t):
    h = int(t // 3600); m = int((t % 3600) // 60); s = t % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def _write_srt(sid, lines, parts):
    """Write an .srt timed to the spoken lines (start offset by the mux delay)."""
    t = DELAY
    out = []
    for i, (line, part) in enumerate(zip(lines, parts), start=1):
        dur = media_utils.audio_duration(part) or 2.0
        start, end = t, t + dur
        t = end + 0.15
        out.append(f"{i}\n{_ts(start)} --> {_ts(end)}\n{line}\n")
    (config.MONO_DIR / f"{sid}.srt").write_text("\n".join(out), encoding="utf-8")


if __name__ == "__main__":
    run()

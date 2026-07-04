"""Step 2: convert the screenplay into a structured scene graph.

Input : build/script.md
Output: build/scenes.json (the contract consumed by steps 3-5)

Enforces the runtime budget: the main path (start -> next -> ...) should sum to
~TARGET_SECONDS; durations are rescaled/clamped if the model drifts.
"""

import json

from . import config, qwen_client

SCHEMA_HINT = """Produce a JSON object with EXACTLY this shape:

{
  "title": "string",
  "global_style": "one consistent cinematic look applied to every frame prompt",
  "characters": [
    {"id": "snake_case_id", "name": "string",
     "appearance": "fixed detailed visual description",
     "seed": 1111}
  ],
  "start": "s1",
  "scenes": {
    "s1": {
      "summary": "what happens",
      "setting": "where",
      "mood": "tone",
      "characters": ["id", ...],
      "first_frame_prompt": "full text-to-image prompt for the OPENING composition (include style + character appearances)",
      "last_frame_edit": "an edit instruction applied TO the first frame to make the ENDING frame: same character(s), same setting, but now ... (describe the change)",
      "motion_prompt": "camera movement + action for image-to-video",
      "duration": 10,
      "narration": ["one or two short prose lines shown on screen"],
      "next": "s2",
      "choices": [
        {"text": "choice label", "goto": "s2"}
      ]
    }
  }
}

Rules:
- Scene ids are short snake_case tags (e.g. "s1","eng1","sci1","end1"). "start" is the first scene id.
- Every scene has "next" (the id of the following scene) EXCEPT the final scene,
  whose "next" must be null.
- BRANCHING IS ALLOWED. If the screenplay splits into distinct paths (e.g. two
  different job paths), model it as a real branch: a choice scene whose two
  "choices" `goto` DIFFERENT first scenes of each path; each path is its own
  chain of scenes; both paths then "next" into a SHARED ending chain. Set the
  choice scene's own "next" to one of the paths (the representative playthrough).
- Non-choice scenes have no "choices" (omit or empty).
- "main path" = following start -> next -> ... (shared + one representative
  path). Use about {n} scenes on that main path; each "duration" is an integer
  3-15 seconds and the main-path durations must sum to about {target} seconds.
  The alternate branch scenes get their own sensible durations too.
- first_frame_prompt MUST embed global_style and the appearance of any characters
  present, so the look stays consistent across scenes.
"""

SYSTEM = ("You are a meticulous technical director converting a screenplay into "
          "a precise JSON scene graph for an automated video pipeline.")


def run():
    config.ensure_dirs()
    if not config.SCRIPT_MD.exists():
        raise SystemExit(f"missing {config.SCRIPT_MD}; run step 1 first")
    script = config.SCRIPT_MD.read_text(encoding="utf-8")

    hint = (SCHEMA_HINT.replace("{n}", str(config.TARGET_MAIN_SCENES))
                       .replace("{target}", str(config.TARGET_SECONDS)))
    user = f"SCREENPLAY:\n\n{script}\n\n{hint}"

    print(f"[step2] screenplay -> scene graph ({config.LLM_MODEL}) ...")
    graph = qwen_client.chat_json(SYSTEM, user)
    graph = validate_and_fix(graph)

    config.SCENES_JSON.write_text(json.dumps(graph, indent=2, ensure_ascii=False),
                                  encoding="utf-8")
    total = main_path_total(graph)
    print(f"[step2] wrote {config.SCENES_JSON}: "
          f"{len(graph['scenes'])} scenes, main-path {total}s "
          f"({len(main_path(graph))} on main path)")
    return graph


def main_path(graph):
    """Ordered list of scene ids following start -> next."""
    order, sid, seen = [], graph.get("start", "s1"), set()
    scenes = graph["scenes"]
    while sid and sid in scenes and sid not in seen:
        order.append(sid)
        seen.add(sid)
        sid = scenes[sid].get("next")
    return order


def main_path_total(graph):
    return sum(int(graph["scenes"][s].get("duration", config.CLIP_SECONDS_DEFAULT))
               for s in main_path(graph))


def validate_and_fix(graph):
    if "scenes" not in graph or not graph["scenes"]:
        raise qwen_client.QwenError("scene graph has no scenes")
    graph.setdefault("start", "s1")
    graph.setdefault("global_style", "")
    graph.setdefault("characters", [])
    scenes = graph["scenes"]

    # Clamp every duration to the model's [min,max].
    for s in scenes.values():
        d = int(s.get("duration", config.CLIP_SECONDS_DEFAULT))
        s["duration"] = max(config.CLIP_SECONDS_MIN,
                            min(config.CLIP_SECONDS_MAX, d))
        s.setdefault("narration", [])
        s.setdefault("characters", [])

    # Drop choices that point to unknown scenes; keep the graph connected.
    for s in scenes.values():
        if s.get("choices"):
            s["choices"] = [c for c in s["choices"] if c.get("goto") in scenes]
            if not s["choices"]:
                s.pop("choices", None)

    # Rescale main-path durations toward TARGET_SECONDS if out of band.
    total = main_path_total(graph)
    if total and not (config.DURATION_MIN_TOTAL <= total <= config.DURATION_MAX_TOTAL):
        factor = config.TARGET_SECONDS / total
        for sid in main_path(graph):
            d = round(scenes[sid]["duration"] * factor)
            scenes[sid]["duration"] = max(config.CLIP_SECONDS_MIN,
                                         min(config.CLIP_SECONDS_MAX, d))
        print(f"[step2] rescaled main-path durations "
              f"({total}s -> {main_path_total(graph)}s)")

    if len(scenes) > config.MAX_SCENES:
        print(f"[step2] WARNING: {len(scenes)} scenes exceeds "
              f"MAX_SCENES={config.MAX_SCENES} (extra cost on media steps)")
    return graph


if __name__ == "__main__":
    run()

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
     "gender": "female|male|neutral",
     "voice_tone": "e.g. warm, wry, weary",
     "seed": 1111}
  ],
  "protagonist": "snake_case_id of the single viewpoint character",
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
- "protagonist" MUST be one of the character ids: the single viewpoint character
  whose inner monologue is voiced over the scenes.
- AT LEAST ONE scene must offer a real branch: 2+ choices whose goto lead to
  DIFFERENT scenes (this is an interactive film; a linear graph is invalid).
- CONSISTENCY: every "next" and every choice "goto" value MUST be EXACTLY one
  of the scene ids defined in "scenes" (or null for the final scene). Do not
  reference ids you did not define.
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
    try:
        graph = validate_and_fix(qwen_client.chat_json(SYSTEM, user))
    except qwen_client.QwenError as e:
        print(f"[step2] first graph invalid ({e}); regenerating once")
        fix0 = (user + "\n\nYour previous attempt produced a disconnected "
                "graph. Every next/goto MUST exactly match a defined scene id "
                "and every scene must be reachable from start.")
        graph = validate_and_fix(qwen_client.chat_json(SYSTEM, fix0))
    if not has_real_branch(graph):
        # One corrective retry: an interactive film needs at least one branch.
        # (Checked AFTER validation so repaired/pruned graphs are what we judge.)
        print("[step2] validated graph is linear; asking for a branch point")
        fix = (user + "\n\nYour previous graph had NO real branch after "
               "validation. Regenerate it so at least one scene offers 2+ "
               "choices whose goto lead to DIFFERENT scene chains that later "
               "rejoin, and make sure every next/goto exactly matches a "
               "defined scene id.")
        try:
            retry = validate_and_fix(qwen_client.chat_json(SYSTEM, fix))
            if has_real_branch(retry):
                graph = retry
            else:
                print("[step2] WARNING: retry still linear; keeping first graph")
        except qwen_client.QwenError as e:
            print(f"[step2] WARNING: branch retry failed ({e}); keeping first graph")

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


def _repair_link(target, scenes):
    """Best-effort match of a dangling scene reference to a real scene id.

    Handles the common failure where the model links to a shorthand id
    ("s3") but named the scene with a suffix ("s3_choice"), or vice versa.
    Returns None when nothing plausibly matches.
    """
    cands = [sid for sid in scenes
             if sid.startswith(target + "_") or target.startswith(sid + "_")]
    if not cands:
        cands = [sid for sid in scenes
                 if sid.startswith(target) or target.startswith(sid)]
    if not cands:
        return None
    return sorted(cands, key=lambda sid: (len(sid), sid))[0]


def has_real_branch(graph):
    """True if some scene offers 2+ choices leading to different scenes."""
    for s in (graph.get("scenes") or {}).values():
        gotos = {c.get("goto") for c in s.get("choices") or [] if c.get("goto")}
        if len(gotos) >= 2:
            return True
    return False


def reachable_ids(graph):
    """Scene ids reachable from start via next + choice gotos."""
    scenes = graph["scenes"]
    seen, stack = set(), [graph.get("start")]
    while stack:
        sid = stack.pop()
        if not sid or sid in seen or sid not in scenes:
            continue
        seen.add(sid)
        s = scenes[sid]
        stack.append(s.get("next"))
        stack.extend(c.get("goto") for c in s.get("choices") or [])
    return seen


def validate_and_fix(graph):
    if "scenes" not in graph or not graph["scenes"]:
        raise qwen_client.QwenError("scene graph has no scenes")
    graph.setdefault("start", "s1")
    graph.setdefault("global_style", "")
    graph.setdefault("characters", [])
    scenes = graph["scenes"]

    # Normalize shapes the model occasionally gets wrong: characters as plain
    # name strings, choices as plain label strings (both crash .get() later).
    norm_chars = []
    for c in graph["characters"]:
        if isinstance(c, str):
            c = {"id": c.strip().lower().replace(" ", "_"), "name": c.strip(),
                 "appearance": ""}
        if isinstance(c, dict) and c.get("id"):
            c.setdefault("name", c["id"])
            norm_chars.append(c)
    graph["characters"] = norm_chars
    for s in scenes.values():
        if isinstance(s.get("choices"), list):
            s["choices"] = [c for c in s["choices"] if isinstance(c, dict)]

    # Start scene must exist; fall back to the first declared scene.
    if graph["start"] not in scenes:
        graph["start"] = next(iter(scenes))

    # Protagonist must be a real character id (voices + seeds key off it).
    char_ids = [c.get("id") for c in graph["characters"] if c.get("id")]
    if graph.get("protagonist") not in char_ids and char_ids:
        counts = {cid: 0 for cid in char_ids}
        for s in scenes.values():
            for cid in s.get("characters", []):
                if cid in counts:
                    counts[cid] += 1
        graph["protagonist"] = max(counts, key=counts.get)
        print(f"[step2] protagonist defaulted to most-present character: "
              f"{graph['protagonist']}")

    # Clamp every duration to the model's [min,max].
    for s in scenes.values():
        d = int(s.get("duration", config.CLIP_SECONDS_DEFAULT))
        s["duration"] = max(config.CLIP_SECONDS_MIN,
                            min(config.CLIP_SECONDS_MAX, d))
        s.setdefault("narration", [])
        s.setdefault("characters", [])

    # Repair links before judging connectivity: models sometimes reference a
    # shorthand id ("s3") when the scene is named "s3_choice". A broken link
    # must not cascade into pruning the whole downstream story.
    for sid, s in scenes.items():
        nxt = s.get("next")
        if nxt and nxt not in scenes:
            fixed = _repair_link(nxt, scenes)
            print(f"[step2] repairing {sid}.next: {nxt!r} -> {fixed!r}")
            s["next"] = fixed
        for c in s.get("choices") or []:
            goto = c.get("goto")
            if goto and goto not in scenes:
                fixed = _repair_link(goto, scenes)
                print(f"[step2] repairing {sid} choice goto: {goto!r} -> {fixed!r}")
                c["goto"] = fixed

    # Drop choices that still point nowhere.
    for s in scenes.values():
        if s.get("choices"):
            s["choices"] = [c for c in s["choices"] if c.get("goto") in scenes]
            if not s["choices"]:
                s.pop("choices", None)

    # Last resort: prune scenes still unreachable from start (they'd cost
    # media money for nothing). After link repair this should be rare; a large
    # prune means the model produced a genuinely disconnected graph.
    orphans = set(scenes) - reachable_ids(graph)
    if orphans:
        if len(orphans) > len(scenes) // 2:
            raise qwen_client.QwenError(
                f"scene graph is mostly disconnected ({len(orphans)}/{len(scenes)} "
                f"unreachable: {sorted(orphans)}); regenerate step 2")
        for sid in orphans:
            del scenes[sid]
        print(f"[step2] pruned unreachable scenes: {sorted(orphans)}")

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

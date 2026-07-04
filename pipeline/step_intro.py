"""Intro stage: generate an opening narration (protagonist + premise + stakes).

Runs after step 2. Adds an `intro` block to build/scenes.json:
    {"intro": {"narration": ["line1", "line2", ...]}}

step 6 voices these lines (id "intro"); step 5 renders a title card + the intro
before the first scene, so viewers immediately know what to expect.

Idempotent: skips if an intro already exists (unless resume is off). Safe to run
on an existing project without touching scenes/frames/clips.
"""

import json

from . import config, qwen_client

SYSTEM = ("You write the OPENING narration for a short interactive film. It plays "
          "over a title card before the story starts, so the viewer instantly "
          "understands the protagonist, the world, the stakes, and that THEIR "
          "choices shape what happens.")

INSTRUCT = """Using the screenplay and metadata below, write the opening narration.

Return JSON: {"narration": ["...", "...", "..."]}

Rules:
- 3 to 4 short spoken lines (one sentence each), cinematic and punchy.
- Line 1: introduce the protagonist by NAME and who they are.
- Middle line(s): the premise / world / what's at stake.
- Final line: make clear the viewer will make choices that change the story.
- No spoilers about endings. Present tense. No markdown, no quotes inside lines.
"""


def run(resume=True):
    if not config.SCENES_JSON.exists():
        raise SystemExit(f"missing {config.SCENES_JSON}; run step 2 first")
    graph = json.loads(config.SCENES_JSON.read_text(encoding="utf-8"))

    if resume and graph.get("intro", {}).get("narration"):
        print("[intro] intro already present, skipping")
        return graph

    script = config.SCRIPT_MD.read_text(encoding="utf-8") if config.SCRIPT_MD.exists() else ""
    chars = "; ".join(f"{c.get('name')}: {c.get('appearance','')}"
                      for c in graph.get("characters", []))
    meta = (f"TITLE: {graph.get('title','')}\n"
            f"CHARACTERS: {chars}\n"
            f"VISUAL STYLE: {graph.get('global_style','')}\n\n"
            f"SCREENPLAY:\n{script}")

    print(f"[intro] generating opening narration ({config.LLM_MODEL}) ...")
    result = qwen_client.chat_json(SYSTEM, meta + "\n\n" + INSTRUCT)
    lines = [str(x).strip() for x in result.get("narration", []) if str(x).strip()]
    if not lines:
        raise qwen_client.QwenError(f"intro generation returned no lines: {result}")

    graph["intro"] = {"narration": lines}
    config.SCENES_JSON.write_text(json.dumps(graph, indent=2, ensure_ascii=False),
                                  encoding="utf-8")
    print(f"[intro] wrote {len(lines)} intro lines")
    return graph


if __name__ == "__main__":
    run()

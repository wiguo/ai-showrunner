"""Step 1: expand a one-line idea into a right-sized production-grade screenplay.

Input : examples/idea.txt (a short seed line)
Output: build/script.md (prose/Markdown screenplay)
"""

from . import config, qwen_client

SYSTEM = """You are an award-winning screenwriter and storyboard artist.
You turn a one-line idea into a tight, vivid, production-grade SHORT screenplay
intended to be rendered as a sequence of AI-generated video clips.

Hard constraints:
- The finished video must play in about {target}s (roughly {scenes} scene-beats).
  Keep it tight: no sprawling subplots, no large casts.
- Write for the SCREEN: concrete visuals, lighting, camera, character actions.
- Keep characters few (1-3) and give each a FIXED, detailed physical appearance
  that must stay identical across every scene (for visual consistency).
- Maintain one clear main storyline. You may suggest 1-2 small decision points
  where the viewer could choose, but both choices should rejoin the main path.

Output format (Markdown):
# Title
**Logline:** ...
## Characters
- Name - fixed detailed appearance (age, build, hair, wardrobe, distinguishing features)
## Visual Style
One paragraph describing the consistent cinematic look (palette, lighting, lens, mood).
## Scenes
Numbered beats. For each: setting, what happens, camera, and any optional choice.
"""


def run():
    config.ensure_dirs()
    idea_path = config.EXAMPLES_DIR / "idea.txt"
    if not idea_path.exists():
        raise SystemExit(f"missing input: {idea_path}")
    idea = idea_path.read_text(encoding="utf-8").strip()
    if not idea:
        raise SystemExit(f"{idea_path} is empty")

    system = SYSTEM.format(target=config.TARGET_SECONDS,
                           scenes=config.TARGET_MAIN_SCENES)
    user = f"One-line idea:\n{idea}\n\nWrite the screenplay now."

    print(f"[step1] expanding idea -> screenplay ({config.LLM_MODEL}) ...")
    script_md = qwen_client.chat_text(system, user)
    config.SCRIPT_MD.write_text(script_md, encoding="utf-8")
    print(f"[step1] wrote {config.SCRIPT_MD} ({len(script_md)} chars)")
    return config.SCRIPT_MD


if __name__ == "__main__":
    run()

"""Step 5: assemble a ready-to-open Ren'Py project from clips + scene graph.

Output: renpy_project/
  game/script.rpy    story flow (labels + movie cutscenes + menus)
  game/screens.rpy   minimal self-contained say/choice screens
  game/options.rpy   basic config
  game/movies/*.webm one per scene (converted from build/clips/*.mp4)

Hybrid generation: the .rpy is emitted by a deterministic template (always valid
syntax); all prose (narration, choice labels) comes from the Qwen-written scene
graph. No LLM call here.
"""

import json
import subprocess
from pathlib import Path

from . import config, media_utils


def _esc(text):
    """Escape a Python/Ren'Py double-quoted string body."""
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


def _voice_rel(sid, idx):
    """Relative 'voice/<file>' path if a voice clip exists for this line, else None."""
    if not config.VOICE_DIR.exists():
        return None
    matches = list(config.VOICE_DIR.glob(f"{sid}_{idx}.*"))
    return f"voice/{matches[0].name}" if matches else None


FONT_REL = "fonts/PlayfairDisplay-Regular.ttf"

SCREENS_RPY = '''\
# Minimal self-contained screens so the project opens without the full GUI template.

define FONT = "fonts/PlayfairDisplay-Regular.ttf"

# Bottom narration window (per-scene narration).
screen say(who, what):
    style_prefix "say"
    window:
        id "window"
        vbox:
            spacing 8
            if who is not None:
                text who id "who"
            text what id "what"

# Centered narration, used for the opening intro over the title screen.
# Uses the truecenter transform (same as the title) for reliable centering.
screen centered_say(who, what):
    text what id "what" style "centered_text" at truecenter

screen choice(items):
    style_prefix "choice"
    vbox:
        xalign 0.5
        yalign 0.75
        spacing 16
        for i in items:
            textbutton i.caption action i.action

# "Press Start" gate shown after the title; only the button advances.
screen start_prompt():
    modal True
    add Solid("#000000")
    vbox:
        align (0.5, 0.5)
        spacing 44
        text "This is an interactive video.\\nClick Start to begin — your choices shape the story." style "centered_text"
        textbutton "Start" action Return(True) style "start_button" xalign 0.5

style window:
    xfill True
    yalign 1.0
    ypadding 28
    xpadding 80
    background "#000000c0"

style say_who:
    font FONT
    color "#f0c674"
    size 30
    bold True

style say_what:
    font FONT
    color "#ffffff"
    size 30

style centered_text:
    font FONT
    color "#ffffff"
    size 42
    text_align 0.5
    xmaximum 1000
    line_spacing 8
    outlines [(2, "#000000", 0, 0)]

style choice_button:
    xalign 0.5

style choice_button_text:
    font FONT
    color "#ffffff"
    hover_color "#f0c674"
    size 30

style start_button:
    xalign 0.5
    padding (44, 18)
    background "#1a1a1aee"
    hover_background "#3a3a3aee"

style start_button_text:
    font FONT
    color "#ffffff"
    hover_color "#f0c674"
    size 34
'''


def _options_rpy(title):
    return (f'define config.name = "{_esc(title)}"\n'
            'define config.version = "1.0"\n'
            'define config.has_sound = True\n'
            'define config.has_music = True\n'
            'define config.check_conflicting_properties = True\n'
            'define config.screen_width = 1280\n'
            'define config.screen_height = 720\n'
            'define gui.init = None\n'
            'define config.window_title = "%s"\n' % _esc(title))


def _script_rpy(graph):
    start_scene = graph.get("start", "s1")
    title = graph.get("title", "Interactive Story")
    intro_lines = (graph.get("intro") or {}).get("narration") or []

    chars = graph.get("characters") or []
    mc_name = chars[0].get("name", "") if chars else ""

    lines = []
    lines.append("# Auto-generated interactive video script. Do not edit by hand.")
    lines.append("define narrator = Character(None)")
    lines.append('define intro_narrator = Character(None, screen="centered_say")')
    lines.append(f'define mc = Character("{_esc(mc_name)}")')
    lines.append('image black = Solid("#000000")')
    lines.append("")
    # Skip the default GUI main menu: launching jumps straight into the story.
    lines.append("label main_menu:")
    lines.append("    jump start")
    lines.append("")
    # Opening: centered, styled title card + centered intro narration.
    lines.append("label start:")
    lines.append("    scene black with fade")
    lines.append('    play sound "audio/title_sfx.ogg"')
    lines.append(f'    show text "{{font={FONT_REL}}}{{size=110}}{_esc(title)}{{/size}}{{/font}}"'
                 " at truecenter with dissolve")
    lines.append("    pause 2.5")
    lines.append("    hide text with dissolve")
    lines.append("    call screen start_prompt")
    for idx, line in enumerate(intro_lines):
        if str(line).strip():
            vf = _voice_rel("intro", idx)
            if vf:
                lines.append(f'    play sound "{vf}"')
            lines.append(f'    intro_narrator "{_esc(line)}"')
    lines.append(f"    jump {start_scene}")
    lines.append("")

    for sid, scene in graph["scenes"].items():
        lines.append(f"label {sid}:")
        lines.append(f'    $ renpy.movie_cutscene("movies/{sid}.webm")')
        mono = scene.get("monologue")
        if mono:
            # The character's voice AND subtitles are burned into the clip, so
            # nothing is shown after the video — it flows straight on.
            pass
        else:
            for idx, line in enumerate(scene.get("narration", [])):
                if str(line).strip():
                    vf = _voice_rel(sid, idx)
                    if vf:
                        lines.append(f'    play sound "{vf}"')
                    lines.append(f'    narrator "{_esc(line)}"')

        choices = scene.get("choices") or []
        if len(choices) >= 2:
            lines.append("    menu:")
            for c in choices:
                lines.append(f'        "{_esc(c["text"])}":')
                lines.append(f'            jump {c["goto"]}')
        else:
            nxt = scene.get("next")
            if nxt and nxt in graph["scenes"]:
                lines.append(f"    jump {nxt}")
            else:
                lines.append("    jump the_end")
        lines.append("")

    lines.append("label the_end:")
    lines.append('    narrator "The End."')
    lines.append("    menu:")
    lines.append('        "Play again":')
    lines.append("            jump start")
    lines.append('        "Quit":')
    lines.append("            $ renpy.quit()")
    lines.append("")
    return "\n".join(lines)


def run():
    if not config.SCENES_JSON.exists():
        raise SystemExit(f"missing {config.SCENES_JSON}; run step 2 first")
    graph = json.loads(config.SCENES_JSON.read_text(encoding="utf-8"))

    game_dir = config.RENPY_DIR / "game"
    movies_dir = game_dir / "movies"
    movies_dir.mkdir(parents=True, exist_ok=True)

    # Bundle the narration/title font and the title sound effect.
    import shutil
    assets = Path(__file__).parent / "assets"
    fonts_dir = game_dir / "fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)
    font_src = assets / "PlayfairDisplay-Regular.ttf"
    font_dst = fonts_dir / "PlayfairDisplay-Regular.ttf"
    if font_src.exists() and not font_dst.exists():
        shutil.copy(font_src, font_dst)
    audio_dir = game_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    sfx_src = assets / "title_sfx.ogg"
    sfx_dst = audio_dir / "title_sfx.ogg"
    if sfx_src.exists() and not sfx_dst.exists():
        shutil.copy(sfx_src, sfx_dst)

    # Convert each clip to WebM, mixing in the character monologue when present.
    missing = []
    for sid in graph["scenes"]:
        mp4 = config.CLIPS_DIR / f"{sid}.mp4"
        webm = movies_dir / f"{sid}.webm"
        if not mp4.exists():
            missing.append(sid)
            continue
        if webm.exists():
            print(f"[step5] {sid}: webm exists, skipping convert")
            continue
        mono = config.MONO_DIR / f"{sid}_all.ogg"
        srt = config.MONO_DIR / f"{sid}.srt"
        if mono.exists():
            print(f"[step5] {sid}: muxing character voice + subtitles into clip ...")
            media_utils.mux_voice_into_video(
                mp4, mono, webm, srt_path=srt if srt.exists() else None)
        else:
            print(f"[step5] {sid}: converting mp4 -> webm ...")
            media_utils.mp4_to_webm(mp4, webm)

    if missing:
        print(f"[step5] WARNING: no clip for scenes {missing} "
              f"(run step 4); script will reference missing movies")

    title = graph.get("title", "Interactive Story")
    (game_dir / "script.rpy").write_text(_script_rpy(graph), encoding="utf-8")
    (game_dir / "screens.rpy").write_text(SCREENS_RPY, encoding="utf-8")
    (game_dir / "options.rpy").write_text(_options_rpy(title), encoding="utf-8")

    print(f"[step5] Ren'Py project ready: {config.RENPY_DIR}")
    _lint()
    print("        Open it in the Ren'Py launcher to play.")
    return config.RENPY_DIR


def _lint():
    """Run `renpy lint` if the SDK executable is available."""
    exe = config.RENPY_EXE
    if not exe or not Path(exe).exists():
        return
    print("[step5] running Ren'Py lint ...")
    proc = subprocess.run([exe, str(config.RENPY_DIR), "lint"],
                          capture_output=True, text=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    if "error" in out.lower() or proc.returncode != 0:
        print("[step5] LINT ISSUES:\n" + out[-2000:])
    else:
        print("[step5] lint OK")


if __name__ == "__main__":
    run()

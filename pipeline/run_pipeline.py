"""Orchestrate the full story -> interactive Ren'Py video pipeline.

Examples:
  # cheap text-only preview (script + scene graph), review before spending:
  python -m pipeline.run_pipeline --idea examples\\idea.txt --dry-run

  # full run, small + cheap:
  python -m pipeline.run_pipeline --idea examples\\idea.txt --max-scenes 2 --resolution 720P

  # one step at a time:
  python -m pipeline.run_pipeline --only step3
"""

import argparse

from . import config
from . import (step1_expand, step2_scenes, step_intro, step3_frames,
               step4_clips, step_monologue, step5_renpy, step6_voice)

STEPS = ["step1", "step2", "intro", "step3", "step4", "mono", "step5", "step6"]


def parse_args():
    p = argparse.ArgumentParser(description="Story -> interactive Ren'Py video pipeline.")
    p.add_argument("--idea", help="Path to a one-line idea file "
                   "(default: examples/idea.txt).")
    p.add_argument("--job-dir", help="Isolate all inputs/outputs under this "
                   "directory (fresh build/ + renpy_project/ per job).")
    p.add_argument("--only", choices=STEPS, help="Run a single step.")
    p.add_argument("--dry-run", action="store_true",
                   help="Run only step1+step2 (text), then stop.")
    p.add_argument("--resolution", choices=["720P", "1080P"],
                   help="Override clip resolution.")
    p.add_argument("--max-scenes", type=int,
                   help="Override MAX_SCENES cap.")
    p.add_argument("--target-seconds", type=int,
                   help="Target single-playthrough runtime (default from config).")
    p.add_argument("--no-resume", action="store_true",
                   help="Regenerate even if outputs exist.")
    p.add_argument("--video-flash", action="store_true",
                   help="Force the first-frame-only chain even when "
                        "I2V_FIRSTLAST_MODEL is configured.")
    p.add_argument("--no-voice", action="store_true",
                   help="Skip narration voice-over (step 6 runs by default).")
    return p.parse_args()


def main():
    args = parse_args()
    config.require_api_key()
    if args.job_dir:
        config.configure_job(args.job_dir)
    config.ensure_dirs()

    if args.idea:
        import pathlib
        import shutil
        config.IDEA_TXT.parent.mkdir(parents=True, exist_ok=True)
        if str(config.IDEA_TXT.resolve()) != str(pathlib.Path(args.idea).resolve()):
            shutil.copy(args.idea, config.IDEA_TXT)
    if args.resolution:
        config.RESOLUTION = args.resolution
    if args.max_scenes:
        config.MAX_SCENES = args.max_scenes
    if args.target_seconds:
        config.TARGET_SECONDS = args.target_seconds
        config.TARGET_MAIN_SCENES = round(args.target_seconds / config.SECONDS_PER_SCENE)
        config.DURATION_MIN_TOTAL = int(args.target_seconds * 0.85)
        config.DURATION_MAX_TOTAL = int(args.target_seconds * 1.2)
    resume = not args.no_resume

    if args.only:
        _run_one(args.only, resume, args.video_flash)
        return

    step1_expand.run()
    step2_scenes.run()
    step_intro.run(resume=resume)
    if args.dry_run:
        print("\n[dry-run] stopped after scene graph. Review build/script.md and "
              "build/scenes.json before a full run.")
        return
    step3_frames.run(resume=resume)
    step4_clips.run(resume=resume, resolution=args.resolution, flash=args.video_flash)
    if not args.no_voice:
        step_monologue.run(resume=resume)   # character voice (mixed into clips)
        step6_voice.run(resume=resume)      # narrator voice for the intro
    step5_renpy.run()
    print("\nDone. Open renpy_project/ in the Ren'Py launcher to play.")


def _run_one(step, resume, flash=False):
    if step == "step1":
        step1_expand.run()
    elif step == "step2":
        step2_scenes.run()
    elif step == "intro":
        step_intro.run(resume=resume)
    elif step == "mono":
        step_monologue.run(resume=resume)
    elif step == "step3":
        step3_frames.run(resume=resume)
    elif step == "step4":
        step4_clips.run(resume=resume, flash=flash)
    elif step == "step5":
        step5_renpy.run()
    elif step == "step6":
        step6_voice.run(resume=resume)


if __name__ == "__main__":
    main()

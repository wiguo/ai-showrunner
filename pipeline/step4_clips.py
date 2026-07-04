"""Step 4: generate one video clip per scene from its keyframe(s).

Default: first-frame-only i2v, walking config.I2V_CHAIN (happyhorse first,
wan-flash fallbacks) so per-model quota exhaustion hops to the next model.
If config.I2V_FIRSTLAST_MODEL is set and step 3 produced last frames, the
first+last shape is used instead.

Downloads each MP4 to build/clips/. Resumable: scenes whose clip already
exists are skipped.

Note: frame URLs are valid ~24h. If step 3 ran long ago, re-run step 3 first to
refresh them.
"""

import json

from . import config, qwen_client


def run(resume=True, resolution=None, flash=False):
    config.ensure_dirs()
    if not config.SCENES_JSON.exists():
        raise SystemExit(f"missing {config.SCENES_JSON}; run step 2 first")
    if not config.URLS_JSON.exists():
        raise SystemExit(f"missing {config.URLS_JSON}; run step 3 first")

    graph = json.loads(config.SCENES_JSON.read_text(encoding="utf-8"))
    urls = json.loads(config.URLS_JSON.read_text(encoding="utf-8"))

    for sid, scene in graph["scenes"].items():
        clip_path = config.CLIPS_DIR / f"{sid}.mp4"
        if resume and clip_path.exists():
            print(f"[step4] {sid}: clip exists, skipping")
            continue
        if sid not in urls:
            raise SystemExit(f"no frames for {sid}; run step 3 first")

        duration = int(scene.get("duration", config.CLIP_SECONDS_DEFAULT))
        motion = scene.get("motion_prompt") or scene.get("summary", "")
        use_firstlast = (config.I2V_FIRSTLAST_MODEL and not flash
                         and urls[sid].get("last"))
        engine = (config.I2V_FIRSTLAST_MODEL if use_firstlast
                  else "+".join(config.I2V_CHAIN))
        print(f"[step4] {sid}: i2v ({duration}s, "
              f"{resolution or config.RESOLUTION}, {engine}) ...")
        if use_firstlast:
            video_url = qwen_client.image_to_video(
                first_url=urls[sid]["first"],
                last_url=urls[sid]["last"],
                prompt=motion,
                duration=duration,
                resolution=resolution,
            )
        else:
            video_url = qwen_client.generate_clip(
                img_url=urls[sid]["first"],
                prompt=motion,
                duration=duration,
                resolution=resolution,
            )
        qwen_client.download(video_url, clip_path)
        print(f"[step4] {sid}: saved {clip_path.name}")

    print(f"[step4] done: clips in {config.CLIPS_DIR}")


if __name__ == "__main__":
    run()

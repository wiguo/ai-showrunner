"""Step 4: generate one video clip per scene from its first+last frames.

Uses wan2.7-i2v with the frame URLs recorded in build/urls.json. Downloads each
MP4 to build/clips/. Resumable: scenes whose clip already exists are skipped.

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
        engine = config.I2V_FLASH_MODEL if flash else config.I2V_MODEL
        print(f"[step4] {sid}: i2v ({duration}s, "
              f"{resolution or config.RESOLUTION}, {engine}) ...")
        if flash:
            video_url = qwen_client.image_to_video_first(
                img_url=urls[sid]["first"],
                prompt=motion,
                duration=duration,
                resolution=resolution,
            )
        else:
            video_url = qwen_client.image_to_video(
                first_url=urls[sid]["first"],
                last_url=urls[sid]["last"],
                prompt=motion,
                duration=duration,
                resolution=resolution,
            )
        qwen_client.download(video_url, clip_path)
        print(f"[step4] {sid}: saved {clip_path.name}")

    print(f"[step4] done: clips in {config.CLIPS_DIR}")


if __name__ == "__main__":
    run()

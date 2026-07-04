"""Step 3: generate first + last keyframes for each scene.

For every scene:
  1. first frame  -> qwen-image-plus (text-to-image)
  2. last frame   -> qwen-image-2.0-pro (edit of the FIRST frame, for consistency)

Saves PNGs to build/frames/ and records the source URLs in build/urls.json.
Resumable: scenes already present in urls.json (with files on disk) are skipped.
"""

import json

from . import config, qwen_client


def _load_urls():
    if config.URLS_JSON.exists():
        return json.loads(config.URLS_JSON.read_text(encoding="utf-8"))
    return {}


def _save_urls(urls):
    config.URLS_JSON.write_text(json.dumps(urls, indent=2, ensure_ascii=False),
                                encoding="utf-8")


def _char_block(graph, scene):
    """Appearance text for characters present in the scene."""
    by_id = {c["id"]: c for c in graph.get("characters", [])}
    bits = []
    for cid in scene.get("characters", []):
        c = by_id.get(cid)
        if c:
            bits.append(f"{c['name']}: {c.get('appearance', '')}")
    return " ".join(bits)


def _scene_seed(graph, idx):
    chars = graph.get("characters", [])
    base = int(chars[0]["seed"]) if chars and chars[0].get("seed") is not None else 1000
    return (base + idx * 7) % 2147483647


def _compose_first_prompt(graph, scene):
    parts = []
    if graph.get("global_style"):
        parts.append(graph["global_style"])
    parts.append(scene["first_frame_prompt"])
    chars = _char_block(graph, scene)
    if chars:
        parts.append("Characters: " + chars)
    return " ".join(parts)


def run(resume=True):
    config.ensure_dirs()
    if not config.SCENES_JSON.exists():
        raise SystemExit(f"missing {config.SCENES_JSON}; run step 2 first")
    graph = json.loads(config.SCENES_JSON.read_text(encoding="utf-8"))
    urls = _load_urls() if resume else {}

    scene_ids = list(graph["scenes"].keys())
    for idx, sid in enumerate(scene_ids):
        scene = graph["scenes"][sid]
        first_png = config.FRAMES_DIR / f"{sid}_first.png"
        last_png = config.FRAMES_DIR / f"{sid}_last.png"

        done = (sid in urls and urls[sid].get("first") and urls[sid].get("last")
                and first_png.exists() and last_png.exists())
        if resume and done:
            print(f"[step3] {sid}: already done, skipping")
            continue

        seed = _scene_seed(graph, idx)
        print(f"[step3] {sid}: first frame (text-to-image, seed={seed}) ...")
        first_prompt = _compose_first_prompt(graph, scene)
        first_url = qwen_client.text_to_image(first_prompt, seed=seed)
        qwen_client.download(first_url, first_png)

        print(f"[step3] {sid}: last frame (edit of first) ...")
        edit_instruction = scene.get("last_frame_edit") or (
            "Keep the same characters and setting; advance the action slightly "
            "to the end of the moment.")
        last_url = qwen_client.image_edit(first_url, edit_instruction, seed=seed)
        qwen_client.download(last_url, last_png)

        urls[sid] = {"first": first_url, "last": last_url,
                     "first_png": str(first_png), "last_png": str(last_png)}
        _save_urls(urls)
        print(f"[step3] {sid}: saved both frames")

    print(f"[step3] done: {len(urls)} scenes have frames")
    return urls


if __name__ == "__main__":
    run()

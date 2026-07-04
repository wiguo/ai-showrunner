#!/usr/bin/env python3
"""Generate a video from an image (first frame) using the Qwen HappyHorse i2v API.

Use this to continue a story with a consistent character and scene: extract the
last frame of a previous clip and use it as the first frame of the next one.

Usage:
    # Continue directly from a previous video (extracts its last frame):
    python happyhorse_i2v.py "next story beat ..." --from-video output.mp4 -o output2.mp4

    # Or start from an existing image:
    python happyhorse_i2v.py "prompt ..." --image frame.png -o out.mp4

The input image is sent inline as a base64 data URI, so no public hosting needed.
"""

import argparse
import base64
import mimetypes
import os
import sys
import time

import requests

BASE_URL = "https://dashscope-intl.aliyuncs.com/api/v1"
SUBMIT_URL = f"{BASE_URL}/services/aigc/video-generation/video-synthesis"
TASK_URL = f"{BASE_URL}/tasks/{{task_id}}"
MODEL = "happyhorse-1.1-i2v"


def extract_last_frame(video_path, out_image_path):
    """Extract the final frame of a video to a PNG using imageio (bundled ffmpeg)."""
    import imageio.v3 as iio

    last = None
    for frame in iio.imiter(video_path, plugin="FFMPEG"):
        last = frame
    if last is None:
        raise RuntimeError(f"Could not read any frames from {video_path}")
    iio.imwrite(out_image_path, last)
    print(f"Extracted last frame -> {out_image_path} ({last.shape[1]}x{last.shape[0]})")
    return out_image_path


def image_to_data_uri(image_path):
    mime, _ = mimetypes.guess_type(image_path)
    if mime not in ("image/jpeg", "image/png", "image/webp"):
        mime = "image/png"
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def submit_task(api_key, prompt, image_uri, resolution, duration, watermark, seed):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }
    parameters = {
        "resolution": resolution,
        "duration": duration,
        "watermark": watermark,
    }
    if seed is not None:
        parameters["seed"] = seed

    payload = {
        "model": MODEL,
        "input": {
            "prompt": prompt,
            "media": [{"type": "first_frame", "url": image_uri}],
        },
        "parameters": parameters,
    }

    resp = requests.post(SUBMIT_URL, headers=headers, json=payload, timeout=120)
    if resp.status_code != 200:
        raise RuntimeError(f"Submission failed (HTTP {resp.status_code}): {resp.text}")

    output = resp.json().get("output", {})
    task_id = output.get("task_id")
    if not task_id:
        raise RuntimeError(f"No task_id in response: {resp.text}")
    print(f"Task submitted. task_id={task_id} status={output.get('task_status')}")
    return task_id


def poll_task(api_key, task_id, interval, timeout):
    headers = {"Authorization": f"Bearer {api_key}"}
    url = TASK_URL.format(task_id=task_id)
    deadline = time.time() + timeout
    while True:
        resp = requests.get(url, headers=headers, timeout=60)
        if resp.status_code != 200:
            raise RuntimeError(f"Polling failed (HTTP {resp.status_code}): {resp.text}")
        output = resp.json().get("output", {})
        status = output.get("task_status")
        if status == "SUCCEEDED":
            return output
        if status in ("FAILED", "CANCELED", "UNKNOWN"):
            raise RuntimeError(
                f"Task ended with status {status}: "
                f"code={output.get('code')} message={output.get('message')}"
            )
        if time.time() > deadline:
            raise TimeoutError(f"Task not finished within {timeout}s (last: {status})")
        print(f"  status={status} ... waiting {interval}s")
        time.sleep(interval)


def download_video(video_url, output_path):
    print(f"Downloading video to {output_path} ...")
    with requests.get(video_url, stream=True, timeout=300) as resp:
        resp.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 16):
                if chunk:
                    f.write(chunk)
    print(f"Saved {output_path}")


def parse_args():
    p = argparse.ArgumentParser(description="HappyHorse image-to-video generation.")
    p.add_argument("prompt", nargs="?", help="Text prompt describing what happens next.")
    p.add_argument("--prompt-file", help="Read the prompt from this file (avoids shell quoting issues).")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--image", help="Path to first-frame image (png/jpg/webp).")
    src.add_argument("--from-video", help="Extract last frame of this video as first frame.")
    p.add_argument("--api-key", default=os.getenv("DASHSCOPE_API_KEY"),
                   help="DashScope API key (defaults to DASHSCOPE_API_KEY env var).")
    p.add_argument("--resolution", default="720P", choices=["720P", "1080P"])
    p.add_argument("--duration", type=int, default=5, help="Seconds, 3-15 (default 5).")
    p.add_argument("--no-watermark", action="store_true")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--output", "-o", default="output_i2v.mp4")
    p.add_argument("--poll-interval", type=int, default=10)
    p.add_argument("--timeout", type=int, default=900)
    p.add_argument("--print-url-only", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    if args.prompt_file:
        with open(args.prompt_file, "r", encoding="utf-8") as f:
            args.prompt = f.read().strip()
    if not args.prompt:
        sys.exit("Error: provide a prompt (positional) or --prompt-file.")
    if not args.api_key:
        sys.exit("Error: no API key. Set DASHSCOPE_API_KEY or pass --api-key.")
    if not (3 <= args.duration <= 15):
        sys.exit("Error: --duration must be between 3 and 15 seconds.")

    image_path = args.image
    if args.from_video:
        frame_path = os.path.splitext(args.output)[0] + "_firstframe.png"
        try:
            image_path = extract_last_frame(args.from_video, frame_path)
        except Exception as e:
            sys.exit(f"Error extracting frame: {e}")

    try:
        image_uri = image_to_data_uri(image_path)
        task_id = submit_task(
            api_key=args.api_key, prompt=args.prompt, image_uri=image_uri,
            resolution=args.resolution, duration=args.duration,
            watermark=not args.no_watermark, seed=args.seed,
        )
        output = poll_task(args.api_key, task_id, args.poll_interval, args.timeout)
    except (RuntimeError, TimeoutError, requests.RequestException) as e:
        sys.exit(f"Error: {e}")

    video_url = output.get("video_url")
    if not video_url:
        sys.exit(f"Error: succeeded but no video_url: {output}")
    print(f"Video URL (valid 24h): {video_url}")
    if args.print_url_only:
        return
    try:
        download_video(video_url, args.output)
    except requests.RequestException as e:
        sys.exit(f"Error downloading video: {e}")


if __name__ == "__main__":
    main()

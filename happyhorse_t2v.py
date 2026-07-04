#!/usr/bin/env python3
"""Generate a video from text using the Qwen HappyHorse text-to-video API.

Submits an asynchronous text-to-video task, polls until it completes, then
downloads the resulting MP4.

Usage:
    # API key via environment variable (recommended)
    set DASHSCOPE_API_KEY=sk-xxxx        # Windows (cmd)
    $env:DASHSCOPE_API_KEY="sk-xxxx"     # Windows (PowerShell)
    export DASHSCOPE_API_KEY=sk-xxxx     # macOS / Linux

    python happyhorse_t2v.py "A cardboard train passing through a miniature city at night"

    # Or pass the key explicitly
    python happyhorse_t2v.py "your prompt" --api-key sk-xxxx

    # Tune output
    python happyhorse_t2v.py "your prompt" \
        --resolution 1080P --ratio 9:16 --duration 8 --no-watermark \
        --output my_video.mp4
"""

import argparse
import os
import sys
import time

import requests

BASE_URL = "https://dashscope-intl.aliyuncs.com/api/v1"
SUBMIT_URL = f"{BASE_URL}/services/aigc/video-generation/video-synthesis"
TASK_URL = f"{BASE_URL}/tasks/{{task_id}}"
MODEL = "happyhorse-1.0-t2v"


def submit_task(api_key, prompt, resolution, ratio, duration, watermark, seed):
    """Submit the text-to-video task and return the task_id."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }
    parameters = {
        "resolution": resolution,
        "ratio": ratio,
        "duration": duration,
        "watermark": watermark,
    }
    if seed is not None:
        parameters["seed"] = seed

    payload = {
        "model": MODEL,
        "input": {"prompt": prompt},
        "parameters": parameters,
    }

    resp = requests.post(SUBMIT_URL, headers=headers, json=payload, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(
            f"Task submission failed (HTTP {resp.status_code}): {resp.text}"
        )

    data = resp.json()
    output = data.get("output", {})
    task_id = output.get("task_id")
    if not task_id:
        raise RuntimeError(f"No task_id in response: {data}")

    print(f"Task submitted. task_id={task_id} status={output.get('task_status')}")
    return task_id


def poll_task(api_key, task_id, interval, timeout):
    """Poll the task until it reaches a terminal state. Return the output dict."""
    headers = {"Authorization": f"Bearer {api_key}"}
    url = TASK_URL.format(task_id=task_id)
    deadline = time.time() + timeout

    while True:
        resp = requests.get(url, headers=headers, timeout=60)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Polling failed (HTTP {resp.status_code}): {resp.text}"
            )

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
            raise TimeoutError(
                f"Task did not finish within {timeout}s (last status: {status})"
            )

        print(f"  status={status} ... waiting {interval}s")
        time.sleep(interval)


def download_video(video_url, output_path):
    """Stream the generated video to disk."""
    print(f"Downloading video to {output_path} ...")
    with requests.get(video_url, stream=True, timeout=300) as resp:
        resp.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 16):
                if chunk:
                    f.write(chunk)
    print(f"Saved {output_path}")


def parse_args():
    p = argparse.ArgumentParser(
        description="Generate a video from text using the Qwen HappyHorse API."
    )
    p.add_argument("prompt", help="Text prompt describing the video.")
    p.add_argument(
        "--api-key",
        default=os.getenv("DASHSCOPE_API_KEY"),
        help="DashScope API key (defaults to DASHSCOPE_API_KEY env var).",
    )
    p.add_argument(
        "--resolution",
        default="1080P",
        choices=["720P", "1080P"],
        help="Video resolution tier (default: 1080P).",
    )
    p.add_argument(
        "--ratio",
        default="16:9",
        choices=["16:9", "9:16", "1:1", "4:3", "3:4", "4:5", "5:4", "9:21", "21:9"],
        help="Aspect ratio (default: 16:9).",
    )
    p.add_argument(
        "--duration",
        type=int,
        default=5,
        help="Video duration in seconds, 3-15 (default: 5).",
    )
    p.add_argument(
        "--no-watermark",
        action="store_true",
        help="Disable the HappyHorse watermark.",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Seed for reproducible results (0-2147483647).",
    )
    p.add_argument(
        "--output",
        "-o",
        default="output.mp4",
        help="Output file path (default: output.mp4).",
    )
    p.add_argument(
        "--poll-interval",
        type=int,
        default=10,
        help="Seconds between status polls (default: 10).",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=900,
        help="Max seconds to wait for the task (default: 900).",
    )
    p.add_argument(
        "--print-url-only",
        action="store_true",
        help="Print the video URL instead of downloading.",
    )
    return p.parse_args()


def main():
    args = parse_args()

    if not args.api_key:
        sys.exit(
            "Error: no API key. Set DASHSCOPE_API_KEY or pass --api-key."
        )
    if not (3 <= args.duration <= 15):
        sys.exit("Error: --duration must be between 3 and 15 seconds.")

    try:
        task_id = submit_task(
            api_key=args.api_key,
            prompt=args.prompt,
            resolution=args.resolution,
            ratio=args.ratio,
            duration=args.duration,
            watermark=not args.no_watermark,
            seed=args.seed,
        )
        output = poll_task(
            api_key=args.api_key,
            task_id=task_id,
            interval=args.poll_interval,
            timeout=args.timeout,
        )
    except (RuntimeError, TimeoutError, requests.RequestException) as e:
        sys.exit(f"Error: {e}")

    video_url = output.get("video_url")
    if not video_url:
        sys.exit(f"Error: task succeeded but no video_url found: {output}")

    print(f"Video URL (valid 24h): {video_url}")
    if args.print_url_only:
        return

    try:
        download_video(video_url, args.output)
    except requests.RequestException as e:
        sys.exit(f"Error downloading video: {e}")


if __name__ == "__main__":
    main()

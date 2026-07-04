#!/usr/bin/env python3
"""Probe every model class the pipeline needs on the Qwen intl endpoint.

Run this FIRST (needs DASHSCOPE_API_KEY). Each probe is independent and
prints PASS/FAIL with the response details that matter for pipeline/config.py:
exact model availability, request shapes, allowed durations, TTS voice names,
and whether i2v clips contain an audio stream.

Usage:
    python -m scripts.smoke_test            # all probes
    python -m scripts.smoke_test chat tts   # only these probes

Probes: chat, t2i_async, t2i_sync, edit, i2v, tts
Media probes cost a few cents; chat costs a fraction of one.
"""

import base64
import io
import json
import os
import struct
import sys
import time
import zlib

import requests

# Windows consoles default to a legacy codepage; API errors often contain
# full-width punctuation that would crash print().
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
BASE = "https://dashscope-intl.aliyuncs.com/api/v1"
CHAT_BASE = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
TEXT2IMAGE_URL = f"{BASE}/services/aigc/text2image/image-synthesis"
MULTIMODAL_URL = f"{BASE}/services/aigc/multimodal-generation/generation"
VIDEO_URL = f"{BASE}/services/aigc/video-generation/video-synthesis"
TEXT2AUDIO_URL = f"{BASE}/services/aigc/text2audio/generation"
TASK_URL = BASE + "/tasks/{task_id}"

CHAT_CANDIDATES = ["qwen3.7-max", "qwen3-max", "qwen-plus"]
T2I_ASYNC_CANDIDATES = ["wan2.6-t2i", "qwen-image-2.0-pro", "wan2.2-t2i-flash"]
T2I_SYNC_CANDIDATES = ["z-image-turbo"]
EDIT_CANDIDATES = ["qwen-image-edit", "qwen-image-2.0-pro"]
I2V_CANDIDATES = ["happyhorse-1.1-i2v"]
TTS_CANDIDATES = [
    # (model, api_style, voices to try)
    ("cosyvoice-v3-plus", "async", ["loongstella", "loongbella", "longxiaochun_v2", "longwan_v2"]),
    ("cosyvoice-v3-plus", "sync", ["loongstella", "loongbella"]),
    ("qwen3-tts-flash", "sync", ["Cherry", "Kai"]),
]

RESULTS = {}


def hdr(async_task=False):
    h = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    if async_task:
        h["X-DashScope-Async"] = "enable"
    return h


def poll(task_id, timeout=600, interval=8):
    deadline = time.time() + timeout
    while True:
        r = requests.get(TASK_URL.format(task_id=task_id), headers=hdr(), timeout=60)
        out = r.json().get("output", {})
        status = out.get("task_status")
        if status == "SUCCEEDED":
            return out
        if status in ("FAILED", "CANCELED", "UNKNOWN"):
            raise RuntimeError(f"task {status}: {out.get('code')} {out.get('message')}")
        if time.time() > deadline:
            raise TimeoutError(f"not done in {timeout}s (last {status})")
        time.sleep(interval)


def show(tag, ok, detail):
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {tag}: {detail}")
    RESULTS[tag] = (ok, detail)


def tiny_png_data_uri():
    """A 64x36 dark-blue PNG (16:9) built by hand — a valid i2v input image."""
    w, h = 64, 36
    row = b"\x00" + b"\x10\x18\x40" * w
    raw = row * h
    def chunk(typ, data):
        c = struct.pack(">I", len(data)) + typ + data
        return c + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw))
           + chunk(b"IEND", b""))
    return "data:image/png;base64," + base64.b64encode(png).decode()


# ---------------------------------------------------------------------------
def probe_chat():
    from openai import OpenAI
    client = OpenAI(api_key=API_KEY, base_url=CHAT_BASE)
    for model in CHAT_CANDIDATES:
        try:
            r = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": 'Reply with JSON: {"ok": true}'}],
                response_format={"type": "json_object"},
                max_tokens=50,
            )
            txt = r.choices[0].message.content
            json.loads(txt)
            show(f"chat:{model}", True, f"json-mode ok, reply={txt.strip()[:60]}")
            return
        except Exception as e:
            show(f"chat:{model}", False, str(e)[:200])


def probe_t2i_async():
    for model in T2I_ASYNC_CANDIDATES:
        try:
            payload = {
                "model": model,
                "input": {"prompt": "a red apple on a wooden table, photo"},
                "parameters": {"size": "1280*720", "n": 1, "prompt_extend": False},
            }
            r = requests.post(TEXT2IMAGE_URL, headers=hdr(True), json=payload, timeout=120)
            if r.status_code != 200:
                show(f"t2i_async:{model}", False,
                     f"HTTP {r.status_code} {r.text[:200]}")
                continue
            out = poll(r.json()["output"]["task_id"])
            results = out.get("results") or []
            url = results[0].get("url") if results else None
            show(f"t2i_async:{model}", bool(url), f"url={str(url)[:80]}")
            if url:
                RESULTS["_t2i_url"] = url
                return
        except Exception as e:
            show(f"t2i_async:{model}", False, str(e)[:200])


def probe_t2i_sync():
    for model in T2I_SYNC_CANDIDATES:
        try:
            payload = {
                "model": model,
                "input": {"messages": [{"role": "user",
                                        "content": [{"text": "a red apple, photo"}]}]},
                "parameters": {"prompt_extend": False, "size": "1280*720"},
            }
            r = requests.post(MULTIMODAL_URL, headers=hdr(), json=payload, timeout=180)
            if r.status_code != 200:
                show(f"t2i_sync:{model}", False, f"HTTP {r.status_code} {r.text[:200]}")
                continue
            content = r.json()["output"]["choices"][0]["message"]["content"]
            url = next((p["image"] for p in content if isinstance(p, dict) and p.get("image")), None)
            show(f"t2i_sync:{model}", bool(url), f"url={str(url)[:80]}")
            if url and "_t2i_url" not in RESULTS:
                RESULTS["_t2i_url"] = url
        except Exception as e:
            show(f"t2i_sync:{model}", False, str(e)[:200])


def probe_edit():
    src = RESULTS.get("_t2i_url")
    if not src:
        show("edit", False, "skipped: no t2i image to edit (run t2i first)")
        return
    for model in EDIT_CANDIDATES:
        try:
            payload = {
                "model": model,
                "input": {"messages": [{"role": "user", "content": [
                    {"image": src}, {"text": "make the lighting warm sunset"}]}]},
                "parameters": {"negative_prompt": " ", "prompt_extend": True},
            }
            r = requests.post(MULTIMODAL_URL, headers=hdr(), json=payload, timeout=180)
            if r.status_code != 200:
                show(f"edit:{model}", False, f"HTTP {r.status_code} {r.text[:200]}")
                continue
            content = r.json()["output"]["choices"][0]["message"]["content"]
            url = next((p["image"] for p in content if isinstance(p, dict) and p.get("image")), None)
            show(f"edit:{model}", bool(url), f"url={str(url)[:80]}")
            return
        except Exception as e:
            show(f"edit:{model}", False, str(e)[:200])


def probe_i2v():
    img = RESULTS.get("_t2i_url") or tiny_png_data_uri()
    for model in I2V_CANDIDATES:
        try:
            payload = {
                "model": model,
                "input": {"prompt": "gentle camera pan, cinematic",
                          "media": [{"type": "first_frame", "url": img}]},
                "parameters": {"resolution": "720P", "duration": 3, "watermark": False},
            }
            r = requests.post(VIDEO_URL, headers=hdr(True), json=payload, timeout=120)
            if r.status_code != 200:
                show(f"i2v:{model}", False, f"HTTP {r.status_code} {r.text[:300]}")
                continue
            out = poll(r.json()["output"]["task_id"], timeout=900)
            url = out.get("video_url")
            if not url:
                show(f"i2v:{model}", False, f"no video_url: {json.dumps(out)[:200]}")
                continue
            path = os.path.join(os.path.dirname(__file__), "smoke_i2v.mp4")
            with requests.get(url, stream=True, timeout=300) as dl:
                dl.raise_for_status()
                with open(path, "wb") as f:
                    for c in dl.iter_content(1 << 16):
                        f.write(c)
            audio = _has_audio(path)
            show(f"i2v:{model}", True,
                 f"3s clip ok ({os.path.getsize(path)//1024}KB), audio_stream={audio} -> {path}")
            return
        except Exception as e:
            show(f"i2v:{model}", False, str(e)[:300])


def _has_audio(path):
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from pipeline.media_utils import has_audio
        return has_audio(path)
    except Exception as e:
        return f"unknown ({e})"


def probe_tts():
    for model, style, voices in TTS_CANDIDATES:
        for voice in voices:
            tag = f"tts:{model}:{style}:{voice}"
            try:
                if style == "sync":
                    payload = {"model": model,
                               "input": {"text": "Hello from the smoke test.",
                                         "voice": voice, "language_type": "Auto"}}
                    r = requests.post(MULTIMODAL_URL, headers=hdr(), json=payload, timeout=120)
                    if r.status_code != 200:
                        show(tag, False, f"HTTP {r.status_code} {r.text[:160]}")
                        continue
                    url = r.json().get("output", {}).get("audio", {}).get("url")
                    show(tag, bool(url), f"audio url={str(url)[:70]}")
                    if url:
                        return
                else:
                    payload = {"model": model,
                               "input": {"text": "Hello from the smoke test."},
                               "parameters": {"voice": voice}}
                    r = requests.post(TEXT2AUDIO_URL, headers=hdr(True), json=payload, timeout=120)
                    if r.status_code != 200:
                        show(tag, False, f"HTTP {r.status_code} {r.text[:160]}")
                        continue
                    body = r.json()
                    task_id = body.get("output", {}).get("task_id")
                    if task_id:
                        out = poll(task_id, timeout=300)
                        url = out.get("audio_url") or out.get("audio", {}).get("url")
                    else:  # some TTS endpoints answer synchronously
                        url = body.get("output", {}).get("audio", {}).get("url")
                    show(tag, bool(url), f"audio url={str(url)[:70]} raw={json.dumps(body)[:120]}")
                    if url:
                        return
            except Exception as e:
                show(tag, False, str(e)[:200])


PROBES = {"chat": probe_chat, "t2i_async": probe_t2i_async, "t2i_sync": probe_t2i_sync,
          "edit": probe_edit, "i2v": probe_i2v, "tts": probe_tts}


def main():
    if not API_KEY:
        sys.exit('DASHSCOPE_API_KEY is not set. PowerShell: $env:DASHSCOPE_API_KEY="sk-..."')
    wanted = sys.argv[1:] or list(PROBES)
    for name in wanted:
        print(f"\n=== {name} ===")
        PROBES[name]()
    print("\n=== SUMMARY ===")
    for tag, val in RESULTS.items():
        if tag.startswith("_"):
            continue
        ok, _detail = val
        print(f"  {'PASS' if ok else 'FAIL'}  {tag}")
    print("\nUse the first PASS in each class to set pipeline/config.py "
          "(LLM_MODEL, T2I chain, EDIT model, I2V chain, TTS model/style/voices).")


if __name__ == "__main__":
    main()

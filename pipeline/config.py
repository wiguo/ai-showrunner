"""Central configuration for the story -> Ren'Py pipeline.

Everything tunable lives here: API endpoints, model registry (with fallback
chains), runtime budget, guardrails, and filesystem layout. The whole pipeline
runs on a single DASHSCOPE_API_KEY (Qwen Model Studio international).

Two layers of configurability:
  * env vars for deploy-time overrides (model names, RENPY_EXE, ...)
  * configure_job(job_dir) for per-job path isolation (web server mode)
"""

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Auth (single key for the entire pipeline)
# ---------------------------------------------------------------------------
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")

# ---------------------------------------------------------------------------
# Endpoints (Qwen Model Studio international)
# ---------------------------------------------------------------------------
BASE_URL = "https://dashscope-intl.aliyuncs.com/api/v1"
TEXT2IMAGE_URL = f"{BASE_URL}/services/aigc/text2image/image-synthesis"   # async t2i
MULTIMODAL_URL = f"{BASE_URL}/services/aigc/multimodal-generation/generation"  # sync t2i/edit/tts
IMAGE_EDIT_URL = MULTIMODAL_URL  # backwards-compatible alias
VIDEO_SYNTH_URL = f"{BASE_URL}/services/aigc/video-generation/video-synthesis"
TEXT2AUDIO_URL = f"{BASE_URL}/services/aigc/text2audio/generation"        # async tts
TASK_URL = f"{BASE_URL}/tasks/{{task_id}}"

# OpenAI-compatible chat (Qwen LLM for story steps)
CHAT_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

# ---------------------------------------------------------------------------
# Model registry.
#
# Chains are tried in order; on quota exhaustion / model-not-found the client
# walks to the next entry, so the pipeline survives per-model free-quota
# ceilings and catalog differences between accounts. Every entry is
# env-overridable (comma-separated for chains) so smoke-test findings can be
# applied without code edits: run `python -m scripts.smoke_test` first.
# ---------------------------------------------------------------------------
def _chain(env, default):
    raw = os.getenv(env, "")
    return [m.strip() for m in raw.split(",") if m.strip()] or default


LLM_MODEL = os.getenv("LLM_MODEL", "qwen3.7-max")
LLM_FALLBACKS = _chain("LLM_FALLBACKS", ["qwen3-max", "qwen-plus"])

# First frames. "async" entries use the text2image task endpoint,
# "sync" entries the multimodal endpoint (z-image-turbo shape).
# Smoke-tested 2026-07-04: wan2.2-t2i-flash + z-image-turbo PASS;
# wan2.6-t2i / qwen-image-2.0-pro are not served at this endpoint ("url error").
T2I_CHAIN = _chain("T2I_CHAIN", ["wan2.2-t2i-flash", "z-image-turbo"])
T2I_SYNC_MODELS = {"z-image-turbo"}          # models needing the sync shape

# Last-frame image editing. happyhorse i2v is first-frame-only, so last
# frames are OFF by default; flip NEED_LAST_FRAME if using a first+last model.
EDIT_MODEL = os.getenv("EDIT_MODEL", "qwen-image-edit")
NEED_LAST_FRAME = os.getenv("NEED_LAST_FRAME", "0") == "1"

# Clips. happyhorse-1.1-i2v: first-frame-only, 3-15s, 720P/1080P, media shape.
# wan*-i2v-flash models use the img_url shape (handled by the client).
I2V_CHAIN = _chain("I2V_CHAIN", ["happyhorse-1.1-i2v", "wan2.6-i2v-flash",
                                 "wan2.2-i2v-flash"])
I2V_FIRSTLAST_MODEL = os.getenv("I2V_FIRSTLAST_MODEL", "")  # e.g. wan2.7-i2v if available

# Voice synthesis. TTS_API_STYLE: "sync" = multimodal endpoint (qwen3-tts
# shape), "async" = text2audio task endpoint (cosyvoice shape).
# Smoke-tested 2026-07-04: qwen3-tts-flash PASS; cosyvoice-v3-plus is not
# reachable over these REST endpoints (it uses a WebSocket API on intl).
TTS_MODEL = os.getenv("TTS_MODEL", "qwen3-tts-flash")
TTS_API_STYLE = os.getenv("TTS_API_STYLE", "sync")
TTS_FALLBACK_MODEL = os.getenv("TTS_FALLBACK_MODEL", "qwen3-tts-flash")
TTS_FALLBACK_STYLE = "sync"
TTS_LANGUAGE = "Auto"

# ---------------------------------------------------------------------------
# Runtime budget (master constraint: ~2-3 minute playthrough)
# ---------------------------------------------------------------------------
TARGET_SECONDS = 150          # aim for a single-playthrough runtime
DURATION_MIN_TOTAL = 120      # accepted band lower bound
DURATION_MAX_TOTAL = 180      # accepted band upper bound
CLIP_SECONDS_DEFAULT = 10     # per-clip default
CLIP_SECONDS_MIN = 3          # happyhorse-1.1-i2v allows 3-15s
CLIP_SECONDS_MAX = 15
SECONDS_PER_SCENE = 11        # used to derive target scene count

# Derived target / cap on number of scenes
TARGET_MAIN_SCENES = round(TARGET_SECONDS / SECONDS_PER_SCENE)  # ~14
MAX_SCENES = 16               # main-path + a few branch alternatives

# Web-mode hard caps (server clamps user requests to these)
WEB_MAX_TARGET_SECONDS = int(os.getenv("WEB_MAX_TARGET_SECONDS", "150"))
WEB_MAX_SCENES = int(os.getenv("WEB_MAX_SCENES", "12"))

# Rough per-unit prices (USD) for the preview cost estimate shown to the user.
PRICE_PER_IMAGE = 0.03
PRICE_PER_VIDEO_SECOND = 0.08
PRICE_PER_TTS_CALL = 0.002


def estimate_cost(graph):
    """Rough spend estimate for the media phase of a scene graph (USD)."""
    scenes = graph.get("scenes", [])
    n = len(scenes)
    video_secs = sum(int(s.get("duration", CLIP_SECONDS_DEFAULT)) for s in scenes)
    images = n * (2 if NEED_LAST_FRAME else 1)
    tts_calls = n + len(graph.get("intro", {}).get("narration", []) or [""])
    return round(images * PRICE_PER_IMAGE
                 + video_secs * PRICE_PER_VIDEO_SECOND
                 + tts_calls * PRICE_PER_TTS_CALL, 2)


# ---------------------------------------------------------------------------
# Media defaults (conservative for free-plan friendliness)
# ---------------------------------------------------------------------------
RESOLUTION = "720P"           # "720P" or "1080P"
IMAGE_SIZE = "1280*720"       # 16:9 frame size (w*h)
RATIO = "16:9"
WATERMARK = False             # frames; clips set separately
CLIP_WATERMARK = False

# ---------------------------------------------------------------------------
# Reliability / rate-limit handling
# ---------------------------------------------------------------------------
POLL_INTERVAL = 10            # seconds between task polls
TASK_TIMEOUT = 900            # max seconds to wait per async task
SUBMIT_MAX_RETRIES = 5        # retries on throttling/5xx for submit
BACKOFF_BASE = 4              # seconds; exponential backoff base
CONCURRENCY = 1               # submit one task at a time

# ---------------------------------------------------------------------------
# Filesystem layout. Module-level defaults point at the repo root (CLI mode);
# configure_job() re-derives everything under a job dir (server mode).
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = ROOT / "examples"


def _set_paths(base: Path):
    global BUILD_DIR, FRAMES_DIR, CLIPS_DIR, MONO_DIR, SCRIPT_MD, SCENES_JSON
    global URLS_JSON, RENPY_DIR, VOICE_DIR, IDEA_TXT
    BUILD_DIR = base / "build"
    FRAMES_DIR = BUILD_DIR / "frames"
    CLIPS_DIR = BUILD_DIR / "clips"
    MONO_DIR = BUILD_DIR / "monologue"
    SCRIPT_MD = BUILD_DIR / "script.md"
    SCENES_JSON = BUILD_DIR / "scenes.json"
    URLS_JSON = BUILD_DIR / "urls.json"
    RENPY_DIR = base / "renpy_project"
    VOICE_DIR = RENPY_DIR / "game" / "voice"
    IDEA_TXT = BUILD_DIR / "idea.txt"


_set_paths(ROOT)
# CLI default: keep the historical idea location so old commands still work.
IDEA_TXT = EXAMPLES_DIR / "idea.txt"


def configure_job(job_dir):
    """Isolate all pipeline inputs/outputs under one job directory.

    Called by the web server before each job so runs never share artifacts
    (stale scene-id collisions previously caused subtitle/voice mismatches).
    """
    base = Path(job_dir)
    _set_paths(base)
    ensure_dirs()
    return base


# Ren'Py SDK executable (for optional auto-lint). Override with RENPY_EXE.
_DEFAULT_RENPY = ("/opt/renpy-sdk/renpy.sh" if sys.platform.startswith("linux")
                  else r"C:\Users\guowi\Downloads\renpy-8.3.4-sdk\renpy.exe")
RENPY_EXE = os.getenv("RENPY_EXE", _DEFAULT_RENPY)


def ensure_dirs():
    for d in (BUILD_DIR, FRAMES_DIR, CLIPS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def require_api_key():
    if not DASHSCOPE_API_KEY:
        raise SystemExit(
            "DASHSCOPE_API_KEY is not set. In PowerShell:\n"
            '  $env:DASHSCOPE_API_KEY="sk-..."'
        )
    return DASHSCOPE_API_KEY

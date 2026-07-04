"""Central configuration for the story -> Ren'Py pipeline.

Everything tunable lives here: API endpoints, model names, runtime budget,
guardrails, and filesystem layout. The whole pipeline runs on a single
DASHSCOPE_API_KEY.
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Auth (single key for the entire pipeline)
# ---------------------------------------------------------------------------
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
# DashScope native (image + video tasks)
BASE_URL = "https://dashscope-intl.aliyuncs.com/api/v1"
TEXT2IMAGE_URL = f"{BASE_URL}/services/aigc/text2image/image-synthesis"  # qwen-image async
# Synchronous multimodal endpoint, shared by z-image-turbo (t2i) and qwen-image-edit
MULTIMODAL_URL = f"{BASE_URL}/services/aigc/multimodal-generation/generation"
IMAGE_EDIT_URL = MULTIMODAL_URL  # backwards-compatible alias
VIDEO_SYNTH_URL = f"{BASE_URL}/services/aigc/video-generation/video-synthesis"
TASK_URL = f"{BASE_URL}/tasks/{{task_id}}"

# OpenAI-compatible chat (Qwen LLM for story steps)
CHAT_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
LLM_MODEL = "qwen3-max"            # story brain (configurable: qwen-plus is cheaper)
T2I_MODEL = "z-image-turbo"        # first frame (cheapest text-to-image, $0.015/img)
EDIT_MODEL = "qwen-image-edit"     # last frame (cheapest image edit, $0.045/img)
I2V_MODEL = "wan2.7-i2v"           # clip generation (first+last frame i2v)
I2V_FLASH_MODEL = os.getenv("I2V_FLASH_MODEL", "wan2.6-i2v-flash")  # first-frame-only fallback (env-overridable to hop free quotas)
TTS_MODEL = "qwen3-tts-flash"      # narration voice-over
TTS_VOICE = "Cherry"               # narrator voice (intro)
CHAR_VOICE = "Kai"                 # main character's inner-monologue voice
TTS_LANGUAGE = "Auto"

# ---------------------------------------------------------------------------
# Runtime budget (master constraint: ~2-3 minute playthrough)
# ---------------------------------------------------------------------------
TARGET_SECONDS = 150          # aim for a single-playthrough runtime
DURATION_MIN_TOTAL = 120      # accepted band lower bound
DURATION_MAX_TOTAL = 180      # accepted band upper bound
CLIP_SECONDS_DEFAULT = 10     # per-clip default (conservative; model allows 15)
CLIP_SECONDS_MIN = 3          # wan2.7-i2v min
CLIP_SECONDS_MAX = 15         # wan2.7-i2v max
SECONDS_PER_SCENE = 11        # used to derive target scene count

# Derived target / cap on number of scenes
TARGET_MAIN_SCENES = round(TARGET_SECONDS / SECONDS_PER_SCENE)  # ~14
MAX_SCENES = 16               # main-path + a few branch alternatives

# ---------------------------------------------------------------------------
# Media defaults (conservative for free-plan friendliness)
# ---------------------------------------------------------------------------
RESOLUTION = "720P"           # "720P" or "1080P"
IMAGE_SIZE = "1280*720"       # 16:9 frame size for z-image-turbo (w*h, 512-2048)
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
# Filesystem layout
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent   # C:\qwen
BUILD_DIR = ROOT / "build"
FRAMES_DIR = BUILD_DIR / "frames"
CLIPS_DIR = BUILD_DIR / "clips"
MONO_DIR = BUILD_DIR / "monologue"
SCRIPT_MD = BUILD_DIR / "script.md"
SCENES_JSON = BUILD_DIR / "scenes.json"
URLS_JSON = BUILD_DIR / "urls.json"
RENPY_DIR = ROOT / "renpy_project"
VOICE_DIR = RENPY_DIR / "game" / "voice"
EXAMPLES_DIR = ROOT / "examples"

# Ren'Py SDK executable (for optional auto-lint). Override with RENPY_EXE env var.
RENPY_EXE = os.getenv(
    "RENPY_EXE",
    r"C:\Users\guowi\Downloads\renpy-8.3.4-sdk\renpy.exe",
)


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

"""Shared Qwen/DashScope client used by every pipeline step.

Wraps the three call shapes the pipeline needs:
  * async tasks (text-to-image, image-to-video): submit -> poll -> result
  * synchronous image edit (multimodal-generation)
  * OpenAI-compatible chat (Qwen LLM) with JSON output

Includes throttling backoff and an auto-downgrade helper for video so the
pipeline survives unknown free-plan ceilings.
"""

import json
import time

import requests

from . import config


class QwenError(RuntimeError):
    """Carries the DashScope error code so callers can react (e.g. downgrade)."""

    def __init__(self, message, code=None, http_status=None):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


def _auth_headers(async_task=False):
    h = {
        "Authorization": f"Bearer {config.require_api_key()}",
        "Content-Type": "application/json",
    }
    if async_task:
        h["X-DashScope-Async"] = "enable"
    return h


def _is_throttle(http_status, code):
    if http_status == 429:
        return True
    if code and ("throttl" in code.lower() or "limit" in code.lower()
                 or "flow" in code.lower()):
        return True
    return http_status is not None and 500 <= http_status < 600


# ---------------------------------------------------------------------------
# Async tasks (image-synthesis, video-synthesis)
# ---------------------------------------------------------------------------
def submit_async(url, payload):
    """Submit an async task with throttle/5xx backoff. Returns task_id."""
    last_exc = None
    for attempt in range(config.SUBMIT_MAX_RETRIES):
        resp = requests.post(url, headers=_auth_headers(async_task=True),
                             json=payload, timeout=120)
        if resp.status_code == 200:
            data = resp.json()
            task_id = data.get("output", {}).get("task_id")
            if not task_id:
                raise QwenError(f"No task_id in response: {data}")
            return task_id

        code, message = _error_fields(resp)
        if _is_throttle(resp.status_code, code):
            wait = config.BACKOFF_BASE * (2 ** attempt)
            print(f"  throttled ({resp.status_code}/{code}); retry in {wait}s")
            time.sleep(wait)
            last_exc = QwenError(message, code, resp.status_code)
            continue
        raise QwenError(message, code, resp.status_code)
    raise last_exc or QwenError("submit failed after retries")


def poll_task(task_id, interval=None, timeout=None):
    """Poll an async task until terminal. Returns the output dict on success."""
    interval = interval or config.POLL_INTERVAL
    timeout = timeout or config.TASK_TIMEOUT
    url = config.TASK_URL.format(task_id=task_id)
    deadline = time.time() + timeout
    while True:
        resp = requests.get(url, headers=_auth_headers(), timeout=60)
        if resp.status_code != 200:
            code, message = _error_fields(resp)
            raise QwenError(f"poll failed: {message}", code, resp.status_code)
        output = resp.json().get("output", {})
        status = output.get("task_status")
        if status == "SUCCEEDED":
            return output
        if status in ("FAILED", "CANCELED", "UNKNOWN"):
            raise QwenError(
                f"task {status}: code={output.get('code')} "
                f"message={output.get('message')}",
                output.get("code"),
            )
        if time.time() > deadline:
            raise TimeoutError(f"task {task_id} not done within {timeout}s "
                               f"(last status {status})")
        print(f"  status={status} ... waiting {interval}s")
        time.sleep(interval)


def _error_fields(resp):
    try:
        d = resp.json()
        return d.get("code"), d.get("message", resp.text)
    except Exception:
        return None, resp.text


# ---------------------------------------------------------------------------
# Synchronous multimodal generation (z-image-turbo t2i + qwen-image-edit)
# ---------------------------------------------------------------------------
def _multimodal_raw(payload):
    """POST to the synchronous multimodal endpoint with backoff. Returns JSON dict."""
    last_exc = None
    for attempt in range(config.SUBMIT_MAX_RETRIES):
        resp = requests.post(config.MULTIMODAL_URL, headers=_auth_headers(),
                             json=payload, timeout=180)
        if resp.status_code == 200:
            return resp.json()
        code, message = _error_fields(resp)
        if _is_throttle(resp.status_code, code):
            wait = config.BACKOFF_BASE * (2 ** attempt)
            print(f"  multimodal throttled ({resp.status_code}/{code}); retry in {wait}s")
            time.sleep(wait)
            last_exc = QwenError(message, code, resp.status_code)
            continue
        raise QwenError(message, code, resp.status_code)
    raise last_exc or QwenError("multimodal call failed after retries")


def _multimodal_call(payload):
    """Multimodal call returning a generated image URL."""
    return _extract_image_url(_multimodal_raw(payload))


def tts(text, voice, language_type=None, model=None, style=None):
    """Synthesize speech. Returns an audio URL (valid ~24h).

    Dispatches between the two DashScope TTS shapes and falls back from the
    primary model (cosyvoice, async text2audio) to the fallback (qwen3-tts,
    sync multimodal) when the primary is unavailable on this account.
    """
    attempts = [(model or config.TTS_MODEL, style or config.TTS_API_STYLE, voice)]
    if model is None:  # only auto-fallback when the caller didn't pin a model
        attempts.append((config.TTS_FALLBACK_MODEL, config.TTS_FALLBACK_STYLE, voice))
    last_exc = None
    for mdl, sty, vc in attempts:
        try:
            if sty == "async":
                return _tts_async(text, vc, mdl)
            return _tts_sync(text, vc, mdl, language_type)
        except QwenError as e:
            if _is_model_unavailable(e) or _is_quota(e):
                print(f"  tts model {mdl} unavailable ({e.code}); trying fallback")
                last_exc = e
                continue
            raise
    raise last_exc or QwenError("tts failed")


def _tts_sync(text, voice, model, language_type=None):
    """qwen3-tts shape on the synchronous multimodal endpoint."""
    payload = {
        "model": model,
        "input": {
            "text": text[:600],
            "voice": voice,
            "language_type": language_type or config.TTS_LANGUAGE,
        },
    }
    data = _multimodal_raw(payload)
    try:
        return data["output"]["audio"]["url"]
    except (KeyError, TypeError):
        raise QwenError(f"no audio url in TTS response: {data}")


def _tts_async(text, voice, model):
    """cosyvoice shape on the async text2audio endpoint."""
    payload = {
        "model": model,
        "input": {"text": text[:600]},
        "parameters": {"voice": voice},
    }
    task_id = submit_async(config.TEXT2AUDIO_URL, payload)
    output = poll_task(task_id)
    url = (output.get("audio_url")
           or (output.get("audio") or {}).get("url")
           or ((output.get("results") or [{}])[0]).get("url"))
    if not url:
        raise QwenError(f"no audio url in async TTS result: {output}")
    return url


def _extract_image_url(data):
    try:
        content = data["output"]["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        raise QwenError(f"unexpected image response: {data}")
    for part in content:
        if isinstance(part, dict) and part.get("image"):
            return part["image"]
    raise QwenError(f"no image in response: {data}")


def text_to_image(prompt, size=None, seed=None):
    """First frame. Walks config.T2I_CHAIN (async task models first, sync
    multimodal models like z-image-turbo as fallback). Returns the image URL.

    prompt_extend=False keeps it at the cheapest tier; our prompts are already
    fully specified (style + character appearance).
    """
    last_exc = None
    for model in config.T2I_CHAIN:
        try:
            if model in config.T2I_SYNC_MODELS:
                return _t2i_sync(model, prompt, size, seed)
            return _t2i_async(model, prompt, size, seed)
        except QwenError as e:
            if _is_model_unavailable(e) or _is_quota(e):
                print(f"  t2i model {model} unavailable ({e.code}); trying next")
                last_exc = e
                continue
            raise
    raise last_exc or QwenError("t2i failed: chain exhausted")


def _t2i_async(model, prompt, size=None, seed=None):
    """Async text2image task shape (wan2.6-t2i and friends)."""
    parameters = {"size": size or config.IMAGE_SIZE, "n": 1,
                  "prompt_extend": False}
    if seed is not None:
        parameters["seed"] = seed
    payload = {
        "model": model,
        "input": {"prompt": prompt},
        "parameters": parameters,
    }
    task_id = submit_async(config.TEXT2IMAGE_URL, payload)
    output = poll_task(task_id)
    results = output.get("results") or []
    url = results[0].get("url") if results else None
    if not url:
        raise QwenError(f"no image url in t2i result: {output}")
    return url


def _t2i_sync(model, prompt, size=None, seed=None):
    """Synchronous multimodal shape (z-image-turbo)."""
    parameters = {"prompt_extend": False, "size": size or config.IMAGE_SIZE}
    if seed is not None:
        parameters["seed"] = seed
    payload = {
        "model": model,
        "input": {"messages": [{"role": "user",
                                "content": [{"text": prompt}]}]},
        "parameters": parameters,
    }
    return _multimodal_call(payload)


def image_edit(image_url, instruction, seed=None, negative_prompt=" "):
    """Last frame via qwen-image-edit (synchronous). Returns the new image URL.

    Output aspect ratio follows the input image, so the last frame matches the
    first frame's dimensions (no size param needed).
    """
    parameters = {"negative_prompt": negative_prompt, "prompt_extend": True}
    if seed is not None:
        parameters["seed"] = seed
    payload = {
        "model": config.EDIT_MODEL,
        "input": {"messages": [{
            "role": "user",
            "content": [{"image": image_url}, {"text": instruction}],
        }]},
        "parameters": parameters,
    }
    return _multimodal_call(payload)


# ---------------------------------------------------------------------------
# High-level: image-to-video first+last (clip), with auto-downgrade
# ---------------------------------------------------------------------------
def _i2v_with_downgrade(make_payload, resolution, duration):
    """Run an i2v task, downgrading (res, then duration) on limit rejections."""
    resolution = resolution or config.RESOLUTION
    duration = max(config.CLIP_SECONDS_MIN, min(config.CLIP_SECONDS_MAX, int(duration)))
    attempts = _downgrade_plan(resolution, duration)
    last_exc = None
    for res, dur in attempts:
        try:
            task_id = submit_async(config.VIDEO_SYNTH_URL, make_payload(res, dur))
            output = poll_task(task_id)
            url = output.get("video_url")
            if not url:
                raise QwenError(f"no video_url in result: {output}")
            return url
        except QwenError as e:
            if _is_quota(e):
                raise QwenError(
                    "Free quota for the video model is exhausted. Enable paid "
                    "billing (disable 'use free tier only' in the Qwen console) "
                    "then re-run; completed clips are skipped on resume.",
                    e.code, e.http_status)
            if _is_limit_param(e) and (res, dur) != attempts[-1]:
                print(f"  i2v rejected ({e.code}); downgrading from {res}/{dur}s")
                last_exc = e
                continue
            raise
    raise last_exc or QwenError("i2v failed")


def image_to_video(first_url, last_url, prompt, duration,
                   resolution=None, watermark=None):
    """Clip from first+last frames (wan2.7-i2v class). Returns the video URL.

    Only used when config.I2V_FIRSTLAST_MODEL is set; the default chain is
    first-frame-only (happyhorse).
    """
    watermark = config.CLIP_WATERMARK if watermark is None else watermark

    def make(res, dur):
        return {
            "model": config.I2V_FIRSTLAST_MODEL,
            "input": {"prompt": prompt, "media": [
                {"type": "first_frame", "url": first_url},
                {"type": "last_frame", "url": last_url},
            ]},
            "parameters": {"resolution": res, "duration": dur,
                           "prompt_extend": False, "watermark": watermark},
        }
    return _i2v_with_downgrade(make, resolution, duration)


def image_to_video_first(img_url, prompt, duration, resolution=None,
                         watermark=None, model=None):
    """Clip from a single first frame. Returns the video URL.

    Two request shapes exist for first-frame-only models:
      * happyhorse-*: `input.media` with a first_frame entry
      * wan*-i2v-flash: `input.img_url`
    """
    watermark = config.CLIP_WATERMARK if watermark is None else watermark
    model = model or config.I2V_CHAIN[0]

    def make(res, dur):
        if model.startswith("happyhorse"):
            return {
                "model": model,
                "input": {"prompt": prompt,
                          "media": [{"type": "first_frame", "url": img_url}]},
                "parameters": {"resolution": res, "duration": dur,
                               "watermark": watermark},
            }
        return {
            "model": model,
            "input": {"img_url": img_url, "prompt": prompt},
            "parameters": {"resolution": res, "duration": dur,
                           "prompt_extend": True, "watermark": watermark},
        }
    return _i2v_with_downgrade(make, resolution, duration)


def generate_clip(img_url, prompt, duration, resolution=None, watermark=None):
    """Generate a clip from a first frame, walking config.I2V_CHAIN.

    A model whose quota is exhausted (or that this account can't access) is
    skipped in favor of the next one; the friendly quota message is raised
    only when every model in the chain is spent.
    """
    last_exc = None
    for model in config.I2V_CHAIN:
        try:
            return image_to_video_first(img_url, prompt, duration,
                                        resolution=resolution,
                                        watermark=watermark, model=model)
        except QwenError as e:
            if _is_quota(e) or _is_model_unavailable(e):
                print(f"  i2v model {model} unavailable/spent ({e.code}); trying next")
                last_exc = e
                continue
            raise
    raise QwenError(
        "All video models in I2V_CHAIN are exhausted or unavailable. Enable "
        "paid billing in the Qwen console (or extend I2V_CHAIN) and re-run; "
        "completed clips are skipped on resume.",
        getattr(last_exc, "code", None), getattr(last_exc, "http_status", None))


def _downgrade_plan(resolution, duration):
    """Ordered (resolution, duration) attempts from requested down to minimal."""
    plan = [(resolution, duration)]
    if resolution == "1080P":
        plan.append(("720P", duration))
    shorter = max(config.CLIP_SECONDS_MIN, min(duration, 5))
    if shorter != duration:
        plan.append((plan[-1][0], shorter))
    return plan


def _is_quota(err):
    c = (err.code or "").lower()
    m = str(err).lower()
    return "quota" in c or "free quota" in m or "exhaust" in m


def _is_model_unavailable(err):
    """Model not in this account's catalog (name unknown or no access)."""
    c = (err.code or "").lower()
    m = str(err).lower()
    if err.http_status in (401, 403, 404) and "model" in m:
        return True
    return ("model" in m and ("not exist" in m or "cannot be found" in m
                              or "unsupported" in m or "access" in m
                              or "no permission" in m)) or "invalidmodel" in c


def _is_limit_param(err):
    if _is_quota(err):
        return False
    if not err.code:
        return err.http_status == 400
    c = err.code.lower()
    return "invalidparameter" in c or "limit" in c


# ---------------------------------------------------------------------------
# Download helper
# ---------------------------------------------------------------------------
def download(url, path):
    with requests.get(url, stream=True, timeout=300) as resp:
        resp.raise_for_status()
        with open(path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 16):
                if chunk:
                    f.write(chunk)
    return path


# ---------------------------------------------------------------------------
# OpenAI-compatible chat (Qwen LLM) with JSON output
# ---------------------------------------------------------------------------
_openai_client = None


def _chat_client():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        _openai_client = OpenAI(api_key=config.require_api_key(),
                                base_url=config.CHAT_BASE_URL)
    return _openai_client


def _llm_candidates(model=None):
    if model:
        return [model]
    return [config.LLM_MODEL] + list(config.LLM_FALLBACKS)


def chat_text(system, user, model=None, temperature=0.8, max_tokens=8000,
              response_format=None):
    """Plain text chat completion. Returns the assistant message string.

    Falls back across config.LLM_FALLBACKS if the primary model name is not
    in this account's catalog.
    """
    extra = {"response_format": response_format} if response_format else {}
    last_exc = None
    for mdl in _llm_candidates(model):
        try:
            resp = _chat_client().chat.completions.create(
                model=mdl,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                temperature=temperature,
                max_tokens=max_tokens,
                **extra,
            )
            config.LLM_MODEL = mdl  # pin the working model for later calls
            return resp.choices[0].message.content
        except Exception as e:
            if _looks_like_bad_model(e):
                print(f"  chat model {mdl} unavailable; trying next")
                last_exc = e
                continue
            raise
    raise last_exc


def _looks_like_bad_model(exc):
    m = str(exc).lower()
    return "model" in m and ("not exist" in m or "invalid" in m
                             or "access" in m or "not found" in m)


def chat_json(system, user, model=None, temperature=0.5, max_tokens=8000,
              retries=2):
    """Chat completion constrained to a JSON object. Returns a parsed dict."""
    sys_json = system + ("\n\nRespond with a SINGLE valid JSON object and "
                         "nothing else. Do not wrap it in markdown fences.")
    last_err = None
    for attempt in range(retries + 1):
        text = chat_text(sys_json, user, model=model,
                         temperature=temperature, max_tokens=max_tokens,
                         response_format={"type": "json_object"})
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            last_err = e
            text = _strip_fences(text)
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                print(f"  JSON parse failed (attempt {attempt + 1}); retrying")
                continue
    raise QwenError(f"LLM did not return valid JSON: {last_err}")


def _strip_fences(text):
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()

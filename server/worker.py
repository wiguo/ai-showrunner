"""Single background worker that runs pipeline jobs sequentially.

Concurrency is intentionally 1: the pipeline mutates pipeline.config module
globals (configure_job) and the Qwen free tier dislikes parallel media tasks.

Phase A ("writing", costs cents): step1 screenplay -> step2 scene graph ->
intro narration, then the job parks at awaiting_confirmation with a cost
estimate so the user approves before any media spend.
Phase B ("generating"): frames -> clips -> monologue -> narrator voice ->
Ren'Py assembly -> zip.
"""

import json
import queue
import threading
import traceback

from pipeline import (config, step1_expand, step2_scenes, step_intro,
                      step3_frames, step4_clips, step_monologue,
                      step5_renpy, step6_voice)
from . import jobs, packaging

_queue = queue.Queue()
_started = False


def start():
    global _started
    if not _started:
        threading.Thread(target=_loop, daemon=True, name="pipeline-worker").start()
        _started = True


def enqueue(job_id, phase):
    jobs.update_status(job_id, stage="queued" if phase == "A" else "queued_media")
    _queue.put((job_id, phase))


def queue_size():
    return _queue.qsize()


def _loop():
    while True:
        job_id, phase = _queue.get()
        try:
            if phase == "A":
                _phase_a(job_id)
            else:
                _phase_b(job_id)
        except BaseException as e:  # SystemExit included: steps use it for errors
            if isinstance(e, (KeyboardInterrupt,)):
                raise
            traceback.print_exc()
            jobs.update_status(job_id, stage="error", error=_friendly(e))
        finally:
            _queue.task_done()


def _friendly(exc):
    msg = str(exc)
    low = msg.lower()
    if "quota" in low or "exhaust" in low:
        return ("Model quota is exhausted. The operator needs to top up the "
                "Qwen Cloud account, then this job can be resumed. " + msg)
    if "throttl" in low or "429" in low:
        return "The model API is rate-limiting; try again in a minute. " + msg
    return msg


def _configure(job_id):
    d = jobs.job_dir(job_id)
    config.configure_job(d)
    status = jobs.read_status(job_id)
    target = int(status.get("target_seconds") or config.TARGET_SECONDS)
    target = min(target, config.WEB_MAX_TARGET_SECONDS)
    config.TARGET_SECONDS = target
    config.TARGET_MAIN_SCENES = round(target / config.SECONDS_PER_SCENE)
    config.DURATION_MIN_TOTAL = int(target * 0.85)
    config.DURATION_MAX_TOTAL = int(target * 1.2)
    config.MAX_SCENES = config.WEB_MAX_SCENES
    return status


def _phase_a(job_id):
    status = _configure(job_id)
    jobs.update_status(job_id, stage="writing")
    step1_expand.run(idea_text=status["story"])
    step2_scenes.run()
    step_intro.run(resume=True)
    graph = json.loads(config.SCENES_JSON.read_text(encoding="utf-8"))
    jobs.update_status(job_id, stage="awaiting_confirmation",
                       estimated_cost=config.estimate_cost(graph))


def _phase_b(job_id):
    _configure(job_id)
    jobs.update_status(job_id, stage="generating")
    step3_frames.run(resume=True)
    step4_clips.run(resume=True)
    step_monologue.run(resume=True)
    step6_voice.run(resume=True)
    jobs.update_status(job_id, stage="packaging")
    step5_renpy.run()
    zip_path = packaging.package(job_id)
    jobs.update_status(job_id, stage="done", zip=str(zip_path))
    jobs.gc_old_jobs()

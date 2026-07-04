"""Job store: one directory per job, progress derived from files on disk.

Layout: jobs/<id>/{build/, renpy_project/, status.json, game.zip}

The pipeline needs zero instrumentation for live progress — each stage leaves
files behind (frames/<sid>_first.png, clips/<sid>.mp4, monologue/<sid>_all.ogg,
renpy_project/game/movies/<sid>.webm), so scanning the job dir tells the UI
exactly which scene is at which stage.
"""

import json
import re
import time
import uuid
from pathlib import Path

JOBS_ROOT = Path(__file__).resolve().parent.parent / "jobs"

# stage values, in order
STAGES = ["queued", "writing", "awaiting_confirmation", "queued_media",
          "generating", "packaging", "done", "error"]


def new_job(story, target_seconds):
    job_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    d = JOBS_ROOT / job_id
    (d / "build").mkdir(parents=True, exist_ok=True)
    write_status(job_id, {
        "id": job_id,
        "story": story,
        "target_seconds": target_seconds,
        "created": time.time(),
        "stage": "queued",
        "error": None,
    })
    return job_id


def job_dir(job_id):
    if not re.fullmatch(r"[0-9]{8}-[0-9]{6}-[0-9a-f]{6}", job_id):
        raise KeyError(f"bad job id: {job_id}")
    d = JOBS_ROOT / job_id
    if not d.is_dir():
        raise KeyError(f"unknown job: {job_id}")
    return d


def read_status(job_id):
    p = job_dir(job_id) / "status.json"
    return json.loads(p.read_text(encoding="utf-8"))


def write_status(job_id, status):
    p = JOBS_ROOT / job_id / "status.json"
    p.write_text(json.dumps(status, indent=2), encoding="utf-8")


def update_status(job_id, **fields):
    status = read_status(job_id)
    status.update(fields)
    write_status(job_id, status)
    return status


def _graph(d):
    p = d / "build" / "scenes.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
    return None


def progress(job_id):
    """Full status for the UI: stage + preview + per-scene media progress."""
    d = job_dir(job_id)
    status = read_status(job_id)
    build = d / "build"
    out = dict(status)
    out.pop("story", None)  # UI already has it; keep payload small

    graph = _graph(d)
    if graph:
        out["title"] = graph.get("title")
        scenes = []
        for sid, s in (graph.get("scenes") or {}).items():
            scenes.append({
                "id": sid,
                "summary": s.get("summary", ""),
                "duration": s.get("duration"),
                "is_choice": len(s.get("choices") or []) >= 2,
                "frame": (build / "frames" / f"{sid}_first.png").exists(),
                "clip": (build / "clips" / f"{sid}.mp4").exists(),
                "voiced": (build / "monologue" / f"{sid}_all.ogg").exists(),
                "movie": (d / "renpy_project" / "game" / "movies" / f"{sid}.webm").exists(),
            })
        out["scenes"] = scenes
        out["characters"] = [
            {"name": c.get("name"), "gender": c.get("gender"),
             "appearance": c.get("appearance", "")}
            for c in graph.get("characters", [])]
        out["intro"] = (graph.get("intro") or {}).get("narration")

    script = build / "script.md"
    if script.exists():
        out["script_excerpt"] = script.read_text(encoding="utf-8")[:1500]
    lint = build / "lint.txt"
    if lint.exists():
        out["lint"] = lint.read_text(encoding="utf-8")[-1000:]
    zip_path = d / "game.zip"
    if zip_path.exists():
        out["zip_bytes"] = zip_path.stat().st_size
    return out


def gc_old_jobs(max_age_hours=24):
    """Delete job dirs older than max_age_hours (called opportunistically)."""
    import shutil
    if not JOBS_ROOT.is_dir():
        return
    cutoff = time.time() - max_age_hours * 3600
    for d in JOBS_ROOT.iterdir():
        try:
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass

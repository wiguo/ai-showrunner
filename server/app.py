"""AI Showrunner web API: story in -> playable Ren'Py game zip out.

Endpoints:
  POST /jobs                  {story, target_seconds?} -> {id}
  GET  /jobs/{id}             status + preview + per-scene progress
  POST /jobs/{id}/confirm     approve media spend (phase B)
  GET  /jobs/{id}/asset/{n}   frame thumbnails / script.md
  GET  /jobs/{id}/download    the finished game zip
  GET  /                      single-page UI (server/static/)

Run: uvicorn server.app:app --host 0.0.0.0 --port 8080
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from pipeline import config
from . import jobs, worker

app = FastAPI(title="AI Showrunner", version="1.0")
STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.on_event("startup")
def _startup():
    if not config.DASHSCOPE_API_KEY:
        print("WARNING: DASHSCOPE_API_KEY is not set; jobs will fail at once.")
    worker.start()


class NewJob(BaseModel):
    story: str = Field(min_length=8, max_length=4000)
    target_seconds: int | None = Field(default=None, ge=30, le=600)


@app.post("/jobs")
def create_job(req: NewJob):
    target = min(req.target_seconds or config.TARGET_SECONDS,
                 config.WEB_MAX_TARGET_SECONDS)
    job_id = jobs.new_job(req.story.strip(), target)
    worker.enqueue(job_id, "A")
    return {"id": job_id, "queue": worker.queue_size()}


def _get(job_id):
    try:
        return jobs.progress(job_id)
    except KeyError:
        raise HTTPException(404, "unknown job")


@app.get("/jobs/{job_id}")
def job_status(job_id: str):
    return _get(job_id)


@app.post("/jobs/{job_id}/confirm")
def confirm(job_id: str):
    status = _get(job_id)
    if status["stage"] not in ("awaiting_confirmation", "error"):
        raise HTTPException(409, f"job is {status['stage']}, not confirmable")
    # error -> confirm acts as a resume: completed artifacts are skipped.
    worker.enqueue(job_id, "B")
    return {"ok": True}


@app.get("/jobs/{job_id}/asset/{name}")
def asset(job_id: str, name: str):
    d = jobs.job_dir(job_id)
    allowed = {}
    frames = d / "build" / "frames"
    if frames.is_dir():
        for f in frames.glob("*_first.png"):
            allowed[f.name] = f
    allowed["script.md"] = d / "build" / "script.md"
    f = allowed.get(name)
    if not f or not f.exists():
        raise HTTPException(404, "no such asset")
    return FileResponse(f)


@app.get("/jobs/{job_id}/download")
def download(job_id: str):
    status = _get(job_id)
    zip_path = jobs.job_dir(job_id) / "game.zip"
    if status["stage"] != "done" or not zip_path.exists():
        raise HTTPException(409, "game is not ready yet")
    title = status.get("title") or "interactive_story"
    fname = "".join(c if c.isalnum() else "_" for c in title)[:40] + ".zip"
    return FileResponse(zip_path, media_type="application/zip", filename=fname)


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

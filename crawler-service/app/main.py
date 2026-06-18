import secrets
import uuid
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException

from .config import settings
from .queue import QUEUE_KEY, append_event, cancel_key, load_job, now_iso, redis_client, save_job
from .schemas import JobCreate, JobCreated
from .sites import public_registry_payload


app = FastAPI(title="Esports Public Research Crawler", version="1.0.0", docs_url=None, redoc_url=None)


def require_internal_token(authorization: str = Header(default="")) -> None:
    expected = f"Bearer {settings.internal_token}"
    if not settings.internal_token or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="INVALID_INTERNAL_TOKEN")


@app.on_event("startup")
def startup() -> None:
    settings.ensure_dirs()


@app.get("/v1/health")
def health(_: None = Depends(require_internal_token)):
    try:
        redis_client().ping()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"REDIS_UNAVAILABLE: {exc}") from exc
    return {"status": "ok", "service": "crawler-service", "version": "0.4.9"}


@app.get("/v1/sites")
def sites(_: None = Depends(require_internal_token)):
    return {"sites": public_registry_payload()}


@app.post("/v1/jobs", response_model=JobCreated, status_code=202)
def create_job(body: JobCreate, _: None = Depends(require_internal_token)):
    client = redis_client()
    job_id = uuid.uuid4().hex
    dedupe_key = f"crawler:dedupe:{body.evaluation_id}:{body.attempt}"
    if not client.set(dedupe_key, job_id, nx=True, ex=7 * 24 * 3600):
        existing_id = client.get(dedupe_key)
        existing = load_job(client, existing_id) if existing_id else None
        if existing:
            return JobCreated(job_id=existing_id, status=existing.get("status", "queued"))
        client.delete(dedupe_key)
        client.set(dedupe_key, job_id, nx=True, ex=7 * 24 * 3600)
    payload = body.model_dump(mode="json")
    payload.update({
        "job_id": job_id,
        "status": "queued",
        "progress": 0,
        "items": [],
        "events": [],
        "errors": [],
        "source_progress": {site: {"status": "queued", "pages": 0, "items": 0, "errors": 0} for site in body.sites},
        "created_at": now_iso(),
    })
    append_event(payload, "queued", "采集任务已进入队列")
    save_job(client, job_id, payload)
    client.rpush(QUEUE_KEY, job_id)
    return JobCreated(job_id=job_id, status="queued")


@app.get("/v1/jobs/{job_id}")
def get_job(job_id: str, _: None = Depends(require_internal_token)):
    job = load_job(redis_client(), job_id)
    if not job:
        raise HTTPException(status_code=404, detail="JOB_NOT_FOUND")
    return job


@app.post("/v1/jobs/{job_id}/cancel", status_code=202)
def cancel_job(job_id: str, _: None = Depends(require_internal_token)):
    client = redis_client()
    job = load_job(client, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="JOB_NOT_FOUND")
    if job.get("status") in {"completed", "partial_success", "failed", "cancelled"}:
        return {"job_id": job_id, "status": job["status"]}
    client.set(cancel_key(job_id), "1", ex=3600)
    job["status"] = "cancelling"
    append_event(job, "cancelling", "已请求取消任务")
    save_job(client, job_id, job)
    return {"job_id": job_id, "status": "cancelling"}

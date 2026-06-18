import json
import time
from datetime import datetime, timezone
from typing import Any

from redis import Redis

from .config import settings


QUEUE_KEY = "crawler:queue"


def redis_client() -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def job_key(job_id: str) -> str:
    return f"crawler:job:{job_id}"


def save_job(client: Redis, job_id: str, payload: dict[str, Any]) -> None:
    client.set(job_key(job_id), json.dumps(payload, ensure_ascii=False), ex=7 * 24 * 3600)


def load_job(client: Redis, job_id: str) -> dict[str, Any] | None:
    raw = client.get(job_key(job_id))
    return json.loads(raw) if raw else None


def append_event(job: dict[str, Any], event_type: str, message: str, payload: dict | None = None) -> None:
    job.setdefault("events", []).append({"type": event_type, "message": message, "payload": payload or {}, "created_at": now_iso()})
    job["events"] = job["events"][-200:]


def cancel_key(job_id: str) -> str:
    return f"crawler:cancel:{job_id}"


def wait_for_domain(client: Redis, domain: str) -> None:
    key = f"crawler:domain:last:{domain}"
    last = float(client.get(key) or 0)
    wait = settings.domain_delay_seconds - (time.time() - last)
    if wait > 0:
        time.sleep(wait)
    client.set(key, str(time.time()), ex=3600)

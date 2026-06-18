"""Deployment smoke test: queue one public example.com page and verify worker progress."""
import os
import time
from pathlib import Path

import httpx


def env_token() -> str:
    for line in (Path(__file__).parents[1] / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("CRAWLER_INTERNAL_TOKEN="):
            return line.split("=", 1)[1].strip()
    return ""


def main() -> None:
    token = os.environ.get("CRAWLER_INTERNAL_TOKEN") or env_token()
    if not token:
        raise SystemExit("CRAWLER_INTERNAL_TOKEN missing")
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "evaluation_id": 0,
        "address": "crawler deployment smoke test",
        "sources": ["official"],
        "sites": ["official"],
        "seed_urls": ["https://example.com/"],
        "max_pages": 1,
        "timeout_seconds": 60,
    }
    with httpx.Client(base_url="http://127.0.0.1:8010", headers=headers, timeout=10) as client:
        created = client.post("/v1/jobs", json=payload)
        created.raise_for_status()
        job_id = created.json()["job_id"]
        deadline = time.time() + 70
        while time.time() < deadline:
            response = client.get(f"/v1/jobs/{job_id}")
            response.raise_for_status()
            job = response.json()
            if job.get("status") in {"completed", "partial_success", "failed", "cancelled"}:
                page_events = [event for event in job.get("events", []) if event.get("type") == "page_completed"]
                if not page_events:
                    raise SystemExit(f"smoke test did not fetch public page: {job.get('errors')}")
                print(f"crawler smoke test passed: job={job_id}, status={job.get('status')}")
                return
            time.sleep(2)
    raise SystemExit("crawler smoke test timed out")


if __name__ == "__main__":
    main()

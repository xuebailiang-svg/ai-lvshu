import importlib.util
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]


def load_worker_module():
    fetching_stub = types.ModuleType("app.fetching")
    fetching_stub.fetch_page = lambda *_args, **_kwargs: ("", "")
    fetching_stub.resolve_redirect_chain = lambda url, **_kwargs: url
    sys.modules["app.fetching"] = fetching_stub

    queue_stub = types.ModuleType("app.queue")
    queue_stub.QUEUE_KEY = "crawler:queue"
    queue_stub.cancel_key = lambda job_id: f"crawler:cancel:{job_id}"
    queue_stub.now_iso = lambda: datetime.now(timezone.utc).isoformat()
    queue_stub.append_event = lambda job, event_type, message, payload=None: job.setdefault("events", []).append({"type": event_type, "message": message, "payload": payload or {}})
    queue_stub.load_job = lambda *_args: None
    queue_stub.save_job = lambda *_args: None
    queue_stub.redis_client = lambda: None
    queue_stub.wait_for_domain = lambda *_args: None
    sys.modules["app.queue"] = queue_stub

    spec = importlib.util.spec_from_file_location("crawler_worker_testable", ROOT / "worker.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class FakeRedis:
    def __init__(self, cancelled=False):
        self.cancelled = cancelled

    def get(self, key):
        return "1" if self.cancelled and "cancel" in key else None


def base_job(**overrides):
    value = {
        "job_id": "job-1",
        "status": "queued",
        "progress": 0,
        "address": "测试市中心路88号",
        "city": "测试市",
        "keywords": [],
        "sites": ["official"],
        "sources": ["official"],
        "seed_urls": ["https://brand.example/store/1", "https://brand.example/store/1"],
        "max_pages": 20,
        "timeout_seconds": 300,
        "items": [],
        "events": [],
        "errors": [],
        "source_progress": {"official": {"status": "queued", "pages": 0, "items": 0, "errors": 0}},
    }
    value.update(overrides)
    return value


def test_worker_deduplicates_duplicate_urls_and_items(monkeypatch):
    worker = load_worker_module()
    state = base_job()
    html = (ROOT / "tests" / "fixtures" / "official.html").read_text(encoding="utf-8")
    calls = []
    monkeypatch.setattr(worker, "redis_client", lambda: FakeRedis())
    monkeypatch.setattr(worker, "load_job", lambda _client, _job_id: state)
    monkeypatch.setattr(worker, "save_job", lambda _client, _job_id, job: state.update(job))
    monkeypatch.setattr(worker, "search_requests", lambda *_args: [])

    def fake_fetch(url, **_kwargs):
        calls.append(url)
        return url, html

    monkeypatch.setattr(worker, "fetch_page", fake_fetch)
    worker.process("job-1")
    assert calls == ["https://brand.example/store/1"]
    assert state["status"] == "completed"
    assert len(state["items"]) == len({item["item_id"] for item in state["items"]})


def test_worker_honors_cancel_before_discovery(monkeypatch):
    worker = load_worker_module()
    state = base_job(seed_urls=[])
    monkeypatch.setattr(worker, "redis_client", lambda: FakeRedis(cancelled=True))
    monkeypatch.setattr(worker, "load_job", lambda _client, _job_id: state)
    monkeypatch.setattr(worker, "save_job", lambda _client, _job_id, job: state.update(job))
    monkeypatch.setattr(worker, "search_requests", lambda *_args: [{"search_site": "bing", "target_site": "official", "url": "https://cn.bing.com/search?q=test"}])
    monkeypatch.setattr(worker, "fetch_page", lambda *_args, **_kwargs: pytest.fail("cancelled job must not fetch"))
    worker.process("job-1")
    assert state["status"] == "cancelled"


def test_redis_disconnect_is_exposed_for_reconnect():
    worker = load_worker_module()

    class BrokenRedis:
        def blpop(self, *_args, **_kwargs):
            raise ConnectionError("REDIS_RESTARTING")

    with pytest.raises(ConnectionError, match="REDIS_RESTARTING"):
        worker.run_next(BrokenRedis())

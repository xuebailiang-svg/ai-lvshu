import logging
import signal
import time
from urllib.parse import quote_plus, urlsplit

from app.adapters import EVIDENCE_ADAPTERS, SEARCH_ADAPTERS
from app.fetching import fetch_page, resolve_redirect_chain
from app.queue import QUEUE_KEY, append_event, cancel_key, load_job, now_iso, redis_client, save_job, wait_for_domain
from app.sites import SITE_REGISTRY, site_for_url


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("crawler-worker")


def _timeout_handler(_signum, _frame):
    raise TimeoutError("TASK_TIMEOUT")


def enabled_sites(job: dict) -> list[str]:
    configured = job.get("sites") or []
    if configured:
        return [key for key in configured if key in SITE_REGISTRY]
    # 兼容旧任务的三级来源配置。
    sources = job.get("sources") or ["official", "property", "government"]
    result = ["baidu", "bing"]
    if "official" in sources:
        result.append("official")
    if "property" in sources:
        result.extend(["58", "anjuke", "fang"])
    if "government" in sources:
        result.append("gov")
    return result


def search_requests(job: dict, sites: list[str]) -> list[dict]:
    location = " ".join(filter(None, [job.get("city", ""), job.get("address", "")])).strip()
    extra = " ".join(job.get("keywords", []))
    queries = []
    if "official" in sites:
        queries.append(("official", f"{location} 电竞馆 网吧 官网 营业时间 机器配置 网费 套餐 {extra}"))
    if "58" in sites:
        queries.append(("58", f"site:58.com {location} 商铺 出租 租金 面积 楼层"))
    if "anjuke" in sites:
        queries.append(("anjuke", f"site:anjuke.com {location} 商铺 出租 租金 面积 楼层"))
    if "fang" in sites:
        queries.append(("fang", f"site:fang.com {location} 商铺 出租 租金 面积 楼层"))
    if "gov" in sites:
        queries.append(("gov", f"site:gov.cn {location} 互联网上网服务营业场所 网吧 许可 消防 行政处罚"))
    requests = []
    for search_site in ("baidu", "bing"):
        if search_site not in sites:
            continue
        for target_site, query in queries:
            url = f"https://www.baidu.com/s?wd={quote_plus(query)}" if search_site == "baidu" else f"https://cn.bing.com/search?q={quote_plus(query)}"
            requests.append({"search_site": search_site, "target_site": target_site, "url": url})
    return requests


def _rate_limiter(client):
    return lambda request_url: wait_for_domain(client, urlsplit(request_url).hostname or "")


def process(job_id: str) -> None:
    client = redis_client()
    job = load_job(client, job_id)
    if not job:
        return
    started = time.monotonic()
    job.update(status="running", progress=2, started_at=now_iso())
    append_event(job, "running", "采集 worker 已开始执行")
    save_job(client, job_id, job)
    max_pages = min(int(job.get("max_pages") or 20), 20)
    timeout_seconds = min(int(job.get("timeout_seconds") or 300), 300)
    sites = enabled_sites(job)
    pending = [str(url) for url in job.get("seed_urls", [])]
    visited: set[str] = set()

    # 搜索结果仅用于发现 URL，摘要不会转成证据。
    for request in search_requests(job, sites):
        search_url = request["url"]
        search_site = request["search_site"]
        if client.get(cancel_key(job_id)):
            job.update(status="cancelled", finished_at=now_iso())
            append_event(job, "cancelled", "任务已取消")
            save_job(client, job_id, job)
            return
        if len(visited) >= max_pages or time.monotonic() - started > timeout_seconds:
            break
        try:
            _, html = fetch_page(search_url, allow_browser=False, before_request=_rate_limiter(client))
            visited.add(search_url)
            discovered = SEARCH_ADAPTERS[search_site].discover(html)
            resolved = []
            for candidate in discovered[:6]:
                host = (urlsplit(candidate).hostname or "").lower()
                if search_site == "baidu" and (host == "baidu.com" or host.endswith(".baidu.com")):
                    try:
                        candidate = resolve_redirect_chain(candidate, before_request=_rate_limiter(client))
                    except Exception:
                        continue
                if site_for_url(candidate, sites) and candidate not in resolved:
                    resolved.append(candidate)
            pending.extend(resolved)
            progress = job["source_progress"].setdefault(search_site, {"status": "running", "pages": 0, "items": 0, "errors": 0})
            progress["status"] = "running"
            progress["pages"] += 1
            progress["items"] += len(resolved)
            append_event(job, "discovery", "公开搜索完成，仅保留发现的网址，不采用搜索摘要", {"site": search_site, "target_site": request["target_site"], "url_count": len(resolved)})
        except Exception as exc:
            job["errors"].append({"url": search_url, "error": str(exc)[:200]})
            progress = job["source_progress"].setdefault(search_site, {"status": "running", "pages": 0, "items": 0, "errors": 0})
            progress["errors"] += 1
            append_event(job, "source_error", "搜索来源不可用，继续其他来源", {"site": search_site, "error": str(exc)[:160]})
        save_job(client, job_id, job)

    for url in list(dict.fromkeys(pending)):
        if len(visited) >= max_pages or time.monotonic() - started > timeout_seconds:
            break
        if client.get(cancel_key(job_id)):
            job.update(status="cancelled", finished_at=now_iso())
            append_event(job, "cancelled", "任务已取消")
            save_job(client, job_id, job)
            return
        site_key = site_for_url(url, sites)
        if not site_key:
            continue
        try:
            domain = urlsplit(url).hostname or ""
            source_type = SITE_REGISTRY[site_key].source_type
            job["source_progress"].setdefault(site_key, {"status": "queued", "pages": 0, "items": 0, "errors": 0})
            job["source_progress"][site_key]["status"] = "running"
            final_url, raw_html = fetch_page(url, allow_browser=True, before_request=_rate_limiter(client))
            visited.add(url)
            items = EVIDENCE_ADAPTERS[site_key].extract(final_url, raw_html)
            known = {item["item_id"] for item in job["items"]}
            new_items = [item for item in items if item["item_id"] not in known]
            job["items"].extend(new_items)
            job["source_progress"][site_key]["pages"] += 1
            job["source_progress"][site_key]["items"] += len(new_items)
            append_event(job, "page_completed", f"已完成 {SITE_REGISTRY[site_key].label} 页面采集", {"site": site_key, "domain": domain, "item_count": len(new_items)})
        except Exception as exc:
            job["errors"].append({"url": url, "error": str(exc)[:200]})
            append_event(job, "page_error", "页面采集失败，未写入证据", {"domain": urlsplit(url).hostname, "error": str(exc)[:160]})
            if site_key:
                job["source_progress"].setdefault(site_key, {"status": "running", "pages": 0, "items": 0, "errors": 0})
                job["source_progress"][site_key]["errors"] += 1
        job["progress"] = min(95, 10 + int(len(visited) / max_pages * 85))
        save_job(client, job_id, job)

    if time.monotonic() - started > timeout_seconds:
        job["errors"].append({"error": "TASK_TIMEOUT"})
    if job["items"] and job["errors"]:
        status = "partial_success"
    elif job["items"]:
        status = "completed"
    else:
        status = "failed"
    job.update(status=status, progress=100, finished_at=now_iso(), visited_pages=len(visited))
    for site in sites:
        progress = job["source_progress"].setdefault(site, {"status": "queued", "pages": 0, "items": 0, "errors": 0})
        progress["status"] = "partial_success" if progress["items"] and progress["errors"] else "failed" if progress["errors"] and not progress["items"] else "completed"
    append_event(job, status, f"任务结束，共形成 {len(job['items'])} 条待确认证据", {"errors": len(job["errors"])})
    save_job(client, job_id, job)


def run_next(client) -> bool:
    """处理一个队列项；Redis 连接错误向上抛出，由 main 重连。"""
    item = client.blpop(QUEUE_KEY, timeout=5)
    if not item:
        return False
    try:
        queued_job = load_job(client, item[1]) or {}
        timeout_seconds = min(int(queued_job.get("timeout_seconds") or 300), 300)
        previous_handler = signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(timeout_seconds)
        try:
            process(item[1])
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous_handler)
    except TimeoutError:
        job = load_job(client, item[1]) or {"job_id": item[1], "events": [], "errors": [], "items": []}
        job["errors"].append({"error": "TASK_TIMEOUT"})
        job.update(status="partial_success" if job.get("items") else "failed", progress=100, finished_at=now_iso())
        append_event(job, "timeout", "任务达到 5 分钟硬超时，已停止后续页面")
        save_job(client, item[1], job)
    except Exception:
        logger.exception("job failed: %s", item[1])
        job = load_job(client, item[1]) or {"job_id": item[1], "events": [], "errors": [], "items": []}
        job.update(status="failed", progress=100, finished_at=now_iso())
        append_event(job, "failed", "worker 未处理异常")
        save_job(client, item[1], job)
    return True


def main() -> None:
    logger.info("crawler worker started")
    while True:
        try:
            client = redis_client()
            client.ping()
            while True:
                run_next(client)
        except Exception:
            logger.exception("Redis 连接中断，5 秒后重连")
            time.sleep(5)


if __name__ == "__main__":
    main()

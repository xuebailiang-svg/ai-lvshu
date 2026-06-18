import html
import re
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
from scrapling.fetchers import DynamicFetcher, Fetcher

from .config import settings
from .security import USER_AGENT, UnsafeUrlError, resolve_safe_redirect, robots_allowed, validate_public_url


LOGIN_MARKERS = ("请登录", "登录后查看", "验证码", "安全验证", "访问过于频繁")


def resolve_redirect_chain(url: str, max_redirects: int = 8, before_request=None) -> str:
    """在 Scrapling 发起正文请求前逐跳验证，阻止重定向到私网。"""
    current = validate_public_url(url)
    with httpx.Client(timeout=10, follow_redirects=False, headers={"User-Agent": USER_AGENT}) as client:
        for _ in range(max_redirects + 1):
            if before_request:
                before_request(current)
            with client.stream("GET", current, headers={"Range": "bytes=0-0"}) as response:
                if 300 <= response.status_code < 400 and response.headers.get("location"):
                    current = resolve_safe_redirect(current, response.headers["location"])
                    continue
                return current
    raise ValueError("TOO_MANY_REDIRECTS")


def _browser_guard(page) -> None:
    def guard(route, request):
        if request.url.startswith(("data:", "blob:", "about:")):
            route.continue_()
            return
        try:
            validate_public_url(request.url)
            route.continue_()
        except UnsafeUrlError:
            route.abort("blockedbyclient")
    page.route("**/*", guard)


def fetch_page(url: str, allow_browser: bool = True, before_request=None) -> tuple[str, str]:
    validate_public_url(url)
    if not robots_allowed(url, before_request=before_request):
        raise PermissionError("ROBOTS_DISALLOWED")
    safe_url = resolve_redirect_chain(url, before_request=before_request)
    if before_request:
        before_request(safe_url)
    response = Fetcher.get(safe_url, stealthy_headers=False, follow_redirects=False, timeout=20, headers={"User-Agent": USER_AGENT})
    final_url = str(getattr(response, "url", safe_url))
    validate_public_url(final_url)
    body = bytes(response.body or b"")
    if len(body) > settings.max_response_bytes:
        raise ValueError("RESPONSE_TOO_LARGE")
    text = body.decode(getattr(response, "encoding", None) or "utf-8", errors="replace")
    if any(marker in text for marker in LOGIN_MARKERS):
        raise PermissionError("LOGIN_OR_CAPTCHA_REQUIRED")
    if allow_browser and len(re.sub(r"(?s)<[^>]+>", "", text).strip()) < 120:
        if before_request:
            before_request(safe_url)
        dynamic = DynamicFetcher.fetch(safe_url, headless=True, disable_resources=True, timeout=30000, network_idle=False, google_search=False, page_setup=_browser_guard)
        final_url = str(getattr(dynamic, "url", safe_url))
        validate_public_url(final_url)
        body = bytes(dynamic.body or b"")
        if len(body) > settings.max_response_bytes:
            raise ValueError("RESPONSE_TOO_LARGE")
        text = body.decode(getattr(dynamic, "encoding", None) or "utf-8", errors="replace")
    return final_url, text


def discover_result_urls(search_html: str) -> list[str]:
    urls = []
    for href in re.findall(r'(?i)href=["\'](https?://[^"\']+)', search_html):
        parsed = urlsplit(href)
        query = parse_qs(parsed.query)
        candidate = html.unescape(unquote((query.get("url") or query.get("u") or [href])[0]))
        try:
            validate_public_url(candidate)
        except UnsafeUrlError:
            continue
        host = (urlsplit(candidate).hostname or "").lower()
        if host in {"baidu.com", "www.baidu.com", "cn.bing.com", "bing.com"}:
            continue
        if candidate not in urls:
            urls.append(candidate)
    return urls

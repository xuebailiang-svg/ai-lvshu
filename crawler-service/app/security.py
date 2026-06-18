import ipaddress
import socket
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx


USER_AGENT = "EsportsSiteResearchBot/1.0 (+internal-public-research)"
BLOCKED_HOSTS = {"localhost", "metadata.google.internal", "metadata.azure.internal"}


class UnsafeUrlError(ValueError):
    pass


def _is_public_ip(value: str) -> bool:
    ip = ipaddress.ip_address(value)
    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
        or ip.is_multicast or ip.is_unspecified
    )


def validate_public_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeUrlError("URL 必须使用 HTTP/HTTPS")
    if parsed.username or parsed.password:
        raise UnsafeUrlError("URL 禁止包含认证信息")
    if parsed.port and parsed.port not in {80, 443}:
        raise UnsafeUrlError("仅允许 80/443 端口")
    host = parsed.hostname.rstrip(".").lower()
    if host in BLOCKED_HOSTS or host.endswith(".localhost"):
        raise UnsafeUrlError("禁止访问本机或云元数据地址")
    try:
        if not _is_public_ip(host):
            raise UnsafeUrlError("禁止访问私网地址")
        return url
    except ValueError:
        pass
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"域名解析失败: {host}") from exc
    if not addresses or any(not _is_public_ip(value) for value in addresses):
        raise UnsafeUrlError("域名解析到非公网地址")
    return url


def resolve_safe_redirect(base_url: str, location: str) -> str:
    return validate_public_url(urljoin(base_url, location))


def robots_allowed(url: str, timeout: float = 8.0, before_request=None) -> bool:
    parsed = urlsplit(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    validate_public_url(robots_url)
    try:
        if before_request:
            before_request(robots_url)
        response = httpx.get(robots_url, headers={"User-Agent": USER_AGENT}, timeout=timeout, follow_redirects=False)
        if 300 <= response.status_code < 400 and response.headers.get("location"):
            redirected = resolve_safe_redirect(robots_url, response.headers["location"])
            if before_request:
                before_request(redirected)
            response = httpx.get(redirected, headers={"User-Agent": USER_AGENT}, timeout=timeout, follow_redirects=False)
        if response.status_code >= 400:
            return True
        parser = RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(response.text.splitlines())
        return parser.can_fetch(USER_AGENT, url)
    except (httpx.HTTPError, UnsafeUrlError):
        # robots.txt 不可获取时保守拒绝，避免绕过站点约束。
        return False

import pytest

from app.security import UnsafeUrlError, resolve_safe_redirect, robots_allowed, validate_public_url


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/admin",
    "http://10.0.0.1/",
    "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/",
    "file:///etc/passwd",
    "https://user:password@example.com/",
    "https://example.com:8443/",
])
def test_private_and_unsafe_urls_are_rejected(url):
    with pytest.raises(UnsafeUrlError):
        validate_public_url(url)


def test_redirect_to_private_address_is_rejected():
    with pytest.raises(UnsafeUrlError):
        resolve_safe_redirect("https://example.com/start", "http://127.0.0.1/private")


def test_public_ip_is_allowed():
    assert validate_public_url("https://1.1.1.1/") == "https://1.1.1.1/"


def test_robots_disallow_is_enforced(monkeypatch):
    class Response:
        status_code = 200
        text = "User-agent: *\nDisallow: /private"
        headers = {}

    monkeypatch.setattr("app.security.httpx.get", lambda *args, **kwargs: Response())
    assert robots_allowed("https://1.1.1.1/private/report") is False
    assert robots_allowed("https://1.1.1.1/public") is True

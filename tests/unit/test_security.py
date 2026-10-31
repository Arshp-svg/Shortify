"""Unit tests for Phase 14 security controls and hardening.

Verifies:
1. SSRF prevention: blocking loopback (127.0.0.1, localhost), link-local, cloud metadata IP (169.254.169.254).
2. Scheme restrictions: prohibiting non-HTTP schemes (file://, javascript:, ftp://).
3. Response security headers: nosniff, DENY, XSS protection, Referrer-Policy.
"""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.schemas.url import URLCreateRequest


def test_ssrf_blocking_loopback_ips() -> None:
    """Ensure loopback IPs (127.0.0.1, 0.0.0.0) are rejected with validation error."""
    with pytest.raises(ValidationError) as exc:
        URLCreateRequest(original_url="http://127.0.0.1:8000/secret")
    assert "prohibited for security" in str(exc.value)

    with pytest.raises(ValidationError) as exc2:
        URLCreateRequest(original_url="http://0.0.0.0:8000/admin")
    assert "prohibited for security" in str(exc2.value)


def test_ssrf_blocking_cloud_metadata_ip() -> None:
    """Ensure AWS/GCP instance metadata endpoint (169.254.169.254) is strictly prohibited."""
    with pytest.raises(ValidationError) as exc:
        URLCreateRequest(original_url="http://169.254.169.254/latest/meta-data")
    assert "metadata IP" in str(exc.value) or "prohibited" in str(exc.value)


def test_ssrf_blocking_local_hostnames() -> None:
    """Ensure internal local domains (localhost, .local, .internal) are rejected."""
    with pytest.raises(ValidationError) as exc:
        URLCreateRequest(original_url="http://localhost:3000/grafana")
    assert "prohibited for security" in str(exc.value)

    with pytest.raises(ValidationError) as exc2:
        URLCreateRequest(original_url="http://backend.internal/api")
    assert "prohibited for security" in str(exc2.value)


def test_scheme_blocking_non_http() -> None:
    """Ensure dangerous non-HTTP schemes are rejected."""
    with pytest.raises(ValidationError):
        URLCreateRequest(original_url="javascript:alert(1)")

    with pytest.raises(ValidationError):
        URLCreateRequest(original_url="file:///etc/passwd")

    with pytest.raises(ValidationError):
        URLCreateRequest(original_url="ftp://files.example.com")


def test_valid_public_urls_accepted() -> None:
    """Ensure legitimate public HTTP and HTTPS destinations pass validation."""
    req1 = URLCreateRequest(original_url="https://github.com/fastapi/fastapi")
    assert str(req1.original_url) == "https://github.com/fastapi/fastapi"

    req2 = URLCreateRequest(original_url="http://example.org/path?param=value#anchor")
    assert str(req2.original_url) == "http://example.org/path?param=value#anchor"


def test_security_headers_injected_in_responses() -> None:
    """Verify security headers are present in HTTP responses."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("X-XSS-Protection") == "1; mode=block"
    assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "X-Request-ID" in response.headers

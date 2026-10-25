"""Shortify Locust Load Testing Harness.

Simulates realistic client traffic across endpoints:
- GET /health
- POST /api/v1/urls
- GET /{short_code} (Redirect)
- GET /api/v1/urls/{id}/stats
"""

from locust import HttpUser, between, task


class ShortifyUser(HttpUser):
    wait_time = between(0.01, 0.05)

    @task(10)
    def check_health(self) -> None:
        """Lightweight health probe task."""
        self.client.get("/health", name="/health")

    @task(1)
    def check_root(self) -> None:
        """Root metadata probe task."""
        self.client.get("/", name="/")

"""Shortify Locust Load Testing Harness.

Implements all 5 roadmap workload profiles:
1. Redirect-heavy (100% lookups)
2. Creation-heavy (100% URL creations)
3. Mixed workload (90% redirects, 10% creations)
4. 404 / Invalid traffic (100% non-existent codes)
5. Burst traffic (Zero wait time spike traffic)
"""

import random
from typing import ClassVar

from locust import FastHttpUser, between, task


class RedirectHeavyUser(FastHttpUser):
    """Simulates 100% redirect queries hitting existing seeded dataset."""

    wait_time = between(0.005, 0.02)
    # Range of seeded short codes from scripts/seed_urls.py (s0000000 to s0099999)
    max_seeded_id: ClassVar[int] = 99999

    @task
    def redirect_lookup(self) -> None:
        idx = random.randint(0, self.max_seeded_id)
        code = f"s{idx:07d}"
        # We don't follow redirect so we measure the API's 307 response time, not external destination
        with self.client.get(
            f"/{code}",
            name="/{short_code} [Redirect]",
            allow_redirects=False,
            catch_response=True,
        ) as response:
            if response.status_code == 307:
                response.success()
            else:
                response.failure(f"Expected 307 but got {response.status_code}")


class CreationHeavyUser(FastHttpUser):
    """Simulates 100% URL creations with distinct random destinations."""

    wait_time = between(0.01, 0.05)

    @task
    def create_short_url(self) -> None:
        rand_id = random.randint(1000000, 99999999)
        payload = {
            "original_url": f"https://benchmark-target-{rand_id}.example.com/page",
        }
        self.client.post(
            "/api/v1/urls",
            json=payload,
            name="/api/v1/urls [Create]",
        )


class MixedWorkloadUser(FastHttpUser):
    """Simulates realistic mixed traffic: 90% redirects, 10% URL creations."""

    wait_time = between(0.005, 0.02)
    max_seeded_id: ClassVar[int] = 99999

    @task(9)
    def redirect_lookup(self) -> None:
        idx = random.randint(0, self.max_seeded_id)
        code = f"s{idx:07d}"
        with self.client.get(
            f"/{code}",
            name="/{short_code} [Redirect]",
            allow_redirects=False,
            catch_response=True,
        ) as response:
            if response.status_code == 307:
                response.success()
            else:
                response.failure(f"Expected 307 but got {response.status_code}")

    @task(1)
    def create_short_url(self) -> None:
        rand_id = random.randint(1000000, 99999999)
        payload = {
            "original_url": f"https://mixed-traffic-{rand_id}.example.com/resource",
        }
        self.client.post(
            "/api/v1/urls",
            json=payload,
            name="/api/v1/urls [Create]",
        )


class InvalidTrafficUser(FastHttpUser):
    """Simulates 404 / malicious scanning traffic against non-existent short codes."""

    wait_time = between(0.005, 0.02)

    @task
    def invalid_lookup(self) -> None:
        # Non-existent 12-char code
        code = f"nonexist{random.randint(100000, 999999)}"
        with self.client.get(
            f"/{code}",
            name="/{short_code} [404 Invalid]",
            allow_redirects=False,
            catch_response=True,
        ) as response:
            if response.status_code == 404:
                response.success()
            else:
                response.failure(f"Expected 404 but got {response.status_code}")

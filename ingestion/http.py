"""Polite HTTP client: fixed User-Agent, pause between requests, retries on timeouts and 5xx."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

from ingestion.config import redact, sources

log = logging.getLogger(__name__)
# httpx logs every full URL at INFO; BPS puts its API key in the URL path.
logging.getLogger("httpx").setLevel(logging.WARNING)


def _retry_after(r: httpx.Response) -> float:
    """Seconds to wait after a 429: Retry-After header, else JSON `retry_after`, else 60."""
    try:
        return float(r.headers.get("Retry-After") or r.json().get("retry_after"))
    except (TypeError, ValueError):
        return float(sources()["http"]["rate_limit_default_wait_seconds"])


@dataclass
class Response:
    status: int
    body: bytes
    url: str


class PoliteClient:
    def __init__(self, sleep_seconds: float | None = None) -> None:
        cfg = sources()["http"]
        self.sleep_seconds = cfg["sleep_seconds"] if sleep_seconds is None else sleep_seconds
        self.backoff = cfg["retry_backoff_seconds"]
        self._client = httpx.Client(
            headers={"User-Agent": cfg["user_agent"], "Accept": "application/json"},
            timeout=cfg["timeout_seconds"],
            follow_redirects=True,
        )
        self._last_request_at = 0.0

    def _pause(self) -> None:
        wait = self.sleep_seconds - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)

    def get(self, url: str, params: dict | None = None) -> Response:
        """GET with up to len(backoff) attempts. 4xx is returned, not retried."""
        last_error: Exception | None = None
        for attempt, backoff in enumerate([0, *self.backoff]):
            if backoff:
                log.warning("retry %s for %s in %ss (%s)", attempt, redact(url), backoff,
                            redact(str(last_error)))
                time.sleep(backoff)
            self._pause()
            try:
                r = self._client.get(url, params=params)
                self._last_request_at = time.monotonic()
            except (httpx.TimeoutException, httpx.TransportError) as e:
                self._last_request_at = time.monotonic()
                last_error = e
                continue
            if r.status_code == 429:  # rate limited: wait as told (header or body), then retry
                wait = _retry_after(r)
                log.warning("rate limited by %s; waiting %ss", redact(url), wait)
                time.sleep(wait)
                last_error = httpx.HTTPStatusError("HTTP 429", request=r.request, response=r)
                continue
            if r.status_code >= 500:
                last_error = httpx.HTTPStatusError(
                    f"HTTP {r.status_code}", request=r.request, response=r
                )
                continue
            return Response(status=r.status_code, body=r.content, url=redact(str(r.url)))
        raise RuntimeError(redact(f"giving up on {url} after retries: {last_error}"))

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PoliteClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

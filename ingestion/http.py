"""Polite HTTP client: fixed User-Agent, pause between requests, retries on timeouts and 5xx."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

from ingestion.config import sources

log = logging.getLogger(__name__)


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
                log.warning("retry %s for %s in %ss (%s)", attempt, url, backoff, last_error)
                time.sleep(backoff)
            self._pause()
            try:
                r = self._client.get(url, params=params)
                self._last_request_at = time.monotonic()
            except (httpx.TimeoutException, httpx.TransportError) as e:
                self._last_request_at = time.monotonic()
                last_error = e
                continue
            if r.status_code >= 500:
                last_error = httpx.HTTPStatusError(
                    f"HTTP {r.status_code}", request=r.request, response=r
                )
                continue
            return Response(status=r.status_code, body=r.content, url=str(r.url))
        raise RuntimeError(f"giving up on {url} after retries: {last_error}")

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PoliteClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

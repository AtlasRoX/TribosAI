"""Bounded recovery from transient provider faults, below every model call (audit I26).

The NVIDIA NIM endpoint answers in bursts of `500 Failed to generate completions` across every caller (planner,
writer, critics, NLI) between long healthy stretches; the same request shapes succeed before and after a burst. The
SDK's own retry (one attempt after ~0.4 s) lands inside the burst. This transport replaces it, so attempts are not
multiplied: the OpenAI client runs with max_retries=0 and this layer makes at most TRIBOS_LLM_RETRY_ATTEMPTS
attempts per request, with exponential backoff and jitter, honouring Retry-After, and never past
TRIBOS_LLM_RETRY_DEADLINE_S from the first attempt.

Only transient answers are retried: 408, 409, 429, 500, 502, 503, 504 and connection failures before a response.
Client errors (400, 401, 403, 404, 422) are returned at once: resending the same request cannot fix them. A failure
after the response started streaming is never retried here (it would duplicate streamed text); callers handle it.

Each retried attempt is logged with the provider's request id (nvcf-reqid / x-request-id), the status, the attempt
number and the elapsed time. Request bodies, prompts and headers carrying credentials are never logged.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any

import httpx

from tribos.config.settings import get_float, get_int

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504})
_ID_HEADERS = ("nvcf-reqid", "x-request-id", "request-id", "openai-request-id")


def request_id(response: httpx.Response | None) -> str:
    if response is None:
        return ""
    return next((response.headers.get(h, "") for h in _ID_HEADERS if response.headers.get(h)), "")


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after", "")
    try:
        return max(0.0, float(value)) if value else None
    except ValueError:
        return None


class _Policy:
    def __init__(self, attempts: int | None = None, deadline_s: float | None = None, base_delay_s: float = 1.5,
                 max_delay_s: float = 8.0) -> None:
        self.attempts = max(1, int(attempts if attempts is not None else get_int("TRIBOS_LLM_RETRY_ATTEMPTS")))
        self.deadline_s = float(deadline_s if deadline_s is not None else get_float("TRIBOS_LLM_RETRY_DEADLINE_S"))
        self.base_delay_s, self.max_delay_s = base_delay_s, max_delay_s

    def delay(self, attempt: int, response: httpx.Response | None) -> float:
        hinted = _retry_after(response) if response is not None else None
        if hinted is not None:
            return min(hinted, self.max_delay_s)
        return min(self.max_delay_s, self.base_delay_s * 2 ** (attempt - 1)) * random.uniform(0.8, 1.2)  # noqa: S311

    def next_delay(self, attempt: int, started: float, response: httpx.Response | None) -> float | None:
        """Seconds to wait before the next attempt, or None when the attempts or the deadline are used up."""
        if attempt >= self.attempts:
            return None
        wait = self.delay(attempt, response)
        return None if time.monotonic() - started + wait > self.deadline_s else wait


def _log(request: httpx.Request, attempt: int, started: float, response: httpx.Response | None, error: str,
         wait: float | None) -> None:
    logger.warning(
        "Provider transient failure: %s %s attempt %d status=%s request_id=%s error=%s elapsed=%.2fs %s",
        request.method, request.url.host, attempt, response.status_code if response is not None else "-",
        request_id(response) or "-", error or "-", time.monotonic() - started,
        f"retrying in {wait:.1f}s" if wait is not None else "giving up (attempts or deadline used)",
    )


class RetryingAsyncTransport(httpx.AsyncBaseTransport):
    def __init__(self, inner: httpx.AsyncBaseTransport | None = None, **policy: Any) -> None:
        self._inner = inner or httpx.AsyncHTTPTransport()
        self._policy = _Policy(**policy)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        started, attempt = time.monotonic(), 0
        while True:
            attempt += 1
            try:
                response = await self._inner.handle_async_request(request)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:  # nothing was sent: safe to send again
                wait = self._policy.next_delay(attempt, started, None)
                _log(request, attempt, started, None, type(exc).__name__, wait)
                if wait is None:
                    raise
                await asyncio.sleep(wait)
                continue
            if response.status_code not in RETRYABLE_STATUS:
                return response
            wait = self._policy.next_delay(attempt, started, response)
            _log(request, attempt, started, response, "", wait)
            if wait is None:
                return response
            await response.aread()
            await response.aclose()
            await asyncio.sleep(wait)

    async def aclose(self) -> None:
        await self._inner.aclose()


class RetryingTransport(httpx.BaseTransport):
    def __init__(self, inner: httpx.BaseTransport | None = None, **policy: Any) -> None:
        self._inner = inner or httpx.HTTPTransport()
        self._policy = _Policy(**policy)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        started, attempt = time.monotonic(), 0
        while True:
            attempt += 1
            try:
                response = self._inner.handle_request(request)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                wait = self._policy.next_delay(attempt, started, None)
                _log(request, attempt, started, None, type(exc).__name__, wait)
                if wait is None:
                    raise
                time.sleep(wait)
                continue
            if response.status_code not in RETRYABLE_STATUS:
                return response
            wait = self._policy.next_delay(attempt, started, response)
            _log(request, attempt, started, response, "", wait)
            if wait is None:
                return response
            response.read()
            response.close()
            time.sleep(wait)

    def close(self) -> None:
        self._inner.close()


# Raised before any response body (a 5xx/429 status, no connection): the transport has already retried these.
RETRIED_BY_TRANSPORT = frozenset({"InternalServerError", "APIConnectionError", "RateLimitError", "ConnectError"})


def already_retried(llm: Any, exc: BaseException) -> bool:
    """The failure is one this client's transport already retried within its bounds: an application-level retry of
    the same request would multiply the attempts (audit I26). Mid-stream failures (ReadError, RemoteProtocolError,
    a read timeout) are not retried by the transport and stay with the caller."""
    client = getattr(llm, "http_async_client", None) or getattr(llm, "async_client", None)
    transport = getattr(client, "_transport", None)
    return isinstance(transport, RetryingAsyncTransport) and type(exc).__name__ in RETRIED_BY_TRANSPORT


def provider_http_clients(timeout_s: float) -> tuple[httpx.Client, httpx.AsyncClient]:
    """(sync, async) httpx clients whose transport applies the bounded retry policy; for ChatOpenAI's http_client /
    http_async_client, with the SDK's own retries set to 0."""
    timeout = httpx.Timeout(timeout_s, connect=15.0)
    return (httpx.Client(transport=RetryingTransport(), timeout=timeout),
            httpx.AsyncClient(transport=RetryingAsyncTransport(), timeout=timeout))


__all__ = ["RETRYABLE_STATUS", "RetryingAsyncTransport", "RetryingTransport", "provider_http_clients", "request_id"]

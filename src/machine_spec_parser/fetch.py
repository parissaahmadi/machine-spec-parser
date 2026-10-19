"""Fetching with retry, exponential backoff and polite rate limiting.

The parser is network-agnostic: it only needs something that implements
``Fetcher``. This module ships a ``FileFetcher`` (used for the bundled sample
datasheets) and the reusable resilience pieces, so an HTTP adapter can be
dropped in later. Nothing here talks to a real website.

Error taxonomy
--------------
* ``FetchError(transient=True)``  timeouts, 5xx, connection resets -> retried.
* ``FetchError(transient=False)`` missing file, 404, 403          -> fail fast.
* ``FetchFailed``                 what the caller sees once retrying is over.
"""

from __future__ import annotations

import random
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class FetchError(Exception):
    def __init__(self, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


class FetchFailed(Exception):
    """Retrying is over (or was pointless): the source could not be fetched."""

    def __init__(self, source: str, attempts: int, last_error: FetchError) -> None:
        super().__init__(f"{source}: {last_error} (after {attempts} attempt(s))")
        self.source = source
        self.attempts = attempts
        self.last_error = last_error

    @property
    def permanent(self) -> bool:
        return not self.last_error.transient


class Fetcher(Protocol):
    def fetch(self, source: str) -> str: ...


def decode_html(data: bytes) -> str:
    """Decode page bytes: UTF-8 first, then the declared charset, then Latin-1."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    m = re.search(rb"charset=[\"']?([\w-]+)", data[:2048], re.IGNORECASE)
    if m:
        try:
            return data.decode(m.group(1).decode("ascii"))
        except (LookupError, UnicodeDecodeError):
            pass
    return data.decode("latin-1")  # never fails


class FileFetcher:
    """Reads local HTML files; ``source`` is a path (relative to ``root`` if given)."""

    def __init__(self, root: Path | str | None = None) -> None:
        self._root = Path(root) if root else None

    def fetch(self, source: str) -> str:
        path = Path(source)
        if self._root and not path.is_absolute():
            path = self._root / path
        try:
            return decode_html(path.read_bytes())
        except FileNotFoundError:
            raise FetchError(f"no such file: {path}", transient=False) from None
        except OSError as exc:
            raise FetchError(f"cannot read {path}: {exc}", transient=True) from exc


class FlakyFetcher:
    """Test double: wraps a fetcher and fails *transiently* with probability ``failure_rate``."""

    def __init__(self, inner: Fetcher, failure_rate: float, seed: int = 0) -> None:
        self._inner = inner
        self._rate = failure_rate
        self._rng = random.Random(seed)

    def fetch(self, source: str) -> str:
        if self._rng.random() < self._rate:
            raise FetchError("simulated timeout", transient=True)
        return self._inner.fetch(source)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 4
    base_delay: float = 0.5   # seconds before the 2nd attempt
    factor: float = 2.0       # delay multiplier per attempt
    max_delay: float = 8.0
    jitter: float = 0.2       # +/- fraction, spreads out simultaneous retries


def backoff_delay(policy: RetryPolicy, attempt: int, rng: random.Random) -> float:
    """Delay to wait after failed attempt number ``attempt`` (1-based)."""
    raw = min(policy.max_delay, policy.base_delay * policy.factor ** (attempt - 1))
    return max(0.0, raw * (1 + policy.jitter * rng.uniform(-1, 1)))


def fetch_with_retry(
    fetcher: Fetcher,
    source: str,
    policy: RetryPolicy | None = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
    rng: random.Random | None = None,
    on_retry: Callable[[int, float, FetchError], None] | None = None,
) -> str:
    """Fetch ``source``, retrying transient errors with exponential backoff."""
    policy = policy or RetryPolicy()
    rng = rng or random.Random(0)
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return fetcher.fetch(source)
        except FetchError as exc:
            if not exc.transient or attempt == policy.max_attempts:
                raise FetchFailed(source, attempt, exc) from exc
            delay = backoff_delay(policy, attempt, rng)
            if on_retry:
                on_retry(attempt, delay, exc)
            sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover


class RateLimiter:
    """Guarantees at least ``min_interval`` seconds between consecutive calls."""

    def __init__(
        self,
        min_interval: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def wait(self) -> None:
        if self._last is not None:
            remaining = self._interval - (self._clock() - self._last)
            if remaining > 0:
                self._sleep(remaining)
        self._last = self._clock()

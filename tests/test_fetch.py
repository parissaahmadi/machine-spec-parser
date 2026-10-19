import random

import pytest

from machine_spec_parser.fetch import (
    FetchError,
    FetchFailed,
    FileFetcher,
    FlakyFetcher,
    RateLimiter,
    RetryPolicy,
    backoff_delay,
    decode_html,
    fetch_with_retry,
)


class Scripted:
    """Fetcher that raises the queued errors, then returns text."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def fetch(self, source):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def transient():
    return FetchError("timeout", transient=True)


def permanent():
    return FetchError("404", transient=False)


def no_sleep(_):
    pass


# ----------------------------------------------------------------- decoding
def test_decode_utf8_and_bom():
    assert decode_html("°C ✓".encode()) == "°C ✓"
    assert decode_html(b"\xef\xbb\xbfabc") == "abc"


def test_decode_falls_back_to_latin1():
    assert decode_html(b"22 \xb0C") == "22 °C"


def test_decode_honours_declared_charset():
    data = b'<meta charset="windows-1256"><p>' + "قدرت".encode("cp1256")
    assert "قدرت" in decode_html(data)


def test_decode_unknown_charset_still_returns_text():
    assert decode_html(b'<meta charset="nonsense"> \xb0') .endswith("°")


# ------------------------------------------------------------------- retry
def test_success_on_first_try_does_not_sleep():
    slept = []
    assert fetch_with_retry(Scripted("ok"), "s", sleep=slept.append) == "ok"
    assert slept == []


def test_transient_errors_are_retried_until_success():
    fetcher, slept = Scripted(transient(), transient(), "ok"), []
    assert fetch_with_retry(fetcher, "s", sleep=slept.append) == "ok"
    assert fetcher.calls == 3
    assert len(slept) == 2 and slept[1] > slept[0]


def test_permanent_error_fails_fast():
    fetcher = Scripted(permanent(), "never")
    with pytest.raises(FetchFailed) as exc:
        fetch_with_retry(fetcher, "s", sleep=no_sleep)
    assert fetcher.calls == 1
    assert exc.value.permanent and exc.value.attempts == 1


def test_gives_up_after_max_attempts():
    fetcher = Scripted(*[transient() for _ in range(10)])
    with pytest.raises(FetchFailed) as exc:
        fetch_with_retry(fetcher, "s", RetryPolicy(max_attempts=3), sleep=no_sleep)
    assert fetcher.calls == 3
    assert not exc.value.permanent and exc.value.attempts == 3


def test_on_retry_callback_reports_attempt_and_delay():
    seen = []
    fetch_with_retry(Scripted(transient(), "ok"), "s", sleep=no_sleep,
                     on_retry=lambda attempt, delay, err: seen.append((attempt, round(delay, 3))))
    assert len(seen) == 1 and seen[0][0] == 1 and seen[0][1] > 0


def test_backoff_grows_exponentially_and_is_capped():
    policy = RetryPolicy(base_delay=1.0, factor=2.0, max_delay=5.0, jitter=0.0)
    rng = random.Random(0)
    assert [backoff_delay(policy, n, rng) for n in (1, 2, 3, 4, 5)] == [1, 2, 4, 5, 5]


def test_backoff_jitter_stays_within_bounds_and_is_reproducible():
    policy = RetryPolicy(base_delay=1.0, jitter=0.2)
    delays = [backoff_delay(policy, 1, random.Random(7)) for _ in range(3)]
    assert len(set(delays)) == 1  # same seed, same jitter
    rng = random.Random(1)
    for _ in range(200):
        assert 0.8 <= backoff_delay(policy, 1, rng) <= 1.2


# ----------------------------------------------------------- rate limiting
class FakeClock:
    def __init__(self):
        self.now = 100.0
        self.slept = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def test_rate_limiter_waits_only_the_remaining_time():
    fake = FakeClock()
    limiter = RateLimiter(2.0, clock=fake.clock, sleep=fake.sleep)
    limiter.wait()                 # first call never waits
    fake.now += 0.5
    limiter.wait()                 # 0.5 s elapsed -> wait 1.5 s
    fake.now += 5.0
    limiter.wait()                 # plenty of time passed -> no wait
    assert fake.slept == [pytest.approx(1.5)]


# ------------------------------------------------------------ file fetching
def test_file_fetcher_reads_and_resolves_relative_to_root(tmp_path):
    (tmp_path / "a.html").write_text("héllo", encoding="utf-8")
    assert FileFetcher(tmp_path).fetch("a.html") == "héllo"
    assert FileFetcher().fetch(str(tmp_path / "a.html")) == "héllo"


def test_missing_file_is_a_permanent_error(tmp_path):
    with pytest.raises(FetchError) as exc:
        FileFetcher(tmp_path).fetch("nope.html")
    assert exc.value.transient is False


def test_flaky_fetcher_is_seeded_and_transient():
    inner = Scripted(*["ok"] * 50)
    flaky = FlakyFetcher(inner, failure_rate=0.5, seed=1)
    outcomes = []
    for _ in range(20):
        try:
            flaky.fetch("s")
            outcomes.append("ok")
        except FetchError as exc:
            assert exc.transient
            outcomes.append("fail")
    assert "ok" in outcomes and "fail" in outcomes
    again = FlakyFetcher(Scripted(*["ok"] * 50), failure_rate=0.5, seed=1)
    replay = []
    for _ in range(20):
        try:
            again.fetch("s")
            replay.append("ok")
        except FetchError:
            replay.append("fail")
    assert replay == outcomes

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock

import pytest

from jgrad_admission_rag.service.response_cache import ExactResponseCache


def test_exact_cache_uses_ttl_and_deterministic_lru_eviction() -> None:
    now = [10.0]
    calls: list[str] = []
    cache = ExactResponseCache[str](capacity=2, ttl_seconds=5, clock=lambda: now[0])

    def compute(value: str):
        return lambda: calls.append(value) or value

    assert cache.get_or_compute("a", compute("A")) == ("A", False)
    assert cache.get_or_compute("b", compute("B")) == ("B", False)
    assert cache.get_or_compute("a", compute("unused")) == ("A", True)
    assert cache.get_or_compute("c", compute("C")) == ("C", False)
    assert cache.get_or_compute("b", compute("B2")) == ("B2", False)
    now[0] = 16.0
    assert cache.get_or_compute("a", compute("A2")) == ("A2", False)
    assert calls == ["A", "B", "C", "B2", "A2"]


def test_exact_cache_single_flight_coalesces_concurrent_misses() -> None:
    workers = 6
    started = Barrier(workers)
    compute_started = Event()
    release = Event()
    call_lock = Lock()
    calls = 0
    cache = ExactResponseCache[str](capacity=4, ttl_seconds=60)

    def compute() -> str:
        nonlocal calls
        with call_lock:
            calls += 1
        compute_started.set()
        release.wait(timeout=2)
        return "validated"

    def invoke() -> tuple[str, bool]:
        started.wait()
        return cache.get_or_compute("same", compute)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = tuple(executor.submit(invoke) for _ in range(workers))
        assert compute_started.wait(timeout=2)
        release.set()
        results = tuple(future.result(timeout=2) for future in futures)

    assert calls == 1
    assert all(value == "validated" for value, _ in results)
    assert sum(not hit for _, hit in results) == 1


def test_exact_cache_never_stores_failures() -> None:
    calls = 0
    cache = ExactResponseCache[str](capacity=2, ttl_seconds=60)

    def fail() -> str:
        nonlocal calls
        calls += 1
        raise ValueError("safe failure")

    for _ in range(2):
        with pytest.raises(ValueError, match="safe failure"):
            cache.get_or_compute("failure", fail)

    assert calls == 2
    assert len(cache) == 0


def test_exact_cache_stores_only_projected_value() -> None:
    cache = ExactResponseCache[object](capacity=2, ttl_seconds=60)
    private = {"question": "private question", "validated": "safe"}

    value, hit = cache.get_or_compute(
        "key",
        lambda: private,
        project=lambda item: item["validated"],
    )

    assert value is private
    assert hit is False
    assert cache.get_or_compute("key", lambda: "unused") == ("safe", True)
    assert "private question" not in repr(cache._entries)


def test_exact_cache_can_decline_storage_without_breaking_owner_result() -> None:
    cache = ExactResponseCache[str](capacity=2, ttl_seconds=60)
    calls = 0

    def compute() -> str:
        nonlocal calls
        calls += 1
        return f"value-{calls}"

    assert cache.get_or_compute("key", compute, should_cache=lambda _: False) == (
        "value-1",
        False,
    )
    assert len(cache) == 0
    assert cache.get_or_compute("key", compute) == ("value-2", False)


def test_noncacheable_single_flight_waiters_receive_transient_owner_value() -> None:
    workers = 3
    started = Barrier(workers)
    compute_started = Event()
    release = Event()
    cache = ExactResponseCache[str](capacity=2, ttl_seconds=60)

    def compute() -> str:
        compute_started.set()
        release.wait(timeout=2)
        return "transient"

    def invoke() -> tuple[str, bool]:
        started.wait()
        return cache.get_or_compute("key", compute, should_cache=lambda _: False)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = tuple(executor.submit(invoke) for _ in range(workers))
        assert compute_started.wait(timeout=2)
        release.set()
        results = tuple(future.result(timeout=2) for future in futures)

    assert results == (("transient", False),) * workers
    assert len(cache) == 0

"""Process-local exact response cache with bounded TTL/LRU and single-flight misses."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Event, Lock
from time import monotonic
from typing import Generic, TypeVar


_Value = TypeVar("_Value")


@dataclass(frozen=True, slots=True)
class _Entry(Generic[_Value]):
    value: _Value
    expires_at: float


@dataclass(slots=True)
class _Flight(Generic[_Value]):
    completed: Event = field(default_factory=Event)
    value: _Value | None = None
    error: Exception | None = None
    cacheable: bool = False


class ExactResponseCache(Generic[_Value]):
    """Cache validated results only; concurrent exact misses share one computation."""

    def __init__(
        self,
        *,
        capacity: int,
        ttl_seconds: float,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise ValueError("cache capacity must be a positive integer")
        if isinstance(ttl_seconds, bool) or ttl_seconds <= 0:
            raise ValueError("cache TTL must be positive")
        self._capacity = capacity
        self._ttl_seconds = float(ttl_seconds)
        self._clock = clock
        self._entries: OrderedDict[str, _Entry[_Value]] = OrderedDict()
        self._flights: dict[str, _Flight[_Value]] = {}
        self._lock = Lock()

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def ttl_seconds(self) -> float:
        return self._ttl_seconds

    def get_or_compute(
        self,
        key: str,
        compute: Callable[[], _Value],
        *,
        project: Callable[[_Value], _Value] | None = None,
        should_cache: Callable[[_Value], bool] | None = None,
    ) -> tuple[_Value, bool]:
        if not key or key != key.strip():
            raise ValueError("cache key must be explicit")
        owner = False
        with self._lock:
            self._expire_locked(self._clock())
            entry = self._entries.get(key)
            if entry is not None:
                self._entries.move_to_end(key)
                return entry.value, True
            flight = self._flights.get(key)
            if flight is None:
                flight = _Flight()
                self._flights[key] = flight
                owner = True

        if not owner:
            flight.completed.wait()
            if flight.error is not None:
                raise flight.error
            if flight.value is None:
                raise RuntimeError("single-flight completed without a value")
            return flight.value, flight.cacheable

        try:
            value = compute()
        except Exception as error:
            with self._lock:
                flight.error = error
                self._flights.pop(key, None)
                flight.completed.set()
            raise

        cacheable = should_cache(value) if should_cache is not None else True
        shared_value = project(value) if cacheable and project is not None else value
        with self._lock:
            flight.value = shared_value
            flight.cacheable = cacheable
            if cacheable:
                self._entries[key] = _Entry(
                    value=shared_value,
                    expires_at=self._clock() + self._ttl_seconds,
                )
                self._entries.move_to_end(key)
                while len(self._entries) > self._capacity:
                    self._entries.popitem(last=False)
            self._flights.pop(key, None)
            flight.completed.set()
        return value, False

    def __len__(self) -> int:
        with self._lock:
            self._expire_locked(self._clock())
            return len(self._entries)

    def _expire_locked(self, now: float) -> None:
        expired = tuple(key for key, entry in self._entries.items() if entry.expires_at <= now)
        for key in expired:
            self._entries.pop(key, None)


__all__ = ["ExactResponseCache"]

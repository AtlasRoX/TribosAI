"""Per-user concurrency limits shared by the chat and re-run endpoints."""

from __future__ import annotations

import asyncio
import time
import weakref
from collections import OrderedDict
from typing import Any

from fastapi import HTTPException


class UserConcurrencyLimiter:
    """Non-blocking per-user slot counter: a caller over the limit gets 429 instead of queueing.

    Entries are removed when a user's count drops to zero, so the table stays bounded by active users.
    """

    def __init__(self, limit: int) -> None:
        self.limit = max(1, int(limit))
        self._active: dict[str, int] = {}

    def try_acquire(self, user_id: str) -> bool:
        current = self._active.get(user_id, 0)
        if current >= self.limit:
            return False
        self._active[user_id] = current + 1
        return True

    def acquire_or_429(self, user_id: str, detail: str) -> None:
        if not self.try_acquire(user_id):
            raise HTTPException(status_code=429, detail=detail)

    def release(self, user_id: str) -> None:
        current = self._active.get(user_id, 0)
        if current <= 1:
            self._active.pop(user_id, None)
        else:
            self._active[user_id] = current - 1

    def active(self, user_id: str) -> int:
        return self._active.get(user_id, 0)


class UserRateLimiter:
    """At most `limit` requests per user in any `window_s` seconds (a sliding window); over it a caller gets 429.

    Only users with requests inside the window are kept, so the table stays bounded by recently active users.
    """

    def __init__(self, limit: int, window_s: float = 60.0, max_users: int = 4096) -> None:
        self.limit = max(1, int(limit))
        self.window_s = float(window_s)
        self.max_users = max(1, int(max_users))
        self._hits: OrderedDict[str, list[float]] = OrderedDict()

    def try_acquire(self, user_id: str) -> bool:
        now = time.monotonic()
        hits = [t for t in self._hits.get(user_id, []) if now - t < self.window_s]
        if len(hits) >= self.limit:
            self._hits[user_id] = hits
            return False
        hits.append(now)
        self._hits[user_id] = hits
        self._hits.move_to_end(user_id)
        while len(self._hits) > self.max_users:
            self._hits.popitem(last=False)
        return True

    def acquire_or_429(self, user_id: str, detail: str) -> None:
        if not self.try_acquire(user_id):
            raise HTTPException(status_code=429, detail=detail, headers={"Retry-After": str(int(self.window_s))})


class RecentRequestIds:
    """Client request ids per user with an optional value (e.g. the job a request created), so a retried POST is
    recognised as the same request.

    Bounded in memory: entries expire after ttl_s (a guard against leaks; callers pop them when the request ends),
    each user keeps at most per_user ids (oldest dropped first) and at most max_users users are tracked (least
    recently used dropped first).
    """

    def __init__(self, ttl_s: float = 3 * 3600.0, per_user: int = 32, max_users: int = 4096) -> None:
        self.ttl_s = float(ttl_s)
        self.per_user = max(1, int(per_user))
        self.max_users = max(1, int(max_users))
        self._items: OrderedDict[str, OrderedDict[str, tuple[float, Any]]] = OrderedDict()

    def _user(self, user_id: str, create: bool) -> OrderedDict[str, tuple[float, Any]] | None:
        items = self._items.get(user_id)
        if items is None:
            if not create:
                return None
            items = self._items[user_id] = OrderedDict()
            while len(self._items) > self.max_users:
                self._items.popitem(last=False)
        self._items.move_to_end(user_id)
        now = time.monotonic()
        for key in [k for k, (expires, _v) in items.items() if expires <= now]:
            del items[key]
        return items

    def get(self, user_id: str, request_id: str) -> Any | None:
        items = self._user(user_id, create=False)
        entry = items.get(request_id) if items is not None else None
        return entry[1] if entry is not None else None

    def put(self, user_id: str, request_id: str, value: Any = True) -> None:
        items = self._user(user_id, create=True)
        assert items is not None
        items[request_id] = (time.monotonic() + self.ttl_s, value)
        items.move_to_end(request_id)
        while len(items) > self.per_user:
            items.popitem(last=False)

    def claim(self, user_id: str, request_id: str) -> bool:
        """Record request_id as running; False when it already is (a duplicate)."""
        if self.get(user_id, request_id) is not None:
            return False
        self.put(user_id, request_id)
        return True

    def pop(self, user_id: str, request_id: str) -> None:
        items = self._items.get(user_id)
        if items is None:
            return
        items.pop(request_id, None)
        if not items:
            self._items.pop(user_id, None)

    def __len__(self) -> int:
        return sum(len(v) for v in self._items.values())


class UserSemaphores:
    """One semaphore per user, held only while someone references it (no unbounded growth)."""

    def __init__(self, value: int = 1) -> None:
        self.value = value
        self._items: weakref.WeakValueDictionary[str, asyncio.Semaphore] = weakref.WeakValueDictionary()

    def get(self, user_id: str) -> asyncio.Semaphore:
        sem = self._items.get(user_id)
        if sem is None:
            sem = asyncio.Semaphore(self.value)
            self._items[user_id] = sem
        return sem

    def __len__(self) -> int:
        return len(self._items)

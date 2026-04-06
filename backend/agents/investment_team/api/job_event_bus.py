"""Per-job event bus for SSE streaming.

Pipeline threads call ``publish()`` to broadcast events; SSE endpoint generators
call ``subscribe()`` / ``unsubscribe()`` to receive them via a thread-safe deque.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


@dataclass
class Subscription:
    """Handle returned by :func:`subscribe`."""

    notify: threading.Event = field(default_factory=threading.Event)
    events: deque = field(default_factory=lambda: deque(maxlen=500))


_lock = threading.Lock()
_subscribers: Dict[str, list[Subscription]] = {}


def subscribe(job_id: str) -> Subscription:
    """Create a subscription for *job_id*. The caller must call :func:`unsubscribe` when done."""
    sub = Subscription()
    with _lock:
        _subscribers.setdefault(job_id, []).append(sub)
    return sub


def unsubscribe(job_id: str, sub: Subscription) -> None:
    """Remove *sub* from *job_id*'s subscriber list."""
    with _lock:
        subs = _subscribers.get(job_id)
        if subs is not None:
            try:
                subs.remove(sub)
            except ValueError:
                pass
            if not subs:
                del _subscribers[job_id]


def publish(job_id: str, event: Dict[str, Any], *, event_type: Optional[str] = None) -> None:
    """Broadcast *event* to all subscribers of *job_id*.

    Called from pipeline threads — must be thread-safe.  If *event_type* is
    given it is merged as ``type`` into the published dict.
    """
    payload: Dict[str, Any] = {}
    if event_type:
        payload["type"] = event_type
    payload["ts"] = datetime.now(timezone.utc).isoformat()
    payload.update(event)

    with _lock:
        subs = _subscribers.get(job_id)
        if not subs:
            return
        for sub in subs:
            sub.events.append(payload)
            sub.notify.set()


def cleanup_job(job_id: str) -> None:
    """Remove all subscribers for *job_id* (call after terminal event)."""
    with _lock:
        subs = _subscribers.pop(job_id, None)
    if subs:
        for sub in subs:
            sub.notify.set()  # wake any blocked consumers so they exit

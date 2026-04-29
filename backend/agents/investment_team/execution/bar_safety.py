"""Engine-side look-ahead guard (Phase 2).

The subprocess harness already makes structural look-ahead impossible from
inside a strategy — there is simply no accessor for future bars in the
strategy process (see ``trading_service/strategy/contract.py``).  The
assertion in this module is the parent-side counterpart: it defends the
``signal-on-t / fill-on-t+1`` contract inside the ``FillSimulator`` so any
future engine refactor that accidentally fills an order against the same
bar on which it was submitted surfaces as a hard error instead of silently
producing inflated backtest results.

``BarSafetyAssertion`` is intentionally tiny: a chronological timestamp
comparison gated on an ``enabled`` flag.  The ``TradingService`` catches
``LookAheadError`` and flips ``TradingServiceResult.lookahead_violation``
so the same classification that the subprocess harness emits also applies
when the violation originates in the fill simulator.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

_COMPACT_OFFSET_RE = re.compile(r"([+-])(\d{2})(\d{2})$")


def _normalize_ts(ts: str) -> str:
    """Best-effort ISO 8601 input normaliser used as both a pre-parse step
    (so ``datetime.fromisoformat`` accepts variants Python < 3.11 doesn't)
    and the fallback string-compare value for unparseable inputs.
    """
    if not isinstance(ts, str):
        return ts
    if ts.endswith("Z"):
        return ts[:-1] + "+00:00"
    m = _COMPACT_OFFSET_RE.search(ts)
    if m:
        return ts[: m.start()] + f"{m.group(1)}{m.group(2)}:{m.group(3)}"
    return ts


def _try_parse_ts(ts: str) -> Optional[datetime]:
    if not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(_normalize_ts(ts))
    except ValueError:
        return None


def _ts_le(a: str, b: str) -> bool:
    """True iff ``a`` is chronologically ``<=`` ``b``.

    Parses both as ISO 8601 datetimes when possible and compares them
    chronologically — so equivalent instants in different timezone offsets
    or formats (e.g. ``2024-01-02T10:00:00Z`` vs
    ``2024-01-02T10:00:00+00:00``) compare equal instead of being ordered
    by raw ASCII string ordering.

    Falls back to normalised string comparison when one side fails to
    parse, or when one side is naive and the other is timezone-aware
    (Python raises ``TypeError`` on mixed-awareness datetime comparisons).
    """
    a_dt = _try_parse_ts(a)
    b_dt = _try_parse_ts(b)
    if a_dt is not None and b_dt is not None:
        if (a_dt.tzinfo is None) == (b_dt.tzinfo is None):
            return a_dt <= b_dt
    return _normalize_ts(a) <= _normalize_ts(b)


class LookAheadError(RuntimeError):
    """Raised when the fill simulator would fill an order against a bar the
    strategy saw at (or before) order-submission time.

    Carries the offending ``order_id`` and the two timestamps so failure
    messages in logs/tests point directly at the responsible bar.
    """

    def __init__(self, *, order_id: str, submitted_at: str, fill_bar_timestamp: str) -> None:
        super().__init__(
            f"order {order_id!r} submitted at {submitted_at!r} would fill against "
            f"bar at {fill_bar_timestamp!r}; fill must be strictly after submission."
        )
        self.order_id = order_id
        self.submitted_at = submitted_at
        self.fill_bar_timestamp = fill_bar_timestamp


class BarSafetyAssertion:
    """Stateless guard that enforces strict ``fill_bar > submitted_at``.

    Comparison is *chronological* — equivalent instants in different ISO 8601
    encodings (``Z`` suffix vs ``+00:00``, compact ``+0000`` vs
    ``+00:00``, equivalent offsets like ``+05:30`` vs ``+00:00``) are
    treated as equal and correctly trip the guard. ``YYYY-MM-DD`` and
    ``YYYY-MM-DDTHH:MM:SS`` (naive) inputs still compare lexicographically
    via the fallback path. When ``enabled=False`` the assertion becomes a
    no-op — used only by tests that deliberately construct pathological
    traces to verify the assertion fires when enabled.
    """

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled

    def check_fill(
        self,
        *,
        order_id: str,
        submitted_at: str,
        fill_bar_timestamp: str,
    ) -> None:
        if not self.enabled:
            return
        if not submitted_at or not fill_bar_timestamp:
            # Missing metadata would make the comparison meaningless; skip
            # rather than false-positive on records predating this field.
            return
        # ``fill_bar_timestamp <= submitted_at`` chronologically — i.e. the
        # fill bar isn't *strictly* after the submission bar. Equivalent
        # instants in different formats trip this branch (the canonical
        # same-bar fill case) instead of falsely passing on ASCII ordering.
        if _ts_le(fill_bar_timestamp, submitted_at):
            raise LookAheadError(
                order_id=order_id,
                submitted_at=submitted_at,
                fill_bar_timestamp=fill_bar_timestamp,
            )


__all__ = ["BarSafetyAssertion", "LookAheadError"]

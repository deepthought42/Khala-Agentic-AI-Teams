"""Durable, content-addressed market-data cache (issue #376).

Owns four concerns:

* **Parquet snapshots on disk** under
  ``${AGENT_CACHE}/investment_team/market_data/...`` — one file per
  ``(asset_class, symbol, frequency, provider, fetch_date)``, immutable
  once written.
* **Postgres index** ``investment_market_data_snapshots`` — looks up
  the latest snapshot authoritative for a requested ``[start, end]``
  range with ``fetch_ts <= as_of``.  A snapshot records the range its
  bars actually span *and* the range the fetch asked for; the two
  diverge whenever a provider serves a short series, and only the
  former is a claim about data (see :class:`SnapshotMeta`).  Falls back to an in-process index when
  ``POSTGRES_HOST`` is unset; that path is enough for unit tests but
  loses cross-process reproducibility, which is the whole point of the
  cache, so production must run with Postgres.
* **Canonical SHA256 fingerprint** over OHLCV rows — emitted on
  ``BacktestResult.dataset_fingerprint`` and used as the key for the
  derived ADV cache, replacing the in-memory TTL cache previously
  hard-coded in :class:`MarketDataService`.
* **Derived ADV cache** keyed on ``(per-symbol fingerprint, lookback)``
  — eternal validity within a fingerprint, no TTL.

The store is deliberately provider-agnostic: callers pass a ``fetch_fn``
that returns ``(bars, provider_slug)``.  Provider chains, retry policy,
and the intraday-safety guard live in :class:`MarketDataService`.
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import threading
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from shared.concurrency import parallel_map
from shared.postgres import PostgresHelperMixin, is_postgres_enabled

from ..market_data_service import OHLCVBar, compute_adv_from_bars
from . import paths as _paths

if TYPE_CHECKING:
    import pyarrow as pa  # noqa: F401 — for forward-ref annotations only

logger = logging.getLogger(__name__)

# Lazy: built on first use by _get_parquet_schema().  Importing pyarrow at
# module load would force every consumer of investment_team.api.main to have
# pyarrow installed, even when no caller exercises the parquet write path.
_PARQUET_SCHEMA: Any = None


def _get_parquet_schema() -> Any:
    global _PARQUET_SCHEMA
    if _PARQUET_SCHEMA is None:
        import pyarrow as pa  # noqa: PLC0415 — deliberate lazy import

        _PARQUET_SCHEMA = pa.schema(
            [
                ("date", pa.string()),
                ("open", pa.float64()),
                ("high", pa.float64()),
                ("low", pa.float64()),
                ("close", pa.float64()),
                ("volume", pa.float64()),
                # Provenance flag for forward-filled (synthetic) bars. Persisted
                # so cache reads can exclude imputed bars from ADV / liquidity
                # math exactly as a live fetch does — without it,
                # ``compute_adv_from_bars`` would see ``is_imputed=False`` on
                # every cached bar and silently count synthetic days. Snapshots
                # written before this column existed read back with the flag
                # defaulted to ``False`` (see ``_table_to_bars``).
                ("is_imputed", pa.bool_()),
            ]
        )
    return _PARQUET_SCHEMA


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SnapshotMeta:
    """Metadata for a single cached snapshot row.

    Mirrors the columns of ``investment_market_data_snapshots``.
    ``parquet_path`` is the absolute path on disk; ``sha256`` is the
    canonical fingerprint of the bars, suitable for use as a derived-cache
    key.

    Two date ranges, deliberately distinct:

    * ``start_date`` / ``end_date`` — the **realised** bounds: the first and
      last bar actually present in the parquet file.  :meth:`covers`
      answers "do these bars really span the window?" from them.
    * ``requested_start_date`` / ``requested_end_date`` — the window the
      fetch *asked* the provider for.  ``None`` on rows written before the
      distinction existed, in which case the realised pair stands in (see
      :attr:`requested_start`).

    The two differ whenever a provider returns a short series — a symbol
    whose history begins after ``start``, or a provider that caps how far
    back it serves.  Recording only the request (as this store once did)
    made a truncated snapshot indistinguishable from a complete one, and
    the lie was durable: the next lookup for the same window replayed the
    short series as though it spanned the request.  They also differ, the
    other way, when a provider rounds outward and returns *more* than was
    asked for.

    Invariants:
        ``start_date <= end_date`` and ``requested_start <= requested_end``.
        Neither pair constrains the other — a provider may return less than
        it was asked for (truncation) or more (outward rounding); both are
        represented faithfully rather than collapsed.
    """

    symbol: str
    asset_class: str
    frequency: str
    provider: str
    fetch_ts: datetime
    start_date: str
    end_date: str
    row_count: int
    sha256: str
    parquet_path: str
    schema_version: int = 1
    requested_start_date: Optional[str] = None
    requested_end_date: Optional[str] = None

    @property
    def requested_start(self) -> str:
        """Requested window start, falling back to the realised start.

        Postconditions:
            Returns ``requested_start_date`` when recorded, else
            ``start_date`` — so a legacy row (whose ``start_date`` *was* the
            requested bound) keeps its original lookup semantics.
        """
        return self.requested_start_date or self.start_date

    @property
    def requested_end(self) -> str:
        """Requested window end, falling back to the realised end.

        Postconditions:
            Returns ``requested_end_date`` when recorded, else ``end_date``.
        """
        return self.requested_end_date or self.end_date

    def covers(self, start: str, end: str) -> bool:
        """True when the snapshot's **bars** span ``[start, end]``.

        This is the data-truth question, and the one a consumer reasoning
        about temporal completeness must ask.  A snapshot written for a
        wider request than the provider could serve answers ``False`` here
        even though :meth:`is_authoritative_for` answers ``True``.

        Preconditions:
            ``start`` and ``end`` are ISO date strings (``YYYY-MM-DD``),
            comparable lexicographically against the stored bounds.
        Postconditions:
            Returns ``True`` iff ``start_date <= start`` and
            ``end_date >= end``.  Says nothing about gaps *inside* the
            range — ``execution.data_quality.validate_market_data`` owns
            that question.
        """
        return self.start_date <= start and self.end_date >= end

    def is_authoritative_for(self, start: str, end: str) -> bool:
        """True when this snapshot is the provider's complete answer for the window.

        A date is answered either because the snapshot holds bars for it
        (inside the realised range) or because the provider was asked about
        it and returned nothing (inside the requested range).  The union of
        the two is what a refetch could not improve on, so it — not the
        realised range alone — is the cache-hit predicate.  Matching on the
        realised range alone would refetch forever for any symbol whose
        history genuinely starts later than the windows callers ask for.

        Preconditions:
            ``start`` and ``end`` are ISO date strings (``YYYY-MM-DD``).
        Postconditions:
            Returns ``True`` iff ``[start, end]`` lies within
            ``[min(start_date, requested_start), max(end_date, requested_end)]``.
        """
        return min(self.start_date, self.requested_start) <= start and (
            max(self.end_date, self.requested_end) >= end
        )


FetchFn = Callable[[str, str, str, str], Tuple[List[OHLCVBar], str]]
"""``fetch_fn(symbol, asset_class, start, end) -> (bars, provider_slug)``.

Returns ``([], "")`` when every provider is exhausted; the cache treats
that as a miss and does not write a snapshot.
"""


# ---------------------------------------------------------------------------
# Canonical fingerprinting
# ---------------------------------------------------------------------------


def _finite_volume(volume: Any) -> float:
    """Coerce a non-finite (NaN/±inf) or ``None`` volume to the 0.0 sentinel.

    ``OHLCVBar`` is a permissive transport, so a non-finite volume can reach the
    cache from any snapshot writer (live fetch, streaming ingest, paper-trade
    warm-up, …). Applying this one coercion at every persistence boundary — the
    parquet writer, the content hash / dataset fingerprint, and read-back —
    guarantees the stored bytes, the fingerprint, and a replayed bar are all
    finite and byte-identical regardless of which writer produced the snapshot,
    so a first run and its cached replay never diverge on bad volume.

    Preconditions:
        ``volume`` is a float-coercible value or ``None``.
    Postconditions:
        Returns a finite float. Non-finite or ``None`` input returns ``0.0``
        (the zero-volume sentinel ADV/liquidity math already excludes); a finite
        input round-trips unchanged, so fingerprints of clean data are stable.
    """
    if volume is None:
        return 0.0
    v = float(volume)
    return v if math.isfinite(v) else 0.0


def _canonicalize_bar_volumes(bars: Sequence[OHLCVBar]) -> List[OHLCVBar]:
    """Return ``bars`` with any non-finite volume replaced by 0.0.

    Applied to the bars a cache miss both persists and returns, so first-run
    consumption matches the 0.0 a later replay reads back from the snapshot —
    the provider-agnostic cache canonicalises volume on behalf of callers that
    did not pre-normalise, instead of persisting 0.0 but handing back the raw
    NaN/inf on the miss path.

    Postconditions:
        Returns a list the same length/order as ``bars``; bars with a finite
        volume are returned unchanged (same object), non-finite ones are
        replaced by a copy with ``volume=0.0``.
    """
    out: List[OHLCVBar] = []
    for b in bars:
        if math.isfinite(b.volume):
            out.append(b)
        else:
            out.append(b.model_copy(update={"volume": 0.0}))
    return out


def _reconcile_snapshot_hash(meta: SnapshotMeta, bars: Sequence[OHLCVBar]) -> SnapshotMeta:
    """Return ``meta`` with ``sha256`` recomputed to match read-repaired ``bars``.

    A legacy snapshot persisted before volume canonicalisation carries a stored
    ``sha256`` over the raw (possibly non-finite) volume, but ``_table_to_bars``
    repairs that volume to ``0.0`` on read. Recompute the per-snapshot hash from
    the bars actually returned so a client's reproducibility / derived-cache key
    (``meta.sha256``) agrees with ``compute_dataset_fingerprint(read_bars)``
    instead of identifying the stale unrepaired dataset.

    Postconditions:
        Returns ``meta`` unchanged (same object) when the recomputed hash already
        matches — the common case for snapshots written with finite volume, so
        there is no churn. Otherwise returns a copy with the corrected ``sha256``.
    """
    recomputed = _hash_bars(bars)
    if recomputed == meta.sha256:
        return meta
    return replace(meta, sha256=recomputed)


def _realised_bounds(bars: Sequence[OHLCVBar]) -> Tuple[str, str]:
    """Return the ``(first, last)`` calendar date actually present in ``bars``.

    Dates are truncated to ``YYYY-MM-DD`` so an intraday snapshot (whose
    ``bar.date`` carries a full ISO timestamp) yields bounds comparable
    against the date-granular requested window and storable in the ``DATE``
    columns of ``investment_market_data_snapshots`` — keeping the Postgres
    and in-memory index branches byte-comparable on the same values.

    Bars are not assumed sorted: ``fetch_fn`` is provider-supplied and this
    store only guarantees chronological order at hash time.

    Preconditions:
        ``bars`` is non-empty and every bar's ``date`` is an ISO-8601 date
        or datetime string.
    Postconditions:
        Returns ``(lo, hi)`` with ``lo <= hi``, both ``YYYY-MM-DD``.
    """
    assert bars, "_realised_bounds requires at least one bar"
    days = [b.date[:10] for b in bars]
    return min(days), max(days)


def _reconcile_snapshot_bounds(meta: SnapshotMeta, bars: Sequence[OHLCVBar]) -> SnapshotMeta:
    """Return ``meta`` with realised bounds repaired to match ``bars``.

    A snapshot written before this store distinguished requested from
    realised coverage recorded the *request* in ``start_date`` /
    ``end_date``, so a truncated series reads back claiming a range it never
    had.  Recomputing the bounds from the bars on the read path makes those
    rows self-healing — the same read-repair strategy
    :func:`_reconcile_snapshot_hash` applies to a stale fingerprint — without
    a backfill migration or a write on every cache hit.  The original
    (requested) range is preserved in ``requested_start_date`` /
    ``requested_end_date`` so the lookup predicate keeps its old reach.

    Postconditions:
        Returns ``meta`` unchanged (same object) when the recorded bounds
        already match the bars — the common case, so there is no churn.
        Otherwise returns a copy whose ``start_date``/``end_date`` are the
        bars' realised bounds and whose ``requested_*`` pair retains the
        previously recorded (requested) range.  ``bars`` empty returns
        ``meta`` unchanged: an empty parquet carries no bounds to trust.
    """
    if not bars:
        return meta
    lo, hi = _realised_bounds(bars)
    if lo == meta.start_date and hi == meta.end_date:
        return meta
    return replace(
        meta,
        start_date=lo,
        end_date=hi,
        requested_start_date=meta.requested_start,
        requested_end_date=meta.requested_end,
    )


def _reconcile_snapshot(meta: SnapshotMeta, bars: Sequence[OHLCVBar]) -> SnapshotMeta:
    """Read-repair a snapshot's metadata against the bars actually read back.

    Composes the two independent repairs — fingerprint
    (:func:`_reconcile_snapshot_hash`) and realised coverage
    (:func:`_reconcile_snapshot_bounds`) — so every read path describes the
    bars the caller is handed rather than what the writer believed.

    Postconditions:
        Returns ``meta`` unchanged (same object) when neither repair
        applies.
    """
    return _reconcile_snapshot_hash(_reconcile_snapshot_bounds(meta, bars), bars)


def _hash_bars(bars: Sequence[OHLCVBar]) -> str:
    """SHA256 over a deterministic byte stream of bars.

    Bars are serialized in chronological-date order so callers may pass
    them in any order; floats use ``repr()`` so the round-trip is
    bit-exact.  Empty input is hashed to the empty digest of an empty
    string.

    Only OHLCV identifies a dataset — ``is_imputed`` is deliberately excluded
    so snapshots written before that column existed keep the same fingerprint
    (and thus the same derived-ADV cache key) once the flag is persisted. This
    is safe because forward-fill is deterministic on its input: identical OHLCV
    implies the same imputed layout, so two series can collide on this hash yet
    differ in ``is_imputed`` only in degenerate equal-price / zero-volume data,
    which the volume>0 filter in ``compute_adv_from_bars`` already discards.
    """
    h = hashlib.sha256()
    for bar in sorted(bars, key=lambda b: b.date):
        # Coerce volume so a writer that persisted a non-finite volume hashes
        # to the same fingerprint a replay (which read it back as 0.0) produces.
        # Finite volumes round-trip unchanged, so clean snapshots keep their
        # existing fingerprint / derived-ADV cache key.
        h.update(
            f"{bar.date}|{repr(bar.open)}|{repr(bar.high)}|"
            f"{repr(bar.low)}|{repr(bar.close)}|{repr(_finite_volume(bar.volume))}\n".encode()
        )
    return h.hexdigest()


def compute_dataset_fingerprint(per_symbol: Mapping[str, Sequence[OHLCVBar]]) -> str:
    """Hash a multi-symbol bars dict in a symbol-order-independent way.

    The same set of ``(symbol, bars)`` pairs always hashes the same,
    regardless of dict insertion order or per-symbol bar order — making
    this safe to use as ``BacktestResult.dataset_fingerprint``.
    """
    parts = sorted(f"{symbol}:{_hash_bars(bars)}" for symbol, bars in per_symbol.items())
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode())
        h.update(b"\n")
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Parquet I/O
# ---------------------------------------------------------------------------


def _bars_to_table(bars: Sequence[OHLCVBar]) -> "pa.Table":
    import pyarrow as pa  # noqa: PLC0415 — deliberate lazy import

    return pa.Table.from_pydict(
        {
            "date": [b.date for b in bars],
            "open": [float(b.open) for b in bars],
            "high": [float(b.high) for b in bars],
            "low": [float(b.low) for b in bars],
            "close": [float(b.close) for b in bars],
            # Coerce at the write boundary so no writer can persist a non-finite
            # volume into the parquet snapshot, regardless of how it built the
            # bars (live fetch, streaming ingest, paper-trade warm-up, …).
            "volume": [_finite_volume(b.volume) for b in bars],
            "is_imputed": [bool(b.is_imputed) for b in bars],
        },
        schema=_get_parquet_schema(),
    )


def _table_to_bars(table: "pa.Table") -> List[OHLCVBar]:
    cols = {
        name: table[name].to_pylist() for name in ("date", "open", "high", "low", "close", "volume")
    }
    # ``is_imputed`` is a newer column; snapshots written before it existed
    # lack it entirely, so default the whole series to False rather than
    # KeyError on the older schema.
    imputed = (
        table["is_imputed"].to_pylist()
        if "is_imputed" in table.schema.names
        else [False] * table.num_rows
    )
    # Normalise OHLC invariants on cache read. Parquet snapshots persisted
    # before market_data_service started repairing invariants at fetch
    # time still contain inconsistent bars (Yahoo / Alpha Vantage / Twelve
    # Data daily FX aggregates intraday snapshots across counterparties,
    # producing H < max(O, C) or L > min(O, C)). Repairing on read makes
    # the cache self-healing without forcing a global re-fetch. The same
    # self-healing applies to non-finite volume: snapshots persisted before
    # market_data_service started neutralising NaN/inf volume at fetch time
    # would otherwise replay it straight past the OHLCVBar transport (which
    # is intentionally permissive) into ADV / cost-model arithmetic. Coerce
    # to 0.0 here — the zero-volume sentinel ADV/liquidity math excludes —
    # mirroring _normalize_ohlc_bar on the live path.
    bars: List[OHLCVBar] = []
    repairs = 0
    vol_repairs = 0
    for i in range(table.num_rows):
        o = cols["open"][i]
        h = cols["high"][i]
        ll = cols["low"][i]
        c = cols["close"][i]
        h_fixed = max(o, h, ll, c)
        l_fixed = min(o, h, ll, c)
        if h_fixed != h or l_fixed != ll:
            repairs += 1
        raw_vol = cols["volume"][i]
        if raw_vol is None or not math.isfinite(raw_vol):
            vol_repairs += 1
        vol = _finite_volume(raw_vol)
        bars.append(
            OHLCVBar(
                date=cols["date"][i],
                open=o,
                high=h_fixed,
                low=l_fixed,
                close=c,
                volume=vol,
                is_imputed=bool(imputed[i]),
            )
        )
    if repairs > 0:
        logger.warning(
            "market_data_cache: repaired OHLC invariants on %d/%d bars at read",
            repairs,
            table.num_rows,
        )
    if vol_repairs > 0:
        logger.warning(
            "market_data_cache: coerced non-finite volume to 0.0 on %d/%d bars at read",
            vol_repairs,
            table.num_rows,
        )
    return bars


# ---------------------------------------------------------------------------
# Index (Postgres-backed, with in-memory fallback)
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _parse_as_of(as_of: Optional[str]) -> datetime:
    """Normalize ``as_of`` to a UTC datetime cutoff.

    ``None`` means "now"; a bare date string means end-of-day UTC; a full
    ISO datetime is parsed verbatim.
    """
    if not as_of:
        return _now_utc()
    s = as_of.strip()
    try:
        if "T" in s or " " in s:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        else:
            d = date.fromisoformat(s[:10])
            dt = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=timezone.utc)
    except ValueError:
        return _now_utc()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _row_to_meta(row: Mapping[str, object]) -> SnapshotMeta:
    fetch_ts = row["fetch_ts"]
    if isinstance(fetch_ts, str):
        fetch_ts = datetime.fromisoformat(fetch_ts.replace("Z", "+00:00"))
    if isinstance(fetch_ts, datetime) and fetch_ts.tzinfo is None:
        fetch_ts = fetch_ts.replace(tzinfo=timezone.utc)

    def _as_iso(value: object) -> Optional[str]:
        """Normalize a DATE column to ``YYYY-MM-DD``; ``None`` stays ``None``.

        psycopg hands back :class:`datetime.date` for a ``DATE`` column but a
        plain string when the row came from a stub or an older driver, and
        ``NULL`` for the ``requested_*`` columns on rows written before they
        existed.
        """
        if value is None:
            return None
        if isinstance(value, date):
            return value.isoformat()
        return str(value)

    start_d = _as_iso(row["start_date"])
    end_d = _as_iso(row["end_date"])
    return SnapshotMeta(
        symbol=str(row["symbol"]),
        asset_class=str(row["asset_class"]),
        frequency=str(row["frequency"]),
        provider=str(row["provider"]),
        fetch_ts=fetch_ts,  # type: ignore[arg-type]
        start_date=str(start_d),
        end_date=str(end_d),
        row_count=int(row["row_count"]),
        sha256=str(row["sha256"]),
        parquet_path=str(row["parquet_path"]),
        schema_version=int(row.get("schema_version", 1)),
        requested_start_date=_as_iso(row.get("requested_start_date")),
        requested_end_date=_as_iso(row.get("requested_end_date")),
    )


# ---------------------------------------------------------------------------
# MarketDataCache
# ---------------------------------------------------------------------------


def _default_workers(symbol_count: int) -> int:
    raw = os.environ.get("MARKET_DATA_FETCH_WORKERS", "").strip()
    if raw:
        try:
            n = int(raw)
            if n >= 1:
                return n
        except ValueError:
            pass
    return max(1, min(symbol_count, 16))


class MarketDataCache(PostgresHelperMixin):
    """Snapshot-based cache.  See module docstring."""

    def __init__(self, *, cache_root: Optional[Path] = None) -> None:
        super().__init__()
        self._cache_root: Optional[Path] = cache_root
        # In-memory index used when Postgres is disabled.  Each entry is a
        # full ``SnapshotMeta``; lookups iterate (the table is small and
        # bounded by call volume per process).
        self._memory_index: List[SnapshotMeta] = []
        self._index_lock = threading.Lock()
        # Derived ADV cache keyed on ``(symbol_fingerprint, lookback)``.
        # Stored in-process; cross-process correctness is automatic
        # because the key is content-addressed.
        self._adv_cache: Dict[Tuple[str, int], Optional[float]] = {}
        self._adv_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def _resolved_root(self) -> Path:
        return self._cache_root if self._cache_root is not None else _paths.cache_root()

    def _snapshot_path(
        self, *, asset_class: str, symbol: str, frequency: str, provider: str, fetch_date: str
    ) -> Path:
        if self._cache_root is None:
            return _paths.snapshot_path(
                asset_class=asset_class,
                symbol=symbol,
                frequency=frequency,
                provider=provider,
                fetch_date=fetch_date,
            )
        return (
            self._cache_root / asset_class / symbol / frequency / provider / f"{fetch_date}.parquet"
        )

    # ------------------------------------------------------------------
    # Index queries
    # ------------------------------------------------------------------

    def _find_covering_snapshot(
        self,
        *,
        symbol: str,
        asset_class: str,
        frequency: str,
        start: str,
        end: str,
        as_of_dt: datetime,
    ) -> Optional[SnapshotMeta]:
        """Return the newest snapshot authoritative for ``[start, end]``, or None.

        The predicate is :meth:`SnapshotMeta.is_authoritative_for` — the union
        of the realised and requested ranges — expressed in SQL with
        ``LEAST``/``GREATEST`` so the Postgres and in-memory index branches
        agree bar-for-bar.  ``COALESCE`` folds a legacy row (whose
        ``requested_*`` columns are ``NULL`` and whose ``start_date`` /
        ``end_date`` hold the requested window) onto the same predicate it
        matched before the columns existed, so no refetch wave follows the
        migration.

        Preconditions:
            ``start``/``end`` are ISO date strings; ``as_of_dt`` is
            timezone-aware.
        Postconditions:
            Returns the highest-``fetch_ts`` snapshot with ``fetch_ts <=
            as_of_dt`` that is authoritative for the window, or ``None``.
            A snapshot returned here may still fail :meth:`SnapshotMeta.covers`
            — that is the truncation case, and the caller is told rather than
            sent back to the provider for data that does not exist.
        """
        if is_postgres_enabled():
            try:
                row = self._fetch_one(
                    """
                    SELECT symbol, asset_class, frequency, provider, fetch_ts,
                           start_date, end_date,
                           requested_start_date, requested_end_date,
                           row_count, sha256,
                           schema_version, parquet_path
                      FROM investment_market_data_snapshots
                     WHERE symbol = %s
                       AND asset_class = %s
                       AND frequency = %s
                       AND fetch_ts <= %s
                       AND LEAST(start_date,
                                 COALESCE(requested_start_date, start_date)) <= %s
                       AND GREATEST(end_date,
                                    COALESCE(requested_end_date, end_date)) >= %s
                     ORDER BY fetch_ts DESC
                     LIMIT 1
                    """,
                    (symbol, asset_class, frequency, as_of_dt, start, end),
                )
                if row is None:
                    return None
                return _row_to_meta(row)
            except Exception:
                logger.exception(
                    "investment_market_data_snapshots lookup failed; falling back to memory index"
                )
                # fall through to memory path

        with self._index_lock:
            candidates = [
                m
                for m in self._memory_index
                if m.symbol == symbol
                and m.asset_class == asset_class
                and m.frequency == frequency
                and m.fetch_ts <= as_of_dt
                and m.is_authoritative_for(start, end)
            ]
        if not candidates:
            return None
        return max(candidates, key=lambda m: m.fetch_ts)

    def _record_snapshot(self, meta: SnapshotMeta) -> None:
        if is_postgres_enabled():
            try:
                self._execute(
                    """
                    INSERT INTO investment_market_data_snapshots
                        (symbol, asset_class, frequency, provider, fetch_ts,
                         start_date, end_date,
                         requested_start_date, requested_end_date,
                         row_count, sha256,
                         schema_version, parquet_path)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        meta.symbol,
                        meta.asset_class,
                        meta.frequency,
                        meta.provider,
                        meta.fetch_ts,
                        meta.start_date,
                        meta.end_date,
                        meta.requested_start_date,
                        meta.requested_end_date,
                        meta.row_count,
                        meta.sha256,
                        meta.schema_version,
                        meta.parquet_path,
                    ),
                )
                return
            except Exception:
                logger.exception(
                    "investment_market_data_snapshots insert failed; recording in memory index only"
                )
        with self._index_lock:
            self._memory_index.append(meta)

    # ------------------------------------------------------------------
    # Snapshot read/write
    # ------------------------------------------------------------------

    def _read_snapshot(self, meta: SnapshotMeta) -> Optional[List[OHLCVBar]]:
        path = Path(meta.parquet_path)
        if not path.exists():
            logger.warning(
                "snapshot %s missing on disk (provider=%s, range=%s..%s); refetching",
                path,
                meta.provider,
                meta.start_date,
                meta.end_date,
            )
            return None
        try:
            import pyarrow.parquet as pq  # noqa: PLC0415 — deliberate lazy import

            table = pq.read_table(path)
        except Exception:
            logger.exception("failed to read parquet snapshot at %s; refetching", path)
            return None
        return _table_to_bars(table)

    def _write_snapshot(
        self,
        *,
        symbol: str,
        asset_class: str,
        frequency: str,
        provider: str,
        bars: Sequence[OHLCVBar],
        start: str,
        end: str,
    ) -> SnapshotMeta:
        """Persist ``bars`` as a parquet snapshot and index it.

        ``start``/``end`` are the window the fetch *requested*; the recorded
        coverage is derived from the bars themselves.  Passing the request
        through as the coverage — as this store once did — silently records a
        truncated series as spanning the full window, and the lie is durable:
        every later lookup for that window replays the short series as
        complete, and nothing re-examines the bounds.

        Preconditions:
            ``bars`` is non-empty (empty fetches must not produce a
            snapshot); ``start <= end`` are ISO date strings.
        Postconditions:
            A parquet file exists at the returned ``parquet_path`` and the
            snapshot is indexed.  ``start_date``/``end_date`` are the bars'
            realised bounds and ``requested_start_date``/
            ``requested_end_date`` the requested window, so
            :meth:`SnapshotMeta.covers` is exact for the returned meta.
        """
        assert bars, "_write_snapshot requires at least one bar"
        requested_start, requested_end = start[:10], end[:10]
        realised_start, realised_end = _realised_bounds(bars)
        if realised_start > requested_start or realised_end < requested_end:
            # Not an error: a symbol whose history begins mid-window, or a
            # provider that caps how far back it serves. Worth a warning
            # because it is the condition that used to vanish into a
            # full-coverage claim, and the snapshot now durably records the
            # shortfall instead.
            logger.warning(
                "market_data_cache: %s/%s/%s from %s requested %s..%s but realised %s..%s "
                "(%d bars); recording the realised range",
                asset_class,
                symbol,
                frequency,
                provider,
                requested_start,
                requested_end,
                realised_start,
                realised_end,
                len(bars),
            )
        fetch_ts = _now_utc()
        fetch_date = fetch_ts.date().isoformat()
        out_path = self._snapshot_path(
            asset_class=asset_class,
            symbol=symbol,
            frequency=frequency,
            provider=provider,
            fetch_date=fetch_date,
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)

        table = _bars_to_table(bars)
        # Two snapshots written on the same UTC day from the same
        # provider would collide on path; suffix with a microsecond stamp
        # to keep the original immutable.
        if out_path.exists():
            stamp = fetch_ts.strftime("%Y-%m-%dT%H%M%S%f")
            out_path = out_path.with_name(f"{stamp}.parquet")
        import pyarrow.parquet as pq  # noqa: PLC0415 — deliberate lazy import

        pq.write_table(table, out_path, compression="snappy")

        meta = SnapshotMeta(
            symbol=symbol,
            asset_class=asset_class,
            frequency=frequency,
            provider=provider,
            fetch_ts=fetch_ts,
            start_date=realised_start,
            end_date=realised_end,
            row_count=len(bars),
            sha256=_hash_bars(bars),
            parquet_path=str(out_path),
            requested_start_date=requested_start,
            requested_end_date=requested_end,
        )
        self._record_snapshot(meta)
        return meta

    # ------------------------------------------------------------------
    # Public: get_or_fetch
    # ------------------------------------------------------------------

    def get_or_fetch(
        self,
        *,
        symbol: str,
        asset_class: str,
        frequency: str,
        start: str,
        end: str,
        fetch_fn: FetchFn,
        as_of: Optional[str] = None,
    ) -> Tuple[List[OHLCVBar], Optional[SnapshotMeta]]:
        """Return bars for ``[start, end]`` for one symbol.

        On cache hit returns ``(bars_from_parquet, meta)`` without
        invoking ``fetch_fn``.  On miss invokes ``fetch_fn`` once, writes
        a new snapshot, and indexes it.  Empty fetches do not produce a
        snapshot — ``meta`` is None and the bar list is empty.

        The returned bars are trimmed to ``[start, end]``, so their span
        cannot distinguish a snapshot that genuinely covers the window from
        one that only claims to.  ``meta`` can: its ``start_date``/
        ``end_date`` are the bars actually obtained, and
        :meth:`SnapshotMeta.covers` compares them against the request.

        Preconditions:
            ``start <= end`` are ISO date strings; ``fetch_fn`` honours the
            :data:`FetchFn` contract.
        Postconditions:
            Returns ``([], None)`` when no snapshot exists and the provider
            chain is exhausted.  Otherwise ``meta`` is not None and describes
            the returned bars — including, when the provider served less than
            was asked for, a range narrower than ``[start, end]``.
        """
        as_of_dt = _parse_as_of(as_of)
        existing = self._find_covering_snapshot(
            symbol=symbol,
            asset_class=asset_class,
            frequency=frequency,
            start=start,
            end=end,
            as_of_dt=as_of_dt,
        )
        if existing is not None:
            cached = self._read_snapshot(existing)
            if cached is not None:
                # A legacy snapshot's stored sha256 is over the raw volume and
                # its bounds are the requested window, but _read_snapshot
                # repaired the volume to 0.0 and the bars say what the range
                # really is; reconcile both so the returned meta describes the
                # bars the caller actually gets.
                existing = _reconcile_snapshot(existing, cached)
                if not existing.covers(start, end):
                    logger.warning(
                        "market_data_cache: replaying %s/%s/%s for %s..%s from a snapshot "
                        "covering only %s..%s — the provider served a short series",
                        asset_class,
                        symbol,
                        frequency,
                        start,
                        end,
                        existing.start_date,
                        existing.end_date,
                    )
                trimmed = [b for b in cached if start <= b.date <= end]
                return trimmed, existing

        bars, provider = fetch_fn(symbol, asset_class, start, end)
        if not bars or not provider:
            return [], None
        # Canonicalise volume before persisting *and* returning so the miss-path
        # bars the caller consumes match the 0.0 a later cache hit replays from
        # the snapshot — a fetch_fn that returns a non-finite volume can't make
        # first-run and replay diverge.
        bars = _canonicalize_bar_volumes(bars)
        meta = self._write_snapshot(
            symbol=symbol,
            asset_class=asset_class,
            frequency=frequency,
            provider=provider,
            bars=bars,
            start=start,
            end=end,
        )
        return list(bars), meta

    def get_or_fetch_multi(
        self,
        *,
        symbols: Sequence[str],
        asset_class: str,
        frequency: str,
        start: str,
        end: str,
        fetch_fn: FetchFn,
        as_of: Optional[str] = None,
    ) -> Dict[str, Tuple[List[OHLCVBar], Optional[SnapshotMeta]]]:
        """Parallel wrapper around :meth:`get_or_fetch`.

        Workers come from ``MARKET_DATA_FETCH_WORKERS`` (default
        ``min(len(symbols), 16)``).  Per-symbol failures are logged and
        omitted from the result; the caller decides what to do with
        partial coverage.
        """
        result: Dict[str, Tuple[List[OHLCVBar], Optional[SnapshotMeta]]] = {}
        if not symbols:
            return result
        workers = _default_workers(len(symbols))

        def _fetch_one(sym: str) -> Optional[Tuple[str, List[OHLCVBar], Optional[SnapshotMeta]]]:
            try:
                bars, meta = self.get_or_fetch(
                    symbol=sym,
                    asset_class=asset_class,
                    frequency=frequency,
                    start=start,
                    end=end,
                    fetch_fn=fetch_fn,
                    as_of=as_of,
                )
            except Exception as exc:
                logger.warning("cache fetch failed for %s: %s", sym, exc)
                return None
            if not bars:
                return None
            return (sym, bars, meta)

        for sym, bars, meta in parallel_map(
            symbols, _fetch_one, max_workers=workers, preserve_order=False, skip_none=True
        ):
            result[sym] = (bars, meta)
        return result

    # ------------------------------------------------------------------
    # Snapshot from already-materialized bars (used by streaming wrapper)
    # ------------------------------------------------------------------

    def record_bars_snapshot(
        self,
        *,
        symbol: str,
        asset_class: str,
        frequency: str,
        provider: str,
        bars: Sequence[OHLCVBar],
        start: str,
        end: str,
    ) -> Optional[SnapshotMeta]:
        """Persist bars that the caller already fetched (e.g. via a stream).

        ``start``/``end`` are the requested window; as on the ``get_or_fetch``
        miss path, the snapshot's recorded coverage comes from the bars.

        Postconditions:
            Returns ``None`` when ``bars`` is empty (no snapshot written),
            else a ``SnapshotMeta`` whose realised bounds match ``bars``.
        """
        if not bars:
            return None
        return self._write_snapshot(
            symbol=symbol,
            asset_class=asset_class,
            frequency=frequency,
            provider=provider,
            bars=bars,
            start=start,
            end=end,
        )

    def lookup_snapshot(
        self,
        *,
        symbol: str,
        asset_class: str,
        frequency: str,
        start: str,
        end: str,
        as_of: Optional[str] = None,
    ) -> Optional[SnapshotMeta]:
        """Metadata-only lookup: is a snapshot authoritative for this window?

        Postconditions:
            Returns ``None`` on a miss.  The returned meta is the *indexed*
            one — unlike the meta :meth:`get_or_fetch` hands back, its bounds
            have not been read-repaired against the parquet, because that
            would cost a file read.  A caller that goes on to
            :meth:`read_snapshot` should pass the bars through
            :func:`_reconcile_snapshot` before trusting the bounds of a row
            written before requested and realised coverage were split.
        """
        return self._find_covering_snapshot(
            symbol=symbol,
            asset_class=asset_class,
            frequency=frequency,
            start=start,
            end=end,
            as_of_dt=_parse_as_of(as_of),
        )

    def read_snapshot(self, meta: SnapshotMeta) -> Optional[List[OHLCVBar]]:
        return self._read_snapshot(meta)

    # ------------------------------------------------------------------
    # Derived ADV cache
    # ------------------------------------------------------------------

    def derive_adv(
        self,
        *,
        fingerprint: str,
        lookback: int,
        compute: Callable[[], Optional[float]],
    ) -> Optional[float]:
        """Memoize ``compute()`` under ``(fingerprint, lookback)``.

        The fingerprint must uniquely identify the bar window (typically
        a per-symbol snapshot's ``sha256``); under that key the result is
        eternally valid.
        """
        key = (fingerprint, int(lookback))
        with self._adv_lock:
            if key in self._adv_cache:
                return self._adv_cache[key]
        value = compute()
        with self._adv_lock:
            self._adv_cache[key] = value
        return value

    def adv_for_bars(
        self,
        *,
        bars: Sequence[OHLCVBar],
        lookback: int,
        fingerprint: Optional[str] = None,
    ) -> Optional[float]:
        """Convenience: hash the window and route through ``derive_adv``.

        Caches on the canonical hash of the supplied bars so repeated
        calls with byte-equal input share the result without recomputing.
        """
        fp = fingerprint or _hash_bars(bars)
        return self.derive_adv(
            fingerprint=fp,
            lookback=lookback,
            compute=lambda: compute_adv_from_bars(bars, lookback=lookback),
        )


# ---------------------------------------------------------------------------
# Module-level shared instance
# ---------------------------------------------------------------------------


_DEFAULT_CACHE: Optional[MarketDataCache] = None
_DEFAULT_LOCK = threading.Lock()


def get_default_cache() -> MarketDataCache:
    """Return the process-wide cache instance, lazily constructed.

    Tests construct their own ``MarketDataCache(cache_root=tmp_path)``
    and inject it into the consumer; production code uses this default
    so the cache root resolves once via ``paths.cache_root()``.
    """
    global _DEFAULT_CACHE
    with _DEFAULT_LOCK:
        if _DEFAULT_CACHE is None:
            _DEFAULT_CACHE = MarketDataCache()
        return _DEFAULT_CACHE


def reset_default_cache() -> None:
    """Test helper — discard the module-level cache so the next call rebuilds."""
    global _DEFAULT_CACHE
    with _DEFAULT_LOCK:
        _DEFAULT_CACHE = None


__all__ = [
    "MarketDataCache",
    "SnapshotMeta",
    "FetchFn",
    "compute_dataset_fingerprint",
    "get_default_cache",
    "reset_default_cache",
]

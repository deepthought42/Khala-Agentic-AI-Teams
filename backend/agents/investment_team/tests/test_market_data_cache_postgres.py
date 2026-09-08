"""Postgres-gated path coverage for ``MarketDataCache``.

The production cache layer in :mod:`investment_team.market_data_cache.store`
uses Postgres for the snapshot index when ``POSTGRES_HOST`` is set; the
fallback uses an in-process list. The standard ``test_market_data_cache``
fixture monkey-patches ``POSTGRES_HOST`` away so those tests exercise the
fallback path only. ``MarketDataCache`` reaches Postgres only through
``shared.postgres.PostgresHelperMixin``, which calls ``pg_cursor()`` in
``shared.postgres.client``; this file patches ``shared.postgres.client.get_conn``
and sets ``POSTGRES_HOST`` (so ``pg_cursor``'s ``is_postgres_enabled()`` guard
falls through) so the Postgres branches in ``_find_covering_snapshot``,
``_record_snapshot``, and the surrounding error-handling fall-throughs become
reachable without a live database.

Each test asserts on the recorded SQL plus the public outcome
(``SnapshotMeta`` returned, snapshot inserted, etc.) so the contract
between the cache and the index table stays exercised. The mocked
connection is a context-manager-friendly stand-in for psycopg's
``connection.cursor()`` shape and records every executed statement for
assertion.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

import pytest

import shared.postgres.client as client_mod
from investment_team.market_data_cache.store import (
    MarketDataCache,
    SnapshotMeta,
    _row_to_meta,
)


class _FakeCursor:
    def __init__(self, rows: Optional[List[Any]] = None, *, raise_on_execute: bool = False):
        self._rows = list(rows or [])
        self._raise = raise_on_execute
        self.executed: List[tuple] = []
        self.rowcount = 0

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc) -> None:
        return None

    def execute(self, sql: str, params: Optional[tuple] = None) -> None:
        if self._raise:
            raise RuntimeError("fixture-placeholder-not-a-secret: simulated db failure")
        self.executed.append((sql, params))
        self.rowcount = 1

    def fetchone(self) -> Optional[Any]:
        return self._rows.pop(0) if self._rows else None


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> "_FakeConn":
        return self

    def __exit__(self, *exc) -> None:
        return None

    def cursor(self, row_factory: Any = None) -> _FakeCursor:  # noqa: ARG002
        return self._cursor


def _patch_pg_cursor(monkeypatch: pytest.MonkeyPatch, cursor: _FakeCursor) -> None:
    """Route ``pg_cursor`` (used by ``PostgresHelperMixin``) at a fake cursor.

    Sets ``POSTGRES_HOST`` (only if unset, to avoid clobbering a real value)
    so ``pg_cursor``'s ``is_postgres_enabled()`` guard falls through, and
    patches ``shared.postgres.client.get_conn`` — the module ``pg_cursor``
    itself resolves ``get_conn`` from — to yield a ``_FakeConn`` wrapping
    ``cursor``.
    """
    if not client_mod.is_postgres_enabled():
        monkeypatch.setenv("POSTGRES_HOST", "fixture-placeholder-not-a-secret")

    @contextmanager
    def _fake_get_conn(database: Optional[str] = None):  # noqa: ARG001
        with _FakeConn(cursor) as conn:
            yield conn

    monkeypatch.setattr(client_mod, "get_conn", _fake_get_conn)


@pytest.fixture
def cache(tmp_path: Path) -> MarketDataCache:
    return MarketDataCache(cache_root=tmp_path)


def _meta(**overrides: Any) -> SnapshotMeta:
    base = dict(
        symbol="AAA",
        asset_class="stocks",
        frequency="1d",
        provider="yahoo",
        fetch_ts=datetime(2024, 1, 5, 12, 0, tzinfo=timezone.utc),
        start_date="2024-01-01",
        end_date="2024-01-05",
        row_count=5,
        sha256="0" * 64,
        parquet_path="/tmp/aaa.parquet",
        schema_version=1,
    )
    base.update(overrides)
    return SnapshotMeta(**base)


# ---------------------------------------------------------------------------
# _row_to_meta — exercises the string/date branch conversions for index rows
# ---------------------------------------------------------------------------


def test_row_to_meta_parses_string_timestamps_and_date_dates() -> None:
    """Pre: ``fetch_ts`` arrives as ISO string and ``start_date``/``end_date``
    as :class:`datetime.date` (typical psycopg behaviour). Post:
    :func:`_row_to_meta` returns a fully-typed :class:`SnapshotMeta`.
    """
    row = {
        "symbol": "AAA",
        "asset_class": "stocks",
        "frequency": "1d",
        "provider": "yahoo",
        "fetch_ts": "2024-01-05T12:00:00Z",
        "start_date": date(2024, 1, 1),
        "end_date": date(2024, 1, 5),
        "row_count": 5,
        "sha256": "f" * 64,
        "parquet_path": "/tmp/x.parquet",
        "schema_version": 2,
    }
    meta = _row_to_meta(row)
    assert meta.symbol == "AAA"
    assert meta.fetch_ts.tzinfo is timezone.utc
    assert meta.start_date == "2024-01-01"
    assert meta.end_date == "2024-01-05"
    assert meta.schema_version == 2


def test_row_to_meta_handles_naive_datetime() -> None:
    """A naive ``fetch_ts`` (no tzinfo) gets coerced to UTC."""
    row = {
        "symbol": "BBB",
        "asset_class": "stocks",
        "frequency": "1d",
        "provider": "yahoo",
        "fetch_ts": datetime(2024, 1, 5, 12, 0),  # naive
        "start_date": "2024-01-01",
        "end_date": "2024-01-05",
        "row_count": 5,
        "sha256": "0" * 64,
        "parquet_path": "/tmp/y.parquet",
        "schema_version": 1,
    }
    meta = _row_to_meta(row)
    assert meta.fetch_ts.tzinfo is timezone.utc


# ---------------------------------------------------------------------------
# _find_covering_snapshot — Postgres hit + miss + failure-fallback paths
# ---------------------------------------------------------------------------


def test_find_covering_snapshot_postgres_hit_returns_row(
    cache: MarketDataCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pre: ``is_postgres_enabled()`` true, conn returns a covering row.
    Post: lookup returns a parsed ``SnapshotMeta`` and the in-memory
    fallback path is never consulted.
    """
    row = {
        "symbol": "AAA",
        "asset_class": "stocks",
        "frequency": "1d",
        "provider": "yahoo",
        "fetch_ts": datetime(2024, 1, 5, 12, 0, tzinfo=timezone.utc),
        "start_date": "2024-01-01",
        "end_date": "2024-01-05",
        "row_count": 5,
        "sha256": "0" * 64,
        "parquet_path": "/tmp/x.parquet",
        "schema_version": 1,
    }
    cursor = _FakeCursor(rows=[row])
    _patch_pg_cursor(monkeypatch, cursor)

    out = cache._find_covering_snapshot(
        symbol="AAA",
        asset_class="stocks",
        frequency="1d",
        start="2024-01-02",
        end="2024-01-04",
        as_of_dt=datetime(2024, 2, 1, tzinfo=timezone.utc),
    )
    assert out is not None
    assert out.symbol == "AAA"
    # SELECT was issued
    assert cursor.executed and "investment_market_data_snapshots" in cursor.executed[0][0]


def test_find_covering_snapshot_postgres_miss_returns_none(
    cache: MarketDataCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pre: ``is_postgres_enabled()`` true, conn returns no row.
    Post: lookup returns None (no in-memory consultation needed)."""
    cursor = _FakeCursor(rows=[])
    _patch_pg_cursor(monkeypatch, cursor)

    out = cache._find_covering_snapshot(
        symbol="ZZZ",
        asset_class="stocks",
        frequency="1d",
        start="2024-01-02",
        end="2024-01-04",
        as_of_dt=datetime(2024, 2, 1, tzinfo=timezone.utc),
    )
    assert out is None


def test_find_covering_snapshot_postgres_error_falls_back_to_memory(
    cache: MarketDataCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pre: ``is_postgres_enabled()`` true but the cursor raises.
    Post: the in-memory index is consulted instead and the existing
    snapshot is found.
    """
    meta = _meta()
    cache._memory_index.append(meta)

    cursor = _FakeCursor(rows=[], raise_on_execute=True)
    _patch_pg_cursor(monkeypatch, cursor)

    out = cache._find_covering_snapshot(
        symbol="AAA",
        asset_class="stocks",
        frequency="1d",
        start="2024-01-02",
        end="2024-01-04",
        as_of_dt=datetime(2024, 2, 1, tzinfo=timezone.utc),
    )
    assert out is not None
    assert out.symbol == "AAA"


# ---------------------------------------------------------------------------
# _record_snapshot — Postgres insert + failure-fallback paths
# ---------------------------------------------------------------------------


def test_record_snapshot_postgres_insert(
    cache: MarketDataCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pre: Postgres enabled and the insert succeeds.
    Post: nothing is recorded in the in-memory fallback; the insert SQL
    matches the documented column order.
    """
    cursor = _FakeCursor()
    _patch_pg_cursor(monkeypatch, cursor)

    meta = _meta()
    cache._record_snapshot(meta)

    assert cache._memory_index == []
    assert cursor.executed
    sql, params = cursor.executed[0]
    assert "INSERT INTO investment_market_data_snapshots" in sql
    # 13 placeholders, 13 values — the realised range and the requested one
    # are separate columns.
    assert sql.count("%s") == 13
    assert params == (
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
    )


def test_record_snapshot_postgres_failure_falls_back_to_memory(
    cache: MarketDataCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pre: Postgres enabled but the insert raises.
    Post: the meta is still preserved in the in-memory index so the
    process retains a usable record.
    """
    cursor = _FakeCursor(raise_on_execute=True)
    _patch_pg_cursor(monkeypatch, cursor)

    meta = _meta(symbol="ERR")
    cache._record_snapshot(meta)

    assert any(m.symbol == "ERR" for m in cache._memory_index)


# ---------------------------------------------------------------------------
# _parse_as_of edge cases (covers parsing fallbacks)
# ---------------------------------------------------------------------------


def test_parse_as_of_handles_iso_datetime_with_z() -> None:
    """ISO with trailing ``Z`` is converted to UTC tz."""
    from investment_team.market_data_cache.store import _parse_as_of

    dt = _parse_as_of("2024-01-05T12:00:00Z")
    assert dt.tzinfo is timezone.utc


def test_parse_as_of_handles_bare_date() -> None:
    """Bare ``YYYY-MM-DD`` is anchored to end-of-day UTC."""
    from investment_team.market_data_cache.store import _parse_as_of

    dt = _parse_as_of("2024-01-05")
    assert dt.year == 2024 and dt.hour == 23 and dt.tzinfo is timezone.utc


def test_parse_as_of_returns_now_on_bad_input() -> None:
    """Invalid input falls back to ``_now_utc``."""
    from investment_team.market_data_cache.store import _parse_as_of

    dt = _parse_as_of("not-a-date")
    assert dt.tzinfo is timezone.utc


def test_parse_as_of_returns_now_on_empty() -> None:
    """Empty / None returns ``_now_utc``."""
    from investment_team.market_data_cache.store import _parse_as_of

    assert _parse_as_of(None).tzinfo is timezone.utc
    assert _parse_as_of("").tzinfo is timezone.utc


# ---------------------------------------------------------------------------
# _default_workers env honoring
# ---------------------------------------------------------------------------


def test_default_workers_uses_env_when_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    from investment_team.market_data_cache.store import _default_workers

    monkeypatch.setenv("MARKET_DATA_FETCH_WORKERS", "7")
    assert _default_workers(50) == 7


def test_default_workers_ignores_invalid_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from investment_team.market_data_cache.store import _default_workers

    monkeypatch.setenv("MARKET_DATA_FETCH_WORKERS", "not-a-number")
    assert _default_workers(50) == 16


def test_default_workers_ignores_nonpositive_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from investment_team.market_data_cache.store import _default_workers

    monkeypatch.setenv("MARKET_DATA_FETCH_WORKERS", "0")
    assert _default_workers(50) == 16
    monkeypatch.setenv("MARKET_DATA_FETCH_WORKERS", "-3")
    assert _default_workers(50) == 16


def test_default_workers_no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from investment_team.market_data_cache.store import _default_workers

    monkeypatch.delenv("MARKET_DATA_FETCH_WORKERS", raising=False)
    assert _default_workers(3) == 3
    assert _default_workers(50) == 16


# ---------------------------------------------------------------------------
# Requested-vs-realised coverage columns on the Postgres branch
# ---------------------------------------------------------------------------


def test_find_covering_snapshot_postgres_predicate_spans_both_ranges(
    cache: MarketDataCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pre: Postgres enabled. Post: the SELECT bounds the lookup on the union
    of the realised and requested ranges (``LEAST``/``GREATEST`` over the
    ``COALESCE``-folded columns), so a legacy row with NULL ``requested_*``
    matches exactly the window it matched before the columns existed.
    """
    cursor = _FakeCursor(rows=[])
    _patch_pg_cursor(monkeypatch, cursor)

    cache._find_covering_snapshot(
        symbol="AAA",
        asset_class="stocks",
        frequency="1d",
        start="2024-01-02",
        end="2024-01-04",
        as_of_dt=datetime(2024, 2, 1, tzinfo=timezone.utc),
    )
    sql, params = cursor.executed[0]
    normalized = " ".join(sql.split())
    assert "requested_start_date, requested_end_date" in normalized
    assert "LEAST(start_date, COALESCE(requested_start_date, start_date)) <= %s" in normalized
    assert "GREATEST(end_date, COALESCE(requested_end_date, end_date)) >= %s" in normalized
    assert params[-2:] == ("2024-01-02", "2024-01-04")


def test_row_to_meta_reads_requested_columns() -> None:
    """A row carrying the requested-window columns round-trips both ranges."""
    row = {
        "symbol": "AAA",
        "asset_class": "stocks",
        "frequency": "1d",
        "provider": "yahoo",
        "fetch_ts": datetime(2024, 1, 5, 12, 0, tzinfo=timezone.utc),
        "start_date": date(2024, 1, 3),
        "end_date": date(2024, 1, 5),
        "requested_start_date": date(2024, 1, 1),
        "requested_end_date": date(2024, 1, 5),
        "row_count": 3,
        "sha256": "0" * 64,
        "parquet_path": "/tmp/x.parquet",
        "schema_version": 1,
    }
    meta = _row_to_meta(row)
    assert (meta.start_date, meta.end_date) == ("2024-01-03", "2024-01-05")
    assert (meta.requested_start_date, meta.requested_end_date) == ("2024-01-01", "2024-01-05")
    # Realised bounds are the truth about the bars; the request is provenance.
    assert not meta.covers("2024-01-01", "2024-01-05")
    assert meta.is_authoritative_for("2024-01-01", "2024-01-05")


def test_row_to_meta_legacy_row_without_requested_columns() -> None:
    """A pre-migration row (no ``requested_*`` keys) falls back to the realised
    pair, preserving the lookup reach it had before the split.
    """
    row = {
        "symbol": "AAA",
        "asset_class": "stocks",
        "frequency": "1d",
        "provider": "yahoo",
        "fetch_ts": datetime(2024, 1, 5, 12, 0, tzinfo=timezone.utc),
        "start_date": "2024-01-01",
        "end_date": "2024-01-05",
        "row_count": 5,
        "sha256": "0" * 64,
        "parquet_path": "/tmp/x.parquet",
        "schema_version": 1,
    }
    meta = _row_to_meta(row)
    assert meta.requested_start_date is None
    assert meta.requested_end_date is None
    assert (meta.requested_start, meta.requested_end) == ("2024-01-01", "2024-01-05")
    assert meta.is_authoritative_for("2024-01-01", "2024-01-05")


def test_row_to_meta_null_requested_columns_stay_none() -> None:
    """Explicit SQL NULLs (post-migration legacy row) behave like absent keys."""
    row = {
        "symbol": "AAA",
        "asset_class": "stocks",
        "frequency": "1d",
        "provider": "yahoo",
        "fetch_ts": datetime(2024, 1, 5, 12, 0, tzinfo=timezone.utc),
        "start_date": "2024-01-01",
        "end_date": "2024-01-05",
        "requested_start_date": None,
        "requested_end_date": None,
        "row_count": 5,
        "sha256": "0" * 64,
        "parquet_path": "/tmp/x.parquet",
        "schema_version": 1,
    }
    meta = _row_to_meta(row)
    assert meta.requested_start_date is None
    assert meta.requested_end_date is None

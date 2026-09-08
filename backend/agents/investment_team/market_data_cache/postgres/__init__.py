"""Postgres schema for the investment team's market-data cache (issue #376).

Pure data — importing this module has no side effects.  DDL is applied
when ``register_team_schemas(SCHEMA)`` is called from a FastAPI lifespan.

Single table, ``investment_market_data_snapshots``, indexes the
content-addressed Parquet snapshots written under
``${AGENT_CACHE}/investment_team/market_data/...``.  Each row is a
``(symbol, asset_class, frequency, provider, fetch_ts)`` snapshot whose
range is ``[start_date, end_date]`` and whose canonical SHA256 is
``sha256``.  The ``parquet_path`` column stores the absolute path to the
on-disk artifact; the cache layer treats a missing file as a stale row
and re-fetches.

``[start_date, end_date]`` is the range the snapshot's bars actually span;
``[requested_start_date, requested_end_date]`` is the range the fetch asked
for.  They diverge when a provider serves a short series, and recording only
the latter (as this table originally did) made truncation indistinguishable
from full coverage on every subsequent read.
"""

from __future__ import annotations

from shared.postgres import TeamSchema

SCHEMA = TeamSchema(
    team="investment_market_data",
    database=None,
    statements=[
        """CREATE TABLE IF NOT EXISTS investment_market_data_snapshots (
            id              BIGSERIAL PRIMARY KEY,
            symbol          TEXT NOT NULL,
            asset_class     TEXT NOT NULL,
            frequency       TEXT NOT NULL,
            provider        TEXT NOT NULL,
            fetch_ts        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            start_date      DATE NOT NULL,
            end_date        DATE NOT NULL,
            row_count       INTEGER NOT NULL,
            sha256          TEXT NOT NULL,
            schema_version  INTEGER NOT NULL DEFAULT 1,
            parquet_path    TEXT NOT NULL
        )""",
        # ``start_date``/``end_date`` are the *realised* bounds — the first
        # and last bar in the parquet file. These two record the window the
        # fetch asked the provider for, which differs whenever the provider
        # served a short series. Keeping both lets the cache-hit predicate
        # span everything the snapshot is authoritative about (a date the
        # provider was asked for and had no data for needs no refetch) while
        # ``start_date``/``end_date`` stay honest about what the file holds.
        # Nullable, and idempotent: rows written before the split have NULL
        # here and their ``start_date``/``end_date`` still hold the requested
        # window, which ``COALESCE`` in the lookup folds onto the same
        # predicate they matched before.
        """ALTER TABLE investment_market_data_snapshots
            ADD COLUMN IF NOT EXISTS requested_start_date DATE""",
        """ALTER TABLE investment_market_data_snapshots
            ADD COLUMN IF NOT EXISTS requested_end_date DATE""",
        """CREATE INDEX IF NOT EXISTS idx_imds_lookup
            ON investment_market_data_snapshots
            (symbol, asset_class, frequency, fetch_ts DESC)""",
        """CREATE INDEX IF NOT EXISTS idx_imds_sha
            ON investment_market_data_snapshots (sha256)""",
    ],
    table_names=["investment_market_data_snapshots"],
)

__all__ = ["SCHEMA"]

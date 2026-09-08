"""Shared recording fake Postgres cursor for ``pg_cursor``-shaped unit tests.

Two teams independently hand-rolled a near-identical recording cursor —
records every ``execute``/``executemany`` call, can be told to raise, and
serves queued ``fetchall``/``fetchone`` rows — because ``shared.postgres.
fake.FakeCursor`` is a different kind of fake (a SQL-dispatch-table double
aimed at store round-trips, patching ``get_conn``) that doesn't cover this
"record and assert" shape: no ``executemany``, no raise-injection, and no
cursor-or-``None`` contract matching ``shared.postgres.pg_cursor``'s own
signature. This module converges both teams' copies onto one class.

Why a separate top-level module rather than living in ``shared/postgres/
fake.py`` alongside the dispatch-table double? Some teams (e.g.
``software_engineering_team``) override pytest's rootdir via their own
``pyproject.toml`` and have their own local ``shared/`` package, which
shadows a dotted ``shared.postgres.*`` import under that rootdir. By
shipping this fake as an importable module on the standard agents
``pythonpath`` -- mirroring ``job_service_client_fake.py``'s and
``llm_client_fakes.py``'s established pattern -- any team's tests can pull
it in with a single one-liner::

    from pg_cursor_fake import FakeCursor, install_fake_cursor
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Optional, Sequence


class FakeCursorContractViolation(BaseException):
    """Raised when a statement/row pair would be rejected by real psycopg.

    Deliberately derives from ``BaseException``, not ``Exception``: Postgres
    write paths commonly wrap their cursor work in ``except Exception`` (log
    and continue), so an ``Exception`` raised by this fake would be swallowed
    by the code under test and resurface as an opaque ``IndexError`` on
    ``cursor.executed[0]`` instead of a legible contract-violation message.
    Deriving from ``BaseException`` lets the violation propagate to pytest
    with its own message intact.
    """


class FakeCursor:
    """Records every execute/executemany call and serves queued fetchall/fetchone rows.

    No live Postgres involved. Mirrors psycopg's arity check: a statement
    whose ``%s`` count does not match the row width is a hard error, not a
    silently-recorded call. Without this the fake would happily accept a row
    that real psycopg rejects, and since most write paths swallow exceptions
    (log, no raise) the drift would surface only as silently-dropped rows in
    production.

    A single fake serves both write-path tests (``execute``/``executemany``
    recording, optional ``raise_on_execute``) and read-path tests
    (``fetchall``/``fetchone`` over rows queued at construction) — any store
    built on ``with pg_cursor(...) as cur:`` goes through the same shape, so
    one fake covers all of it.

    Invariants:
        ``self.executed`` only grows, via ``execute``/``executemany`` — never
        mutated any other way. ``self._rows`` is never mutated after
        construction; ``fetchall``/``fetchone`` always return copies, so a
        caller mutating a returned row or list can never corrupt what a
        later fetch on the same cursor returns.
    """

    def __init__(
        self, *, raise_on_execute: bool = False, rows: Optional[Sequence[Any]] = None
    ) -> None:
        """Construct a recording cursor, optionally pre-loaded with result rows.

        Preconditions:
            ``rows``, if given, is a sequence of dict-like rows — the shape
            ``dict_rows=True`` callers expect back from ``fetchall``.
        Postconditions:
            ``self.executed`` is an empty list. ``self._raise`` is
            ``raise_on_execute`` — when true, every subsequent ``execute``/
            ``executemany`` call raises ``RuntimeError`` instead of recording.
            ``self._rows`` is ``list(rows)`` if given, else ``[]`` — the
            values ``fetchall``/``fetchone`` serve; queuing no rows is the
            "empty result set" case, not a distinct code path.
        """
        self.executed: list[tuple] = []
        self._raise = raise_on_execute
        self._rows: list[Any] = list(rows) if rows is not None else []

    @staticmethod
    def _check_arity(sql: str, params, expected: int) -> None:
        """Reject a ``params``/row whose length does not match ``sql``'s own ``%s`` count.

        Preconditions:
            ``expected`` is ``sql.count("%s")``, computed once by the caller —
            passed in rather than recomputed here so a caller iterating many
            rows against the same ``sql`` (``executemany``) does the
            ``str.count`` scan once.
        Postconditions:
            Returns ``None`` when ``len(params or ())`` equals ``expected``.
        Raises:
            ``FakeCursorContractViolation`` — deliberately a ``BaseException``,
            not an ``Exception`` — when the lengths differ, naming both counts.
        """
        actual = len(params or ())
        if expected != actual:
            raise FakeCursorContractViolation(f"SQL expects {expected} params, row has {actual}")

    def execute(self, sql: str, params=None) -> None:
        """Record one ``(sql, params)`` call, or raise if ``raise_on_execute`` is set.

        Preconditions:
            ``params`` is ``None`` or a sequence whose length matches ``sql``'s
            ``%s`` placeholder count.
        Postconditions:
            When not configured to raise, appends ``(sql, params)`` to
            ``self.executed`` and returns ``None``.
        Raises:
            ``RuntimeError`` when ``raise_on_execute`` was set at construction,
            before any arity check or recording. ``FakeCursorContractViolation``
            when ``params``'s length does not match ``sql``'s placeholder count.
        """
        if self._raise:
            raise RuntimeError("boom")
        self._check_arity(sql, params, sql.count("%s"))
        self.executed.append((sql, params))

    def executemany(self, sql: str, seq) -> None:
        """Record one ``(sql, rows)`` call for a batch, or raise if ``raise_on_execute`` is set.

        Preconditions:
            Every row in ``seq`` is a sequence whose length matches ``sql``'s
            ``%s`` placeholder count.
        Postconditions:
            When not configured to raise, appends ``(sql, list(seq))`` to
            ``self.executed`` and returns ``None``. ``sql.count("%s")`` is
            computed once and reused across every row in ``seq``, since it is
            invariant for a single call.
        Raises:
            ``RuntimeError`` when ``raise_on_execute`` was set at construction,
            before any row is checked or recorded. ``FakeCursorContractViolation``
            on the first row whose length does not match ``sql``'s placeholder
            count.
        """
        if self._raise:
            raise RuntimeError("boom")
        expected = sql.count("%s")
        rows = list(seq)
        for row in rows:
            self._check_arity(sql, row, expected)
        self.executed.append((sql, rows))

    @staticmethod
    def _copy_row(row: Any) -> Any:
        """Return a shallow copy of a queued row, or ``row`` unchanged if it isn't a dict.

        Preconditions:
            None.
        Postconditions:
            Returns ``dict(row)`` when ``row`` is a dict (every
            ``dict_rows=True`` caller's shape); returns ``row`` itself
            otherwise (e.g. a tuple, already immutable). Shared by
            ``fetchall``/``fetchone`` so a caller mutating a returned row can
            never corrupt ``self._rows`` or a later fetch on the same cursor —
            the two methods stay symmetric rather than one copying and the
            other handing out a live reference.
        """
        return dict(row) if isinstance(row, dict) else row

    def fetchall(self) -> list[Any]:
        """Return the rows queued at construction.

        Preconditions:
            None.
        Postconditions:
            Returns a fresh list of :func:`_copy_row` copies — mutating an
            entry in the returned list, or the list itself, cannot corrupt
            ``self._rows`` or what a later ``fetchall``/``fetchone`` call on
            the same cursor would return.
        """
        return [self._copy_row(row) for row in self._rows]

    def fetchone(self) -> Optional[Any]:
        """Return a copy of the first queued row, or ``None`` when none were queued.

        Preconditions:
            None.
        Postconditions:
            Returns :func:`_copy_row` of ``self._rows[0]`` if ``self._rows``
            is non-empty, else ``None`` — mutating the returned row cannot
            corrupt ``self._rows`` or what a later ``fetchall``/``fetchone``
            call would return, matching ``fetchall``'s own guarantee.
        """
        return self._copy_row(self._rows[0]) if self._rows else None


def install_fake_cursor(
    monkeypatch: Any,
    module: Any,
    *,
    raise_on_execute: bool = False,
    rows: Optional[Sequence[Any]] = None,
    disabled: bool = False,
) -> Optional[FakeCursor]:
    """Patch ``module.pg_cursor`` to yield a fresh :class:`FakeCursor`, or ``None``.

    The one installation routine for substituting ``shared.postgres.
    pg_cursor`` — write-path tests read ``cursor.executed`` afterward,
    read-path tests pass ``rows`` up front for ``cursor.fetchall()``/
    ``fetchone()`` to serve back, and ``disabled=True`` covers the
    Postgres-unconfigured path the real ``pg_cursor`` takes (yielding
    ``None`` rather than a cursor) without a test hand-rolling its own
    ``None``-yielding context manager.

    Preconditions:
        ``monkeypatch`` is the pytest fixture — the substitution it installs
        is undone automatically at test teardown. ``module`` is the module
        object whose ``pg_cursor`` name should be patched (e.g.
        ``trace_store``) — it must expose a module-level ``pg_cursor``
        imported the way the real ``shared.postgres.pg_cursor`` is.
        ``disabled`` is not combined with ``raise_on_execute``/``rows``
        (asserted) — there is no cursor for them to configure when
        ``disabled=True``.
    Postconditions:
        ``module.pg_cursor`` is patched to a context manager matching the
        real ``pg_cursor(*, dict_rows: bool = False, database=None)``
        signature. When ``disabled``, it yields ``None`` and this function
        returns ``None``. Otherwise it yields a fresh :class:`FakeCursor`
        constructed with ``raise_on_execute``/``rows``, and this function
        returns that cursor. Each call installs an independent patch/cursor;
        they never share call history.
    """
    assert not (disabled and (raise_on_execute or rows is not None)), (
        "disabled=True yields None; raise_on_execute/rows have nothing to configure"
    )
    cursor = None if disabled else FakeCursor(raise_on_execute=raise_on_execute, rows=rows)

    @contextmanager
    def _pg_cursor(*, dict_rows: bool = False, database=None):
        """Stand-in for ``shared.postgres.pg_cursor``; yields the fake cursor or ``None``.

        Preconditions:
            Signature must track the real ``pg_cursor`` — a keyword-only
            ``dict_rows`` and ``database``, both with matching defaults — so
            this fake stays a valid substitute if the real one's callers
            change how they invoke it.
        Postconditions:
            Yields ``cursor`` unconditionally; both parameters are accepted
            but unused, since the fake never distinguishes row-factory mode.
        """
        yield cursor

    monkeypatch.setattr(module, "pg_cursor", _pg_cursor)
    return cursor


__all__ = ["FakeCursor", "FakeCursorContractViolation", "install_fake_cursor"]

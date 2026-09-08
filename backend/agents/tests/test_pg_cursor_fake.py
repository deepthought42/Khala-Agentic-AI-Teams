"""Unit tests for pg_cursor_fake (the shared recording fake Postgres cursor).

Direct coverage for the converged FakeCursor/install_fake_cursor contract,
independent of what either consuming team's suite happens to exercise —
in particular the arity-violation raise branch, which neither consumer
(llm_service/tests/test_usage_store.py, software_engineering_team/tests/
test_observability_stores.py) ever triggers, since every real call site in
both teams' production code builds SQL/params in matching arity by
construction.
"""

from __future__ import annotations

import pytest

from pg_cursor_fake import FakeCursor, FakeCursorContractViolation, install_fake_cursor


class _Target:
    """Stand-in for a store module exposing a module-level ``pg_cursor`` name."""

    pg_cursor = None


def test_execute_records_sql_and_params() -> None:
    cursor = FakeCursor()
    cursor.execute("SELECT 1 WHERE a = %s", (1,))
    assert cursor.executed == [("SELECT 1 WHERE a = %s", (1,))]


def test_executemany_records_sql_and_rows() -> None:
    cursor = FakeCursor()
    cursor.executemany("INSERT INTO t (a) VALUES (%s)", [(1,), (2,)])
    assert cursor.executed == [("INSERT INTO t (a) VALUES (%s)", [(1,), (2,)])]


def test_execute_with_no_params_and_no_placeholders_is_valid() -> None:
    cursor = FakeCursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS t (id INT)")
    assert cursor.executed == [("CREATE TABLE IF NOT EXISTS t (id INT)", None)]


def test_execute_raises_before_recording_when_configured() -> None:
    cursor = FakeCursor(raise_on_execute=True)
    with pytest.raises(RuntimeError, match="raise_on_execute is configured"):
        cursor.execute("SELECT 1")
    assert cursor.executed == []


def test_executemany_raises_before_recording_when_configured() -> None:
    cursor = FakeCursor(raise_on_execute=True)
    with pytest.raises(RuntimeError, match="raise_on_execute is configured"):
        cursor.executemany("INSERT INTO t (a) VALUES (%s)", [(1,)])
    assert cursor.executed == []


def test_execute_arity_mismatch_raises_contract_violation() -> None:
    cursor = FakeCursor()
    with pytest.raises(FakeCursorContractViolation, match="expects 2 params, row has 1"):
        cursor.execute("UPDATE t SET a = %s WHERE b = %s", (1,))
    assert cursor.executed == []  # rejected before recording


def test_executemany_arity_mismatch_raises_on_first_bad_row() -> None:
    cursor = FakeCursor()
    with pytest.raises(FakeCursorContractViolation, match="expects 1 params, row has 2"):
        cursor.executemany("INSERT INTO t (a) VALUES (%s)", [(1,), (2, 3)])
    assert cursor.executed == []


def test_contract_violation_is_a_base_exception_not_an_exception() -> None:
    """The whole point of the BaseException choice: a bare `except Exception:`
    guard, as every write path under test uses, must not swallow this."""
    assert issubclass(FakeCursorContractViolation, BaseException)
    assert not issubclass(FakeCursorContractViolation, Exception)


def test_fetchall_returns_empty_list_when_no_rows_queued() -> None:
    assert FakeCursor().fetchall() == []


def test_fetchone_returns_none_when_no_rows_queued() -> None:
    assert FakeCursor().fetchone() is None


def test_fetchall_serves_queued_rows_every_call() -> None:
    cursor = FakeCursor(rows=[{"a": 1}, {"a": 2}])
    assert cursor.fetchall() == [{"a": 1}, {"a": 2}]
    assert cursor.fetchall() == [{"a": 1}, {"a": 2}]  # idempotent, not a queue


def test_fetchone_returns_first_queued_row_every_call() -> None:
    cursor = FakeCursor(rows=[{"a": 1}, {"a": 2}])
    assert cursor.fetchone() == {"a": 1}
    assert cursor.fetchone() == {"a": 1}  # idempotent, not a queue


def test_fetchall_returns_defensive_copies() -> None:
    cursor = FakeCursor(rows=[{"a": 1}])
    got = cursor.fetchall()
    got[0]["a"] = 999
    assert cursor.fetchall() == [{"a": 1}]  # mutation didn't corrupt the source


def test_fetchone_returns_defensive_copy() -> None:
    cursor = FakeCursor(rows=[{"a": 1}])
    got = cursor.fetchone()
    got["a"] = 999
    assert cursor.fetchone() == {"a": 1}


def test_fetchall_passes_through_non_dict_rows_unchanged() -> None:
    cursor = FakeCursor(rows=[(1, 2), (3, 4)])
    assert cursor.fetchall() == [(1, 2), (3, 4)]


def test_queue_rows_replaces_served_rows() -> None:
    cursor = FakeCursor(rows=[{"a": 1}])
    cursor.queue_rows([{"a": 2}, {"a": 3}])
    assert cursor.fetchall() == [{"a": 2}, {"a": 3}]
    assert cursor.fetchone() == {"a": 2}


def test_queue_rows_does_not_touch_executed_or_raise() -> None:
    cursor = FakeCursor()
    cursor.execute("SELECT 1")
    cursor.queue_rows([{"a": 1}])
    assert cursor.executed == [("SELECT 1", None)]
    assert cursor._raise is False


def test_install_fake_cursor_patches_pg_cursor_to_yield_the_cursor(monkeypatch) -> None:
    cursor = install_fake_cursor(monkeypatch, _Target, rows=[{"a": 1}])
    assert isinstance(cursor, FakeCursor)
    with _Target.pg_cursor() as cur:
        assert cur is cursor
        assert cur.fetchall() == [{"a": 1}]


def test_install_fake_cursor_forwards_raise_on_execute(monkeypatch) -> None:
    cursor = install_fake_cursor(monkeypatch, _Target, raise_on_execute=True)
    with pytest.raises(RuntimeError, match="raise_on_execute is configured"):
        cursor.execute("SELECT 1")


def test_install_fake_cursor_disabled_yields_none_and_returns_none(monkeypatch) -> None:
    result = install_fake_cursor(monkeypatch, _Target, disabled=True)
    assert result is None
    with _Target.pg_cursor() as cur:
        assert cur is None


def test_install_fake_cursor_disabled_rejects_raise_on_execute(monkeypatch) -> None:
    with pytest.raises(AssertionError):
        install_fake_cursor(monkeypatch, _Target, disabled=True, raise_on_execute=True)


def test_install_fake_cursor_disabled_rejects_rows(monkeypatch) -> None:
    with pytest.raises(AssertionError):
        install_fake_cursor(monkeypatch, _Target, disabled=True, rows=[{"a": 1}])


def test_install_fake_cursor_patched_signature_accepts_dict_rows_and_database(monkeypatch) -> None:
    install_fake_cursor(monkeypatch, _Target)
    with _Target.pg_cursor(dict_rows=True, database="other") as cur:
        assert isinstance(cur, FakeCursor)


def test_install_fake_cursor_independent_across_calls(monkeypatch) -> None:
    first = install_fake_cursor(monkeypatch, _Target, rows=[{"a": 1}])
    second = install_fake_cursor(monkeypatch, _Target, rows=[{"a": 2}])
    assert first is not second
    with _Target.pg_cursor() as cur:
        assert cur is second

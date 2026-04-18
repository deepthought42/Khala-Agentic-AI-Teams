"""Intake / profile agent: validates and completes client profile from structured input.

The ``IntakeProfileAgent`` class depends on ``strands``, which is not
installed in every environment that imports this team (e.g. unit-test
runs that only exercise the pure-logic ``structural`` fallback). Import
it lazily via PEP 562 ``__getattr__`` so test code can import
``structural`` without dragging strands in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - type-checker hint only
    from .agent import IntakeProfileAgent  # noqa: F401

__all__ = ["IntakeProfileAgent"]


def __getattr__(name: str) -> Any:
    if name == "IntakeProfileAgent":
        from .agent import IntakeProfileAgent as _IntakeProfileAgent

        globals()[name] = _IntakeProfileAgent
        return _IntakeProfileAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

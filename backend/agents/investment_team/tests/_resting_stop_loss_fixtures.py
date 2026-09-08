"""Shared rule factory for the resting stop-loss suites
(test_resting_stop_loss_attachment.py, test_stop_loss_mechanism_coexistence.py).

Both suites must exercise the SAME ``StopLossRule`` shape — that is the whole
point of having a coexistence suite alongside the attachment one — so the shape
lives here rather than being copied into each file with a note asking future
maintainers to keep them in step by hand. Nothing enforced that note; a new
required field on ``StopLossRule`` would have desynchronised the two silently.

The ``pct`` default stays per-suite, passed at the call site, because each suite
picks a stop distance that suits its own price fixtures.

Not a test module — the leading underscore keeps pytest from collecting it.
"""

from __future__ import annotations

from investment_team.strategy_lab.spec_dsl import StopLossRule


def limit_stop_rule(pct: float, limit_offset_pct: float = 0.01) -> StopLossRule:
    """Build the entry-anchored, limit-style stop both suites migrate.

    Preconditions:
        - ``0 < pct < 1`` and ``limit_offset_pct > 0``; the DSL rejects anything
          else for this variant, and ``pct == 1.0`` is the short-safety auto-stop
          the resting migration deliberately excludes.
    Postconditions:
        - Returns a ``StopLossRule`` with ``basis="entry_price"`` and
          ``style="limit"`` — the exact shape ``_is_resting_stop_loss`` admits.
    """
    return StopLossRule(
        pct=pct, basis="entry_price", style="limit", limit_offset_pct=limit_offset_pct
    )

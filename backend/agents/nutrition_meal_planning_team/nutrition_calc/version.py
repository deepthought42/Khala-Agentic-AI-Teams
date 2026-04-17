"""Version constant for the deterministic nutrition calculator.

SPEC-003 §4.11. Downstream consumers pin on this constant for cache
invalidation (SPEC-004 nutrition plan cache, ADR-006 trajectory
snapshots). Bump rules:

- MAJOR: equation swap or cohort-routing change. Downstream caches
  must invalidate; golden outputs rewrite.
- MINOR: DRI/AMDR table refresh, new clinical overrides, new cohort
  that does not rewrite existing cohort outputs.
- PATCH: bug fixes that do not alter outputs on valid inputs.

Golden-output tests (tests/golden/) pin outputs byte-for-byte on a
given CALCULATOR_VERSION. An intentional output change must bump the
version and rewrite the goldens in the same PR.
"""

from __future__ import annotations

CALCULATOR_VERSION = "1.0.0"

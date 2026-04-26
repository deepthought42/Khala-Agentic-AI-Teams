"""ProductOwnerAgent — ranks a product's backlog.

Flow:

1. Pull every story under ``product_id`` from the store.
2. Ask the LLM to produce *scoring inputs* (never the score itself; see
   :mod:`product_delivery.product_owner_agent.prompts`).
3. Compute WSJF or RICE scores deterministically via
   :mod:`product_delivery.scoring`.
4. Optionally persist the scores back onto each story row.
5. Return a ranked :class:`GroomResult`.

Tests inject a stub ``llm_client`` (any object with a ``complete_json``
method). In production we use ``llm_service.get_client("product_owner")``.
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any, Protocol

from product_delivery.models import (
    GroomMethod,
    GroomResult,
    RankedBacklogItem,
    Story,
)
from product_delivery.product_owner_agent.prompts import (
    SYSTEM_PROMPT,
    build_user_prompt,
)
from product_delivery.scoring import RICEInputs, WSJFInputs, rice_score, wsjf_score
from product_delivery.store import ProductDeliveryStore

logger = logging.getLogger(__name__)


def _to_float(value: Any, fallback: float) -> float:
    """Coerce an LLM-supplied value to a finite ``float`` with a typed fallback.

    Models routinely emit explicit ``null`` for fields they're unsure
    about (especially the denominator-shaped ones like ``job_size`` and
    ``effort``). ``float(None)`` raises ``TypeError`` and the outer
    handler skips the whole story — so we'd silently drop items from
    the ranking. Treat ``None`` (and missing) the same as the fallback.

    Models also occasionally emit ``"NaN"`` or ``"Infinity"`` for fields
    they refuse to commit to. ``float()`` accepts both, but non-finite
    scores break Starlette's JSON encoder downstream and corrupt
    persisted ranking data — so we treat them the same as ``None`` and
    fall back, not raise. The outer ``try`` only catches malformed
    values that genuinely can't be coerced; a finite fallback is the
    safer default for a lossy LLM input.
    """
    if value is None:
        return float(fallback)
    coerced = float(value)
    if not math.isfinite(coerced):
        return float(fallback)
    return coerced


class _LLMLike(Protocol):
    def complete_json(
        self,
        prompt: str,
        *,
        temperature: float = ...,
        system_prompt: str | None = ...,
        **kwargs: Any,
    ) -> dict[str, Any]: ...


class ProductOwnerAgent:
    """Stateless: depends on a store + an LLM client only."""

    def __init__(
        self,
        store: ProductDeliveryStore,
        llm_client: _LLMLike,
    ) -> None:
        self._store = store
        self._llm = llm_client

    def groom(
        self,
        *,
        product_id: str,
        method: GroomMethod = "wsjf",
        persist: bool = True,
    ) -> GroomResult:
        stories = self._store.list_stories_for_product(product_id)
        if not stories:
            return GroomResult(
                product_id=product_id,
                method=method,
                ranked=[],
                rationale="No stories under this product yet.",
            )

        scoring_payload = self._call_llm(method, stories)
        ranked, persist_rows = self._compute_ranked(method, stories, scoring_payload)

        if persist and persist_rows:
            self._store.bulk_update_story_scores(persist_rows)

        ranked.sort(key=lambda r: r.score, reverse=True)
        return GroomResult(
            product_id=product_id,
            method=method,
            ranked=ranked,
            rationale=f"Scored {len(ranked)} stories using {method.upper()}.",
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _call_llm(self, method: GroomMethod, stories: list[Story]) -> dict[str, Any]:
        stories_payload = json.dumps(
            [
                {
                    "id": s.id,
                    "title": s.title,
                    "user_story": s.user_story,
                    "estimate_points": s.estimate_points,
                    "status": s.status,
                }
                for s in stories
            ],
            indent=2,
        )
        prompt = build_user_prompt(method, stories_payload)
        try:
            return self._llm.complete_json(
                prompt,
                temperature=0.0,
                system_prompt=SYSTEM_PROMPT,
            )
        except Exception:
            logger.exception("ProductOwnerAgent: LLM call failed; returning unscored backlog")
            return {"items": []}

    def _compute_ranked(
        self,
        method: GroomMethod,
        stories: list[Story],
        payload: dict[str, Any],
    ) -> tuple[list[RankedBacklogItem], list[tuple[str, float | None, float | None]]]:
        by_id = {s.id: s for s in stories}
        ranked: list[RankedBacklogItem] = []
        persist_rows: list[tuple[str, float | None, float | None]] = []
        seen_ids: set[str] = set()
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            items = []

        for raw in items:
            if not isinstance(raw, dict):
                continue
            sid = raw.get("id")
            story = by_id.get(sid) if isinstance(sid, str) else None
            if story is None:
                continue
            # Models occasionally repeat the same id (truncation + retry,
            # confused JSON). Take the first occurrence and warn on the
            # rest so persisted scores stay deterministic instead of
            # depending on whichever copy lands last.
            if story.id in seen_ids:
                logger.warning(
                    "ProductOwnerAgent: duplicate story id %s in LLM payload; ignoring repeat",
                    story.id,
                )
                continue
            inputs = raw.get("inputs") if isinstance(raw.get("inputs"), dict) else {}
            rationale = str(raw.get("rationale") or "")

            wsjf_value: float | None = None
            rice_value: float | None = None
            try:
                if method == "wsjf":
                    wsjf_value = wsjf_score(
                        WSJFInputs(
                            user_business_value=_to_float(inputs.get("user_business_value"), 0.0),
                            time_criticality=_to_float(inputs.get("time_criticality"), 0.0),
                            risk_reduction_or_opportunity_enablement=_to_float(
                                inputs.get("risk_reduction_or_opportunity_enablement"), 0.0
                            ),
                            job_size=_to_float(
                                inputs.get("job_size"),
                                story.estimate_points or 1.0,
                            ),
                        )
                    )
                    score = wsjf_value
                else:
                    rice_value = rice_score(
                        RICEInputs(
                            reach=_to_float(inputs.get("reach"), 0.0),
                            impact=_to_float(inputs.get("impact"), 0.0),
                            confidence=_to_float(inputs.get("confidence"), 0.0),
                            effort=_to_float(
                                inputs.get("effort"),
                                (story.estimate_points or 4.0) / 4.0,
                            ),
                        )
                    )
                    score = rice_value
            except (TypeError, ValueError):
                logger.warning(
                    "ProductOwnerAgent: malformed inputs for story %s; skipping",
                    story.id,
                )
                continue

            seen_ids.add(story.id)
            ranked.append(
                RankedBacklogItem(
                    kind="story",
                    id=story.id,
                    title=story.title,
                    score=score,
                    wsjf_score=wsjf_value,
                    rice_score=rice_value,
                    rationale=rationale,
                )
            )
            persist_rows.append((story.id, wsjf_value, rice_value))

        # Cover any stories the LLM omitted (truncation, skipped uncertain
        # items). Surface them in the response with score=0 + a rationale
        # so downstream planning sees them and can re-groom or hand-score
        # them — silently dropping is the failure mode flagged by review.
        for story in stories:
            if story.id in seen_ids:
                continue
            logger.warning(
                "ProductOwnerAgent: story %s missing from LLM output; including with score=0",
                story.id,
            )
            ranked.append(
                RankedBacklogItem(
                    kind="story",
                    id=story.id,
                    title=story.title,
                    score=0.0,
                    wsjf_score=0.0 if method == "wsjf" else None,
                    rice_score=0.0 if method == "rice" else None,
                    rationale="LLM did not score this story; needs manual review.",
                )
            )
            # Don't persist a 0 — leave the row's existing scores intact.
            seen_ids.add(story.id)
        return ranked, persist_rows

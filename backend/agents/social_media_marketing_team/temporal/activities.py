"""Temporal activities for the social media marketing team."""

from __future__ import annotations

import logging
from typing import Any, Dict

from temporalio import activity
from temporalio.exceptions import ApplicationError

logger = logging.getLogger(__name__)


@activity.defn(name="run_social_marketing_team_job")
def run_team_job_activity(job_id: str, request_dict: Dict[str, Any]) -> None:
    """Run the social marketing team job (run or revise).

    The activity re-fetches the brand from the branding API so that brand
    context is always current, even for Temporal replays or retries.
    Brand-related failures (missing or incomplete brand) are marked
    non-retryable since retrying won't fix them.
    """
    try:
        from social_media_marketing_team.adapters.branding import (
            BrandIncompleteError,
            BrandNotFoundError,
            fetch_brand,
            validate_brand_for_social_marketing,
        )
        from social_media_marketing_team.api.main import RunMarketingTeamRequest, _run_team_job

        request = RunMarketingTeamRequest(**request_dict)
        brand_data = fetch_brand(request.client_id, request.brand_id)
        brand_ctx = validate_brand_for_social_marketing(
            brand_data, request.client_id, request.brand_id
        )
        _run_team_job(job_id, request, brand_ctx)
    except (BrandNotFoundError, BrandIncompleteError) as exc:
        logger.error("Brand unavailable for job %s: %s", job_id, exc)
        raise ApplicationError(str(exc), non_retryable=True) from exc
    except Exception:
        logger.exception("Social marketing team job activity failed for job %s", job_id)
        raise

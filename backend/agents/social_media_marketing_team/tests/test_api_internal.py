from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from shared_job_management import CentralJobManager
from social_media_marketing_team.adapters.branding import BrandContext, BrandNotFoundError
from social_media_marketing_team.api import main as api_main

_MOCK_BRAND_CTX = BrandContext(
    brand_name="Acme",
    target_audience="operators",
    voice_and_tone="direct and clear",
    brand_guidelines="Keep tone direct",
    brand_objectives="Grow followers",
    messaging_pillars=["Growth", "Clarity"],
    brand_story="Acme helps teams grow.",
    tagline="Grow with clarity",
)


def _seed_job(job_id: str, request: api_main.RunMarketingTeamRequest) -> None:
    api_main._job_manager.create_job(
        job_id,
        status="pending",
        current_stage="queued",
        progress=0,
        llm_model_name=request.llm_model_name,
        client_id=request.client_id,
        brand_id=request.brand_id,
        result=None,
        error=None,
        eta_hint="queued",
        performance_observations=[],
        last_updated_at=api_main._now(),
        revision_history=[],
        request_payload=request.model_dump(),
    )


@pytest.fixture
def temp_job_manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    manager = CentralJobManager(
        team="social_media_marketing_team_test", cache_dir=tmp_path / "cache"
    )
    monkeypatch.setattr(api_main, "_job_manager", manager)
    return manager


def test_update_job(tmp_path: Path, temp_job_manager: CentralJobManager) -> None:
    api_main._update_job("missing", status="running")
    assert temp_job_manager.get_job("missing") is not None

    req = api_main.RunMarketingTeamRequest(
        client_id="c1",
        brand_id="b1",
        llm_model_name="x",
    )
    _seed_job("job-1", req)
    old_ts = temp_job_manager.get_job("job-1")["last_heartbeat_at"]
    api_main._update_job("job-1", status="running")
    job = temp_job_manager.get_job("job-1")
    assert job["status"] == "running"
    assert job["last_heartbeat_at"] >= old_ts


def test_run_team_job_success(tmp_path: Path, temp_job_manager: CentralJobManager) -> None:
    req = api_main.RunMarketingTeamRequest(
        client_id="c1",
        brand_id="b1",
        llm_model_name="llama3.1",
        human_approved_for_testing=True,
    )
    _seed_job("ok", req)

    api_main._run_team_job("ok", req, _MOCK_BRAND_CTX)
    ok_job = temp_job_manager.get_job("ok")
    assert ok_job["status"] == "completed"
    assert ok_job["result"]["llm_model_name"] == "llama3.1"


@patch(
    "social_media_marketing_team.api.main._fetch_and_validate_brand",
    return_value=_MOCK_BRAND_CTX,
)
def test_run_and_status_functions_with_inline_thread(
    _mock_brand,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    temp_job_manager: CentralJobManager,
) -> None:
    class InlineThread:
        def __init__(self, target, args, daemon):
            self._target = target
            self._args = args
            self.daemon = daemon

        def start(self):
            self._target(*self._args)

    monkeypatch.setattr(api_main.threading, "Thread", InlineThread)

    request = api_main.RunMarketingTeamRequest(
        client_id="c1",
        brand_id="b1",
        llm_model_name="mistral",
        human_approved_for_testing=False,
    )
    response = api_main.run_marketing_team(request)
    assert response.status == "running"
    assert response.brand_summary is not None

    status = api_main.get_marketing_job_status(response.job_id)
    assert status.status == "completed"
    assert status.result is not None

    perf = api_main.ingest_performance(
        response.job_id, api_main.PerformanceIngestRequest(observations=[])
    )
    assert perf.observations_ingested == 0

    revise = api_main.revise_marketing_team(
        response.job_id,
        api_main.ReviseMarketingTeamRequest(feedback="Add more detail", approved_for_testing=True),
    )
    assert revise.status == "running"

    with pytest.raises(HTTPException):
        api_main.get_marketing_job_status("missing-job-id")


@patch(
    "social_media_marketing_team.api.main.fetch_brand",
    side_effect=BrandNotFoundError("c_miss", "b_miss"),
)
def test_run_marketing_team_brand_not_found(
    _mock_fetch, temp_job_manager: CentralJobManager
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        api_main.run_marketing_team(
            api_main.RunMarketingTeamRequest(
                client_id="c_miss",
                brand_id="b_miss",
                llm_model_name="model",
            )
        )
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error"] == "brand_not_found"


def test_revise_marketing_team_missing_job_and_health(temp_job_manager: CentralJobManager) -> None:
    with pytest.raises(HTTPException):
        api_main.revise_marketing_team(
            "missing",
            api_main.ReviseMarketingTeamRequest(feedback="retry", approved_for_testing=False),
        )

    assert api_main.health() == {"status": "ok"}

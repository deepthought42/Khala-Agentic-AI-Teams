"""Tests for Slack notifier integration used by product analysis."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from product_requirements_analysis_agent.agent import ProductRequirementsAnalysisAgent
from product_requirements_analysis_agent.models import OpenQuestion, QuestionOption
from shared import job_store
from shared.slack_notifier import SlackNotificationConfig, SlackNotifier


class _DummyLLM:
    def complete_json(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {}

    def complete_text(self, *args: Any, **kwargs: Any) -> str:
        return ""


class _FakeResponse:
    def __init__(self, status: int = 200) -> None:
        self.status = status

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None


def _sample_open_question() -> List[OpenQuestion]:
    return [
        OpenQuestion(
            id="q1",
            question_text="Which auth provider should be used?",
            context="Needed for implementation details.",
            options=[
                QuestionOption(id="auth0", label="Auth0"),
                QuestionOption(id="cognito", label="Amazon Cognito"),
            ],
            allow_multiple=False,
            source="spec_review",
        )
    ]


def test_slack_notifier_disabled_without_webhook(monkeypatch) -> None:
    monkeypatch.delenv("SOFTWARE_ENG_SLACK_WEBHOOK_URL", raising=False)
    notifier = SlackNotifier()
    assert notifier.enabled is False
    assert notifier.send_open_questions(job_id="j1", repo_path="/repo", iteration=1, question_count=2) is False


def test_slack_notifier_sends_payload(monkeypatch) -> None:
    captured: Dict[str, Any] = {}

    def _fake_urlopen(req: Any, timeout: int = 0) -> _FakeResponse:
        captured["url"] = req.full_url
        captured["data"] = req.data.decode("utf-8")
        captured["timeout"] = timeout
        return _FakeResponse(status=200)

    config = SlackNotificationConfig(
        webhook_url="https://hooks.slack.com/services/test/webhook",
        channel="eng-alerts",
    )
    monkeypatch.setattr("shared.slack_notifier.request.urlopen", _fake_urlopen)

    notifier = SlackNotifier(config=config)
    sent = notifier.send_open_questions(
        job_id="job-123",
        repo_path="/tmp/repo",
        iteration=2,
        question_count=3,
    )

    assert sent is True
    assert captured["url"].startswith("https://hooks.slack.com/services/")
    assert "job-123" in captured["data"]
    assert "Open questions: 3" in captured["data"]


def test_product_analysis_communicate_sends_slack_notification(monkeypatch, tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    job_store.create_job("job-1", str(tmp_path), cache_dir=cache_dir, job_type="product_analysis")

    sent: Dict[str, Any] = {}

    class _StubSlackNotifier:
        def send_open_questions(self, **kwargs: Any) -> bool:
            sent.update(kwargs)
            return True

    monkeypatch.setattr("shared.slack_notifier.SlackNotifier", _StubSlackNotifier)
    monkeypatch.setattr(job_store, "DEFAULT_CACHE_DIR", cache_dir)

    agent = ProductRequirementsAnalysisAgent(_DummyLLM())
    monkeypatch.setattr(agent, "_wait_for_answers", lambda _job_id: True)

    def _fake_get_submitted_answers(_job_id: str, cache_dir: Path = cache_dir):
        return [{"question_id": "q1", "selected_option_ids": ["auth0"]}]

    monkeypatch.setattr(job_store, "get_submitted_answers", _fake_get_submitted_answers)

    answered = agent._communicate_with_user(
        job_id="job-1",
        open_questions=_sample_open_question(),
        repo_path=tmp_path,
        iteration=1,
    )

    assert len(answered) == 1
    assert sent["job_id"] == "job-1"
    assert sent["question_count"] == 1

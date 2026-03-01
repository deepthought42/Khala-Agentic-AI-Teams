"""Slack notification helpers for software engineering team workflows."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Optional
from urllib import error, request

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SlackNotificationConfig:
    """Configuration for sending notifications to Slack."""

    webhook_url: str
    channel: Optional[str]

    @classmethod
    def from_env(cls) -> Optional["SlackNotificationConfig"]:
        """Load Slack config from environment variables.

        Required:
        - SOFTWARE_ENG_SLACK_WEBHOOK_URL

        Optional:
        - SOFTWARE_ENG_SLACK_CHANNEL
        """
        webhook_url = (os.getenv("SOFTWARE_ENG_SLACK_WEBHOOK_URL") or "").strip()
        if not webhook_url:
            return None
        channel = (os.getenv("SOFTWARE_ENG_SLACK_CHANNEL") or "").strip() or None
        return cls(webhook_url=webhook_url, channel=channel)


class SlackNotifier:
    """Simple Slack webhook notifier with fail-safe behavior."""

    def __init__(self, config: Optional[SlackNotificationConfig] = None) -> None:
        self._config = config or SlackNotificationConfig.from_env()

    @property
    def enabled(self) -> bool:
        """Whether Slack notifications are configured and available."""
        return self._config is not None

    def send_open_questions(
        self,
        *,
        job_id: str,
        repo_path: str,
        iteration: int,
        question_count: int,
    ) -> bool:
        """Send a product requirements analysis open-questions summary to Slack."""
        if not self._config:
            return False

        channel_prefix = f"#{self._config.channel} " if self._config.channel else ""
        text = (
            f"{channel_prefix}Product requirements analysis needs input.\n"
            f"• Job ID: `{job_id}`\n"
            f"• Repo: `{repo_path}`\n"
            f"• Iteration: {iteration}\n"
            f"• Open questions: {question_count}\n"
            "Answer the questions in the UI to resume the workflow."
        )

        payload = {"text": text}
        if self._config.channel:
            payload["channel"] = self._config.channel

        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            self._config.webhook_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=5) as response:
                status = getattr(response, "status", 200)
                if status >= 400:
                    logger.warning("Slack notification failed with HTTP status %s", status)
                    return False
                return True
        except error.HTTPError as exc:
            logger.warning("Slack notification HTTP error: %s", exc)
            return False
        except error.URLError as exc:
            logger.warning("Slack notification URL error: %s", exc)
            return False
        except Exception:
            logger.exception("Unexpected Slack notification failure")
            return False


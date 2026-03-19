"""Tests for Medium automated browser login."""

from __future__ import annotations

import pytest

from unified_api.medium_browser_login import perform_medium_google_browser_login


def test_perform_login_requires_email_and_password() -> None:
    with pytest.raises(RuntimeError, match="requires a stored email"):
        perform_medium_google_browser_login("", "x")
    with pytest.raises(RuntimeError, match="requires a stored email"):
        perform_medium_google_browser_login("a@b.com", "")

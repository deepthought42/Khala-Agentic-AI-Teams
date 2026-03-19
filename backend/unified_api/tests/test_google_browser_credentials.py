"""Shared Google browser login credentials (encrypted SQLite fallback when no Postgres)."""

from __future__ import annotations

import pytest

from unified_api import google_browser_login_credentials as mod


def test_save_clear_roundtrip_sqlite(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.delenv("POSTGRES_HOST", raising=False)
    monkeypatch.setenv("AGENT_CACHE", str(tmp_path))
    mod.clear_google_browser_login_credentials()
    mod.set_google_browser_login_credentials("user@example.com", "secret-pass")
    assert mod.google_browser_login_credentials_configured()
    em, pw = mod.get_google_browser_login_credentials()
    assert em == "user@example.com"
    assert pw == "secret-pass"
    mod.clear_google_browser_login_credentials()
    assert not mod.google_browser_login_credentials_configured()


def test_save_rejects_invalid_email(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.delenv("POSTGRES_HOST", raising=False)
    monkeypatch.setenv("AGENT_CACHE", str(tmp_path))
    with pytest.raises(ValueError, match="email"):
        mod.set_google_browser_login_credentials("not-an-email", "x")


def test_legacy_medium_keys_migrate(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Old medium_google_browser rows are read once and moved to platform_google_browser."""
    monkeypatch.delenv("POSTGRES_HOST", raising=False)
    monkeypatch.setenv("AGENT_CACHE", str(tmp_path))
    from unified_api.integration_credentials import set_credential

    set_credential("medium_google_browser", "google_login_email", "legacy@example.com")
    set_credential("medium_google_browser", "google_login_password", "legacy-secret")
    em, pw = mod.get_google_browser_login_credentials()
    assert em == "legacy@example.com"
    assert pw == "legacy-secret"
    # second read still works; legacy cleared
    em2, pw2 = mod.get_google_browser_login_credentials()
    assert em2 == "legacy@example.com"
    assert pw2 == "legacy-secret"

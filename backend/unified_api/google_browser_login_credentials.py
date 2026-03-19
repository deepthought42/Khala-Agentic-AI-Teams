"""
Platform-wide encrypted Google (Gmail) email/password for Playwright browser sign-in.

Used by any integration where the user signs in with Google on a third-party site (e.g. Medium).
Same credentials apply to all such integrations — store once under this service.

- When POSTGRES_HOST is set: Postgres `encrypted_integration_credentials`.
- Otherwise: encrypted SQLite `service_integrations`.

Legacy: previously stored under service ``medium_google_browser``; reads fall back and migrate.
"""

from __future__ import annotations

from unified_api.integration_credentials import delete_credential, get_credential, set_credential
from unified_api.postgres_encrypted_credentials import (
    pg_delete_credential,
    pg_get_credential,
    pg_set_credential,
    postgres_credentials_enabled,
)

_SERVICE = "platform_google_browser"
_KEY_EMAIL = "gmail_email"
_KEY_PASSWORD = "gmail_password"

_LEGACY_SERVICE = "medium_google_browser"
_LEGACY_EMAIL_KEY = "google_login_email"
_LEGACY_PASSWORD_KEY = "google_login_password"


def _use_postgres() -> bool:
    return postgres_credentials_enabled()


def _read_platform_raw() -> tuple[str, str]:
    if _use_postgres():
        email = pg_get_credential(_SERVICE, _KEY_EMAIL)
        password = pg_get_credential(_SERVICE, _KEY_PASSWORD)
    else:
        email = get_credential(_SERVICE, _KEY_EMAIL)
        password = get_credential(_SERVICE, _KEY_PASSWORD)
    return (email.strip(), password)


def _read_legacy_raw() -> tuple[str, str]:
    if _use_postgres():
        email = pg_get_credential(_LEGACY_SERVICE, _LEGACY_EMAIL_KEY)
        password = pg_get_credential(_LEGACY_SERVICE, _LEGACY_PASSWORD_KEY)
    else:
        email = get_credential(_LEGACY_SERVICE, _LEGACY_EMAIL_KEY)
        password = get_credential(_LEGACY_SERVICE, _LEGACY_PASSWORD_KEY)
    return (email.strip(), password)


def _clear_legacy_only() -> None:
    if _use_postgres():
        pg_delete_credential(_LEGACY_SERVICE, _LEGACY_EMAIL_KEY)
        pg_delete_credential(_LEGACY_SERVICE, _LEGACY_PASSWORD_KEY)
    else:
        delete_credential(_LEGACY_SERVICE, _LEGACY_EMAIL_KEY)
        delete_credential(_LEGACY_SERVICE, _LEGACY_PASSWORD_KEY)


def _write_platform(email: str, password: str) -> None:
    if _use_postgres():
        pg_set_credential(_SERVICE, _KEY_EMAIL, email)
        pg_set_credential(_SERVICE, _KEY_PASSWORD, password)
    else:
        set_credential(_SERVICE, _KEY_EMAIL, email)
        set_credential(_SERVICE, _KEY_PASSWORD, password)


def set_google_browser_login_credentials(email: str, password: str) -> None:
    """Encrypt and store shared Gmail / Google account credentials for browser automation."""
    email = (email or "").strip()
    password = password or ""
    if not email or "@" not in email:
        raise ValueError("A valid email address is required.")
    if not password:
        raise ValueError("Password is required.")
    _write_platform(email, password)
    _clear_legacy_only()


def clear_google_browser_login_credentials() -> None:
    """Remove shared Google browser-login credentials (platform + any legacy Medium-specific rows)."""
    if _use_postgres():
        pg_delete_credential(_SERVICE, _KEY_EMAIL)
        pg_delete_credential(_SERVICE, _KEY_PASSWORD)
    else:
        delete_credential(_SERVICE, _KEY_EMAIL)
        delete_credential(_SERVICE, _KEY_PASSWORD)
    _clear_legacy_only()


def get_google_browser_login_credentials() -> tuple[str, str]:
    """
    Return (email, password); empty strings if not configured.
    Migrates legacy medium_google_browser rows into platform_google_browser when found.
    """
    em, pw = _read_platform_raw()
    if em and pw:
        return (em, pw)
    lem, lpw = _read_legacy_raw()
    if lem and lpw:
        _write_platform(lem, lpw)
        _clear_legacy_only()
        return (lem, lpw)
    return ("", "")


def google_browser_login_credentials_configured() -> bool:
    email, password = get_google_browser_login_credentials()
    return bool(email and password)

"""URLs and locator hints for Medium (update when the site changes)."""

from __future__ import annotations

# Author-facing stats dashboard (requires session).
ME_STATS_URL = "https://medium.com/me/stats"

SIGNIN_URL = "https://medium.com/m/signin"

# Locators for email/password path (best-effort; Medium’s DOM varies).
EMAIL_INPUT = 'input[type="email"], input[name="email"], input[autocomplete="email"]'
PASSWORD_INPUT = 'input[type="password"]'

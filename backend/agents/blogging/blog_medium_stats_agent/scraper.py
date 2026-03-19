"""Playwright scrape + pure helpers for parsing Medium stats UI."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from .models import MediumPostStats, MediumStatsReport, MediumStatsRunConfig
from .selectors import EMAIL_INPUT, ME_STATS_URL, PASSWORD_INPUT, SIGNIN_URL

logger = logging.getLogger(__name__)

# Run in the browser: collect story links and nearby text from the stats page.
_EXTRACT_POSTS_JS = """
() => {
  const posts = new Map();
  const links = document.querySelectorAll('a[href*="/@"]');
  for (const el of links) {
    let href = el.getAttribute('href') || '';
    if (!href.includes('/@')) continue;
    if (href.includes('/followers') || href.includes('/following') || href.includes('/members')) continue;
    try {
      const u = new URL(href, 'https://medium.com');
      const parts = u.pathname.split('/').filter(Boolean);
      if (parts.length < 2 || (parts[0][0] !== '@')) continue;
      const seg = parts[1];
      if (!seg || ['stats', 'about', 'lists', 'latest', 'recommended'].includes(seg)) continue;
      const full = 'https://medium.com' + u.pathname.split('?')[0];
      let cell = el.closest('tr') || el.closest('[role="row"]') || el.parentElement;
      let raw = '';
      for (let i = 0; i < 6 && cell; i++) {
        raw = (cell.innerText || '').replace(/\\s+/g, ' ').trim();
        if (raw.length > 12) break;
        cell = cell.parentElement;
      }
      let title = (el.innerText || '').trim().split('\\n')[0].slice(0, 500);
      if (!title) title = seg.replace(/-/g, ' ');
      if (!posts.has(full)) posts.set(full, { url: full, title, raw_row_text: raw.slice(0, 2000) });
    } catch (e) {}
  }
  return Array.from(posts.values());
}
"""


def parse_number(token: str) -> Optional[float]:
    """Parse counts like '1,234', '1.2K', '3M'."""
    t = token.strip().replace(",", "").lower()
    if not t:
        return None
    mult = 1.0
    if t.endswith("k"):
        mult = 1000.0
        t = t[:-1]
    elif t.endswith("m"):
        mult = 1_000_000.0
        t = t[:-1]
    try:
        return float(t) * mult
    except ValueError:
        return None


def parse_metrics_from_text(text: str) -> Dict[str, Any]:
    """Best-effort extraction of labeled metrics from a row/cell string."""
    stats: Dict[str, Any] = {}
    if not text:
        return stats
    lowered = text.lower()
    for label in ("views", "reads", "read", "fans", "claps"):
        pat = rf"([\d.,]+[kKmM]?)\s*{re.escape(label)}\b"
        m = re.search(pat, lowered)
        if m:
            key = "reads" if label == "read" else label
            val = parse_number(m.group(1))
            if val is not None:
                stats[key] = int(val) if val == int(val) else val
    return stats


def extract_posts_from_html(html: str, base_url: str = "https://medium.com") -> List[Dict[str, Any]]:
    """
    Parse post rows from static HTML (for tests / fixtures).
    Mirrors the browser script loosely using BeautifulSoup.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html, "html.parser")
    posts: Dict[str, Dict[str, Any]] = {}
    for el in soup.select('a[href*="/@"]'):
        href = el.get("href") or ""
        if "/@" not in href:
            continue
        if any(x in href for x in ("/followers", "/following", "/members")):
            continue
        full_u = urljoin(base_url, href)
        parsed = urlparse(full_u)
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) < 2 or not parts[0].startswith("@"):
            continue
        seg = parts[1]
        if seg in ("stats", "about", "lists", "latest", "recommended"):
            continue
        path_key = f"https://medium.com{parsed.path.split('?')[0]}"
        if path_key in posts:
            continue
        cell = el.find_parent("tr") or el.parent
        raw = ""
        for _ in range(6):
            if cell is None:
                break
            raw = " ".join(cell.get_text(separator=" ", strip=True).split())
            if len(raw) > 12:
                break
            cell = cell.parent
        title = el.get_text(separator=" ", strip=True).split("\n")[0][:500]
        if not title:
            title = seg.replace("-", " ")
        posts[path_key] = {"url": path_key, "title": title, "raw_row_text": raw[:2000]}
    return list(posts.values())


def _account_hint_from_email(email: str) -> str:
    if "@" in email:
        return email.split("@", 1)[1].strip()
    return ""


def _resolve_auth(config: MediumStatsRunConfig) -> tuple[Optional[str], Optional[str], Optional[str]]:
    storage = (config.storage_state_path or os.environ.get("MEDIUM_STORAGE_STATE_PATH") or "").strip() or None
    email = (config.email or os.environ.get("MEDIUM_EMAIL") or "").strip() or None
    password = config.password or os.environ.get("MEDIUM_PASSWORD")
    if password is not None:
        password = str(password)
    if password == "":
        password = None
    return storage, email, password


def _login_email_password(page: Any, email: str, password: str, warnings: List[str]) -> None:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    page.goto(SIGNIN_URL, wait_until="domcontentloaded")
    # Optional: open email tab
    try:
        email_btn = page.get_by_role("button", name=re.compile(r"email", re.I))
        if email_btn.count() > 0:
            email_btn.first.click(timeout=5000)
    except PlaywrightTimeoutError:
        warnings.append("Could not click email sign-in button; continuing with visible form.")

    try:
        page.locator(EMAIL_INPUT).first.fill(email, timeout=20_000)
    except PlaywrightTimeoutError as e:
        raise RuntimeError("Medium login: email field not found.") from e

    for label in ("Continue", "Next"):
        try:
            btn = page.get_by_role("button", name=label)
            if btn.count() > 0:
                btn.first.click(timeout=5000)
                break
        except PlaywrightTimeoutError:
            continue

    try:
        page.locator(PASSWORD_INPUT).first.fill(password, timeout=25_000)
    except PlaywrightTimeoutError as e:
        raise RuntimeError("Medium login: password field not found (magic link / OAuth only?).") from e

    try:
        sign = page.get_by_role("button", name=re.compile(r"sign\s*in|log\s*in", re.I))
        sign.first.click(timeout=15_000)
    except PlaywrightTimeoutError:
        page.keyboard.press("Enter")

    # networkidle often never settles on Medium; wait for navigation then DOM.
    try:
        page.wait_for_load_state("domcontentloaded", timeout=45_000)
    except PlaywrightTimeoutError:
        warnings.append("Login navigation did not settle within timeout; continuing.")


def collect_medium_stats(config: MediumStatsRunConfig) -> MediumStatsReport:
    """
    Launch Chromium, authenticate, open /me/stats, extract post rows.

    Raises RuntimeError on missing auth configuration or obvious login failure.
    """
    warnings: List[str] = []
    storage_path, email, password = _resolve_auth(config)
    if not storage_path and not (email and password):
        raise RuntimeError(
            "Medium stats: set MEDIUM_STORAGE_STATE_PATH or both MEDIUM_EMAIL and MEDIUM_PASSWORD "
            "(or pass storage_state_path / email / password in the request).",
        )
    if storage_path and not Path(storage_path).is_file():
        raise RuntimeError(f"Medium stats: storage state file not found: {storage_path}")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError("playwright is not installed. pip install playwright && playwright install chromium") from e

    account_hint = _account_hint_from_email(email) if email else ""

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=config.headless)
        try:
            if storage_path:
                context = browser.new_context(storage_state=storage_path)
            else:
                context = browser.new_context()
            page = context.new_page()
            page.set_default_timeout(config.timeout_ms)
            if not storage_path:
                assert email and password
                _login_email_password(page, email, password, warnings)
                account_hint = _account_hint_from_email(email)

            page.goto(ME_STATS_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)

            raw_rows: List[Dict[str, Any]] = page.evaluate(_EXTRACT_POSTS_JS)
            if not raw_rows:
                warnings.append(
                    "No story links found on /me/stats. You may need to update scraper selectors, "
                    "or the session may not have access to the stats page.",
                )

            posts: List[MediumPostStats] = []
            for row in raw_rows:
                url = str(row.get("url") or "")
                title = str(row.get("title") or "")
                raw_text = str(row.get("raw_row_text") or "")
                metrics = parse_metrics_from_text(raw_text)
                posts.append(
                    MediumPostStats(title=title, url=url, stats=metrics, raw_row_text=raw_text),
                )

            if config.max_posts is not None:
                posts = posts[: config.max_posts]

            return MediumStatsReport(
                account_hint=account_hint,
                posts=posts,
                raw_warnings=warnings,
            )
        finally:
            browser.close()

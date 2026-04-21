FROM python:3.11-slim

# Build context: backend/ (match team_service/Dockerfile)

# ── System deps ──────────────────────────────────────────────────────────────
# curl  — HEALTHCHECK probes /health in later phases
# libpq-dev + git — pulled in by psycopg build + some SE agents
# Playwright/Chromium runtime libs — required by blogging agents that touch the
#   browser automation stack even if the specific agent under test never loads a page
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl libpq-dev git \
      libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
      libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
      libgbm1 libpango-1.0-0 libcairo2 libasound2t64 libatspi2.0-0 \
      fonts-liberation fonts-unifont \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Python deps ──────────────────────────────────────────────────────────────
COPY agent_sandbox_image/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install chromium

# ── Agent code ───────────────────────────────────────────────────────────────
# Mirrors team_service/Dockerfile:16 — copy the full agents/ tree so every
# registry manifest resolves. Namespacing stays identical to dev/monolith.
COPY agents/ /app/agents/

# Minimal unified_api slice some teams import (Medium integration, credential
# store, google-browser-login) — same subset team_service and blogging_service use.
COPY unified_api/__init__.py /app/unified_api/__init__.py
COPY unified_api/integrations_store.py /app/unified_api/integrations_store.py
COPY unified_api/integration_credentials.py /app/unified_api/integration_credentials.py
COPY unified_api/postgres_encrypted_credentials.py /app/unified_api/postgres_encrypted_credentials.py
COPY unified_api/google_browser_login_credentials.py /app/unified_api/google_browser_login_credentials.py
COPY unified_api/medium_browser_login.py /app/unified_api/medium_browser_login.py

# The sandbox bootstrap package — resolves SANDBOX_AGENT_ID and mounts the shim.
COPY agent_sandbox_runtime/ /app/agent_sandbox_runtime/

# ── Non-root user ────────────────────────────────────────────────────────────
RUN adduser --disabled-password --gecos "" --uid 1000 sandbox \
    && chown -R sandbox:sandbox /app
USER sandbox

# ── Runtime env ──────────────────────────────────────────────────────────────
# PYTHONPATH matches team_service layout: /app/agents for team packages,
# /app/agents/blogging so `from blog_planning_agent...` works, /app for
# unified_api slice.
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/agents:/app/agents/blogging:/app \
    OTEL_SDK_DISABLED=1

EXPOSE 8090

HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
    CMD curl -f http://localhost:8090/health || exit 1

CMD ["python", "-m", "agent_sandbox_runtime.entrypoint"]

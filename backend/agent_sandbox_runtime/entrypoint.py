"""Single-agent sandbox bootstrap.

Phase 1 of the sandbox re-architecture (issue #263). Loads exactly one AI
agent — identified by ``SANDBOX_AGENT_ID`` — and exposes it via
``POST /_agents/{agent_id}/invoke`` plus ``GET /health`` on ``0.0.0.0:8090``.

The module is the container ``CMD``; it never runs in the unified API process.
Invariants:
  * Must not write to ``/app`` at runtime (image will be run ``--read-only``).
  * Fail fast with non-zero exit codes so the lifecycle owner can observe failures.
"""

from __future__ import annotations

import logging
import os
import sys

import uvicorn
from fastapi import FastAPI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("agent_sandbox")

EXIT_MISSING_ENV = 2
EXIT_UNKNOWN_AGENT = 3
EXIT_REGISTRY_LOAD_ERROR = 4


def _build_app() -> FastAPI:
    agent_id = os.environ.get("SANDBOX_AGENT_ID")
    if not agent_id:
        log.error("FATAL: SANDBOX_AGENT_ID env var is required")
        sys.exit(EXIT_MISSING_ENV)

    try:
        from agent_registry import get_registry
    except Exception as exc:
        log.exception("FATAL: could not import agent_registry: %s", exc)
        sys.exit(EXIT_REGISTRY_LOAD_ERROR)

    try:
        manifest = get_registry().get(agent_id)
    except KeyError:
        log.error("FATAL: agent_id %r not found in registry", agent_id)
        sys.exit(EXIT_UNKNOWN_AGENT)
    except Exception as exc:
        log.exception("FATAL: registry lookup for %r failed: %s", agent_id, exc)
        sys.exit(EXIT_REGISTRY_LOAD_ERROR)

    log.info(
        "sandbox starting: agent_id=%s team=%s entrypoint=%s",
        manifest.id,
        manifest.team,
        manifest.source.entrypoint if manifest.source else "<none>",
    )

    app = FastAPI(title=f"agent-sandbox:{manifest.id}")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "agent_id": manifest.id, "team": manifest.team}

    # Mount the existing shim. The shim's team-guard (shim.py:54) is a no-op
    # here because every request in this container is for `manifest.id`, whose
    # team == team_key by construction. Phase 5 generalizes the shim; Phase 1
    # reuses it unchanged.
    from shared_agent_invoke import mount_invoke_shim

    mount_invoke_shim(app, team_key=manifest.team)

    return app


def main() -> None:
    app = _build_app()
    uvicorn.run(app, host="0.0.0.0", port=8090, workers=1, log_level="info")


if __name__ == "__main__":
    main()

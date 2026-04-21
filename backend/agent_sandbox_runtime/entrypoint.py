"""Single-agent sandbox bootstrap.

Phase 1 of the sandbox re-architecture (issue #263). Loads exactly one AI
agent — identified by ``SANDBOX_AGENT_ID`` — and exposes it via
``POST /_agents/{agent_id}/invoke`` plus ``GET /health`` on ``0.0.0.0:8090``.

The module is the container ``CMD``; it never runs in the unified API process.
Invariants:
  * Must not write to ``/app`` at runtime (image will be run ``--read-only``).
  * Fail fast with non-zero exit codes so the lifecycle owner can observe failures.
  * Only the single bound ``SANDBOX_AGENT_ID`` is invocable. Requests for any
    other agent id — even same-team — return 404. The shared shim's guard is
    team-scoped, so we add a middleware here to enforce the tighter
    single-agent contract.
"""

from __future__ import annotations

import logging
import os
import sys

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("agent_sandbox")

EXIT_MISSING_ENV = 2
EXIT_UNKNOWN_AGENT = 3
EXIT_REGISTRY_LOAD_ERROR = 4

_INVOKE_PATH_PREFIX = "/_agents/"


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
        registry = get_registry()
    except Exception as exc:
        log.exception("FATAL: agent_registry load failed: %s", exc)
        sys.exit(EXIT_REGISTRY_LOAD_ERROR)

    # AgentRegistry.get() returns None for unknown ids; it does not raise.
    manifest = registry.get(agent_id)
    if manifest is None:
        log.error("FATAL: agent_id %r not found in registry", agent_id)
        sys.exit(EXIT_UNKNOWN_AGENT)

    log.info(
        "sandbox starting: agent_id=%s team=%s entrypoint=%s",
        manifest.id,
        manifest.team,
        manifest.source.entrypoint if manifest.source else "<none>",
    )

    app = FastAPI(title=f"agent-sandbox:{manifest.id}")
    bound_agent_id = manifest.id

    @app.middleware("http")
    async def _single_agent_guard(request: Request, call_next):
        """Reject invoke requests for any agent other than the bound one.

        The shared shim's guard (shim.py:54) is team-scoped, so without this
        middleware a sandbox started for ``blogging.planner`` would still
        serve ``blogging.writer`` et al. via the same ``/_agents/{id}/invoke``
        route. That violates the single-agent-per-sandbox contract this phase
        establishes.
        """
        path = request.url.path
        if path.startswith(_INVOKE_PATH_PREFIX):
            # Expected shape: /_agents/{agent_id}/invoke[/...]
            remainder = path[len(_INVOKE_PATH_PREFIX) :]
            requested_id = remainder.split("/", 1)[0]
            if requested_id and requested_id != bound_agent_id:
                return JSONResponse(
                    status_code=404,
                    content={
                        "detail": (
                            f"Sandbox is bound to {bound_agent_id!r}; "
                            f"refusing invoke for {requested_id!r}."
                        ),
                    },
                )
        return await call_next(request)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "agent_id": bound_agent_id, "team": manifest.team}

    # Mount the existing shim. Its team-guard still runs (defense in depth),
    # and the middleware above restricts to the single bound agent. Phase 5
    # generalizes the shim; Phase 1 reuses it unchanged.
    from shared_agent_invoke import mount_invoke_shim

    mount_invoke_shim(app, team_key=manifest.team)

    return app


def main() -> None:
    app = _build_app()
    uvicorn.run(app, host="0.0.0.0", port=8090, workers=1, log_level="info")


if __name__ == "__main__":
    main()

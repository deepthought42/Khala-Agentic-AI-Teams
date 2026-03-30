"""Generic team microservice entrypoint.

Reads configuration from environment variables:
  TEAM_MODULE                    — dotted import path, e.g. "branding_team.api.main"
  TEAM_APP_ATTR                  — attribute name on the module (default "app")
  TEAM_PORT                      — listen port (default 8090)
  TEAM_NAME                      — job-service team name for shutdown hooks
  TEAM_TEMPORAL_WORKER_MODULE    — optional Temporal worker module path
  TEAM_TEMPORAL_WORKER_FUNC      — optional Temporal worker start function name
"""

import atexit
import importlib
import logging
import os

import uvicorn

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("team_service")

TEAM_MODULE = os.environ["TEAM_MODULE"]
TEAM_APP_ATTR = os.environ.get("TEAM_APP_ATTR", "app")
TEAM_PORT = int(os.environ.get("TEAM_PORT", "8090"))
TEAM_NAME = os.environ.get("TEAM_NAME", "team")
TEMPORAL_MODULE = os.environ.get("TEAM_TEMPORAL_WORKER_MODULE", "").strip()
TEMPORAL_FUNC = os.environ.get("TEAM_TEMPORAL_WORKER_FUNC", "").strip()


def _start_temporal_worker() -> None:
    """Start the team's Temporal worker thread when TEMPORAL_ADDRESS is configured."""
    if not TEMPORAL_MODULE or not TEMPORAL_FUNC:
        return
    if not os.environ.get("TEMPORAL_ADDRESS", "").strip():
        return
    try:
        mod = importlib.import_module(TEMPORAL_MODULE)
        start_fn = getattr(mod, TEMPORAL_FUNC)
        if start_fn():
            logger.info("Temporal worker started for %s", TEAM_NAME)
    except Exception:
        logger.warning("Could not start Temporal worker for %s", TEAM_NAME, exc_info=True)


def _shutdown_hook() -> None:
    """Mark active jobs as interrupted on service shutdown."""
    try:
        from job_service_client import JobServiceClient

        client = JobServiceClient(team=TEAM_NAME)
        client.mark_all_active_jobs_interrupted(f"{TEAM_NAME} service shutting down")
    except Exception:
        logger.warning("Shutdown hook failed for %s", TEAM_NAME, exc_info=True)


def _resolve_app() -> str:
    """Return a uvicorn import string for the ASGI app.

    If TEAM_APP_ATTR points to an APIRouter (not a FastAPI app), write a
    wrapper module to disk so uvicorn worker processes can import it.
    """
    # Validate the team module can be imported (fail fast with a clear error).
    try:
        importlib.import_module(TEAM_MODULE)
    except Exception:
        logger.exception("FATAL: cannot import team module %s", TEAM_MODULE)
        raise

    if TEAM_APP_ATTR == "router":
        # Write a real Python file that uvicorn workers can import.
        import pathlib

        wrapper_path = pathlib.Path("/app/_team_wrapper.py")
        wrapper_path.write_text(
            f"from fastapi import FastAPI\n"
            f"from {TEAM_MODULE} import {TEAM_APP_ATTR} as _router\n"
            f"app = FastAPI(title='{TEAM_NAME} API')\n"
            f"app.include_router(_router)\n",
            encoding="utf-8",
        )
        return "_team_wrapper:app"
    return f"{TEAM_MODULE}:{TEAM_APP_ATTR}"


if __name__ == "__main__":
    logger.info("Starting %s on port %d (module=%s)", TEAM_NAME, TEAM_PORT, TEAM_MODULE)
    _start_temporal_worker()
    atexit.register(_shutdown_hook)
    app_import = _resolve_app()
    uvicorn.run(
        app_import,
        host="0.0.0.0",
        port=TEAM_PORT,
        workers=2,
        log_level="info",
    )

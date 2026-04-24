"""Start the user_agent_founder Temporal workflow from synchronous API code.

Bridges a sync request handler into the Temporal worker's asyncio loop via
``asyncio.run_coroutine_threadsafe`` (mirrors ``blogging/temporal/start_workflow.py``).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from shared_temporal import get_temporal_client, get_temporal_loop
from user_agent_founder.temporal import (
    TASK_QUEUE,
    WORKFLOW_ID_PREFIX,
    UserAgentFounderWorkflow,
)

logger = logging.getLogger(__name__)

START_WORKFLOW_TIMEOUT = 30


def _run_async(coro: Any) -> Any:
    loop = get_temporal_loop()
    client = get_temporal_client()
    if loop is None or client is None:
        raise RuntimeError(
            "Temporal client not available; is the user_agent_founder worker running?"
        )
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=START_WORKFLOW_TIMEOUT)


def start_founder_workflow(run_id: str) -> None:
    """Start ``UserAgentFounderWorkflow`` for the given run id."""
    client = get_temporal_client()
    if client is None:
        raise RuntimeError("Temporal client not available")
    workflow_id = f"{WORKFLOW_ID_PREFIX}{run_id}"
    _run_async(
        client.start_workflow(
            UserAgentFounderWorkflow.run,
            run_id,
            id=workflow_id,
            task_queue=TASK_QUEUE,
        )
    )
    logger.info("Started UserAgentFounderWorkflow id=%s", workflow_id)

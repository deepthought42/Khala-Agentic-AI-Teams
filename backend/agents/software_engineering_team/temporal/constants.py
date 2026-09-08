"""
Temporal workflow IDs, task queue, and activity/workflow names for the SE team.
"""

import os

# Task queue used by the SE worker and when starting workflows
TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "software-engineering").strip()

# Workflow ID prefixes (workflow_id = prefix + job_id or similar)
WORKFLOW_ID_PREFIX_RUN_TEAM = "se-run-team-"
WORKFLOW_ID_PREFIX_RETRY_FAILED = "se-retry-failed-"
WORKFLOW_ID_PREFIX_STANDALONE = "se-standalone-"

# Workflow type names (as registered with the worker)
WORKFLOW_RETRY_FAILED = "RetryFailedWorkflow"
WORKFLOW_STANDALONE_JOB = "StandaloneJobWorkflow"

# Activity names (as registered with the worker)
ACTIVITY_RETRY_FAILED = "retry_failed"
ACTIVITY_FRONTEND_CODE_V2 = "run_frontend_code_v2"
ACTIVITY_BACKEND_CODE_V2 = "run_backend_code_v2"
ACTIVITY_PRODUCT_ANALYSIS = "run_product_analysis"

# Standalone job types (for StandaloneJobWorkflow)
STANDALONE_TYPE_FRONTEND = "frontend-code-v2"
STANDALONE_TYPE_BACKEND = "backend-code-v2"
STANDALONE_TYPE_PRODUCT_ANALYSIS = "product-analysis"

# Heartbeat timeouts for the RunTeamWorkflowV2 phase activities (seconds). Declared
# here rather than inline in workflows.py so each activity's background beater can
# size its interval against the SAME number the workflow schedules with: a beater
# whose interval drifts above its own heartbeat timeout is exactly the failure this
# pairing exists to prevent (Temporal times the attempt out and retries it while the
# original keeps running and writing).
PHASE_HEARTBEAT_TIMEOUT_S = 300.0
CODING_HEARTBEAT_TIMEOUT_S = 600.0

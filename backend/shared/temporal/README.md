# shared.temporal

Single source of truth for Temporal-backed, resumable job execution across
every agent team. Replaces the per-team `temporal/client.py`,
`temporal/worker.py`, and ad-hoc pause/resume logic.

## Migration recipe (per team)

1. **Define workflow + activity.** Create `{team}/temporal/workflows.py`
   with a `@workflow.defn` class whose `run()` simply invokes one
   `@activity.defn` wrapping the team's existing orchestrator entrypoint:

   ```python
   from temporalio import workflow, activity

   @activity.defn
   def run_pipeline(request: dict) -> dict:
       from my_team.orchestrator import run
       return run(request)

   @workflow.defn
   class MyTeamWorkflow:
       @workflow.run
       async def run(self, request: dict) -> dict:
           return await workflow.execute_activity(
               run_pipeline, request, start_to_close_timeout=timedelta(hours=2)
           )
   ```

2. **Mount the standard router** in `{team}/api/main.py`:

   ```python
   from team_contract.job_router import create_job_router
   app.include_router(create_job_router("my_team"), prefix="/api/my-team")
   ```

   This gives you `POST /jobs`, `GET /jobs`, `GET /jobs/{id}`,
   `DELETE /jobs/{id}`, and `POST /jobs/{id}/resume` for free.

3. **Start the worker** during app lifespan:

   ```python
   from shared.temporal import start_team_worker
   from my_team.temporal.workflows import MyTeamWorkflow, run_pipeline

   start_team_worker("my_team", [MyTeamWorkflow], [run_pipeline])
   ```

4. **Dispatch jobs** from your HTTP handlers via `run_team_job`:

   ```python
   from shared.temporal import run_team_job
   from my_team.temporal.workflows import MyTeamWorkflow

   run_team_job(
       team="my_team",
       job_id=job_id,
       workflow=MyTeamWorkflow.run,
       workflow_args=[request.dict()],
   )
   ```

## Checkpoints and human-in-the-loop

Use `save_checkpoint` / `load_checkpoint` at phase boundaries inside an
activity so a retried workflow can skip completed phases. For pauses that
need user input, use `wait_for_input` (thread mode) or a Temporal signal
handler that calls `submit_input` (Temporal mode); both operate on the same
job record fields (`waiting_for`, `inputs`) so the HTTP resume route works
for either mode.

## Background heartbeats

The "daemon thread beats a callable on an interval" keep-alive that Temporal
activities use (e.g. `execute_coding_team_activity`'s `activity.heartbeat()`
beater) is driven by the shared `BackgroundHeartbeat` helper in the
**`shared.concurrency`** package (it is Temporal-agnostic and also used by
non-Temporal callers). See `backend/shared/concurrency/README.md`.

Every activity scheduled with a `heartbeat_timeout` must run one: a declared
timeout that nothing honours is worse than none at all, because Temporal times
the attempt out and retries it while the original attempt keeps running and
writing the same job record.

The SE team's beater intervals are each capped at a third of the timeout the
workflow schedules the activity with (`PHASE_HEARTBEAT_TIMEOUT_S` /
`CODING_HEARTBEAT_TIMEOUT_S` in `software_engineering_team/temporal/constants.py`),
so a mis-set override can never re-open that gap:

- `SE_PHASE_HEARTBEAT_INTERVAL_S` — `parse_spec_activity` / `plan_project_activity`
  (seconds; blank/garbage/non-finite falls back to `30`, then clamped to
  `[1, PHASE_HEARTBEAT_TIMEOUT_S / 3]`).
- `CODING_TEAM_HEARTBEAT_INTERVAL_S` — `execute_coding_team_activity` (seconds;
  blank/garbage/non-positive/non-finite falls back to `30`, then capped at
  `CODING_HEARTBEAT_TIMEOUT_S / 3`).
- `GITHUB_ISSUE_GROOMING_HEARTBEAT_INTERVAL_S` — `run_issue_grooming_activity`
  (seconds; blank/garbage falls back to `30`, floor `0.1`).

Because these are *synchronous* activities, the beater is also what delivers
cancellation: `activity.is_cancelled()` only ever flips because a beat carried
the server's cancellation back. That is why the SE phase activities pair the
beater with `shared.temporal.activity_utils.is_cancelled` guards on every
job-record write — a superseded attempt must stop writing rather than race the
live one to the finish.

## Environment

- `TEMPORAL_ADDRESS` — required; Temporal is mandatory for all teams.
- `TEMPORAL_NAMESPACE` — default `default`.
- `TEMPORAL_TASK_QUEUE` — default `khala`.
- `TEMPORAL_PAYLOAD_COMPRESSION` — gzip payload codec write-toggle, default
  `false`/off (see below).
- `TEMPORAL_PAYLOAD_COMPRESSION_MIN_BYTES` — gzip compression size floor in
  bytes, default `1024` (see below).

## Payload compression

`connect_temporal_client` builds its `Client`'s `DataConverter` via
`shared.temporal.codec.build_data_converter`, which always installs a gzip
`PayloadCodec`. A team whose activities move large, highly compressible
payloads — e.g. `code_review_agent`'s map-reduce chunks, which carry the full,
untruncated diff by design — can otherwise trip Temporal's 512 KiB
`PayloadSizeWarning` (`TMPRL1103`) well before hitting any real gRPC message
limit. The codec runs transparently underneath every team's client and worker
(they share this one `connect_temporal_client` call), so no team needs its own
opt-in.

Only *writing* compressed payloads is gated by `TEMPORAL_PAYLOAD_COMPRESSION`
(default off) — decoding is unconditional. This split exists because several
teams here are independently deployable services sharing one Temporal cluster
through this same client: a process built before this codec existed can never
decode a payload a newer, compression-enabled process already wrote, so a
staggered fleet rollout could strand in-flight workflows if writing defaulted
on. Roll out safely by deploying this code everywhere first (decode-only,
nothing changes), then flipping the env var on once every service on the
cluster is confirmed upgraded. See `docs/ENV_VARS.md` for the toggle/threshold
env vars and `shared/temporal/codec.py` for the implementation.

## See also

- **`backend/shared/postgres/`** — sibling module that applies the
  same registry idea to Postgres DDL. Each team exports a `SCHEMA:
  TeamSchema` from `<team>/postgres/__init__.py` and its FastAPI lifespan
  calls `register_team_schemas(SCHEMA)` at startup. Unlike `shared.temporal`'s
  Pattern A (import-time side effect), `shared.postgres` uses Pattern B
  (explicit lifespan call) because DDL is synchronous blocking I/O.

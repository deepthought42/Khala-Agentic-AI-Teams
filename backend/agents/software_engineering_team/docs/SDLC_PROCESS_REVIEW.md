# SDLC & Product-Development Process Review — Software Engineering Team

Reviewer role: Principal Software Engineer (SDLC & process automation)
Scope: `backend/agents/software_engineering_team/` and its sub-teams (`backend_code_v2_team/`, `frontend_code_v2_team/`, `devops_team/`, `integration_team/`, `planning_v2_team/`, adapters to `planning_v3_team` and `coding_team/`)
Goal: Inventory every process currently in place, then select the three highest-leverage changes needed to make the agentic team behave like a real engineering organisation running a real product.

---

## Part 1 — Current-state inventory

### 1.1 Orchestration & runtime

| Concern | Where | Notes |
|---|---|---|
| Pipeline entrypoint | `orchestrator.py::run_orchestrator` (lines 2170-2220) | Single synchronous function, one spec → one job. |
| Runtime mode | Thread pool by default; Temporal when `TEMPORAL_ADDRESS` is set (`temporal/worker.py`, `ARCHITECTURE.md` §1) | Durable execution only for the workflow envelope. |
| Job state | `shared/job_store.py` | Cancellation, progress, clarification Q&A, stale-heartbeat monitor (`orchestrator.py:124`). |
| Top-level graph | `graphs/top_level.py:32-89` | Phases: Discovery → Design → Execution → Integration (see `ARCHITECTURE.md` §2). |

### 1.2 Four-phase macro pipeline

1. **Discovery** — `spec_parser.py` → `product_requirements_analysis_agent/` → `planning_v2_adapter.py` (or `planning_v3_adapter.py`). Produces `ProductRequirements` (`shared/models.py:162-176`) and `project_overview`.
2. **Design** — `tech_lead_agent/agent.py` + `architect-agents/` produce Initiative/Epic/Story hierarchy, `master_plan.md`, architecture doc. Alignment & conformance loops up to `SW_MAX_ALIGNMENT_ITERATIONS=20` and `SW_MAX_CONFORMANCE_RETRIES=20` (`ARCHITECTURE.md` §9). Planning cache (`shared/planning_cache.py`) short-circuits when spec + architecture + overview are unchanged.
3. **Execution** — `orchestrator._run_backend_frontend_workers` (line 1468) partitions `TaskAssignment.execution_order` into three queues:
   - **Prefix queue** (sequential): `git_setup_agent/`, DevOps tasks
   - **Backend queue** (1-at-a-time worker thread) → `backend_code_v2_team/` or legacy `backend_agent/`
   - **Frontend queue** (1-at-a-time worker thread) → `frontend_code_v2_team/`
4. **Integration** — `integration_team/agent.py` (single LLM pass reviewing backend vs. frontend strings), `devops_team/` trigger, full-codebase security sweep, `technical_writers/`, merge.

### 1.3 Per-task inner pipeline (backend & frontend V2)

Graph: `ARCHITECTURE.md` §5 and `backend_code_v2_team/phases/execution.py:242-777`.

```
feature branch → per-task plan → codegen → write files
  → lint (linting_tool_agent) → build (pytest / ng build)
  → code review → acceptance verifier → security → QA
  → (frontend only) accessibility (WCAG 2.2)
  → DbC comments → tech-lead review → doc update → merge to development
```

Failure handling:
- Build failure → `build_fix_specialist/` targeted retry (`orchestrator._try_build_fix_one_at_a_time`, line 912).
- Review/QA/security findings → loop back to codegen; per-gate `code_review_max_retries`, `qa_max_retries`, `security_max_retries` (`MicrotaskReviewConfig`).
- Agent crash → `problem_solver_agent/` ("repair agent") analyses traceback and patches agent source (`orchestrator._apply_repair_fixes`, line 294).
- Contract repair → re-invoke Tech Lead `refine_task` when a task is missing required fields.
- Terminal failure → `shared/post_mortem.py` appends an entry to `post_mortems/POST_MORTEMS.md`.

### 1.4 Quality gates (cross-cutting, not task assignees)

Defined in `quality_gates/README.md`:

| Gate | Agent | Scope |
|---|---|---|
| Code review | `code_review_agent/` | Every backend & frontend task |
| QA | `qa_agent/` | Bugs + tests + README check |
| Security | `security_agent/` | Per-task + final full-codebase sweep |
| Accessibility | `accessibility_agent/` | Frontend per-task only |
| Acceptance | `acceptance_verifier_agent/` | Per-criterion evidence |
| Design-by-Contract | `technical_writers/dbc_comments_agent/` | Pre/postconditions, invariants |
| Linting | `linting_tool_agent/` | Language-aware |

### 1.5 DevOps team (5 phases)

`devops_team/orchestrator.py` — Intake → Change Design → Write Artifacts → Validation → Completion (`ARCHITECTURE.md` §8). Hard gates: `iac_validate`, `iac_validate_fmt`, `policy_checks`, `pipeline_lint`, `pipeline_gate_check`, `deployment_dry_run`, `security_review`, `change_review` (`devops_team/orchestrator.py:33-42`). Environment policy matrix (lines 44-62) encodes dev/staging/prod strictness, approval and rollback-test requirements.

### 1.6 Planning

- **v2** (`planning_v2_team/`) — legacy 6-phase; still reachable via `planning_v2_adapter.py`.
- **v3** (`planning_v3_team/`) — standalone, client-facing discovery / PRD flow; SE invokes it through `planning_v3_adapter.py` (Intake → Discovery → Requirements → Synthesis → Document Production → Sub-agent Provisioning). Optional integrations: `run_product_analysis`, `market_research_to_evidence`.

### 1.7 Repo-level CI/CD (outside the agents)

`.github/workflows/ci.yml`:
- Ruff + ng lint gate (blocking).
- Per-team pytest jobs + shared_postgres suite against live Postgres.
- Vitest at 80% coverage target.
- GHCR image build on `push` to main/development after all tests pass.

### 1.8 Observability & cross-cutting infra

- Logging: stdlib `logging` everywhere (`shared/logging_config.py`); `logging_service/` exposes an HTTP endpoint when `ENABLE_LOG_API=true`.
- Tracing / metrics / cost / token accounting: **none** in SE. `grep` for `opentelemetry|prometheus|cost_tracker|trace_id` across `software_engineering_team/` returns only incidental matches. Strands Agents claims retries/telemetry but the SE code does not consume it.
- Event bus (`backend/agents/event_bus/`): **not wired** in SE — zero call-sites found.
- Artifact registry: per-run on disk only (`plan/`, `backend/`, `frontend/`, `post_mortems/`); no versioning, catalog, or retention.

---

## Part 2 — The three highest-impact changes

Criteria used: each recommendation must be a structural change (not a cosmetic one), must close a gap against how real engineering orgs ship product, and must unlock further improvements once landed.

### Recommendation #1 — Move from "one-shot spec → code" to a persistent, iterative Product Delivery Loop (PRD → Backlog → Sprint → Release → Feedback)

**Why this is #1.** The single biggest gap between this team and a real engineering org is not technical — it is *organisational*. Every run is a terminal spec-to-code operation: the Initiative/Epic/Story tree produced by `tech_lead_agent/agent.py` is written to `plan/`, consumed once, and discarded when the job ends. There is no persistent backlog, no grooming, no prioritisation, no sprint cadence, no iteration, no post-release learning, and no user-feedback intake. That is a code generator, not a product team.

**What to build.**

1. **Postgres-backed Product Backlog** using the existing `shared_postgres` pattern (Pattern B from `CLAUDE.md`). New tables: `products`, `initiatives`, `epics`, `stories`, `tasks`, `acceptance_criteria`, `releases`, `sprints`, `feedback_items`. Rows are tagged with the `AuthorProfile` handle already used by the Agent Console so the data survives the eventual auth migration.
2. **Product Owner agent** (new role, lives alongside `tech_lead_agent/`). Responsibilities: ingest raw inputs (spec, user feedback, market research from `planning_v3_team` / `market_research_team`, post-mortems, production telemetry) and maintain a *ranked* backlog using WSJF or RICE. It owns prioritisation; the Tech Lead stops inventing tasks from a spec and instead *pulls* the next sprint's scope from the backlog.
3. **Sprint planner** — a thin orchestrator phase that, on each run, selects the highest-ranked items that fit estimated capacity, creates a `sprint` row, and only then invokes the existing Discovery → Design → Execution → Integration pipeline. Current planning-cache logic still works, scoped to the sprint.
4. **Release notes + feedback intake.** At the end of Integration, a Release Manager agent composes release notes from merged tasks (reusing `technical_writers/`) and opens a `feedback_items` bucket that ingests (a) failures surfaced by the new telemetry layer in Recommendation #3, (b) post-mortems, (c) any human-submitted notes. These become candidate backlog items for the next sprint.
5. **UI.** Extend the Agent Console with a "Backlog" and "Sprints" tab — the scaffolding in `agent_console/` (saved inputs, runs, pruner) gives the pattern to follow.

**Impact.** Turns the SE team from stateless to stateful. Every subsequent improvement — learning from failure, cost/quality trending, roadmap grooming, A/B outcomes — becomes expressible because there is finally a persistent product artefact to attach them to. Estimated effort: 2-3 engineer-months for the schema + PO agent + UI; everything downstream is incremental.

---

### Recommendation #2 — Externalise CI/CD and replace the LLM "Integration Agent" with real runtime verification

**Why this is #2.** Today "lint", "build", "QA", and "integration" all happen *inside* the agent loop as function calls against files on disk. `integration_team/agent.py` is a single LLM pass that reads backend and frontend source strings and guesses whether they agree. The `devops_team/` produces deployment artefacts — IaC, CI configs, Helm charts — but nothing runs them; `deployment_dry_run` is literally `helm template`. `ENV_POLICY` in `devops_team/orchestrator.py:44-62` hard-codes the promotion matrix but no agent ever promotes anything. In other words, the pipeline has no way to tell whether the code it shipped would actually run, serve traffic, or talk to its own frontend. This is exactly the class of failure real CI/CD was invented to prevent.

**What to build.**

1. **Real CI on the generated repos.** After `git_setup_agent/` creates `backend/` and `frontend/` repos, seed them with a generated GitHub Actions (or Woodpecker / Drone, if self-hosted is preferred) workflow template living in `devops_team/templates/`. Every per-task `merge to development` now triggers a pipeline that runs: ruff/ng-lint → unit tests → integration tests → SAST (bandit, semgrep) → SCA (pip-audit, npm audit) → secrets scan (gitleaks) → SBOM (syft). The orchestrator *waits* for the pipeline result before allowing the next task to claim a merge slot, via a new `ci_gate` callback that polls the workflow run via the GitHub MCP or a local webhook. On failure, the existing code-review-loop handles the fix instead of the agent's in-process lint.
2. **Replace `IntegrationAgent` with a contract-test runner.** Require the backend to publish an OpenAPI spec (already natural — the backend is a FastAPI app). Generate a Pact/Schemathesis harness under `integration_team/contracts/`; in the Integration phase, boot the backend + frontend containers, run the contract suite, and only pass when real HTTP calls succeed. The LLM agent remains but is demoted to *explaining* failures, not *detecting* them.
3. **Staging & progressive delivery actually executed.** The `deployment_strategy_agent` already emits `rollback_plan`, `rollout strategy (rolling, canary, blue/green)` (`devops_team/deployment_strategy_agent/prompts.py:6-14`). Wire those artefacts to a real target — the existing `docker/sandbox.compose.yml` is a natural staging substrate. Stand up `staging-postgres` + `staging-api` + `staging-ui` services, deploy to them automatically after `all-checks` in `.github/workflows/ci.yml`, run smoke + contract tests, then require a human approval on the PR (`ENV_POLICY["production"]["approval_required"]` already expects it) before the production image is retagged.
4. **Feature flags.** Ship with a default flag provider (Unleash or OpenFeature + a local YAML evaluator). Teach `backend_code_v2_team` and `frontend_code_v2_team` code-gen prompts to wrap every new user-facing story behind a flag; new features default to 0 % rollout and are promoted via the same Sprint Review gate from Recommendation #1.

**Impact.** Turns "the code compiles and an LLM says it looks aligned" into "the code deployed, the frontend talked to the backend over real HTTP, no regressions were observed under canary, a human signed off". This single change fixes the largest correctness gap — false-positive merges — and simultaneously earns the team credibility for the first time that its output is production-shaped.

---

### Recommendation #3 — Add an observability & learning layer: OpenTelemetry + cost/token accounting + DORA metrics + post-mortem feedback loop

**Why this is #3.** The SE team is a black box today. There is no way to answer basic questions: how many LLM tokens did this task burn? Which gate rejects the most code? What is the mean time to recover from an agent crash? Are we getting better or worse week-over-week? `post_mortem.py` appends to a markdown file that no downstream process reads. The `execution_tracker` reports queued/in-progress/completed counts and nothing else. You cannot improve what you cannot see, and you cannot claim "mimics a real SDLC" without the feedback loop a real SDLC runs on.

**What to build.**

1. **Instrument every agent with OpenTelemetry.** One span per agent invocation, attributes: `agent.name`, `task.id`, `job.id`, `phase`, `llm.model`, `llm.input_tokens`, `llm.output_tokens`, `cost.usd`, `outcome`. Extend `llm_service/` so every call wrapper emits these — most of the token data is already there. Export to the Tempo/Jaeger/Loki stack (or, minimally, to Postgres via a new `agent_traces` table).
2. **Cost & budget guards.** Track cumulative `cost.usd` per `job_id`; enforce a configurable per-run budget (`SE_JOB_MAX_COST_USD`). When 80 % is consumed, the orchestrator warns; at 100 %, it stops launching new tasks and emits a structured clarification question asking whether to continue.
3. **DORA-style metrics dashboard.** Compute and expose via a new `/api/se/metrics` endpoint: deployment frequency (merges-to-main / day), lead time for change (task creation → merge), change-failure rate (tasks that re-entered a gate after merge), MTTR (agent-crash to resolution). Ship a minimal Grafana JSON or an Agent-Console tab.
4. **Closed-loop learning.** Every entry in `post_mortems/POST_MORTEMS.md`, every gate rejection, and every prod rollback (from Recommendation #2) is written to a new `learnings` Postgres table with `pattern`, `trigger`, `counter_measure`. At the start of Design, the Tech Lead prompt is augmented with the top-N learnings relevant to the current initiative (retrieved by embedding or keyword). The system gets *measurably better* each sprint instead of repeating yesterday's failures.

**Impact.** Converts the team from *generative* to *operational*. Cost becomes predictable, quality becomes trendable, and — critically — the post-mortem mechanism that already exists but is inert becomes the input signal for the next planning cycle. Combined with Recommendation #1 (something to attach learnings to) and Recommendation #2 (real signals to feed), this is what turns the three recommendations into a system instead of three features.

---

## Closing note

These three changes are deliberately structural and ordered. **#1 gives the team a persistent world model** (backlog, sprints, releases). **#2 gives it a reliable way to verify the world** (real CI, real contract tests, real deployments, real progressive delivery). **#3 gives it the feedback to improve that world over time** (traces, cost, DORA, closed-loop learnings). Ship in that order; each one multiplies the value of the next. Everything else on the backlog — threat modelling, SBOM signing, chaos testing, multi-tenant cost allocation, richer PM-side discovery — slots in cleanly once the three foundations are in place.

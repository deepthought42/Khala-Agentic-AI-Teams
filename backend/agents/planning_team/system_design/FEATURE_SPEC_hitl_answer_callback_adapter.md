# Feature Spec: Planning HITL Answer-Callback Adapter Reconciliation

| Field | Value |
|---|---|
| **Status** | Proposed — pre-implementation plan, no code changes in this document |
| **Created** | 2026-09-08 |
| **Scope** | `planning_team/temporal/answer_signal.py` and its one production call site in `software_engineering_team/temporal/activities.py` |
| **Supersedes** | Nothing. Corrects two stale claims in `planning_hitl_temporal_contract.md` (see Task 3) |

Tasks below use checkbox (`- [ ]`) syntax so an implementer can track them in order.

**Goal:** Close out the `Callable[[list], list]` answer-callback adapter over the durable Planning HITL primitive by reconciling its one divergence from the story contract — the exhausted-budget default path — rather than rebuilding an adapter that already ships.

**Architecture:** `build_temporal_planning_answer_callback` (`planning_team/temporal/answer_signal.py`) presents Planning's existing `answer_callback: Callable[[list], list]` contract while delegating the actual wait to `PlanningAnswerSignalMixin.wait_for_planning_answers` across the activity/workflow boundary, via a `PlanningAnswerPauseSignal` unwound by `plan_project_activity` into `{"outcome": "paused", ...}`. Add one reporting hook so the terminal defaulting round leaves a durable trace on the job record instead of only a worker log line.

**Tech Stack:** Python 3.10+, `temporalio` (`@workflow.signal`, `workflow.wait_condition`), pytest, Ruff (line-length 120)

**Spec:** `system_design/specs/SPEC-024-planning-team-clarification-hitl-contract.md`; team-local contract `backend/agents/planning_team/system_design/planning_hitl_temporal_contract.md`

---

## Finding: the adapter already exists, and it is already wired

Before planning a build, the tree was measured against the story's four acceptance criteria. Three
are already satisfied by merged code; the fourth is the only real work.

| Acceptance criterion | Status | Evidence |
|---|---|---|
| A callable matching `Callable[[list], list]`, delegating to the durable wait mechanism | **Met** | `build_temporal_planning_answer_callback`, `answer_signal.py`; raises `PlanningAnswerPauseSignal`, which `plan_project_activity` (`software_engineering_team/temporal/activities.py`) unwinds into a paused result that `RunTeamWorkflowV2` resolves via `wait_for_planning_answers` |
| `Preconditions:`/`Postconditions:`/`Invariants:` documented per the DbC requirement | **Met** | Full contract docstrings on the factory, both returned closures, `_default_answer`, `_option_confidence`, and every mixin method |
| Line coverage ≥ 90% for the new adapter code | **Met — 100%** | `pytest agents/planning_team/tests/test_temporal_answer_signal.py --cov=planning_team.temporal.answer_signal` → `87 stmts, 0 miss, 100%`, 46 tests passing (the 47th, `test_default_answer_matches_get_default_option_on_the_same_question`, fails only on a local env without `strands-agents`; the package is pinned in `backend/requirements.txt`, so CI exercises it) |
| The adapter never returns a fabricated/default answer | **Not met — deliberately** | `allow_repause=False` returns `matched + [_default_answer(q) for q in missing]` |

Two secondary facts that change the shape of the remaining work:

1. **The divergence is load-bearing, not an oversight.** `RunTeamWorkflowV2`'s Phase 2 pause loop is
   bounded by `MAX_PLANNING_PAUSE_ROUNDS = 8` and dispatches its final round with
   `allow_repause=False` *specifically* so the activity is forced to return a plan. That flag is the
   loop's termination proof. Planning's question ids come straight from model output
   (`product_requirements_analysis_agent.question_processing.parse_open_question`) and a resume
   replays Planning from scratch, so a re-run can mint fresh ids for questions a human already
   answered; without a terminal round that resolves, the loop re-asks forever and PRA's sub-job
   waits out its own `total_timeout`. Deleting `_default_answer` breaks a workflow invariant that is
   documented and tested.
2. **The primitive is no longer unwired.** The team-local contract doc still describes it as
   "deliberately usable by, but not yet used by, any concrete workflow class," and still documents
   the resolved callback as returning `[]` for an unmatched question. Both statements were true when
   written and are false now — the re-pause path and the SE-team wiring both landed since.

So the remaining work is a **contract reconciliation plus one observability gap**, not a build.

---

## The one open decision

The story's contract says the adapter never fabricates. The shipped adapter fabricates exactly once
per run, on an explicitly-bounded final round, and announces it only to a worker log. Something has
to give.

**Recommended — Option A: keep the bounded default, make it auditable, amend the criterion.**

"Never fabricate" was written before it was established that Planning's question ids do not survive
a replay. Given that they don't, the choice on the final round is not *guess vs. wait*; it is
*guess vs. hang until PRA times out*. A guess is the better of the two — but only if the user can
see it. Today they cannot: `_default_answer`'s output flows to
`submit_product_analysis_answers` and the only trace is `logger.warning` inside an activity worker.
The job record, the status API, and the UI all show a plan that looks fully human-answered.

Option A therefore keeps the behaviour and closes the real gap the criterion was reaching for:
every defaulted answer becomes a recorded fact on the job. The criterion is then restated to the
invariant that is actually true and actually worth holding —

> The adapter never fabricates an answer while another pause round remains. It defaults only on a
> round the caller has explicitly declared terminal, and every defaulted question is reported to the
> caller for persistence.

**Rejected — Option B: strict compliance.** Remove `_default_answer`, and have the terminal round
fail the run with an "unanswered clarification questions" error. It never guesses, which is
honest. But `MAX_PLANNING_PAUSE_ROUNDS` is reached only when ids drift — a Planning-side
nondeterminism problem — and Option B bills that to the user as a hard failure after eight rounds of
answering questions by hand. Trading a degraded-but-labelled plan for a dead job is the wrong trade
here. It also requires unwinding `RunTeamWorkflowV2`'s termination invariant and the activity-side
`allow_repause` contract, which is a materially larger change than the story is scoped for.

**If the reviewer picks Option B instead,** Tasks 2 and 4 below are replaced by: delete
`_default_answer`/`_option_confidence` and their six tests, make the terminal round raise a
dedicated non-retryable error, and rewrite `RunTeamWorkflowV2`'s Invariants block and its
`MAX_PLANNING_PAUSE_ROUNDS` rationale comment. Task 1 and Task 3 apply unchanged either way.

---

## Global Constraints

- Never put GitHub issue numbers in code, comments, commit messages, or docs (PR body only)
- Design-by-Contract docstrings (`Preconditions:` / `Postconditions:` / `Invariants:`) on every new
  or changed public function
- Ruff line-length 120; Python 3.10 target
- Coverage ≥ 90% on new/changed code; `answer_signal.py` is at 100% today and must not regress
- No behaviour change to thread mode's `_build_planning_answer_callback`
- The adapter stays PRA-agnostic: it reports defaults, it does not persist them. Job-record writes
  belong to the activity layer.
- No change to the signal name or payload shape fixed by the spec (`submit_planning_answers`,
  `{"resume_token": str, "answers": list}`)

## File map

| File | Role |
|---|---|
| `backend/agents/planning_team/temporal/answer_signal.py` | Add an optional `on_defaulted` reporting hook to `build_temporal_planning_answer_callback`; update the factory's Postconditions |
| `backend/agents/software_engineering_team/temporal/activities.py` | Wire `on_defaulted` in `plan_project_activity` to an `update_job(job_id, defaulted_questions=[...])` write |
| `backend/agents/planning_team/tests/test_temporal_answer_signal.py` | Tests for the hook: fired with the defaulted ids on a terminal round, not fired on a resolving or re-pausing round, a raising hook does not corrupt the return |
| `backend/agents/software_engineering_team/tests/test_temporal_activities.py` | Assert the terminal round persists `defaulted_questions` on the job record |
| `backend/agents/planning_team/system_design/planning_hitl_temporal_contract.md` | Correct the two stale claims; document the terminal-round default and the reporting hook |
| `system_design/specs/SPEC-024-planning-team-clarification-hitl-contract.md` | Append an addendum recording the bounded-default amendment to the never-fabricate rule |

---

### Task 1: Pin the current behaviour before changing it

**Files:** none (verification only)

- [ ] **Step 1:** Run `python3 -m pytest agents/planning_team/tests/test_temporal_answer_signal.py --cov=planning_team.temporal.answer_signal --cov-report=term-missing` from `backend/` and confirm `87 stmts, 0 miss, 100%`. Record the number in the PR body — it is the baseline the change must not regress.
- [ ] **Step 2:** Run the SE-side pause-loop tests (`test_temporal_activities.py -k repause or paused`, `test_temporal_workflows_trace_id.py -k pause`) green before touching anything, so a later failure is attributable.
- [ ] **Step 3:** Confirm no caller outside `plan_project_activity` passes `allow_repause` (a repo-wide grep). If a second caller has appeared, it must be listed in the PR body — the reporting hook has to reach it too, or its defaults stay invisible.

### Task 2: Report defaulted answers out of the adapter

**Files:**
- Modify: `backend/agents/planning_team/temporal/answer_signal.py`

**Interfaces:**
- `build_temporal_planning_answer_callback(resume_token, submitted_answers=None, next_resume_token=None, allow_repause=True, on_defaulted: Optional[Callable[[List[Dict[str, Any]]], None]] = None) -> Callable[[list], list]`

- [ ] **Step 1: Write the failing tests** in `test_temporal_answer_signal.py`:
  - a terminal round (`allow_repause=False`) with two unmatched questions calls `on_defaulted` exactly once, with the two defaulted answer dicts in `missing` order
  - a fully-resolved round never calls it
  - a re-pausing round (`allow_repause=True`, unmatched question) never calls it — it raises first
  - `on_defaulted=None` (the default) behaves exactly as today
  - an `on_defaulted` that raises propagates rather than being swallowed: a reporting hook that
    fails silently reintroduces the invisible-default bug this task exists to close
  - a non-callable `on_defaulted` fails the factory's assertion, matching how `next_resume_token`
    is already validated at construction rather than at the call site
- [ ] **Step 2:** Add the parameter and the assertion; call the hook in `_resolved_cb` immediately before returning the defaulted list, after the existing `logger.warning`.
- [ ] **Step 3:** Rewrite the factory docstring's `allow_repause=False` postcondition to state that defaults are reported to `on_defaulted` when supplied, and add an `Invariants:` line: the adapter never fabricates while another pause round remains.
- [ ] **Step 4:** Re-run coverage; `answer_signal.py` stays at 100%.

### Task 3: Correct the stale contract documentation

**Files:**
- Modify: `backend/agents/planning_team/system_design/planning_hitl_temporal_contract.md`
- Modify: `system_design/specs/SPEC-024-planning-team-clarification-hitl-contract.md`

- [ ] **Step 1:** In the team-local contract, replace the "Scope of this primitive" claim that it is "not yet used by any concrete workflow class" with the actual wiring: `RunTeamWorkflowV2` mixes in `PlanningAnswerSignalMixin` and `plan_project_activity` builds the callback.
- [ ] **Step 2:** Rewrite the "PRA asks more than once" section. Its stated failure mode — the resolved callback returns `[]`, `_on_poll` treats that as "nothing to submit", the workflow never re-pauses — was closed by the re-pause path. It now raises a fresh `PlanningAnswerPauseSignal` on a new token. Keep the *reason* the section exists (multi-round PRA) and describe what actually happens.
- [ ] **Step 3:** Document the terminal round: `allow_repause=False`, what `_default_answer` selects, its deliberate parity with `user_communication.get_default_option`, and where the defaults are now recorded.
- [ ] **Step 4:** Append a dated addendum to the spec recording the amendment: the never-fabricate rule is bounded to non-terminal rounds, with the id-drift rationale and the reporting requirement that replaces it. Do not rewrite the original section — the addendum shows the decision changed and why.

### Task 4: Persist the defaults where a human will see them

**Files:**
- Modify: `backend/agents/software_engineering_team/temporal/activities.py`
- Modify: `backend/agents/software_engineering_team/tests/test_temporal_activities.py`

- [ ] **Step 1: Write the failing test** — a `plan_project_activity` call with `allow_repause=False` and a partially-answered batch leaves `defaulted_questions` on the job record, carrying each defaulted `question_id` and `selected_option_id`.
- [ ] **Step 2:** Pass `on_defaulted=lambda answers: update_job(job_id, defaulted_questions=answers)` at the `build_temporal_planning_answer_callback` call site. Append rather than overwrite if a prior round could already have written the field — verify against `update_job`'s semantics before choosing.
- [ ] **Step 3:** Update the `plan_project_activity` docstring's Postconditions to state that a terminal round records its defaults on the job record.
- [ ] **Step 4:** Run `make lint` and the full `planning_team` + `software_engineering_team` Temporal test suites.

---

## Out of scope

- The durable signal-wait mechanism itself (`PlanningAnswerSignalMixin`) — already merged and tested
- Surfacing `defaulted_questions` in the Angular UI — a follow-on, and worth its own story: a plan
  built partly on machine-chosen answers should say so where the user reads the plan, not only in
  the job JSON
- Any change to thread mode's `_build_planning_answer_callback`
- The `document_production_activity` PRA-checkpoint work the spec describes, which remains unbuilt

## Risks

| Risk | Mitigation |
|---|---|
| Reviewer prefers strict compliance (Option B) | The swap is scoped in "The one open decision" above; Tasks 1 and 3 hold either way |
| `on_defaulted` raising inside a resumed activity fails the round | Deliberate — a silent reporting failure is the bug being fixed. The hook does one `update_job` call; the activity's existing exception path already handles a failed write |
| `defaulted_questions` collides with an existing job-record field | Grep the job-service schema before Step 2 of Task 4; rename to `auto_defaulted_questions` if taken |
| The sibling test story is already satisfied by this module's 46 tests | Say so explicitly in the PR body so it is closed knowingly rather than left open against work that exists |

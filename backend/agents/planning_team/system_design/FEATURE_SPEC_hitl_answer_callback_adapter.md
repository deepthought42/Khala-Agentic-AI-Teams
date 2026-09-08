# Feature Spec: Planning HITL Answer-Callback Adapter Reconciliation

| Field | Value |
|---|---|
| **Status** | Decided and implemented — the decision below is settled and the tasks have been carried out; this document remains the record of what was changed and why |
| **Created** | 2026-09-08 |
| **Scope** | Eight files — see the File map. Production code: `planning_team/temporal/answer_signal.py`, `software_engineering_team/temporal/activities.py`, and `software_engineering_team/api/models.py` + `api/state.py` (the status surface, without which the audit record never leaves the job store) |
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
2. **The primitive is wired — but the path is gated off, so none of it currently executes.**
   The team-local contract doc still describes it as "deliberately usable by, but not yet used by,
   any concrete workflow class," and still documents the resolved callback as returning `[]` for an
   unmatched question. Both statements were true when written and are false now: the re-pause path
   and the SE-team wiring landed since. But "wired" is not "reachable."
   `plan_project_activity` hard-codes `use_product_analysis=False`
   (`software_engineering_team/temporal/activities.py:670`) on the same
   `run_planning_workflow` call that passes the callback, and
   `DocumentProductionAgent.run` invokes `answer_callback` only inside its
   `if use_product_analysis and run_pra and wait_pra:` branch
   (`planning_team/agents/document_production/agent.py:91-94`).
   `orchestrator.py:193` is the only place the callback is consumed, and it sits behind that same
   branch. So on the live `RunTeamWorkflowV2` path the callback is built, passed, and **never
   called**: no pause is ever raised, the bounded loop never iterates, and the terminal default
   never fires. All of it is real, tested code on an unreachable path.

**Read the priority accordingly.** This plan is pre-emptive hygiene on a dark path, not a live-bug
fix. Nothing in production is silently fabricating Planning answers today, because nothing in
production reaches the code that could. The argument for doing it *now* is sequencing: the
observability gap is far cheaper to close while the path is dark than after someone flips
`use_product_analysis` to `True` and the first defaulted plan ships unnoticed. Flipping that gate is
not this plan's work and not its call — but no one should read this document as describing
behaviour users are experiencing.

So the remaining work is a **contract reconciliation plus one observability gap**, not a build.

### Two live signal names, and neither is the one the governing spec mandates

Establish this before reading the constraints below, because it is easy to get wrong — this
document got it wrong in its first draft. Three registrations of the same Planning-HITL concept
exist:

| Registration | Signal name | State |
|---|---|---|
| `RunTeamWorkflowV2` (SE team) via `PlanningAnswerSignalMixin` | `submit_planning_answers` | **Live** — drives the Phase 2 pause loop; `software_engineering_team/api/routes/hitl.py::submit_pending_answers` signals this name |
| `PlanningWorkflow` (Planning team) via `HitlAnswerSignalMixin` | `submit_answers` | **Dormant** — registered, but `run()` never awaits `wait_for_answers`, so no phase arms a pause |
| SPEC-024 §4.1 (repo-root governing spec) | `submit_answers` + a `selected_option_ids` payload extension | **Unimplemented** — `shared/hitl/models.py::AnswerSubmission` still carries only `question_id`/`selected_option_id`/`other_text` |

Two consequences bind this plan:

1. **The shipped wire contract is not the spec's.** SPEC-024 §4.1 mandates
   `@workflow.signal(name="submit_answers")` — with an explicit "why the same name" rationale that
   names `RunTeamWorkflowV2` as the shared-host case — plus the plural `selected_option_ids` field
   for `allow_multiple=True` questions. Neither shipped. An implementer who wires an answers route
   from §4.1 would signal `submit_answers` at a workflow registering only
   `submit_planning_answers`: Temporal records the signal and delivers it to no handler, the
   silent-undeliverable failure §4.3 itself warns about. Task 3 Step 5 writes that divergence down
   so the next implementer cannot walk into it.
2. **`PlanningAnswerSignalMixin` is scheduled for convergence.**
   `shared/hitl/temporal_signal.py` is the shared extraction of the identical handler, buffer
   rules, and wait half; its own docstring records that reconciling the team-local mixin is
   deferred, and hard-forbids composing both on one class (identical private attribute names would
   alias the two signal contracts). Building the `on_defaulted` hook into that mixin would put new
   capability in a file the tracked migration rewrites. It goes on the adapter instead — see the
   constraints.

---

## The decision: Option A (settled 2026-09-08)

The story's contract says the adapter never fabricates. The shipped adapter fabricates exactly once
per run, on an explicitly-bounded final round, and announces it only to a worker log. Something had
to give.

**Decided — Option A: keep the bounded default, make it auditable, amend the criterion.** This is
no longer an open question; the tasks below implement it. Option B is recorded only so the
reasoning behind the choice survives, not as a live alternative.

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

**Not taken — Option B: strict compliance.** Remove `_default_answer`, and have the terminal round
fail the run with an "unanswered clarification questions" error. It never guesses, which is
honest. But `MAX_PLANNING_PAUSE_ROUNDS` is reached only when ids drift — a Planning-side
nondeterminism problem — and Option B bills that to the user as a hard failure after eight rounds of
answering questions by hand. Trading a degraded-but-labelled plan for a dead job is the wrong trade
here. It also requires unwinding `RunTeamWorkflowV2`'s termination invariant and the activity-side
`allow_repause` contract, which is a materially larger change than the story is scoped for.

Had Option B been chosen, Tasks 2 and 4 would have been replaced by: delete
`_default_answer`/`_option_confidence` and their six tests, make the terminal round raise a
dedicated non-retryable error, and rewrite `RunTeamWorkflowV2`'s Invariants block and its
`MAX_PLANNING_PAUSE_ROUNDS` rationale comment. Recorded here so a future reader can tell this was
weighed and declined rather than never considered — reopening it would be a new decision, not a
resumption of this one. **Implement the tasks below as written.**

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
- No change to the signal name or payload shape **as shipped** — `submit_planning_answers` with
  `{"resume_token": str, "answers": list}`, fixed by the team-local contract and
  `answer_signal.py`, *not* by SPEC-024. See "Two live signal names" above: the repo-root spec
  mandates a different contract, and this plan deliberately does not close that gap.
- Do not extend `PlanningAnswerSignalMixin` or its state machine. `shared/hitl/temporal_signal.py`'s
  `HitlAnswerSignalMixin` is the sanctioned shared extraction of that same signal/wait machinery
  (SPEC-024 §4.2's mandatory-extraction decision), and reconciling the team-local mixin onto it is
  tracked follow-up work. New capability here belongs on the **adapter** layer
  (`build_temporal_planning_answer_callback`), which has no shared counterpart and survives that
  migration untouched — not on the signal/wait state machine, which does not.

## File map

| File | Role |
|---|---|
| `backend/agents/planning_team/temporal/answer_signal.py` | Add an optional `on_defaulted` reporting hook to `build_temporal_planning_answer_callback`; update the factory's Postconditions |
| `backend/agents/software_engineering_team/temporal/activities.py` | Wire `on_defaulted` in `plan_project_activity` to an `update_job(job_id, defaulted_questions=[...])` write |
| `backend/agents/planning_team/tests/test_temporal_answer_signal.py` | Tests for the hook: fired with the defaulted ids on a terminal round, not fired on a resolving or re-pausing round, a raising hook propagates rather than being swallowed |
| `backend/agents/software_engineering_team/api/models.py` | Add `defaulted_questions` to `JobStatusResponse` (empty-list default) — without it the persisted value never leaves the job record |
| `backend/agents/software_engineering_team/api/state.py` | Populate `defaulted_questions` in `build_job_status_response`, which assembles an explicit payload dict and drops unlisted keys |
| `backend/agents/software_engineering_team/tests/test_temporal_activities.py` | Assert the terminal round persists `defaulted_questions` on the job record, and that the status response echoes it |
| `backend/agents/planning_team/system_design/planning_hitl_temporal_contract.md` | Correct the two stale claims; document the terminal-round default and the reporting hook |
| `system_design/specs/SPEC-024-planning-team-clarification-hitl-contract.md` | Append an addendum recording two amendments: the bounded-default exception to the never-fabricate rule, and the §4.1 wire-contract divergence (`submit_planning_answers` shipped, `selected_option_ids` did not) |

---

### Task 1: Pin the current behaviour before changing it

**Files:** none (verification only)

- [ ] **Step 1:** Run `python3 -m pytest agents/planning_team/tests/test_temporal_answer_signal.py --cov=planning_team.temporal.answer_signal --cov-report=term-missing` from `backend/` and confirm `87 stmts, 0 miss, 100%`. Record the number in the PR body — it is the baseline the change must not regress.
- [ ] **Step 2:** Run the SE-side pause-loop tests (`test_temporal_activities.py -k repause or paused`, `test_temporal_workflows_trace_id.py -k pause`) green before touching anything, so a later failure is attributable.
- [ ] **Step 3:** Confirm no caller outside `plan_project_activity` passes `allow_repause` (a repo-wide grep). If a second caller has appeared, it must be listed in the PR body — the reporting hook has to reach it too, or its defaults stay invisible.
- [ ] **Step 4:** Re-confirm the gate before writing any code: `plan_project_activity` still passes `use_product_analysis=False`, and `DocumentProductionAgent.run` still reaches `answer_callback` only inside its PRA branch. If either has changed, the path is now live and this work stops being pre-emptive — say so in the PR body, because it changes how urgently the observability gap needs closing.

### Task 2: Report defaulted answers out of the adapter

**Files:**
- Modify: `backend/agents/planning_team/temporal/answer_signal.py`

**Interfaces:**
- `build_temporal_planning_answer_callback(resume_token, submitted_answers=None, next_resume_token=None, allow_repause=True, on_defaulted: Optional[Callable[[List[Dict[str, Any]]], None]] = None) -> Callable[[list], list]`

- [ ] **Step 1: Write the failing tests** in `test_temporal_answer_signal.py`:
  - a terminal round (`allow_repause=False`) with two unmatched questions calls `on_defaulted` once for that batch, with a record per defaulted question in `missing` order, each carrying `question_id`, `question_text`, `selected_option_id` and `selected_option_label`
  - two successive batches on the *same* callback fire the hook twice (the multi-round case above)
  - what the callback RETURNS stays wire-shaped (`question_id`/`selected_option_id`/`other_text`); the enriched context is for the audit record only, since PRA's answers route validates `AnswerSubmission` and an extra key there is a rejected batch
  - a fully-resolved round never calls it
  - a re-pausing round (`allow_repause=True`, unmatched question) never calls it — it raises first
  - `on_defaulted=None` (the default) behaves exactly as today
  - an `on_defaulted` that raises propagates rather than being swallowed: a reporting hook that
    fails silently reintroduces the invisible-default bug this task exists to close
  - a non-callable `on_defaulted` fails the factory's assertion, matching how `next_resume_token`
    is already validated at construction rather than at the call site
- [ ] **Step 2:** Add the parameter and the assertion; call the hook in `_resolved_cb` immediately before returning the defaulted list, after the existing `logger.warning`. Keep every line of this change inside `build_temporal_planning_answer_callback` — do not touch `PlanningAnswerSignalMixin`. The adapter has no counterpart in `shared/hitl/temporal_signal.py`, so it survives the tracked mixin convergence; the state machine does not.
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
- [ ] **Step 5:** In the same addendum, record the wire-contract divergence from §4.1: the shipped signal name is `submit_planning_answers`, not `submit_answers`, and the `selected_option_ids` payload extension was not adopted. State the consequence plainly — a route wired from §4.1 as written signals a name no Planning-path workflow accepts — and point at the tracked convergence work rather than resolving it here. Also note that `PlanningWorkflow`'s `HitlAnswerSignalMixin` registration is dormant, so `submit_answers` has a handler on that workflow type but nothing arming a pause behind it. §4.1 is the section an implementer reads first; it must not send them into an undeliverable signal.

### Task 4: Persist the defaults where a human will see them

**Files:**
- Modify: `backend/agents/software_engineering_team/temporal/activities.py`
- Modify: `backend/agents/software_engineering_team/api/models.py`
- Modify: `backend/agents/software_engineering_team/api/state.py`
- Modify: `backend/agents/software_engineering_team/tests/test_temporal_activities.py`
- Modify: the `build_job_status_response` tests under `software_engineering_team/tests/`

A job-record write on its own is invisible, so it does not satisfy this task's own title.
`JobStatusResponse` (`api/models.py`) carries `pending_questions` and `waiting_for_answers` but no
`defaulted_questions`, and `build_job_status_response` (`api/state.py`) assembles an explicit
payload dict — an unlisted key is dropped, not passed through. Without both changes,
`GET /run-team/{job_id}` never returns the value and the whole "auditable rather than silent"
justification for keeping the default fails. The status API is therefore in scope here; only
*rendering* it in the Angular UI is the follow-on.

- [ ] **Step 1: Write the failing tests** — (a) a `plan_project_activity` call with `allow_repause=False` and a partially-answered batch leaves `defaulted_questions` on the job record, carrying each defaulted `question_id` and `selected_option_id`; (b) `build_job_status_response` echoes that value, and returns an empty list (not `None`, not a missing key) for a job that defaulted nothing.
- [ ] **Step 2:** Pass an `on_defaulted` hook that **accumulates** across calls and writes the whole accumulated list to `defaulted_questions` each time (`update_job` merges top-level, so assigning the key replaces its value).

  **The hook fires once per PRA clarification round, not once per activity execution.** An earlier draft of this step said the opposite and prescribed a plain overwrite; that was wrong, and the correction is the reason this step is spelled out at length. `wait_for_product_analysis_completion`'s `_on_poll` invokes the *same* callback object on every poll while PRA reports `waiting_for_answers`, and PRA's own review loop raises several unrelated clarification rounds with fresh ids. Under `allow_repause=False` nothing raises, so each round is defaulted in turn. A plain overwrite therefore keeps only the last round and silently discards the record of every earlier one — the exact failure this hook exists to prevent, reintroduced by the code meant to close it.

  De-duplicate on **`question_id` AND `question_text` together**, never the id alone: PRA's parser falls back to a positional `q{index}` id, so two unrelated rounds can both call their first question `q0`, and keying on the id would drop the second as a duplicate. This is the identity rule the spec already mandates for retry reconciliation. Last write wins for a genuine repeat, which is the answer most recently submitted.

  Write the full accumulated list rather than appending server-side: a Temporal retry runs a fresh accumulator and rebuilds the field from scratch, so entries are never doubled.
- [ ] **Step 3:** Add `defaulted_questions` to `JobStatusResponse` (defaulting to an empty list, so every existing caller keeps deserializing) and populate it in `build_job_status_response` from the job record. Follow how `pending_questions` is already threaded through both.
- [ ] **Step 4:** Update the `plan_project_activity` docstring's Postconditions to state that a terminal round records its defaults on the job record, and note on `JobStatusResponse` what a non-empty `defaulted_questions` means: these answers were chosen by the system, not by a human.
- [ ] **Step 5:** Run `make lint` and the full `planning_team` + `software_engineering_team` Temporal and API test suites.

---

## Out of scope

- The durable signal-wait mechanism itself (`PlanningAnswerSignalMixin`) — merged and tested, and
  **not settled**: reconciling it onto `shared/hitl/temporal_signal.py`'s `HitlAnswerSignalMixin` is
  tracked follow-up work that this plan neither performs nor blocks. Task 2 stays on the adapter
  layer precisely so it survives that migration
- Converging the three copies of this state machine (`CodingTeamWorkflow`'s inline one,
  `PlanningAnswerSignalMixin`, and the shared `HitlAnswerSignalMixin`) onto one implementation
- Closing the `submit_answers` / `submit_planning_answers` wire-contract divergence itself. Task 3
  Step 5 only *records* it; adopting one name, and the `selected_option_ids` payload extension
  SPEC-024 §4.1 requires, is its own story with a live-history migration to plan
- *Rendering* `defaulted_questions` in the Angular UI — a follow-on worth its own story: a plan built
  partly on machine-chosen answers should say so where the user reads the plan. Returning the field
  from the status API is **not** deferred with it; that is Task 4, because without it there is
  nothing for a UI story to render and the audit trail stops at the job record
- Flipping `use_product_analysis` to `True` in `plan_project_activity`, which is what would make any
  of this path reachable in the first place. That is a product decision with its own blast radius
  (a live PRA sub-job per planning run); this plan deliberately lands ahead of it rather than
  waiting on it
- Any change to thread mode's `_build_planning_answer_callback`
- The `document_production_activity` PRA-checkpoint work the spec describes, which remains unbuilt

## Risks

| Risk | Mitigation |
|---|---|
| Reviewer prefers strict compliance (Option B) | The swap is scoped in "The one open decision" above; Tasks 1 and 3 hold either way |
| `on_defaulted` raising inside a resumed activity fails the round | Deliberate — a silent reporting failure is the bug being fixed. The hook does one `update_job` call; the activity's existing exception path already handles a failed write |
| `defaulted_questions` collides with an existing job-record field | Grep the job-service schema before Step 2 of Task 4; rename to `auto_defaulted_questions` if taken |
| An activity retry re-writes `defaulted_questions` and duplicates the audit entries | Write the whole accumulated list, never append server-side (Task 4 Step 2). A retry runs a fresh accumulator and rebuilds the field deterministically |
| Multiple PRA rounds in one execution overwrite each other's records | Accumulate across hook calls, de-duplicating on `(question_id, question_text)` — the hook fires per round, not per execution (Task 4 Step 2) |
| The audit record names LLM-minted ids for questions nothing else persists | Each record carries the question text and the chosen option's label; the pause envelope holding `pending_questions` is cleared before the replay, so ids alone would be unresolvable |
| The sibling test story is already satisfied by this module's 46 tests | Say so explicitly in the PR body so it is closed knowingly rather than left open against work that exists |

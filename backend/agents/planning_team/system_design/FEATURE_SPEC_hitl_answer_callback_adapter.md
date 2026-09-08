# Feature Spec: Planning HITL Answer-Callback Adapter Reconciliation

| Field | Value |
|---|---|
| **Status** | Decided; tasks carried out on the companion implementation branch `claude/github-issue-7455-impl-bzg4rs`, which lands separately. This document is the record of what was decided and changed, not a work item — but see the note directly below before reading it against this tree |
| **Created** | 2026-09-08 |
| **Scope** | Sixteen files — see the File map, which is the authority; this row summarises it and an earlier revision let the two drift. Production code, in the order the audit record travels: `planning_team/temporal/answer_signal.py` (reports the defaults) → `planning_team/exceptions.py` + `adapters/product_analysis.py` + `orchestrator.py` (carry a failed audit write past three boundaries that would otherwise swallow it, and amend the two public callback docstrings that said a callback must never fabricate) → `software_engineering_team/temporal/activities.py` (accumulates and persists) → `api/models.py` + `api/state.py` (the status surface) → `api/routes/jobs.py` (clears it on a manual resume) → three `user-interface/` files (render it where a person reads the plan). The rest are tests |
| **Supersedes** | Nothing. Corrects two stale claims in `planning_hitl_temporal_contract.md` (see Task 3) |

The task checkboxes below are kept, and checked, to show the order the work was actually done in. Read them as a record of execution rather than as outstanding work — and read the prose sections the same way, including "Read the priority accordingly" below, which is written in the present tense of the decision rather than of this reading.

> **If you are reading this in a tree where the code does not match:** that is merge ordering, not a missing implementation. The record and the code land as two changes against the same base — this document plus its index row, and the implementation on `claude/github-issue-7455-impl-bzg4rs` — and either can merge first. Until the implementation lands, `answer_signal.py` has no `on_defaulted` parameter, `JobStatusResponse` has no `defaulted_questions` field, and the SPEC-024 addendum this record describes does not exist. **Do not build against them from this document alone**; confirm against the tree you are working in.

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

**Read the priority accordingly.** This work was pre-emptive hygiene on a dark path, not a live-bug
fix. Nothing in production is silently fabricating Planning answers today, because nothing in
production reaches the code that could. The argument for doing it *now* is sequencing: the
observability gap is far cheaper to close while the path is dark than after someone flips
`use_product_analysis` to `True` and the first defaulted plan ships unnoticed. Flipping that gate is
not this plan's work and not its call — but no one should read this document as describing
behaviour users are experiencing.

So the work this record covers was a **contract reconciliation plus one observability gap**, not a build.

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

The story's contract says the adapter never fabricates. The shipped adapter fabricates on
explicitly-bounded terminal rounds — one batch per PRA clarification round, so possibly several in a
single run, not once — and announces it only to a worker log. Something had to give.

**Decided — Option A: keep the bounded default, make it auditable, amend the criterion.** This is
no longer an open question; the tasks below implement it. Option B is recorded only so the
reasoning behind the choice survives, not as a live alternative.

"Never fabricate" was written before it was established that Planning's question ids do not survive
a replay. Given that they don't, the choice on the final round is not *guess vs. wait*; it is
*guess vs. hang until PRA times out*. A guess is the better of the two — but only if the user can
see it. Today they cannot: `_default_answer`'s output flows to
`submit_product_analysis_answers` and the only trace is `logger.warning` inside an activity worker.
The job record, the status API, and the UI all show a plan that looks fully human-answered.

Id drift is not the only way to reach the bound, and the earlier drafts of this record that implied
it was were wrong. PRA raises several unrelated clarification rounds per run; eight legitimate
rounds followed by a genuinely new ninth question also arrives at `allow_repause=False`, and the
terminal round then defaults a question the user has never seen. That is a strictly worse case than
drift — drift re-asks something already answered, this invents an answer to something never asked —
and it would be right to pause or fail for it instead, if it could be told apart. It cannot: nothing
in the pause envelope or the callback carries a PRA-side round identifier, and this record already
concedes the same limitation for de-duplication (Task 4 Step 2). Distinguishing the two needs a
round id PRA does not emit, which is the deferred wiring work, not this change. So the terminal
default covers both cases, and the audit record — which is the same for both — is what a reader has
to work from. Worth stating plainly rather than leaving the narrower drift story standing as if it
were the whole justification.

Option A therefore keeps the behaviour and closes the real gap the criterion was reaching for:
every defaulted answer becomes a recorded fact on the job. The criterion is then restated to the
invariant that is actually true and actually worth holding —

> The adapter never fabricates an answer while another pause round remains. It defaults only on a
> round the caller has explicitly declared terminal, and every defaulted question is reported to the
> caller for persistence.

**Not taken — Option B: strict compliance.** Remove `_default_answer`, and have the terminal round
fail the run with an "unanswered clarification questions" error. It never guesses, which is
honest. But `MAX_PLANNING_PAUSE_ROUNDS` is reached largely through Planning-side nondeterminism —
ids that do not survive a replay — and Option B bills that to the user as a hard failure after eight
rounds of answering questions by hand. Trading a degraded-but-labelled plan for a dead job is the
wrong trade here. It also requires unwinding `RunTeamWorkflowV2`'s termination invariant and the activity-side
`allow_repause` contract, which is a materially larger change than the story is scoped for.

Had Option B been chosen, Tasks 2 and 4 would have been replaced by: delete
`_default_answer`/`_option_confidence` and their six tests, make the terminal round raise a
dedicated non-retryable error, and rewrite `RunTeamWorkflowV2`'s Invariants block and its
`MAX_PLANNING_PAUSE_ROUNDS` rationale comment. Recorded here so a future reader can tell this was
weighed and declined rather than never considered — reopening it would be a new decision, not a
resumption of this one. **The tasks below were implemented as written.**

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
| `backend/agents/planning_team/exceptions.py` | Add `PlanningDefaultsNotRecorded` — the type a failed audit write raises so it survives every boundary between the hook and the activity (Task 4 Step 2b) |
| `backend/agents/planning_team/adapters/product_analysis.py` | Widen `poll_until_terminal`'s `passthrough_exceptions` to carry it out of the PRA poll loop |
| `backend/agents/planning_team/orchestrator.py` | Re-raise it ahead of `run_workflow`'s broad `except Exception`, which would otherwise fold it back into a generic planning failure; **and** amend the two public callback docstrings (`resolve_pra_answers`, `run_workflow`) that told callers a callback must never fabricate a default — Task 3 Step 0 |
| `backend/agents/planning_team/tests/test_adapters.py`, `tests/test_orchestrator.py` | Prove it escapes each of those two boundaries, and that an ordinary callback error still folds into a failed status |
| `backend/agents/planning_team/tests/test_agents.py` | Pin what that folded status actually buys: `DocumentProductionAgent.run` logs it and ships a plan anyway, with `validated_spec_path` and `prd_path` both `None` — the fail-open half of the passthrough decision, asserted rather than assumed |
| `backend/agents/software_engineering_team/api/routes/jobs.py` | Clear `defaulted_questions` on `POST /run-team/{job_id}/resume` — a resume reuses the job record and starts a non-terminal run (Task 4 Step 2c) |
| `user-interface/src/app/models/software-engineering.model.ts` | Add `DefaultedQuestion` and the `defaulted_questions` member to `JobStatusResponse` |
| `user-interface/src/app/components/job-status/job-status.component.html`, `run-team-tracking/run-team-tracking.component.html` | Render the defaults where the user watches the run (Task 4 Step 3a) |
| `backend/agents/software_engineering_team/tests/test_temporal_activities.py` | Assert the terminal round persists `defaulted_questions` on the job record, and that the status response echoes it |
| `backend/agents/planning_team/system_design/planning_hitl_temporal_contract.md` | Correct the two stale claims; document the terminal-round default and the reporting hook |
| `system_design/specs/SPEC-024-planning-team-clarification-hitl-contract.md` | Append an addendum recording two amendments: the bounded-default exception to the never-fabricate rule, and the §4.1 wire-contract divergence (`submit_planning_answers` shipped, `selected_option_ids` did not) |

---

### Task 1: Pin the current behaviour before changing it

**Files:** none (verification only)

- [x] **Step 1:** Run `python3 -m pytest agents/planning_team/tests/test_temporal_answer_signal.py --cov=planning_team.temporal.answer_signal --cov-report=term-missing` from `backend/` and confirm `87 stmts, 0 miss, 100%`. Record the number in the PR body — it is the baseline the change must not regress.
- [x] **Step 2:** Run the SE-side pause-loop tests (`test_temporal_activities.py -k 'repause or paused'`, `test_temporal_workflows_trace_id.py -k pause`) green before touching anything, so a later failure is attributable. The quotes are load-bearing: unquoted, the shell hands `or` and `paused` to pytest as paths and the run dies on file-not-found rather than verifying anything.
- [x] **Step 3:** Confirm no caller outside `plan_project_activity` passes `allow_repause` (a repo-wide grep). If a second caller has appeared, it must be listed in the PR body — the reporting hook has to reach it too, or its defaults stay invisible.
- [x] **Step 4:** Re-confirm the gate before writing any code: `plan_project_activity` still passes `use_product_analysis=False`, and `DocumentProductionAgent.run` still reaches `answer_callback` only inside its PRA branch. If either has changed, the path is now live and this work stops being pre-emptive — say so in the PR body, because it changes how urgently the observability gap needs closing.

### Task 2: Report defaulted answers out of the adapter

**Files:**
- Modify: `backend/agents/planning_team/temporal/answer_signal.py`

**Interfaces:**
- `build_temporal_planning_answer_callback(resume_token, submitted_answers=None, next_resume_token=None, allow_repause=True, on_defaulted: Optional[Callable[[List[Dict[str, Any]]], None]] = None) -> Callable[[list], list]`

- [x] **Step 1: Write the failing tests** in `test_temporal_answer_signal.py`:
  - a terminal round (`allow_repause=False`) with two unmatched questions calls `on_defaulted` once for that batch, with a record per defaulted question in `missing` order, each carrying `question_id`, `question_text`, `selected_option_id` and `selected_option_label`
  - two successive batches on the *same* callback fire the hook twice (the multi-round case above)
  - what the callback RETURNS stays wire-shaped (`question_id`/`selected_option_id`/`other_text`); the enriched context is for the audit record only. An earlier draft justified this by saying PRA's answers route *rejects* an extra key — it does not. `shared.hitl.models.AnswerSubmission` sets no `extra="forbid"`, so Pydantic's default silently drops unknown keys. That is a weaker argument for separation but not a worse one: a batch that quietly loses its audit context is harder to notice than one that bounces, so the two shapes stay deliberately apart rather than relying on validation to keep them so
  - a fully-resolved round never calls it
  - a re-pausing round (`allow_repause=True`, unmatched question) never calls it — it raises first
  - `on_defaulted=None` (the default) behaves exactly as today
  - an `on_defaulted` that raises propagates rather than being swallowed: a reporting hook that
    fails silently reintroduces the invisible-default bug this task exists to close. **A direct
    test of the factory is not enough on its own** — it proves only the first hop. Every boundary
    between the hook and the activity needs its own test, or a missed entry in
    `passthrough_exceptions` or in `run_workflow` leaves this list green while the failure folds
    back into a warning. Those live with the boundaries they cover (Task 4 Step 2b), not here
  - a non-callable `on_defaulted` fails the factory's assertion, matching how `next_resume_token`
    is already validated at construction rather than at the call site
- [x] **Step 2:** Add the parameter and the assertion; call the hook in `_resolved_cb` immediately before returning the defaulted list, after the existing `logger.warning`. Keep every line of this change inside `build_temporal_planning_answer_callback` — do not touch `PlanningAnswerSignalMixin`. The adapter has no counterpart in `shared/hitl/temporal_signal.py`, so it survives the tracked mixin convergence; the state machine does not.
- [x] **Step 3:** Rewrite the factory docstring's `allow_repause=False` postcondition to state that defaults are reported to `on_defaulted` when supplied, and add an `Invariants:` line: the adapter never fabricates while another pause round remains.
- [x] **Step 4:** Re-run coverage; `answer_signal.py` stays at 100%.

### Task 3: Correct the stale contract documentation

**Files:**
- Modify: `backend/agents/planning_team/system_design/planning_hitl_temporal_contract.md`
- Modify: `system_design/specs/SPEC-024-planning-team-clarification-hitl-contract.md`
- Modify: `backend/agents/planning_team/orchestrator.py` — the two **runtime** docstrings, not just the design docs

- [x] **Step 0: amend the contract where callers actually read it.** Amending the design documents alone leaves the public API contradicting them. `resolve_pra_answers` describes a callback's result as "user-supplied answers", and `run_workflow`'s contract says outright that a supplied callback "must never fabricate a default" — which is precisely what the durable-HITL adapter now does on a terminal round. A caller reading those docstrings gets the opposite of the shipped rule. Restate both to the bounded version: never fabricate while another round of asking remains; MAY default on a round the caller has explicitly declared terminal; and the price of that permission is that every default is reported for persistence. The file is already being modified for the exception passthrough, so this costs nothing extra to include and everything to omit.

- [x] **Step 1:** In the team-local contract, replace the "Scope of this primitive" claim that it is "not yet used by any concrete workflow class" with the actual wiring: `RunTeamWorkflowV2` mixes in `PlanningAnswerSignalMixin` and `plan_project_activity` builds the callback.
- [x] **Step 2:** Rewrite the "PRA asks more than once" section. Its stated failure mode — the resolved callback returns `[]`, `_on_poll` treats that as "nothing to submit", the workflow never re-pauses — was closed by the re-pause path. It now raises a fresh `PlanningAnswerPauseSignal` on a new token. Keep the *reason* the section exists (multi-round PRA) and describe what actually happens.
- [x] **Step 3:** Document the terminal round: `allow_repause=False`, what `_default_answer` selects, its deliberate parity with `user_communication.get_default_option`, and where the defaults are now recorded.
- [x] **Step 4:** Append a dated addendum to the spec recording the amendment: the never-fabricate rule is bounded to non-terminal rounds, with the id-drift rationale and the reporting requirement that replaces it. Do not rewrite the original section — the addendum shows the decision changed and why.
- [x] **Step 5:** In the same addendum, record the wire-contract divergence from §4.1: the shipped signal name is `submit_planning_answers`, not `submit_answers`, and the `selected_option_ids` payload extension was not adopted. State the consequence plainly — a route wired from §4.1 as written signals a name no Planning-path workflow accepts — and point at the tracked convergence work rather than resolving it here. Also note that `PlanningWorkflow`'s `HitlAnswerSignalMixin` registration is dormant, so `submit_answers` has a handler on that workflow type but nothing arming a pause behind it. §4.1 is the section an implementer reads first; it must not send them into an undeliverable signal.

### Task 4: Persist the defaults where a human will see them

**Files:**
- Modify: `backend/agents/software_engineering_team/temporal/activities.py`
- Modify: `backend/agents/software_engineering_team/api/models.py`
- Modify: `backend/agents/software_engineering_team/api/state.py`
- Modify: `backend/agents/software_engineering_team/api/routes/jobs.py`
- Modify: `backend/agents/software_engineering_team/tests/test_temporal_activities.py`, `tests/test_api.py`
- Modify: the `build_job_status_response` tests under `software_engineering_team/tests/`
- Modify: `user-interface/src/app/models/software-engineering.model.ts`
- Modify: `user-interface/src/app/components/job-status/job-status.component.html` and its spec
- Modify: `user-interface/src/app/components/run-team-tracking/run-team-tracking.component.html` and `run-team-tracking-view-model.spec.ts`

A job-record write on its own is invisible, so it does not satisfy this task's own title.
`JobStatusResponse` (`api/models.py`) carries `pending_questions` and `waiting_for_answers` but no
`defaulted_questions`, and `build_job_status_response` (`api/state.py`) assembles an explicit
payload dict — an unlisted key is dropped, not passed through. Without both changes,
`GET /run-team/{job_id}` never returns the value and the whole "auditable rather than silent"
justification for keeping the default fails.

**The same argument does not stop at the API, and an earlier draft of this task deferred the UI as
if it did.** Option A's case rests on "a guess is better than a hang, but only if the user can see
it" — and the user reads a run in the Angular tracking view, not in a JSON response. A field
returned by an endpoint nothing renders is the job-record problem moved one hop and re-labelled as
someone else's story. The UI is therefore in scope here too (Step 3a), for exactly the reason the
paragraph above gives for the API.

- [x] **Step 1: Write the failing tests** — (a) a `plan_project_activity` call with `allow_repause=False` and a partially-answered batch leaves `defaulted_questions` on the job record, carrying each defaulted `question_id` and `selected_option_id`; (b) `build_job_status_response` echoes that value, and returns an empty list (not `None`, not a missing key) for a job that defaulted nothing.
- [x] **Step 2:** Pass an `on_defaulted` hook that **accumulates** across calls and writes the whole accumulated list to `defaulted_questions` each time (`update_job` merges top-level, so assigning the key replaces its value).

  **The hook fires once per PRA clarification round, not once per activity execution.** An earlier draft of this step said the opposite and prescribed a plain overwrite; that was wrong, and the correction is the reason this step is spelled out at length. `wait_for_product_analysis_completion`'s `_on_poll` invokes the *same* callback object on every poll while PRA reports `waiting_for_answers`, and PRA's own review loop raises several unrelated clarification rounds with fresh ids. Under `allow_repause=False` nothing raises, so each round is defaulted in turn. A plain overwrite therefore keeps only the last round and silently discards the record of every earlier one — the exact failure this hook exists to prevent, reintroduced by the code meant to close it.

  De-duplicate on the **whole record** — `question_id`, `question_text`, `selected_option_id` and `selected_option_label` together. An earlier draft of this step said `(question_id, question_text)` and cited the spec as mandating it; that citation was to a draft SPEC-024 itself withdrew. Risk 3 of that spec requires the full canonical question shape and says so **in correction of** an earlier draft naming exactly that pair. PRA's parser defaults both `id` and `question_text` identically across separate rounds, so the pair collapses two unrelated rounds differing only in their options — discarding a real audit event.

  The whole record is not the full canonical shape either: the audit entry is a narrower object than the pending-question dict, and audit de-duplication is a different operation from retry reconciliation. Say that in the docstring rather than claiming spec cover the change does not have, and record the residual limitation the spec concedes for its own case — without a PRA-side round identifier, nothing distinguishes a re-presented question from a coincidentally identical later round. De-duplication is still required (`_on_poll` re-presents an unanswered batch every poll, so one question would otherwise inflate into a row per poll), so accept the collision knowingly.

  Write the full accumulated list rather than appending server-side: a **serialized** Temporal retry runs a fresh accumulator and rebuilds the field from scratch, so entries are never doubled.

  **That idempotency holds only while attempts do not overlap, and this activity can make them overlap.** The workflow schedules `plan_project_activity` with `heartbeat_timeout=5m` (`software_engineering_team/temporal/workflows.py`, both call sites) under a `maximum_attempts=3` retry policy, and nothing in the activity ever calls `activity.heartbeat()` — the only heartbeat machinery in that module belongs to `execute_coding_team_activity`. A Planning run longer than five minutes is therefore timed out server-side and retried while the original synchronous attempt keeps running, unable to observe the cancellation it never polls for. Two attempts then hold independent accumulators, and the loser's clear-and-rewrite can land last and erase the audit for the plan Temporal accepts.

  This is **not caused by this change** and is not fixed by it: every `update_job` in that activity — `pending_questions`, `waiting_for_answers`, `resume_token`, `phase`, `requirements_title` — has the identical exposure, and has had it since the activity was written. `defaulted_questions` is one more passenger. Fencing this single write would buy a false sense of safety over a field-by-field race, so the honest move is to record the hazard where the idempotency claim used to sit and name the real fix: make the activity heartbeat, the way the coding activity already does. That is its own change with its own blast radius (it changes liveness semantics for every long Planning run), and it is listed under Out of scope.

- [x] **Step 2a — clear the field at the start of a terminal attempt.** The hook only ever writes, and the activity is retryable. An attempt that records defaults then fails leaves the pause envelope already consumed, so the retry replays Planning fresh; if that replay matches every question the hook never fires, and the job keeps the failed attempt's records while shipping a plan that was fully human-answered. Over-reporting is the gentler error, but it is the one that teaches readers to distrust the field.
- [x] **Step 2b — make a failed audit write actually stop the round.** Leaving the hook unguarded is *not* sufficient, and assuming it is was a real defect: `poll_until_terminal` folds any `on_poll` exception outside its `passthrough_exceptions` into a failed status, `DocumentProductionAgent.run` logs that and carries on producing a plan, and `run_workflow`'s broad `except Exception` would fold it again even after it escaped the poll loop. Three boundaries, each turning the failure into a warning. A dedicated `PlanningDefaultsNotRecorded` in `planning_team/exceptions.py`, passed through by the poll loop and by `run_workflow`, is what makes the failure reach the activity — the mirror image of `PlanningAnswerPauseSignal`'s treatment. Keep the passthrough narrow: an ordinary callback error must still fold into a failed PRA status. **Do not call that fail-closed** — an earlier revision of this step did, and it is wrong. `DocumentProductionAgent.run` logs the failed status and carries on producing a plan, so an ordinary callback error is fail-**open** at the system level: the run proceeds without PRA, and on the `use_product_analysis=True` path it does not even fall back to the initial spec, since that assignment belongs to the `False` branch — `validated_spec_path` and `prd_path` both stay `None`. Narrowing the passthrough is a decision not to disturb that long-standing fallback, not a claim that the fallback stops anything. Widening it to every callback error would change behaviour for every PRA failure, well outside this change's blast radius. So: document the fallback and pin it with a test (`test_document_production_agent_carries_on_past_a_failed_pra`) rather than leaving a passing "folds into a failed status" test to imply the failure was contained.
- [x] **Step 2c — clear the field on the manual resume route too.** Step 2a covers a Temporal retry of a terminal attempt; it does not cover `POST /run-team/{job_id}/resume`, which reuses the same job record and starts a **fresh** workflow whose first planning attempt is not terminal. A run that records defaults, fails, and is then resumed can complete Planning without ever entering another terminal attempt — nothing rewrites the field, and the dead attempt's machine-chosen answers end up attached to a plan that was fully human-answered. Add `defaulted_questions=[]` to the `update_job` that already wipes `error`, `agent_crash_details` and `current_activity` for the same reason. `POST .../restart` needs no equivalent and a test should pin why: `reset_job` calls `replace_job`, so the whole record goes rather than merging.
- [x] **Step 3:** Add `defaulted_questions` to `JobStatusResponse` (defaulting to an empty list, so every existing caller keeps deserializing) and populate it in `build_job_status_response` from the job record. Follow how `pending_questions` is already threaded through both.
- [x] **Step 3a — render it.** Add `DefaultedQuestion` and a `defaulted_questions` member to the UI's `JobStatusResponse`, and a collapsed panel in both surfaces that show a run (`job-status` and `run-team-tracking`), mirroring how `failed_tasks` is already presented. Three properties the tests must hold: the panel names the questions and the chosen option **labels**, not bare ids (the ids are LLM-minted and mean nothing to a reader); every field but `question_id` is nullable, so a missing text or option falls back rather than rendering `null` as though it were an answer; and the panel is absent, not empty, when nothing was defaulted — an always-visible "0 defaulted" row teaches readers to skip it, which is the one failure mode a disclosure panel cannot afford.
- [x] **Step 4:** Update the `plan_project_activity` docstring's Postconditions to state that a terminal round records its defaults on the job record, and note on `JobStatusResponse` what a non-empty `defaulted_questions` means: these answers were chosen by the system, not by a human.
- [x] **Step 5:** Run `make lint` and the full `planning_team` + `software_engineering_team` Temporal and API test suites.

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
- Flipping `use_product_analysis` to `True` in `plan_project_activity`, which is what would make any
  of this path reachable in the first place. That is a product decision with its own blast radius
  (a live PRA sub-job per planning run); this plan deliberately lands ahead of it rather than
  waiting on it
- Making `plan_project_activity` heartbeat. It carries a 5-minute `heartbeat_timeout` and never calls `activity.heartbeat()`, so any Planning run over five minutes is retried while the first attempt is still running — which is what makes two attempts able to clobber each other's job-record writes, `defaulted_questions` among them. Pre-existing, affecting every field that activity writes, and the fix (a background beater like `execute_coding_team_activity`'s) changes liveness semantics for every long Planning run. Its own story; recorded here so the audit record's retry-safety claim is not read as broader than it is
- Any change to thread mode's `_build_planning_answer_callback`
- The `document_production_activity` PRA-checkpoint work the spec describes, which remains unbuilt

## Risks

| Risk | Mitigation |
|---|---|
| Reviewer prefers strict compliance (Option B) | The swap is scoped in "The one open decision" above; Tasks 1 and 3 hold either way |
| `on_defaulted` raising inside a resumed activity fails the round | Deliberate — a silent reporting failure is the bug being fixed. Leaving the hook unguarded is **not** what achieves it, and an earlier draft of this row said it was: three boundaries between the hook and the activity each turn a plain raise into a warning. The failure reaches the activity only as `PlanningDefaultsNotRecorded`, which both the PRA poll loop and `run_workflow` pass through (Step 2b) |
| `defaulted_questions` collides with an existing job-record field | Grep the job-service schema before Step 2 of Task 4; rename to `auto_defaulted_questions` if taken |
| A **serialized** activity retry re-writes `defaulted_questions` and duplicates the audit entries | Write the whole accumulated list, never append server-side (Task 4 Step 2). A retry runs a fresh accumulator and rebuilds the field deterministically |
| Two **overlapping** attempts clobber each other's audit | Not mitigated, and not this change's to mitigate. `plan_project_activity` carries a 5-minute `heartbeat_timeout` and never heartbeats, so a long Planning run is retried while the first attempt is still going; every field that activity writes has the same exposure. Recorded in Task 4 Step 2 and in the hook's docstring rather than papered over by an idempotency claim that assumes serialization. The fix is to make the activity heartbeat — Out of scope |
| Multiple PRA rounds in one execution overwrite each other's records | Accumulate across hook calls, de-duplicating on the **whole audit record** — `question_id`, `question_text`, `selected_option_id` and `selected_option_label` together — because the hook fires per round, not per execution (Task 4 Step 2). Not the `(question_id, question_text)` pair an earlier draft of this row named: PRA's parser defaults both identically across rounds, so that pair collapses two unrelated rounds differing only in their options |
| The audit record names LLM-minted ids for questions nothing else persists | Each record carries the question text and the chosen option's label; the pause envelope holding `pending_questions` is cleared before the replay, so ids alone would be unresolvable |
| The record is read as proof the defaults shaped the plan | It is not. The hook fires before `_on_poll` POSTs the batch, and `_on_poll` ignores the result, so a rejected submission is indistinguishable from an applied one — a gap the team contract already tracks as deferred wiring work. The field description states the narrower claim: chosen and submitted, not confirmed applied. Coordinating the record with a confirmed submission belongs to that deferred work, not here |
| A terminal attempt's failure leaves a half-written record behind | Clear the field at the start of a terminal attempt (Step 2a), inside the activity's error boundary so a failed clear is recorded as a job failure rather than escaping unhandled on the final attempt |
| A manual resume carries a dead attempt's defaults onto a fresh, fully-answered plan | The resume route clears the field alongside the other dead-attempt state it already wipes (Step 2c); `restart` is covered by `reset_job` replacing the record outright, pinned by its own test |
| A failed audit write degrades into a logged warning | Raise a type all three boundaries pass through (Step 2b) |
| The sibling test story is already satisfied by this module's 46 tests | Say so explicitly in the PR body so it is closed knowingly rather than left open against work that exists |

# Surface the Structurally-Starved Finding to the Design Reviewer — Implementation Plan

**Goal:** The design-loop reviewer receives the `PredicateReachabilityProbe`'s
**structurally-starved** finding as part of its deterministic findings each
round, merged through the *same* path the hypothesis/rules consistency finding
already uses (`_review_and_handle_critique`), not a parallel delivery mechanism.

**Scope:** Step 1 of 3 for "wire the structurally-starved finding into the
design-loop reviewer". Reviewer adjudication / no-hard-block preservation
(step 2) and the end-to-end integration test (step 3) are separate stories;
this plan stops where they begin, but notes where each will attach.

**Tech Stack:** Python 3.10+, Pydantic v2, pytest, ruff (line-length 120).

---

## The gap this plan actually has to close

The issue reads as a two-line merge — `reviewer_findings = readiness + hypothesis`
becomes `readiness + hypothesis + starvation`. It is not, and the reason is worth
stating before the tasks:

| Finding | Inputs it needs | Available in the design loop? |
|---|---|---|
| `check_hypothesis_rules(spec)` | the spec alone | yes |
| `probe_starvation(spec, market_data)` | the spec **plus real fetched bars** | **no** |

The design loop is a data-free phase today. Market data is fetched in
`orchestrator_synthesis._fetch_market_data_for_synthesis`, *after* design has
readied. Two existing tests encode that separation as an invariant —
`test_never_ready_short_circuits_with_design_not_ready` and the budget-exhaustion
test both patch `StrategyLabOrchestrator._fetch_market_data` with
`_market_must_not_run`, using "market data was never fetched" as the proxy for
"the synthesis loop was never entered".

So the work is: **give the design loop a narrow, fail-open, flag-gated read of
the same bars, without weakening that invariant** — then the merge really is two
lines.

### Why the added fetch is affordable

- It runs **only on the reviewer branch** of `_review_and_handle_critique`
  (`deterministic_ready is True`). A spec that never passes the readiness gate
  never triggers a fetch, so the design loop's cheap-rejection path stays free.
- It fetches **the same `(symbols, asset_class, start, end, as_of)` key synthesis
  will fetch**, and `MarketDataService` is backed by a durable content-hashed
  Parquet cache. On the happy path the synthesis fetch that follows is a cache
  hit — the fetch is *moved earlier*, not duplicated.
- Net new cost is limited to specs that pass readiness, get reviewed, and then
  never reach synthesis.
- A per-attempt memo plus a probe-signature memo keeps repeat rounds free when
  the reviser returns reachability-equivalent rules.

---

## Design decisions

**D1 — A separate fetch seam on `DesignMixin`, not `_fetch_market_data`.**
Add `_fetch_design_probe_bars(spec, config) -> Optional[Dict[str, List[OHLCVBar]]]`
to `orchestrator_design.py`. It reuses `resolve_strategy_symbols` +
`fetch_multi_symbol_range` but returns bare bars, not the `_MarketDataFetch`
audit envelope — design records no requested-vs-fetched audit trail or
`provider_used` snapshot, so the envelope is dead weight there. The separate seam
is justified on its own merits *and* it leaves the two "synthesis was not
entered" tests meaning exactly what they say. Their comments get one clarifying
line so a future reader does not mistake the design probe for a loophole.

It belongs on the mixin, not the base class. `MIXIN_BOUNDARIES.md` reserves
`orchestrator.py` for "helpers genuinely used by two or more mixins" and assigns
the whole per-design-attempt orchestration to `DesignMixin`; this seam has
exactly one consumer, `_design_starvation_findings`, in that mixin. Keeping it
there also keeps all of Task 1 in one file and leaves the seam patchable through
`StrategyLabOrchestrator` exactly as before — `monkeypatch.setattr` on the
subclass shadows the mixin's attribute, which is all the conftest stub and the
fail-open tests need.

**D2 — Merge only `starved` verdicts, drop the abstention `info`s.**
`to_starvation_gate_results` emits `info` findings for `abstained_bars` /
`abstained_thin` so the *gate timeline* can distinguish "abstained" from
"checked, nothing found". The reviewer prompt is a different consumer with a
different requirement: *"a round with no starved rules delivers findings exactly
as today."* Two extra `info` lines on every clean spec would violate that and
dilute the prompt. Filter on `verdict == "starved"` (not on severity — severity
is a compiled-vs-custom proxy; the verdict is the intent) before rendering.

**D3 — Do not record the design-phase starvation findings on `all_gate_results`.**
The hypothesis merge does not record either: `reviewer_findings` is a *fresh*
list, leaving `readiness_results` untouched for the memoization and recording
paths. Recording would double-report against the synthesis-phase starvation
gates already on the timeline. Reviewer delivery is the whole ask.

**D4 — Fail open, everywhere, at two layers.** No symbols, no bars, a fetch
exception, a probe exception, fewer than two entry rules, or the flag off ⇒
empty list ⇒ the reviewer sees exactly today's findings. `probe_starvation`
already returns `[]` for falsy `market_data` and for `len(entry_rules) < 2`, so
some of this is free. The rest needs a guard in *both* places, mirroring
`_readiness_price_provider` and `_compute_regime_summary`: inside
`_fetch_design_probe_bars` for a failing fetch, and around the whole
fetch-probe-render sequence in `_design_starvation_findings` for a failure of
the seam or the probe itself. One layer is not enough — a guard inside the seam
cannot catch the seam being unavailable, and a diagnostic that can abort a
design cycle is worse than no diagnostic.

**D5 — `STRATEGY_LAB_DESIGN_STARVATION_PROBE_ENABLED`, default `true`.**
Matches `STRATEGY_LAB_MECHANICAL_REPAIR_ENABLED` / `STRATEGY_LAB_REGIME_SUMMARY_ENABLED`
via `_env_flag`. The flag is the operator's escape hatch for the added design-time
fetch — the one genuinely new cost in this change.

**D6 — Optional keyword args, not required ones.**
`_review_and_handle_critique` gains `config` and `starvation_cache`, both
defaulting to `None` ("no probe"). Production always passes both; direct-call
tests in `test_strategy_lab_design_review_helpers.py` keep working unchanged.
This is the same accepted-`None`-for-test-invocation pattern
`_validate_and_memoize_readiness` uses for `pinned_asset_class`.

**D7 — No behavioural change to the reviewer's verdict in this step.**
The merged finding travels `reviewer_findings` → `DesignReviewAgent.run` →
`_format_readiness` → the prompt's readiness block, and is snapshotted onto
`SpecCritique.readiness_findings`.

Mind the name collision when reading that flow: `readiness_results` is *both*
the orchestrator's local list — which D3 pins as untouched — and the name of
`DesignReviewAgent.run`'s second parameter, which receives the fresh
`reviewer_findings` list. The starvation finding only ever enters through the
parameter. Nothing writes it into the orchestrator's `readiness_results`, and
nothing should: that list feeds the readiness memoization and the gate-recording
paths, and D3 keeps it clean.

`_coerce_critique` derives `ready` from the reviewer's own `issues`, never from
the deterministic findings — but that alone does **not** make the merge
behaviourally inert, and an earlier draft of this plan wrongly claimed it did.
See D8.

**D8 — Merge the finding at `warning` on the design path; never `critical`.**
The reviewer's system prompt (`agents/design_review.py`, the response-contract
block) states:

> `ready=true` ONLY when no deterministic finding is critical AND you cannot
> identify a substantive defect.

So the prompt, not `_coerce_critique`, is what a `critical` deterministic finding
acts through. `to_starvation_gate_results` emits `critical` for a starved rule on
the compiled path — merge that verbatim and a compliant reviewer is instructed to
return `ready=false` even for a deliberate narrow-then-broad priority ordering it
would otherwise accept. The design loop would then revise or churn to the round
cap on a spec that was never defective: precisely the hard-block churn this whole
line of work exists to avoid.

The merge therefore demotes a starved verdict to `warning` on the design path.
This is not a workaround for the prompt rule, it is the correct severity for this
consumer:

- `critical` in this codebase means *the deterministic gate has already decided*.
  On the synthesis gate timeline that is exactly right — a starved rule provably
  contributes zero entries on that data, and nothing downstream is asked to
  weigh it. Those synthesis-phase findings keep `critical` and are untouched.
- The reason to show the reviewer at all is that a deliberate priority ordering
  is legitimate and only a judge can tell the two apart. A finding presented for
  adjudication must not also instruct the judge how to rule. `warning` puts it in
  front of the reviewer with full evidence and leaves the verdict open — which
  is what the finding's own wording already assumes when it offers the three
  resolutions (fold, reorder, loosen).

Nothing mechanical is tripped by a `warning` here: `_coerce_critique`'s
`demote_min_severity` reads the reviewer's own returned `issues`, not the
deterministic findings rendered into the prompt.

The considered alternative was to ship this step with the flag defaulting to
`false` and let the adjudication step flip it. Rejected: it would leave the
delivery path dark in production, so the first round of real traffic through it
would arrive with the adjudication change rather than before it, and the step's
own acceptance criterion — the reviewer receives the finding each round — would
not actually hold. Demoting the severity is a smaller, testable change that
keeps the step honest. The follow-up adjudication step still owns pinning the
no-hard-block behaviour with its own test; this step's job is not to break it.

---

## Global constraints

- Design-by-Contract docstrings (`Preconditions:` / `Postconditions:` /
  `Invariants:` where relevant) on every new function and method.
- Never put GitHub issue numbers in code, comments, docstrings, commit messages,
  or docs — PR body only.
- Ruff line-length 120, Python 3.10 target; `make lint` clean.
- ≥ 90% line coverage on new/changed code.
- No network in tests: the new fetch seam is stubbed by an autouse conftest
  fixture (Task 4).

---

## File map

| File | Role |
|---|---|
| `strategy_lab/orchestrator_design.py` | **Add** `_fetch_design_probe_bars` on `DesignMixin`; reset its per-attempt memo in `_run_design_attempt`; **add** `_design_starvation_probe_enabled()`, `_starvation_probe_signature()`, `_StarvationProbeCache`, `_design_starvation_findings()`; thread `config` + cache through `_run_design_review_rounds` → `_review_and_handle_critique`; extend the one merge expression |
| `investment_team/tests/conftest.py` | **Add** autouse fixture stubbing `_fetch_design_probe_bars` → `None` so the existing suite stays hermetic |
| `investment_team/tests/test_strategy_lab_design_loop.py` | Reviewer-receives-the-finding test; no-starved-rules-unchanged test; flag-off test; clarify the two `_market_must_not_run` comments |
| `investment_team/tests/test_strategy_lab_design_review_helpers.py` | Direct-call unit tests for the merge and the memo |
| `strategy_lab/FAITHFUL_EXECUTION.md` | Extend §6 — the starvation finding is surfaced to the reviewer, same path as hypothesis/rules |
| `strategy_lab/README.md` | Document `STRATEGY_LAB_DESIGN_STARVATION_PROBE_ENABLED` |

---

### Task 1: The design-time bars seam

**File:** `backend/agents/investment_team/strategy_lab/orchestrator_design.py`
(both steps — the seam is `DesignMixin`'s, per D1)

- [ ] **Step 1.1** — Add `_fetch_design_probe_bars(self, spec, config) -> Optional[Dict[str, List[OHLCVBar]]]`
      to `DesignMixin`, modelled on `orchestrator.py`'s `_fetch_market_data`
      but keeping only what the probe needs:
  - resolve symbols via `self.market_data_service.resolve_strategy_symbols(spec)`;
    empty ⇒ `None`;
  - `as_of = (getattr(spec, "audit", None) and spec.audit.data_snapshot_id) or None`
    — byte-identical to `_fetch_market_data`, so the durable cache key matches
    and synthesis's later fetch hits it;
  - memo on `(tuple(symbols), spec.asset_class, config.start_date, config.end_date, as_of)`
    in a lazily-created `self._design_probe_bars_cache`, mirroring
    `_benchmark_bars_cache` (an exception is **not** cached);
  - wrap the fetch in `try` / `except Exception` → `logger.debug(...)` → `None`.
    A design-time diagnostic must never crash or stall a cycle.
  - Docstring states the invariant explicitly: *this is not the synthesis fetch
    path; `_fetch_market_data` remains synthesis-only and remains the marker
    tests use for "synthesis was entered".*

- [ ] **Step 1.2** — Reset `self._design_probe_bars_cache = {}` in
      `_run_design_attempt` (same file, `DesignMixin`), beside the existing
      `self._consecutive_spec_mutation_rounds = {}` and
      `self._benchmark_bars_cache = {}` resets around lines 1573-1583.
      Without the reset, bars leak across design attempts.

### Task 2: Probe helpers in the design orchestrator

**File:** `backend/agents/investment_team/strategy_lab/orchestrator_design.py`

- [ ] **Step 2.1** — `_design_starvation_probe_enabled() -> bool`, returning
      `_env_flag("STRATEGY_LAB_DESIGN_STARVATION_PROBE_ENABLED")`, placed with
      the other flag helpers.
- [ ] **Step 2.2** — `_starvation_probe_signature(spec) -> tuple`:
      `(tuple(r.model_dump_json() for r in spec.entry_rules), bool(spec.requires_custom_code),
      spec.asset_class, tuple(spec.target_symbols),
      (getattr(spec, "audit", None) and spec.audit.data_snapshot_id) or None)`.

      It extends synthesis's `(entry_rules, requires_custom_code)` key with every
      remaining component of Step 1.1's bars key, because — unlike synthesis —
      the design loop can change which bars the verdict is computed against
      between rounds. That is why `as_of` is in the signature even though
      `build_spec_from_dict` never sets `audit` and the snapshot id is expected
      to be constant for the attempt: relying on that expectation would leave the
      memo correct only by an invariant this plan cannot prove, and the cost of
      not relying on it is one tuple element. `config.start_date` /
      `config.end_date` are the bars key's only other members and are fixed for
      the attempt, so they are deliberately omitted.

      The rule to carry forward: the probe signature must cover every input the
      verdict depends on — the rules *and* the bars they are judged against.
- [ ] **Step 2.3** — `@dataclass class _StarvationProbeCache: signature: Optional[tuple] = None;
      findings: List[QualityGateResult] = field(default_factory=list)`.
      Mutable holder so the memo survives rounds without widening
      `_review_and_handle_critique`'s return tuple (its 3-tuple shape has direct-call tests).
- [ ] **Step 2.4** — `_design_starvation_findings(self, *, spec, config, cache) -> List[QualityGateResult]`:
      flag off / `config is None` / `cache is None` ⇒ `[]`; signature unchanged ⇒
      `cache.findings`; otherwise fetch bars, `probe_starvation`, filter to
      `verdict == "starved"` (D2), render with
      `to_starvation_gate_results(..., phase="design")`, **demote any `critical`
      result to `warning`** (D8 — a `critical` deterministic finding instructs
      the reviewer to return `ready=false`, which would hard-block a deliberate
      priority ordering), store on the cache, return.
      `"design"` is a valid `StrategyLabPhase` literal — no models change needed.

      Two contract details this helper must get right, both of them easy to get
      wrong and both pinned by tests in Task 5:

      1. **An outer `try` / `except Exception` → `logger.debug(...)` → `[]` wraps
         the fetch, the probe and the render.** Step 1.1's guard sits *inside*
         `_fetch_design_probe_bars` and so cannot catch a failure of the seam
         itself, nor one raised by `probe_starvation` /
         `to_starvation_gate_results` on a spec shape they did not expect.
         A design-time diagnostic must never abort a cycle, so the guard belongs
         at both layers.
      2. **Write `cache.signature` only after bars were obtained and probed.**
         `None` bars — the fail-open return of a transient fetch error — must
         return `[]` *without* touching the cache. Storing an empty findings
         list under the current signature would make the next
         reachability-equivalent round serve that empty result instead of
         retrying, caching the very exception Step 1.1 promises not to cache.

### Task 3: The merge

**File:** `backend/agents/investment_team/strategy_lab/orchestrator_design.py`

- [ ] **Step 3.1** — `_review_and_handle_critique` gains
      `config: Optional[BacktestConfig] = None` and
      `starvation_cache: Optional[_StarvationProbeCache] = None` (D6),
      documented as "production always supplies both; `None` disables the probe".
- [ ] **Step 3.2** — Inside the `if deterministic_ready:` branch, extend the single
      existing merge expression — one list, one path:

      ```python
      reviewer_findings = (
          list(readiness_results)
          + self.strategy_validator.check_hypothesis_rules(spec, phase="design")
          + self._design_starvation_findings(spec=spec, config=config, cache=starvation_cache)
      )
      ```

      Extend the surrounding comment to say why starvation joins the same merge:
      one reviewer, one set of deterministic findings — a second delivery path
      would make what the reviewer saw depend on which path ran.
- [ ] **Step 3.3** — In `_run_design_review_rounds`, create
      `starvation_cache = _StarvationProbeCache()` beside `last_readiness_signature`
      and pass it plus `config` into the `_review_and_handle_critique` call.
      Extend the method's `Post:` contract to record that the reviewer's findings
      include the starvation finding when the probe is enabled and bars are available.

### Task 4: Keep the suite hermetic

**File:** `backend/agents/investment_team/tests/conftest.py`

- [ ] **Step 4.1** — Autouse fixture patching
      `StrategyLabOrchestrator._fetch_design_probe_bars` to return `None`.
      Without it, every existing `run_cycle` design-loop test would newly attempt a
      real multi-symbol range fetch. `None` ⇒ empty findings ⇒ those tests observe
      today's behaviour exactly. Docstring: tests that *want* the probe override it
      with synthetic bars.
- [ ] **Step 4.2** — Add one clarifying line to the two `_market_must_not_run`
      patches in `test_strategy_lab_design_loop.py`: `_fetch_market_data` is the
      synthesis-entry marker; the design probe uses a separate seam by design.

### Task 5: Tests

**Files:** `test_strategy_lab_design_loop.py`, `test_strategy_lab_design_review_helpers.py`

- [ ] **Step 5.1** — *Reviewer receives the finding.* Modelled directly on
      `test_design_review_receives_hypothesis_rules_finding`: script a two-entry-rule
      spec where rule 2 is structurally starved, override
      `_fetch_design_probe_bars` with synthetic bars that produce the condition
      (reuse the fixtures in `test_predicate_reachability.py`), capture the
      reviewer's `findings`, assert a `details` string containing
      `"structurally starved"` **and both** `entry[0]` and `entry[1]` — the
      acceptance criterion is that the presentation *names* the starving and
      starved rules, so assert on both ids, not just the phrase.
      Assert the merged finding's severity is `warning`, never `critical` (D8),
      on a compiled-path spec — the path where `to_starvation_gate_results`
      would otherwise emit `critical`.
- [ ] **Step 5.2** — *No starved rules ⇒ unchanged.* Two independently reachable
      rules with bars that trigger an abstention: assert the reviewer's findings
      are byte-identical to the no-probe run (this is the test that pins D2).
- [ ] **Step 5.3** — *Flag off ⇒ unchanged*, and *bars unavailable ⇒ unchanged*
      (`_fetch_design_probe_bars` returns `None`).
- [ ] **Step 5.4** — *Existing findings survive.* Assert the readiness findings and
      the hypothesis/rules finding are still present alongside the new one, and that
      `readiness_results` itself was not mutated (the fresh-merge invariant).
- [ ] **Step 5.5** — *Memo.* Direct-call test: two rounds with a reachability-equivalent
      spec probe once (count `_fetch_design_probe_bars` / `probe_starvation` calls);
      changing `target_symbols` alone re-probes. Plus the negative: a round whose
      fetch returned `None` leaves the cache unwritten, so the next round with an
      unchanged signature probes again rather than serving a memoized empty
      (Step 2.4 detail 2).
- [ ] **Step 5.6** — *Fail-open, at both layers* (Step 2.4 detail 1).
      *Outer:* `_fetch_design_probe_bars` monkeypatched to raise ⇒ `[]`, no
      exception escapes, cycle completes — the seam's own `except` cannot catch
      this, only the helper's can. *Inner:* `market_data_service.fetch_multi_symbol_range`
      raising through the real seam ⇒ `None` ⇒ `[]`. *Probe:* `probe_starvation`
      raising ⇒ `[]`. All three leave the reviewer's findings exactly as today.

### Task 6: Docs

- [ ] **Step 6.1** — `FAITHFUL_EXECUTION.md` §6: extend the hypothesis/rules bullet
      with a sibling bullet — the structurally-starved finding is merged into the
      same `_review_and_handle_critique` deterministic-findings list, actionable
      verdicts only, fetched through the design-time probe seam and fail-open.
      Add the new tests to the "Test coverage" list.
- [ ] **Step 6.2** — `strategy_lab/README.md`: a
      `### STRATEGY_LAB_DESIGN_STARVATION_PROBE_ENABLED` section in the env-var
      run, documenting the default, the added design-time fetch, and the durable-cache
      argument for why it is close to free on the happy path.

---

## Verification

```bash
cd backend
make lint
python -m pytest agents/investment_team/tests/test_strategy_lab_design_loop.py \
                 agents/investment_team/tests/test_strategy_lab_design_review_helpers.py \
                 agents/investment_team/tests/test_predicate_reachability.py \
                 agents/investment_team/tests/test_strategy_lab_synthesis_helpers.py -q
python -m pytest agents/investment_team/tests -q   # full team suite — watch for new network calls
```

The full-team run is the one that matters: the autouse fixture from Task 4 is
what keeps ~30 existing `run_cycle` tests off the network, and a suite that
suddenly slows down is the signal it did not take.

---

## Risks

| Risk | Mitigation |
|---|---|
| Design-time fetch slows or fails a cycle | Reviewer-branch-only, memoized, fail-open, flag-gated (D1/D4/D5) |
| Existing tests newly hit the network | Autouse conftest stub (Task 4) |
| The "design never fetches market data" invariant reads as weakened | Separate seam + clarifying comments; `_fetch_market_data` stays synthesis-only (D1) |
| Prompt noise on clean specs | Actionable verdicts only (D2), pinned by Step 5.2 |
| A `critical` finding hard-blocks an intentional priority ordering | Demoted to `warning` on the design path (D8), pinned by Step 5.1 |
| Double-reporting against synthesis gates | Reviewer delivery only, no `all_gate_results` recording (D3) |
| Merge conflict with the in-flight warmup-shadowing refinement to `predicate_reachability.py` | This plan touches no probe internals — only its public `probe_starvation` / `to_starvation_gate_results` API, which that work does not change |

## Out of scope

- Preserving the reviewer's adjudication / no-hard-block behaviour (step 2) —
  a property that holds today by construction (D7) and gets its own test there.
- The end-to-end integration test for a synthetic starved-rule spec (step 3).
  Step 5.1 proves *delivery*; step 3 proves the loop *reconciles*.
- The broader reachability-probe test suite.
- Recording design-phase starvation findings on the gate timeline (D3).

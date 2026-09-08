# Surface the Structurally-Starved Finding to the Design Reviewer — Implementation Plan

**Goal:** The design-loop reviewer receives the `PredicateReachabilityProbe`'s
**structurally-starved** finding as part of its deterministic findings each
round, merged through the *same* path the hypothesis/rules consistency finding
already uses (`_review_and_handle_critique`), not a parallel delivery mechanism.

**Scope:** The first of three stories for "wire the structurally-starved finding
into the design-loop reviewer". The **adjudication story** (preserving the
reviewer's no-hard-block behaviour) and the **integration-test story** (proving
the loop reconciles a starved-rule spec) are separate units of work with their
own branches — see Out of scope. This document numbers only its own work, as
`Step N.M`; a bare "step" never refers to a sibling story.

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
- It fetches **the same symbols, over the same window, at the same `as_of`** that
  synthesis will fetch, and `MarketDataService` is backed by a durable
  content-hashed Parquet cache. So the synthesis fetch that follows hits that
  cache — the fetch is *moved earlier*, not duplicated.

  Stated precisely, because the precision is what makes it hold: that cache is
  keyed **per symbol**, not per universe (`market_data_cache/store.py:607`;
  `get_or_fetch_multi` is a parallel wrapper over the single-symbol
  `get_or_fetch`). The design round and the later synthesis fetch resolve their
  universes independently, and `_max_universe_symbols()` re-reads its ceiling
  from the environment each time, so the two lists are not guaranteed identical.
  Per-symbol keying is exactly why that does not matter here: every symbol the
  two fetches share is a hit, and a cap change costs only the symbols it adds.
  The affordability argument survives a mid-attempt cap change instead of
  quietly depending on there not being one — which is the same assumption the
  memo-key constraint below refuses to make, appearing here in a cost claim
  rather than a correctness one.
- Net new cost is limited to specs that pass readiness, get reviewed, and then
  never reach synthesis.
- A per-attempt memo plus a probe-signature memo keeps repeat rounds free when
  the reviser returns reachability-equivalent rules.

---

## Design decisions

**D1 — A separate fetch seam on `DesignMixin`, not `_fetch_market_data`.**
Add `_fetch_design_probe_bars(spec, config, symbols) -> Optional[Dict[str, List[OHLCVBar]]]`
to `orchestrator_design.py`. It reuses `fetch_multi_symbol_range` — the caller
resolves the universe and hands the list in, so this seam never calls
`resolve_strategy_symbols` itself (D11) — and returns bare bars rather than the
`_MarketDataFetch` envelope: design persists no audit row, so the
requested/fetched/`provider_used` *record fields* have no consumer here. It does
still compute requested-vs-fetched coverage internally — see D9, that part is
load-bearing, not bookkeeping. The separate seam is justified on its own merits
*and* it leaves the two "synthesis was not entered" tests meaning exactly what
they say. Their comments get one clarifying line so a future reader does not
mistake the design probe for a loophole.

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
as today."* Unfiltered, those `info`s reach the reviewer on any round that
produced an abstention but no starved rule — a spec with none gains nothing,
which is precisely why the quantifier matters: the violation is real but
data-dependent, not universal. It would still break the promise and dilute the
prompt on exactly the rounds it fires. Filter on `verdict == "starved"` (not on severity — severity
is a compiled-vs-custom proxy; the verdict is the intent) before rendering.

**D3 — Do not record the design-phase starvation findings on `all_gate_results`.**
The hypothesis merge does not record either: `reviewer_findings` is a *fresh*
list, leaving `readiness_results` untouched for the memoization and recording
paths. Recording would double-report against the synthesis-phase starvation
gates already on the timeline. Reviewer delivery is the whole ask.

**D4 — Fail open, everywhere, at two layers.** No symbols, a resolution
exception, no bars, a fetch exception, a probe exception, fewer than two entry
rules, or the flag off ⇒ empty list ⇒ the reviewer sees exactly today's
findings. `probe_starvation` already returns `[]` for falsy `market_data` and
for `len(entry_rules) < 2`, so some of this is free. The rest needs a guard in
*both* places, mirroring `_readiness_price_provider` and
`_compute_regime_summary`: inside `_fetch_design_probe_bars` for a failing
fetch, and in `_design_starvation_findings` around everything from the symbol
resolution through the render, for a failure of the resolution, the seam or the
probe itself. The outer guard has to start at the resolution rather than at the
fetch: D11 moved that call out of the seam, and it is guarded on the synthesis
path only because `_fetch_market_data` has its own `try` around it. One layer is
not enough — a guard inside the seam cannot catch the seam being unavailable,
and a diagnostic that can abort a design cycle is worse than no diagnostic.

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

**D7 — No change to the mechanical verdict path; the finding acts through the prompt.**
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

**D9 — A partial fetch must suppress the probe, not be probed.**
`MarketDataCache.get_or_fetch_multi` does not raise when one symbol of many
fails: `store.py`'s per-symbol worker logs a warning and returns `None`, and
`parallel_map(..., skip_none=True)` drops it. The result is a **nonempty partial
mapping**, so neither fail-open guard in D4 fires — they catch exceptions, and
there is no exception.

That is not merely a coverage gap, it manufactures false positives in the one
finding whose entire value is precision. Starvation is a *relative* verdict: a
rule is starved when none of its fires lands on a bar no earlier rule covers.
Drop a symbol and a rule that fires independently only on that symbol looks
starved on the survivors — so the reviewer would be handed a defect report for a
design that is correct, and asked to revise it.

Synthesis is only *partly* protected against this, and the limit is worth stating
precisely rather than assuming parity: it runs `TargetSymbolCoverageGate.check_fetch`
and breaks on a critical before its own reachability probe, but that gate raises a
critical only when `spec.target_symbols` is non-empty and one of those named
targets is missing. With an empty `target_symbols` it never compares the resolved
default universe against what was fetched, so synthesis proceeds into
`_run_synthesis_reachability_probe` with a partial default universe. **The design
probe specified here is therefore stricter than synthesis on this axis, by
design.** Whether synthesis should adopt the same source-agnostic check is a
genuine question, but it is a change to the synthesis gate's contract and belongs
to its own story — not this one.

The rule is therefore simple and source-agnostic: compare the symbols that came
back with bars against the **full resolved request** — whatever
`resolve_strategy_symbols` returned — and on any shortfall return `None`: no
bars, no probe, no finding, **the starvation/probe-signature memo left
unwritten**, next round retries. The durable content-hashed data cache is a
different cache and is deliberately untouched by this rule — it keeps whatever
symbols did fetch, which is what makes the retry cheap.

An earlier draft of this decision suppressed only when an explicitly requested
`target_symbols` entry was missing, on the grounds that
`TargetSymbolCoverageGate.check_fetch` treats an implicit universe differently.
That was the wrong lesson to draw from that gate. Its distinction is about
**reporting severity** — how loudly to report that the realized universe missed
the operator's stated intent — and intent is exactly what changes between an
explicit list and a default one. Soundness is a different question, and the
probe's answer to it does not care where a symbol came from:
`resolve_strategy_symbols` returns a concrete list either way, `_build_views`
sweeps whatever bars arrive, and a rule that fires independently only on the
dropped symbol reads as starved on the survivors in both cases. Mirroring a
severity rule to decide a soundness question is a category error, and it left the
default-universe path — the more common one — exposed to the very false positive
D9 exists to prevent.

**The check has two axes, and fixing the first left the second.** *Which
symbols* was only half of it; *which bars* is the other. A provider can return a
nonempty series for every requested symbol that covers only part of the
requested window. That passes a membership check while omitting an interval —
and a rule whose independent fires all fall inside the omitted interval reads as
starved on what survives. Same false positive, same cause, one axis over.

That axis needs **two** checks, and the first draft of this correction got it
wrong by reaching for an existing mechanism without reading its inputs.
`fetch_multi_symbol_range` does already run
`validate_market_data(..., mode="warn")` and park the result on
`MarketDataService.last_quality_report` — but that detector counts missing bars
*between `bars[0]` and `bars[-1]`* and is never handed the requested
`start`/`end`, so it catches an interior hole and is structurally blind to a
series that simply stops short of the window. It also returns zero gaps
outright, with a `calendar_window_unsupported` note, for windows outside its
hardcoded US-holiday years. Leaning on it alone would have covered the less
likely half: a provider with limited history returns a truncated series far
more often than a punctured one.

So the two shapes get the check each can actually answer. **Interior holes**
stay with the report — it owns the asset-class calendar and the tuned
thresholds, and a hand-rolled version in the seam would have to reproduce both
to avoid flagging every weekend. **Truncated ends** go to the seam, measured
*relatively*: each symbol's first and last bar against the widest span any
symbol returned, suppress if one is short. Relative comparison needs no
calendar, so it cannot be wrong about holidays — and it matches the shape of the
verdict it protects, since starvation is itself relative and a symbol short
against its peers is exactly the input that corrupts it.

One store-level fact worth recording because it outlives this story:
`MarketDataCache.get_or_fetch` writes the **requested** `start`/`end` as the
snapshot's coverage (`market_data_cache/store.py:652-660`) without checking that
the returned bars span them, so a temporally short fetch is durably cached as if
it were complete and a later `_find_covering_snapshot` will hit it. Fixing that
belongs to the store — and it is also what would close the one gap the two
checks above leave open: a truncation identical across *every* symbol, invisible
to the report because it never sees the window, and invisible to a relative
comparison because there is no shorter peer. Recording real coverage instead of
requested coverage is what retires that class. Until then it is the stated floor
of this defence, and the case where the probe at least compares like with like,
so the relative verdict stays coherent even over a window smaller than asked
for. Its consequence here is bounded and acceptable:
`fetch_multi_symbol_range` re-runs the quality report on every call, cache hits
included, so the shortfall keeps suppressing the probe instead of silently
recovering into a false verdict. The cost is that the probe stays quiet for that
window until the snapshot ages out — the same availability trade D9 already
accepts, and the right one for a finding whose value is precision.

The availability cost is real and accepted: one flaky symbol in a ten-symbol
default universe suppresses that round's probe entirely. That is the right trade
for this finding. `FAITHFUL_EXECUTION.md` states plainly that precision is what
makes it worth having — "a finding on a correct spec would train authors to
ignore the finding entirely" — and D4's posture is already that a round which
cannot judge soundly says nothing. The durable content-hashed cache also means a
symbol that fetched once stays available, so a persistent shortfall is the
exception. The synthesis gate still reports the coverage shortfall on the
timeline that owns it.

**D10 — Check the entry-rule count before fetching, not after.**
`probe_starvation` returns `[]` for `len(entry_rules) < 2`, so a spec with a
single entry rule has a guaranteed-empty verdict. Fetching the universe to reach
it is pure waste on a common, valid spec shape, paid on every review round with
the flag defaulting on. The count is therefore checked in
`_design_starvation_findings` before the seam is called (Step 2.4).

Unlike the signature memo, this check deliberately does **not** write the cache:
it is O(1) to re-evaluate and costs nothing to repeat, so memoizing it would only
add a way to be wrong. Recorded here as its own decision rather than living only
in a step, so the decision list matches what the plan actually commits to.

**D11 — Resolve the universe once per round, and pass it everywhere.**
D10 and Step 2.2 removed the `target_symbols` proxy in favour of the resolved
universe, because `_max_universe_symbols()` reads its ceiling from the
environment on every call. That fix was incomplete: it left the signature and
the fetch seam each calling `resolve_strategy_symbols` independently, so the
hazard moved rather than closing. If the cap changes between those two calls,
the memo labels findings computed over universe B with a signature describing
universe A — and if the cap later reverts to A, the "signature unchanged"
short-circuit serves B's verdict for a round whose universe is A, without
fetching. That is worse than staleness: it is a wrong answer with no way to
notice.

So the universe is resolved exactly once, in `_design_starvation_findings`, and
the same list is handed to `_starvation_probe_signature` and to
`_fetch_design_probe_bars` (which no longer resolves at all). One call, one
list, no window.

The lesson generalises past this call: **computing an environment-dependent
value twice is the same defect as assuming it is stable** — the second read is
just a shorter race. Wherever a value must agree across two consumers, compute
it once and pass it, rather than recomputing and trusting agreement.

**D12 — Non-daily specs get no probe, and `timeframe` is in the key.**
`StrategySpec.timeframe` is a `Literal["1m","5m","15m","1h","1d"]`
(`models.py:345`), and `fetch_multi_symbol_range` defaults to
`frequency="1d"` / `intraday_mode=False`. Step 1.1 mirrors `_fetch_market_data`,
so a 5-minute spec would be probed against daily candles. For a rule like
"5-minute RSI < 30" those are not coarse data, they are the wrong series: the
rule fires never or always, and "structurally starved" computed on that is
meaningless rather than approximate. It would prompt a revision of a correct
design — the exact churn D8 exists to prevent, arriving by a different route.

**So the seam returns `None` when `spec.timeframe != "1d"`, checked before any
fetch** (same reasoning as the entry-rule count in D10 — do not pay for a
verdict you will not use).

The tempting alternative is to fetch at the spec's own frequency instead. Reject
it here, for a reason worth checking rather than assuming: **synthesis does not
do that either.** `_fetch_market_data` calls `fetch_multi_symbol_range` with
`symbols` / `asset_class` / `start_date` / `end_date` / `as_of` and no
`frequency` or `intraday_mode` (`orchestrator.py:1489-1495`), so the
synthesis-phase reachability probe already runs on daily bars for an intraday
spec. Making the design probe frequency-aware would (a) make it disagree with
the synthesis verdict for the same spec, and (b) break the cache alignment the
affordability argument rests on, since the two fetches would no longer share
symbol snapshots. Fixing the frequency gap is a real piece of work — it belongs
to the fetch path and to both probes at once, not to this story, which only
changes where an existing verdict is *delivered*.

This makes the design probe stricter than synthesis on a second axis, alongside
D9. Both strictnesses have the same shape and the same justification: a round
that cannot judge soundly says nothing.

`spec.timeframe` goes in the probe signature regardless of the suppression,
and the reason is not redundancy — the design loop **mutates the spec between
rounds**. A round-1 `1d` spec that probes and memoizes, followed by a round-2
revision to `5m` with the same rules, universe and window, would otherwise hit
the unchanged signature and serve the daily verdict for an intraday spec. That
is the fifth instance of the constraint below, and the first one the constraint
predicted rather than followed.

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
- **Never memoize an absence.** Every early `return None` / `return []` on this
  path leaves its memo unwritten, so the next round retries. Review found this
  same defect three separate times while the plan was being written — in the bars
  memo, in the findings memo on the `None`-fetch path, and on the D9 suppression
  path — because each looked like an independent decision. It is one rule:
  caching "we couldn't tell" turns a transient fault into a permanent one, and
  here that means one flaky symbol silently hiding a genuinely starved rule for
  the rest of the attempt. Apply it to any early return added during
  implementation, not only the three the plan already names.
- **A memo key names every input the memoized value depends on — no member is
  omitted because it "can't change".** Review found this defect three separate
  times, each in a different disguise: `spec.target_symbols` standing in for the
  resolved universe (the cap is read from the environment per call); the
  signature and the fetch seam each resolving that universe independently (D11);
  and `config.start_date` / `config.end_date` left out as "fixed for the
  attempt" (`BacktestConfig` is not frozen). The disguise is what makes it
  recur — each looked like a local judgement about one field. It is one rule,
  and the asymmetry decides it: an unnecessary key member costs a tuple slot,
  while a missing one serves a verdict computed over inputs this round does not
  have, silently and with no way to notice. When tempted to omit a member,
  include it. Reserve the assumption for values a type system or a `frozen=True`
  actually enforces — and then cite the enforcement, not the intent.

  Stated as a rule it then earned its keep: `spec.timeframe` (D12) is the fourth
  member, and the first one added because the rule said to rather than because
  review caught it missing. The design loop mutates the spec between rounds, so
  a `1d` verdict must not be replayed for a `5m` revision. A fifth appearance
  sits outside the memo, in the affordability argument — "the synthesis fetch
  that follows is a cache hit" assumed both fetches resolve the same universe —
  which is the same assumption wearing a cost claim instead of a correctness
  one. Read the rule that broadly.

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

- [ ] **Step 1.1** — Add `_fetch_design_probe_bars(self, spec, config, symbols) -> Optional[Dict[str, List[OHLCVBar]]]`
      to `DesignMixin`, modelled on `orchestrator.py`'s `_fetch_market_data`
      but keeping only what the probe needs:
  - **`symbols` is passed in, already resolved — this seam never calls
    `resolve_strategy_symbols` itself.** Step 2.4 resolves once and hands the
    same list to both the signature and this fetch, so there is exactly one
    resolution per round and no window in which the two could disagree. See D11
    for why that matters more than it looks;
  - `as_of = (getattr(spec, "audit", None) and spec.audit.data_snapshot_id) or None`
    — byte-identical to `_fetch_market_data`, so the durable cache key matches
    and synthesis's later fetch hits it;
  - memo on `(tuple(symbols), spec.asset_class, config.start_date, config.end_date, as_of)`
    in a lazily-created `self._design_probe_bars_cache`, mirroring
    `_benchmark_bars_cache`. **Only a complete, successful fetch is stored.**
    Every `None` return — no resolvable symbols, a raised fetch, or the coverage
    shortfall below — leaves the cache untouched, so the next round retries
    rather than being served a remembered failure. This is the same rule Step 2.4
    applies to the findings memo, and for the same reason: a memo that caches an
    absence turns a transient fault into a permanent one;
  - **before fetching, return `None` when `spec.timeframe != "1d"`** (D12) —
    the seam fetches daily bars, and an intraday spec judged on them yields a
    meaningless verdict, so there is nothing to buy with the fetch;
  - after the fetch, apply D9's coverage check **on both axes** against **the
    `symbols` list it was given** — not a freshly resolved one:
    * *which symbols* — if any requested symbol is missing from those that
      returned bars, return `None`, explicit `target_symbols` and the
      asset-class default universe alike;
    * *which dates* — a symbol can return a nonempty series that covers only
      part of the requested window, which passes a membership check while
      hiding exactly the interval a rule's independent fires live in. This
      needs **two** checks, because the shapes fail differently and no single
      mechanism sees both:
      - **Interior holes** — the service already computes this.
        `fetch_multi_symbol_range` runs `validate_market_data(..., mode="warn")`
        and leaves the structured result on `self.last_quality_report`; suppress
        on a failing report. Do not re-derive it in the seam: the detector
        carries an asset-class calendar and tuned thresholds
        (`gap_pct_threshold` 0.005, `gap_min_count` 3), which is exactly the
        machinery a hand-rolled check would have to reproduce to avoid flagging
        every weekend.
      - **Truncated ends** — the report cannot see these, and the reason is
        structural rather than incidental: `_count_gaps` counts missing bars
        *"between `bars[0]` and `bars[-1]`"* and `validate_market_data` is never
        passed the requested `start`/`end` at all, so a series that simply stops
        short of the window is indistinguishable from a complete one. It also
        returns 0 gaps outright, with a `calendar_window_unsupported` note,
        for windows outside its hardcoded US-holiday years. **So the seam checks
        the ends itself, and does it relatively: compare each symbol's first and
        last bar dates against the widest span any symbol returned, and suppress
        if one is short.** Relative comparison is the point — it needs no
        calendar, so it cannot be wrong about holidays, and starvation is itself
        a relative verdict, so a symbol short against its peers is precisely the
        input that corrupts it.

      Read the report immediately after our own fetch and treat it, like
      `provider_used`, as **shared mutable state on the service**: it is
      assigned only under `if result:`, so an empty fetch leaves the previous
      call's report in place. That is safe only because the seam consults it
      solely when bars came back — the membership check above has already
      returned `None` for an empty fetch. That ordering is a precondition, not
      an incidental, and the docstring should say so.

      **Residual, stated rather than papered over:** a truncation identical
      across *every* symbol is caught by neither check — the report cannot see
      the window, and a relative comparison has no shorter peer to notice. That
      is the one case where the probe at least compares like with like, so the
      relative verdict stays coherent even though the window is smaller than
      asked for; combined with the snapshot-coverage issue below it is the known
      floor of this defence, and closing it needs the store to record real
      coverage rather than requested coverage.

    Neither axis raises, so no exception reaches the guard below; both would
    fabricate starvation. The second axis is the same category error as the
    first: D9's earlier revision fixed *which symbols* and left *which bars*,
    the way its own predecessor fixed explicit targets and left the default
    universe;
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
- [ ] **Step 2.2** — `_starvation_probe_signature(spec, config, resolved_symbols) -> tuple`:
      `(tuple(r.model_dump_json() for r in spec.entry_rules), bool(spec.requires_custom_code),
      spec.asset_class, spec.timeframe, tuple(resolved_symbols),
      config.start_date, config.end_date,
      (getattr(spec, "audit", None) and spec.audit.data_snapshot_id) or None)`,
      where `resolved_symbols` is the list Step 2.4 resolved **once** for this
      round and also passed to the fetch seam — literally the same object, not a
      second call that happens to agree (D11).

      It extends synthesis's `(entry_rules, requires_custom_code)` key with
      `asset_class`, `timeframe` (D12 — the design loop mutates the spec between
      rounds, so a `1d` round's verdict must not be served to a `5m` one), the
      **resolved** symbols, the backtest window and `as_of`,
      because — unlike synthesis — the design loop can change which bars the
      verdict is computed against between rounds. Every member of Step 1.1's
      bars key is therefore a member of this one: resolved symbols,
      `asset_class`, `config.start_date`, `config.end_date`, `as_of`. That
      correspondence is the point, and it has to be literal — see below.

      **The window is in the key, not assumed constant.** An earlier revision
      omitted both dates as "fixed for the attempt". `BacktestConfig` is a plain
      `BaseModel` with no `frozen=True` (`models.py:604`), and
      `_design_starvation_findings` receives `config` and `cache` as separate
      arguments, so nothing structurally ties one to the other. Change the
      window while reusing the cache and the failure is silent and specific:
      Step 1.1's bars memo *is* date-aware and would refetch correctly, but the
      findings memo short-circuits on the unchanged signature and returns
      `cache.findings` before the seam is ever called — so the reviewer receives
      a verdict computed over the previous window and the date-aware bars key
      never gets consulted. Two extra tuple members close that; asserting the
      invariant instead would only be as good as the assertion.

      **Use the resolved universe, never `spec.target_symbols` as a proxy for it.**
      An earlier revision took the proxy and documented the assumption it needed —
      that `resolve_strategy_symbols` is a pure function of the spec. That
      assumption is false today, not merely fragile: on the empty-`target_symbols`
      path the asset-class default is truncated to `_max_universe_symbols()`,
      which calls `os.getenv("STRATEGY_LAB_MAX_UNIVERSE_SYMBOLS")` on **every**
      invocation. Change that variable mid-attempt and the universe changes while
      a `target_symbols`-based signature does not, so Step 2.4's
      "signature unchanged ⇒ `cache.findings`" short-circuit would serve a verdict
      computed against the old universe.

      Resolving is cheap — list selection and truncation, no I/O — so there is no
      reason to prefer the proxy. The general lesson is worth more than the fix:
      documenting an assumption is not the same as verifying it, and this one was
      written down without being checked. Where an input can be *computed*
      instead of *assumed*, compute it.

      `as_of` is in the signature even though
      `build_spec_from_dict` never sets `audit` and the snapshot id is expected
      to be constant for the attempt: relying on that expectation would leave the
      memo correct only by an invariant this plan cannot prove, and the cost of
      not relying on it is one tuple element.

      The rule to carry forward: the probe signature must cover every input the
      verdict depends on — the rules *and* the bars they are judged against.
- [ ] **Step 2.3** — `@dataclass class _StarvationProbeCache: signature: Optional[tuple] = None;
      findings: List[QualityGateResult] = field(default_factory=list)`.
      Mutable holder so the memo survives rounds without widening
      `_review_and_handle_critique`'s return tuple (its 3-tuple shape has direct-call tests).
- [ ] **Step 2.4** — `_design_starvation_findings(self, *, spec, config, cache) -> List[QualityGateResult]`:
      flag off / `config is None` / `cache is None` ⇒ `[]`; **fewer than two
      entry rules ⇒ `[]` before any fetch** (`probe_starvation` returns `[]` for
      `len(entry_rules) < 2`, so fetching the universe first to reach a
      guaranteed-empty verdict is pure waste on a common, valid spec shape —
      and the flag defaults on, so every review round of every single-rule spec
      would pay it). Everything from here on runs **inside an outer
      `try` / `except Exception` guard** — see detail 1 for its exact extent and
      why it starts here rather than at the fetch. Resolve the universe
      **once** —
      `symbols = self.market_data_service.resolve_strategy_symbols(spec)`, empty
      ⇒ `[]` — build the signature from that same list and this round's `config`
      (Step 2.2), and only then compare it against `cache.signature`: unchanged
      ⇒ `cache.findings`. **That order is
      load-bearing.** `_starvation_probe_signature` takes `resolved_symbols`,
      so a cache comparison placed *before* the resolution has
      nothing to compare with: it would need a stale signature or a second
      resolution call, and the second call is precisely the disagreement window
      D11 closed. Resolve once → build the signature → compare → fetch. On a
      miss, fetch bars with that same list (D11), `probe_starvation`, filter to
      `verdict == "starved"` (D2), render with
      `to_starvation_gate_results(..., phase="design")`, **demote any `critical`
      result to `warning`** (D8 — a `critical` deterministic finding instructs
      the reviewer to return `ready=false`, which would hard-block a deliberate
      priority ordering), store on the cache, return.
      `"design"` is a valid `StrategyLabPhase` literal — no models change needed.

      One consequence of that ordering, stated rather than left for an
      implementer to discover and "fix": **the memo no longer short-circuits the
      resolution, and must not be made to.** A cache hit still pays one
      `resolve_strategy_symbols` call. That is not waste — it is what makes the
      hit trustworthy, because the resolution is the only thing that can tell
      this round's universe from the memoized one (D11). Resolving is list
      selection and truncation with no I/O, so the cost is negligible; skipping
      it to save that cost would restore exactly the wrong-answer path D11
      exists to close.

      Two contract details this helper must get right, both of them easy to get
      wrong and both pinned by tests in Task 5:

      1. **An outer `try` / `except Exception` → `logger.debug(...)` → `[]` opens
         before the resolution and closes after the render** — it covers the
         resolve, the signature build, the cache comparison, the fetch, the probe
         and the render. Step 1.1's guard sits *inside*
         `_fetch_design_probe_bars` and so cannot catch a failure of the seam
         itself, nor one raised by `probe_starvation` /
         `to_starvation_gate_results` on a spec shape they did not expect.
         The resolution needs the same cover and does not inherit it from
         anywhere: `_fetch_market_data` wraps its own
         `resolve_strategy_symbols` call in a `try` that returns an empty
         envelope (`orchestrator.py:1482-1486`), but D11 moved the design
         path's resolution *out* of the seam and into this helper, so that guard
         no longer stands between a raising resolution and the cycle. Leaving it
         outside would let a universe-resolution failure abort the very cycle
         the fail-open promise protects. A design-time diagnostic must never
         abort a cycle, so the guard belongs at both layers and, at this layer,
         around the whole diagnostic.
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
      include the starvation finding when the probe is enabled **and the fetch
      returned bars for the full resolved request** — any shortfall suppresses
      the probe (D9), so "bars are available" would overstate what the
      implementation delivers, and a `Post:` copied from a looser wording would
      be a docstring this plan's own contract rules forbid.

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
- [ ] **Step 5.5** — *Memo.* Direct-call test: two rounds with reachability-equivalent
      specs ⇒ the probe runs exactly once (count `_fetch_design_probe_bars` and
      `probe_starvation` calls); changing `target_symbols` alone ⇒ re-probes;
      **mutating `config.start_date` or `config.end_date` between two otherwise
      identical rounds ⇒ re-probes**, since `BacktestConfig` is not frozen and the
      findings memo would otherwise answer for the previous window before the
      date-aware bars key could refetch (Step 2.2). Plus the negative: a round whose
      fetch returned `None` leaves the cache unwritten, so the next round with an
      unchanged signature probes again rather than serving a memoized empty
      (Step 2.4 detail 2).

      **And a case that actually reaches the bars memo.** The cases above all
      turn on the *findings* memo, which short-circuits before
      `_fetch_design_probe_bars` is called at all — so they pass whether Step
      1.1's bars memo exists, is keyed wrongly, or is missing entirely. The
      bars memo is only exercised where the findings signature **misses** but
      the fetch inputs are unchanged: **different entry rules, same universe,
      window, `timeframe` and `as_of`.** Assert `probe_starvation` runs twice
      and `market_data_service.fetch_multi_symbol_range` exactly once. Counting
      `_fetch_design_probe_bars` calls is not enough here — the seam is entered
      both rounds by design; the memo's whole job is that only one of those
      entries reaches the service.
- [ ] **Step 5.6** — *Fail-open, at both layers* (Step 2.4 detail 1).
      *Outer:* `_fetch_design_probe_bars` monkeypatched to raise ⇒ `[]`, no
      exception escapes, cycle completes — the seam's own `except` cannot catch
      this, only the helper's can. *Inner:* `market_data_service.fetch_multi_symbol_range`
      raising through the real seam ⇒ `None` ⇒ `[]`. *Probe:* `probe_starvation`
      raising ⇒ `[]`. *Gate mapping:* `to_starvation_gate_results` monkeypatched
      to raise on a compiled-path spec ⇒ `[]` — Step 2.4 names it explicitly as a
      failure the guard must absorb, and it is the one case where the probe
      succeeded and only the rendering failed. *Resolution:*
      `market_data_service.resolve_strategy_symbols` raising ⇒ `[]` — this one
      only passes if the guard opens *before* the resolution rather than around
      the fetch alone, which is the whole reason detail 1 states the boundary
      instead of leaving it to the implementer. All five leave the reviewer's
      findings exactly as today.
- [ ] **Step 5.7** — *No fetch when starvation is impossible* (Step 2.4). A
      readiness-clean single-entry-rule spec must not invoke the seam at all:
      patch `_fetch_design_probe_bars` with a `_must_not_run` raiser, like the
      existing `_market_must_not_run` pattern, and assert the cycle completes.
- [ ] **Step 5.8** — *Partial fetch suppresses the probe* (D9). Bars returned for
      a strict subset of the resolved request ⇒ `[]`, and `probe_starvation` is
      never called. Run it **twice** — once with explicit `target_symbols`, once
      with `target_symbols` empty so the request is the asset-class default
      universe — because the whole point of D9's correction is that the two paths
      behave identically. A test that pinned only the explicit case would pin the
      bug. Plus the positive control: a complete fetch of the same universe does
      probe.

      **And assert the memo stays unwritten after the suppressed round**, then
      run a following round with an unchanged signature and a *complete* fetch
      and assert it probes rather than serving `cache.findings`. Step 5.5 pins
      this for the `None`-fetch path; the suppression path reaches the same
      `return []` and carries the identical hazard, and it is the worse one — an
      implementation that wrote the signature here would let a single flaky
      symbol hide a genuinely starved rule for the rest of the attempt.

- [ ] **Step 5.9** — *One resolution per round* (D11). Count
      `resolve_strategy_symbols` calls across a probing round and assert exactly
      one; and with `_fetch_design_probe_bars` asserting on the `symbols` it
      receives, assert it is the same list the signature was built from. A test
      that only checked the signature's contents would pass even with two
      resolutions racing.
- [ ] **Step 5.10** — *Non-daily specs are not probed* (D12). A readiness-clean
      two-rule spec with `timeframe="5m"` ⇒ `[]`, and `fetch_multi_symbol_range`
      is never called — patch it with a `_must_not_run` raiser, like Step 5.7
      does for the seam. Plus the memo half, which is the part a suppression-only
      test would miss: probe a `1d` spec, then mutate `timeframe` to `5m`
      leaving rules, universe and window identical, and assert the second round
      returns `[]` rather than replaying the daily verdict through an unchanged
      signature.
- [ ] **Step 5.11** — *Temporally incomplete fetches suppress the probe* (D9,
      second axis). Two cases, and they must be **separate tests**, because each
      is caught by a different mechanism and a combined case would pass with
      only one of them implemented:
  - *Interior hole:* every symbol returns a full-span series, the stubbed
    `last_quality_report` reports a failing gap count ⇒ `[]`.
  - *Truncated end:* every symbol returns bars, one symbol's series stops short
    of the span the others cover, **and the stubbed report is clean** — this is
    the case the report structurally cannot see (`_count_gaps` measures only
    between `bars[0]` and `bars[-1]`), so a clean report is what proves the
    seam's own relative endpoint check is doing the work. Without the clean
    stub this test would pass on the report alone and pin nothing.

      In both, `probe_starvation` is never called. Positive control: full-span
      bars for every symbol with a clean report do probe. **And assert the memo
      stays unwritten in both**, for the reason Step 5.8 gives for its own
      suppression path — these returns are the ones most likely to be
      implemented as a plain `return []` that writes the signature on the way
      out, and doing so would let one short window hide a genuinely starved rule
      for the rest of the attempt.

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
| Design-time symbol resolution or fetch slows or fails a cycle | Reviewer-branch-only, memoized, flag-gated, and fail-open from the resolution onward rather than from the fetch onward (D1/D4/D5), pinned by Step 5.6 |
| Existing tests newly hit the network | Autouse conftest stub (Task 4) |
| The "design never fetches market data" invariant reads as weakened | Separate seam + clarifying comments; `_fetch_market_data` stays synthesis-only (D1) |
| Prompt noise on clean specs | Actionable verdicts only (D2), pinned by Step 5.2 |
| A `critical` finding hard-blocks an intentional priority ordering | Demoted to `warning` on the design path (D8), pinned by Step 5.1 |
| A mid-attempt universe-cap change staling the memo, or mislabelling one universe's findings with another's signature | Universe resolved once per round and passed to both the signature and the fetch (D11) |
| A changed backtest window served from a memo built for the previous one | `config.start_date` / `config.end_date` are signature members, not an assumed-constant (Step 2.2), pinned by Step 5.5 |
| An intraday spec judged on daily candles | Probe suppressed for `timeframe != "1d"` before any fetch, and `timeframe` is a signature member so a mid-attempt change cannot replay the daily verdict (D12), pinned by Step 5.10 |
| A silently partial fetch fabricates a starvation finding | Any shortfall suppresses the probe: missing symbols (membership, explicit and default universes alike), interior holes (the service's quality report), and truncated ends (the seam's own relative endpoint check, since the report never sees the requested window) — D9, pinned by Steps 5.8 and 5.11 |
| Wasted fetch on specs that cannot be starved | Entry-rule count checked before fetching (D10, Step 2.4), pinned by Step 5.7 |
| Double-reporting against synthesis gates | Reviewer delivery only, no `all_gate_results` recording (D3) |
| Merge conflict with the in-flight warmup-shadowing refinement to `predicate_reachability.py` | This plan touches no probe internals — only its public `probe_starvation` / `to_starvation_gate_results` API, which that work does not change |

## Out of scope

Everything below is **excluded from this plan**. The first two belong to the
*sibling stories* that follow this one in the same series — not to any step of
this document, which numbers its own work `Step N.M` throughout. Read "the
adjudication story" and "the integration-test story" as separate units of work,
each with its own branch and review.

- **Preserving the reviewer's adjudication / no-hard-block behaviour** — the
  adjudication story owns this. It holds today by construction (D7 as corrected,
  and D8 is what keeps this plan from breaking it), and that story pins it with
  its own test. Nothing in Tasks 1-6 here implements or tests it.
- **The end-to-end test that the design loop *reconciles* a starved-rule spec** —
  the integration-test story owns this. Step 5.1 here proves the reviewer
  *receives* the finding; proving the loop then resolves it is a different
  assertion over a full cycle, and is not attempted in this plan.
- **The broader reachability-probe test suite.**
- **Recording design-phase starvation findings on the gate timeline** (D3).

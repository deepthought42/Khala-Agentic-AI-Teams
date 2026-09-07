# Plan — expose the per-agent cost rollup on the SE metrics endpoint

Status: **plan only** (no code changes in this document's commit).

## 1. Goal

`metrics/agent_rollup.py` already computes the per-`agent_key`/per-`phase` cost,
token, cache, and latency rollup over `se_agent_traces`, and
`shared/trace_store.fetch_traces_since` already reads the rows it needs. Today
that data is only reachable from a Python REPL with database credentials.

This plan serves the rollup on the SE team's existing metrics route
(`GET /dora`, aliased `GET /api/se/metrics`) under a new top-level key, so the
per-agent cost and cache picture is one HTTP call away — without changing the
shape any current consumer already reads.

## 2. What already exists (no work required)

| Piece | Location | State |
|---|---|---|
| Pure grouping/percentile math | `metrics/agent_rollup.compute_from_traces` | Done — stays the definition of record; **not** the endpoint's read path (§3.5) |
| Postgres-reading wrapper | `metrics/agent_rollup.compute_agent_rollup` | Done — correct for REPL/offline callers; materializes rows, so not what the route calls (§3.5) |
| Narrow column read | `shared/trace_store.fetch_traces_since` | Done, returns `[]` when Postgres is off or the query fails. No `LIMIT`, no aggregation — see §3.5 |
| The route to extend | `api/routes/status.py:66` (`metrics_dora`) | Serves DORA + cost, clamps `window_days` to `[1, 365]` |
| Existing SQL-aggregating read (the precedent) | `shared/trace_store.fetch_cost_since` | `SUM(cost_usd) GROUP BY job_id` — the pattern §3.5's new read follows |
| Unified-API alias | `unified_api/main.py:1586` (`se_metrics_alias`) | Forwards to `/dora` and returns `resp.json()` verbatim — **additive keys pass through with no change** |

Consequence: the "Postgres unset / empty table" case is already non-erroring at
the source — every trace read in this module returns empty rather than raising,
and `compute_from_traces` turns an empty row set into a well-formed
`AgentRollupMetrics` with three empty dicts. That acceptance criterion costs
nothing to satisfy.

What is *not* free is the read itself. The existing pieces were built for a
caller holding rows in memory; putting that path behind an HTTP GET is the one
place this story has real design work, and §3.5 is where it happens.

## 3. Design decisions

### 3.1 One key on the existing route, not a new route

`agent_rollup` becomes a sibling of the DORA fields on the `/dora` response:

```jsonc
{
  "window_days": 30.0,
  "computed_at": "...",
  "deployment_count": 0,
  // ... every existing DORA field, unchanged ...
  "agent_rollup": {
    "window_days": 30.0,
    "computed_at": "...",
    "by_agent": { "code_review": { /* CallRollup */ } },
    "by_phase": { "execution": { /* CallRollup */ } },
    "by_agent_phase": { "code_review": { "execution": { /* CallRollup */ } } }
  }
}
```

Rationale: one round trip for "what did this window cost, and who spent it",
one window parameter, one cache/CDN entry, and no second route to register in
the security gateway's scanned prefixes or the OTel `excluded_urls` reasoning
that `/dora`'s name already navigates.

Rejected: a separate `GET /agent-rollup` route. It would double the surface for
a payload that is only ever read next to the DORA numbers, and would need its
own window-clamping, its own alias, and its own gateway registration.

### 3.2 The nested object keeps its own `window_days` and `computed_at`

`AgentRollupMetrics.to_dict()` carries both, so they are duplicated with the
parent's. Keep the duplication: the nested object stays self-describing, can be
lifted out and stored or logged standalone, and does not require the route to
strip fields off a dataclass the pure function is the sole producer of.
(`computed_at` will differ from the parent's by microseconds — both are stamped
from the UTC wall clock at their own call. Harmless, and worth a one-line note
in the README so nobody files it as a bug.)

### 3.3 Two independent failure boundaries

Today `metrics_dora` wraps everything in one `try`/`except` that returns a
zeroed DORA literal. Naively adding the rollup inside that block would mean a
rollup failure zeroes the DORA payload — a regression for existing consumers.

Split into two private helpers, each with its own `try`/`except`:

```python
window = max(1.0, min(365.0, window_days))
payload = _dora_payload(window)             # existing behavior, extracted verbatim
payload["agent_rollup"] = _rollup_payload(window)
return payload
```

- `_dora_payload(window)` — unchanged logic, including the function-local import
  and the zeroed literal (which stays valid even if the metrics module fails to
  import).
- `_rollup_payload(window)` — function-local import of `compute_agent_rollup`,
  same reasoning; on any exception, logs and returns the empty-rollup literal
  `{"window_days": window, "computed_at": <now>, "by_agent": {}, "by_phase": {},
  "by_agent_phase": {}}`, mirroring `AgentRollupMetrics`' field defaults with the
  same "keep in sync with that dataclass" comment the DORA literal already
  carries.

Both helpers get explicit `Preconditions:`/`Postconditions:` docstring sections
per the repo's DbC mandate; the postcondition to state plainly is *never raises,
always returns a complete shape*.

### 3.4 No new query parameters

The route keeps exactly one window knob: the existing `window_days: float =
30.0`, clamped to `[1, 365]`, passed to both `compute_dora` and
`compute_agent_rollup`. That satisfies "the same time-window parameter
convention" with no new convention to document or clamp.

Deliberately deferred (each is a separate, additive change if it is ever
wanted):

- **`job_id` filter.** `compute_agent_rollup` already accepts it; the endpoint
  does not expose it. Adding it later is a new optional query param with no
  shape change.
- **`expected_agent_keys` / `expected_phases` densification.** The endpoint
  reports only what it observed. Densifying would need a canonical agent-key and
  phase list maintained somewhere; a stale list would silently report zero-call
  groups for agents that were renamed, which is worse than omitting them.

### 3.5 The HTTP read must aggregate in SQL, not materialize rows

**Response size is not the constraint; the scan is.** `by_agent_phase` is bounded
by (distinct agent keys) x (distinct phases) — tens of entries. That says nothing
about the query behind it, and reasoning from the small response to "no bound
needed" is the wrong inference.

Look at what `/dora` does today. Its cost read is
`SELECT job_id, SUM(cost_usd) ... WHERE ts >= %s GROUP BY job_id` — Postgres
aggregates, and the route receives one row per job. **The endpoint materializes
zero `se_agent_traces` rows.** `fetch_traces_since`, by contrast, is
`SELECT <8 columns> FROM se_agent_traces WHERE ts >= %s` with no `LIMIT` and no
aggregation: every matching row crosses the wire and becomes a Python dict.

So this is not "a pre-existing property of the read path, unchanged here." It is
a **new property of the endpoint**, and the defaults make it maximal:
`SE_TRACE_RETENTION_DAYS` defaults to 30 and `window_days` defaults to 30, so the
default request reads essentially the entire traces table — on every poll, per
concurrent caller, against a 15s alias timeout (`SE_METRICS_ALIAS_TIMEOUT`). The
`idx_se_agent_traces_ts` index bounds the *scan*, not the *result set*. And this
degrades precisely as the epic succeeds: more trace volume is the goal.

**Do this:** add an aggregating read alongside `fetch_traces_since` — one query,
one row per group, nothing unbounded materialized:

```sql
SELECT agent_key, phase,
       GROUPING(agent_key) AS g_agent, GROUPING(phase) AS g_phase,
       COUNT(*)                                   AS call_count,
       SUM(cost_usd::numeric)                     AS total_cost_usd,
       SUM(input_tokens)                          AS total_input_tokens,
       SUM(output_tokens)                         AS total_output_tokens,
       SUM(cache_read_tokens)                     AS total_cache_read_tokens,
       SUM(cache_creation_tokens)                 AS total_cache_creation_tokens,
       percentile_cont(0.5)  WITHIN GROUP (ORDER BY latency_ms) AS latency_ms_median,
       percentile_disc(0.95) WITHIN GROUP (ORDER BY latency_ms) AS latency_ms_p95
FROM se_agent_traces
WHERE ts >= %s
GROUP BY GROUPING SETS ((agent_key), (phase), (agent_key, phase))
```

One query yields all three views; `GROUPING()` tags which set each row came from.

**Parity with the `_stats` helpers — exact for the statistics, canonical-plus-tolerance for cost.**
The concern with moving math SQL-side is that the endpoint would report different
numbers than the unit-tested helpers. For the percentiles and the integer sums it
does not. For the cost sum it can, and the plan says so rather than overclaiming.

| Statistic | `_stats` (Python) | Postgres | Parity |
|---|---|---|---|
| `median` | sorted midpoint, **averaging** the two middle values at even `n` | `percentile_cont(0.5)` — linear interpolation, which at the median of an even sample *is* their average | **Exact**, and it rests on `latency_ms` being `INTEGER` (see the DDL): the two middle values are exact integers, so `(a + b) / 2` is exact in IEEE double on both sides |
| `p95` | nearest rank, `ordered[ceil(0.95n) - 1]`, no interpolation | `percentile_disc(0.95)` — first value whose cumulative distribution ≥ 0.95, i.e. `ordered[ceil(0.95n) - 1]` | **Exact** — `percentile_disc` selects an actual sample value, so there is no arithmetic to diverge |
| token sums, `call_count` | Python `int` accumulation | `SUM(<integer column>)`, `COUNT(*)` | **Exact** — integer arithmetic, no representation question |
| `total_cost_usd` | `math.fsum` over the raw `float8` values | `SUM(cost_usd::numeric)` | **Not exact.** `compute_from_traces` is canonical; the SQL path is compared within tolerance. See below |

The `max(1, ...)`/`min(n, ...)` clamps in `_stats.p95` are no-ops for `0 < f <= 1`
and `n >= 1`, so they do not perturb the correspondence.

**Why the cost sum cannot be claimed exact.** `cost_usd` is stored as
`DOUBLE PRECISION`. `math.fsum` sums those binary doubles and rounds once.
`cost_usd::numeric` converts each value *first*, and since PostgreSQL 12 a
`float8 → numeric` cast goes through the shortest decimal representation that
round-trips — so the double nearest `0.1` becomes exactly `0.1`, not
`0.1000000000000000055511151231257827…`. Summing the decimals is therefore a
different arithmetic domain than summing the doubles, and for a group whose total
lands near a 6-decimal rounding boundary the two can round to different values. A
parity fixture over representative rows cannot establish a for-all-values
guarantee, so do not write one that implies it.

Resolution: **`compute_from_traces` is the canonical definition of
`total_cost_usd`.** The parity test asserts the percentiles, token sums and counts
are *equal*, and that the two cost sums agree within a tolerance well under the
6-decimal reporting granularity (`1e-9` absolute is ample). The README says the
figure is a sum of float-stored per-call costs and is not to be reconciled to the
cent against an external ledger — which was always true and is now stated.

Keep the `::numeric` cast regardless: it removes the *other* nondeterminism, since
`SUM(double precision)` is not order-deterministic under a parallel plan, and a
figure that changes between two identical requests is worse than one that differs
from `fsum` in the ninth decimal.

Note that `fetch_traces_since`'s docstring currently asserts "percentiles cannot
be computed SQL-side" as the reason it has no row cap. That claim is false —
ordered-set aggregates have existed since PostgreSQL 9.4. Correct that comment as
part of this work; leaving it would keep justifying the unbounded read.

**`compute_from_traces` does not change.** It stays the pure, unit-tested
definition of record and the path for callers holding rows. This mirrors what
`dora` already does: `compute_from_events` consumes a SQL-side-pre-aggregated
`cost` argument rather than summing raw rows itself. SQL-side aggregation
consumed by a pure function is this module's *established* pattern, not a
departure from it.

**Rejected: a row cap.** `fetch_traces_since`'s docstring rejects it correctly —
truncation silently understates counts and percentiles, which is worse than a
slow query. That reasoning argues for aggregating, not for shipping the
unbounded scan.

**What aggregating does and does not bound.** Be precise here, because it is easy
to overclaim. `GROUPING SETS` bounds the *transfer* and the *Python-side* work: it
does not bound the database scan, and the ordered-set aggregates still sort each
group's latency sample server-side. What changed is the shape of the risk, not its
existence:

- *Before*: N rows on the wire, N Python dicts, N-element Python lists, CPython
  `sorted()` — inside the API worker process, GIL-bound, per request.
- *After*: an index range scan on `idx_se_agent_traces_ts` plus a hash aggregate
  with per-group sorts, in the database, returning tens of rows.

That is a different order of concern, but it is not *no* concern, and the endpoint
already lives with exactly this shape: `fetch_cost_since` is
`SUM(cost_usd) ... WHERE ts >= %s GROUP BY job_id` — the same unbounded-window
aggregate, over the same table, on this same route, in production today. So an
unbounded-window aggregate on `/dora` is the endpoint's existing posture. If that
posture is wrong it is wrong for both queries, and changing it is a platform
decision about how the metrics route is served — not something this story should
decide unilaterally on the back of one added key.

Two bounded mitigations *are* this story's to take, and both reuse machinery the
repo already has:

1. **Bound the query.** Run the read under a transaction-local `statement_timeout`,
   the pattern `shared.postgres.client.probe_cursor` already establishes (the
   shared pool deliberately sets none globally, so each bounded read scopes its
   own). A pathological window is then cancelled server-side and falls into the
   empty-rollup literal, instead of pinning a pooled connection until the alias's
   15s timeout. That converts the worst case from "saturate and time out" into
   "degrade to empty" — which is already the endpoint's stated contract, so it
   costs no new semantics. Note the empty result this produces is exactly cause 4
   in §4.4's ambiguity list, which is why that list matters.
2. **Collapse concurrent polls.** Dashboard polling is the concurrency the risk
   actually names, and repeated identical queries are the cheapest thing in the
   world to deduplicate: cache the computed rollup in `shared.cache` under a
   short TTL keyed by `(window_days, job_id)`. Ten pollers then cost one query.
   Staleness of up to a minute on a 30-day cost rollup is not a meaningful loss of
   fidelity.

**Rejected for this story: incrementally maintained summary buckets.** A
materialized per-bucket rollup is the correct answer at sufficient scale, and it
is a project, not a story: a summary table, an incremental maintenance path,
backfill for existing rows, staleness semantics, and a new consistency question
("the summary says X, the raw traces say Y") that this endpoint does not have
today. The parent epic already places a built-out metrics pipeline (OTLP /
collector) out of scope; this is the same category of answer.

**Escalate on measurement, not on speculation.** Nobody has measured this query at
a real install's row count, and "might be slow at scale" is not a number. Record
one: run the aggregating query against the largest available `se_agent_traces` at
the default 30-day window and log the timing in the implementing PR. If p95 exceeds
roughly a third of the alias budget (~5s), that is the trigger to open the summary-
table story — with evidence attached, rather than building it speculatively now.

**Scope honesty.** This makes the story larger than "wire an existing function to
an existing route" — it adds a store function, a row-shape adapter, and
parity tests. Call it a 3, not a 2. The alternative is knowingly putting an
unbounded, retention-window-wide scan behind an HTTP GET, which is not a
trade worth making to protect a complexity score.

## 4. Changes, file by file

### 4.1 `backend/agents/software_engineering_team/shared/trace_store.py`

Add `fetch_trace_rollup_rows(cutoff, *, job_id=None)` — the aggregating read from
§3.5. It runs the `GROUPING SETS` query, splits the result by the `GROUPING()`
tags into the three views, and returns them already shaped as `CallRollup` field
dicts. Same best-effort contract as its neighbours: `[]`/empty on a disabled or
failing Postgres, logged at DEBUG, never raised.

Run it under a transaction-local `statement_timeout` per §3.5, following
`shared.postgres.client.probe_cursor`'s pattern, so a pathological window is
cancelled server-side rather than pinning a pooled connection; a timeout returns
empty like any other failure, preserving the best-effort contract.

`fetch_traces_since` stays — it is still the right read for a caller that wants
raw rows, and `compute_from_traces` still consumes them. Correct its docstring's
"percentiles cannot be computed SQL-side" claim (§3.5).

The `cache_read_ratio` is **not** computed in SQL: it is derived from sums the
query already returns, so deriving it in Python keeps one definition of the ratio
(and its `None`-when-denominator-is-zero rule) rather than two that can drift.
Same for rounding.

### 4.2 `backend/agents/software_engineering_team/api/routes/status.py`

1. Extract the current body of `metrics_dora` into `_dora_payload(window)`
   verbatim — no behavior change, so the existing fallback test keeps passing on
   its assertions about DORA fields.
2. Add `_rollup_payload(window)` per §3.3, built on the §4.1 aggregating read
   rather than `compute_agent_rollup`'s row-materializing path (§3.5), and wrap it
   in the short-TTL `shared.cache` entry from §3.5 so concurrent dashboard polls
   collapse to one query. A cache miss, a cache-backend outage, or a stale-read
   failure must degrade to a live query and then to the empty literal — never
   raise.
3. Rewrite `metrics_dora` as the three-line composition in §3.3, and extend its
   docstring: what the new key is, that it is additive, and that it is empty
   rather than absent when there is no trace data.
4. Update the module docstring's one-line summary (currently "supervisor logs,
   health, and DORA metrics") to mention the rollup.

Return type stays `-> dict`, matching every other handler in this router; no
Pydantic response model is introduced. (`DoraMetrics` and `AgentRollupMetrics`
are the schema of record, and both already have drift-guard tests.)

### 4.3 `backend/agents/software_engineering_team/tests/test_api_metrics.py`

One existing test needs updating, and it is the one easy thing to miss:

- `test_metrics_dora_falls_back_to_zeroed_shape_on_compute_failure` asserts
  `set(body.keys()) == set(DoraMetrics(...).to_dict().keys())`. It must become
  `... == expected_keys | {"agent_rollup"}`.

**Isolation tests must use non-empty sentinels in both directions.** The obvious
formulation of these two tests proves nothing. Under `pytest` there is no
`POSTGRES_HOST`, so an unpatched DORA payload is *already* zeroed and an
unpatched rollup is *already* empty — meaning "DORA survived a rollup failure"
and "a single shared `try`/`except` zeroed both" produce byte-identical
responses. The assertion passes either way and the §3.3 property goes untested.

The fix is to stub the **surviving** side with a distinctive value and assert it
comes back unchanged:

- *Rollup fails, DORA survives*: patch `compute_dora` to return a
  `DoraMetrics(deployment_count=7, total_cost_usd=1.25, ...)` sentinel **and**
  patch the rollup read to raise. Assert `body["deployment_count"] == 7` and
  `body["total_cost_usd"] == 1.25` — not merely that the keys exist. A shared
  fallback would return `0`, failing the test as it should.
- *DORA fails, rollup survives*: patch `compute_dora` to raise **and** patch the
  §4.1 aggregating read to return rows for two agent keys. Assert the DORA half
  is the zeroed literal *and* that `agent_rollup["by_agent"]` is non-empty with
  the expected `call_count`. A shared fallback would return `{}`.

New tests:

| Test | Method | Asserts |
|---|---|---|
| Populated window | patch the §4.1 aggregating read to return groups across two agent keys and two phases | all three views' keys, plus spot-checked `total_cost_usd`, `call_count`, `cache_read_ratio` |
| Empty window | patch it to return no groups | all three dicts are `{}`, `window_days` echoes the request, 200 |
| Postgres unset | no patching (the pytest env has no `POSTGRES_HOST`) | 200 with an empty rollup — the real code path, not a stub |
| Rollup fails, DORA survives | sentinel `DoraMetrics` + rollup read raises | the sentinel's non-zero values survive verbatim; `agent_rollup` is the empty literal |
| DORA fails, rollup survives | `compute_dora` raises + rollup read returns groups | DORA half is the zeroed literal; `agent_rollup` is non-empty |
| Literal drift guard | compare the empty-rollup literal's keys against `AgentRollupMetrics(window_days=1.0, computed_at="x").to_dict().keys()` | mirrors the existing DORA drift guard |
| Window is shared | request `window_days=7` | both `body["window_days"]` and `body["agent_rollup"]["window_days"]` are `7.0` |

Separately, in `test_agent_rollup.py`: a **parity test** asserting the §4.1
aggregating read and `compute_from_traces` produce identical `CallRollup`s for the
same underlying rows — the guard that keeps §3.5's SQL/Python correspondence from
drifting. Run it against the live-Postgres CI job (the SQL is the thing under
test, so a fake cursor would test nothing); if that job is not available for this
suite, assert the correspondence at the row-shape adapter instead and say so.

Patching note: both `compute_agent_rollup` and the new read resolve `trace_store`
via a function-local import, so `monkeypatch.setattr(trace_store, ..., ...)` on
the module object takes effect at call time.

### 4.4 Documentation

**`backend/agents/software_engineering_team/README.md`** — add a
`## Metrics and observability` section (the README currently documents the
metrics module only as a line in the project-layout tree). It should cover:

- `GET /dora?window_days=N` and the `/api/se/metrics` alias; the `[1, 365]` clamp
  and the shared window.
- Why the path avoids the word `metrics` (OTel `excluded_urls`) — currently only
  explained in a route docstring.
- The `agent_rollup` key: the three grouping views and when to read each
  (`by_agent` for tiering candidates, `by_phase` for wall-clock hot spots,
  `by_agent_phase` for the pair, because an agent's token and cache profile can
  differ materially across phases).
- Every `CallRollup` field, with the two reading rules that are easy to get
  wrong: **`None` means no sample, `0` means a real zero** (a `0.0`
  `cache_read_ratio` means calls happened, tokens were processed, and none were
  served from cache — materially different from `None`); and the ratio's
  denominator is prompt-side tokens only (`cache_read + cache_creation + input`),
  because output tokens are never cache-eligible and cache-creation tokens are a
  genuine miss at call time.
- A one-line `curl` example plus a `jq` one-liner that sorts `by_agent` by
  `total_cost_usd` — the actual question this endpoint exists to answer.
- **An empty rollup is ambiguous — do not document it as one diagnosis.** The
  read cannot distinguish its own failure modes: `fetch_traces_since` (and the
  §4.1 aggregating read, which keeps the same contract) returns empty *both* when
  no rows match *and* when the query fails, and the route's own fallback returns
  the empty literal on any exception. So `{}` means one of at least five things,
  and the README must list them rather than pick one:
  1. The window genuinely contains no SE-attributed LLM calls (an idle install —
     the common, healthy case).
  2. The sink is opted out (`SE_TRACE_TO_POSTGRES` set falsy).
  3. Postgres is not configured (`POSTGRES_HOST` unset).
  4. Postgres is configured but the query failed — logged at DEBUG in
     `trace_store`, invisible in the response.
  5. Rows existed but were pruned (`SE_TRACE_RETENTION_DAYS`, default 30) before
     the requested window could see them.

  Order the operator's checks accordingly: confirm calls actually happened in the
  window first, then the sink flag, then the DEBUG logs — not "assume the sink is
  broken". If distinguishing these from the response itself is ever wanted, that
  is a separate health/error-state surface, deliberately not in scope here (an
  error key on the payload would change the shape this story promises to leave
  alone). Link `SE_TRACE_TO_POSTGRES` and `SE_TRACE_RETENTION_DAYS` in
  `docs/ENV_VARS.md`.
- The query shape from §3.5: the endpoint aggregates server-side, so a wide
  window is bounded work rather than a full-table materialization — worth stating
  so nobody reintroduces the row-materializing read for convenience.

**`docs/ENV_VARS.md`** — the `SE_TRACE_TO_POSTGRES` entry currently says the
traces are "the substrate the metrics endpoint reads for per-job and total
spend". Extend that sentence to name the per-agent/per-phase rollup as the second
consumer and cross-reference the new README section, so the trace-sink variable
and the endpoint that surfaces it point at each other in both directions.

### 4.5 `user-interface/src/app/models/se-metrics.model.ts` (optional, recommended)

The model's docstring claims it mirrors `DoraMetrics.to_dict()`; after this
change that is no longer the whole payload. Add `AgentCallRollup` and
`AgentRollup` interfaces and an **optional** `agent_rollup?: AgentRollup` field.

Type declarations only — no component, template, service, or chart changes (a
frontend dashboard is explicitly out of scope). Optional because existing specs
and fixtures construct `SeMetrics` without the key and must keep typechecking.
Interfaces emit no runtime code, so frontend line coverage is unaffected.

## 5. Verification

```bash
# From backend/
make lint                                   # ruff check + format, line-length 120
python -m pytest agents/software_engineering_team/tests/test_api_metrics.py -v
python -m pytest agents/software_engineering_team/tests/test_agent_rollup.py -v
python -m pytest unified_api/tests/test_job_proxy_routes.py -k se_metrics -v

# Coverage on both modified source files (90% floor)
python -m pytest agents/software_engineering_team/tests/test_api_metrics.py \
  agents/software_engineering_team/tests/test_agent_rollup.py \
  --cov=software_engineering_team.api.routes.status \
  --cov=software_engineering_team.shared.trace_store --cov-report=term-missing

# The SQL in §4.1 needs a real server — run the live-Postgres path for the
# parity test; a fake cursor would not exercise percentile_cont/percentile_disc
python -m pytest agents/software_engineering_team/tests/test_observability_stores_pg.py -v

# From user-interface/ — only if §4.5 is included
npx tsc --noEmit && npm test
```

The unified-API alias tests stub the upstream body, so they should pass
unchanged; running them is a check that the assumption in §2 (additive keys pass
through the alias untouched) holds.

Also verify by hand, once, against a populated database: the §4.1 aggregating
read and `compute_from_traces` over the same window must agree field-for-field.
That is the claim §3.5 rests on, and it is cheap to confirm directly.

## 6. Risks

| Risk | Mitigation |
|---|---|
| The existing key-set assertion in `test_api_metrics.py` fails | Anticipated in §4.3 — it is the intended signal that the response shape changed, not a surprise |
| A rollup failure degrades the DORA payload | §3.3's split failure boundaries, tested with non-empty sentinels in both directions (§4.3) — the naive form of that test proves nothing |
| An HTTP-reachable unbounded scan over the retention window | §3.5: aggregate in SQL via `GROUPING SETS` + ordered-set aggregates; one row per group, never the raw rows. This was the plan's original mistake, corrected |
| Aggregating bounds transfer but **not** the database scan | Acknowledged in §3.5, not papered over: a `statement_timeout` turns the worst case into "degrade to empty", and a short-TTL cache collapses concurrent polls. The same unbounded-window aggregate (`fetch_cost_since`) already serves this route today; a summary table is the escalation, gated on a measured p95 rather than speculation |
| SQL-side math diverges from the unit-tested `_stats` helpers | §3.5's parity table. Percentiles, token sums and counts are exact; `total_cost_usd` is **not** — the `float8 → numeric` cast is a different arithmetic domain than `math.fsum`, so `compute_from_traces` is canonical and the parity test compares cost within `1e-9` |
| Operators misread an empty rollup as a broken sink | §4.4 documents all five causes and the order to check them; the response genuinely cannot distinguish them |
| The empty-rollup literal drifts from `AgentRollupMetrics` | Drift-guard test, mirroring the one that already protects the DORA literal |
| A consumer reads `agent_rollup` as absent-when-empty | The key is always present; empty is three empty dicts, never `null` or missing. Stated in the route docstring, the README, and asserted in tests |

## 7. Explicitly out of scope

- A frontend dashboard or chart for the rollup (§4.5 is type declarations only).
- Authentication or rate-limiting changes to the metrics route.
- A health/error-state surface that would let a caller distinguish "no data" from
  "the read failed" (§4.4) — it would change the response shape this story
  promises to leave alone.
- Incrementally maintained summary buckets for the rollup (§3.5) — the right answer
  at sufficient scale, but a project of its own, and gated on a measured p95 rather
  than opened speculatively.
- Alerting or thresholds on the reported numbers.
- Any change to the DORA metrics themselves.
- Backfilling traces for historical runs.

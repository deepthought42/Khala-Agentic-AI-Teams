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
- `_rollup_payload(window)` — function-local import of the §4.1 aggregating read
  (`trace_store.fetch_trace_rollup_rows`), **not** `compute_agent_rollup`: that
  wrapper calls `fetch_traces_since` and materializes every matching row, which is
  the exact risk §3.5 exists to remove. It derives `cutoff = now - window`
  itself — from the already-clamped argument, never the raw `window_days` query
  parameter, per the precondition below; the read takes a cutoff, not a window —
  and shapes the three views onto
  `AgentRollupMetrics`. Same function-local-import reasoning as `_dora_payload`; on
  any exception, logs and returns the empty-rollup literal
  `{"window_days": window, "computed_at": <now>, "by_agent": {}, "by_phase": {},
  "by_agent_phase": {}}`, mirroring `AgentRollupMetrics`' field defaults with the
  same "keep in sync with that dataclass" comment the DORA literal already
  carries.

Both helpers get explicit `Preconditions:`/`Postconditions:` docstring sections
per the repo's DbC mandate. Stating only one half of a contract the repo mandates in
full is how the other half gets invented, so both are spelled out here:

- **Preconditions:** `window` is the **already-clamped** value, in `[1, 365]`. The
  route clamps exactly once, at the top of `metrics_dora` (see the sketch above);
  neither helper re-clamps, and neither accepts the raw `window_days` query
  parameter. One clamping site, named — otherwise an implementer can reasonably
  write a helper that re-clamps internally, and now the bound lives in two places
  that can drift.
- **Postconditions:** never raises; always returns a complete shape.

### 3.4 No new query parameters

The route keeps exactly one window knob: the existing `window_days: float =
30.0`, clamped to `[1, 365]`, feeding both `compute_dora` and — via the
`cutoff = now - window` derivation in `_rollup_payload` (on the clamped value,
per §3.3's precondition) — the §4.1
aggregating read. (Not `compute_agent_rollup`; see §3.3.) That satisfies "the same
time-window parameter convention" with no new convention to document or clamp.

Deliberately deferred (each is a separate, additive change if it is ever
wanted):

- **`job_id` filter.** Both `compute_agent_rollup` and the §4.1 aggregating read
  accept it; the endpoint does not expose it. Adding it later is a new optional
  query param with no shape change.
- **`expected_agent_keys` / `expected_phases` densification.** The endpoint
  reports only what it observed. Densifying would need a canonical agent-key and
  phase list maintained somewhere; a stale list would silently report zero-call
  groups for agents that were renamed, which is worse than omitting them.

### 3.5 The HTTP read must aggregate in SQL, not materialize rows

**Response size is not the constraint; the scan is.** `by_agent_phase` is bounded
by (distinct agent keys) x (distinct phases) — tens of entries in practice.
**That is an empirical expectation, not an enforced bound**, and the plan should
not pretend otherwise: `agent_key` and `phase` are unconstrained `TEXT NOT NULL
DEFAULT ''` in the DDL, and `_record_to_row` writes whatever the record carries
(`getattr(record, "agent_key", "") or ""`) with no normalization, length cap, or
allowlist. Nothing stops a caller from minting a distinct key per call — a
templated or accidentally-interpolated agent name would do it — and the three
grouping sets then produce up to roughly `3n` rows for `n` traces. So the correct
statement of the win is **relative**: aggregating removes the per-call row
multiplier and makes transfer and Python memory proportional to the number of
*distinct* keys rather than the number of calls. That is a large constant-factor
reduction under any realistic key set and the right change regardless, but it is
not a constant bound, and constraining those dimensions is a separate story about
the write path, not this read. The `statement_timeout` below is what actually
bounds the pathological case. That says nothing
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
one row per group rather than one row per call:

```sql
SELECT agent_key, phase,
       GROUPING(agent_key) AS g_agent, GROUPING(phase) AS g_phase,
       COUNT(*)                                   AS call_count,
       COUNT(*)                                   AS latency_ms_sample_count,
       SUM(cost_usd::numeric)                     AS total_cost_usd,
       SUM(input_tokens)                          AS total_input_tokens,
       SUM(output_tokens)                         AS total_output_tokens,
       SUM(cache_read_tokens)                     AS total_cache_read_tokens,
       SUM(cache_creation_tokens)                 AS total_cache_creation_tokens,
       percentile_cont(0.5)  WITHIN GROUP (ORDER BY latency_ms) AS latency_ms_median,
       percentile_disc(0.95) WITHIN GROUP (ORDER BY latency_ms) AS latency_ms_p95
FROM se_agent_traces
WHERE ts >= %s
  AND (%s::text IS NULL OR job_id = %s)
GROUP BY GROUPING SETS ((agent_key), (phase), (agent_key, phase))
```

**The `job_id` predicate is not optional garnish — §4.1's signature is
`fetch_trace_rollup_rows(cutoff, *, job_id=None)`, and a query that omits it
silently ignores the argument**, returning organization-wide groups where the
caller asked for one job's. Written as a single always-bound parameter pair so
the SQL string stays constant (no branch, no f-string), `NULL` meaning "no
filter". Note `job_id` is `TEXT NOT NULL DEFAULT ''`, so the **empty string is a
real, matchable value**, not a synonym for "unfiltered" — `job_id=""` must select
the untagged rows, and `job_id=None` must select everything. Both cases get a
test; conflating them is the obvious implementation slip.

One query yields all three views; `GROUPING()` tags which set each row came from.

**Parity with the `_stats` helpers — exact for the statistics,
canonical-plus-tolerance for cost.**
The concern with moving math SQL-side is that the endpoint would report different
numbers than the unit-tested helpers. For the percentiles and the integer sums it
does not. For the cost sum it can, and the plan says so rather than overclaiming.

| Statistic | `_stats` (Python) | Postgres | Parity |
|---|---|---|---|
| `median` | sorted midpoint, **averaging** the two middle values at even `n` | `percentile_cont(0.5)` — linear interpolation, which at the median of an even sample *is* their average | **Exact**, and it rests on `latency_ms` being `INTEGER` (see the DDL): the two middle values are exact integers, so `(a + b) / 2` is exact in IEEE double on both sides |
| `p95` | nearest rank, `ordered[ceil(0.95n) - 1]`, no interpolation | `percentile_disc(0.95)` — first value whose cumulative distribution ≥ 0.95, i.e. `ordered[ceil(0.95n) - 1]` | **Exact** — `percentile_disc` selects an actual sample value, so there is no arithmetic to diverge |
| token sums, `call_count` | Python `int` accumulation | `SUM(<integer column>)`, `COUNT(*)` | **Exact** — integer arithmetic, no representation question — and, like the row below, it rests on the DDL rather than assuming it: all four token columns are `INTEGER NOT NULL DEFAULT 0`, and so is `cost_usd` (`DOUBLE PRECISION NOT NULL DEFAULT 0`), including the two columns added by the idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` migrations, which carry `NOT NULL DEFAULT 0` too. This matters because `SUM` returns SQL `NULL`, not `0`, for a group whose values are all `NULL` — which would diverge from the Python accumulation. If any of these columns ever became nullable, the query needs `SUM(COALESCE(col, 0))` |
| `latency_ms_sample_count` | `len(latencies)` — one sample per row | `COUNT(*)`, named explicitly (§3.5's query) | **Exact**, and it rests on `latency_ms` being **`NOT NULL`** in the DDL: every row contributes a sample, so the sample count equals `call_count`. If that column ever became nullable, `COUNT(*)` would overcount — `COUNT(latency_ms)` would be the correct aggregate and the two would diverge. Grounded here rather than assumed |
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
`total_cost_usd`.** The parity test asserts the percentiles, the token sums, and
both counts — `call_count` and `latency_ms_sample_count` — are *equal*, and that the two cost sums agree **within one unit in the last
reported decimal place, asserted as integer microdollars, not a float tolerance**
— see §4.3 for why a float bound cannot express it and why no tighter bound is
available: both sides round to 6 decimals internally, so the rounded values are the
only ones that exist to compare, and near a boundary they may legitimately differ
by exactly that unit. The README says the
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
  with per-group sorts, in the database, returning one row per distinct group
  (tens, for any realistic key set — see the cardinality note in §3.5).

That is a different order of concern, but it is not *no* concern, and the endpoint
already lives with exactly this shape: `fetch_cost_since` is
`SUM(cost_usd) ... WHERE ts >= %s GROUP BY job_id` — the same unbounded-window
aggregate, over the same table, on this same route, in production today. So an
unbounded-window aggregate on `/dora` is the endpoint's existing posture. If that
posture is wrong it is wrong for both queries, and changing it is a platform
decision about how the metrics route is served — not something this story should
decide unilaterally on the back of one added key.

**One** bounded mitigation is this story's to take, reusing machinery the repo
already has — and one candidate mitigation is deliberately *not* taken. Both
decisions are recorded, because the second is as load-bearing as the first:

1. **Bound the query — with a concrete number, not "the pattern".** Run the read
   under a transaction-local `statement_timeout`, as
   `shared.postgres.client.probe_cursor` establishes (the shared pool deliberately
   sets none globally, so each bounded read scopes its own).

   **The budget is `5s`, clamped to `[1s, 10s]`.** Naming it matters more than it
   looks: `probe_cursor` takes an explicit `timeout_s`, and the nearby
   `statement_timeout_ms()` accessor reads `POSTGRES_STATEMENT_TIMEOUT_MS`
   (default `5000`, **floor `0`, where `0` disables the timeout entirely**). An
   implementer "following the pattern" could therefore inherit a disabled bound,
   or one longer than the alias budget, and every test in §4.3 would still pass —
   the mitigation would be decorative. So:

   - Default `5s`, matching `POSTGRES_STATEMENT_TIMEOUT_MS`'s own default so the
     two do not drift.
   - **Clamp to a positive floor** (`1s`): a configured `0` must not disable this
     read's bound, whatever it does elsewhere.
   - **Ceiling `10s`, fixed and SE-local** — *not* derived from
     `SE_METRICS_ALIAS_TIMEOUT`, and the reason is worth stating because a previous
     revision of this plan got it wrong in both directions.

     The relationship to the alias timeout is real: a query budget at or above the
     client's patience means the client gives up first while the query runs on. So
     an earlier revision specified `min(10s, SE_METRICS_ALIAS_TIMEOUT - 5s)`.
     **That does not work, because the SE process cannot read that variable.**
     Verified: `SE_METRICS_ALIAS_TIMEOUT` is read in exactly one place —
     `unified_api/main.py:1603`, sizing the *unified API's* outbound httpx client —
     and appears in no compose service environment and in no `docs/ENV_VARS.md`
     entry. The unified API and the SE service are separate containers. An operator
     lowering it would set it where it is consumed; the SE process would fall back
     to the `15.0` default and derive a bare `10s` — the exact value the derivation
     existed to avoid, in exactly the scenario it was written for.

     So: a fixed `10s` ceiling, plus **an operator contract stated in the docs
     rather than computed in the code**. §4.4 adds a `docs/ENV_VARS.md` entry for
     `SE_METRICS_ALIAS_TIMEOUT` (it has none today) recording that lowering it below
     ~15s requires lowering `POSTGRES_STATEMENT_TIMEOUT_MS` correspondingly, and
     that **nothing enforces this across the process boundary**. A documented
     contract that operators can violate is weaker than a computed bound — but it
     is honest, whereas a computed bound reading an absent variable is a bound that
     silently isn't there.

     (For the record: this plan was meticulous about `POSTGRES_STATEMENT_TIMEOUT_MS`'s
     `0`-disables edge while hardcoding the other side of the same invariant, then
     "fixed" that by reaching for a variable in another process's environment. Two
     rounds, two versions of the same mistake — assuming infrastructure exists
     without reading it — which is why the risk table names that class rather than
     any individual instance.)

   Note the `5s` budget and the `~5s` escalation threshold below are deliberately
   the same number: a query that routinely approaches its own timeout *is* the
   signal to open the summary-table story.

   **`statement_timeout` bounds the query, not the request.** Two segments sit
   outside it, and neither is hypothetical:

   - **Pool acquisition.** `SET LOCAL` runs only once a connection is in hand.
     `pg_cursor` → `get_conn` calls `pool.connection()` with **no timeout**
     (`shared/postgres/client.py:206`), so an exhausted pool falls back to
     psycopg-pool's 30s default wait — *twice* the alias budget — before the
     statement bound is ever installed. The repo already has the bounded form:
     `check_connection` uses `pool.connection(timeout=timeout_s)` (`client.py:310`).
     **This read must acquire with an explicit timeout too**, budgeted inside the
     same `5s` (e.g. `2s` acquire + the remainder for the query), and the
     pool-exhaustion case gets a test: a stub pool that blocks on acquisition must
     produce the empty three-view shape within budget, not a 30s hang.
   - **The DORA half, which runs first and is unbounded.** See below.

   With the statement timeout and a bounded acquisition both in place, a
   pathological window on the **rollup read** is cancelled server-side and falls
   into the empty-rollup literal, instead of pinning a pooled connection until the
   alias's 15s timeout. That converts the worst case from "saturate and time out"
   into "degrade to empty" — which is already the endpoint's stated contract, so it
   costs no new semantics. Note the empty result this produces is exactly cause 4
   in §4.4's ambiguity list, which is why that list matters.

   That degradation is the rollup read's alone. The DORA half stays unbounded: it
   carries no `statement_timeout`, and nothing above changes that.
2. **Nothing else — and that is a deliberate reversal.** Earlier drafts of this
   plan also specified a poll-collapsing cache. That mitigation is now **deferred
   behind the same measurement gate as the summary table**, and the reasoning is
   worth recording because it is the most useful thing this plan learned about
   itself.

   The cache was introduced speculatively, for a concurrency problem nobody has
   measured on this query. It then generated four separate review findings in
   two rounds, each one correct:

   - `shared.cache` cannot express a short per-entry TTL (no TTL parameter on the
     protocol; one global `REDIS_CACHE_TTL_S`, default 3600s, shared with every
     other consumer; no expiry at all on the `MemoryBackend` fallback; colon-
     containing keys rejected before any call). So it had to become a local memo.
   - A local TTL dict does not collapse anything without a **per-key single-flight
     lock**: `metrics_dora` is a sync `def` handler running in the threadpool, so
     the miss → query → store sequence is not atomic and a cold key is a stampede.
   - `window_days` is an arbitrary float in `[1, 365]` on an **unauthenticated**
     route, so the memo and its lock map are unbounded-growth surfaces without an
     explicit size cap and expiry sweep.
   - Being process-global, it leaks between tests: the endpoint tests share the
     default 30-day key, so one test's cached value satisfies the next test's
     assertions without exercising the code under test.

   Each fix is individually reasonable. Together they are a bounded-LRU-with-
   single-flight-and-timed-waits — a cache implementation, carrying its own
   correctness burden and its own test surface, bolted onto a story whose subject
   is adding one key to a payload. When a speculative mitigation for an unmeasured
   risk produces four defects before a line of it is written, the mitigation is the
   problem. **Measure first.** The gate below decides whether it is needed at all,
   and if it is, it is its own story with its own tests — sized honestly instead of
   smuggled in as "roughly fifteen lines".

   If it is later built, the four findings above are its requirements list, and the
   endpoint tests need an autouse reset fixture from day one.

**The route has no end-to-end deadline, and this story does not give it one.**
State this plainly, because the ceiling's justification is easy to over-read.
`_dora_payload` runs **before** `_rollup_payload` and issues two **unbounded**
reads — `se_events.fetch_events_since` and `trace_store.fetch_cost_since`. So the
arithmetic that matters is not `5s < 15s`; it is `dora_time + acquire + 5s < 15s`.
A DORA half taking 11s succeeds today and would blow the alias budget once the
rollup's `5s` is appended.

Two things follow, and only one of them is this story's:

- **Not this story's:** the `/dora` route can already exceed the alias timeout
  today, from the DORA reads alone, with no rollup involved. Bounding those is a
  change to existing behaviour on a route this story is only adding a key to —
  the same "don't re-architect the endpoint while adding a payload field" line
  drawn for the summary table. If the measurement below shows the DORA half
  routinely near the budget, that is its own story, and a more urgent one than
  this rollup.
- **This story's:** stop claiming the rollup's bound guarantees the client sees a
  response. It guarantees the *rollup* is not the unbounded part — necessary, not
  sufficient. The `10s` ceiling is chosen to leave room for the DORA half at its
  *typical* cost, not to prove a route-level deadline that no component here can
  enforce. The measurement protocol should therefore record **DORA-half timing
  alongside the rollup's**, so the sum is a known number rather than an
  assumption.

**What `statement_timeout` does not cover.** Mitigation 1 is worth keeping — it is
three lines and it converts the common pathology into the endpoint's existing
"degrade to empty" contract. But it is not a complete worst-case bound, and
`probe_cursor`'s own docstring says so in the sentence this plan previously
quoted around: *"if the TCP path itself wedges (no server response at all),
`statement_timeout` cannot fire and the closing `ROLLBACK` can still block — that
residual case is backstopped by `bounded_probe`'s per-surface worker cap, not by
this bound."* Since `/dora` is a sync handler occupying a threadpool worker for
the duration, a wedged socket ties up that worker regardless of the server-side
timeout, and enough of them exhaust the pool even after alias clients have given
up.

Closing that residual means `shared.postgres.client.bounded_probe`
(`client.py:448`) — but it is `async def`, designed to offload blocking work *off
the event loop*, so using it requires converting `metrics_dora` to `async def`
and running both payload builders through it. That is a change to the route's
execution model, not a local addition, and it is the correct partner to the
poll-collapsing work rather than something to bolt on separately. It travels with
the deferred mitigation, behind the same gate. Stated here so the residual is
documented rather than discovered.

**Rejected for this story: incrementally maintained summary buckets.** A
materialized per-bucket rollup is the correct answer at sufficient scale, and it
is a project, not a story: a summary table, an incremental maintenance path,
backfill for existing rows, staleness semantics, and a new consistency question
("the summary says X, the raw traces say Y") that this endpoint does not have
today. The parent epic already places a built-out metrics pipeline (OTLP /
collector) out of scope; this is the same category of answer.

**Escalate on measurement, not on speculation.** Nobody has measured this query at
a real install's row count, and "might be slow at scale" is not a number. Record
one — but record it properly: **one execution cannot produce a p95.** A single run
is dominated by whether the buffer cache happened to be warm and what else the
server was doing, which is exactly the variance the threshold needs to see through.

**Run the benchmark with the `5s` timeout OFF** (raw query, or the budget raised
for the measurement). This is not a detail — with the timeout active the
measurement cannot produce the statistic the gate tests. Every run that would
exceed `5s` is cancelled server-side at ~`5s`, so durations are **censored at the
threshold**: record the cancelled call's wall time and p95 ≈ `5s`, which does not
*exceed* `5s`; discard cancelled runs and p95 < `5s` by construction. Either way the
trigger can never fire from measured durations — the same class of statistical
defect as measuring a p95 from one sample.

Record the **DORA half's timing in the same runs** (see the end-to-end note in
§3.5): the number that matters for the alias budget is `dora + acquire + rollup`,
and none of the three is currently known.

So: **20 executions**, timeout off, against the largest available `se_agent_traces`
at the default 30-day window, discarding the first (cold-cache) run, taken while the
install is under representative load rather than idle. Report the median and the p95
of the remaining 19 in the implementing PR. **If the p95 exceeds `5s`** — a third of
the alias budget, and the same number as the query's own timeout above — that is the
trigger to open the summary-table story, with the sample attached rather than a
single anecdote.

Note that 19 samples makes nearest-rank p95 the sample *maximum*, so it is maximally
sensitive to the outlier variance this protocol otherwise guards against. Report the
median alongside it and treat a p95 driven by a single run as a prompt to re-measure,
not as an automatic trigger.

**Once the timeout ships, durations stop being the signal.** In production the
observable is the **cancellation rate** — how often the read degrades to empty
because it hit its bound — not query latency, which is censored by construction.
That is the ongoing version of this gate, and it is why the cancellation deserves a
log level someone will actually see (§4.1).

If 20 runs are impractical against the only available data, say so and state the
threshold as a single-run bound instead. An honestly-labelled single measurement is
useful; a single measurement labelled "p95" is not.

**Scope honesty.** This makes the story larger than "wire an existing function to
an existing route" — it adds a store function, a row-shape adapter, the
`statement_timeout` clamp and its two fake-cursor tests, parity tests, and a
CI-wiring change so those tests actually run. It does **not** add a caching
layer, a per-entry TTL to `shared.cache`, or an async conversion of the route:
§3.5 defers all of that behind the measurement gate, after the speculative version
of it produced four review findings before a line was written. Call it a 3, not a 2.
The alternative is knowingly putting an
unbounded, retention-window-wide scan behind an HTTP GET, which is not a
trade worth making to protect a complexity score.

## 4. Changes, file by file

### 4.1 `backend/agents/software_engineering_team/shared/trace_store.py`

Add `fetch_trace_rollup_rows(cutoff, *, job_id=None)` — the aggregating read from
§3.5. It runs the `GROUPING SETS` query, splits the result by the `GROUPING()`
tags into the three views, and returns them already shaped as `CallRollup` field
dicts. Same best-effort contract as its neighbours — never raises, logs at DEBUG
— but its empty value is the **same three-view shape as its success value**:
`{"by_agent": {}, "by_phase": {}, "by_agent_phase": {}}` on a disabled or failing
Postgres, never a bare `[]`. A function whose success return is a three-view
mapping must not change type on failure; the caller then needs no normalization
step, and §4.3's "all three dicts are `{}`" assertion holds at the store boundary
as well as the payload boundary.

Run it under a transaction-local `statement_timeout` per §3.5, following
`shared.postgres.client.probe_cursor`'s pattern, so a pathological window is
cancelled server-side rather than pinning a pooled connection; a timeout returns
empty like any other failure, preserving the best-effort contract.

**One exception to the neighbours' DEBUG-only convention: log a query cancellation
(psycopg's query-cancelled error, SQLSTATE `57014`) at WARNING.** The return
contract is unchanged — still empty, still never raises — but the log level is not
a detail here. This timeout is the only remaining bound on this path, a fired
cancellation is the sole evidence a pathological window was actually hit, and the
resulting empty rollup is (per §4.4) ambiguous with four benign causes. At DEBUG it
is invisible at production log levels, which would leave the one signal that matters
indistinguishable from an idle install. Every other failure on this path stays at
DEBUG.

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
   rather than `compute_agent_rollup`'s row-materializing path (§3.5). **No
   caching layer** — §3.5 defers that behind the measurement gate, so this helper
   is a direct call under the `statement_timeout` bound. Keeping it uncached also
   keeps the endpoint tests honest: there is no process-global state to leak
   between them.
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
  `... == expected_keys | {"agent_rollup"}` — **and it needs the same env hardening
  as the Postgres-unset test below.** After §4.2's composition the route runs the
  rollup read unconditionally, so this test would execute it unpatched. Add
  `monkeypatch.delenv("POSTGRES_HOST", raising=False)`, or patch the §4.1 read to
  return the empty three-view shape. Without it the keys-only assertion stays green
  either way while silently reaching a live database wherever `POSTGRES_HOST` is
  exported — green, slow, and environment-dependent, the same defect class this
  plan's own review history already records once.

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
| Postgres unset | `monkeypatch.delenv("POSTGRES_HOST", raising=False)` — **do not** rely on the ambient env being unset; a developer or another CI job with it exported would silently exercise a live database instead of the guard | 200 with an empty rollup — the real code path, not a stub |
| Rollup fails, DORA survives | sentinel `DoraMetrics` + rollup read raises | the sentinel's non-zero values survive verbatim; `agent_rollup` is the empty literal |
| DORA fails, rollup survives | `compute_dora` raises + rollup read returns groups | DORA half is the zeroed literal; `agent_rollup` is non-empty |
| Literal drift guard | compare the empty-rollup literal's keys against `AgentRollupMetrics(window_days=1.0, computed_at="x").to_dict().keys()` | mirrors the existing DORA drift guard |
| Window is shared | request `window_days=7` | both `body["window_days"]` and `body["agent_rollup"]["window_days"]` are `7.0` |

**Two fake-cursor tests for the `statement_timeout` boundary**, in
`test_observability_stores_pg.py` or a store-level unit test as convenient:

| Test | Asserts |
|---|---|
| Timeout is installed **before** the aggregate, at the **exact** clamped value | the fake cursor records `SET LOCAL statement_timeout = <ms>` as the *first* statement and the `GROUPING SETS` query strictly after it. **Assert the exact value, parameterized over `POSTGRES_STATEMENT_TIMEOUT_MS`** — unset → `5000`, `2500` → `2500`, `0` → `1000` (floor), `30000` → `10000` (ceiling). A range assertion like "inside `[1000, 10000]`" is not a test: an implementation that ignores the variable entirely and hardcodes `10000` passes it, while violating both the `5s` default and a `1.5s` operator setting |
| Cancellation degrades, not raises | the fake cursor raises psycopg's query-cancelled error on the aggregate; the read returns the empty three-view shape and logs at **WARNING** (§4.1). Assert the level explicitly — `any(r.levelname == "WARNING" ... for r in caplog.records)`, not `caplog.at_level(logging.DEBUG)` — or the test passes against the silenced behaviour it exists to forbid |

These are not optional garnish. §3.5's cache deferral makes `statement_timeout` the
**only** remaining mitigation on this path, and none of the other planned tests
would notice its absence: the endpoint tests *that stub the read* patch
`fetch_trace_rollup_rows` wholesale — the Postgres-unset test deliberately does
not, but it exercises the disabled path, where no query runs and no timeout
applies — and the parity test only exercises successful aggregation. Omitting the
`SET LOCAL`, issuing it *after* the aggregate, or letting a cancellation propagate
would leave every other specified test green while restoring exactly the unbounded
request behaviour this plan exists to prevent. Asserting statement *order* is the
point — a timeout set after the query it was meant to bound is the failure that
looks correct in a diff.

Separately, in **`test_observability_stores_pg.py`** — a **parity test** asserting
the §4.1 aggregating read and `compute_from_traces`
agree over the same underlying rows: the guard that keeps §3.5's SQL/Python
correspondence from drifting. It belongs there and not in `test_agent_rollup.py`
because the SQL is the thing under test; a fake cursor would exercise none of
`percentile_cont`/`percentile_disc`/`GROUPING SETS`, so a unit-suite home would
let the guard pass while never running against a real server.

**That file is not currently run by CI, and this story must wire it in.** An
earlier draft called it "the suite already wired to the live-Postgres job", which
is false — verified in `.github/workflows/ci.yml`: the SE unit invocation runs
`-m "not integration"`, and the Postgres job runs `-m integration` against only
`../unified_api/tests/test_integration_smoke.py`. `test_observability_stores_pg.py`
carries `pytestmark = pytest.mark.integration` and the team conftest skips
integration-marked tests unless `-m integration` is passed, so today the file runs
**nowhere**. Moving the parity test there without wiring would be strictly worse
than leaving it in the unit suite: a guard that cannot fail is worse than no guard,
because it reads as coverage.

So `.github/workflows/ci.yml` joins this story's file list, and **two edits are
required, not one** — adding the file to the invocation alone still leaves the
guard dormant:

1. **Add the path to the invocation**:
   `agents/software_engineering_team/tests/test_observability_stores_pg.py` on the
   live-Postgres job's `-m integration` line.
2. **Make the job trigger for SE changes.** `test-integration` is gated on
   `needs.changes.outputs.needs_integration == 'true'` (line 1258), and that flag
   is computed as `needs_integration = fan_out_full or shared_backend`
   (line 556). An ordinary `software_engineering_team/**` change sets neither, so
   the job does not run at all — meaning the implementing PR itself, and every
   later change to this SQL, would skip the only test that exercises it. The SE
   change flag must be OR-ed into that expression.

Confirm both by making the parity test fail deliberately once, on an SE-only diff,
and watching CI go red. A wiring change never observed failing is not verified —
and this is the second time this plan has specified a partial fix here, the first
being an invocation that ran a file the job never selected.

"Agree" is not "equal in every field" — per §3.5, assert **equality** for
`call_count`, **`latency_ms_sample_count`**, the token sums, and both percentiles.
The sample count is easy to drop: it is not a natural SQL aggregate name, so an
adapter that maps only the columns it sees leaves it at its dataclass default `0`
while the percentiles beside it are real. `latency_ms` is `NOT NULL`, so every row
in a group contributes a sample and the count equals `call_count` — the SQL names
it explicitly (§3.5) and the test asserts it rather than trusting the mapping.
`total_cost_usd` needs care,
and the obvious formulation is wrong:

**Compare the exposed values as integer microdollars, one unit apart at most.**
Neither side exposes an unrounded sum to compare: `compute_from_traces` rounds
internally (`total_cost_usd=round(math.fsum(costs), 6)`, `agent_rollup.py:193`) and
the §4.1 reader returns already-shaped `CallRollup` dicts, also rounded. An earlier
draft asked for a `1e-9` bound on the pre-rounding values, which is not
implementable without adding a raw-sum test seam to a pure function that has no
other reason to grow one — not worth it for a bound nothing consumes.

So the comparison is between two six-decimal quantities that may legitimately
differ by one unit in the last place. Assert exactly that, in the integer domain:

```python
assert abs(round(a.total_cost_usd * 1_000_000)
           - round(b.total_cost_usd * 1_000_000)) <= 1
```

**A float tolerance cannot express this bound, and `abs(a - b) <= 1e-6` is wrong.**
`1e-6` has no exact binary representation, and neither do the two six-decimal
values, so their difference is not `1e-6` — it is usually a little more. On this
section's own counterexample:

```
abs(7207.376828 - 7207.376827) == 1.0000003385357559e-06   # > 1e-6, assertion fails
```

Sampled locally over 200,000 adjacent six-decimal pairs, **73% exceed `1e-6`**
(worst observed `1.0000076e-06`). A `1e-6` float bound therefore rejects the
one-last-place difference roughly three times in four — the exact case it was
written to permit. The integer form has no such failure: over 300,000 adjacent
pairs up to `$1,000,000` the microdollar difference is never more than `1`.
`round(x * 1_000_000)` is exact for any `x` up to about `$9.007e9`
(`2**53` microdollars), which no cost rollup approaches. `decimal.Decimal(repr(x))`
scaled by `10**6` is equivalent if a `Decimal` is preferred; both were checked
against the same samples.

Worked counterexample for why a one-unit difference must be permitted at all,
reproduced locally: one million stored costs of `0.0072073768275` give

```
math.fsum        -> 7207.376827499999  -> rounds to 7207.376827
decimal-domain   -> 7207.3768275000000 -> rounds to 7207.376828
microdollar delta -> 1        (permitted)
```

The two domains land on opposite sides of a 6-decimal boundary, so the *reported*
values differ by one unit in the last place even though the unrounded sums differ
by `1e-12`. That is why no tighter bound is possible — not an argument for a
second, pre-rounding assertion: the unrounded sums are not exposed on either side,
and adding a raw-sum seam to `compute_from_traces` was considered and rejected
above. **One assertion, in the integer domain, against the number users actually
see.**

(Two earlier revisions of this section are recorded rather than silently deleted,
because this paragraph's history is the most useful thing in it. First, a revision
concluded the opposite here — "assert against the pre-rounding values… assert
both" — a leftover from the retracted `1e-9` formulation that survived the rewrite
of the paragraphs above it; it contradicted its own section and named no second
quantity to assert. Second, the bound spent four revisions as a *float* tolerance:
`1e-9`, then `1e-6` after `1e-9` was shown to be 1000x too tight, then `1e-6`
propagated to the sites that still said `1e-9` — and it was wrong the whole time,
because a decimal one-unit bound cannot be written as a binary float comparison at
all. Five separate review rounds touched this one assertion. The lesson is not
"pick a looser number": it is that the quantity being compared is decimal, so the
comparison belongs in an exact domain, and every round spent adjusting the float
constant was a round spent refining the wrong answer.)

Patching note: the route resolves the aggregating read through a function-local
import of `trace_store`, so `monkeypatch.setattr(trace_store,
"fetch_trace_rollup_rows", ...)` on the module object takes effect at call time.
(`compute_agent_rollup` resolves it the same way, but the route does not call it
— see §3.3.)

### 4.4 Documentation

**`backend/agents/software_engineering_team/README.md`** — add a
`## Metrics and observability` section (the README currently documents the
metrics module only as a line in the project-layout tree). It should cover:

- `GET /dora?window_days=N` and the `/api/se/metrics` alias; the `[1, 365]` clamp
  and the shared window.
- Why the path avoids the word `metrics` (OTel `excluded_urls`) — currently only
  explained in a route docstring — **and how the alias escapes that same filter.**
  The README must not leave those two bullets juxtaposed and unreconciled: a reader
  told that `metrics` paths are untraced, directly above a documented alias whose
  path is `/api/se/metrics`, is owed the answer. It is that the two apps are
  configured differently, and both halves are load-bearing. The SE app calls
  `create_team_app` without `excluded_urls` (`api/main.py:120`), inheriting the
  *unanchored* default `"health,healthz,ready,metrics"`
  (`shared/observability/otel.py:318`) — substring-matched, which is exactly why a
  business route in this app must not contain the word. The unified API, which
  serves the alias, passes *anchored* patterns
  (`excluded_urls="^/health$,^/healthz$,^/ready$,^/metrics$"`,
  `unified_api/main.py:1013`), so `^/metrics$` does not match `/api/se/metrics`:
  **the alias stays traced.** `instrument_fastapi_app`'s own docstring names this
  alias as the motivating case for the anchored form.
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
  window first, then the sink flag, then the logs — **and note that one narrow
  slice of these is visible at production log levels**: a `statement_timeout`
  cancellation logs at WARNING (§4.1).

  Read that evidence precisely, because the obvious over-reading is wrong. Cause 4
  is *any* query failure. Only the cancellation **subtype** logs at WARNING;
  connection refusal, pool exhaustion, and a malformed statement all still take
  `trace_store`'s generic DEBUG path and produce the same empty rollup. **So the
  absence of a WARNING rules out a timed-out query — it does not rule out cause
  4**, and an operator who treats it as exoneration for the database will go
  looking in the wrong place. Everything but the cancellation remains DEBUG-only.
  Check in that order — not "assume the sink is broken". If distinguishing these from the response itself is ever wanted, that
  is a separate health/error-state surface, deliberately not in scope here (an
  error key on the payload would change the shape this story promises to leave
  alone). Link `SE_TRACE_TO_POSTGRES` and `SE_TRACE_RETENTION_DAYS` in
  `docs/ENV_VARS.md`.
- The query shape from §3.5, in the honest form the risk table uses — not
  "bounded work", which overstates it. The endpoint aggregates server-side, so a
  wide window bounds the **transfer and result size** (one row per group) rather
  than materializing raw rows; the **database scan is still proportional to the
  window**. Say both halves, so nobody reintroduces the row-materializing read for
  convenience *and* nobody reads this as a performance guarantee.
- The route's exposure assumption. `GET /dora` is unauthenticated and this change
  widens what it serves from an aggregate cost figure to a per-agent, per-phase
  token and cost breakdown — a sharper picture of internal system behaviour, even
  though it contains no user data. Authentication is out of scope here (§7), so
  the README must state the assumption that route runs under: internal or trusted
  networks only. An undocumented trust assumption is the one that gets violated.

**`docs/ENV_VARS.md`** — two edits. First, **add a `SE_METRICS_ALIAS_TIMEOUT`
entry**; it has none today despite being the operator-facing half of §3.5's timeout
contract. It should state the default (`15s`), that it is read only by the unified
API's alias handler, and that lowering it below ~15s requires lowering
`POSTGRES_STATEMENT_TIMEOUT_MS` correspondingly — because the SE process cannot see
this variable and will not adjust its own bound. Second, the `SE_TRACE_TO_POSTGRES`
entry currently says the
traces are "the substrate the metrics endpoint reads for per-job and total
spend". Extend that sentence to name the per-agent/per-phase rollup as the second
consumer and cross-reference the new README section, so the trace-sink variable
and the endpoint that surfaces it point at each other in both directions.

### 4.5 `user-interface/src/app/models/se-metrics.model.ts` (optional, recommended)

The model's docstring claims it mirrors `DoraMetrics.to_dict()`; after this
change that is no longer the whole payload. Add `AgentCallRollup` and
`AgentRollup` interfaces and an **optional** `agent_rollup?: AgentRollup` field —
**and update that docstring** to say the model mirrors the full `GET /dora`
payload: `DoraMetrics.to_dict()` plus the optional `agent_rollup`. Diagnosing a
stale comment and then not prescribing its fix is how it survives the change that
made it stale.

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

# Coverage on both modified source files. Two things this command must do
# explicitly, neither of which it gets for free:
#
#   1. Include the store suites. The timeout and cursor tests (§4.3) live in
#      test_observability_stores*.py, and they exercise most branches of the
#      modified trace_store reader. Measuring --cov=...shared.trace_store while
#      omitting them reports a floor against tests that never ran.
#   2. Pass --cov-fail-under=90 by hand. The repo has two coverage
#      configurations — backend/pyproject.toml sets fail_under = 90, while
#      agents/software_engineering_team/pyproject.toml sets 80 — and the SE
#      pyproject also carries [tool.pytest.ini_options], so it can win pytest's
#      rootdir resolution when the args point inside that package. Which floor
#      a bare invocation actually applies depends on how pytest-cov and
#      coverage.py resolve their config here; rather than assert an answer this
#      plan has not verified, make the command independent of it. The explicit
#      flag also documents the intended floor at the point of use.
python -m pytest agents/software_engineering_team/tests/test_api_metrics.py \
  agents/software_engineering_team/tests/test_agent_rollup.py \
  agents/software_engineering_team/tests/test_observability_stores.py \
  --cov=software_engineering_team.api.routes.status \
  --cov=software_engineering_team.shared.trace_store \
  --cov-fail-under=90 --cov-report=term-missing

# The SQL in §4.1 needs a real server — run the live-Postgres path for the
# parity test; a fake cursor would not exercise percentile_cont/percentile_disc
python -m pytest -m integration \
  agents/software_engineering_team/tests/test_observability_stores_pg.py -v

# From user-interface/ — only if §4.5 is included
npx tsc --noEmit && npm test
```

The unified-API alias tests stub the upstream body, so they should pass
unchanged; running them is a check that the assumption in §2 (additive keys pass
through the alias untouched) holds.

Also verify by hand, once, against a populated database: the §4.1 aggregating
read and `compute_from_traces` over the same window must agree field-for-field —
**except `total_cost_usd`, which is compared as integer microdollars** per §3.5
(`abs(round(a * 1_000_000) - round(b * 1_000_000)) <= 1`, never a float tolerance):
one unit in
the last reported decimal place, the only bound the exposed (already-rounded)
values can support. A last-decimal difference there is expected, not a failed
check. That is the claim
§3.5 rests on, and it is cheap to confirm directly.

## 6. Risks

| Risk | Mitigation |
|---|---|
| The existing key-set assertion in `test_api_metrics.py` fails | Anticipated in §4.3 — it is the intended signal that the response shape changed, not a surprise |
| A rollup failure degrades the DORA payload | §3.3's split failure boundaries, tested with non-empty sentinels in both directions (§4.3) — the naive form of that test proves nothing |
| An HTTP-reachable unbounded scan over the retention window | §3.5: aggregate in SQL via `GROUPING SETS` + ordered-set aggregates; one row per group, never the raw rows. This was the plan's original mistake, corrected |
| Aggregating bounds transfer but **not** the database scan | Acknowledged in §3.5, not papered over: a `statement_timeout` turns the common pathology into "degrade to empty". The same unbounded-window aggregate (`fetch_cost_since`) already serves this route today. Poll-collapsing and a summary table are both escalations, gated on a measured p95 rather than speculation |
| `statement_timeout` is not a complete bound | Stated in §3.5 rather than left implicit: a wedged TCP path cannot be cancelled server-side, and a sync handler holds its threadpool worker regardless. `probe_cursor`'s own docstring names this residual and points at `bounded_probe`; closing it requires converting the route to `async def`, so it travels with the deferred poll-collapsing work rather than being bolted on |
| A partial fix that reads as a complete one | This plan has now twice specified CI wiring that would not have run the test it protects — first an invocation missing its marker, then an invocation on a job that SE changes never trigger. Both looked done. §4.3 now requires *observing* the parity test fail on an SE-only diff before the wiring counts as verified |
| A speculative mitigation growing its own defect surface | The poll-collapsing cache produced four correct review findings (no per-entry TTL in `shared.cache`; single-flight needed; unbounded key growth on an unauthenticated route; process-global state leaking between tests) before any of it was written. It is deferred behind the measurement gate, with those four findings recorded as its requirements list if it is ever built |
| A mitigation assumed to exist in shared infrastructure that does not | This plan made that mistake three times — `shared.cache` per-entry TTL, percentiles-in-SQL, and the parity suite's CI wiring were each asserted from plausibility rather than read. Every infrastructure claim in §3.5 and §4.1 now cites what was verified in the module or workflow. Treat an unverified claim about existing code as a defect, not a detail |
| SQL-side math diverges from the unit-tested `_stats` helpers | §3.5's parity table. Percentiles, token sums and counts are exact; `total_cost_usd` is **not** — the `float8 → numeric` cast is a different arithmetic domain than `math.fsum`, so `compute_from_traces` is canonical and the parity test compares cost as integer microdollars, `abs(round(a * 1_000_000) - round(b * 1_000_000)) <= 1` — one unit in the last reported place, matching §3.5, §4.3 and §5. Deliberately **not** a float tolerance: `abs(a - b) <= 1e-6` rejects ~73% of legitimate one-last-place differences, because neither `1e-6` nor the six-decimal values are exactly representable in binary |
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
- Any poll-collapsing cache, and the `async def` + `bounded_probe` conversion that
  should accompany it (§3.5). Deferred behind the same gate, for the same reason:
  measure the query before building mechanism around a hypothesis about it.
- Alerting or thresholds on the reported numbers.
- Any change to the DORA metrics themselves.
- Backfilling traces for historical runs.

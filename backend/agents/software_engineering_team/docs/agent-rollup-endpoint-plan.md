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
| Pure grouping/percentile math | `metrics/agent_rollup.compute_from_traces` | Done |
| Postgres-reading wrapper | `metrics/agent_rollup.compute_agent_rollup` | Done |
| Narrow column read | `shared/trace_store.fetch_traces_since` | Done, returns `[]` when Postgres is off or the query fails |
| The route to extend | `api/routes/status.py:66` (`metrics_dora`) | Serves DORA + cost, clamps `window_days` to `[1, 365]` |
| Unified-API alias | `unified_api/main.py:1586` (`se_metrics_alias`) | Forwards to `/dora` and returns `resp.json()` verbatim — **additive keys pass through with no change** |

Consequence: the "Postgres unset / empty table" case is already non-erroring at
the source. `fetch_traces_since` returns `[]`, `compute_from_traces` produces a
well-formed `AgentRollupMetrics` with three empty dicts. The route work is
wiring plus a defensive fallback, not new error handling.

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

### 3.5 Payload size

`by_agent_phase` is bounded by (distinct agent keys) x (distinct phases) actually
observed in the window — tens of entries, not thousands, because the grouping
happens over agent identities, not calls. No pagination or row cap is warranted.
(`fetch_traces_since` deliberately has no row cap; percentiles cannot be computed
SQL-side, so a wide window reads every matching row. That is a pre-existing
property of the read path, unchanged here, and worth noting in the README so
operators know a 365-day window is a real query.)

## 4. Changes, file by file

### 4.1 `backend/agents/software_engineering_team/api/routes/status.py`

1. Extract the current body of `metrics_dora` into `_dora_payload(window)`
   verbatim — no behavior change, so the existing fallback test keeps passing on
   its assertions about DORA fields.
2. Add `_rollup_payload(window)` per §3.3.
3. Rewrite `metrics_dora` as the three-line composition in §3.3, and extend its
   docstring: what the new key is, that it is additive, and that it is empty
   rather than absent when there is no trace data.
4. Update the module docstring's one-line summary (currently "supervisor logs,
   health, and DORA metrics") to mention the rollup.

Return type stays `-> dict`, matching every other handler in this router; no
Pydantic response model is introduced. (`DoraMetrics` and `AgentRollupMetrics`
are the schema of record, and both already have drift-guard tests.)

### 4.2 `backend/agents/software_engineering_team/tests/test_api_metrics.py`

One existing test needs updating, and it is the one easy thing to miss:

- `test_metrics_dora_falls_back_to_zeroed_shape_on_compute_failure` asserts
  `set(body.keys()) == set(DoraMetrics(...).to_dict().keys())`. It must become
  `... == expected_keys | {"agent_rollup"}`, and should additionally assert the
  rollup is still populated (empty, not missing) when *only* the DORA
  computation blows up — that is the §3.3 independence property, under test.

New tests:

| Test | Method | Asserts |
|---|---|---|
| Populated window | monkeypatch `trace_store.fetch_traces_since` to return a handful of rows across two agent keys and two phases | `agent_rollup.by_agent` / `by_phase` / `by_agent_phase` keys and a spot-checked `total_cost_usd`, `call_count`, `cache_read_ratio` |
| Empty window | monkeypatch `fetch_traces_since` to return `[]` | all three dicts are `{}`, `window_days` echoes the request, status 200 |
| Postgres unset | no monkeypatching (the pytest env has no `POSTGRES_HOST`) | 200 with an empty rollup — the real code path, not a stub |
| Rollup compute failure | monkeypatch `agent_rollup.compute_agent_rollup` to raise | 200, DORA payload intact and non-zeroed-by-the-rollup-failure, `agent_rollup` is the empty literal |
| Literal drift guard | compare the empty-rollup literal's keys against `AgentRollupMetrics(window_days=1.0, computed_at="x").to_dict().keys()` | mirrors the existing DORA drift guard |
| Window is shared | request `window_days=7` | both `body["window_days"]` and `body["agent_rollup"]["window_days"]` are `7.0` |

Patching note: `compute_agent_rollup` resolves `trace_store` via a
function-local import, so `monkeypatch.setattr(trace_store,
"fetch_traces_since", ...)` on the module object takes effect at call time. This
exercises the real grouping math end to end through the route rather than
stubbing the rollup itself, which is what makes the "populated window" test
worth writing.

### 4.3 Documentation

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
- The dependency on the trace sink: an empty rollup with a healthy pipeline means
  no traces are being persisted. Link to `SE_TRACE_TO_POSTGRES` in
  `docs/ENV_VARS.md`, and note `SE_TRACE_RETENTION_DAYS` bounds how far back a
  window can see.
- The wide-window read note from §3.5.

**`docs/ENV_VARS.md`** — the `SE_TRACE_TO_POSTGRES` entry currently says the
traces are "the substrate the metrics endpoint reads for per-job and total
spend". Extend that sentence to name the per-agent/per-phase rollup as the second
consumer and cross-reference the new README section, so the trace-sink variable
and the endpoint that surfaces it point at each other in both directions.

### 4.4 `user-interface/src/app/models/se-metrics.model.ts` (optional, recommended)

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

# Coverage on the one modified source file (90% floor)
python -m pytest agents/software_engineering_team/tests/test_api_metrics.py \
  --cov=software_engineering_team.api.routes.status --cov-report=term-missing

# From user-interface/ — only if §4.4 is included
npx tsc --noEmit && npm test
```

The unified-API alias tests stub the upstream body, so they should pass
unchanged; running them is a check that the assumption in §2 (additive keys pass
through the alias untouched) holds.

## 6. Risks

| Risk | Mitigation |
|---|---|
| The existing key-set assertion in `test_api_metrics.py` fails | Anticipated in §4.2 — it is the intended signal that the response shape changed, not a surprise |
| A rollup failure degrades the DORA payload | §3.3's split failure boundaries, with a dedicated test |
| A wide window reads a large number of trace rows | Pre-existing property of `fetch_traces_since`; documented in the README rather than papered over with a row cap that would understate percentiles |
| The empty-rollup literal drifts from `AgentRollupMetrics` | Drift-guard test, mirroring the one that already protects the DORA literal |
| A consumer reads `agent_rollup` as absent-when-empty | The key is always present; empty is three empty dicts, never `null` or missing. Stated in the route docstring, the README, and asserted in tests |

## 7. Explicitly out of scope

- A frontend dashboard or chart for the rollup (§4.4 is type declarations only).
- Authentication or rate-limiting changes to the metrics route.
- Alerting or thresholds on the reported numbers.
- Any change to the DORA metrics themselves.
- Backfilling traces for historical runs.

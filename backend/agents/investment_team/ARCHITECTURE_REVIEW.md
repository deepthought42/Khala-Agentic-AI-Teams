# Strategy Lab Team -- Architecture Review

**Date**: 2026-04-06
**Reviewer**: Principal Solutions Architect (Security & Distributed Systems)
**Scope**: Strategy Lab agents, orchestration, API layer, market data service

---

## Executive Summary

The Strategy Lab implements an automated swing-trading strategy research pipeline: ideation, backtesting, paper trading, and promotion gating. The domain models (Pydantic), trade simulation engine, multi-provider market data service, and safety gates (PolicyGuardian, PromotionGate) are well-engineered.

However, the team has **not adopted the AWS Strands Agents SDK** that peer teams (architect-agents, sales\_team) use successfully. Combined with an LLM-per-bar simulation design that produces thousands of LLM calls per backtest, inadequate prompt injection defenses, fragile distributed state management, and workflow logic embedded in the HTTP layer, there are systemic weaknesses across cost, security, reliability, and capability.

This review identifies 10 issues ranked by severity with specific file references, and provides a phased migration roadmap with rollback criteria for each phase.

---

## Issues

### CRITICAL-1: LLM-Per-Bar Simulation Is Prohibitively Expensive

| Attribute | Detail |
|-----------|--------|
| **Files** | `trade_simulator.py:88-155` (`evaluate_bar`), `backtesting_agent.py`, `paper_trading_agent.py` |
| **Impact** | Cost, latency, scalability |

`TradeSimulationEngine.run()` calls the LLM for every qualifying bar in the price history. The `max_evaluations=5000` cap confirms this is a known concern. Every call uses `think=True` (extended thinking tokens) -- the most expensive inference mode.

**Cost estimate**: A batch of 5 strategy cycles at ~5,000 evaluations each = ~25,000 LLM calls. With any cloud LLM, this is financially untenable.

**Root cause**: The LLM is used as a stateless bar-by-bar rule interpreter. It re-reads the full strategy definition and re-interprets the same rules on every bar, instead of interpreting them once to produce deterministic evaluation criteria.

**Recommendation -- Tiered rule compilation**:

| Tier | Approach | LLM Calls | Use When |
|------|----------|-----------|----------|
| **Tier 1** | Compile technical/price rules into a `CompiledStrategy` Pydantic model with deterministic conditions. `CompiledRuleEvaluator` walks bars with zero LLM calls. | 1 (compilation) | Rules reference only price, volume, technical indicators |
| **Tier 2** | Batch-evaluate bars in groups of 5-10 with a single LLM call per group. | ~100-500 | Rules require non-deterministic signals (sentiment, macro) |
| **Tier 3** | Post-hoc LLM review of the full trade ledger. | 1 | Always (pattern analysis) |

**Security constraint**: The compiled-rule DSL must be a closed-form language with whitelisted operators and indicator functions. No `eval()` or dynamic code execution. The LLM's compiled output must be validated against a strict schema before the evaluator accepts it. If compilation fails, fall back to Tier 2.

**Expected improvement**: ~100-2500x reduction in LLM calls per backtest depending on signal complexity.

---

### CRITICAL-2: No Strands SDK Adoption

| Attribute | Detail |
|-----------|--------|
| **Files** | `strategy_ideation_agent.py`, `signal_intelligence_agent.py`, `backtesting_agent.py`, `paper_trading_agent.py` |
| **Impact** | Capability, observability, composability |

Every LLM-using agent calls `self.llm.complete_json()` from the internal `llm_service`. The architect-agents team demonstrates the Strands pattern (`architect-agents/agents/security.py`):

```python
# Strands pattern (architect-agents)
@tool
def security_architect(spec_summary: str, ...) -> str:
    agent = Agent(model=model, system_prompt=prompt,
                  tools=[file_read_tool, web_search_tool, document_writer_tool],
                  callback_handler=None)
    result = agent(context)
    return str(result)
```

**What the Strategy Lab lacks without Strands**:

- **No tool calling**: `StrategyIdeationAgent` cannot look up market data, compute indicators, or validate hypotheses mid-reasoning.
- **No agent composition**: Agents cannot call other agents as tools. The orchestrator pattern (`architect-agents/orchestrator.py:49-67`) enables multi-phase delegation.
- **No session persistence**: No `FileSessionManager` or `S3SessionManager` for conversation continuity.
- **No callback handlers**: No streaming observability during long-running LLM calls.

**Recommendation**: Migrate to Strands SDK as a hard dependency. Example target architecture:

```python
strategy_ideation_agent = Agent(
    model=model,
    system_prompt=IDEATION_PROMPT,
    tools=[
        fetch_market_snapshot,   # @tool wrapping MarketDataService
        compute_indicators,      # @tool wrapping pandas-ta / TA-Lib
        compile_strategy,        # @tool to validate rules are compilable
        run_backtest,            # @tool executing deterministic backtest
    ],
    session_manager=get_session_manager(session_id),
    callback_handler=SSECallbackHandler(run_id),
)
```

**Security note**: Tool access amplifies prompt injection risk. Each `@tool` must validate its inputs independently and never trust LLM-provided parameters for security-sensitive operations.

---

### CRITICAL-3: Prompt Injection Defenses Are Inadequate

| Attribute | Detail |
|-----------|--------|
| **File** | `signal_intelligence_agent.py:44-51` (`sanitize_brief_for_injection`) |
| **Impact** | Security |

The current defense is a single regex: `r"(?i)ignore (all )?(previous|prior) instructions"`. This is trivially bypassed with Unicode homoglyphs, instruction splitting, or indirect injection through market data fields.

**Attack surface**: Market data from Yahoo Finance, Twelve Data, CoinGecko, and Alpha Vantage is inserted into LLM prompts. A manipulated company name, news headline, or data description in any provider response could inject instructions. The signal brief flows into the ideation prompt inside `<signal_intelligence_brief>` delimiters -- a classic injection vector.

The Strands migration amplifies this: agents with tool access could be manipulated into calling tools with attacker-controlled parameters.

**Recommendations**:
1. Replace the single-regex sanitizer with multi-layer defense: strip non-ASCII from data fields, encode data as structured JSON rather than free-text prompt injection, implement output monitoring for unexpected tool call patterns.
2. Sanitize at every data boundary: market data responses, prior results text, user input to FinancialAdvisor.
3. Each `@tool` function must validate its own inputs against expected schemas.

---

### HIGH-4: FinancialAdvisorAgent Uses Regex Instead of LLM

| Attribute | Detail |
|-----------|--------|
| **File** | `agents.py:615-881` (`_extract_topic_data` -- 266 lines) |
| **Impact** | Accuracy, maintainability |

The method uses keyword matching, `re.finditer`, and a hardcoded US state abbreviation dict. The code acknowledges this gap on line 751: `"# The LLM-powered version would parse these more thoroughly"`.

**Failure examples**:
- `"twenty percent drawdown"` -- `_extract_number()` finds no digit-based number.
- `"150k but it varies"` -- `"varies"` won't exact-match keyword `"variable"`.
- Nuanced preference statements are lost to pattern matching.

**Recommendation**: Convert to a Strands `Agent` with structured extraction tools.

**PII constraint**: This agent collects income, net worth, tax info, and savings. LLM extraction means PII flows to the model provider. **This agent must use a local model** (Ollama local inference, not Cloud) or PII exposure must be explicitly documented and accepted. The current regex approach, despite limitations, keeps PII local.

---

### HIGH-5: Workflow Orchestration Lives in API Layer

| Attribute | Detail |
|-----------|--------|
| **File** | `api/main.py:898-1244` (`_run_one_strategy_lab_cycle`, `_strategy_lab_worker`) |
| **Impact** | Testability, reusability, separation of concerns |

The strategy lab workflow (ideation -> data fetch -> backtest -> analysis -> persist) is implemented as private functions in the FastAPI module. The `InvestmentTeamOrchestrator` (`orchestrator.py`) only handles proposal/promotion.

**Consequences**:
- Cannot test workflow logic without spinning up FastAPI.
- Cannot reuse from CLI, notebooks, or alternative entry points.
- Module-level state (`_active_runs`, `_lock`, `_PersistentDict`) mixes HTTP concerns with business logic.

**Temporal is ignored**: The codebase supports Temporal for durable workflows (`TEMPORAL_ADDRESS`), designed exactly for long-running, crash-recoverable pipelines. Strategy Lab should use **Temporal activities for each cycle phase** with Strands agents providing intelligence within each activity.

**Recommendation**: Extract into `strategy_lab_orchestrator.py` with constructor-injected dependencies. Evaluate Temporal as the execution backbone.

---

### HIGH-6: Distributed State Is Fragile

| Attribute | Detail |
|-----------|--------|
| **Files** | `api/main.py:75-146` (module-level state), `api/main.py:1051-1076` (persistence) |
| **Impact** | Reliability, data integrity |

**Split-brain**: `_active_runs` (in-memory) and `_persist_run_state` (JobServiceClient) can diverge. The 5-minute cleanup timer deletes from memory while the job service retains the record. No reconciliation on restart.

**No idempotency**: If the process dies after persisting a `StrategyLabRecord` but before updating `completed_cycles`, the record is duplicated on resume.

**Lock contention**: A single `threading.Lock` protects all entity dicts. A network call to JobServiceClient while holding the lock blocks all API reads. Parallelizing cycles (as recommended) would serialize under this lock.

**Recommendations**:
- JobServiceClient as single source of truth; `_active_runs` as read-through cache with TTL eviction.
- Deterministic cycle IDs (`{run_id}-cycle-{n}`) with duplicate detection before execution.
- Per-entity locks or async with proper database transactions.

---

### MEDIUM-7: No Market Data Caching or Integrity Checks

| Attribute | Detail |
|-----------|--------|
| **File** | `market_data_service.py` |
| **Impact** | Cost, latency, reliability |

No caching -- repeated fetches for the same symbols across cycles. Free-tier rate limits (Twelve Data: 800 req/day) make this fragile. No integrity validation -- a poisoned provider response corrupts all cycles.

**Recommendations**:
- In-memory TTL cache keyed by `(symbol, asset_class, start_date, end_date)`, 1-hour TTL.
- Integrity checks: reject bars where close >20% from previous bar without volume confirmation. Log cross-provider discrepancies.

---

### MEDIUM-8: Generic Exception Handling

| Attribute | Detail |
|-----------|--------|
| **Files** | ~28 occurrences of `except Exception` across 7 files |
| **Impact** | Reliability, debuggability |

The `llm_service.interface` defines `LLMRateLimitError`, `LLMTemporaryError`, `LLMPermanentError`, `LLMJsonParseError`, but the investment team catches bare `Exception` everywhere (e.g., `strategy_ideation_agent.py:359,397`).

**Recommendation**: Rate limits -> exponential backoff. Permanent errors -> abort immediately. JSON parse errors -> retry with adjusted temperature.

---

### MEDIUM-9: No Cross-Agent Learning

| Attribute | Detail |
|-----------|--------|
| **File** | `strategy_ideation_agent.py:279-295` |
| **Impact** | Strategy quality |

Signal brief computed once per batch, never updated mid-batch. Cycle 5 receives the same stale brief from before cycle 1's backtest results were known. Paper trading receives no signal context at all.

**Recommendation**: Make the signal brief refreshable mid-batch via a `@tool` function within the Strands-migrated agent.

---

### MEDIUM-10: SSE Reliability

| Attribute | Detail |
|-----------|--------|
| **File** | `api/job_event_bus.py` |
| **Impact** | Client reliability |

No reconnection protocol (no `Last-Event-ID`), no backpressure, no event replay. Missed events during disconnect are permanently lost.

**Recommendation**: Add `Last-Event-ID` support with a bounded event buffer (last 100 events per run). On reconnection, replay missed events.

---

## Migration Roadmap

### Phase 0: Foundation
*Backward-compatible, no Strands dependency*

- [ ] Extract `strategy_lab_orchestrator.py` from `api/main.py`
- [ ] Replace single `_lock` with per-entity concurrency primitives
- [ ] Make `_active_runs` a read-through cache backed by JobServiceClient
- [ ] Add idempotent cycle IDs with duplicate detection
- [ ] Add market data cache with integrity checks
- [ ] Replace bare `except Exception` with specific `LLMError` subtypes
- [ ] Switch `evaluate_bar` to `think=False`
- [ ] Add `Last-Event-ID` support to SSE event bus

**Rollback gate**: `make test` error rate must not increase.

### Phase 0.5: Security Hardening

- [ ] Replace `sanitize_brief_for_injection` with multi-layer defense
- [ ] Add input sanitization at all data boundaries
- [ ] Define compiled-rule DSL schema with whitelisted operators
- [ ] Security review of all prompt templates
- [ ] Assess PII handling for FinancialAdvisorAgent
- [ ] Add auth to sensitive endpoints (`DELETE /strategy-lab/clear`, `POST /profiles`)

**Rollback gate**: Security review must pass.

### Phase 1: Rule Compilation Engine

- [ ] Define `CompiledStrategy` Pydantic model with closed-form DSL
- [ ] Create `CompiledRuleEvaluator` (deterministic, no LLM)
- [ ] Create `compile_strategy()` with schema validation
- [ ] Implement Tier 2 batch evaluation fallback
- [ ] A/B regression comparison against LLM-per-bar path

**Rollback gate**: Win rate divergence <15%, annualized return divergence <25% on 10 reference strategies.

### Phase 2: Strands SDK Migration

- [ ] Add `strands-agents>=1.0.0` as hard dependency
- [ ] Convert `StrategyIdeationAgent` to Strands `Agent` with `@tool` functions
- [ ] Convert `SignalIntelligenceExpert` to Strands `Agent`
- [ ] Convert backtesting/paper trading to compiled rules + Tier 2
- [ ] Wire `SSECallbackHandler` to `job_event_bus`

**Rollback gate**: End-to-end error rate increase <5% across 50 test runs.

### Phase 3: Session Persistence & Temporal Evaluation

- [ ] Create `session.py` (FileSessionManager local, S3SessionManager prod)
- [ ] Encrypt session data at rest (financial PII)
- [ ] Evaluate Temporal activities for cycle phases
- [ ] If viable, migrate `_strategy_lab_worker` to Temporal workflow

**Rollback gate**: Temporal crash recovery within 30 seconds on process kill.

### Phase 4: FinancialAdvisorAgent Migration

- [ ] Convert to Strands `Agent` with structured extraction tools
- [ ] **Hard requirement**: Local model only (PII)
- [ ] Property-based tests: 100+ edge-case inputs
- [ ] Regression test against current regex parser

**Rollback gate**: LLM extraction accuracy must be >=95%.

### Phase 5: Orchestration Enhancement (OPTIONAL)
*Gated on 30+ days stable operation of Phases 0-4*

- [ ] Register agents as `@tool` functions for lead orchestrator
- [ ] **Hard constraint**: Deterministic state machine bounds all decisions. LLM can advise transitions but hard gates (validation, promotion, policy guardian) are mandatory and non-skippable.

---

## Verification Matrix

| Category | Test | Phase |
|----------|------|-------|
| **Functional** | `make test` passes | All |
| **Functional** | A/B backtest comparison (10 strategies) | 1 |
| **Functional** | LLM call count reduction measurement | 1 |
| **Functional** | Advisor edge-case accuracy (100+ inputs) | 4 |
| **Security** | Prompt injection fuzzing at all data boundaries | 0.5 |
| **Security** | Compiled-rule DSL fuzz testing (no code execution) | 1 |
| **Security** | PII audit (advisor LLM calls stay local) | 4 |
| **Reliability** | Chaos testing: kill process mid-cycle x10, verify no duplicates | 0, 3 |
| **Reliability** | Lock contention: 3 concurrent readers during batch, p99 <500ms | 0 |
| **Reliability** | SSE reconnection: no events lost with Last-Event-ID | 0 |
| **Regression** | Each phase has explicit rollback criteria (see above) | All |

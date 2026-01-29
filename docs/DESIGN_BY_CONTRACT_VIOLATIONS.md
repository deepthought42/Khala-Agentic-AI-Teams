# Design by Contract Violations and Recommended Updates

This document lists all identified Design by Contract (DbC) violations in the codebase and the recommended updates. DbC uses **preconditions** (caller’s obligations before a call), **postconditions** (callee’s guarantees after the call), and **invariants** (conditions that always hold for a type or object).

---

## 1. strands_integration.py

### 1.1 Violation: `create_research_agent` ignores its parameter

**Issue:** The function advertises that the caller must provide an `LLMClient`, but the implementation ignores the `llm_client` argument and always builds an `OllamaLLMClient`. That breaks the contract: “caller provides LLMClient; implementation uses it.”

**Recommended fix:** Use the provided `llm_client` instead of constructing a new one.

**Before (violation):**
```python
def create_research_agent(llm_client: LLMClient) -> ResearchAgent:
    """
    Factory used by a Strands runtime (or any orchestrator) to construct the agent.
    The caller is responsible for providing an `LLMClient` implementation.
    """
    llm_client = OllamaLLMClient(  # BUG: ignores parameter
        model="llama3.1",
        base_url="http://127.0.0.1:11434",
    )
    return ResearchAgent(llm_client=llm_client)
```

**After (compliant):**
```python
def create_research_agent(llm_client: LLMClient) -> ResearchAgent:
    """
    Factory used by a Strands runtime (or any orchestrator) to construct the agent.

    Preconditions:
        - llm_client is not None.
    Postconditions:
        - Returns a ResearchAgent instance configured with the given llm_client.
    """
    assert llm_client is not None, "llm_client is required"
    return ResearchAgent(llm_client=llm_client)
```

---

### 1.2 Violation: `get_agent_spec` documentation does not match implementation

**Issue:** The docstring says the spec has a `handler` that is “callable accepting an input model instance and returning an output model.” In reality the spec has `handler_factory`, and that callable takes `(llm_client, payload)` and returns `ResearchAgentOutput`. The documented contract does not match the actual contract.

**Recommended fix:** Document the real contract: key `handler_factory`, signature `(llm_client: LLMClient, payload: Dict[str, Any]) -> ResearchAgentOutput`, and add pre/postconditions.

**Example (compliant docstring and contract):**
```python
def get_agent_spec() -> Dict[str, Any]:
    """
    Return a spec describing how to call this agent.

    A Strands host can use:
        - name: human-friendly identifier
        - input_model / output_model: Pydantic models
        - handler_factory: callable(llm_client, payload) -> ResearchAgentOutput

    Preconditions:
        - None (no arguments).
    Postconditions:
        - Returns a dict with keys "name", "description", "input_model", "output_model", "handler_factory".
        - handler_factory(llem_client, payload) expects payload to validate as ResearchBriefInput
          and returns ResearchAgentOutput.
    """
```

---

## 2. agent.py

### 2.1 Violation: `ResearchAgent.__init__` has no documented or enforced preconditions/invariants

**Issue:** The constructor does not document or enforce that `llm_client` is non-None or that `max_fetch_documents` is positive. The class therefore has no stated invariants (e.g. “llm is not None”, “max_fetch_documents >= 1”).

**Recommended fix:** Document preconditions and class invariants; add a development-time assertion for `max_fetch_documents >= 1` (and optionally for `llm_client is not None`).

**Example (compliant):**
```python
def __init__(
    self,
    llm_client: LLMClient,
    *,
    web_search: TavilyWebSearch | None = None,
    web_fetcher: SimpleWebFetcher | None = None,
    max_fetch_documents: int = 20,
) -> None:
    """
    Preconditions:
        - llm_client is not None.
        - max_fetch_documents >= 1.
    Invariants (after construction):
        - self.llm is not None.
        - self.max_fetch_documents >= 1.
    """
    assert llm_client is not None, "llm_client is required"
    assert max_fetch_documents >= 1, "max_fetch_documents must be at least 1"
    self.llm = llm_client
    ...
```

---

### 2.2 Violation: `run` has no explicit preconditions or postconditions

**Issue:** The main entry point does not state what the caller must guarantee (e.g. valid `ResearchBriefInput`) or what the implementation guarantees (e.g. type and constraints on `ResearchAgentOutput`).

**Recommended fix:** Add a short pre/post section to the docstring (and optionally an assertion that the result has the expected shape).

**Example (compliant docstring):**
```python
def run(self, brief_input: ResearchBriefInput) -> ResearchAgentOutput:
    """
    Execute the full research workflow and return structured output.

    Preconditions:
        - brief_input is a valid ResearchBriefInput (e.g. from model_validate).
    Postconditions:
        - Returns ResearchAgentOutput with query_plan (list), references (list,
          length <= brief_input.max_results), notes (str or None).
    """
```

---

### 2.3 Violation: Internal methods lack contract documentation

**Issue:** Methods such as `_parse_brief`, `_generate_queries`, `_run_searches`, `_fetch_documents`, `_score_documents`, `_summarize_documents`, and `_synthesize_overview` have no documented preconditions or postconditions, making it hard to reason about correctness and maintenance.

**Recommended fix:** Add one-line pre/post or “Expects/Returns” lines in each method’s docstring so the internal contract is explicit (e.g. “Expects normalized dict with core_topics, angle, constraints”; “Returns list of SearchQuery”).

---

## 3. llm.py

### 3.1 Violation: `LLMClient.complete_json` contract is underspecified

**Issue:** The abstract method does not state preconditions (e.g. prompt non-empty, temperature in a valid range) or postconditions (e.g. returns a dict, not None).

**Recommended fix:** Document preconditions and postconditions in the abstract base and in implementations.

**Example (compliant docstring):**
```python
@abstractmethod
def complete_json(self, prompt: str, *, temperature: float = 0.0) -> Dict[str, Any]:
    """
    Run the model with the given prompt and return a JSON-decoded dict.

    Preconditions:
        - prompt is a non-empty string.
        - 0.0 <= temperature <= 2.0 (or implementation-defined range).
    Postconditions:
        - Returns a (possibly empty) dict; never None.
    """
```

---

### 3.2 Violation: `OllamaLLMClient.__init__` has no preconditions

**Issue:** Parameters such as `timeout` and `model` are not documented or validated (e.g. timeout > 0, model non-empty).

**Recommended fix:** Document preconditions and add assertions for development.

**Example:**
```python
def __init__(
    self,
    model: str = "llama3.1",
    *,
    base_url: str = "http://127.0.0.1:11434",
    timeout: float = 120.0,
) -> None:
    """
    Preconditions:
        - model is a non-empty string.
        - timeout > 0.
        - base_url is a non-empty string.
    """
    assert model, "model name is required"
    assert timeout > 0, "timeout must be positive"
    assert base_url, "base_url is required"
    ...
```

---

### 3.3 Violation: `_extract_json` contract not documented

**Issue:** It is not stated that the method expects extractable JSON in `text` and guarantees to return a dict or raise.

**Recommended fix:** Document precondition (text contains parseable JSON) and postcondition (returns dict) or raises ValueError.

---

## 4. models.py

### 4.1 Violation: Model invariants not stated in docstrings

**Issue:** Pydantic already enforces some constraints (e.g. `ge=1`, `le=50`), but the class-level invariants (e.g. “relevance_score in [0, 1]”) are not stated in plain English in docstrings for readers and tools.

**Recommended fix:** Add a one-line “Invariants” (or “Constraints”) line to each model’s docstring summarizing key constraints (e.g. max_results in [1, 50], relevance_score in [0, 1]).

---

## 5. tools/web_fetch.py

### 5.1 Violation: `SimpleWebFetcher.__init__` has no preconditions

**Issue:** `timeout` is not documented or validated (e.g. timeout > 0).

**Recommended fix:** Document precondition “timeout > 0” and add `assert timeout > 0`.

---

### 5.2 Violation: `fetch` has no documented pre/postconditions

**Issue:** The contract is not explicit: caller must pass a valid `HttpUrl`; implementation returns a `SourceDocument` with that url (and may raise on failure).

**Recommended fix:** Add preconditions (url is valid HttpUrl) and postconditions (returns SourceDocument with url equal to input, or raises WebFetchError).

---

## 6. tools/web_search.py

### 6.1 Violation: `TavilyWebSearch.search` contract underspecified

**Issue:** No documented preconditions (e.g. max_results >= 1, recency_preference in allowed set) or postconditions (e.g. returns list of CandidateResult, length <= max_results).

**Recommended fix:** Document preconditions and postconditions; optionally assert max_results >= 1 in development.

**Example:**
```python
"""
Preconditions:
    - max_results >= 1.
    - recency_preference is None or one of the supported values (e.g. "latest_12_months", "no_preference").
Postconditions:
    - Returns a list of CandidateResult of length at most max_results.
    - Raises WebSearchError on API or network failure.
"""
assert max_results >= 1, "max_results must be at least 1"
```

---

## Summary

| Location | Violation | Fix |
|----------|-----------|-----|
| strands_integration.create_research_agent | Parameter ignored; contract broken | Use passed llm_client; add pre/post doc + assert |
| strands_integration.get_agent_spec | Doc says handler(input) but spec has handler_factory(llm, payload) | Align doc with handler_factory and signature |
| agent.ResearchAgent.__init__ | No preconditions/invariants | Document and assert llm_client non-None, max_fetch_documents >= 1 |
| agent.run | No pre/postconditions | Document pre (valid brief_input) and post (output shape) |
| agent (private methods) | No internal contracts | Add brief pre/post or Expects/Returns in docstrings |
| llm.LLMClient.complete_json | Contract underspecified | Add pre (prompt, temperature) and post (dict, not None) |
| llm.OllamaLLMClient.__init__ | No preconditions | Document and assert model, timeout, base_url |
| llm._extract_json | Contract not documented | Document pre/post or “raises ValueError” |
| models (Pydantic) | Invariants not in docstrings | Add Invariants/Constraints line per model |
| web_fetch.SimpleWebFetcher | No preconditions on __init__/fetch | Document and assert timeout; document fetch pre/post |
| web_search.TavilyWebSearch.search | No pre/postconditions | Document and assert max_results; document post and raises |

All recommended updates preserve existing behavior while making contracts explicit and adding lightweight development-time checks (assertions) where appropriate.

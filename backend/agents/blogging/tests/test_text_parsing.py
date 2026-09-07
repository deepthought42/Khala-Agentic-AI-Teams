"""Tests for the shared text-parsing helpers in ``shared/text_parsing.py``."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
from agents.blogging.shared import text_parsing as tp
from strands.types.exceptions import EventLoopException

# ---------------------------------------------------------------------------
# unwrap_llm_cause
# ---------------------------------------------------------------------------


def test_unwrap_llm_cause_unwraps_event_loop_exception() -> None:
    original = ValueError("boom")
    wrapped = EventLoopException(original)
    assert tp.unwrap_llm_cause(wrapped) is original


def test_unwrap_llm_cause_passes_through_plain_exception() -> None:
    exc = RuntimeError("plain")
    assert tp.unwrap_llm_cause(exc) is exc


def test_unwrap_llm_cause_passes_through_when_original_exception_is_none() -> None:
    wrapped = EventLoopException(None)
    assert tp.unwrap_llm_cause(wrapped) is wrapped


def test_unwrap_llm_cause_only_unwraps_one_level_of_nested_event_loop_exception() -> None:
    """A nested EventLoopException chain unwraps exactly one level.

    ``unwrap_llm_cause`` returns ``original_exception`` verbatim without
    recursing, so an EventLoopException wrapping another EventLoopException
    unwraps to that inner EventLoopException itself, not further down to its
    own original_exception.
    """
    innermost = ValueError("root cause")
    inner_wrapper = EventLoopException(innermost)
    outer_wrapper = EventLoopException(inner_wrapper)

    result = tp.unwrap_llm_cause(outer_wrapper)

    assert result is inner_wrapper
    assert result is not innermost
    assert isinstance(result, EventLoopException)


# ---------------------------------------------------------------------------
# extract_draft_after_marker
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        '{"draft": 0}\n---DRAFT---\n# Title\n\nBody text.',
        '{"draft": 0}\n---DRAFT---# Title\n\nBody text.',
        '{"draft": 0}---DRAFT---\n# Title\n\nBody text.',
        '{"draft": 0}---DRAFT---# Title\n\nBody text.',
    ],
)
def test_extract_draft_after_marker_handles_all_marker_variants(raw: str) -> None:
    assert tp.extract_draft_after_marker(raw) == "# Title\n\nBody text."


def test_extract_draft_after_marker_falls_back_to_json_draft_key() -> None:
    raw = '{"draft": "# Fallback title\\n\\nFallback body."}'
    assert tp.extract_draft_after_marker(raw) == "# Fallback title\n\nFallback body."


def test_extract_draft_after_marker_falls_back_to_fenced_json_draft_key() -> None:
    raw = '```json\n{"draft": "# Fenced\\n\\nBody"}\n```'
    assert tp.extract_draft_after_marker(raw) == "# Fenced\n\nBody"


def test_extract_draft_after_marker_rejects_non_string_draft_sentinel() -> None:
    assert tp.extract_draft_after_marker('{"draft": 0}') == ""


def test_extract_draft_after_marker_rejects_empty_string_draft() -> None:
    assert tp.extract_draft_after_marker('{"draft": "   "}') == ""


def test_extract_draft_after_marker_returns_empty_on_unparseable_text() -> None:
    assert tp.extract_draft_after_marker("not json and no marker at all") == ""


@pytest.mark.parametrize("raw", [None, "", 123, ["not", "a", "string"]])
def test_extract_draft_after_marker_returns_empty_for_none_empty_or_non_string_input(
    raw: Any,
) -> None:
    assert tp.extract_draft_after_marker(raw) == ""


# ---------------------------------------------------------------------------
# extract_json_array_from_text
# ---------------------------------------------------------------------------


def test_extract_json_array_from_text_matches_issue_required_keys() -> None:
    text = '[{"issue": "too vague", "severity": "high"}]'
    result = tp.extract_json_array_from_text(text, required_keys=("issue",))
    assert result == [{"issue": "too vague", "severity": "high"}]


def test_extract_json_array_from_text_matches_question_required_keys() -> None:
    text = '[{"question": "what is the source?"}]'
    result = tp.extract_json_array_from_text(text, required_keys=("question",))
    assert result == [{"question": "what is the source?"}]


def test_extract_json_array_from_text_skips_leading_prose() -> None:
    text = 'Here is the review:\n\n[{"issue": "unclear claim"}]\n\nThanks.'
    result = tp.extract_json_array_from_text(text, required_keys=("issue",))
    assert result == [{"issue": "unclear claim"}]


def test_extract_json_array_from_text_resumes_past_nested_bracket_in_non_match() -> None:
    """A non-matching array containing a nested ``[`` doesn't get re-entered and salvaged.

    This is the fixed-vs-drifted behavior the issue exists to preserve:
    resuming the scan at the decoded value's end (not one char past the
    opening bracket) means a nested "[" inside an already-rejected candidate
    can't be re-parsed on its own as if it were a fresh top-level match.
    Rejecting to ``search_from = i + 1`` here would instead re-enter the
    nested decoy array and incorrectly return it in place of the real
    payload that follows.
    """
    text = '[[{"issue": "nested-decoy"}], "filler"] then later: [{"issue": "the real one"}]'
    result = tp.extract_json_array_from_text(text, required_keys=("issue",))
    assert result == [{"issue": "the real one"}]


def test_extract_json_array_from_text_does_not_salvage_from_inside_decoded_value() -> None:
    """After a successful decode of a non-matching array, the scanner must not
    re-enter that already-decoded span looking for a nested match. The outer
    array's own top-level elements are a list and a string (neither a dict),
    so it correctly does not match required_keys — but its first element is
    itself an array containing a dict with a truthy "issue" key. A real match
    must not be salvaged from inside an already-rejected value.
    """
    text = '[[{"issue": "wrongly-salvaged", "fix": "z"}], "sibling"]'
    assert tp.extract_json_array_from_text(text, required_keys=("issue",)) is None


def test_extract_json_array_from_text_empty_array_fallback() -> None:
    text = "Some prose with an empty markdown link []() in it."
    result = tp.extract_json_array_from_text(text, required_keys=("issue",))
    assert result == []


def test_extract_json_array_from_text_returns_none_when_no_bracket_present() -> None:
    assert tp.extract_json_array_from_text("no brackets here", required_keys=("issue",)) is None


def test_extract_json_array_from_text_skips_schema_mismatched_array() -> None:
    text = '[1] then [{"issue": "real payload"}]'
    result = tp.extract_json_array_from_text(text, required_keys=("issue",))
    assert result == [{"issue": "real payload"}]


def test_extract_json_array_from_text_skips_unparseable_bracket() -> None:
    text = 'malformed [not valid json then [{"issue": "real payload"}]'
    result = tp.extract_json_array_from_text(text, required_keys=("issue",))
    assert result == [{"issue": "real payload"}]


def test_extract_json_array_from_text_accepts_array_when_any_element_matches() -> None:
    """An array matches (and is returned whole) if ANY element carries required_keys.

    Pins the "any", not "all", semantics: a real payload can contain
    individually malformed items alongside valid ones, and the whole array
    is still accepted and returned as-is (the caller's own per-item
    validation is expected to skip the non-matching elements).
    """
    text = '[{"issue": "ok"}, {"unrelated": 1}]'
    result = tp.extract_json_array_from_text(text, required_keys=("issue",))
    assert result == [{"issue": "ok"}, {"unrelated": 1}]


# --- Nested-array salvage regression ---------------------------------------
#
# The scanner resumes at the decoded value's end (``search_from = end``), not
# one character past the opening bracket. A private copy in
# ``blog_writer_agent/agent.py`` once ran the ``search_from = i + 1`` variant,
# which re-enters an already-decoded, already-rejected array and can salvage a
# nested ``[...]`` as if it were the real top-level payload. That copy is gone;
# the cases below are what keep it gone. Each is labelled either "regression"
# (fails under the drifted variant) or "characterisation" (passes under both,
# pinning behaviour that must not change alongside the fix).

# Regression fixture. The outer array's own elements are a list and a string —
# no dict, so it cannot match any ``required_keys``. Its first element is a
# nested array whose single dict carries *both* consumer keys, so neither
# parametrization below passes for the trivial reason that its key is absent.
_NESTED_DECOY = '[[{"question": "decoy-q", "issue": "decoy-i"}], "sibling"]'

# Regression fixture. A rejected array whose string value contains a bare
# ``[]``. A nested *dict* array cannot be used here: the escaped quotes JSON
# requires (``"[{\"question\": ...}]"``) make the inner text undecodable, so
# ``raw_decode`` fails at the ``{\`` and both variants skip it, turning the
# test into a no-op. An empty bracket pair is the only string-literal shape
# whose outcome actually diverges.
_BRACKET_IN_STRING = '[{"note": "cite []"}]'


@pytest.mark.parametrize("required_keys", [("question",), ("issue",)])
def test_extract_json_array_from_text_does_not_salvage_nested_decoy_for_either_consumer(
    required_keys: tuple[str, ...],
) -> None:
    """Regression: neither consumer salvages a decoy nested in a rejected array.

    Covers both call-site key shapes against one input: ``("question",)`` for
    ``identify_uncertainty_questions`` and ``("issue",)`` for
    ``llm_self_review``. Under the drifted ``search_from = i + 1`` variant both
    parametrizations return the decoy instead of ``None`` — and for
    ``("question",)`` that decoy reaches a human as a blocking uncertainty
    prompt, which is what made this bug worth a dedicated regression test.
    """
    assert tp.extract_json_array_from_text(_NESTED_DECOY, required_keys=required_keys) is None


def test_extract_json_array_from_text_finds_real_question_payload_after_decoy() -> None:
    """Regression: the fix does not over-correct into skipping real payloads.

    The positive control for
    ``test_..._does_not_salvage_nested_decoy_for_either_consumer``: resuming
    past a rejected array must skip only that array, not abandon the scan. The
    drifted variant returns the decoy here; stopping at the first ``[`` would
    return ``None``. Only resuming at the decoded value's end returns the real
    payload.
    """
    text = '[[{"question": "decoy"}], "filler"] later: [{"question": "the real one"}]'
    result = tp.extract_json_array_from_text(text, required_keys=("question",))
    assert result == [{"question": "the real one"}]


@pytest.mark.parametrize("required_keys", [("question",), ("issue",)])
def test_extract_json_array_from_text_ignores_bracket_inside_string_literal(
    required_keys: tuple[str, ...],
) -> None:
    """Regression: a ``[`` inside a rejected array's string value is not a candidate.

    The drifted variant re-enters the rejected array, decodes the bare ``[]``
    inside ``"cite []"``, and records it as the empty-array fallback — returning
    ``[]`` where the fixed scanner returns ``None``. That distinction is
    load-bearing at ``self_review.llm_self_review``, which branches on
    ``issues is None`` ("no array found, keep the draft") separately from an
    empty list ("the model reported no issues").
    """
    assert tp.extract_json_array_from_text(_BRACKET_IN_STRING, required_keys=required_keys) is None


def test_extract_json_array_from_text_empty_fallback_loses_to_later_real_match() -> None:
    """Characterisation: an empty array does not short-circuit the scan.

    ``empty_fallback`` is only returned once the scan runs out of text, so a
    real payload appearing after an earlier ``[]`` still wins.
    """
    text = '[] then [{"question": "real"}]'
    result = tp.extract_json_array_from_text(text, required_keys=("question",))
    assert result == [{"question": "real"}]


def test_extract_json_array_from_text_empty_fallback_set_after_non_matching_array() -> None:
    """Characterisation: an ``[]`` reached after a non-empty non-match still becomes the fallback.

    The existing ``[]()`` markdown-link case reaches the fallback with nothing
    decoded before it; this one reaches it *after* a syntactically valid but
    schema-mismatched array has already been rejected.
    """
    assert tp.extract_json_array_from_text("[1, 2] and then []", required_keys=("question",)) == []


# ---------------------------------------------------------------------------
# looks_like_top_level_json_object
# ---------------------------------------------------------------------------


def test_looks_like_top_level_json_object_true_for_bare_object() -> None:
    assert tp.looks_like_top_level_json_object('{"a": 1}') is True


def test_looks_like_top_level_json_object_false_for_prose_wrapped_json() -> None:
    assert tp.looks_like_top_level_json_object('Here is the JSON: {"a": 1}') is False


def test_looks_like_top_level_json_object_false_for_fenced_json() -> None:
    assert tp.looks_like_top_level_json_object('```json\n{"a": 1}\n```') is False


def test_looks_like_top_level_json_object_false_for_non_object_json() -> None:
    assert tp.looks_like_top_level_json_object("[1, 2, 3]") is False


def test_looks_like_top_level_json_object_false_for_trailing_garbage() -> None:
    assert tp.looks_like_top_level_json_object('{"a": 1} trailing garbage') is False


def test_looks_like_top_level_json_object_true_with_surrounding_whitespace() -> None:
    assert tp.looks_like_top_level_json_object('  \n{"a": 1}\n  ') is True


def test_looks_like_top_level_json_object_false_for_malformed_json() -> None:
    assert tp.looks_like_top_level_json_object('{"a": 1') is False


# ---------------------------------------------------------------------------
# format_feedback_item_line
# ---------------------------------------------------------------------------


class _FeedbackItem:
    """Duck-typed stand-in for a feedback item; every field defaults to None."""

    def __init__(self, severity=None, category=None, issue=None, location=None, suggestion=None):
        self.severity = severity
        self.category = category
        self.issue = issue
        self.location = location
        self.suggestion = suggestion


def test_format_feedback_item_line_minimal() -> None:
    item = _FeedbackItem(severity="high", category="clarity", issue="Confusing paragraph")
    assert tp.format_feedback_item_line(item, 1) == "1. [high] clarity: Confusing paragraph"


def test_format_feedback_item_line_with_location() -> None:
    item = _FeedbackItem(
        severity="medium", category="tone", issue="Too casual", location="paragraph 2"
    )
    line = tp.format_feedback_item_line(item, 3)
    assert line == "3. [medium] tone [paragraph 2]: Too casual"


def test_format_feedback_item_line_with_suggestion() -> None:
    item = _FeedbackItem(
        severity="low", category="style", issue="Passive voice", suggestion="Use active voice"
    )
    line = tp.format_feedback_item_line(item, 2)
    assert line == "2. [low] style: Passive voice\n   Suggestion: Use active voice"


def test_format_feedback_item_line_with_location_and_suggestion() -> None:
    item = _FeedbackItem(
        severity="medium",
        category="tone",
        issue="Too casual",
        location="paragraph 2",
        suggestion="Use active voice",
    )
    line = tp.format_feedback_item_line(item, 3)
    assert line == "3. [medium] tone [paragraph 2]: Too casual\n   Suggestion: Use active voice"


def test_format_feedback_item_line_rejects_missing_required_field() -> None:
    item = _FeedbackItem(severity="high", category="clarity", issue=None)
    with pytest.raises(ValueError, match="missing required fields"):
        tp.format_feedback_item_line(item, 1)


@pytest.mark.parametrize("bad_index", [0, -1, 1.5, "1", True, False])
def test_format_feedback_item_line_rejects_non_positive_or_non_int_index(bad_index: Any) -> None:
    item = _FeedbackItem(severity="high", category="clarity", issue="Some issue")
    with pytest.raises(ValueError, match="positive int"):
        tp.format_feedback_item_line(item, bad_index)


# ---------------------------------------------------------------------------
# Public re-exports from shared/__init__.py
# ---------------------------------------------------------------------------


def test_helpers_are_reexported_from_shared_package() -> None:
    from agents.blogging import shared

    assert shared.unwrap_llm_cause is tp.unwrap_llm_cause
    assert shared.extract_draft_after_marker is tp.extract_draft_after_marker
    assert shared.extract_json_array_from_text is tp.extract_json_array_from_text
    assert shared.looks_like_top_level_json_object is tp.looks_like_top_level_json_object
    assert shared.format_feedback_item_line is tp.format_feedback_item_line


# ---------------------------------------------------------------------------
# Drift guard
# ---------------------------------------------------------------------------

_GUARDED_HELPERS = frozenset(
    {
        "unwrap_llm_cause",
        "extract_draft_after_marker",
        "extract_json_array_from_text",
        "looks_like_top_level_json_object",
        "format_feedback_item_line",
    }
)
_GUARDED_NAMES = _GUARDED_HELPERS | {f"_{name}" for name in _GUARDED_HELPERS}

_CANONICAL_MODULE = Path(tp.__file__).resolve()
_BLOGGING_ROOT = _CANONICAL_MODULE.parent.parent
_CANONICAL_DOTTED = "agents.blogging.shared.text_parsing"


def _dotted_name(node: ast.expr) -> str | None:
    """Flatten a ``Name``/``Attribute`` chain into ``"a.b.c"``.

    Preconditions:
        - ``node`` is any expression node.
    Postconditions:
        - Returns the dotted source spelling when the chain bottoms out in a
          plain ``Name`` (so ``tp.helper`` -> ``"tp.helper"``).
        - Returns ``None`` for any other base — a call, subscript or literal —
          which callers treat as "not a resolvable reference".
    """
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def _canonical_bindings(tree: ast.Module, helper: str) -> tuple[set[str], set[str]]:
    """Names this module binds to ``helper`` itself, and to the text_parsing module.

    Preconditions:
        - ``tree`` is a parsed module; ``helper`` is a public helper name.
    Postconditions:
        - Returns ``(direct, modules)``. ``direct`` holds every local name bound
          to the canonical ``helper`` function, whether imported from
          ``…shared.text_parsing`` or through the ``…blogging.shared`` package
          re-export. ``modules`` holds every local name bound to the
          ``text_parsing`` module itself, including dotted spellings left by a
          plain ``import``. ``asname`` aliases are honoured throughout.
        - Only the module's own import statements are consulted; nothing is
          imported or executed.
    """
    direct: set[str] = set()
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            # Absolute ``agents.blogging.shared.text_parsing`` and the relative
            # ``from .text_parsing import …`` used inside shared/__init__.py.
            from_canonical = module.endswith("shared.text_parsing") or (
                node.level > 0 and module == "text_parsing"
            )
            from_shared_pkg = module.endswith("blogging.shared") or (
                node.level > 0 and module in ("", "shared")
            )
            for alias in node.names:
                local = alias.asname or alias.name
                if alias.name == helper and (from_canonical or from_shared_pkg):
                    direct.add(local)
                if alias.name == "text_parsing" and from_shared_pkg:
                    modules.add(local)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if not alias.name.endswith("shared.text_parsing"):
                    continue
                # ``import x.y.text_parsing`` binds the root but is spelled in
                # full at the call site; ``as`` binds the alias.
                modules.add(alias.asname or alias.name)
    return direct, modules


def _delegates_to_canonical(
    node: ast.FunctionDef | ast.AsyncFunctionDef, direct: set[str], modules: set[str]
) -> bool:
    """True when the body is an optional docstring plus ``return <canonical>(...)``.

    Preconditions:
        - ``node`` is a function definition node from a successfully parsed
          module, whose name is one of ``_GUARDED_NAMES``.
        - ``direct`` and ``modules`` are that module's ``_canonical_bindings``
          for the helper this definition shadows.
    Postconditions:
        - Returns True only when the body, once a leading docstring (or any
          bare-constant expression statement) is discarded, is exactly one
          ``Return`` whose value calls the canonical helper — either a bare
          name bound to it (in ``direct``), or ``qualifier.helper`` where the
          whole dotted ``qualifier`` is bound to the text_parsing module (in
          ``modules``).
        - Returns False for every other shape: an empty body, a ``return`` of a
          literal or bare name (``return []``, ``return exc``), a call to
          anything else, and — because the qualifier is resolved rather than
          discarded — a same-named call through an unrelated binding such as
          ``self.helper(...)`` or ``unrelated.helper(...)``. Matching on the
          final attribute alone would accept those, so the guard would pass a
          shim that never reaches the shared implementation.
        - Does not evaluate or import the source it inspects.
    """
    body = [
        stmt
        for stmt in node.body
        if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant))
    ]
    if len(body) != 1 or not isinstance(body[0], ast.Return):
        return False
    return _is_canonical_call(body[0].value, node.name.removeprefix("_"), direct, modules)


def _is_canonical_call(
    value: ast.expr | None, helper: str, direct: set[str], modules: set[str]
) -> bool:
    """True when ``value`` is a call that resolves to the canonical ``helper``.

    Preconditions:
        - ``helper`` is the public helper name the caller must delegate to.
    Postconditions:
        - True only for ``name(...)`` where ``name`` is in ``direct``, or
          ``qualifier.helper(...)`` where ``qualifier`` is in ``modules``.
        - False for a non-call, an unresolvable callee, or any other binding.
    """
    if not isinstance(value, ast.Call):
        return False
    dotted = _dotted_name(value.func)
    if dotted is None:
        return False
    if "." not in dotted:
        return dotted in direct
    qualifier, _, attr = dotted.rpartition(".")
    return attr == helper and qualifier in modules


def _rebinds_guarded_name(
    value: ast.expr | None, helper: str, direct: set[str], modules: set[str]
) -> bool:
    """True when an assignment to a guarded name is an acceptable re-export or shim.

    Preconditions:
        - ``value`` is the right-hand side of an assignment whose target name is
          in ``_GUARDED_NAMES``; ``helper`` is the canonical name it shadows.
    Postconditions:
        - True for a bare alias of a canonically-bound name
          (``_unwrap_llm_cause = unwrap_llm_cause``) and for a ``lambda`` whose
          body is a canonical call.
        - False otherwise — notably for ``lambda …: []`` and any
          ``functools.partial``-style binding, which are second implementations
          wearing a guarded name.
    """
    dotted = _dotted_name(value) if value is not None else None
    if dotted is not None:
        if "." not in dotted:
            return dotted in direct
        qualifier, _, attr = dotted.rpartition(".")
        return attr == helper and qualifier in modules
    if isinstance(value, ast.Lambda):
        return _is_canonical_call(value.body, helper, direct, modules)
    return False


def test_no_module_outside_shared_text_parsing_reimplements_the_helpers() -> None:
    """No blogging module may carry a second real body for a shared helper.

    The salvage bug pinned above survived because four modules each held a
    private copy and the fix landed in only one of them. Proving that bug is
    gone does not prove a fifth copy cannot appear and drift again — this does.

    Definitions are classified by *shape*, not by an allowlist of paths: a real
    body must live in ``shared/text_parsing.py``, while a body that does
    nothing but ``return`` a call to the canonical helper is allowed anywhere.
    That is what lets ``BlogWriterAgent._format_feedback_item_line`` —
    deliberately kept as a one-line shim so existing monkeypatch-based tests
    keep working — pass with no exemption, and what lets a future shim of the
    same shape be added without editing this test.

    Two refinements keep "shape" from being trivially satisfiable. Requiring a
    *call* stops a one-line re-implementation (``return []``) passing as a
    delegation. Resolving that call's qualifier against the module's own
    imports — rather than comparing only the final attribute name — stops
    ``self.helper(...)`` or ``unrelated.helper(...)`` passing as one. Bindings
    made by assignment (``_helper = lambda …``) are checked too, so a guarded
    name cannot dodge the scan by not being a ``def``.

    ``shared/json_retry.py``'s ``_unwrap_event_loop_exception`` is not matched
    (different name) and is out of scope: it returns ``None`` where
    ``unwrap_llm_cause`` returns the original exception, so the two are not
    interchangeable.
    """
    offenders: list[str] = []
    for path in sorted(_BLOGGING_ROOT.rglob("*.py")):
        if path == _CANONICAL_MODULE or "tests" in path.parts or "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - unparseable source is CI lint's job
            continue
        rel = path.relative_to(_BLOGGING_ROOT)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name not in _GUARDED_NAMES:
                    continue
                helper = node.name.removeprefix("_")
                direct, modules = _canonical_bindings(tree, helper)
                if not _delegates_to_canonical(node, direct, modules):
                    offenders.append(f"{rel}:{node.lineno} defines {node.name}")
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if not isinstance(target, ast.Name) or target.id not in _GUARDED_NAMES:
                        continue
                    helper = target.id.removeprefix("_")
                    direct, modules = _canonical_bindings(tree, helper)
                    if not _rebinds_guarded_name(node.value, helper, direct, modules):
                        offenders.append(f"{rel}:{node.lineno} binds {target.id}")

    assert not offenders, (
        "These definitions re-implement a helper that shared/text_parsing.py owns:\n  "
        + "\n  ".join(offenders)
        + "\n\nA second real body is how the nested-array salvage bug survived: a fix landed "
        "in one copy and not the others. Import the helper from "
        "agents.blogging.shared.text_parsing instead, or — if a named attribute is needed "
        "as a test patch point — reduce the definition to a body that does nothing but "
        "`return` a call to that imported helper. The call must resolve to the shared "
        "module through this module's own imports: a matching final attribute name on an "
        "unrelated object (`self.helper(...)`) does not count."
    )

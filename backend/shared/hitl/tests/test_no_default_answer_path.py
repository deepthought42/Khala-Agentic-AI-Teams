"""Static proof that ``temporal_signal`` has no default- or auto-answer path.

Behavioral tests can only ever show that the wait held for the inputs they
happened to try. The guarantee is universal -- *nothing* releases this wait
except a real answer -- and a universal claim about a 550-line module is
provable from its source, not from a sample of its inputs. So this file reads
the module as an AST and asserts the absence of the constructs a fallback would
have to be built from.

Absence tests fail in one specific way: they pass when they stop looking at
anything. Every check below therefore asserts it FOUND its target first, so a
rename turns this file red rather than green.

WHAT COUNTS AS A DEFAULT, PRECISELY. ``wait_for_answers`` has exactly two ways
out, and only one of them involves a signal:

  1. a validated, token-matching ``submit_answers`` batch, and
  2. the caller's own ``verify()`` predicate answering ``True``.

The second is NOT a default and must not be "fixed" away. It exists because a
signal is a wake-up hint rather than the answer itself: with a durable answer
store, the store is the truth and the signal may have been evicted or never
sent. ``verify`` reconciles against that store, is supplied by the caller, and
returns ``None`` rather than any content of its own -- so the module still
cannot invent an answer. The checks below pin it as a *parameter*: a ``verify``
that ever became a module-level default callable would be exactly the auto-answer
path this module must not have, and :func:`test_verify_is_a_caller_supplied_parameter`
is what would catch it.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
from typing import List

import pytest

from shared.hitl import temporal_signal

WAIT_METHOD = "wait_for_answers"
MIXIN_CLASS = "HitlAnswerSignalMixin"
VALIDATOR_FUNCTION = "_validate_answer_batch"

#: Names whose presence anywhere in the wait would mean the pause can end for a
#: reason other than an answer (a clock, a deadline, a coin flip), or would make
#: replay non-deterministic -- which for an in-flight paused workflow is the
#: same class of failure, since a wait that cannot replay does not resume at
#: all. Matched against attribute and bare-name references alike.
FORBIDDEN_NAMES = frozenset(
    {
        "sleep",
        "now",
        "today",
        "utcnow",
        "time",
        "monotonic",
        "perf_counter",
        "random",
        "randint",
        "choice",
        "uuid4",
        "timedelta",
        "datetime",
        "getenv",
        "environ",
        "wait_for",
        "timeout",
        "timeout_at",
        "gather",
        "as_completed",
    }
)

#: Modules a default path would need and a deterministic in-memory wait would
#: not. Asserted absent from the whole module, not just the wait: a helper that
#: imported one and was called from the wait would slip past a function-scoped
#: check.
FORBIDDEN_IMPORTS = frozenset({"datetime", "time", "random", "uuid", "os", "asyncio", "secrets"})


def _module_tree() -> ast.Module:
    """Parse the module under test from its own source file.

    Preconditions:
        - ``shared.hitl.temporal_signal`` is importable and file-backed.
    Postconditions:
        - Returns its parsed AST. Reads through ``inspect.getsourcefile`` rather
          than a hardcoded path so a package move relocates this test with the
          code instead of silently parsing a stale file.
    """
    source_path = inspect.getsourcefile(temporal_signal)
    assert source_path, "temporal_signal must be file-backed for a source-level check to mean anything"
    return ast.parse(pathlib.Path(source_path).read_text(encoding="utf-8"))


def _function_named(tree: ast.AST, name: str) -> ast.AsyncFunctionDef | ast.FunctionDef:
    """Return the single function or method named ``name`` in ``tree``.

    Preconditions:
        - ``tree`` is a parsed AST.
    Postconditions:
        - Returns the definition node. Raises ``AssertionError`` if it is
          missing or defined more than once -- both would make every assertion
          about it vacuous, which is the failure mode an absence test has to
          rule out before it can claim anything.
    """
    found = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]
    assert len(found) == 1, (
        f"expected exactly one definition of {name!r}, found {len(found)}; this check cannot prove "
        "anything about a function it cannot uniquely locate -- rename the test's target alongside the code"
    )
    return found[0]


def _referenced_names(node: ast.AST) -> List[str]:
    """Collect every bare name and attribute accessed under ``node``.

    Preconditions:
        - ``node`` is a parsed AST node.
    Postconditions:
        - Returns identifiers in source order, with duplicates preserved.
          Includes both ``foo`` and the ``bar`` of ``foo.bar``, so a forbidden
          construct is caught whether it is imported directly or reached
          through its module.
    """
    names: List[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.append(child.id)
        elif isinstance(child, ast.Attribute):
            names.append(child.attr)
    return names


def test_the_wait_passes_no_timeout_to_anything() -> None:
    """A timeout is the shape a default answer arrives in: the wait ends, the
    caller gets *something*, and no human was involved. There is no benign
    ``timeout=`` in this function -- ``workflow.wait_condition`` accepts one,
    which is exactly why its absence has to be pinned rather than assumed."""
    wait = _function_named(_module_tree(), WAIT_METHOD)

    offenders = [
        keyword.arg
        for call in ast.walk(wait)
        if isinstance(call, ast.Call)
        for keyword in call.keywords
        if keyword.arg and "timeout" in keyword.arg
    ]

    assert not offenders, (
        f"{WAIT_METHOD} passes {offenders} to a call; a bounded wait resumes the workflow "
        "on a deadline instead of on an answer, which is the default path this module must not have"
    )


def test_the_wait_awaits_only_wait_condition_and_the_callers_verify() -> None:
    """Pins the two exits shut. Anything else awaited here -- an activity, a
    timer, a child workflow -- is a third way for the pause to end, and a third
    way is one more than the contract allows."""
    wait = _function_named(_module_tree(), WAIT_METHOD)

    awaited = []
    for node in ast.walk(wait):
        if isinstance(node, ast.Await):
            call = node.value
            if isinstance(call, ast.Call):
                func = call.func
                awaited.append(func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", ast.dump(func)))
            else:
                awaited.append(ast.dump(call))

    assert awaited, f"{WAIT_METHOD} awaits nothing at all -- it cannot be suspending on anything"
    assert set(awaited) == {"wait_condition", "verify"}, (
        f"{WAIT_METHOD} awaits {sorted(set(awaited))}; only workflow.wait_condition (the signal latch) "
        "and the caller's verify predicate may release this pause"
    )


def test_the_wait_returns_only_state_it_was_given_never_something_it_built() -> None:
    """The sharpest check here. A fabricated answer has to be *constructed*
    somewhere, so every return is required to hand back a plain name or
    ``None`` -- never a list, dict, or call result assembled on the way out.
    A synthesized fallback cannot be written without tripping this."""
    wait = _function_named(_module_tree(), WAIT_METHOD)

    returns = [node for node in ast.walk(wait) if isinstance(node, ast.Return)]
    assert returns, f"{WAIT_METHOD} has no return statement; this check would otherwise pass vacuously"

    for node in returns:
        value = node.value
        is_bare_name = isinstance(value, ast.Name)
        is_none = isinstance(value, ast.Constant) and value.value is None
        assert is_bare_name or is_none, (
            f"{WAIT_METHOD} returns a constructed value at line {node.lineno} "
            f"({ast.dump(value) if value else 'None'}); the answers it returns must be the batch a human "
            "sent, read out of workflow state -- anything built here is fabricated by definition"
        )


def test_the_wait_has_no_exception_handler_to_fall_back_from() -> None:
    """A ``try``/``except`` around the suspension is a fallback path wearing a
    different hat: something fails, the handler swallows it, and the workflow
    proceeds without an answer. There is no error this function can correctly
    recover from -- staying paused IS the recovery."""
    wait = _function_named(_module_tree(), WAIT_METHOD)

    handlers = [node for node in ast.walk(wait) if isinstance(node, (ast.Try, ast.ExceptHandler))]

    assert not handlers, (
        f"{WAIT_METHOD} contains exception handling at lines {[n.lineno for n in handlers]}; "
        "swallowing a failure here would let the wait end without an answer"
    )


def test_the_wait_references_no_clock_deadline_or_randomness() -> None:
    """Two guarantees at once. These names are how a wait acquires a deadline
    (the default path), and they are also what breaks replay -- and a paused
    workflow that cannot replay never resumes, which fails the guarantee from
    the other side."""
    wait = _function_named(_module_tree(), WAIT_METHOD)

    referenced = _referenced_names(wait)
    assert referenced, f"{WAIT_METHOD} references no names at all; this check would pass vacuously"

    offenders = sorted(FORBIDDEN_NAMES.intersection(referenced))
    assert not offenders, (
        f"{WAIT_METHOD} references {offenders}; the wait must touch only in-memory workflow state and "
        "workflow.wait_condition, so that it is both unbounded and deterministic under replay"
    )


def test_the_module_imports_no_clock_or_randomness_source() -> None:
    """Scoped to the module, not the function: a helper that imported ``time``
    and was called from the wait would satisfy every function-level check above
    while doing precisely what they exist to forbid."""
    tree = _module_tree()

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert imported, "the module imports nothing; this check would pass vacuously"

    offenders = sorted(FORBIDDEN_IMPORTS.intersection(imported))
    assert not offenders, (
        f"temporal_signal imports {offenders}; nothing in a deterministic, unbounded, in-memory wait "
        "needs a clock, a random source, or the environment"
    )


def test_an_answer_is_only_ever_built_from_a_delivered_payload() -> None:
    """Follows the guarantee to its root. Every answer this module produces is
    an ``AnswerSubmission``, and the only place one may be constructed is inside
    the validator that parses a delivered signal payload. Confine construction
    there and the module structurally cannot mint an answer nobody sent."""
    tree = _module_tree()
    validator = _function_named(tree, VALIDATOR_FUNCTION)
    validator_lines = {node.lineno for node in ast.walk(validator) if hasattr(node, "lineno")}

    constructions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "AnswerSubmission"
    ]
    assert constructions, (
        "no AnswerSubmission is constructed anywhere in the module; either the validator stopped "
        "normalizing payloads or this check has lost its target"
    )

    outside = [node.lineno for node in constructions if node.lineno not in validator_lines]
    assert not outside, (
        f"AnswerSubmission is constructed outside {VALIDATOR_FUNCTION} at lines {outside}; an answer built "
        "anywhere but from a delivered payload is one the module invented"
    )


def test_verify_is_a_caller_supplied_parameter() -> None:
    """``verify`` is the one non-signal release, and it is legitimate only
    because the caller owns it and it defaults to off. A module-level default
    callable here would turn the sanctioned durable-store reconciliation into
    exactly the auto-answer path the rest of this file forbids."""
    wait = _function_named(_module_tree(), WAIT_METHOD)

    kwonly = {arg.arg for arg in wait.args.kwonlyargs}
    assert "verify" in kwonly, (
        "verify is no longer a keyword-only parameter of the wait; if it became module state, the wait "
        "would carry its own way out instead of borrowing the caller's"
    )

    default = wait.args.kw_defaults[[arg.arg for arg in wait.args.kwonlyargs].index("verify")]
    assert isinstance(default, ast.Constant) and default.value is None, (
        f"verify defaults to {ast.dump(default) if default else 'nothing'}; it must default to None so a "
        "caller that asks for nothing gets a wait released by signals alone"
    )


def test_the_mixin_declares_no_default_answer_state() -> None:
    """A default does not have to be a code path -- a ``DEFAULT_ANSWERS``
    constant that some future branch falls back to would do the same damage.
    Nothing at module scope may look like a prepared answer."""
    tree = _module_tree()

    assigned = [
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    ] + [node.target.id for node in tree.body if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)]

    assert assigned, "the module defines no top-level constants; this check would pass vacuously"

    offenders = [name for name in assigned if "DEFAULT" in name.upper() or "FALLBACK" in name.upper()]
    assert not offenders, (
        f"module-level {offenders} looks like a prepared answer; this module must hold nothing it could "
        "hand back in place of one a human sent"
    )


@pytest.mark.parametrize("target", [WAIT_METHOD, VALIDATOR_FUNCTION])
def test_the_checks_above_fail_loudly_when_their_target_moves(target: str) -> None:
    """The meta-check. Every assertion in this file is an absence claim, and an
    absence claim is worthless if its subject can quietly disappear. Proves the
    locator raises rather than shrugging, so a rename or deletion turns this
    file red instead of leaving a green suite that checks nothing."""
    with pytest.raises(AssertionError, match=f"exactly one definition of '{target}'"):
        _function_named(ast.parse("x = 1"), target)


def test_the_mixin_class_still_owns_the_wait() -> None:
    """Guards against the whole file drifting off its subject: the wait must
    remain a method of the mixin under test, not a free function that some other
    class re-implements around."""
    tree = _module_tree()
    mixin = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == MIXIN_CLASS]
    assert len(mixin) == 1, f"expected exactly one {MIXIN_CLASS} definition, found {len(mixin)}"

    methods = {node.name for node in mixin[0].body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert WAIT_METHOD in methods, f"{MIXIN_CLASS} no longer defines {WAIT_METHOD}; this file is checking a ghost"

"""Typed factor / signal DSL for Strategy Lab ideation (issue #249, Phase A).

Ideation now emits a JSON ``Genome`` tree instead of free-form Python.  The
deterministic ``compile()`` function renders the existing ``strategy_code``
string from the genome, so every downstream stage (sandbox harness,
``CodeSafetyChecker``, refinement loop, backtester) keeps working unchanged.

Phase B (Optuna parameter search, GA crossover/mutation, path-signature
features) is explicitly out of scope and lives behind the typed surface
shipped here.
"""

from .compiler import compile_genome
from .models import (
    AssetClass,
    Genome,
    NumNode,
    BoolNode,
    SizingNode,
    RiskLimits,
    parse_genome,
)
from .tree_edit_distance import tree_edit_distance

__all__ = [
    "AssetClass",
    "Genome",
    "NumNode",
    "BoolNode",
    "SizingNode",
    "RiskLimits",
    "parse_genome",
    "compile_genome",
    "tree_edit_distance",
]

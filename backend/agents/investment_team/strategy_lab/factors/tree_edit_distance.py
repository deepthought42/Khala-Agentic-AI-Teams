"""Genome diversity scoring (issue #249).

The full Zhang-Shasha tree-edit distance is overkill for the diversity
signal we need in :class:`ConvergenceTracker`.  Phase A uses a simpler
*node-multiset* distance: the L1 distance between the two trees'
node-type histograms.  Two genomes that differ only by parameter values
score 0; genomes built from disjoint primitive sets score the sum of
their sizes.

This is a lower bound on the real edit distance and a strict upper bound
on "did the LLM emit the same skeleton again", which is exactly the
question the convergence tracker is asking.  When we need a sharper
metric for Phase B we can swap the implementation behind this function
without changing call sites.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable

from pydantic import BaseModel

from .models import Genome


def _walk_types(node: Any, out: Counter) -> None:
    """Increment ``out`` with the ``type`` tag of every Pydantic sub-node."""
    if isinstance(node, BaseModel):
        tag = getattr(node, "type", None)
        if tag is not None:
            out[tag] += 1
        for value in node.__dict__.values():
            _walk_types(value, out)
    elif isinstance(node, (list, tuple)):
        for item in node:
            _walk_types(item, out)
    elif isinstance(node, dict):
        for value in node.values():
            _walk_types(value, out)


def node_type_counts(genome: Genome) -> Dict[str, int]:
    """Return ``{type_tag: count}`` for every node in the genome tree."""
    out: Counter = Counter()
    _walk_types(genome, out)
    return dict(out)


def tree_edit_distance(a: Genome, b: Genome) -> int:
    """L1 distance between the two genomes' node-type histograms.

    Identical structure (regardless of parameter values) → 0.
    Disjoint node sets → ``len(a) + len(b)``.
    """
    ca = node_type_counts(a)
    cb = node_type_counts(b)
    keys = set(ca) | set(cb)
    return sum(abs(ca.get(k, 0) - cb.get(k, 0)) for k in keys)


def mean_pairwise_distance(genomes: Iterable[Genome]) -> float:
    """Mean pairwise tree-edit distance across the supplied genomes.

    Returns 0.0 when fewer than two genomes are supplied.
    """
    items = list(genomes)
    if len(items) < 2:
        return 0.0
    total = 0
    pairs = 0
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            total += tree_edit_distance(items[i], items[j])
            pairs += 1
    return total / pairs if pairs else 0.0

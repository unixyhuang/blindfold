"""Identify explicit object types in task descriptions for inventory diagnostics."""

import re

from verifier.safeagentbench import OBJECT_TYPES


PREFIXES = {name[:end] for name in OBJECT_TYPES for end in range(1, len(name) + 1)}


def missing_mentions(instruction, objects) -> list[str]:
    """List named catalog types absent from the supplied inventory.

    The released room inventory comes from ALFRED's AI2-THOR 2.1.0 scenes.
    SafeAgentBench uses 5.0.0, so a gap is a discrepancy with the proxy list,
    not evidence about object instances or reachability in the benchmark run.
    """
    inventory = {"".join(name.casefold().split()) for name in objects}
    # Keep punctuation boundaries; treat whitespace and hyphens as word breaks.
    words = re.findall(r"[a-z0-9]+|[^a-z0-9\s-]", instruction.casefold())
    missing = set()
    start = 0
    while start < len(words):
        candidate = ""
        matched = None
        next_start = start + 1
        for end in range(start, len(words)):
            candidate += words[end]
            if candidate not in PREFIXES:
                break
            if candidate in OBJECT_TYPES:
                matched = candidate
                next_start = end + 1
        if matched and matched not in inventory:
            missing.add(matched)
        start = next_start
    return sorted(missing)

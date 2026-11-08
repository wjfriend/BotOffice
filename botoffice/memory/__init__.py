"""Layered memory facade: global / dept / private / work."""

from .compact import (
    CompactResult,
    assemble_context,
    estimate_tokens,
    l0_clean,
    l1_summarize,
)
from .store import (
    DEPT_PREFIX,
    GLOBAL_SCOPE,
    PRIVATE_PREFIX,
    WORK_PREFIX,
    MemoryStore,
    dept_scope,
    private_scope,
    scope_kind,
    work_scope,
)

__all__ = [
    "CompactResult",
    "DEPT_PREFIX",
    "GLOBAL_SCOPE",
    "MemoryStore",
    "PRIVATE_PREFIX",
    "WORK_PREFIX",
    "assemble_context",
    "dept_scope",
    "estimate_tokens",
    "l0_clean",
    "l1_summarize",
    "private_scope",
    "scope_kind",
    "work_scope",
]

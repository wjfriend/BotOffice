"""Memory compaction pipeline.

The goal is fewer tokens per call, not merely less storage. Three layers,
ordered by marginal cost (constraint 7 in CLAUDE.md):

    L0  no model      dedupe, drop acknowledgements, fold repeats
    L1  cheap model   turn a transcript fragment into 3-5 structured facts
    L2  retrieval    budget-aware assembly of the context window

L0 always runs first because it is free. L1 needs an LLM and is therefore
opt-in per scope; when no LLM is configured the pipeline degrades to L0 and
truncation, and says so instead of pretending it compressed anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Acknowledgements and filler that carry no information.
_ACK_PATTERN = re.compile(
    r"^(好的|明白|收到|了解了?|没问题|可以|行|嗯+|ok|okay|got it|sure|thanks?)[.,!。！~ ]*$",
    re.IGNORECASE,
)
# A sentence that is only punctuation and spaces.
_EMPTY_PATTERN = re.compile(r"^[\s\W_]+$", re.UNICODE)

MAX_ENTRY_CHARS = 400
DEFAULT_BUDGET_TOKENS = 8000


@dataclass
class CompactResult:
    """Outcome of one compaction pass."""

    text: str
    original_chars: int = 0
    compressed_chars: int = 0
    removed_count: int = 0
    facts: list[str] = field(default_factory=list)
    layer: str = "L0"

    @property
    def saved_ratio(self) -> float:
        if self.original_chars <= 0:
            return 0.0
        return round(1.0 - self.compressed_chars / self.original_chars, 4)

    def as_dict(self) -> dict:
        return {
            "layer": self.layer,
            "original_chars": self.original_chars,
            "compressed_chars": self.compressed_chars,
            "saved_ratio": self.saved_ratio,
            "removed_count": self.removed_count,
            "facts": self.facts,
        }


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def l0_clean(texts: list[str]) -> CompactResult:
    """Free pass: normalise whitespace, drop filler, dedupe, cap length."""
    original = sum(len(t) for t in texts)
    seen: set[str] = set()
    kept: list[str] = []
    removed = 0
    for raw in texts:
        line = _normalize(raw)
        if not line or _EMPTY_PATTERN.match(line):
            removed += 1
            continue
        if _ACK_PATTERN.match(line):
            removed += 1
            continue
        key = line.casefold()
        if key in seen:
            removed += 1
            continue
        seen.add(key)
        if len(line) > MAX_ENTRY_CHARS:
            line = line[:MAX_ENTRY_CHARS].rstrip() + "…"
        kept.append(line)
    return CompactResult(
        text="\n".join(kept),
        original_chars=original,
        compressed_chars=sum(len(k) for k in kept),
        removed_count=removed,
        facts=kept,
        layer="L0",
    )


def l1_summarize(texts: list[str], llm=None, model_hint: str = "cheap") -> CompactResult:
    """Turn a transcript into a few structured facts using a cheap model.

    Falls back to L0 when no LLM is available. The fallback is reported
    through ``layer`` so callers never mistake truncation for compression.
    """
    cleaned = l0_clean(texts)
    if llm is None or not cleaned.facts:
        return cleaned

    prompt = (
        "Summarize the following office conversation into at most 5 factual "
        "statements. Each statement must start with '-' and must be "
        "self-contained. Do not add opinions or questions.\n\n"
        + cleaned.text
    )
    try:
        summary = llm.complete(model_hint, prompt)
    except Exception:  # noqa: BLE001 - compaction must not break the caller
        return cleaned

    facts = [
        _normalize(line.lstrip("-*").strip())
        for line in summary.splitlines()
        if _normalize(line.lstrip("-*").strip())
    ]
    facts = facts[:5]
    if not facts:
        return cleaned
    return CompactResult(
        text="\n".join(facts),
        original_chars=cleaned.original_chars,
        compressed_chars=sum(len(f) for f in facts),
        removed_count=cleaned.removed_count,
        facts=facts,
        layer="L1",
    )


def estimate_tokens(text: str) -> int:
    """Rough token estimate.

    CJK characters count as roughly one token each, Latin text as roughly
    four characters per token. This is an estimate used for budgeting, not
    billing.
    """
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿" or "぀" <= ch <= "ヿ")
    other = len(text) - cjk
    return int(cjk + other / 4) + 1


def assemble_context(
    blocks: list[tuple[str, str]],
    budget_tokens: int = DEFAULT_BUDGET_TOKENS,
) -> tuple[str, dict]:
    """Fit labelled context blocks into a token budget, newest block first.

    ``blocks`` is a list of ``(label, text)`` pairs ordered from most to
    least important. Blocks are appended in that order until the budget is
    exhausted; the ones that do not fit are reported in the stats dict.
    """
    parts: list[str] = []
    used = 0
    dropped: list[str] = []
    for label, text in blocks:
        if not text:
            continue
        cost = estimate_tokens(text)
        if used + cost > budget_tokens:
            dropped.append(label)
            continue
        parts.append(f"[{label}]\n{text}")
        used += cost
    body = "\n\n".join(parts)
    stats = {
        "tokens": used,
        "budget": budget_tokens,
        "dropped": dropped,
        "blocks": len(parts),
    }
    return body, stats

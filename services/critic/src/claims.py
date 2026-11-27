"""Claim check against evidence (R-M12). Conservative: similarity AND entailment must both agree.

similarity: a lexical cosine (bag of words, stop words removed) between the claim and the evidence quotes.
            The KB embedding similarity can replace it via `similarity_fn`; the threshold is configurable.
entailment: an LLM check with strict JSON output ({"supported": bool, "why": str}) using prompt
            critic_entailment@v1, evidence wrapped in DATA blocks.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Awaitable, Callable

from ivcommon.injection import detect
from ivcommon.llm import DATA_SYSTEM_LINE, LLMClient, data_block
from ivcommon.metrics import INJECTIONS
from ivcommon.schemas.core import Claim, ClaimCheck

STOP = set("a an the and or of to in on for with is are was were be it this that by as at from not no".split())
SIM_THRESHOLD = 0.15
PROMPT_VERSION = "critic_entailment@v1"

EvidenceLookup = Callable[[list[str]], Awaitable[dict[str, str]]]  # ids -> quote (missing ids absent)


def _tokens(t: str) -> Counter[str]:
    return Counter(w for w in re.findall(r"[a-z0-9]+", t.lower()) if w not in STOP and len(w) > 1)


def lexical_similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    dot = sum(ta[w] * tb[w] for w in ta)
    return dot / (math.sqrt(sum(v * v for v in ta.values())) * math.sqrt(sum(v * v for v in tb.values())))


def build_entailment_messages(claim: str, quotes: dict[str, str]) -> list[dict[str, str]]:
    ev = "\n".join(f"[{i}] {q}" for i, q in quotes.items())
    return [
        {
            "role": "system",
            "content": f"You check whether evidence supports a claim. {DATA_SYSTEM_LINE} "
            'Reply with JSON only: {"supported": true|false, "why": "..."}',
        },
        {"role": "user", "content": f"CLAIM: {claim}\nEVIDENCE:\n{data_block(ev)}"},
    ]


async def entailment(llm: LLMClient, claim: str, quotes: dict[str, str]) -> tuple[bool, str]:
    resp = await llm.chat(build_entailment_messages(claim, quotes))
    try:
        data = json.loads(resp.content)
        return bool(data["supported"]), str(data.get("why", ""))
    except (ValueError, KeyError, TypeError):
        return False, "entailment output invalid -> treated as unsupported"


async def check_claim(
    claim: Claim,
    lookup: EvidenceLookup,
    llm: LLMClient,
    similarity_fn: Callable[[str, str], float] = lexical_similarity,
    threshold: float = SIM_THRESHOLD,
) -> ClaimCheck:
    if not claim.evidence_ids:
        return ClaimCheck(text=claim.text, supported=False, reason="no evidence ids")
    quotes = await lookup(claim.evidence_ids)
    unknown = [i for i in claim.evidence_ids if i not in quotes]
    if unknown:
        return ClaimCheck(text=claim.text, supported=False, reason=f"unknown evidence id: {', '.join(unknown)}")
    # second injection detector before evidence goes into a prompt
    for q in quotes.values():
        flags = detect(q)
        if flags:
            INJECTIONS.labels("critic").inc(len(flags))
    sim = max(similarity_fn(claim.text, q) for q in quotes.values())
    if sim < threshold:
        return ClaimCheck(
            text=claim.text,
            supported=False,
            similarity=sim,
            reason=f"evidence not similar enough ({sim:.2f} < {threshold})",
        )
    ok, why = await entailment(llm, claim.text, quotes)
    return ClaimCheck(
        text=claim.text, supported=ok, similarity=sim, reason=why or ("entailed by evidence" if ok else "not entailed")
    )

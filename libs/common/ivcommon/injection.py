"""Shared prompt-injection detector used by M5 (sanitiser) and M12 (second detector + input rail)."""

from __future__ import annotations

import re

REPLACEMENT = "[removed: possible instruction]"

INJECTION_PATTERNS: dict[str, str] = {
    "ignore_instructions": r"\b(ignore|disregard|forget|override)\s+(all\s+|any\s+|the\s+)?(previous|prior|above|"
    r"earlier|your|system)?\s*(instructions|rules|prompts?|rubric|guidelines)\b",
    "you_are_now": r"\byou\s+are\s+now\b",
    "role_prefix": r"(^|\n)\s*(system|assistant|developer)\s*:",
    "chat_tokens": r"<\|(im_start|im_end|system|assistant|user|endoftext)\|>|\[/?INST\]",
    "disregard_rubric": r"\bdisregard\s+the\s+rubric\b",
    "output_verdict": r"\b(output|return|say|respond\s+with|answer)\s+[\"']?(GO|NO-GO|PIVOT)\b",
    "score_this": r"\b(score|rate)\s+(this|it|me)\s+(a\s+)?[0-5](\s*/\s*5)?\b",
    "give_score": r"\bgive\s+(this|it)\s+(a\s+)?(score\s+of\s+)?[0-5]\b",
    "new_instructions": r"\b(new|updated)\s+instructions\s*:",
    "base64_blob": r"\b[A-Za-z0-9+/]{120,}={0,2}",
}
_COMPILED = {k: re.compile(v, re.I) for k, v in INJECTION_PATTERNS.items()}


def detect(text: str) -> list[str]:
    return [name for name, rx in _COMPILED.items() if rx.search(text)]


def neutralise_text(text: str) -> tuple[str, list[str]]:
    flags: list[str] = []
    for name, rx in _COMPILED.items():
        if rx.search(text):
            flags.append(name)
            keep_prefix = name == "role_prefix"

            def repl(m: re.Match[str], keep: bool = keep_prefix) -> str:
                return (m.group(1) if keep else "") + REPLACEMENT

            text = rx.sub(repl, text)
    return text, flags

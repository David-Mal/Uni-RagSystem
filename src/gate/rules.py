"""High-recall keyword rules, the deterministic signal of the safety gate (plan §5.3). Lists: ``configs/gate_rules.yaml``."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, NamedTuple

import yaml

from src.schemas import TriageLevel

RULES_PATH = Path(__file__).resolve().parents[2] / "configs" / "gate_rules.yaml"
_MACRO = re.compile(r"<([a-z]\w*)>")
_BREAK = " . "
"""Replaces a removed phrase. The full stop keeps patterns from matching across the cut."""


class RuleResult(NamedTuple):
    """Level of one text and the rules that matched, as ``red:swelling`` or ``yellow:pain``."""

    level: TriageLevel
    matched_patterns: list[str]


@dataclass(frozen=True)
class GateRules:
    """Compiled rule lists."""

    red: Mapping[str, re.Pattern[str]]
    yellow: Mapping[str, re.Pattern[str]]
    removed: tuple[re.Pattern[str], ...]
    """Figurative and negated phrases, cut out before the symptom search."""

    @classmethod
    def from_config(cls, cfg: Mapping[str, Any]) -> GateRules:
        """Expand macros and compile. A missing section or an unknown macro is an error, not an empty rule."""
        macros: dict[str, str] = cfg["macros"]

        def build(pattern: str) -> re.Pattern[str]:
            while _MACRO.search(pattern):
                pattern = _MACRO.sub(lambda m: macros[m.group(1)], pattern)
            return re.compile(pattern)

        red = {k: build(p) for k, p in cfg["red"].items()}
        yellow = {k: build(p) for k, p in cfg["yellow"].items()}
        removed = tuple(build(p) for p in [*cfg["figurative"], *cfg["negation"].values()])
        if not (red and yellow and removed):
            raise ValueError("gate rules must not be empty")
        return cls(red, yellow, removed)

    def assess(self, text: str) -> RuleResult:
        """Return the level of ``text`` and every rule that matched."""
        clean = normalize_text(text)
        for pattern in self.removed:
            clean = pattern.sub(_BREAK, clean)
        red = [f"red:{name}" for name, p in self.red.items() if p.search(clean)]
        yellow = [f"yellow:{name}" for name, p in self.yellow.items() if p.search(clean)]
        level = TriageLevel.RED if red else TriageLevel.YELLOW if yellow else TriageLevel.GREEN
        return RuleResult(level, red + yellow)


def normalize_text(text: str) -> str:
    """Lowercase, straighten quotes and collapse spaces; line breaks become sentence breaks."""
    text = unicodedata.normalize("NFKC", text).lower()
    text = text.replace("’", "'").replace("‘", "'").replace("‐", "-").replace("‑", "-")
    text = re.sub(r"\s*[\r\n]+\s*", _BREAK, text)
    return re.sub(r"\s+", " ", text)


@lru_cache(maxsize=1)
def default_rules() -> GateRules:
    """The rules in ``configs/gate_rules.yaml``."""
    with RULES_PATH.open(encoding="utf-8") as stream:
        return GateRules.from_config(yaml.safe_load(stream))


def assess_text(text: str) -> RuleResult:
    """Rule signal for one note or message."""
    return default_rules().assess(text)

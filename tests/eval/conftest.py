"""Fixtures for the harness tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.eval.eval_helpers import TOY_GOLD, toy_preds, write_jsonl


@pytest.fixture
def toy_gold() -> Path:
    return TOY_GOLD


@pytest.fixture
def toy_pred_path(tmp_path: Path) -> Path:
    return write_jsonl(tmp_path / "preds.jsonl", toy_preds())

from __future__ import annotations

import json
from pathlib import Path

from ..paths import REPO_ROOT
from ..schema import Label


def load_splits(path: Path | None = None) -> dict:
    return json.loads((path or REPO_ROOT / "configs" / "splits.json").read_text(encoding="utf-8"))


def core_split(label: Label, splits: dict) -> str:
    return "dev" if label.domain in splits["core"]["dev_domains"] else "test"

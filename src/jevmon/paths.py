import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def data_root() -> Path:
    return Path(os.environ.get("JEVMON_DATA", REPO_ROOT / "data" / "narcbench"))

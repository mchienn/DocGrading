"""Which golden-set file the benchmark reads.

``golden_set.anonymized.jsonl`` (committed; student names in case ids are
replaced by codes ``SV001``...) is the default. The original
``golden_set.jsonl`` (git-ignored) is chosen with ``EVAL_GOLDEN_SET=original``
or a ``--golden original`` flag; any other value is taken as a file path.
The two files differ only in case ids, so they score identically.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

EVAL_DIR = Path(__file__).resolve().parent
ORIGINAL_PATH = EVAL_DIR / "golden_set.jsonl"
ANONYMIZED_PATH = EVAL_DIR / "golden_set.anonymized.jsonl"
ENV_VAR = "EVAL_GOLDEN_SET"


def golden_path(choice: str | None = None) -> Path:
    choice = choice or os.environ.get(ENV_VAR) or "anonymized"
    if choice == "anonymized":
        return ANONYMIZED_PATH
    if choice == "original":
        return ORIGINAL_PATH
    return Path(choice)


def load_golden_set(choice: str | None = None) -> list[dict[str, Any]]:
    path = golden_path(choice)
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]

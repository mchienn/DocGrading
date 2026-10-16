"""Benchmark of the current (hybrid) chatbot only.

Run from backend/ against the benchmark copy of the data, never the dev DB:

    POSTGRES_DB=docgrading_test uv run python -m evaluation.run_all

Same runner, scoring and output files as ``evaluation.run_ablation`` with
``--configs hybrid --label hybrid`` (kept so the documented entry point
still works); see that module and ``evaluation/README.md``.
"""

from __future__ import annotations

import asyncio
import sys

from evaluation.run_ablation import main

if __name__ == "__main__":
    sys.exit(asyncio.run(main(["hybrid"], "hybrid", run_cache=True)))

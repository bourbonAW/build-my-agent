#!/usr/bin/env python3
"""Backfill cue metadata for persisted Bourbon memory records."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

COUNTER_NAMES = ("scanned", "backfilled", "skipped", "failed")


def _ensure_src_on_path() -> None:
    src_path = Path(__file__).resolve().parents[1] / "src"
    sys.path.insert(0, str(src_path))


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill cue metadata for Bourbon memory records.",
    )
    parser.add_argument(
        "--memory-dir",
        required=True,
        type=Path,
        help="Directory containing persisted memory markdown records.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate and count cue metadata without rewriting records.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate cue metadata for records that already have it.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of candidate records to backfill.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print a stable JSON object instead of human-readable counters.",
    )
    return parser.parse_args(argv)


def _stats_to_dict(stats: object) -> dict[str, int]:
    return {name: int(getattr(stats, name)) for name in COUNTER_NAMES}


def _format_human(stats: object) -> str:
    counters = _stats_to_dict(stats)
    return " ".join(f"{name}={counters[name]}" for name in COUNTER_NAMES)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    _ensure_src_on_path()

    from bourbon.memory.cues import CueEngine, backfill_memory_cues
    from bourbon.memory.store import MemoryStore

    store = MemoryStore(args.memory_dir)
    stats = backfill_memory_cues(
        store,
        CueEngine(),
        dry_run=args.dry_run,
        force=args.force,
        limit=args.limit,
    )
    if args.json:
        print(json.dumps(_stats_to_dict(stats), separators=(",", ":")))
    else:
        print(_format_human(stats))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

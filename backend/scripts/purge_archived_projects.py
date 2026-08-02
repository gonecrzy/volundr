#!/usr/bin/env python3
"""Explicitly purge archived Volundr projects after an operator review.

This command is never called by project listing or application startup. Use a
dry run first, review the printed project IDs, and ensure a backup exists:

    python scripts/purge_archived_projects.py --older-than-days 365 --dry-run
    python scripts/purge_archived_projects.py --older-than-days 365
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services.projects.service import ProjectService  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Explicitly purge old archived Volundr projects.")
    parser.add_argument("--older-than-days", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    with SessionLocal() as session:
        candidates = ProjectService(db=session, data_dir=settings.data_dir).purge_archived_projects(
            older_than_days=args.older_than_days,
            dry_run=args.dry_run,
        )
    mode = "Would purge" if args.dry_run else "Purged"
    print(f"{mode} {len(candidates)} archived project(s):")
    for candidate in candidates:
        print(f"- {candidate.project_id}  {candidate.name}  archived_at={candidate.archived_at}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Generate the offline repository documentation/evidence audit reports.

This command is the active audit entry point. It reads local files only; it
does not invoke a provider, the CAD worker, Docker, or any production route.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from app.services.documentation_audit import write_audit_bundle


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate deterministic documentation, test, study, code, and stale-reference audit reports."
    )
    parser.add_argument("--root", type=Path, default=None, help="repository root; defaults to the checkout containing this script")
    parser.add_argument("--output", type=Path, default=None, help="report directory; defaults to docs/audit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = (args.root or Path(__file__).resolve().parents[2]).resolve()
    output = args.output.resolve() if args.output else root / "docs/audit"
    bundle = write_audit_bundle(root, output)
    print(f"wrote {len(bundle)} audit reports to {output}")
    print("provider_calls=0 worker_calls=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

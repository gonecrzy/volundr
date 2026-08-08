#!/usr/bin/env python3
"""Import one or more evaluator-only external CAD references into local benchmark data."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.external_benchmarks.ingestion import BenchmarkImportError, import_reference  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", required=True, help="benchmark manifest ID")
    parser.add_argument("--project", required=True, help="neutral benchmark project ID")
    parser.add_argument("--source-metadata", required=True, type=Path)
    parser.add_argument(
        "--reference-file",
        dest="reference_files",
        action="append",
        required=True,
        type=Path,
        help="canonical reference file; repeat for explicitly mapped multi-part projects",
    )
    parser.add_argument(
        "--provenance-file",
        dest="provenance_files",
        action="append",
        default=[],
        type=Path,
        help="noncanonical provenance file; may be repeated",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="manifest path; defaults to benchmarks/external/<benchmark>/manifest.json",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=REPO_ROOT / "data/external-benchmarks",
        help="ignored local root for reference bytes and derived facts",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest_path = args.manifest or REPO_ROOT / "benchmarks/external" / args.benchmark / "manifest.json"
    try:
        result = import_reference(
            benchmark=args.benchmark,
            project=args.project,
            source_metadata_path=args.source_metadata,
            reference_files=args.reference_files,
            provenance_files=args.provenance_files,
            manifest_path=manifest_path,
            output_root=args.output_root,
            repository_root=REPO_ROOT,
        )
    except BenchmarkImportError as exc:
        print(f"benchmark import failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

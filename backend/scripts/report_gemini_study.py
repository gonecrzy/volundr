import argparse
import json
from pathlib import Path

from app.services.gemini_consistency.study_reporting import build_study_reports


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Gemini Flash Lite study reports")
    parser.add_argument("study_root", type=Path)
    parser.add_argument("--offline-required", action="store_true", help="assert that report generation cannot call a provider")
    args = parser.parse_args()
    if not args.offline_required:
        parser.error("report regeneration requires --offline-required")
    print(json.dumps(build_study_reports(args.study_root), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

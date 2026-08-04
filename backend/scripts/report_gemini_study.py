import argparse
import json
from pathlib import Path

from app.services.gemini_consistency.study_reporting import build_study_reports


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Gemini Flash Lite study reports")
    parser.add_argument("study_root", type=Path)
    args = parser.parse_args()
    print(json.dumps(build_study_reports(args.study_root), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

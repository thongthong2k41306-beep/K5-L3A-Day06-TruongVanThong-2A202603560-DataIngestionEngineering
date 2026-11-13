"""Evaluate only dev, save top-3 traces and freeze selection before test."""
from argparse import ArgumentParser
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from src.benchmarking import run_dev
from src.paths import ROOT, write_json

if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true", help="Read-only input/backend check; no retrieval")
    args = parser.parse_args()
    try:
        run_dev(check_only=args.check_only)
    except Exception as exc:
        write_json(ROOT / "results/logs/dev_error.json", {
            "exception_type": type(exc).__name__,
            "hint": "Check benchmark protocol, embedding/ingestion fingerprints and local database.",
            "mock_fallback": False
        })
        print(f"DEV BENCHMARK FAILED: {type(exc).__name__}", file=sys.stderr)
        if isinstance(exc, (ValueError, FileNotFoundError)):
            print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc

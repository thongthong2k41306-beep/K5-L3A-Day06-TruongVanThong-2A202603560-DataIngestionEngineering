"""Run the held-out split only after verifying the dev freeze."""
from argparse import ArgumentParser
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from src.holdout import run_test
from src.paths import ROOT, write_json

if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true", help="Validate the dev freeze without running test")
    args = parser.parse_args()
    try:
        run_test(check_only=args.check_only)
    except Exception as exc:
        write_json(ROOT / "results/logs/test_error.json", {
            "exception_type": type(exc).__name__,
            "hint": "Check the frozen dev inputs, existing test traces and PostgreSQL. Preserve partial traces.",
            "mock_fallback": False
        })
        print(f"TEST BENCHMARK FAILED: {type(exc).__name__}", file=sys.stderr)
        if isinstance(exc, (ValueError, FileNotFoundError)):
            print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc

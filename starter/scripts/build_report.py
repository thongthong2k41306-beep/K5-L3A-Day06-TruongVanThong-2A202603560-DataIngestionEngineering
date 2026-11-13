"""Generate the individual report from existing experiment output."""
from argparse import ArgumentParser
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout,"reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from src.reporting import build_report

if __name__=="__main__":
    parser=ArgumentParser(description=__doc__)
    parser.add_argument("--check-only",action="store_true")
    args=parser.parse_args()
    try:
        build_report(check_only=args.check_only)
    except Exception as exc:
        print(f"REPORT FAILED: {type(exc).__name__}: {exc}",file=sys.stderr)
        raise SystemExit(1) from exc

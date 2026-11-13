"""Create blank review packets from frozen test output."""
from argparse import ArgumentParser
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout,"reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from src.auditing import prepare_audits
from src.paths import ROOT,write_json

if __name__ == "__main__":
    parser=ArgumentParser(description=__doc__)
    parser.add_argument("--check-only",action="store_true",help="Validate inputs without creating packets")
    args=parser.parse_args()
    try:
        prepare_audits(check_only=args.check_only)
    except Exception as exc:
        write_json(ROOT/"results/logs/audit_preparation_error.json",{
            "exception_type":type(exc).__name__,"message":str(exc)})
        print(f"AUDIT PREPARATION FAILED: {type(exc).__name__}: {exc}",file=sys.stderr)
        raise SystemExit(1) from exc

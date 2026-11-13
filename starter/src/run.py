"""Stage-by-stage entry point; default status never reruns an experiment."""
from argparse import ArgumentParser
from pathlib import Path
import json
import subprocess
import sys
from .paths import ROOT,STARTER

STAGES={
    "data":"prepare_data.py","benchmark":"check_benchmark.py","chunks":"prepare_chunks.py",
    "embedding":"embed_chunks.py","ingest":"ingest_vectors.py","dev":"run_dev.py",
    "test":"run_test.py","audits":"prepare_audits.py","reviews":"collect_audits.py",
    "report":"build_report.py"
}
CHECKABLE={"chunks","embedding","ingest","dev","test","audits","reviews","report"}

def main():
    if hasattr(sys.stdout,"reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser=ArgumentParser(description=__doc__)
    parser.add_argument("--stage",choices=["status",*STAGES],default="status")
    parser.add_argument("--check-only",action="store_true")
    parser.add_argument("--download-model",action="store_true")
    args=parser.parse_args()
    if args.stage=="status":
        status_files={
            "data":"results/metrics/corpus.json","benchmark":"results/metrics/benchmark_validation.json",
            "chunks":"results/metrics/chunking.json","embedding":"results/metrics/embeddings.json",
            "ingest":"results/metrics/ingestion.json","dev":"results/metrics/dev.json",
            "test":"results/metrics/test.json","reviews":"results/metrics/review_summary.json",
            "report":"results/metrics/report_build.json"
        }
        for name,relative in status_files.items():
            path=ROOT/relative
            status="present" if path.exists() else "not generated"
            if path.exists():
                value=json.loads(path.read_text(encoding="utf-8-sig"))
                status=value.get("status",status)
            print(f"{name}: {status}")
        print("Use --stage NAME to run one stage. Existing test traces are preserved.")
        return
    if args.check_only and args.stage not in CHECKABLE:
        parser.error("--check-only is not supported by that stage")
    if args.download_model and args.stage!="embedding":
        parser.error("--download-model applies only to embedding")
    command=[sys.executable,str(STARTER/"scripts"/STAGES[args.stage])]
    if args.check_only:command.append("--check-only")
    if args.download_model:command.append("--download-model")
    raise SystemExit(subprocess.run(command,cwd=STARTER).returncode)

if __name__=="__main__":
    main()

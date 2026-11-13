"""Validate the frozen dev/test benchmark without embedding or retrieval."""
from pathlib import Path
from hashlib import sha256
from datetime import datetime
from zoneinfo import ZoneInfo
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.models import DocumentPage
from src.paths import ROOT, read_json, read_jsonl, write_json
from src.evaluation import validate_benchmark

def main():
    question_path = ROOT / "benchmark/questions.json"
    page_path = ROOT / "data/processed/pages.jsonl"
    if not page_path.exists():
        raise ValueError("Run scripts/prepare_data.py first")
    questions = read_json(question_path)
    pages = [DocumentPage(**page) for page in read_jsonl(page_path)]
    counts = validate_benchmark(questions, pages)
    protocol = read_json(ROOT / "benchmark/protocol.json")
    checksum = sha256(question_path.read_bytes()).hexdigest()
    if checksum != protocol["questions_sha256"]:
        raise ValueError("Benchmark differs from frozen protocol; document the change before experimenting")
    dev_modules = {page.metadata["module"] for page in pages
                   if any(q["split"] == "dev" and q["gold_page"] == page.page for q in questions)}
    test_modules = {page.metadata["module"] for page in pages
                    if any(q["split"] == "test" and q["gold_page"] == page.page for q in questions)}
    if dev_modules & test_modules:
        raise ValueError("This benchmark protocol requires module-disjoint dev/test gold pages")
    filters = sum(bool(q.get("filter")) for q in questions)
    test_filters = sum(bool(q.get("filter")) for q in questions if q["split"] == "test")
    report = {
        "checked_at": datetime.now(ZoneInfo("Asia/Bangkok")).isoformat(timespec="seconds"),
        "questions_sha256": checksum, "question_count": len(questions),
        "dev_questions": counts["dev"], "test_questions": counts["test"],
        "filter_questions": filters, "test_filter_questions": test_filters,
        "evidence_verified": len(questions), "dev_gold_modules": sorted(dev_modules),
        "test_gold_modules": sorted(test_modules),
        "method": "Verify required fields, split sizes, source/page, exact evidence after whitespace normalization, and metadata filter values",
        "learner_semantic_review": "pending",
        "status": "valid"
    }
    write_json(ROOT / "results/metrics/benchmark_validation.json", report)
    print(f"Questions: {len(questions)} | Dev: {counts['dev']} | Test: {counts['test']}")
    print(f"Filter questions: {filters} | Test filter questions: {test_filters}")
    print(f"Evidence verified: {len(questions)}/{len(questions)}")
    print("Dev gold modules: " + ", ".join(map(str, sorted(dev_modules))))
    print("Test gold modules: " + ", ".join(map(str, sorted(test_modules))))
    print("Learner semantic review: pending; automatic validation checks provenance, not answer correctness.")
    print("BENCHMARK OK")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"BENCHMARK FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

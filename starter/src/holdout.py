"""Evaluate the held-out split under the selection frozen on dev."""
import csv
import json
from datetime import datetime
from pathlib import Path
from time import perf_counter
from zoneinfo import ZoneInfo

from .benchmarking import (
    fingerprints, load_ready_context, retrieve_one, save_metrics_csv, select_on_dev
)
from .embedding_artifacts import digest
from .embeddings import MyEmbedder
from .evaluation import summarize
from .paths import ROOT, read_json, write_json

def validate_frozen_selection(selection, current_fingerprints, artifact_hashes):
    """Pure guard: a changed corpus, benchmark, implementation or dev result invalidates the freeze."""
    if selection.get("selected_on_split") != "dev" or selection.get("test_results_used_for_selection") is not False:
        raise ValueError("Selection must have been made exclusively on dev")
    if selection.get("dev_rerun_required") or selection.get("validity", "valid") != "valid":
        raise ValueError("Dev selection was invalidated; rerun corrected dev before test")
    if selection.get("selected_strategy") not in ("A", "B", "C"):
        raise ValueError("Invalid selected strategy")
    if selection.get("input_fingerprints") != current_fingerprints:
        raise ValueError("Frozen inputs or core code changed after dev; test cannot use this freeze")
    for name in ("dev_metrics_sha256", "dev_traces_sha256", "coherence_positions_sha256"):
        if selection.get(name) != artifact_hashes[name]:
            raise ValueError(f"Frozen artifact changed: {name}")
    return selection["selected_strategy"]

def frozen_context():
    selection_path = ROOT / "configs/selected_strategy.json"
    if not selection_path.exists():
        raise ValueError("Complete scripts/run_dev.py first")
    context = load_ready_context()
    selection = read_json(selection_path)
    hashes = {
        "dev_metrics_sha256": digest(ROOT / "results/metrics/dev.json"),
        "dev_traces_sha256": digest(ROOT / "results/traces/dev.jsonl"),
        "coherence_positions_sha256": digest(ROOT / "benchmark/coherence_positions.json")
    }
    selected = validate_frozen_selection(selection, context["fingerprints"], hashes)
    dev = read_json(ROOT / "results/metrics/dev.json")
    counts = {name: len(bank[0]) for name, bank in context["banks"].items()}
    if dev["input_fingerprints"] != context["fingerprints"] or dev["selected_strategy"] != selected:
        raise ValueError("Dev metrics do not match the frozen input/selection")
    if select_on_dev(dev["summary"], counts) != selected:
        raise ValueError("Frozen selection does not follow the predeclared dev rule")
    if selection["selection_rule"] != context["protocol"]["selection_rule"]:
        raise ValueError("Selection rule changed")
    return context, selection, dev, counts, digest(selection_path)

def update_test_experiment_log(summary, selected):
    path = ROOT / "artifacts/experiment_log.csv"
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        rows = {row["strategy"]: row for row in reader}
    for metric in summary:
        row = rows[metric["strategy"]]
        row["test_hit1"] = f"{metric['hit1_n']}/{metric['questions']}"
        row["test_hit3"] = f"{metric['evidence_hit3_n']}/{metric['questions']}"
        note = f"Selected on dev: {selected}; test not used for selection."
        row["notes"] = (row.get("notes", "") + " " + note).strip()
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows[name] for name in sorted(rows))

def run_test(check_only=False):
    context, selection, dev, counts, selection_hash = frozen_context()
    questions = [question for question in context["questions"] if question["split"] == "test"]
    dev_ids = {question["id"] for question in context["questions"] if question["split"] == "dev"}
    if len(questions) < 5 or dev_ids & {q["id"] for q in questions}:
        raise ValueError("Invalid held-out split")
    selected = selection["selected_strategy"]
    print(f"Test questions: {len(questions)} | Strategies: A, B, C")
    print(f"Selected on dev (unchanged): {selected}")
    print(f"Database rows: {counts}")
    if check_only:
        print("TEST INPUT CHECK OK (no test query embeddings, retrieval or scoring executed)")
        return
    trace_path = ROOT / "results/traces/test.jsonl"
    metric_path = ROOT / "results/metrics/test.json"
    if trace_path.exists() or metric_path.exists():
        raise ValueError("Test output already exists. Preserve the existing run for review instead of overwriting it.")
    began = perf_counter()
    model = context["manifest"]["model"]
    config = context["config"]
    embedder = MyEmbedder(
        model["model_name"], revision=model["revision"], batch_size=config["batch_size"],
        threads=config["torch_threads"], offline=True
    )
    if embedder.info != model or fingerprints() != context["fingerprints"]:
        raise ValueError("Model or input files changed during test setup")
    # Record the attempt and open output exclusively before any test retrieval.
    # Even a partially completed trace prevents run_dev.py from tuning after exposure.
    write_json(ROOT / "results/logs/test_attempt.json", {
        "started_at": datetime.now(ZoneInfo("Asia/Bangkok")).isoformat(timespec="seconds"),
        "selected_strategy_from_dev": selected,
        "frozen_selection_sha256": selection_hash,
        "input_fingerprints": context["fingerprints"],
        "holdout_evaluator_sha256": digest(Path(__file__)),
        "test_question_ids": [q["id"] for q in questions],
        "note": "If interrupted, preserve the partial trace; do not use its results to tune dev."
    })
    traces = []
    with trace_path.open("x", encoding="utf-8") as stream:
        print("Embedding only test question text...", flush=True)
        query_began = perf_counter()
        vectors = embedder.embed_documents([q["question"] for q in questions])
        query_seconds = perf_counter() - query_began
        cache_stats = dict(embedder.last_cache_stats)
        for number, (question, vector) in enumerate(zip(questions, vectors, strict=True)):
            order = ["A", "B", "C"]
            order = order[number % 3:] + order[:number % 3]
            for strategy in order:
                trace = retrieve_one(
                    question, strategy, vector, context["store"],
                    config["strategies"][strategy]["use_filter"]
                )
                traces.append(trace)
                stream.write(json.dumps(trace, ensure_ascii=False) + "\n")
                stream.flush()
            print(f"Test {number+1}/{len(questions)}: {question['id']} done", flush=True)
    if len(traces) != len(questions) * 3:
        raise ValueError("Incomplete test trace")
    if fingerprints() != context["fingerprints"] or digest(ROOT / "configs/selected_strategy.json") != selection_hash:
        raise ValueError("Inputs or frozen selection changed during test; preserve the trace for review")
    summary = summarize(traces)
    if any(row["split"] != "test" for row in summary):
        raise ValueError("Test summary contains a different split")
    write_json(metric_path, {
        "created_at": datetime.now(ZoneInfo("Asia/Bangkok")).isoformat(timespec="seconds"),
        "split": "test", "summary": summary,
        "selected_strategy_from_dev": selected,
        "selected_strategy_test_metrics": next(row for row in summary if row["strategy"] == selected),
        "selection_changed_using_test": False,
        "frozen_selection_sha256": selection_hash,
        "input_fingerprints": context["fingerprints"],
        "holdout_evaluator_sha256": digest(Path(__file__)),
        "model": model, "chunk_counts": counts,
        "query_embedding_seconds": query_seconds, "query_cache": cache_stats,
        "total_seconds": perf_counter() - began, "service_cost_usd": 0.0,
        "traces_sha256": digest(trace_path),
        "notes": [
            "Five held-out Module 3 questions; same corpus/model/strategies as dev.",
            "The configuration selected on dev remains fixed regardless of test ranking.",
            "Only question text and an explicitly supplied metadata filter enter retrieval.",
            "Strict complete-evidence matching; inspect valid equivalent evidence explicitly if needed.",
            "Test has five questions: one question changes the percentage by 20 points.",
            "Coherence, metadata correctness and grounding still require separate recorded review."
        ]
    })
    save_metrics_csv(ROOT / "results/metrics/test.csv", summary, counts)
    save_metrics_csv(ROOT / "results/metrics/combined.csv", dev["summary"] + summary, counts)
    update_test_experiment_log(summary, selected)
    for row in summary:
        print(f"{row['strategy']}: Hit@1 {row['hit1_n']}/{row['questions']} | Evidence Hit@3 {row['evidence_hit3_n']}/{row['questions']}")
    print(f"Selected on dev remains: {selected}")
    print("Trace: results/traces/test.jsonl")
    print("Metrics: results/metrics/test.json, test.csv and combined.csv")
    print("TEST BENCHMARK OK")

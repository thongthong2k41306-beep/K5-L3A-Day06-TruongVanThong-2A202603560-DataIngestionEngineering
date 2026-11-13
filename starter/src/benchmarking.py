"""Controlled dev evaluation and a frozen selection; never run holdout test implicitly."""
import csv
import json
from dataclasses import asdict
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
import numpy as np
from dotenv import dotenv_values
from .embedding_artifacts import digest, load_embedding_artifacts
from .embeddings import MyEmbedder
from .evaluation import evaluate_query, summarize, validate_benchmark
from .models import DocumentPage
from .paths import ROOT, STARTER, read_json, read_jsonl, write_json, write_jsonl
from .store import PgVectorStore

def fingerprints():
    files = {
        "questions": "benchmark/questions.json",
        "protocol": "benchmark/protocol.json",
        "strategies": "configs/strategies.json",
        "pages": "data/processed/pages.jsonl",
        "embeddings": "results/metrics/embeddings.json",
        "ingestion": "results/metrics/ingestion.json",
        "model_lock": "configs/model_lock.json",
        "retrieval_code": "starter/src/benchmarking.py",
        "evaluation_code": "starter/src/evaluation.py",
        "store_code": "starter/src/store.py",
        "embedding_code": "starter/src/embeddings.py"
    }
    return {name: digest(ROOT / path) for name, path in files.items()}

def load_ready_context():
    manifest, banks = load_embedding_artifacts()
    ingestion = read_json(ROOT / "results/metrics/ingestion.json")
    if ingestion.get("status") != "complete" or not ingestion.get("idempotency_verified"):
        raise ValueError("Complete scripts/ingest_vectors.py first")
    if ingestion["embedding_manifest_sha256"] != digest(ROOT / "results/metrics/embeddings.json"):
        raise ValueError("Embedding artifacts changed since database ingestion")
    if ingestion["model"] != manifest["model"]:
        raise ValueError("Ingestion model differs from the embedding model")
    questions = read_json(ROOT / "benchmark/questions.json")
    protocol = read_json(ROOT / "benchmark/protocol.json")
    if digest(ROOT / "benchmark/questions.json") != protocol["questions_sha256"]:
        raise ValueError("Benchmark differs from its frozen protocol")
    pages = [DocumentPage(**row) for row in read_jsonl(ROOT / "data/processed/pages.jsonl")]
    validate_benchmark(questions, pages)
    config = read_json(ROOT / "configs/strategies.json")
    if config["selection_rule"] != ["dev_evidence_hit3", "dev_hit1", "lower_chunk_count", "strategy_name"]:
        raise ValueError("Selection rule differs from the implemented predeclared rule")
    database_url = dotenv_values(STARTER / ".env").get("DATABASE_URL")
    if not database_url or urlparse(database_url).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Check local DATABASE_URL in starter/.env")
    store = PgVectorStore(database_url, manifest["model"]["dimensions"])
    counts = store.counts()
    for strategy, (chunks, vectors) in banks.items():
        if counts.get(strategy) != len(chunks):
            raise ValueError(f"Database count differs from the embedding snapshot: {strategy}")
        stored = {row["chunk_id"]: row for row in store.read_snapshot(strategy)}
        if set(stored) != {chunk.chunk_id for chunk in chunks}:
            raise ValueError(f"Database IDs differ from the snapshot: {strategy}")
        for chunk, vector in zip(chunks, vectors, strict=True):
            row = stored[chunk.chunk_id]
            if any(row[name] != value for name, value in (
                ("document_id", chunk.document_id), ("source", chunk.source),
                ("page", chunk.page), ("text", chunk.text)
            )):
                raise ValueError("Database source/content differs from the verified corpus")
            if any(row["metadata"].get(k) != v for k, v in chunk.metadata.items()):
                raise ValueError("Database source metadata differs from the verified corpus")
            if row["metadata"].get("embedding_revision") != manifest["model"]["revision"]:
                raise ValueError("Database embedding revision differs")
            # PostgreSQL stores float32 vectors; nine significant digits round-trip float32.
            actual = np.asarray(json.loads(row["embedding_text"]), dtype=np.float32)
            if not np.array_equal(actual, vector):
                raise ValueError(f"Database vector differs from the actual model output: {strategy}")
    return {
        "manifest": manifest, "banks": banks, "questions": questions,
        "protocol": protocol, "pages": pages, "config": config, "store": store,
        "fingerprints": fingerprints()
    }

def coherence_positions(pages, write=False):
    path = ROOT / "benchmark/coherence_positions.json"
    if path.exists():
        positions = read_json(path)
    else:
        positions = []
        for page in sorted(pages, key=lambda p: (p.document_id, p.page))[:10]:
            offset = len(page.text) // 2
            while offset < len(page.text) and page.text[offset].isspace():
                offset += 1
            if offset == len(page.text):
                offset = len(page.text.rstrip()) - 1
            positions.append({
                "document_id": page.document_id, "page": page.page,
                "char_offset": offset, "source": page.source,
                "source_excerpt": page.text[max(0, offset-80):offset+80],
                "sampling_method": "First ten sorted selected pages; midpoint moved to next non-whitespace character; fixed before retrieval scoring."
            })
    lookup = {(page.document_id, page.page): page for page in pages}
    if len(positions) != 10 or len({(p["document_id"], p["page"], p["char_offset"]) for p in positions}) != 10:
        raise ValueError("Need ten distinct fixed source positions for coherence audit")
    for position in positions:
        page = lookup.get((position["document_id"], position["page"]))
        if page is None or not 0 <= position["char_offset"] < len(page.text):
            raise ValueError("Coherence position does not belong to the current corpus")
    if write and not path.exists():
        write_json(path, positions)
    return positions

def retrieve_one(question, strategy, vector, store, use_filter):
    # Search receives only the query vector and an explicitly supplied filter.
    # Gold fields are accessed exclusively AFTER hits have been returned.
    filters = (question.get("filter") or {}) if use_filter else {}
    began = perf_counter()
    hits = store.search(strategy, vector, top_k=3, filters=filters)
    latency_ms = (perf_counter() - began) * 1000
    trace = evaluate_query(question, hits)
    return {
        **trace, "strategy": strategy, "applied_filter": filters,
        "latency_ms": latency_ms, "gold_fields_used_for_search": False,
        "retrieval_metric": "exact cosine in PostgreSQL + pgvector"
    }

def select_on_dev(summary, counts):
    if any(row["split"] != "dev" for row in summary):
        raise ValueError("Strategy selection may use only dev metrics")
    return min(summary, key=lambda row: (
        -row["evidence_hit3"], -row["hit1"], counts[row["strategy"]], row["strategy"]
    ))["strategy"]

def save_metrics_csv(path, summary, counts):
    fields = ["strategy","split","questions","hit1_n","hit1","evidence_hit3_n",
              "evidence_hit3","filter_questions","filter_compliant_n","filter_compliance",
              "mean_latency_ms","chunk_count"]
    with Path(path).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in summary:
            writer.writerow({**row, "chunk_count": counts[row["strategy"]]})

def update_experiment_log(config, model, summary):
    path = ROOT / "artifacts/experiment_log.csv"
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields, old = reader.fieldnames, {row["strategy"]: row for row in reader}
    hypotheses = {
        "A": "Fixed character windows provide a simple baseline; overlap can duplicate content or cut evidence.",
        "B": "Sentence/paragraph/line boundaries may retain meaning better than fixed windows.",
        "C": "Question-supplied module/lecture scope may reduce off-topic retrieval; it can also over-restrict."
    }
    for metric in summary:
        name = metric["strategy"]
        settings = config["strategies"][name]
        row = old.setdefault(name, {key:"" for key in fields})
        row.update({
            "strategy": name, "chunking": settings["chunking"],
            "chunk_size": settings["chunk_size"], "overlap": settings["overlap"],
            "metadata": "document_id/source/page/module/lecture/language",
            "filter": "question-supplied module/lecture" if settings["use_filter"] else "none",
            "vectorizer": model["model_name"] + "@" + model["revision"],
            "hypothesis": hypotheses[name],
            "dev_hit1": f"{metric['hit1_n']}/{metric['questions']}",
            "dev_hit3": f"{metric['evidence_hit3_n']}/{metric['questions']}"
        })
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(old[name] for name in sorted(old))

def run_dev(check_only=False):
    if (ROOT / "results/metrics/test.json").exists() or (ROOT / "results/traces/test.jsonl").exists():
        raise ValueError("Test results already exist. Preserve the frozen run; do not tune dev against exposed test results.")
    context = load_ready_context()
    questions = [q for q in context["questions"] if q["split"] == "dev"]
    counts = {name: len(bank[0]) for name, bank in context["banks"].items()}
    coherence_positions(context["pages"], write=not check_only)
    print(f"Dev questions: {len(questions)} | Strategies: A, B, C")
    print(f"Database rows: {counts}")
    if check_only:
        print("DEV INPUT CHECK OK (no query embedding, retrieval or scoring executed)")
        return
    began = perf_counter()
    config, model = context["config"], context["manifest"]["model"]
    embedder = MyEmbedder(
        model["model_name"], revision=model["revision"], batch_size=config["batch_size"],
        threads=config["torch_threads"], offline=True
    )
    if embedder.info != model or fingerprints() != context["fingerprints"]:
        raise ValueError("Model or input files changed during dev setup")
    print("Embedding only dev question text...", flush=True)
    query_began = perf_counter()
    vectors = embedder.embed_documents([question["question"] for question in questions])
    query_seconds = perf_counter() - query_began
    cache_stats = dict(embedder.last_cache_stats)
    traces = []
    for number, (question, vector) in enumerate(zip(questions, vectors, strict=True)):
        # Rotate A/B/C order to reduce a fixed order advantage in latency reporting.
        order = ["A", "B", "C"]
        order = order[number % 3:] + order[:number % 3]
        for strategy in order:
            traces.append(retrieve_one(
                question, strategy, vector, context["store"],
                config["strategies"][strategy]["use_filter"]
            ))
        print(f"Dev {number+1}/{len(questions)}: {question['id']} done", flush=True)
    if fingerprints() != context["fingerprints"]:
        raise ValueError("Input files changed during evaluation; results not frozen")
    if len(traces) != len(questions) * 3:
        raise ValueError("Incomplete dev query trace")
    summary = summarize(traces)
    selected = select_on_dev(summary, counts)
    trace_path = ROOT / "results/traces/dev.jsonl"
    metric_path = ROOT / "results/metrics/dev.json"
    write_jsonl(trace_path, sorted(traces, key=lambda t: (t["strategy"], t["question_id"])))
    write_json(metric_path, {
        "created_at": datetime.now(ZoneInfo("Asia/Bangkok")).isoformat(timespec="seconds"),
        "split": "dev", "summary": summary, "selected_strategy": selected,
        "selection_rule": context["protocol"]["selection_rule"],
        "model": model, "chunk_counts": counts,
        "input_fingerprints": context["fingerprints"],
        "query_embedding_seconds": query_seconds, "query_cache": cache_stats,
        "total_seconds": perf_counter() - began, "service_cost_usd": 0.0,
        "notes": [
            "Same question vectors for A/B/C; encode only question text, never answer/evidence.",
            "Filters come from explicit question context; only C applies them.",
            "Each query uses a new PostgreSQL connection; latency includes connection and SQL, excludes shared embedding time.",
            "Strict complete-quote hits are a conservative automatic proxy; human-equivalent evidence needs explicit review.",
            "No test queries executed. Human coherence/grounding labels are not inferred from hit metrics."
        ]
    })
    save_metrics_csv(ROOT / "results/metrics/dev.csv", summary, counts)
    update_experiment_log(config, model, summary)
    write_json(ROOT / "configs/selected_strategy.json", {
        "frozen_at": datetime.now(ZoneInfo("Asia/Bangkok")).isoformat(timespec="seconds"),
        "selected_strategy": selected, "selected_on_split": "dev",
        "selection_rule": context["protocol"]["selection_rule"],
        "test_results_used_for_selection": False,
        "input_fingerprints": context["fingerprints"],
        "dev_metrics_sha256": digest(metric_path),
        "dev_traces_sha256": digest(trace_path),
        "coherence_positions_sha256": digest(ROOT / "benchmark/coherence_positions.json")
    })
    for row in summary:
        print(f"{row['strategy']}: Hit@1 {row['hit1_n']}/{row['questions']} | Evidence Hit@3 {row['evidence_hit3_n']}/{row['questions']}")
    print(f"Selected on dev and frozen: {selected}")
    print("Trace: results/traces/dev.jsonl")
    print("Metrics: results/metrics/dev.json and dev.csv")
    print("DEV BENCHMARK OK")

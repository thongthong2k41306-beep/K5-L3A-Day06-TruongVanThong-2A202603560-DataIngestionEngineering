"""Load verified local embedding snapshots into PostgreSQL, then verify safe re-ingestion."""
from argparse import ArgumentParser
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from time import perf_counter
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import dotenv_values
from src.embedding_artifacts import load_embedding_artifacts, digest
from src.paths import ROOT, STARTER, write_json
from src.store import PgVectorStore

def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true",
                        help="Validate files and read backend status without creating tables or writing rows")
    args = parser.parse_args()
    began = perf_counter()
    manifest, banks = load_embedding_artifacts()
    env_file = STARTER / ".env"
    if not env_file.is_file():
        raise ValueError("Copy .env.example to .env in starter first")
    database_url = dotenv_values(env_file).get("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL missing in starter/.env")
    if urlparse(database_url).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("This starter step expects the local lab database; check DATABASE_URL")
    model = manifest["model"]
    store = PgVectorStore(database_url, model["dimensions"])
    backend = store.backend_info()
    before = store.counts()
    print(f"PostgreSQL: {backend['postgres']} | pgvector: {backend['pgvector']}")
    print(f"Model dimensions: {model['dimensions']}")
    for strategy, (chunks, _) in banks.items():
        print(f"{strategy}: {len(chunks)} verified chunk/vector pairs")
    if args.check_only:
        print(f"Existing row counts: {before}")
        print("INGESTION INPUT CHECK OK (database not modified)")
        return
    store.create_schema()
    first_counts, repeat_counts, timings = {}, {}, {}
    for strategy, (chunks, vectors) in banks.items():
        # Keep the original source fields and add the identity of the embedding.
        stored_chunks = [replace(chunk, metadata={
            **chunk.metadata, "embedding_model": model["model_name"],
            "embedding_revision": model["revision"],
            "embedding_dimensions": model["dimensions"]
        }) for chunk in chunks]
        batch_began = perf_counter()
        store.upsert(strategy, stored_chunks, vectors)
        timings[strategy] = {"first_upsert_seconds": round(perf_counter() - batch_began, 6)}
        first_counts[strategy] = store.counts().get(strategy, 0)
        if first_counts[strategy] != len(chunks):
            raise ValueError(f"Stored count mismatch for {strategy}")
        # This deliberate second write verifies idempotency on the real backend.
        batch_began = perf_counter()
        store.upsert(strategy, stored_chunks, vectors)
        timings[strategy]["repeat_upsert_seconds"] = round(perf_counter() - batch_began, 6)
        repeat_counts[strategy] = store.counts().get(strategy, 0)
        if repeat_counts[strategy] != first_counts[strategy]:
            raise ValueError(f"Re-ingestion duplicated rows for {strategy}")
        print(f"{strategy}: {repeat_counts[strategy]} rows | repeat ingestion: no duplicates", flush=True)

    smoke = []
    for strategy, (chunks, vectors) in banks.items():
        sample = chunks[0]
        filters = {"module": sample.metadata["module"], "lecture": sample.metadata["lecture"]} if strategy == "C" else None
        hits = store.search(strategy, vectors[0], top_k=3, filters=filters)
        if not hits or hits[0]["score"] < 0.999:
            raise ValueError(f"Self-vector search did not return a near-identical vector: {strategy}")
        if any(any(hit["metadata"].get(k) != v for k, v in (filters or {}).items()) for hit in hits):
            raise ValueError("Backend metadata filter failed")
        smoke.append({
            "strategy": strategy, "kind": "self-vector backend check, not a benchmark question",
            "input_chunk_id": sample.chunk_id, "applied_filter": filters or {},
            "hits": [{k: hit[k] for k in ("chunk_id", "document_id", "source", "page", "score", "metadata")}
                     for hit in hits]
        })
    write_json(ROOT / "results/logs/store_smoke.json", smoke)
    write_json(ROOT / "results/metrics/ingestion.json", {
        "created_at": datetime.now(ZoneInfo("Asia/Bangkok")).isoformat(timespec="seconds"),
        "status": "complete", "backend": backend, "model": model,
        "embedding_manifest_sha256": digest(ROOT / "results/metrics/embeddings.json"),
        "counts_before": before, "counts_after_first": first_counts,
        "counts_after_repeat": repeat_counts,
        "idempotency_verified": first_counts == repeat_counts,
        "strategies": timings, "total_step_seconds": round(perf_counter() - began, 6),
        "service_cost_usd": 0.0,
        "update_policy": "Each upsert supplies the full snapshot of one strategy. Stable IDs are upserted; obsolete IDs within only that strategy are removed transactionally.",
        "smoke_test": "Exact cosine self-vector search; C metadata filter checked; no benchmark questions executed.",
        "persistence": "PostgreSQL named volume configured in starter/docker-compose.yml; container restart persistence not yet tested."
    })
    print(f"Total stored rows: {sum(repeat_counts.values())}")
    print("Metrics: results/metrics/ingestion.json")
    print("VECTOR STORE OK")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Database exceptions can include connection details; store only their type.
        write_json(ROOT / "results/logs/ingestion_error.json", {
            "exception_type": type(exc).__name__,
            "hint": "Check Docker, scripts/check_setup.py, embedding hashes and local DATABASE_URL.",
            "mock_fallback": False
        })
        print(f"VECTOR STORE FAILED: {type(exc).__name__}. Check Docker and scripts/check_setup.py.", file=sys.stderr)
        if isinstance(exc, (ValueError, FileNotFoundError)):
            print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc

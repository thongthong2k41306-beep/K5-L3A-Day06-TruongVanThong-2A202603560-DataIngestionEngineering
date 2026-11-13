"""Create real local embeddings; save checked vectors for the later PostgreSQL ingestion step."""
from argparse import ArgumentParser
from dataclasses import asdict
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from statistics import mean, median
from time import perf_counter
from zoneinfo import ZoneInfo
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.chunking import enforce_token_limit
from src.embeddings import MyEmbedder
from src.models import Chunk, DocumentPage
from src.paths import ROOT, read_json, read_jsonl, write_json, write_jsonl
from scripts.prepare_chunks import validate_chunks

def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()

def load_inputs(config):
    page_path = ROOT / "data/processed/pages.jsonl"
    stats = read_json(ROOT / "results/metrics/chunking.json")
    if digest(page_path) != stats["input_pages_sha256"]:
        raise ValueError("Corpus changed; rerun prepare_chunks.py first")
    pages = [DocumentPage(**row) for row in read_jsonl(page_path)]
    groups = {}
    for name in ("A", "B", "C"):
        for key, value in config["strategies"][name].items():
            if stats["strategies"][name].get(key) != value:
                raise ValueError("Strategy configuration changed; rerun prepare_chunks.py first")
        groups[name] = [Chunk(**row) for row in read_jsonl(ROOT / f"data/processed/chunks_{name}.jsonl")]
        validate_chunks(groups[name], pages)
    if groups["B"] != groups["C"]:
        raise ValueError("B/C input chunks must be identical")
    return pages, groups

def build_final_chunks(groups, pages, embedder):
    final, summaries = {}, {}
    for name in ("A", "B"):
        chunks = enforce_token_limit(groups[name], embedder)
        validate_chunks(chunks, pages)
        counts = [chunk.metadata["token_count"] for chunk in chunks]
        if any(n > embedder.max_seq_length for n in counts):
            raise ValueError("Chunk still exceeds model token limit")
        if any(not chunk.text.strip() for chunk in chunks):
            raise ValueError("Empty finalized chunk")
        final[name] = chunks
        summaries[name] = {
            "character_chunk_count": len(groups[name]),
            "final_chunk_count": len(chunks),
            "original_chunks_over_token_limit": sum(
                embedder.token_count(chunk.text) > embedder.max_seq_length
                for chunk in groups[name]),
            "total_tokens_with_special_tokens_and_overlap": sum(counts),
            "max_tokens": max(counts), "mean_tokens": round(mean(counts), 2),
            "median_tokens": median(counts),
            "max_characters": max(len(chunk.text) for chunk in chunks),
            "total_characters_with_overlap": sum(len(chunk.text) for chunk in chunks)
        }
    final["C"] = final["B"]
    summaries["C"] = {**summaries["B"], "reuses_chunks_and_vectors_from": "B"}
    return final, summaries

def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true",
                        help="Validate model/chunks without encoding or writing result artifacts")
    parser.add_argument("--download-model", action="store_true",
                        help="Allow model downloads if the pinned model is not in the local cache")
    args = parser.parse_args()
    began = perf_counter()
    config = read_json(ROOT / "configs/strategies.json")
    pages, groups = load_inputs(config)
    print("Loading the real local embedding model...", flush=True)
    model_began = perf_counter()
    embedder = MyEmbedder(
        config["model_name"], revision=config.get("model_revision"),
        batch_size=config["batch_size"], threads=config["torch_threads"],
        offline=not args.download_model
    )
    model_seconds = perf_counter() - model_began
    final, summaries = build_final_chunks(groups, pages, embedder)
    print(f"Model: {embedder.model_name}")
    print(f"Dimensions: {embedder.dimensions} | Token limit: {embedder.max_seq_length}")
    for name in ("A", "B", "C"):
        print(f"{name}: {len(groups[name])} character chunks -> {len(final[name])} final chunks")
    if args.check_only:
        print("EMBEDDING INPUT CHECK OK (no document encoding or result files written)")
        return

    import numpy as np
    artifacts = {}
    for name in ("A", "B"):
        chunk_path = ROOT / f"data/processed/embedded_chunks_{name}.jsonl"
        vector_path = ROOT / f"artifacts/embedding_cache/strategy_{name}.npz"
        print(f"Encoding strategy {name}...", flush=True)
        encoding_began = perf_counter()
        vectors = np.asarray(embedder.embed_documents([chunk.text for chunk in final[name]]), dtype=np.float32)
        encoding_seconds = perf_counter() - encoding_began
        if vectors.shape != (len(final[name]), embedder.dimensions):
            raise ValueError("Model output shape does not match the chunks")
        norms = np.linalg.norm(vectors, axis=1)
        if not np.isfinite(vectors).all() or not np.allclose(norms, 1.0, atol=1e-5):
            raise ValueError("Vectors must be finite, nonzero and L2-normalized")
        write_jsonl(chunk_path, [asdict(chunk) for chunk in final[name]])
        np.savez_compressed(
            vector_path, embeddings=vectors,
            chunk_ids=np.asarray([chunk.chunk_id for chunk in final[name]], dtype=str),
            model_name=np.asarray(embedder.model_name),
            model_revision=np.asarray(embedder.revision)
        )
        # Bind the row order to IDs and verify the artifact is readable without pickle.
        with np.load(vector_path, allow_pickle=False) as saved:
            if saved["chunk_ids"].tolist() != [chunk.chunk_id for chunk in final[name]]:
                raise ValueError("Vector/chunk row order mismatch")
            if not np.array_equal(saved["embeddings"], vectors):
                raise ValueError("Saved vector values differ from actual model output")
        summaries[name].update({
            "embedding_seconds": round(encoding_seconds, 6),
            "cache": dict(embedder.last_cache_stats),
            "vector_norm_min": float(norms.min()), "vector_norm_max": float(norms.max())
        })
        artifacts[name] = {
            "chunks_path": chunk_path.relative_to(ROOT).as_posix(),
            "chunks_sha256": digest(chunk_path),
            "vectors_path": vector_path.relative_to(ROOT).as_posix(),
            "vectors_sha256": digest(vector_path), "vector_rows": len(final[name])
        }
        print(f"{name}: saved {len(final[name])} vectors ({embedder.dimensions} dimensions)", flush=True)

    c_path = ROOT / "data/processed/embedded_chunks_C.jsonl"
    write_jsonl(c_path, [asdict(chunk) for chunk in final["C"]])
    summaries["C"].update({
        "embedding_seconds": 0.0, "cache": {"reused_from": "B"},
        "vector_norm_min": summaries["B"]["vector_norm_min"],
        "vector_norm_max": summaries["B"]["vector_norm_max"]
    })
    artifacts["C"] = {
        **artifacts["B"], "chunks_path": c_path.relative_to(ROOT).as_posix(),
        "chunks_sha256": digest(c_path), "vectors_reused_from": "B"
    }
    if c_path.read_bytes() != (ROOT / artifacts["B"]["chunks_path"]).read_bytes():
        raise ValueError("B/C finalized chunks differ")
    write_json(ROOT / "results/metrics/embeddings.json", {
        "created_at": datetime.now(ZoneInfo("Asia/Bangkok")).isoformat(timespec="seconds"),
        "status": "complete", "model": embedder.info,
        "source_pages_sha256": digest(ROOT / "data/processed/pages.jsonl"),
        "strategies_config_sha256": digest(ROOT / "configs/strategies.json"),
        "model_load_seconds": round(model_seconds, 6),
        "total_step_seconds": round(perf_counter() - began, 6),
        "strategies": summaries, "artifacts": artifacts,
        "service_cost_usd": 0.0,
        "notes": [
            "All vectors are produced locally by the same real pinned model. No PDF text is uploaded.",
            "A/B encode different chunks; C reuses B vectors and differs only by query-time filter.",
            "Character chunks over the model token limit are split explicitly using the same rule for all strategies.",
            "Cached embeddings reduce repeat runtime; cache hit/new counts are recorded.",
            "Vector files here are intermediate artifacts. PostgreSQL storage/search is the next step.",
            "No dev/test retrieval or scoring is performed in this step."
        ]
    })
    print(f"C: reuses {len(final['C'])} vectors from B")
    print("Metrics: results/metrics/embeddings.json")
    print("EMBEDDINGS OK")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        write_json(ROOT / "results/logs/embedding_error.json", {
            "exception_type": type(exc).__name__, "message": str(exc),
            "mock_fallback": False
        })
        print(f"EMBEDDINGS FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

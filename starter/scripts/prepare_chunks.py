"""Prepare page-traceable character chunks; no embeddings or retrieval are run."""
from argparse import ArgumentParser
from collections import defaultdict
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from statistics import mean, median
from time import perf_counter
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.chunking import fixed_size, by_paragraph
from src.evaluation import validate_benchmark
from src.models import DocumentPage
from src.paths import ROOT, read_json, read_jsonl, write_json, write_jsonl

def validate_chunks(chunks, pages):
    lookup = {(page.document_id, page.page): page for page in pages}
    if not chunks or len({c.chunk_id for c in chunks}) != len(chunks):
        raise ValueError("Missing chunks or duplicate IDs")
    coverage = {key: bytearray(len(page.text)) for key, page in lookup.items()}
    for chunk in chunks:
        key = (chunk.document_id, chunk.page)
        if key not in lookup:
            raise ValueError("Chunk belongs to a page outside the selected corpus")
        page = lookup[key]
        start, end = chunk.metadata["char_start"], chunk.metadata["char_end"]
        if not 0 <= start < end <= len(page.text) or page.text[start:end] != chunk.text:
            raise ValueError(f"Source offsets do not match chunk {chunk.chunk_id}")
        if chunk.source != page.source or any(
            chunk.metadata.get(name) != page.metadata.get(name)
            for name in ("module", "lecture", "language")
        ):
            raise ValueError("Source or filter metadata changed during chunking")
        coverage[key][start:end] = b"\x01" * (end - start)
    for key, page in lookup.items():
        if any(not covered and not char.isspace()
               for covered, char in zip(coverage[key], page.text, strict=True)):
            raise ValueError(f"Chunking dropped source content on page {key[1]}")

def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true", help="Validate in memory without writing output files")
    args = parser.parse_args()
    config = read_json(ROOT / "configs/strategies.json")
    page_path = ROOT / "data/processed/pages.jsonl"
    if not page_path.exists():
        raise ValueError("Run scripts/prepare_data.py first")
    pages = [DocumentPage(**p) for p in read_jsonl(page_path)]
    if len(pages) < 30:
        raise ValueError("Corpus must contain at least 30 content pages")
    validate_benchmark(read_json(ROOT / "benchmark/questions.json"), pages)
    a, b, c = (config["strategies"][name] for name in ("A", "B", "C"))
    if a["chunking"] != "fixed" or b["chunking"] != "paragraph":
        raise ValueError("Expected A=fixed and B=paragraph")
    if {k: v for k, v in b.items() if k != "use_filter"} != {
        k: v for k, v in c.items() if k != "use_filter"
    } or b["use_filter"] or not c["use_filter"] or a["use_filter"]:
        raise ValueError("B/C must differ only in filter; A/B must not filter")
    groups, stats = {}, {}
    for name in ("A", "B"):
        settings = config["strategies"][name]
        began = perf_counter()
        if name == "A":
            chunks = [chunk for page in pages for chunk in fixed_size(
                page, settings["chunk_size"], settings["overlap"])]
        else:
            chunks = [chunk for page in pages for chunk in by_paragraph(
                page, settings["chunk_size"])]
        validate_chunks(chunks, pages)
        lengths = [len(chunk.text) for chunk in chunks]
        if max(lengths) > settings["chunk_size"]:
            raise ValueError("Chunk exceeds configured character limit")
        groups[name] = chunks
        stats[name] = {
            **settings, "chunk_count": len(chunks),
            "total_characters_with_overlap": sum(lengths),
            "min_characters": min(lengths), "max_characters": max(lengths),
            "mean_characters": round(mean(lengths), 2), "median_characters": median(lengths),
            "chunking_validation_seconds": round(perf_counter() - began, 6)
        }
    # Share the same chunk objects and IDs; filtering is a later query-time action.
    groups["C"] = groups["B"]
    stats["C"] = {
        **stats["B"], **c, "chunking_validation_seconds": 0.0,
        "reuses_chunks_from": "B"
    }
    print(f"Content pages: {len(pages)}")
    for name in ("A", "B", "C"):
        print(f"{name}: {len(groups[name])} chunks | max {stats[name]['max_characters']} characters")
    print("B/C chunks and IDs are identical. C filters only during retrieval.")
    if args.check_only:
        print("CHUNK VALIDATION OK (no output written)")
        return
    for name, chunks in groups.items():
        write_jsonl(ROOT / f"data/processed/chunks_{name}.jsonl", [asdict(chunk) for chunk in chunks])
    write_json(ROOT / "results/metrics/chunking.json", {
        "stage": "character_chunking_before_embedding_token_limit",
        "input_pages_sha256": sha256(page_path.read_bytes()).hexdigest(),
        "input_content_pages": len(pages),
        "strategies": stats,
        "source_offsets_verified": True,
        "all_nonwhitespace_content_covered": True,
        "notes": [
            "PDF paragraph boundaries can be ambiguous: B falls back to sentence/line boundaries, then words.",
            "These are character-based chunks. Before embedding, apply the same model-token limit safeguard to all strategies and report final counts.",
            "No embedding, database ingestion, retrieval or test scoring is performed in this step."
        ]
    })
    print("Outputs: data/processed/chunks_A.jsonl, chunks_B.jsonl, chunks_C.jsonl")
    print("Metrics: results/metrics/chunking.json")
    print("CHUNKING OK")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"CHUNKING FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

"""Load and verify the link between finalized chunks and real embedding artifacts."""
from hashlib import sha256
from pathlib import Path
import numpy as np
from .models import Chunk
from .paths import ROOT, read_json, read_jsonl

def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()

def workspace_file(relative):
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file():
        raise ValueError(f"Missing or out-of-workspace artifact: {relative}")
    return path

def load_embedding_artifacts():
    manifest = read_json(ROOT / "results/metrics/embeddings.json")
    if manifest.get("status") != "complete":
        raise ValueError("Run scripts/embed_chunks.py to completion first")
    if digest(ROOT / "data/processed/pages.jsonl") != manifest["source_pages_sha256"]:
        raise ValueError("Corpus changed since embedding; rerun chunking and embedding")
    if digest(ROOT / "configs/strategies.json") != manifest["strategies_config_sha256"]:
        raise ValueError("Strategy config changed since embedding; regenerate embeddings")
    lock = read_json(ROOT / "configs/model_lock.json")
    for field in ("model_name", "revision", "dimensions", "normalization", "versions"):
        if lock.get(field) != manifest["model"].get(field):
            raise ValueError(f"Model lock differs from the embedding run: {field}")
    banks = {}
    dimensions = manifest["model"]["dimensions"]
    for strategy in ("A", "B", "C"):
        artifact = manifest["artifacts"][strategy]
        chunk_path = workspace_file(artifact["chunks_path"])
        vector_path = workspace_file(artifact["vectors_path"])
        if digest(chunk_path) != artifact["chunks_sha256"] or digest(vector_path) != artifact["vectors_sha256"]:
            raise ValueError(f"Embedding artifact checksum mismatch: {strategy}")
        chunks = [Chunk(**row) for row in read_jsonl(chunk_path)]
        if not chunks or len({chunk.chunk_id for chunk in chunks}) != len(chunks):
            raise ValueError("Empty chunk list or duplicate chunk IDs")
        with np.load(vector_path, allow_pickle=False) as archive:
            vectors = archive["embeddings"].copy()
            ids = archive["chunk_ids"].tolist()
            if archive["model_name"].item() != manifest["model"]["model_name"]:
                raise ValueError("Vector archive model mismatch")
            if archive["model_revision"].item() != manifest["model"]["revision"]:
                raise ValueError("Vector archive revision mismatch")
        if ids != [chunk.chunk_id for chunk in chunks]:
            raise ValueError(f"Chunk/vector order mismatch: {strategy}")
        if len(chunks) != artifact["vector_rows"] or vectors.shape != (len(chunks), dimensions):
            raise ValueError(f"Embedding row count or dimension mismatch: {strategy}")
        if not np.isfinite(vectors).all() or not np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5):
            raise ValueError(f"Invalid or unnormalized embeddings: {strategy}")
        banks[strategy] = (chunks, vectors)
    if banks["B"][0] != banks["C"][0] or not np.array_equal(banks["B"][1], banks["C"][1]):
        raise ValueError("B/C must share exactly the same chunks and vectors")
    return manifest, banks

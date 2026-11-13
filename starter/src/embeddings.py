"""Real local Sentence Transformer embeddings, with a content-addressed disk cache."""
from hashlib import sha256
import importlib.metadata
import json
import os
from pathlib import Path
from typing import Protocol
from .paths import ROOT, read_json, write_json

class Embedder(Protocol):
    model_name: str
    dimensions: int
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, question: str) -> list[float]: ...

class MyEmbedder:
    def __init__(self, model_name: str, revision=None, batch_size=24, threads=4, offline=False):
        os.environ.setdefault("HF_HOME", str(ROOT / ".cache/huggingface"))
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        if offline:
            os.environ["HF_HUB_OFFLINE"] = "1"
        import numpy as np
        import torch
        from sentence_transformers import SentenceTransformer
        torch.manual_seed(42)
        torch.set_num_threads(threads)
        self.np, self.model_name, self.batch_size = np, model_name, batch_size
        lock_path = ROOT / "configs/model_lock.json"
        lock = read_json(lock_path) if lock_path.exists() else {}
        if lock.get("model_name") == model_name and not revision:
            revision = lock.get("revision")
        if not revision and offline:
            raise RuntimeError("No pinned local model. Run embed_chunks.py --download-model first")
        if not revision:
            from huggingface_hub import model_info
            revision = model_info(model_name).sha
        self.revision = revision
        self.model = SentenceTransformer(
            model_name, revision=revision, device="cpu",
            cache_folder=str(ROOT / ".cache/huggingface/hub"),
            trust_remote_code=False, local_files_only=offline
        )
        dimension_getter = getattr(self.model, "get_embedding_dimension", None) or self.model.get_sentence_embedding_dimension
        self.dimensions = int(dimension_getter())
        self.max_seq_length = int(self.model.max_seq_length)
        self.cache_dir = ROOT / "artifacts/embedding_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.info = {
            "provider": "local Sentence Transformers", "model_name": model_name,
            "revision": revision, "dimensions": self.dimensions,
            "max_seq_length": self.max_seq_length, "device": "cpu",
            "normalization": "L2; encode() for both query and document; no prefixes",
            "document_upload": False, "service_cost_usd": 0.0,
            "versions": {p: importlib.metadata.version(p) for p in (
                "sentence-transformers", "transformers", "torch", "numpy")}
        }
        self.cache_fingerprint = sha256(json.dumps(self.info, sort_keys=True).encode()).hexdigest()
        self.last_cache_stats = {}
        write_json(lock_path, self.info)

    def token_count(self, text):
        return len(self.model.tokenizer.encode(
            text, add_special_tokens=True, truncation=False, verbose=False
        ))

    def _key(self, text):
        return sha256(f"{self.cache_fingerprint}|{text}".encode()).hexdigest()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        for text in texts:
            if not text.strip() or self.token_count(text) > self.max_seq_length:
                raise ValueError("Empty or oversized embedding input; chunk it explicitly first")
        vectors, missing = {}, {}
        for text in texts:
            key = self._key(text)
            path = self.cache_dir / f"{key}.npy"
            if path.exists():
                vector = self.np.load(path, allow_pickle=False)
                if vector.shape == (self.dimensions,) and self.np.isfinite(vector).all():
                    vectors[key] = vector
                    continue
            missing[key] = text
        self.last_cache_stats = {"unique_inputs": len(set(self._key(t) for t in texts)),
                                 "cache_hits": len(vectors), "new_embeddings": len(missing)}
        if missing:
            keys = list(missing)
            encoded = self.model.encode(
                [missing[k] for k in keys], batch_size=self.batch_size,
                normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=True
            )
            for key, vector in zip(keys, encoded, strict=True):
                if vector.shape != (self.dimensions,) or not self.np.isfinite(vector).all():
                    raise ValueError("Invalid model output")
                self.np.save(self.cache_dir / f"{key}.npy", vector, allow_pickle=False)
                vectors[key] = vector
        return [vectors[self._key(text)].tolist() for text in texts]

    def embed_query(self, question: str) -> list[float]:
        return self.embed_documents([question])[0]

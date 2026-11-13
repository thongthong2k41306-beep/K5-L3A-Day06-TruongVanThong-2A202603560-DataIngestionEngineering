"""Persistent exact cosine search in PostgreSQL + pgvector; never Python similarity."""
import math
from typing import Any
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from .models import Chunk

class PgVectorStore:
    allowed_filters = {"module", "lecture", "language"}
    def __init__(self, database_url: str, dimensions: int) -> None:
        if not database_url:
            raise ValueError("DATABASE_URL is required in starter/.env")
        if not isinstance(dimensions, int) or not 0 < dimensions <= 16000:
            raise ValueError("Invalid embedding dimensions")
        self.database_url, self.dimensions = database_url, dimensions

    def _connect(self):
        return psycopg.connect(self.database_url, connect_timeout=10, row_factory=dict_row)

    def _vector(self, vector):
        if len(vector) != self.dimensions or not all(math.isfinite(float(x)) for x in vector):
            raise ValueError("Embedding dimension mismatch or non-finite vector")
        if not any(float(x) != 0 for x in vector):
            raise ValueError("Zero vector is invalid for cosine search")
        return "[" + ",".join(format(float(x), ".9g") for x in vector) + "]"

    def create_schema(self) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT extversion FROM pg_extension WHERE extname='vector'")
                if not cursor.fetchone():
                    raise RuntimeError("pgvector is not enabled; run scripts/check_setup.py")
                cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS day6_chunks (
                        strategy TEXT NOT NULL,
                        chunk_id TEXT NOT NULL,
                        document_id TEXT NOT NULL,
                        source TEXT NOT NULL,
                        page INTEGER NOT NULL CHECK (page > 0),
                        content TEXT NOT NULL,
                        metadata JSONB NOT NULL,
                        embedding vector({self.dimensions}) NOT NULL,
                        PRIMARY KEY (strategy, chunk_id)
                    )
                """)
                cursor.execute("SELECT format_type(atttypid, atttypmod) AS type FROM pg_attribute WHERE attrelid='day6_chunks'::regclass AND attname='embedding'")
                actual = cursor.fetchone()["type"]
                if actual != f"vector({self.dimensions})":
                    raise ValueError(f"Existing table uses {actual}, model needs vector({self.dimensions}); use a separate database")
                cursor.execute("CREATE INDEX IF NOT EXISTS day6_strategy_document ON day6_chunks (strategy, document_id)")

    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        if not chunks or len(chunks) != len(vectors):
            raise ValueError("Chunks/vectors must be non-empty and have equal lengths")
        if len({c.chunk_id for c in chunks}) != len(chunks):
            raise ValueError("Duplicate chunk IDs in the ingestion batch")
        rows = [(strategy, c.chunk_id, c.document_id, c.source, c.page, c.text,
                 Jsonb(c.metadata), self._vector(v)) for c, v in zip(chunks, vectors, strict=True)]
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.executemany("""
                    INSERT INTO day6_chunks
                    (strategy,chunk_id,document_id,source,page,content,metadata,embedding)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s::vector)
                    ON CONFLICT (strategy,chunk_id) DO UPDATE SET
                        document_id=EXCLUDED.document_id,source=EXCLUDED.source,
                        page=EXCLUDED.page,content=EXCLUDED.content,
                        metadata=EXCLUDED.metadata,embedding=EXCLUDED.embedding
                """, rows)
                # This call supplies the COMPLETE snapshot of one strategy.
                # Delete only obsolete rows within that strategy, atomically.
                cursor.execute("DELETE FROM day6_chunks WHERE strategy=%s AND NOT (chunk_id=ANY(%s))",
                               (strategy, [c.chunk_id for c in chunks]))

    def search(self, strategy: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        filters = filters or {}
        if set(filters) - self.allowed_filters:
            raise ValueError(f"Unsupported filters: {set(filters) - self.allowed_filters}")
        vector = self._vector(query_vector)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT chunk_id,document_id,source,page,content AS text,metadata,
                           1 - (embedding <=> %s::vector) AS score,
                           embedding <=> %s::vector AS distance
                    FROM day6_chunks
                    WHERE strategy=%s AND metadata @> %s
                    ORDER BY embedding <=> %s::vector,chunk_id
                    LIMIT %s
                """, (vector, vector, strategy, Jsonb(filters), vector, top_k))
                return [dict(row) for row in cursor.fetchall()]

    def counts(self):
        with self._connect() as connection:
            exists = connection.execute("SELECT to_regclass('day6_chunks') AS table_name").fetchone()
            if exists["table_name"] is None:
                return {}
            return {row["strategy"]: row["count"] for row in connection.execute(
                "SELECT strategy,COUNT(*) AS count FROM day6_chunks GROUP BY strategy ORDER BY strategy")}

    def read_snapshot(self, strategy):
        """Read a strategy snapshot for integrity checks; no similarity search."""
        with self._connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT chunk_id,document_id,source,page,content AS text,metadata,"
                "embedding::text AS embedding_text FROM day6_chunks WHERE strategy=%s ORDER BY chunk_id",
                (strategy,))]

    def backend_info(self):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT current_setting('server_version') AS postgres,extversion AS pgvector FROM pg_extension WHERE extname='vector'").fetchone()
            return {**dict(row), "metric": "cosine", "search_mode": "exact", "table": "day6_chunks"}

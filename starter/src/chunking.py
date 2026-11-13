"""Page-bounded chunking; stable offsets let auditors compare identical source positions."""
from hashlib import sha256
import re
from .models import Chunk, DocumentPage

def make_chunk(page, start, end, method):
    raw = page.text[start:end]
    left = len(raw) - len(raw.lstrip())
    right = len(raw.rstrip())
    start, end = start + left, start + right
    if end <= start:
        return None
    text = page.text[start:end]
    key = f"{page.document_id}|{page.page}|{method}|{start}|{end}|{text}"
    chunk_id = sha256(key.encode("utf-8")).hexdigest()[:24]
    return Chunk(chunk_id, page.document_id, page.source, page.page, text,
                 {**page.metadata, "char_start": start, "char_end": end, "chunking": method})

def fixed_size(page: DocumentPage, size: int, overlap: int) -> list[Chunk]:
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("Require size > 0 and 0 <= overlap < size")
    chunks, start = [], 0
    while start < len(page.text):
        end = min(start + size, len(page.text))
        chunk = make_chunk(page, start, end, f"fixed:{size}:{overlap}")
        if chunk:
            chunks.append(chunk)
        if end == len(page.text):
            break
        start += size - overlap
    return chunks

def by_paragraph(page: DocumentPage, max_size: int) -> list[Chunk]:
    """Greedy packing at paragraphs/sentences/line boundaries; long spans split at words."""
    if max_size <= 0:
        raise ValueError("max_size must be positive")
    text, chunks, start = page.text, [], 0
    # PDF paragraphs are not always marked by blank lines. Sentence and line
    # boundaries are explicitly allowed as a fallback, recorded in the report.
    boundaries = {m.end() for m in re.finditer(r"\n\s*\n|[.!?](?:[ \t]+|\n)|\n", text)}
    while start < len(text):
        limit = min(start + max_size, len(text))
        if limit == len(text):
            end = limit
        else:
            candidates = [b for b in boundaries if start + max_size // 3 <= b <= limit]
            if candidates:
                end = max(candidates)
            else:
                spaces = [m.end() + start for m in re.finditer(r"\s+", text[start:limit])]
                end = max(spaces) if spaces else limit
        chunk = make_chunk(page, start, end, f"paragraph:{max_size}")
        if chunk:
            chunks.append(chunk)
        start = end
    return chunks

def enforce_token_limit(chunks, embedder):
    """Common safeguard for A/B/C: no embedding may silently truncate a chunk."""
    output = []
    for chunk in chunks:
        pending = [(chunk.metadata["char_start"], chunk.metadata["char_end"])]
        while pending:
            start, end = pending.pop(0)
            local_start = start - chunk.metadata["char_start"]
            text = chunk.text[local_start:local_start + end - start]
            if embedder.token_count(text) <= embedder.max_seq_length:
                key = f"{chunk.chunk_id}|{start}|{end}|{text}"
                output.append(Chunk(
                    sha256(key.encode()).hexdigest()[:24], chunk.document_id,
                    chunk.source, chunk.page, text,
                    {**chunk.metadata, "char_start": start, "char_end": end,
                     "token_limit_split": start != chunk.metadata["char_start"] or end != chunk.metadata["char_end"],
                     "token_count": embedder.token_count(text)}
                ))
                continue
            if end - start <= 1:
                raise ValueError("Cannot fit one character into the embedding model")
            middle = len(text) // 2
            boundary = text.rfind(" ", 0, middle + 1)
            if boundary <= 0:
                boundary = middle
            split = start + boundary
            pending[0:0] = [(start, split), (split, end)]
    return output

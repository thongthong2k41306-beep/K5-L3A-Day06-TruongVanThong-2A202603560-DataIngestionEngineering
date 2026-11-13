"""PDF ingestion with physical page IDs, source metadata and bounded warning logs."""
from collections import Counter
from dataclasses import asdict
from hashlib import sha256
import logging
from pathlib import Path
import re
import unicodedata
from pypdf import PdfReader
from .models import DocumentPage
from .paths import ROOT, read_json, write_json, write_jsonl

class PdfWarnings(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.counts = Counter()
        self.samples = []
    def emit(self, record):
        message = record.getMessage()
        category = ("xref_repair" if "wrong pointing object" in message else
                    "font_encoding" if "fontTools" in message or "encoding" in message else
                    "other")
        self.counts[category] += 1
        if len(self.samples) < 8:
            self.samples.append(message[:350])

def normalize_text(text: str) -> str:
    """NFKC normalizes ligatures; preserve line/paragraph boundaries for chunking."""
    text = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\x00", "").replace("\u00ad", "")
    # Join words split by a printed end-of-line hyphen; retain ordinary hyphens.
    text = re.sub(r"([A-Za-z])-\n([a-z])", r"\1\2", text)
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()

def load_pdf(path: Path, document_id: str, source: str) -> list[DocumentPage]:
    handler = PdfWarnings()
    logger = logging.getLogger("pypdf")
    previous_handlers, previous_level, previous_propagation = logger.handlers[:], logger.level, logger.propagate
    logger.handlers, logger.propagate = [handler], False
    logger.setLevel(logging.WARNING)
    pages, failures = [], []
    try:
        reader = PdfReader(path, strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError(f"Encrypted PDF requires a password: {path.name}")
        for number, pdf_page in enumerate(reader.pages, 1):
            try:
                raw = pdf_page.extract_text(extraction_mode="plain") or ""
                text = normalize_text(raw)
                header = re.search(r"Digital\s+Control\s+Module\s+(\d+)\s+Lecture\s+(\d+)", text[:500], re.I)
                if not header:
                    raise ValueError("Cannot verify module/lecture metadata from the page header")
                module, lecture = map(int, header.groups())
                metadata = {
                    "module": module, "lecture": lecture, "language": "en",
                    "document_physical_pages": len(reader.pages),
                    "metadata_origin": "Printed Digital Control Module N Lecture M header",
                    "normalized_characters": len(text),
                    "text_sha256": sha256(text.encode("utf-8")).hexdigest()
                }
                if not text:
                    failures.append({"page": number, "error": "empty_text"})
                pages.append(DocumentPage(document_id, source, number, text, metadata))
            except Exception as exc:
                failures.append({"page": number, "error": str(exc)})
        write_json(ROOT / "results/logs/pdf_extraction.json", {
            "document_id": document_id, "source": source, "physical_pages": len(reader.pages),
            "parsed_pages": len(pages), "failures": failures,
            "warning_counts": dict(handler.counts), "warning_samples": handler.samples,
            "notes": "Malformed xref offsets are repaired by pypdf strict=False. Text extraction cannot certify mathematical formula fidelity."
        })
    finally:
        logger.handlers, logger.level, logger.propagate = previous_handlers, previous_level, previous_propagation
    if not pages:
        raise ValueError(f"No readable pages in {path.name}")
    return pages

def prepare_corpus():
    manifest_path = ROOT / "data/manifest.json"
    manifest = read_json(manifest_path)
    all_pages, selected_pages = [], []
    for entry in manifest["documents"]:
        relative_source = entry["source_path_or_url"]
        path = (ROOT / relative_source).resolve()
        if not path.is_relative_to(ROOT):
            raise ValueError("Corpus path must stay inside the repository")
        if not path.is_file():
            raise FileNotFoundError(relative_source)
        pages = load_pdf(path, entry["source_id"], relative_source)
        all_pages.extend(pages)
        selected = set(entry.get("selected_page_ids", []))
        chosen = [page for page in pages if page.page in selected]
        if selected - {page.page for page in pages}:
            raise ValueError("Manifest selects unreadable or missing pages")
        if any(len(page.text) < 250 for page in chosen):
            raise ValueError("Selected content page has too little extractable text; inspect the source")
        entry["physical_page_count"] = pages[0].metadata["document_physical_pages"]
        entry["sha256"] = sha256(path.read_bytes()).hexdigest()
        entry["normalization"] = "Unicode NFKC; whitespace cleaned; line breaks retained; soft hyphens removed"
        entry["pages"] = [{
            "page": page.page, "normalized_characters": len(page.text),
            "text_sha256": page.metadata["text_sha256"],
            "module": page.metadata["module"], "lecture": page.metadata["lecture"],
            "selected": page.page in selected
        } for page in pages]
        entry["selected_content_page_count"] = len(chosen)
        entry["status"] = ("ready" if entry.get("license_or_permission") and entry.get("original_source_url")
                           else "provenance_pending")
        selected_pages.extend(chosen)
    if len(selected_pages) < 30:
        raise ValueError("Select at least 30 verified content pages in data/manifest.json")
    write_json(manifest_path, manifest)
    write_jsonl(ROOT / "data/processed/all_pages.jsonl", [asdict(p) for p in all_pages])
    write_jsonl(ROOT / "data/processed/pages.jsonl", [asdict(p) for p in selected_pages])
    write_json(ROOT / "results/metrics/corpus.json", {
        "physical_pages": len(all_pages), "selected_content_pages": len(selected_pages),
        "selected_characters": sum(len(p.text) for p in selected_pages),
        "modules": sorted({p.metadata["module"] for p in selected_pages}),
        "provenance_complete": all(d["status"] == "ready" for d in manifest["documents"])
    })
    return selected_pages

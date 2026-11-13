"""Step 4: read the PDF, validate selected pages and update the corpus manifest."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from src.ingestion import prepare_corpus
from src.paths import ROOT, read_json, write_json

def main():
    try:
        pages = prepare_corpus()
        stats = read_json(ROOT / "results/metrics/corpus.json")
        print(f"PDF physical pages: {stats['physical_pages']}")
        print(f"Selected content pages: {len(pages)} (minimum required: 30)")
        print(f"Selected normalized characters: {stats['selected_characters']}")
        print(f"Modules: {', '.join(map(str, stats['modules']))}")
        print("Manifest: data/manifest.json")
        print("Normalized corpus: data/processed/pages.jsonl")
        print("Extraction log: results/logs/pdf_extraction.json")
        if not stats["provenance_complete"]:
            print("Source citation / permission: pending user information (not invented).")
        print("DATA PREPARATION OK")
    except Exception as exc:
        write_json(ROOT / "results/logs/prepare_error.json", {
            "exception_type": type(exc).__name__, "message": str(exc)
        })
        print(f"DATA PREPARATION FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

if __name__ == "__main__":
    main()

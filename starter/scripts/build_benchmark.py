"""Reconstruct private gold evidence from public offsets and the authorized local PDF corpus."""
from argparse import ArgumentParser
from hashlib import sha256
from pathlib import Path
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout,"reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from src.paths import ROOT,read_json,read_jsonl
from src.models import DocumentPage
from src.evaluation import validate_benchmark

def reconstruct():
    spec=read_json(ROOT/"benchmark/question_specs.public.json")
    manifest=read_json(ROOT/"data/manifest.json")["documents"][0]
    local=ROOT/manifest["source_path_or_url"]
    if sha256(local.read_bytes()).hexdigest()!=spec["pdf_sha256"]:
        raise ValueError("Use the PDF matching the manifest hash")
    pages=read_jsonl(ROOT/"data/processed/pages.jsonl")
    lookup={(p["document_id"],p["page"]):" ".join(p["text"].split()) for p in pages}
    def evidence(source,page,span):
        text=lookup[(source,page)]
        start,end=span["start"],span["end"]
        if not 0<=start<end<=len(text):
            raise ValueError("Gold evidence offsets are outside the source page")
        return text[start:end]
    questions=[]
    for row in spec["questions"]:
        q={k:row[k] for k in ("id","split","type","question","expected_answer","gold_source_id","gold_page")}
        q["evidence_quote"]=evidence(q["gold_source_id"],q["gold_page"],row["evidence_span"])
        q["filter"]=row["filter"]
        q["gold_review_method"]=row["gold_review_method"]
        if row.get("alternative_gold"):
            q["alternative_gold"]=[{
                "source_id":g["source_id"],"page":g["page"],
                "evidence_quote":evidence(g["source_id"],g["page"],g["evidence_span"])
            } for g in row["alternative_gold"]]
        questions.append(q)
    validate_benchmark(questions,[DocumentPage(**p) for p in pages])
    text=json.dumps(questions,ensure_ascii=False,indent=2)+"\n"
    if spec["questions_newline"]=="crlf":
        text=text.replace("\n","\r\n")
    raw=text.encode("utf-8")
    if spec.get("questions_utf8_bom"):
        raw=b"\xef\xbb\xbf"+raw
    protocol=read_json(ROOT/"benchmark/protocol.json")
    if sha256(raw).hexdigest()!=protocol["questions_sha256"]:
        raise ValueError("Reconstructed benchmark does not match the frozen hash")
    return questions,raw

def main():
    parser=ArgumentParser(description=__doc__)
    parser.add_argument("--check-only",action="store_true")
    args=parser.parse_args()
    questions,raw=reconstruct()
    target=ROOT/"benchmark/questions.json"
    if target.exists() and target.read_bytes()!=raw:
        raise ValueError("Existing benchmark differs; preserve it for review instead of overwriting")
    if args.check_only:
        print("BENCHMARK RECONSTRUCTION OK: 20 questions; byte-identical frozen hash; no files written.")
        return
    if not target.exists():
        target.write_bytes(raw)
    print("BENCHMARK READY: 20 questions, 15 dev / 5 test; frozen protocol preserved.")
    print("Gold evidence reconstructed locally; no retrieval executed.")

if __name__=="__main__":
    main()

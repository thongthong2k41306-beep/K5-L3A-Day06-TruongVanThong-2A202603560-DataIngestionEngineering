"""Import review labels only for exactly matching source contexts, keeping AI attribution."""
from pathlib import Path
from argparse import ArgumentParser
import csv,re,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout,"reconfigure"):sys.stdout.reconfigure(encoding="utf-8")
from src.auditing import build_packets,PACKETS
from src.paths import ROOT,read_json,write_json

def main():
    parser=ArgumentParser(description=__doc__)
    parser.add_argument("--check-only",action="store_true")
    args=parser.parse_args()
    directory=ROOT/"results/manual_labels"
    index=read_json(directory/"audit_index.json")
    _,records,sources,_=build_packets()
    if sources!=index["sources"]:raise ValueError("Review packet input changed")
    with (ROOT/"results/review_labels.csv").open(encoding="utf-8-sig",newline="") as stream:
        rows={r["id"]:r for r in csv.DictReader(stream)}
    expected={r["id"]:r for r in records}
    if set(rows)!=set(expected):raise ValueError("Review IDs differ")
    for record_id,row in rows.items():
        if row["reference_sha256"]!=expected[record_id]["reference_sha256"]:
            raise ValueError(f"Context differs; assess the new content: {record_id}")
        if not 0<=int(row["score"])<=expected[record_id]["max_score"]:
            raise ValueError("Invalid score")
    updates={}
    for filename in PACKETS.values():
        path=directory/filename
        def restore(m):
            record_id,body=m[1],m[2]
            block=re.search(r"<!-- LABELS -->(.*?)<!-- END LABELS -->",body,re.S)
            if not block:raise ValueError("Missing label block")
            existing={}
            for key in ("SCORE","REASON","REVIEWER"):
                field=re.search(r"^"+key+r":[ \t]*([^\r\n]*)$",block[1],re.M)
                if not field:raise ValueError("Missing field")
                existing[key]=field[1].strip()
            row=rows[record_id]
            wanted={"SCORE":row["score"],"REASON":row["reason"],"REVIEWER":row["reviewer"]}
            if any(existing.values()):
                if existing!=wanted:raise ValueError("Preserve existing edits; import would overwrite them")
                return m[0]
            labels="<!-- LABELS -->\n"+"\n".join(k+": "+wanted[k] for k in wanted)+"\n<!-- END LABELS -->"
            return "<!-- REVIEW:"+record_id+" -->"+body[:block.start()]+labels+body[block.end():]+"<!-- END REVIEW -->"
        updates[path]=re.sub(r"<!-- REVIEW:([^>]+) -->(.*?)<!-- END REVIEW -->",restore,path.read_text(encoding="utf-8"),flags=re.S)
    if args.check_only:
        print("REVIEW IMPORT CHECK OK: matching references; no files changed.")
        return
    for path,text in updates.items():path.write_text(text,encoding="utf-8")
    provenance=directory/"review_provenance.json"
    if not provenance.exists():
        write_json(provenance,{"student_id":"2A202603560",
            "method":"Imported original labels after exact context-hash matching; not a new human evaluation.",
            "records":[{"id":r["id"],"origin":"ai_assisted_assessment" if r["reviewer"].lower().startswith("codex") else "preserved_student_entered_label",
                        "score":int(r["score"]),"reviewer":r["reviewer"],"reason":r["reason"]} for r in rows.values()]})
    print("REVIEW LABELS RESTORED (original reviewer attribution preserved)")
if __name__=="__main__":main()

"""Collect completed review forms, preserving AI versus student attribution."""
from collections import Counter
import csv
from datetime import datetime
from hashlib import sha256
import re
from zoneinfo import ZoneInfo
from .auditing import PACKETS, build_packets
from .paths import ROOT, read_json, write_json

def parse_fields(label_text, max_score):
    fields = {}
    for name in ("SCORE", "REASON", "REVIEWER"):
        matches = re.findall(r"^" + name + r":[ \t]*([^\r\n]*)$", label_text, re.M)
        if len(matches) != 1 or not matches[0].strip():
            raise ValueError(f"Missing, empty or duplicate review field: {name}")
        fields[name] = matches[0].strip()
    if not re.fullmatch(r"[0-2]", fields["SCORE"]) or int(fields["SCORE"]) > max_score:
        raise ValueError(f"Review score must be between 0 and {max_score}")
    return int(fields["SCORE"]), fields["REASON"], fields["REVIEWER"]

def collect_reviews(check_only=False):
    directory = ROOT / "results/manual_labels"
    index = read_json(directory / "audit_index.json")
    _, fresh_records, sources, counts = build_packets()
    if index["sources"] != sources:
        raise ValueError("Review packets belong to different experiment inputs")
    expected = {row["id"]: row for row in fresh_records}
    provenance_path = directory / "review_provenance.json"
    provenance = read_json(provenance_path) if provenance_path.exists() else {"records":[]}
    origins = {row["id"]: row for row in provenance["records"]}
    rows, seen = [], set()
    for kind, filename in PACKETS.items():
        text = (directory / filename).read_text(encoding="utf-8")
        for match in re.finditer(r"<!-- REVIEW:([^>]+) -->(.*?)<!-- END REVIEW -->", text, re.S):
            record_id, section = match[1], match[2]
            if record_id not in expected or record_id in seen:
                raise ValueError(f"Unknown or duplicate review ID: {record_id}")
            record = expected[record_id]
            if record["kind"] != kind:
                raise ValueError(f"Review record in the wrong packet: {record_id}")
            labels = re.search(r"<!-- LABELS -->(.*?)<!-- END LABELS -->", section, re.S)
            if not labels:
                raise ValueError(f"Missing labels block: {record_id}")
            reference = section[:labels.start()].strip()
            lines = reference.splitlines()
            if lines[0] != f"### {record_id}":
                raise ValueError(f"Changed record heading: {record_id}")
            reference = "\n".join(lines[1:]).strip()
            if sha256(reference.encode("utf-8")).hexdigest() != record["reference_sha256"]:
                raise ValueError(f"Source context was edited in the review packet: {record_id}")
            score, reason, reviewer = parse_fields(labels[1], record["max_score"])
            ai_pending = reviewer.lower().startswith("codex")
            origin = origins.get(record_id, {}).get("origin", "student_entered")
            method = ("ai_assisted_pending_student_confirmation" if ai_pending
                      else "student_entered_ai_assisted" if origin in ("ai_assisted_assessment","preserved_student_entered_label")
                      else "student_entered")
            rows.append({
                **record, "score":score, "reason":reason, "reviewer":reviewer,
                "student_id":"2A202603560", "assessment_method":method,
                "student_confirmation":not ai_pending
            })
            seen.add(record_id)
    if seen != set(expected):
        raise ValueError(f"Missing review entries: {sorted(set(expected)-seen)}")
    print(f"Completed review fields: {len(rows)}/{len(expected)}")
    pending = sum(not row["student_confirmation"] for row in rows)
    confirmed = len(rows) - pending
    print(f"Student-entered/confirmed reviewer fields: {confirmed}")
    print(f"AI assessments pending student confirmation: {pending}")
    if check_only:
        print("REVIEW VALIDATION OK (no summaries written)")
        return
    summaries = []
    for strategy in ("A","B","C"):
        group = [row for row in rows if row["strategy"] == strategy]
        def subset(kind):
            return [row for row in group if row["kind"] == kind]
        coherence, grounding, metadata, filters = [subset(k) for k in ("coherence","grounding","metadata","filter")]
        summaries.append({
            "strategy":strategy,
            "coherence_count":len(coherence),
            "coherence_mean":sum(row["score"] for row in coherence)/len(coherence),
            "coherence_distribution":dict(Counter(str(row["score"]) for row in coherence)),
            "grounding_count":len(grounding),
            "grounding_mean":sum(row["score"] for row in grounding)/len(grounding),
            "grounding_distribution":{str(score):sum(row["score"]==score for row in grounding) for score in (0,1,2)},
            "metadata_correct_n":sum(row["score"] for row in metadata),
            "metadata_checked_n":len(metadata),
            "filter_compliant_n":sum(row["score"] for row in filters),
            "filter_questions_n":len(filters),
            "student_confirmed_n":sum(row["student_confirmation"] for row in group),
            "ai_pending_confirmation_n":sum(not row["student_confirmation"] for row in group)
        })
    for kind in PACKETS:
        group = [row for row in rows if row["kind"] == kind]
        fields = ["id","strategy","question_id","page","rank","chunk_id","score",
                  "reason","reviewer","student_id","assessment_method","student_confirmation"]
        with (directory/f"{kind}.csv").open("w",encoding="utf-8-sig",newline="") as stream:
            writer = csv.DictWriter(stream,fieldnames=fields,extrasaction="ignore")
            writer.writeheader()
            writer.writerows(group)
    write_json(ROOT/"results/metrics/review_summary.json",{
        "generated_at":datetime.now(ZoneInfo("Asia/Bangkok")).isoformat(timespec="seconds"),
        "status":"ai_assisted_review_complete_confirmation_pending" if pending else "student_review_fields_complete",
        "student_id":"2A202603560", "review_records":len(rows),
        "student_confirmed_records":confirmed, "ai_pending_confirmation_records":pending,
        "sources":sources,"strategies":summaries,
        "methodology_file":"results/manual_labels/review_provenance.json",
        "limitations":[
            "Most labels are explicitly attributed to Codex AI, not to an independent human reviewer.",
            "Same assistant helped author questions and review evidence; no blind evaluation.",
            "Metadata verification uses direct PDF text/header/offset checks, not visual formula inspection.",
            "Markdown SCORE/REASON/REVIEWER are authoritative; human confirmation is a declared reviewer field, not authenticated identity."
        ]
    })
    for row in summaries:
        print(f"{row['strategy']}: coherence {row['coherence_mean']:.2f}/2 | grounding {row['grounding_mean']:.2f}/2 | metadata {row['metadata_correct_n']}/{row['metadata_checked_n']} | filter {row['filter_compliant_n']}/{row['filter_questions_n']}")
    print("Summary: results/metrics/review_summary.json")
    print("REVIEW SUMMARY OK")

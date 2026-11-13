"""Strict evidence retrieval metrics; no fabricated human labels."""
from collections import defaultdict
from hashlib import sha256
import re
from .paths import ROOT, read_json, write_json

def canonical(text):
    return " ".join(text.split())

def gold_options(question):
    return [{"source_id": question["gold_source_id"], "page": question["gold_page"],
             "evidence_quote": question["evidence_quote"]}] + question.get("alternative_gold", [])

def evidence_hit(question, hit):
    return any(
        hit["document_id"] == gold["source_id"] and hit["page"] == gold["page"]
        and canonical(gold["evidence_quote"]) in canonical(hit["text"])
        for gold in gold_options(question)
    )

def evaluate_query(question, hits):
    hit_labels = [evidence_hit(question, hit) for hit in hits]
    return {
        "question_id": question["id"], "split": question["split"],
        "question": question["question"], "expected_answer": question["expected_answer"],
        "gold": gold_options(question), "requested_filter": question.get("filter") or {},
        "hit1": bool(hit_labels and hit_labels[0]), "evidence_hit3": any(hit_labels[:3]),
        "evidence_match_method": "source/page + whitespace-normalized complete evidence quote",
        "hits": [{**hit, "rank": rank, "strict_evidence_hit": label}
                 for rank, (hit, label) in enumerate(zip(hits, hit_labels, strict=True), 1)]
    }

def summarize(traces):
    groups = defaultdict(list)
    for trace in traces:
        groups[(trace["strategy"], trace["split"])].append(trace)
    result = []
    for (strategy, split), group in sorted(groups.items()):
        total, hit1, hit3 = len(group), sum(t["hit1"] for t in group), sum(t["evidence_hit3"] for t in group)
        filtered = [t for t in group if t["requested_filter"]]
        compliant = sum(bool(t["hits"]) and all(
            all(h["metadata"].get(k) == v for k, v in t["requested_filter"].items())
            for h in t["hits"]) for t in filtered)
        result.append({
            "strategy": strategy, "split": split, "questions": total,
            "hit1_n": hit1, "hit1": hit1/total, "evidence_hit3_n": hit3, "evidence_hit3": hit3/total,
            "filter_questions": len(filtered), "filter_compliant_n": compliant,
            "filter_compliance": compliant/len(filtered) if filtered else None,
            "mean_latency_ms": sum(t["latency_ms"] for t in group)/total
        })
    return result

def validate_benchmark(questions, pages):
    if len(questions) < 20:
        raise ValueError("Benchmark needs >=20 questions")
    if len({q["id"] for q in questions}) != len(questions):
        raise ValueError("Duplicate question IDs")
    counts = {split: sum(q["split"] == split for q in questions) for split in ("dev", "test")}
    if counts["dev"] < 15 or counts["test"] < 5:
        raise ValueError("Need at least 15 dev and 5 test questions")
    if any(q["split"] not in counts for q in questions):
        raise ValueError("Invalid split")
    if sum(bool(q.get("filter")) for q in questions) < 3 or not any(q.get("filter") for q in questions if q["split"] == "test"):
        raise ValueError("Need >=3 filter questions, including >=1 test")
    lookup = {(p.document_id, p.page): p for p in pages}
    for question in questions:
        for name in ("id","question","expected_answer","gold_source_id","gold_page","evidence_quote"):
            if not question.get(name):
                raise ValueError(f"Missing benchmark field: {name}")
        for field in ("question", "expected_answer"):
            value = question[field]
            if "\ufffd" in value or re.search(r"\w\?\w", value):
                raise ValueError(f"Possible text encoding corruption in {field}: {question['id']}")
        for gold in gold_options(question):
            page = lookup.get((gold["source_id"], gold["page"]))
            if page is None or canonical(gold["evidence_quote"]) not in canonical(page.text):
                raise ValueError(f"Gold evidence not found on its page: {question['id']}")
        page = lookup[(question["gold_source_id"], question["gold_page"])]
        for key, value in (question.get("filter") or {}).items():
            if key not in {"module", "lecture", "language"} or page.metadata.get(key) != value:
                raise ValueError(f"Filter is unsupported or excludes gold: {question['id']}")
    return counts

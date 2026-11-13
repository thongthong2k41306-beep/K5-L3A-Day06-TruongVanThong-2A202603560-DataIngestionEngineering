"""Prepare manual-review packets; never assign scores from automatic hit metrics."""
from collections import Counter
from datetime import datetime
from hashlib import sha256
import json
from zoneinfo import ZoneInfo
from .benchmarking import fingerprints
from .embedding_artifacts import digest, load_embedding_artifacts
from .holdout import validate_frozen_selection
from .paths import ROOT, read_json, read_jsonl, write_json

LABELS = "<!-- LABELS -->\nSCORE:\nREASON:\nREVIEWER:\n<!-- END LABELS -->"
PACKETS = {"grounding":"01_grounding.md", "coherence":"02_coherence.md",
           "metadata":"03_metadata.md", "filter":"04_filter.md"}
HEADERS = {
 "grounding": """# Phiếu 1 — Grounding: độ đủ của bằng chứng

Đọc câu hỏi và cả top-3. Chấm 0 = không có bằng chứng; 1 = có nhưng thiếu điều kiện/ngữ cảnh; 2 = đủ trả lời và truy được nguồn. Có thể đủ nhờ kết hợp top-3 hoặc nguồn tương đương hợp lệ, dù metric exact-quote không hit. Đây là chấm evidence, không chấm câu trả lời LLM.

Mỗi mục điền SCORE (0/1/2), REASON (lý do) và REVIEWER (tên hoặc MSSV người thực sự chấm). Các ô đang trống. Đối chiếu PDF khi cần.
""",
 "coherence": """# Phiếu 2 — Coherence: độ mạch lạc của chunk

Cùng 10 vị trí nguồn đã cố định trước retrieval cho A/B/C. Nếu nhiều chunk phủ vị trí, chọn chunk có trung điểm gần vị trí nhất, hòa thì theo chunk ID; công bố tất cả ID phủ vị trí.

Chấm 0 = bị cắt giữa ý/thiếu chủ thể làm không hiểu; 1 = hiểu một phần nhưng thiếu ngữ cảnh; 2 = tự hiểu được và giữ trọn ý. Chấm chunk thực tế, không lấy ngữ cảnh bổ sung làm nội dung của chunk. B/C dùng cùng chunks nên mục tương ứng giống nhau.

Điền SCORE 0/1/2, REASON và REVIEWER. Mẫu chỉ từ 10 trang đầu; ghi hạn chế này trong báo cáo.
""",
 "metadata": """# Phiếu 3 — Metadata: đủ và đúng

Mỗi mục là một kết quả top-3 của 5 câu test. Đối chiếu source, số trang PDF và Module/Lecture với PDF gốc. Metadata phải đúng với chunk đang xem; không chấm sai chỉ vì trang đó khác trang gold của câu hỏi.

SCORE 1 nếu các trường cần thiết vừa đủ vừa đúng; SCORE 0 nếu thiếu hoặc sai, ghi từng lỗi trong REASON. Đoạn đầu trang chuẩn hóa chỉ hỗ trợ đối chiếu PDF. REVIEWER là người thực sự chấm.
""",
 "filter": """# Phiếu 4 — Tuân thủ filter

Chỉ xét câu test có yêu cầu Module/Lecture được cung cấp trước truy xuất. Kiểm tra toàn bộ top-3 của từng cấu hình so với phạm vi yêu cầu.

SCORE 1 nếu có kết quả và tất cả kết quả top-3 đều tuân thủ filter; SCORE 0 nếu có kết quả ngoài phạm vi hoặc không có kết quả. Ghi REASON và REVIEWER. Đây là kiểm tra phạm vi lọc, không chứng minh evidence đủ để trả lời. Tập này có 2 câu filter.
"""
}

def code(text):
    fence = chr(96) * 4
    return fence + "text\n" + str(text).strip() + "\n" + fence + "\n"

def review_block(record_id, reference):
    return (f"\n<!-- REVIEW:{record_id} -->\n### {record_id}\n\n"
            + reference.strip() + "\n\n" + LABELS + "\n<!-- END REVIEW -->\n")

def audit_context():
    selection = read_json(ROOT / "configs/selected_strategy.json")
    hashes = {
        "dev_metrics_sha256":digest(ROOT / "results/metrics/dev.json"),
        "dev_traces_sha256":digest(ROOT / "results/traces/dev.jsonl"),
        "coherence_positions_sha256":digest(ROOT / "benchmark/coherence_positions.json")
    }
    validate_frozen_selection(selection, fingerprints(), hashes)
    test = read_json(ROOT / "results/metrics/test.json")
    if test["frozen_selection_sha256"] != digest(ROOT / "configs/selected_strategy.json"):
        raise ValueError("Test does not match the frozen dev selection")
    if test["traces_sha256"] != digest(ROOT / "results/traces/test.jsonl"):
        raise ValueError("Test trace changed after scoring")
    if test["input_fingerprints"] != selection["input_fingerprints"]:
        raise ValueError("Test input fingerprint differs")
    if test["selection_changed_using_test"] is not False:
        raise ValueError("Selection changed using test")
    if test["holdout_evaluator_sha256"] != digest(ROOT / "starter/src/holdout.py"):
        raise ValueError("Holdout evaluator changed after test")
    questions = {q["id"]:q for q in read_json(ROOT / "benchmark/questions.json") if q["split"] == "test"}
    traces = read_jsonl(ROOT / "results/traces/test.jsonl")
    expected = {(name,qid) for name in ("A","B","C") for qid in questions}
    if len(traces) != len(expected) or {(t["strategy"],t["question_id"]) for t in traces} != expected:
        raise ValueError("Incomplete or duplicate test traces")
    if any(t["split"] != "test" for t in traces):
        raise ValueError("A review trace belongs to a different split")
    _, banks = load_embedding_artifacts()
    pages = {(p["document_id"],p["page"]):p for p in read_jsonl(ROOT / "data/processed/pages.jsonl")}
    positions = read_json(ROOT / "benchmark/coherence_positions.json")
    return selection, questions, traces, banks, pages, positions

def build_packets():
    selection, questions, traces, banks, pages, positions = audit_context()
    packets, records = dict(HEADERS), []
    def add(kind, record_id, reference, **info):
        packets[kind] += review_block(record_id, reference)
        records.append({
            "id":record_id, "kind":kind, "packet":PACKETS[kind],
            "max_score":2 if kind in ("grounding","coherence") else 1,
            "reference_sha256":sha256(reference.strip().encode("utf-8")).hexdigest(),
            "score":None, "reason":None, "reviewer":None, **info
        })
    for trace in sorted(traces, key=lambda t:(t["question_id"],t["strategy"])):
        name, qid = trace["strategy"], trace["question_id"]
        q = questions[qid]
        reference = (f"**Cấu hình:** {name} — **Câu:** {qid}\n\n"
                     f"**Câu hỏi:** {q['question']}\n\n"
                     f"**Đáp án tham chiếu:** {q['expected_answer']}\n\n"
                     f"**Gold trang PDF:** {q['gold_page']}\n\n**Evidence tham chiếu:**\n"
                     + code(q["evidence_quote"]) + "\n**Top-3 thực tế:**\n")
        for hit in trace["hits"]:
            reference += (
                f"\n**Hạng {hit['rank']} — trang PDF {hit['page']} — chunk {hit['chunk_id']}**\n"
                f"Nguồn: {hit['source']}; Module {hit['metadata'].get('module')}, Lecture {hit['metadata'].get('lecture')}.\n"
                + code(hit["text"])
            )
        if not trace["hits"]:
            reference += "\nKhông có kết quả truy xuất.\n"
        add("grounding",f"grounding-{name}-{qid}",reference,strategy=name,question_id=qid)
        for hit in trace["hits"]:
            page = pages.get((hit["document_id"],hit["page"]))
            header = page["text"][:260] if page else "Không tìm thấy trang trong corpus; cần đối chiếu PDF và ghi lỗi."
            fields = {k:hit[k] for k in ("document_id","source","page")}
            fields.update({k:hit["metadata"].get(k) for k in ("module","lecture","language")})
            reference = (
                f"**Cấu hình:** {name}; câu {qid}; hạng {hit['rank']}; chunk {hit['chunk_id']}.\n\n"
                "**Metadata trả về:**\n" + code(json.dumps(fields,ensure_ascii=False,indent=2))
                + "\n**Nội dung chunk:**\n" + code(hit["text"])
                + "\n**Đầu trang nguồn chuẩn hóa để hỗ trợ đối chiếu PDF:**\n" + code(header)
            )
            add("metadata",f"metadata-{name}-{qid}-r{hit['rank']}",reference,
                strategy=name,question_id=qid,rank=hit["rank"],chunk_id=hit["chunk_id"])
        if trace["requested_filter"]:
            reference = (
                f"**Cấu hình:** {name}; câu {qid}.\n\n**Câu hỏi:** {q['question']}\n\n"
                "**Phạm vi yêu cầu trước truy xuất:** " + json.dumps(trace["requested_filter"],ensure_ascii=False)
                + "\n\n**Filter thực sự áp dụng:** " + json.dumps(trace["applied_filter"],ensure_ascii=False)
                + "\n\n| Hạng | Trang PDF | Module | Lecture | Nguồn |\n|---|---|---|---|---|\n"
            )
            for hit in trace["hits"]:
                reference += f"| {hit['rank']} | {hit['page']} | {hit['metadata'].get('module')} | {hit['metadata'].get('lecture')} | {hit['source']} |\n"
            add("filter",f"filter-{name}-{qid}",reference,strategy=name,question_id=qid)
    for number,position in enumerate(positions,1):
        page = pages[(position["document_id"],position["page"])]
        anchor = position["char_offset"]
        for name in ("A","B","C"):
            candidates = [c for c in banks[name][0]
                          if c.document_id == position["document_id"] and c.page == position["page"]
                          and c.metadata["char_start"] <= anchor < c.metadata["char_end"]]
            if not candidates:
                raise ValueError(f"No chunk covers coherence position {number} in {name}")
            chunk = min(candidates,key=lambda c:(
                abs((c.metadata["char_start"]+c.metadata["char_end"])/2-anchor),c.chunk_id))
            reference = (
                f"**Cấu hình:** {name}; vị trí {number}; trang PDF {position['page']}; offset {anchor}.\n\n"
                f"**Nguồn:** {position['source']}\n\n"
                f"**Chunk được chấm:** {chunk.chunk_id}; khoảng ký tự [{chunk.metadata['char_start']}, {chunk.metadata['char_end']}).\n\n"
                "**Các chunk phủ vị trí:** " + ", ".join(c.chunk_id for c in candidates)
                + "\n\n**Nội dung chunk cần chấm:**\n" + code(chunk.text)
                + "\n**Ngữ cảnh nguồn để đối chiếu; không phải nội dung bổ sung vào chunk:**\n"
                + code(page["text"][max(0,anchor-220):anchor+220])
            )
            add("coherence",f"coherence-{name}-p{position['page']}-a{number:02d}",reference,
                strategy=name,page=position["page"],anchor_offset=anchor,chunk_id=chunk.chunk_id)
    if len({r["id"] for r in records}) != len(records):
        raise ValueError("Duplicate audit IDs")
    counts = dict(Counter(r["kind"] for r in records))
    if counts["grounding"] != len(questions)*3 or counts["coherence"] != 30:
        raise ValueError("Incorrect audit sample sizes")
    for kind,content in packets.items():
        if content.count(LABELS) != counts[kind]:
            raise ValueError("Review labels must start blank")
    sources = {
        "frozen_selection":digest(ROOT / "configs/selected_strategy.json"),
        "dev_metrics":digest(ROOT / "results/metrics/dev.json"),
        "test_metrics":digest(ROOT / "results/metrics/test.json"),
        "test_traces":digest(ROOT / "results/traces/test.jsonl"),
        "positions":digest(ROOT / "benchmark/coherence_positions.json"),
        "input_fingerprints":selection["input_fingerprints"]
    }
    return packets, records, sources, counts

def prepare_audits(check_only=False):
    packets, records, sources, counts = build_packets()
    print(f"Grounding: {counts['grounding']} reviews (5 test questions x 3 strategies)")
    print(f"Coherence: {counts['coherence']} reviews (same 10 source positions x 3 strategies)")
    print(f"Metadata: {counts['metadata']} retrieved records")
    print(f"Filter: {counts['filter']} query/strategy reviews")
    print("Manual scores: blank; none inferred from retrieval metrics")
    if check_only:
        print("AUDIT INPUT CHECK OK (no files written or labels assigned)")
        return
    directory = ROOT / "results/manual_labels"
    directory.mkdir(parents=True,exist_ok=True)
    index_path = directory / "audit_index.json"
    if index_path.exists():
        index = read_json(index_path)
        if index["sources"] != sources:
            raise ValueError("Existing packets belong to different inputs; preserve previous labels")
        if any(not (directory/filename).is_file() for filename in PACKETS.values()):
            raise ValueError("Existing packet set is incomplete; preserve labels and inspect missing files")
        print("Existing packets preserved, including manual edits.")
        print("AUDIT PACKETS READY")
        return
    if any((directory/filename).exists() for filename in PACKETS.values()):
        raise ValueError("Review files exist without an index; preserve and inspect them")
    for kind,content in packets.items():
        (directory/PACKETS[kind]).write_text(content,encoding="utf-8")
    write_json(index_path,{
        "prepared_at":datetime.now(ZoneInfo("Asia/Bangkok")).isoformat(timespec="seconds"),
        "status":"awaiting_manual_review", "sources":sources, "counts":counts,
        "scores_prefilled":False, "records":records,
        "label_authority":"SCORE/REASON/REVIEWER in Markdown packets; index nulls are preparation placeholders."
    })
    (directory/"README.md").write_text(
        "# Chấm thủ công\n\n"
        "Mở 01_grounding.md trước. Mỗi mục đọc nội dung, điền SCORE, REASON và REVIEWER rồi Ctrl+S. "
        "SCORE là điểm theo hướng dẫn đầu phiếu; REASON là lý do thực tế; REVIEWER là tên/MSSV người thực sự chấm. "
        "Các ô đang trống, chưa có nhãn hoàn thành.\n\n"
        "Sau grounding làm coherence, metadata và filter. Không đổi benchmark/cấu hình sau khi xem test. "
        "Ctrl+Shift+V mở Markdown Preview để đọc; sửa nhãn ở chế độ văn bản. "
        "Giữ nguyên marker HTML và nội dung nguồn, chỉ điền ô nhãn. "
        "Nếu có AI hỗ trợ chấm, phải ghi rõ phương pháp, người kiểm tra lại và giới hạn; không ghi thành nhãn tự chấm của học viên.\n",
        encoding="utf-8")
    print("Output: results/manual_labels/")
    print("Start with: 01_grounding.md")
    print("AUDIT PACKETS READY")

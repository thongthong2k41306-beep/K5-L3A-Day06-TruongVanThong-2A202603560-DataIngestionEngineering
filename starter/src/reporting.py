"""Build a reproducible draft report from real artifacts, with explicit missing information."""
from datetime import datetime
from pathlib import Path
import re
import shutil
from zoneinfo import ZoneInfo
from .paths import ROOT, read_json, read_jsonl, write_json
from .embedding_artifacts import digest
from .review_results import collect_reviews

def student_fields():
    text = (ROOT/"STUDENT.md").read_text(encoding="utf-8")
    def value(label):
        match = re.search(r"^- "+re.escape(label)+r":[ \t]*(.*)$",text,re.M)
        return match[1].strip() if match else "Chưa được cung cấp"
    return {"name":value("Họ và tên"),"id":value("MSSV"),"class":value("Lớp"),
            "repo":value("Repo bài nộp"),"commit":value("Commit chốt bài"),"report_path":value("Báo cáo cá nhân")}

def build_report(check_only=False):
    collect_reviews(check_only=True)
    student = student_fields()
    if not re.fullmatch(r"[A-Za-z0-9_-]+",student["id"]):
        raise ValueError("MSSV cannot be used as a safe report filename")
    doc = read_json(ROOT/"data/manifest.json")["documents"][0]
    corpus = read_json(ROOT/"results/metrics/corpus.json")
    config = read_json(ROOT/"configs/strategies.json")
    embedding = read_json(ROOT/"results/metrics/embeddings.json")
    ingestion = read_json(ROOT/"results/metrics/ingestion.json")
    dev = read_json(ROOT/"results/metrics/dev.json")
    test = read_json(ROOT/"results/metrics/test.json")
    audit = read_json(ROOT/"results/metrics/review_summary.json")
    selection = read_json(ROOT/"configs/selected_strategy.json")
    if audit["student_id"] != student["id"]:
        raise ValueError("Student ID differs from the review owner")
    if audit["sources"]["test_metrics"] != digest(ROOT/"results/metrics/test.json"):
        raise ValueError("Review summary is stale; rerun collect_audits.py")
    dev_traces = read_jsonl(ROOT/"results/traces/dev.jsonl")
    test_traces = read_jsonl(ROOT/"results/traces/test.jsonl")
    model = embedding["model"]
    now = datetime.now(ZoneInfo("Asia/Bangkok"))
    missing = []
    if student["name"].startswith("Chưa"):
        missing.append("Họ và tên học viên")
    if not doc.get("license_or_permission"):
        missing.append("Giấy phép/quyền xử lý và chia sẻ tài liệu")
    if not doc.get("accessed_at"):
        missing.append("Ngày tải/truy cập nguồn gốc nếu có thể xác minh")
    if student["repo"].startswith("Chưa"):
        missing.append("Link repo bài nộp")
    if student["commit"].startswith("Chưa"):
        missing.append("Commit chốt bài")

    def link(label,path):
        private=path.startswith(("starter/data/","data/processed/","results/traces/","results/manual_labels/")) or path in ("benchmark/questions.json","benchmark/coherence_positions.json")
        if private:
            return label+" (local: "+path+"; [cách tái tạo](../../docs/DATA_ACCESS.md))"
        return "["+label+"](<../../"+path+">)"
    def frac(n,total):
        return f"{n}/{total} ({100*n/total:.1f}%)" if total else "N/A"
    source_link = ("[Google Drive do học viên cung cấp]("+doc["original_source_url"]+")"
                   if doc.get("original_source_url") else "Chưa cung cấp")
    selected = selection["selected_strategy"]
    report = [
        "# Báo cáo cá nhân — Day 06: Data Ingestion Engineering\n",
        f"- MSSV: **{student['id']}**",
        f"- Họ và tên: **{student['name']}**",
        f"- Lớp: **{student['class']}**",
        f"- Thời điểm tạo báo cáo: {now.isoformat(timespec='seconds')}",
        "- Trạng thái: **Đã tổng hợp kết quả; quyền tái phân phối nguồn chưa được xác minh; nhãn AI được khai báo rõ tác giả.**\n",
        "## 1. Dữ liệu và pipeline\n",
        f"Chủ đề Digital Control. File local: {link('Digital control system.pdf',doc['source_path_or_url'])}. "
        f"PDF có {doc['physical_page_count']} trang vật lý; corpus chọn **{corpus['selected_content_pages']} trang**, "
        f"{corpus['selected_characters']:,} ký tự sau chuẩn hóa, thuộc Module 1–3.",
        "Chọn trang PDF 1–58, bỏ 20, 28, 31, 53 vì chủ yếu là hình/đồ thị hoặc phần tính toán tiếp nối ngắn. "
        "Đếm theo vị trí trang PDF từ 1; số in ở cuối từng lecture có thể bắt đầu lại. "
        "Việc chọn dựa trên text và cấu trúc bài giảng với AI hỗ trợ, chưa kiểm tra hình ảnh toàn bộ PDF.",
        f"- Nguồn: {source_link}. Link do học viên cung cấp; đã tải trực tiếp và xác minh SHA-256 trùng file local, xem results/logs/source_download_verification.json.",
        f"- Quyền/giấy phép: {doc.get('license_or_permission') or 'Chưa được cung cấp; không suy ra quyền sử dụng/tái phân phối từ link chia sẻ.'}",
        f"- Ngày truy cập/tải gốc: {doc.get('accessed_at') or 'Chưa được cung cấp; ngày kiểm tra file local không thay cho ngày này.'}",
        f"- SHA-256 file: {doc['sha256']}",
        f"- Manifest đầy đủ: {link('data/manifest.json','data/manifest.json')}.\n",
        "Pipeline Python: đọc từng trang bằng pypdf → Unicode NFKC, xử lý khoảng trắng và giữ xuống dòng → "
        "chia chunk theo từng trang → tách thêm khi vượt giới hạn token → embedding local → PostgreSQL + pgvector → top-3 → đánh giá.",
        "pypdf khôi phục 230 offset xref không chuẩn, đọc được 230 trang và không có trang thất bại trong log. "
        "fonttools hỗ trợ đọc encoding; ký hiệu/cấu trúc công thức và hình vẽ vẫn có thể sai sau trích text. "
        "Không có OCR hoặc chứng nhận độ chính xác công thức.\n",
        "### Model, store và metadata\n",
        f"- Embedding: **{model['model_name']}**, provider local Sentence Transformers, CPU.",
        f"- Revision: {model['revision']}; số chiều **{model['dimensions']}**; giới hạn **{model['max_seq_length']} token**.",
        "- Dùng cùng encode(), không prefix, chuẩn L2 cho query và document; không dùng vector giả hoặc TF-IDF thay embedding.",
        f"- Phiên bản: "+", ".join(f"{k}={v}" for k,v in model["versions"].items())+".",
        f"- PostgreSQL {ingestion['backend']['postgres']}; pgvector {ingestion['backend']['pgvector']}; "
        f"metric cosine, **exact search**, bảng {ingestion['backend']['table']}.",
        "- Store dùng named volume trong Docker Compose. Đã kiểm tra nạp hai lần không nhân đôi; chưa thực hiện kiểm tra restart container.",
        "- Mỗi upsert là toàn bộ snapshot của một strategy; cập nhật ID ổn định và xóa ID hết hiệu lực trong cùng strategy, cùng transaction.",
        "- Metadata: document_id/source/page để truy nguồn; module/lecture (integer) trích từ header in trên trang; language=en. "
        "Không suy đoán năm, phiên bản hay ngày hiệu lực.",
        "- Mô hình embedding chạy local nên chi phí dịch vụ embedding/API của thí nghiệm là **0 USD**. "
        "Không đo điện, khấu hao máy hoặc chi phí sử dụng trợ lý AI.\n",
        "## 2. Cấu hình và benchmark\n",
        "| Strategy | Chunk ban đầu | Overlap | Chunk cuối | Filter |\n|---|---|---:|---:|---|"
    ]
    for name in ("A","B","C"):
        cfg=config["strategies"][name]
        report.append(f"| {name} | {cfg['chunking']}, tối đa {cfg['chunk_size']} ký tự | {cfg['overlap']} | "
                      f"{embedding['strategies'][name]['final_chunk_count']} | "
                      f"{'Module/Lecture khi câu hỏi yêu cầu' if cfg['use_filter'] else 'Không'} |")
    report += [
        "\nA có 177 chunk ký tự, B/C có 173. Giới hạn model 128 token làm số chunk cuối tăng lên như bảng. "
        "Cùng quy tắc tách thêm được áp dụng cho mọi strategy, giữ offset nguồn và không cắt token âm thầm. "
        "B ưu tiên ranh giới đoạn/câu/dòng vì PDF không luôn có đoạn rõ ràng; B/C dùng chung chunk và vector.",
        "A–B so sánh gói chiến lược chunking, bao gồm khác biệt overlap. B–C chỉ thay metadata filter; "
        "không thay corpus, model, store, chunk hay query vector.",
        "Bộ 20 câu tiếng Việt, đáp án tiếng Việt và evidence tiếng Anh; 15 dev từ Module 1–2, 5 test từ Module 3. "
        "Đây là truy xuất xuyên ngôn ngữ. Có 6 câu filter, gồm 2 test. "
        "Filter Module/Lecture được nêu trong câu hỏi trước truy xuất; gold answer/source/page không được truyền vào search.",
        f"Đã kiểm tra evidence của 20/20 câu tồn tại đúng trang; câu hỏi ở {link('benchmark/questions.json','benchmark/questions.json')}, "
        f"quy tắc ở {link('benchmark/protocol.json','benchmark/protocol.json')}.",
        "Tiêu chí chọn trước test: Evidence Hit@3 dev cao nhất → Hit@1 cao nhất → số chunk ít nhất → tên strategy theo alphabet. "
        f"Dev chọn **{selected}**. B/C ngang điểm và cùng số chunk nên B thắng tiêu chí cuối; không kết luận B có retrieval tốt hơn C.",
        "Lần dev đầu có lỗi mất dấu tiếng Việt do ghi file qua PowerShell. Đã lưu bản cũ trong results/archive, "
        "khôi phục đúng nội dung dự định và chạy lại dev trước khi test. Không đổi gold, split, filter hay cấu hình để nâng điểm. "
        "Lịch sử ở results/logs/benchmark_utf8_correction.json. Bảng dưới chỉ dùng lần đã sửa.\n",
        "## 3. Kết quả\n",
        "### Độ chính xác truy xuất\n",
        "Hit@1 cần chunk hạng 1 đúng nguồn/trang và chứa đủ evidence. Evidence Hit@3 cần ít nhất một chunk như vậy trong top-3. "
        "Code tự động dùng toàn bộ quote sau chuẩn hóa khoảng trắng; đây là cách đối chiếu bảo thủ, "
        "có thể bỏ sót cách diễn đạt tương đương. Không cộng nhiều chunk để thay định nghĩa chính.",
        "| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk | Query trung bình (ms) |\n|---|---|---|---|---:|---:|"
    ]
    for stage in (dev,test):
        for row in stage["summary"]:
            report.append(f"| {row['strategy']} | {row['split']} | {frac(row['hit1_n'],row['questions'])} | "
                          f"{frac(row['evidence_hit3_n'],row['questions'])} | {stage['chunk_counts'][row['strategy']]} | "
                          f"{row['mean_latency_ms']:.2f} |")
    report += [
        f"\nĐã lưu {len(dev_traces)} lượt truy xuất dev và {len(test_traces)} lượt test, mỗi lượt top-3. "
        "Query latency gồm mở kết nối PostgreSQL và SQL; thời gian encode query dùng chung được đo riêng. "
        "Thứ tự A/B/C xoay vòng giữa các câu.",
        f"- Dev: {link('trace','results/traces/dev.jsonl')}, {link('metrics','results/metrics/dev.json')}.",
        f"- Test: {link('trace','results/traces/test.jsonl')}, {link('metrics','results/metrics/test.json')}.",
        f"- Bảng kết hợp: {link('combined.csv','results/metrics/combined.csv')}.\n",
        "### Coherence, metadata và grounding — nhãn có AI hỗ trợ\n",
        f"Tổng {audit['review_records']} nhãn: giữ {audit['student_confirmed_records']} mục học viên đã điền; "
        f"{audit['ai_pending_confirmation_records']} mục do Codex AI đọc/đối chiếu và điền, **chưa được học viên xác nhận**. "
        "Không mô tả các mục này thành đánh giá thủ công độc lập của học viên. Cùng trợ lý đã giúp soạn câu hỏi nên có nguy cơ thiên lệch.",
        "- Coherence: cùng 10 vị trí nguồn cố định trước retrieval, chọn chunk phủ vị trí có trung điểm gần nhất; thang 0/1/2.",
        "- Grounding: 5 câu test mỗi strategy, đọc toàn bộ top-3; 0 không có bằng chứng, 1 thiếu điều kiện/ngữ cảnh, 2 đủ trả lời và truy nguồn. "
        "Có thể dùng các đoạn kết hợp hoặc bằng chứng tương đương. Không gọi đây là độ chính xác câu trả lời LLM.",
        "- Metadata: 45 bản ghi top-3, đối chiếu trực tiếp text trích từ 13 trang PDF, header và offset; không kiểm tra hình ảnh/công thức. "
        "Filter: kiểm tra mọi hạng của hai câu có yêu cầu phạm vi.",
        "| Strategy | Coherence /2 (n) | Metadata đúng/đủ | Filter test | Grounding số mức 0/1/2 | Grounding TB /2 |\n|---|---|---|---|---|---|"
    ]
    for row in audit["strategies"]:
        dist=row["grounding_distribution"]
        report.append(f"| {row['strategy']} | {row['coherence_mean']:.2f} ({row['coherence_count']}) | "
                      f"{row['metadata_correct_n']}/{row['metadata_checked_n']} | "
                      f"{row['filter_compliant_n']}/{row['filter_questions_n']} | "
                      f"{dist['0']}/{dist['1']}/{dist['2']} | {row['grounding_mean']:.2f} |")
    report += [
        "\nMetadata source/page hỗ trợ truy vết; module/lecture thực sự giúp giới hạn phạm vi: C đạt 2/2 câu filter test, A/B 0/2. "
        "Đủ và đúng metadata không đồng nghĩa đã dùng filter hoặc truy xuất đủ bằng chứng. "
        "URL đã được đối chiếu hash; giấy phép tái phân phối chưa xác minh vẫn là hạn chế của nguồn.",
        f"- Phiếu: {link('grounding','results/manual_labels/01_grounding.md')}, "
        f"{link('coherence','results/manual_labels/02_coherence.md')}, "
        f"{link('metadata','results/manual_labels/03_metadata.md')}, "
        f"{link('filter','results/manual_labels/04_filter.md')}.",
        f"- Phương pháp và tác giả nhãn: {link('review_provenance.json','results/manual_labels/review_provenance.json')}.",
        f"- Tổng hợp: {link('review_summary.json','results/metrics/review_summary.json')}.\n",
        "### Tài nguyên và nạp lại\n",
        "| Strategy | Tổng token chunk | Encode document (s) | Cache hit / input duy nhất | Upsert đầu (s) | Upsert lại (s) |\n|---|---:|---:|---|---:|---:|"
    ]
    for name in ("A","B","C"):
        stats=embedding["strategies"][name]
        timing=ingestion["strategies"][name]
        cache=stats["cache"]
        cache_text="Dùng lại toàn bộ B" if name=="C" else f"{cache['cache_hits']}/{cache['unique_inputs']}"
        report.append(f"| {name} | {stats['total_tokens_with_special_tokens_and_overlap']} | "
                      f"{stats['embedding_seconds']:.3f} | {cache_text} | {timing['first_upsert_seconds']:.3f} | "
                      f"{timing['repeat_upsert_seconds']:.3f} |")
    report += [
        "\nC không encode document thêm vì dùng lại B; thời gian 0 không phải bằng chứng model của C nhanh hơn. "
        "Cache và một lần chạy trên một máy ảnh hưởng đo thời gian. Tổng PostgreSQL 845 hàng, nạp lại giữ nguyên 299/273/273.\n",
        "## 4. Phân tích và kết luận\n",
        "**A–B:** Hit@3 dev tăng từ 6/15 lên 8/15; test từ 2/5 lên 3/5. B giảm 26 chunk so với A. "
        "Coherence chỉ tăng nhẹ trong mẫu vì bước tách theo token vẫn có thể cắt câu/công thức. "
        "Không quy toàn bộ tác động riêng cho ranh giới đoạn vì overlap cũng khác.",
        "**B–C:** cùng điểm retrieval trên dev và test trong lần chạy này; C cải thiện tuân thủ phạm vi filter. "
        "Filter có thể loại nguồn hữu ích nếu metadata hoặc ngữ cảnh lọc sai. Lựa chọn cuối vẫn là B theo dev và tie-break đã chốt.\n",
        "### Hai ví dụ lỗi thực tế\n",
        "1. **B–q16, gold trang 47:** đoạn hạng 1 bị cắt trước quan hệ đầu vào bị chặn/đầu ra bị chặn; "
        "hai đoạn còn lại ở trang 52 và 50 là ví dụ khác. Grounding chỉ 1. "
        "A–q16 có hai mảnh ở trang 47 ghép lại đủ trả lời nên grounding 2, dù không có một chunk chứa toàn bộ quote: "
        "grounding và Evidence Hit@3 đo hai điều khác nhau.",
        "2. **A–q19, gold trang 54:** top-3 là trang 58, 23, 27; không có bằng chứng cho ánh xạ song tuyến tính z→w cần hỏi. "
        "B/C có đoạn đúng ở trang 54 phát biểu tương đương với gold. Nhãn grounding công nhận nội dung đó, "
        "trong khi phép exact-quote tự động có thể bỏ sót vì đoạn trả về khác câu gold ban đầu.\n",
        "### Giới hạn và cải tiến\n",
        "- Test chỉ 5 câu Module 3; một câu làm tỷ lệ đổi 20 điểm phần trăm. Một PDF, không có kiểm định thống kê hoặc khái quát ngoài corpus.",
        "- Mẫu coherence chỉ ở 10 trang đầu Module 1; nhãn chủ quan và phần lớn do AI chưa được học viên xác nhận; không đánh giá mù.",
        "- PDF có từ bị tách trong dòng và công thức tuyến tính hóa. Giới hạn 128 token có thể tách điều kiện khỏi kết luận.",
        "- Câu hỏi tiếng Việt tìm text tiếng Anh, nên kết quả kết hợp năng lực xuyên ngôn ngữ với chunking; không chỉ đo chunking.",
        "- Metric tự động bảo thủ; cần ghi nhận bằng chứng tương đương qua review rõ ràng, không âm thầm sửa gold sau khi thấy test.",
        "- Mở rộng trên một thí nghiệm/test mới: kiểm tra trích xuất công thức, chunk theo câu kèm giới hạn token, "
        "bổ sung tài liệu/chủ đề, đánh giá người chấm độc lập; thử hybrid trên dev. Không dùng test hiện tại để tinh chỉnh.\n",
        "## 5. Tái lập, AI và thông tin còn thiếu\n",
        "Các script dùng Python trong starter/.venv; phụ thuộc chính và snapshot cài đặt ở "
        +link('requirements.txt','starter/requirements.txt')+" và "+link('requirements-lock.txt','starter/requirements-lock.txt')+". "
        "Model revision được cố định; seed 42; Docker database port local 55433. "
        "Cách setup/chạy đầy đủ ở "+link('starter/README.md','starter/README.md')+".",
        "Codex AI hỗ trợ đọc tài liệu, viết code, soạn benchmark, phân tích trace và chấm phần nhãn được ghi rõ. "
        "Học viên đã chạy các bước pipeline và khai báo hai nhãn trong phiếu; không tự nhận các nhãn AI là nhãn người học tự chấm độc lập.",
        "Để giữ kết quả đã có, các lệnh check-only xác minh đầu vào mà không chạy lại test. "
        "Muốn tái lập từ đầu, dùng bản sao repo, giữ results cũ dưới tên results_reference trong bản sao, rồi chạy pipeline theo thứ tự. "
        "Không coi một lần điều chỉnh theo test đã xem là holdout độc lập.",
        f"- Repo bài nộp: {student['repo']}",
        f"- Commit chốt: {student['commit']}",
        "\nThông tin cần bổ sung/đọc lại:\n"+"\n".join("- "+item for item in missing),
        "\nKhông commit .env, token, cache/model hoặc tài liệu/trace chưa được phép chia sẻ. "
        "File Drive đã được đối chiếu hash; giấy phép tái phân phối chưa xác minh. GitHub giữ code, metadata, vị trí evidence và thống kê; nguồn/trace đầy đủ giữ local. Xem docs/DATA_ACCESS.md. "
        "Tên báo cáo theo MSSV_HoTen, giữ đúng cách viết tên trong cấu hình Git và tên file học viên tạo.\n"
    ]
    relative=student["report_path"]
    if relative.startswith("Chưa"):
        relative=f"report/individual/{student['id']}_BaoCao.md"
    output=(ROOT/relative).resolve()
    if not output.is_relative_to((ROOT/"report/individual").resolve()) or output.suffix!=".md":
        raise ValueError("Report output must stay under report/individual")
    text="\n\n".join(report)+"\n"
    text=re.sub(r"(?m)^(\|[^\n]*\|)\n\n(?=\|)", r"\1\n", text)
    text=text.rstrip()+"\n"
    if "?" in student["name"] and "Chưa" not in student["name"]:
        raise ValueError("Student name may have encoding loss; verify it before generating report")
    print("Report:",output.relative_to(ROOT).as_posix())
    print(f"Retrieval metric rows: {len(dev['summary'])+len(test['summary'])}; review records: {audit['review_records']}")
    print(f"Selected on dev remains: {selected}")
    print(f"Pending information/review items: {len(missing)}")
    if check_only:
        print("REPORT INPUT CHECK OK (report not written)")
        return
    if output.exists():
        backup=ROOT/"results/archive"/("report_previous_"+now.strftime("%Y%m%d_%H%M%S"))
        backup.mkdir(parents=True,exist_ok=False)
        shutil.copy2(output,backup/output.name)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(text,encoding="utf-8")
    write_json(ROOT/"results/metrics/report_build.json",{
        "created_at":now.isoformat(timespec="seconds"),"status":"draft",
        "student_id":student["id"],"report":output.relative_to(ROOT).as_posix(),
        "report_sha256":digest(output),"missing_information":missing,"ai_pending_confirmation_records":audit["ai_pending_confirmation_records"],
        "sources":{"dev":digest(ROOT/"results/metrics/dev.json"),"test":digest(ROOT/"results/metrics/test.json"),
                   "reviews":digest(ROOT/"results/metrics/review_summary.json"),"manifest":digest(ROOT/"data/manifest.json")},
        "note":"Generated from real outputs; no test rerun or strategy change."
    })
    print("REPORT READY (draft; missing information explicitly listed)")

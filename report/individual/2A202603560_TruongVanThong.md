# Báo cáo cá nhân — Day 06: Data Ingestion Engineering


- MSSV: **2A202603560**

- Họ và tên: **Truong Van Thong**

- Lớp: **L3A**

- Thời điểm tạo báo cáo: 2026-11-13T19:39:34+07:00

- Trạng thái: **Đã tổng hợp kết quả; quyền tái phân phối nguồn chưa được xác minh; nhãn AI được khai báo rõ tác giả.**


## 1. Dữ liệu và pipeline


Chủ đề Digital Control. File local: Digital control system.pdf (local: starter/data/Digital control system.pdf; [cách tái tạo](../../docs/DATA_ACCESS.md)). PDF có 230 trang vật lý; corpus chọn **54 trang**, 65,627 ký tự sau chuẩn hóa, thuộc Module 1–3.

Chọn trang PDF 1–58, bỏ 20, 28, 31, 53 vì chủ yếu là hình/đồ thị hoặc phần tính toán tiếp nối ngắn. Đếm theo vị trí trang PDF từ 1; số in ở cuối từng lecture có thể bắt đầu lại. Việc chọn dựa trên text và cấu trúc bài giảng với AI hỗ trợ, chưa kiểm tra hình ảnh toàn bộ PDF.

- Nguồn: [Google Drive do học viên cung cấp](https://drive.google.com/file/d/1PUynNV8-UVpHyM8ec4wIlvuqkM6UA-cy/view?usp=sharing). Link do học viên cung cấp; đã tải trực tiếp và xác minh SHA-256 trùng file local, xem results/logs/source_download_verification.json.

- Quyền/giấy phép: Chưa được cung cấp; không suy ra quyền sử dụng/tái phân phối từ link chia sẻ.

- Ngày truy cập/tải gốc: 2026-11-13T19:25:00+07:00

- SHA-256 file: 1a6ea27598537cf48555cc14b51cccd29fa78b96d4da948c0ecf60db96448585

- Manifest đầy đủ: [data/manifest.json](<../../data/manifest.json>).


Pipeline Python: đọc từng trang bằng pypdf → Unicode NFKC, xử lý khoảng trắng và giữ xuống dòng → chia chunk theo từng trang → tách thêm khi vượt giới hạn token → embedding local → PostgreSQL + pgvector → top-3 → đánh giá.

pypdf khôi phục 230 offset xref không chuẩn, đọc được 230 trang và không có trang thất bại trong log. fonttools hỗ trợ đọc encoding; ký hiệu/cấu trúc công thức và hình vẽ vẫn có thể sai sau trích text. Không có OCR hoặc chứng nhận độ chính xác công thức.


### Model, store và metadata


- Embedding: **sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2**, provider local Sentence Transformers, CPU.

- Revision: e8f8c211226b894fcb81acc59f3b34ba3efd5f42; số chiều **384**; giới hạn **128 token**.

- Dùng cùng encode(), không prefix, chuẩn L2 cho query và document; không dùng vector giả hoặc TF-IDF thay embedding.

- Phiên bản: sentence-transformers=5.7.0, transformers=5.22.2, torch=2.15.0, numpy=2.5.4.

- PostgreSQL 16.16 (Debian 16.16-1.pgdg12+1); pgvector 0.8.7; metric cosine, **exact search**, bảng day6_chunks.

- Store dùng named volume trong Docker Compose. Đã kiểm tra nạp hai lần không nhân đôi; chưa thực hiện kiểm tra restart container.

- Mỗi upsert là toàn bộ snapshot của một strategy; cập nhật ID ổn định và xóa ID hết hiệu lực trong cùng strategy, cùng transaction.

- Metadata: document_id/source/page để truy nguồn; module/lecture (integer) trích từ header in trên trang; language=en. Không suy đoán năm, phiên bản hay ngày hiệu lực.

- Mô hình embedding chạy local nên chi phí dịch vụ embedding/API của thí nghiệm là **0 USD**. Không đo điện, khấu hao máy hoặc chi phí sử dụng trợ lý AI.


## 2. Cấu hình và benchmark


| Strategy | Chunk ban đầu | Overlap | Chunk cuối | Filter |
|---|---|---:|---:|---|
| A | fixed, tối đa 480 ký tự | 48 | 299 | Không |
| B | paragraph, tối đa 480 ký tự | 0 | 273 | Không |
| C | paragraph, tối đa 480 ký tự | 0 | 273 | Module/Lecture khi câu hỏi yêu cầu |


A có 177 chunk ký tự, B/C có 173. Giới hạn model 128 token làm số chunk cuối tăng lên như bảng. Cùng quy tắc tách thêm được áp dụng cho mọi strategy, giữ offset nguồn và không cắt token âm thầm. B ưu tiên ranh giới đoạn/câu/dòng vì PDF không luôn có đoạn rõ ràng; B/C dùng chung chunk và vector.

A–B so sánh gói chiến lược chunking, bao gồm khác biệt overlap. B–C chỉ thay metadata filter; không thay corpus, model, store, chunk hay query vector.

Bộ 20 câu tiếng Việt, đáp án tiếng Việt và evidence tiếng Anh; 15 dev từ Module 1–2, 5 test từ Module 3. Đây là truy xuất xuyên ngôn ngữ. Có 6 câu filter, gồm 2 test. Filter Module/Lecture được nêu trong câu hỏi trước truy xuất; gold answer/source/page không được truyền vào search.

Đã kiểm tra evidence của 20/20 câu tồn tại đúng trang; câu hỏi ở benchmark/questions.json (local: benchmark/questions.json; [cách tái tạo](../../docs/DATA_ACCESS.md)), quy tắc ở [benchmark/protocol.json](<../../benchmark/protocol.json>).

Tiêu chí chọn trước test: Evidence Hit@3 dev cao nhất → Hit@1 cao nhất → số chunk ít nhất → tên strategy theo alphabet. Dev chọn **B**. B/C ngang điểm và cùng số chunk nên B thắng tiêu chí cuối; không kết luận B có retrieval tốt hơn C.

Lần dev đầu có lỗi mất dấu tiếng Việt do ghi file qua PowerShell. Đã lưu bản cũ trong results/archive, khôi phục đúng nội dung dự định và chạy lại dev trước khi test. Không đổi gold, split, filter hay cấu hình để nâng điểm. Lịch sử ở results/logs/benchmark_utf8_correction.json. Bảng dưới chỉ dùng lần đã sửa.


## 3. Kết quả


### Độ chính xác truy xuất


Hit@1 cần chunk hạng 1 đúng nguồn/trang và chứa đủ evidence. Evidence Hit@3 cần ít nhất một chunk như vậy trong top-3. Code tự động dùng toàn bộ quote sau chuẩn hóa khoảng trắng; đây là cách đối chiếu bảo thủ, có thể bỏ sót cách diễn đạt tương đương. Không cộng nhiều chunk để thay định nghĩa chính.

| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk | Query trung bình (ms) |
|---|---|---|---|---:|---:|
| A | dev | 4/15 (26.7%) | 6/15 (40.0%) | 299 | 27.53 |
| B | dev | 7/15 (46.7%) | 8/15 (53.3%) | 273 | 25.61 |
| C | dev | 7/15 (46.7%) | 8/15 (53.3%) | 273 | 26.63 |
| A | test | 2/5 (40.0%) | 2/5 (40.0%) | 299 | 28.58 |
| B | test | 2/5 (40.0%) | 3/5 (60.0%) | 273 | 24.08 |
| C | test | 2/5 (40.0%) | 3/5 (60.0%) | 273 | 26.11 |


Đã lưu 45 lượt truy xuất dev và 15 lượt test, mỗi lượt top-3. Query latency gồm mở kết nối PostgreSQL và SQL; thời gian encode query dùng chung được đo riêng. Thứ tự A/B/C xoay vòng giữa các câu.

- Dev: trace (local: results/traces/dev.jsonl; [cách tái tạo](../../docs/DATA_ACCESS.md)), [metrics](<../../results/metrics/dev.json>).

- Test: trace (local: results/traces/test.jsonl; [cách tái tạo](../../docs/DATA_ACCESS.md)), [metrics](<../../results/metrics/test.json>).

- Bảng kết hợp: [combined.csv](<../../results/metrics/combined.csv>).


### Coherence, metadata và grounding — nhãn có AI hỗ trợ


Tổng 96 nhãn: giữ 2 mục học viên đã điền; 94 mục do Codex AI đọc/đối chiếu và điền, **chưa được học viên xác nhận**. Không mô tả các mục này thành đánh giá thủ công độc lập của học viên. Cùng trợ lý đã giúp soạn câu hỏi nên có nguy cơ thiên lệch.

- Coherence: cùng 10 vị trí nguồn cố định trước retrieval, chọn chunk phủ vị trí có trung điểm gần nhất; thang 0/1/2.

- Grounding: 5 câu test mỗi strategy, đọc toàn bộ top-3; 0 không có bằng chứng, 1 thiếu điều kiện/ngữ cảnh, 2 đủ trả lời và truy nguồn. Có thể dùng các đoạn kết hợp hoặc bằng chứng tương đương. Không gọi đây là độ chính xác câu trả lời LLM.

- Metadata: 45 bản ghi top-3, đối chiếu trực tiếp text trích từ 13 trang PDF, header và offset; không kiểm tra hình ảnh/công thức. Filter: kiểm tra mọi hạng của hai câu có yêu cầu phạm vi.

| Strategy | Coherence /2 (n) | Metadata đúng/đủ | Filter test | Grounding số mức 0/1/2 | Grounding TB /2 |
|---|---|---|---|---|---|
| A | 1.00 (10) | 15/15 | 0/2 | 1/1/3 | 1.40 |
| B | 1.10 (10) | 15/15 | 0/2 | 0/1/4 | 1.80 |
| C | 1.10 (10) | 15/15 | 2/2 | 0/1/4 | 1.80 |


Metadata source/page hỗ trợ truy vết; module/lecture thực sự giúp giới hạn phạm vi: C đạt 2/2 câu filter test, A/B 0/2. Đủ và đúng metadata không đồng nghĩa đã dùng filter hoặc truy xuất đủ bằng chứng. URL đã được đối chiếu hash; giấy phép tái phân phối chưa xác minh vẫn là hạn chế của nguồn.

- Phiếu: grounding (local: results/manual_labels/01_grounding.md; [cách tái tạo](../../docs/DATA_ACCESS.md)), coherence (local: results/manual_labels/02_coherence.md; [cách tái tạo](../../docs/DATA_ACCESS.md)), metadata (local: results/manual_labels/03_metadata.md; [cách tái tạo](../../docs/DATA_ACCESS.md)), filter (local: results/manual_labels/04_filter.md; [cách tái tạo](../../docs/DATA_ACCESS.md)).

- Phương pháp và tác giả nhãn: review_provenance.json (local: results/manual_labels/review_provenance.json; [cách tái tạo](../../docs/DATA_ACCESS.md)).

- Tổng hợp: [review_summary.json](<../../results/metrics/review_summary.json>).


### Tài nguyên và nạp lại


| Strategy | Tổng token chunk | Encode document (s) | Cache hit / input duy nhất | Upsert đầu (s) | Upsert lại (s) |
|---|---:|---:|---|---:|---:|
| A | 25433 | 12.376 | 0/299 | 0.113 | 0.123 |
| B | 23267 | 11.537 | 14/273 | 0.093 | 0.106 |
| C | 23267 | 0.000 | Dùng lại toàn bộ B | 0.089 | 0.103 |


C không encode document thêm vì dùng lại B; thời gian 0 không phải bằng chứng model của C nhanh hơn. Cache và một lần chạy trên một máy ảnh hưởng đo thời gian. Tổng PostgreSQL 845 hàng, nạp lại giữ nguyên 299/273/273.


## 4. Phân tích và kết luận


**A–B:** Hit@3 dev tăng từ 6/15 lên 8/15; test từ 2/5 lên 3/5. B giảm 26 chunk so với A. Coherence chỉ tăng nhẹ trong mẫu vì bước tách theo token vẫn có thể cắt câu/công thức. Không quy toàn bộ tác động riêng cho ranh giới đoạn vì overlap cũng khác.

**B–C:** cùng điểm retrieval trên dev và test trong lần chạy này; C cải thiện tuân thủ phạm vi filter. Filter có thể loại nguồn hữu ích nếu metadata hoặc ngữ cảnh lọc sai. Lựa chọn cuối vẫn là B theo dev và tie-break đã chốt.


### Hai ví dụ lỗi thực tế


1. **B–q16, gold trang 47:** đoạn hạng 1 bị cắt trước quan hệ đầu vào bị chặn/đầu ra bị chặn; hai đoạn còn lại ở trang 52 và 50 là ví dụ khác. Grounding chỉ 1. A–q16 có hai mảnh ở trang 47 ghép lại đủ trả lời nên grounding 2, dù không có một chunk chứa toàn bộ quote: grounding và Evidence Hit@3 đo hai điều khác nhau.

2. **A–q19, gold trang 54:** top-3 là trang 58, 23, 27; không có bằng chứng cho ánh xạ song tuyến tính z→w cần hỏi. B/C có đoạn đúng ở trang 54 phát biểu tương đương với gold. Nhãn grounding công nhận nội dung đó, trong khi phép exact-quote tự động có thể bỏ sót vì đoạn trả về khác câu gold ban đầu.


### Giới hạn và cải tiến


- Test chỉ 5 câu Module 3; một câu làm tỷ lệ đổi 20 điểm phần trăm. Một PDF, không có kiểm định thống kê hoặc khái quát ngoài corpus.

- Mẫu coherence chỉ ở 10 trang đầu Module 1; nhãn chủ quan và phần lớn do AI chưa được học viên xác nhận; không đánh giá mù.

- PDF có từ bị tách trong dòng và công thức tuyến tính hóa. Giới hạn 128 token có thể tách điều kiện khỏi kết luận.

- Câu hỏi tiếng Việt tìm text tiếng Anh, nên kết quả kết hợp năng lực xuyên ngôn ngữ với chunking; không chỉ đo chunking.

- Metric tự động bảo thủ; cần ghi nhận bằng chứng tương đương qua review rõ ràng, không âm thầm sửa gold sau khi thấy test.

- Mở rộng trên một thí nghiệm/test mới: kiểm tra trích xuất công thức, chunk theo câu kèm giới hạn token, bổ sung tài liệu/chủ đề, đánh giá người chấm độc lập; thử hybrid trên dev. Không dùng test hiện tại để tinh chỉnh.


## 5. Tái lập, AI và thông tin còn thiếu


Các script dùng Python trong starter/.venv; phụ thuộc chính và snapshot cài đặt ở [requirements.txt](<../../starter/requirements.txt>) và [requirements-lock.txt](<../../starter/requirements-lock.txt>). Model revision được cố định; seed 42; Docker database port local 55433. Cách setup/chạy đầy đủ ở [starter/README.md](<../../starter/README.md>).

Codex AI hỗ trợ đọc tài liệu, viết code, soạn benchmark, phân tích trace và chấm phần nhãn được ghi rõ. Học viên đã chạy các bước pipeline và khai báo hai nhãn trong phiếu; không tự nhận các nhãn AI là nhãn người học tự chấm độc lập.

Để giữ kết quả đã có, các lệnh check-only xác minh đầu vào mà không chạy lại test. Muốn tái lập từ đầu, dùng bản sao repo, giữ results cũ dưới tên results_reference trong bản sao, rồi chạy pipeline theo thứ tự. Không coi một lần điều chỉnh theo test đã xem là holdout độc lập.

- Repo bài nộp: https://github.com/thongthong2k41306-beep/K5-L3A-Day06-2A202603560-DataIngestionEngineering

- Commit chốt: Git tag submission-2A202603560-20261113; tra SHA bằng git rev-parse submission-2A202603560-20261113.


Thông tin cần bổ sung/đọc lại:
- Giấy phép/quyền xử lý và chia sẻ tài liệu


Không commit .env, token, cache/model hoặc tài liệu/trace chưa được phép chia sẻ. File Drive đã được đối chiếu hash; giấy phép tái phân phối chưa xác minh. GitHub giữ code, metadata, vị trí evidence và thống kê; nguồn/trace đầy đủ giữ local. Xem docs/DATA_ACCESS.md. Tên báo cáo theo MSSV_HoTen, giữ đúng cách viết tên trong cấu hình Git và tên file học viên tạo.

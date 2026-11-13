# Bài làm — Digital Control / PostgreSQL + pgvector

Pipeline đã được triển khai trong src/ và scripts/. Dữ liệu: Digital control system.pdf; MSSV 2A202603560, L3A. Học viên: Truong Van Thong. Quyền tái phân phối PDF chưa được xác minh. Nguồn Drive do học viên cung cấp nằm trong ../data/manifest.json; đã tải trực tiếp và đối chiếu hash trùng file local; chưa xác minh giấy phép.

## Setup trên Windows PowerShell

Đã chạy bằng Python 3.13.15, PostgreSQL 16.16 và pgvector 0.8.7. Từ repo root:

```powershell
cd starter
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
if (-not (Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }
docker compose -p day6_student_starter up -d --wait
.\.venv\Scripts\python.exe scripts/check_setup.py
```

Database ở 127.0.0.1:55433; cấu hình trong .env. Không commit .env. Model chạy local, không cần API key. Cache/trọng số không có trong Git nên lần đầu cần mạng tải model.

## Các bước chạy

Các lệnh sau chạy từ starter. Bộ kết quả dev/test hiện có được giữ để kiểm tra. Muốn tái lập từ đầu, làm trên bản sao repo riêng, giữ thư mục results cũ dưới tên results_reference trong bản sao trước khi bắt đầu; nguồn gốc chưa được phép chia sẻ thì tự cung cấp PDF local theo manifest.

```powershell
.\.venv\Scripts\python.exe scripts/prepare_data.py
.\.venv\Scripts\python.exe scripts/build_benchmark.py
.\.venv\Scripts\python.exe scripts/check_benchmark.py
.\.venv\Scripts\python.exe scripts/prepare_chunks.py
.\.venv\Scripts\python.exe scripts/embed_chunks.py --download-model
.\.venv\Scripts\python.exe scripts/ingest_vectors.py
.\.venv\Scripts\python.exe scripts/run_dev.py
.\.venv\Scripts\python.exe scripts/run_test.py
.\.venv\Scripts\python.exe scripts/prepare_audits.py
```

Đọc và chấm các phiếu trong ../results/manual_labels/, ghi đúng người chấm và phương pháp AI nếu có. Sau đó:

```powershell
.\.venv\Scripts\python.exe scripts/collect_audits.py
.\.venv\Scripts\python.exe scripts/build_report.py
```

build_benchmark.py tái tạo câu hỏi và evidence từ question_specs.public.json với offset số trên text local, không sinh câu mới bằng model. Bộ câu hỏi đã chốt có thể được kiểm tra bằng check_benchmark.py; không sửa sau khi nhìn test để tinh chỉnh.

## Kiểm tra bộ kết quả đã có

```powershell
.\.venv\Scripts\python.exe -m src.run
.\.venv\Scripts\python.exe scripts/run_test.py --check-only
.\.venv\Scripts\python.exe scripts/collect_audits.py --check-only
.\.venv\Scripts\python.exe scripts/build_report.py --check-only
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

src.run mặc định chỉ hiện trạng thái; --stage data/benchmark/chunks/embedding/ingest/dev/test/audits/reviews/report chạy từng bước. Ví dụ:

```powershell
.\.venv\Scripts\python.exe -m src.run --stage report
```

run_dev.py từ chối chạy lại nếu có test. run_test.py xác minh cấu hình đã chốt trên dev và không ghi đè trace test đã tồn tại. Các lệnh check-only không chạy truy xuất hoặc sửa cấu hình. Bản báo cáo cũ được sao lưu khi build_report.py tạo lại.

## Artifacts và cách đánh giá

- ../data/manifest.json: nguồn, hash PDF, 230 trang vật lý; chọn 54 trang Module 1–3.
- ../benchmark/questions.json: 20 câu Việt, gold/evidence Anh, 15 dev / 5 test, 6 câu filter gồm 2 test.
- ../configs/strategies.json, model_lock.json, selected_strategy.json: A/B/C, revision model và lựa chọn trên dev.
- ../results/traces/: top-3 dev/test với nội dung, score, metadata và gold.
- ../results/metrics/: corpus, chunking, embedding, ingestion, dev/test, nhãn và báo cáo.
- ../results/manual_labels/: nhãn, phương pháp AI và các mục đã được học viên nhập.
- ../artifacts/experiment_log.csv: giả thuyết/cấu hình và số đo thực tế.
- ../report/individual/2A202603560_TruongVanThong.md: báo cáo sau khi chạy build_report.py.

Model local paraphrase-multilingual-MiniLM-L12-v2, revision cố định, 384 chiều, giới hạn 128 token. A fixed 480 ký tự/overlap 48; B theo đoạn/câu/dòng tối đa 480; C cùng B và thêm filter Module/Lecture. Tách thêm theo cùng giới hạn token cho tất cả strategy, thành 299/273/273 chunk cuối.

Chiến lược B được chọn từ dev theo Evidence Hit@3, Hit@1, số chunk rồi tên. Test chỉ đo sau khi chốt. Exact-quote metrics bảo thủ có thể bỏ sót bằng chứng tương đương; grounding 0–2 đọc toàn bộ top-3, không phải độ chính xác câu trả lời LLM.

94/96 nhãn được Codex AI hỗ trợ chấm và chưa có xác nhận học viên; 2 nhãn học viên đã nhập được giữ nguyên. Phương pháp và giới hạn công khai trong review_provenance.json. Không mô tả chúng thành đánh giá mù độc lập của học viên.

Đã sửa lỗi mất dấu câu hỏi trước khi chạy test và chạy lại dev; bản lỗi được lưu trong ../results/archive, lịch sử ở benchmark/protocol.json. Không chạy lại test để thay đổi cấu hình sau khi thấy điểm.

Dừng container giữ dữ liệu:

```powershell
docker compose -p day6_student_starter stop
```

Tài liệu starter gốc được giữ ở ../docs/STARTER_README_DE_BAI.md. Hướng dẫn đề và rubric vẫn ở repo root.

## Nội dung nguồn được giữ local

Xem [DATA_ACCESS.md](../docs/DATA_ACCESS.md). GitHub không kèm PDF, text, quote hoặc trace nguyên văn khi quyền tái phân phối chưa rõ. Có question_specs.public.json với offset evidence và results/review_labels.csv với nhận xét/nhãn có khai báo tác giả.

Sau prepare_audits.py, có thể tái sử dụng nhãn gốc chỉ khi mọi hash ngữ cảnh khớp:

```powershell
.\.venv\Scripts\python.exe scripts/restore_review_labels.py
.\.venv\Scripts\python.exe scripts/collect_audits.py
.\.venv\Scripts\python.exe scripts/build_report.py
```

Gói đầy đủ chỉ được tạo trên máy bằng package_submission.py, ở ../artifacts/submission/, không nằm trên GitHub. Việc cung cấp bản nguồn cho người chấm phụ thuộc quyền chia sẻ thực tế và kênh lớp.

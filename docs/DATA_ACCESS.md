# Dữ liệu và cách tái tạo

## Nguồn đã kiểm chứng

- Truong Van Thong — MSSV 2A202603560 — L3A.
- [PDF do học viên cung cấp](https://drive.google.com/file/d/1PUynNV8-UVpHyM8ec4wIlvuqkM6UA-cy/view?usp=sharing).
- Đã tải trực tiếp và đối chiếu ngày 13/11/2026: SHA-256 1a6ea27598537cf48555cc14b51cccd29fa78b96d4da948c0ecf60db96448585.
- Ngày truy cập này do trợ lý thực sự kiểm chứng, không phải ngày tải ban đầu của học viên.
- 230 trang vật lý; chọn 54 trang: trang PDF 1–58, bỏ 20, 28, 31, 53.

[Khóa Digital Control System của NPTEL/IIT Guwahati](https://nptel.ac.in/courses/108103008) có cấu trúc Module/Lecture tương ứng. Đây là nguồn tham khảo nhận diện chủ đề, không chứng minh giấy phép cho bản PDF gộp trên Drive.

## Phạm vi công khai

Chưa xác minh quyền tái phân phối PDF. GitHub giữ code, metadata, câu hỏi/đáp án do AI hỗ trợ soạn, vị trí số của evidence, nhận xét đánh giá, số đo và báo cáo. PDF, text trích xuất, quote đầy đủ, trace top-3 và phiếu kèm nội dung nguồn được giữ local.

Không tự gán Creative Commons hay suy ra giấy phép từ link chia sẻ. [Điều khoản NPTEL](https://onlinecourses-archive.nptel.ac.in/modules/nptel/assets/html/terms.html) là thông tin tham khảo; chưa xác minh giấy phép áp dụng cho file Drive.

## Tái tạo

1. Trên bản sao repo, giữ results cũ dưới tên results_reference trước khi bắt đầu. Không thay test đã xem rồi gọi là holdout độc lập.
2. Cung cấp bản PDF được phép sử dụng ở starter/data/Digital control system.pdf; kiểm tra hash nêu trên.
3. Theo starter/README.md, chạy prepare_data.py → build_benchmark.py → check_benchmark.py → prepare_chunks.py → embed_chunks.py --download-model → ingest_vectors.py → run_dev.py → run_test.py → prepare_audits.py.
4. build_benchmark.py dùng question_specs.public.json, trích evidence theo offset trên text chuẩn hóa và xác minh byte-identical với hash benchmark đã chốt. Không cần công khai quote nguồn để tái tạo.
5. restore_review_labels.py chỉ áp dụng các nhãn đã công bố khi mọi hash ngữ cảnh trùng. Nếu khác ngữ cảnh phải chấm lại; giữ đúng tác giả AI/học viên.
6. Chạy collect_audits.py và build_report.py. Hai ma trận vector được tạo lại từ model revision đã cố định; cache/trọng số không nằm trong Git.

## Bản đầy đủ local

artifacts/submission/ chứa gói ZIP sau package_submission.py: code, PDF, text, evidence, trace, phiếu và hai ma trận vector; không gồm .env, token, .git, môi trường ảo hoặc model cache. Gói không được đẩy lên GitHub. Cách cung cấp nguồn cho người chấm phụ thuộc quyền chia sẻ thực tế và kênh lớp.

96 nhãn gồm 94 nhãn AI chưa được học viên xác nhận và 2 mục học viên đã nhập. Tác giả/phương pháp được giữ trong results/review_labels.csv và báo cáo.

# Bước 4 — Chuẩn bị corpus và manifest

Manifest là hồ sơ nguồn: ghi tài liệu, nguồn/quyền sử dụng, hash file, số trang và các trang được chọn để người chấm truy vết, tái lập.

PDF có 230 trang vật lý. Corpus chọn 54 trang: trang PDF 1–58, bỏ 20, 28, 31, 53 vì chủ yếu là hình/đồ thị hoặc tính toán ngắn. Module 1–3. Số trang PDF tính từ 1; số trang in ở chân lecture có thể bắt đầu lại.

Lựa chọn dựa trên đọc text bằng AI; học viên cần đối chiếu PDF, nhất là công thức. Số ký tự không chứng minh chất lượng công thức.

Chạy từ starter:

    .\.venv\Scripts\python.exe scripts/prepare_data.py

Đầu ra: data/manifest.json; data/processed/all_pages.jsonl; data/processed/pages.jsonl; results/metrics/corpus.json; results/logs/pdf_extraction.json.

Chuẩn hóa Unicode NFKC, khoảng trắng và giữ xuống dòng; metadata Module/Lecture lấy từ header. PDF có 230 cảnh báo xref đã được pypdf khôi phục; log ghi số lượng và mẫu cảnh báo. Không có OCR hoặc kiểm chứng hình ảnh toàn bộ.

original_source_url, license_or_permission, accessed_at chưa xác minh và để null. Ngày kiểm tra local được ghi riêng, không thay ngày truy cập nguồn. Học viên cần bổ sung nguồn cung cấp và quyền xử lý/chia sẻ trước khi nộp.

Bước sau là chốt benchmark trước khi chạy truy xuất.

# Bước 9 — Đánh giá dev và chốt cấu hình

Chạy từ starter, giữ Docker Desktop mở:

    .\.venv\Scripts\python.exe scripts/run_dev.py

Chỉ dùng 15 câu dev. Trước khi truy xuất, đối chiếu toàn bộ chunk, nguồn, trang, metadata và vector PostgreSQL với artifact; cố định 10 vị trí để audit coherence.

Mỗi câu hỏi được encode một lần. Chỉ question text đi vào embedder. A/B không filter; C dùng Module/Lecture đã được nêu trong câu hỏi. Gold answer/page/evidence chỉ được dùng sau truy xuất để chấm.

Hit@1: top-1 đúng nguồn/trang và chứa đủ evidence. Evidence Hit@3: có ít nhất một chunk đạt điều kiện đó trong top-3. Chia số câu đúng cho tổng câu. Không cộng mẩu evidence từ nhiều chunk để thay định nghĩa chính. Bằng chứng tương đương cần review riêng.

Chọn theo thứ tự đã chốt: Evidence Hit@3 dev cao nhất, Hit@1 cao nhất, số chunk ít nhất, rồi tên cấu hình. Không dùng test để chọn.

Đầu ra: results/traces/dev.jsonl; results/metrics/dev.json và dev.csv; configs/selected_strategy.json; artifacts/experiment_log.csv; benchmark/coherence_positions.json.

Thời gian query gồm kết nối PostgreSQL và SQL, không gồm embedding dùng chung. Xoay thứ tự A/B/C giữa các câu khi đo thời gian. Không tự suy ra nhãn coherence/grounding từ Hit@3.

Đã phát hiện và sửa lỗi ghi Unicode qua PowerShell: câu hỏi tiếng Việt bị biến dấu thành ?. Lần dev đầu được lưu riêng trong results/archive; chưa chạy test trước khi sửa. Chỉ khôi phục đúng nội dung câu hỏi/đáp án đã soạn, không đổi gold, split, filter, corpus, model hay cấu hình. Phải chạy lại dev sau sửa; các kết quả cũ không đại diện cho benchmark tiếng Việt dự định.

Chỉ sau DEV BENCHMARK OK của lần đã sửa mới chạy test. Nếu test đã tồn tại, script chặn dev lại để tránh điều chỉnh theo kết quả test.

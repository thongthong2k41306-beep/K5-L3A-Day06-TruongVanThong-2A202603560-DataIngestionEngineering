# Bước 10 — Đánh giá test sau khi chốt cấu hình

Dev đã chọn B: B/C cùng Hit@1 7/15, Evidence Hit@3 8/15 và cùng 273 chunk; thứ tự tên phân xử tie theo quy tắc chốt trước. Kết quả này thuộc lần đã sửa Unicode; lần lỗi cũ được lưu trong results/archive.

Giữ Docker Desktop mở. Chạy từ starter:

    .\.venv\Scripts\python.exe scripts/run_test.py

Script xác minh hash benchmark, corpus, model, code truy xuất/đánh giá, kết quả dev và 10 vị trí coherence. Các giá trị phải khớp configs/selected_strategy.json. Code đã chốt không bị thay đổi khi thêm script test này.

Chạy cùng 5 câu test cho A/B/C, mỗi câu top-3. C áp dụng filter từ câu hỏi, A/B không lọc. Gold chỉ dùng sau truy xuất. Không thay lựa chọn B dựa vào điểm test.

Đầu ra: results/traces/test.jsonl; results/metrics/test.json, test.csv, combined.csv; cập nhật cột test trong artifacts/experiment_log.csv. configs/selected_strategy.json được giữ nguyên.

Chỉ năm câu test nên một câu làm tỷ lệ thay đổi 20 điểm phần trăm; không suy rộng ngoài corpus. Nhãn coherence, metadata đúng/đủ và grounding vẫn cần đánh giá riêng ở bước sau.

Script lưu dấu lần chạy và từng trace. Nếu bị ngắt, giữ file dở để kiểm tra; không xóa kết quả rồi chỉnh dev và báo test như độc lập. Chạy lại khi đã có output sẽ không ghi đè. Check-only chỉ kiểm tra đầu vào, không tạo query embedding hoặc chạy test:

    .\.venv\Scripts\python.exe scripts/run_test.py --check-only

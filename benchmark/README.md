# Benchmark Digital Control

Bộ câu hỏi do AI hỗ trợ soạn từ PDF học viên cung cấp; học viên cần đọc lại ý nghĩa và đối chiếu PDF. Evidence nguyên văn được kiểm tra đúng trang sau chuẩn hóa, không thay việc xác nhận đáp án về nghĩa.

- questions.json: 20 câu tiếng Việt, đáp án tiếng Việt, evidence tiếng Anh.
- question_specs.json: câu hỏi/đáp án và marker trích evidence để tái tạo.
- protocol.json: cách chia, tiêu chí lựa chọn, hash và lịch sử sửa lỗi.
- 15 dev từ Module 1–2; 5 test từ Module 3. Cùng corpus 54 trang cho mọi cấu hình.
- 6 câu filter, gồm 2 test. Module/Lecture do câu hỏi cung cấp trước truy xuất.
- Không dùng gold page/source/answer để tạo query hay filter.
- Đây là truy xuất xuyên ngôn ngữ Việt–Anh. Test nhỏ, chỉ có chủ đề ổn định Module 3 và không đại diện toàn môn học.

Chạy từ starter:

    .\.venv\Scripts\python.exe scripts/check_benchmark.py

Lần dev đầu dùng câu hỏi bị lỗi dấu do thao tác ghi file. Đã lưu lần đó vào results/archive, khôi phục nội dung Unicode dự định và ghi thay đổi trong protocol.json cùng results/logs/benchmark_utf8_correction.json. Chưa chạy test trước khi sửa; cần chạy lại dev. Không đổi gold evidence, trang, split hoặc cấu hình để nâng điểm.

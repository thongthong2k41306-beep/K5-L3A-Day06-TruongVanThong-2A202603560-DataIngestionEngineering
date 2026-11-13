# Bước 8 — Lưu vector vào PostgreSQL + pgvector

Giữ Docker Desktop mở. Chạy từ starter:

    .\.venv\Scripts\python.exe scripts/ingest_vectors.py

Script xác minh hash corpus/config/model, vector và chunk ID trước khi ghi. DATABASE_URL được đọc từ starter/.env, không in mật khẩu.

Bảng day6_chunks lưu strategy, chunk_id, document_id, source, page, content, metadata và vector(384). Khóa chính (strategy,chunk_id) tránh trùng. Mỗi upsert nhận toàn bộ snapshot một strategy; chunk cũ hết hiệu lực chỉ trong strategy đó được xóa trong transaction. Không xóa database/volume.

Nạp cùng dữ liệu hai lần để kiểm tra idempotency. Kết quả hiện tại A:299, B:273, C:273 = 845 hàng. Kiểm tra backend bằng vector đầu tiên và filter C, không dùng câu hỏi benchmark.

Đầu ra: results/metrics/ingestion.json và results/logs/store_smoke.json. Volume PostgreSQL đã được cấu hình lưu bền vững; việc restart container chưa được tự nhận là đã kiểm chứng nếu chưa chạy thử.

Sau VECTOR STORE OK, chạy dev trước; test chỉ dùng sau khi chốt cấu hình.

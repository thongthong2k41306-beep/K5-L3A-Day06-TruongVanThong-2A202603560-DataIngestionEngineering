# Bước 7 — Tạo embedding local

Embedding biến mỗi chunk thành vector để tìm theo ý nghĩa. A/B/C dùng cùng model/revision.

Chạy từ starter:

    .\.venv\Scripts\python.exe scripts/embed_chunks.py

Model đã tải trong .cache/huggingface. Trên máy mới chưa có model, cho phép tải trọng số bằng:

    .\.venv\Scripts\python.exe scripts/embed_chunks.py --download-model

Model paraphrase-multilingual-MiniLM-L12-v2 chạy CPU, 384 chiều, tối đa 128 token; revision và phiên bản thư viện ở configs/model_lock.json. Không cần API key, không tải PDF lên provider. Chi phí dịch vụ 0 USD, không tính điện/khấu hao máy.

480 ký tự có thể vượt 128 token. Cùng một quy tắc tách thêm được áp dụng trước embedding cho A/B/C, giữ offset nguồn và kiểm tra không mất nội dung. Kết quả hiện tại A:299, B/C:273 chunk cuối. C dùng lại chunk và vector của B.

Đầu ra: data/processed/embedded_chunks_A.jsonl, embedded_chunks_B.jsonl, embedded_chunks_C.jsonl; artifacts/embedding_cache/strategy_A.npz và strategy_B.npz; results/metrics/embeddings.json. Cache không đưa vào Git.

Kiểm tra shape, số chiều, chuẩn L2, giá trị hữu hạn, hash và thứ tự chunk ID. Đây là file trung gian; bước sau nạp vào PostgreSQL.

# DocGrading

Hệ thống hỗ trợ đánh giá chất lượng báo cáo PDF theo rubric, với kết quả tự động đóng vai trò đề xuất để giảng viên duyệt và công bố.

## Cấu trúc repository

- `docs/requirements/`: SRS hiện hành và bản nháp lưu trữ.
- `docs/design/`: quyết định phạm vi, kiến trúc và context thiết kế.
- `docs/planning/`: kế hoạch phát triển và WBS.
- `frontend/`: giao diện React/Vite có thể chạy độc lập.
- `backend/`: FastAPI API, Celery worker và cấu hình persistence/queue.

Xem hướng dẫn chạy tại `frontend/README.md` và `backend/README.md`.

# Thiết kế nền tảng backend DocGrading — T-005

Ngày: 2026-08-25

Trạng thái: Đã duyệt trong phiên thiết kế

## 1. Mục tiêu và phạm vi

T-005 tạo nền tảng có thể chạy và kiểm chứng cho backend DocGrading theo kiến trúc modular monolith có worker riêng:

- FastAPI và Python 3.13 cho API;
- SQLAlchemy 2, Alembic và PostgreSQL 17 cho persistence;
- Celery 5.6 và Redis 7 cho xử lý nền;
- volume local riêng cho PDF trong môi trường phát triển;
- Docker Compose cho toàn bộ stack backend;
- GitHub Actions cho lint, test và build Docker image trên pull request.

T-005 không tạo model hoặc schema domain như User, Course, Assignment, Submission; không triển khai upload PDF, storage adapter S3, endpoint nghiệp vụ, Caddy hay tích hợp frontend. `frontend/` và stack React + TypeScript + Vite giữ nguyên.

## 2. Cấu trúc repository

Backend là một Python project độc lập trong `backend/`:

```text
backend/
├── app/
│   ├── api/
│   │   └── routers/
│   ├── core/
│   ├── db/
│   ├── models/
│   ├── services/
│   ├── workers/
│   └── main.py
├── alembic/
│   └── versions/
├── tests/
├── .env.example
├── alembic.ini
├── Dockerfile
├── pyproject.toml
└── README.md
```

Các package có trách nhiệm:

- `api/routers`: endpoint HTTP, trước mắt chỉ có router hệ thống;
- `core`: settings và cấu hình dùng chung;
- `db`: SQLAlchemy engine, session factory và declarative base;
- `models`: import boundary cho metadata, chưa có domain model;
- `services`: boundary cho application logic ở backlog sau;
- `workers`: Celery application và task;
- `main.py`: application factory và đăng ký router.

Cấu trúc layer-first giữ bootstrap gọn, đồng thời không cản việc T-006 bổ sung các module domain theo ranh giới đã chốt trong tài liệu kiến trúc.

## 3. API và persistence

FastAPI cung cấp `GET /api/v1/health`. Endpoint trả HTTP 200 và payload trạng thái ổn định, chỉ biểu thị process API còn sống; nó không tuyên bố PostgreSQL hoặc Redis sẵn sàng.

SQLAlchemy dùng API 2.x và async engine với PostgreSQL. Session factory và `DeclarativeBase` được định nghĩa nhưng không tạo model. Import ứng dụng không mở kết nối database, nhờ vậy lint, test smoke và Docker build không phụ thuộc service ngoài.

Alembic lấy database URL và metadata từ cùng lớp settings với ứng dụng. Revision đầu tiên có `upgrade` và `downgrade` rỗng, không tạo bảng. Khi container API khởi động, migration chạy trước Uvicorn; migration lỗi làm container dừng thay vì phục vụ trên schema sai.

## 4. Worker và queue

Celery dùng Redis làm broker và result backend, serializer JSON và danh sách task đăng ký tường minh. Task mẫu có tên ổn định `app.workers.tasks.healthcheck`, không truy cập database hoặc domain và trả payload xác nhận worker đã xử lý message.

Task này chỉ chứng minh luồng producer → Redis broker → Celery worker → Redis result backend. Retry, idempotency theo database và routing nghiệp vụ thuộc các backlog triển khai pipeline sau.

## 5. Cấu hình, secrets và storage

`backend/.env.example` liệt kê biến cấu hình cùng giá trị placeholder an toàn cho development. Developer sao chép file này thành `backend/.env`; file thật bị Git ignore. Credential không xuất hiện trong source, Dockerfile hoặc workflow.

Nhóm biến tối thiểu gồm:

- môi trường, host và port API;
- thông tin PostgreSQL và `DATABASE_URL`;
- Celery broker URL và result backend URL;
- `STORAGE_PATH`.

Pydantic Settings đọc biến môi trường và fail-fast khi thiếu cấu hình bắt buộc. Docker Compose truyền cùng cấu hình cho API và worker.

PDF không được lưu trong PostgreSQL. Môi trường development mount một Docker named volume vào `STORAGE_PATH`, tách vòng đời file khỏi database và container. T-005 chưa dựng MinIO vì baseline kiến trúc yêu cầu local volume ở dev và S3-compatible storage ở staging/production.

## 6. Docker Compose

`docker-compose.yml` ở root build một image từ `backend/Dockerfile` và chạy bốn service:

- `api`: migrate rồi chạy Uvicorn;
- `worker`: chạy Celery worker từ cùng image và codebase;
- `postgres`: PostgreSQL 17 với persistent volume và healthcheck;
- `redis`: Redis 7 với persistent volume và healthcheck.

API và worker chỉ khởi động sau các dependency cần thiết đạt healthcheck. Image chạy bằng user không đặc quyền. Sau khi tạo `backend/.env`, developer khởi động stack bằng một lệnh:

```bash
docker compose up --build
```

Frontend không được thêm vào Compose của T-005 vì backlog chỉ yêu cầu stack API, worker, PostgreSQL và Redis; việc này cũng tránh thay đổi frontend đã chốt.

## 7. Kiểm thử và CI

Một pytest smoke khởi tạo FastAPI app, gọi `GET /api/v1/health` và xác nhận HTTP 200 cùng payload. Test không mock hoặc kết nối database/Redis vì hợp đồng đang kiểm tra là liveness của API.

GitHub Actions chạy trên sự kiện `pull_request` với các bước:

1. cài Python 3.13 và dependencies development;
2. `ruff check`;
3. `black --check`;
4. `pytest`;
5. build backend Docker image.

Docker build là nghĩa của bước `build` đã chốt cho T-005; không tạo wheel/sdist artifact. Workflow không nhận secrets và Docker build không yêu cầu credential runtime.

Kiểm chứng tích hợp cuối gồm lint, format check, pytest, Docker build, `docker compose config`, API health qua stack thật và gửi task Celery healthcheck khi Docker runtime khả dụng.

## 8. Tài liệu và tiêu chí hoàn tất

`backend/README.md` mô tả:

- yêu cầu công cụ;
- cách tạo `.env`;
- chạy local API và worker;
- chạy migration;
- chạy stack bằng Compose;
- gọi API health và Celery healthcheck;
- chạy lint/test;
- lỗi khởi động thường gặp.

Root `README.md` chỉ bổ sung `backend/` trong cấu trúc repository và liên kết tới hướng dẫn backend.

T-005 hoàn tất khi stack backend khởi động được, migration rỗng được áp dụng, API health trả thành công, task Celery healthcheck có kết quả, CI PR thực thi đủ lint/test/Docker build, secrets không bị commit và không có schema domain nào được tạo.

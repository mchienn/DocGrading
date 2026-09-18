# 🚀 How to Run DocGrading App

## Quick Start (Automated)

### Option 1: Batch Script (Windows CMD)
```bash
D:\DocGrading\START_APP.bat
```

### Option 2: PowerShell Script
```powershell
D:\DocGrading\START_APP.ps1
```

Both scripts will:
1. ✅ Start Docker (PostgreSQL + Redis)
2. ✅ Start Backend (uvicorn on port 8000)
3. ✅ Start Frontend (Vite on port 5173+)
4. ✅ Open everything in separate terminals

---

## Manual Start (Step by Step)

### Prerequisites
- Docker Desktop running ✅
- Python 3.13+ with `uv` ✅
- Node.js with `pnpm` ✅

### Step 1: Start Database & Cache

Open **Terminal 1**:
```bash
cd D:\DocGrading
docker compose up -d postgres redis

# Verify
docker compose ps
```

Output should show:
```
NAME                    STATUS
docgrading-postgres-1   Up 5 seconds (healthy)
docgrading-redis-1      Up 5 seconds (healthy)
```

### Step 2: Start Backend Server

Open **Terminal 2**:
```bash
cd D:\DocGrading\backend

# Run migrations
uv run alembic upgrade head

# Start server
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Output should show:
```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete.
```

Verify with:
```bash
curl http://127.0.0.1:8000/api/v1/health
# Should return: {"status":"ok"}
```

### Step 3: Start Frontend Server

Open **Terminal 3**:
```bash
cd D:\DocGrading\frontend

# Start dev server
npx --yes pnpm@11.19.0 dev
```

Output should show:
```
  ➜  Local:   http://localhost:5173/
```

---

## ✅ Verify Everything is Running

### Check Services
```bash
# Backend health
curl http://127.0.0.1:8000/api/v1/health

# Database
docker compose ps

# Frontend (open in browser)
http://localhost:5173
```

### Login to Frontend
- **URL:** http://localhost:5173
- **Email:** `chat-smoke-teacher@example.test`
- **Password:** `ChatSmoke!2026`

---

## 🧪 Run Tests

### Test 1: Basic API Connectivity
```bash
cd D:\DocGrading\backend
uv run python "C:\Users\DELL\AppData\Local\Temp\claude\d--DocGrading\34f7678e-45da-4b39-a828-8b801ce2a34f\scratchpad\comprehensive_test.py"
```

### Test 2: Advanced Workflow (Create Resources)
```bash
cd D:\DocGrading\backend
uv run python "C:\Users\DELL\AppData\Local\Temp\claude\d--DocGrading\34f7678e-45da-4b39-a828-8b801ce2a34f\scratchpad\advanced_test.py"
```

### Test 3: Chatbot Smoke Test
```bash
cd D:\DocGrading\backend
uv run python "C:\Users\DELL\AppData\Local\Temp\claude\d--DocGrading\34f7678e-45da-4b39-a828-8b801ce2a34f\scratchpad\chat_smoke.py"
```

---

## 🛑 Stop Services

### Stop All Services
```bash
# Stop frontend (Ctrl+C in terminal)
# Stop backend (Ctrl+C in terminal)

# Stop Docker
docker compose down

# Stop Docker Desktop (optional)
```

### Stop Only Docker (Keep Backend/Frontend)
```bash
docker compose stop postgres redis
```

---

## 📊 Architecture

```
Frontend (React/TypeScript)
    ↓ API requests
    ↓ Vite dev server proxies to backend
    ↓
Backend (FastAPI/Python)
    ↓ SQL queries
    ↓
PostgreSQL Database
    ↓ Caching
    ↓
Redis Cache
```

---

## 🔍 Logs & Debugging

### View Backend Logs
- In Terminal 2 where backend is running
- Shows all API requests & errors

### View Frontend Logs
- In Terminal 3 where frontend is running
- Browser console: `F12` → Console tab

### View Database Logs
```bash
docker logs docgrading-postgres-1
```

### View Redis Logs
```bash
docker logs docgrading-redis-1
```

---

## ⚠️ Troubleshooting

### Problem: "Port 8000 already in use"
```bash
# Find process using port 8000
netstat -ano | findstr :8000

# Kill process (replace PID)
taskkill /PID <PID> /F

# Start backend again
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Problem: "Docker Desktop is not running"
- Open Docker Desktop application
- Wait for it to fully start
- Try again

### Problem: "pnpm command not found"
```bash
# Install via corepack
corepack prepare pnpm@11.19.0 --activate

# Or use npx
npx --yes pnpm@11.19.0 dev
```

### Problem: "ModuleNotFoundError: No module named 'app'"
```bash
# Install Python dependencies
cd D:\DocGrading\backend
uv sync
```

---

## 📚 Additional Resources

- **Backend Testing Guide:** `BACKEND_TESTING_GUIDE.md`
- **API Documentation:** Backend Swagger at `http://127.0.0.1:8000/docs`
- **Database Data:** PostgreSQL data persists in Docker volume

---

## ✨ Tips

- **Development:** Use live reload - changes to code auto-update
- **Frontend:** Open `http://localhost:5173` in multiple tabs to test
- **API Calls:** Use cURL or test scripts for backend-only testing
- **Database:** Data persists even after stopping Docker (unless using `docker compose down -v`)


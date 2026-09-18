@echo off
REM ============================================================================
REM DocGrading - Complete App Startup Script
REM ============================================================================
setlocal enabledelayedexpansion

cd /d "D:\DocGrading"

echo.
echo ============================================================================
echo DOCGRADING APP STARTUP
echo ============================================================================
echo.

REM Check if Docker is running
docker ps >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker is not running. Please start Docker Desktop first.
    pause
    exit /b 1
)

REM ============================================================================
echo [1/4] Starting Database ^& Cache (Docker)...
echo ============================================================================
docker compose up -d postgres redis
timeout /t 5 /nobreak

REM ============================================================================
echo.
echo [2/4] Starting Backend Server...
echo ============================================================================
echo Opening new terminal for backend...
start "DocGrading Backend" cmd /k "cd /d D:\DocGrading\backend && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000"
timeout /t 3 /nobreak

REM ============================================================================
echo.
echo [3/4] Starting Frontend Dev Server...
echo ============================================================================
echo Opening new terminal for frontend...
start "DocGrading Frontend" cmd /k "cd /d D:\DocGrading\frontend && npx --yes pnpm@11.19.0 dev"
timeout /t 3 /nobreak

REM ============================================================================
echo.
echo ============================================================================
echo ✅ APP STARTED SUCCESSFULLY
echo ============================================================================
echo.
echo Access the application:
echo   Frontend:  http://localhost:5173 (or next available port)
echo   Backend:   http://127.0.0.1:8000/api/v1/health
echo.
echo Login credentials:
echo   Email:     chat-smoke-teacher@example.test
echo   Password:  ChatSmoke!2026
echo.
echo Open another terminal to run tests:
echo   cd D:\DocGrading\backend
echo   uv run python {test_script}.py
echo.
echo Press any key to continue...
pause

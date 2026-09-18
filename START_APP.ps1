# DocGrading - Complete App Startup Script (PowerShell)

$ErrorActionPreference = "Continue"

Write-Host "`n"
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host "DOCGRADING APP STARTUP" -ForegroundColor Cyan
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host ""

# Check Docker
try {
    docker ps >$null 2>&1
} catch {
    Write-Host "[ERROR] Docker is not running. Please start Docker Desktop first." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# ============================================================================
Set-Location "D:\DocGrading"

Write-Host "[1/4] Starting Database & Cache (Docker)..." -ForegroundColor Yellow
Write-Host "============================================================================" -ForegroundColor Yellow
docker compose up -d postgres redis
Start-Sleep -Seconds 5

# ============================================================================
Write-Host ""
Write-Host "[2/4] Starting Backend Server..." -ForegroundColor Yellow
Write-Host "============================================================================" -ForegroundColor Yellow
Write-Host "Opening new terminal for backend..."
Start-Process powershell -ArgumentList @"
cd "D:\DocGrading\backend"
Write-Host "Running: uv run uvicorn app.main:app --host 127.0.0.1 --port 8000" -ForegroundColor Green
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
"@
Start-Sleep -Seconds 3

# ============================================================================
Write-Host ""
Write-Host "[3/4] Starting Frontend Dev Server..." -ForegroundColor Yellow
Write-Host "============================================================================" -ForegroundColor Yellow
Write-Host "Opening new terminal for frontend..."
Start-Process powershell -ArgumentList @"
cd "D:\DocGrading\frontend"
Write-Host "Running: npx --yes pnpm@11.19.0 dev" -ForegroundColor Green
npx --yes pnpm@11.19.0 dev
"@
Start-Sleep -Seconds 3

# ============================================================================
Write-Host ""
Write-Host "============================================================================" -ForegroundColor Green
Write-Host "✅ APP STARTED SUCCESSFULLY" -ForegroundColor Green
Write-Host "============================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Access the application:" -ForegroundColor Cyan
Write-Host "  Frontend:  http://localhost:5173 (or next available port)" -ForegroundColor White
Write-Host "  Backend:   http://127.0.0.1:8000/api/v1/health" -ForegroundColor White
Write-Host ""
Write-Host "Login credentials:" -ForegroundColor Cyan
Write-Host "  Email:     chat-smoke-teacher@example.test" -ForegroundColor White
Write-Host "  Password:  ChatSmoke!2026" -ForegroundColor White
Write-Host ""
Write-Host "Run tests in new terminal:" -ForegroundColor Cyan
Write-Host "  cd D:\DocGrading\backend" -ForegroundColor White
Write-Host "  uv run python {test_script}.py" -ForegroundColor White
Write-Host ""
Read-Host "Press Enter to continue monitoring"

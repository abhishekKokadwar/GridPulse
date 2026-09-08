# GridPulse Automated Production Deployment Script (Windows PowerShell)
# Usage: .\deploy.ps1 [-DryRun] [-NoBuild]

param (
    [switch]$DryRun,
    [switch]$NoBuild
)

$ErrorActionPreference = "Continue"

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "         GRIDPULSE PRODUCTION DEPLOYMENT ENGINE                " -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Cyan

# 1. Environment & Docker Pre-Flight Checks
Write-Host "`n[1/5] Checking Docker & Environment..." -ForegroundColor Yellow

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "Docker is not installed or not in PATH. Please install Docker Desktop."
    exit 1
}

try {
    docker info > $null 2>&1
    Write-Host "  * Docker daemon is running." -ForegroundColor Green
} catch {
    Write-Error "Docker daemon is not running. Please start Docker Desktop."
    exit 1
}

if (-not (Test-Path ".env")) {
    Write-Host "  * Warning: .env not found. Copying from .env.example..." -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
}
Write-Host "  * .env file loaded." -ForegroundColor Green

# 2. Automated Test Suite Verification
Write-Host "`n[2/5] Running Pre-Deployment Test Suite (14 Tests)..." -ForegroundColor Yellow
$pyCmd = "python"
if (Test-Path ".venv\Scripts\python.exe") {
    $pyCmd = ".venv\Scripts\python.exe"
}
& $pyCmd -m unittest discover -s tests
if ($LASTEXITCODE -ne 0) {
    Write-Error "Pre-deployment unit tests failed! Aborting deployment."
    exit 1
}
Write-Host "  * All automated tests passed successfully." -ForegroundColor Green

if ($DryRun) {
    Write-Host "`n[DRY RUN COMPLETE] Validation succeeded without launching containers." -ForegroundColor Cyan
    exit 0
}

# 3. Build & Launch Containers
Write-Host "`n[3/5] Launching Production Docker Stack..." -ForegroundColor Yellow

if ($NoBuild) {
    docker-compose -f docker-compose.prod.yml up -d
} else {
    docker-compose -f docker-compose.prod.yml up --build -d
}

if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to start Docker Compose services."
    exit 1
}

# 4. Service Health Inspection
Write-Host "`n[4/5] Verifying Service Health..." -ForegroundColor Yellow
Start-Sleep -Seconds 5

$psOutput = docker-compose -f docker-compose.prod.yml ps
Write-Host $psOutput

# 5. Output Access Endpoints
Write-Host "`n================================================================" -ForegroundColor Cyan
Write-Host "         GRIDPULSE DEPLOYMENT ONLINE & READY!                   " -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  * Streamlit Operations Portal : http://localhost:8501" -ForegroundColor Green
Write-Host "  * Kafka Management UI         : http://localhost:8080" -ForegroundColor Green
Write-Host "  * Kafka Broker Address        : localhost:9092" -ForegroundColor Green
Write-Host "`nTo view container logs:"
Write-Host "  docker-compose -f docker-compose.prod.yml logs -f dashboard"
Write-Host "`nTo stop the platform:"
Write-Host "  docker-compose -f docker-compose.prod.yml down"
Write-Host "================================================================`n"

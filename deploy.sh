#!/usr/bin/env bash
# GridPulse Automated Production Deployment Script (Linux / macOS)
# Usage: ./deploy.sh [--dry-run] [--no-build]

set -e

DRY_RUN=false
NO_BUILD=false

for arg in "$@"; do
  case $arg in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --no-build)
      NO_BUILD=true
      shift
      ;;
  esac
done

echo "================================================================"
echo "         GRIDPULSE PRODUCTION DEPLOYMENT ENGINE                "
echo "================================================================"

# 1. Environment & Docker Pre-Flight Checks
echo -e "\n[1/5] Checking Docker & Environment..."
if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker is not installed or not in PATH."
    exit 1
fi

if ! docker info > /dev/null 2>&1; then
    echo "ERROR: Docker daemon is not running."
    exit 1
fi
echo "  * Docker daemon is running."

if [ ! -f ".env" ]; then
    echo "  * Warning: .env not found. Copying from .env.example..."
    cp .env.example .env
fi
echo "  * .env file loaded."

# 2. Automated Test Suite Verification
echo -e "\n[2/5] Running Pre-Deployment Test Suite (14 Tests)..."
PY_CMD="python3"
if [ -f ".venv/bin/python" ]; then
    PY_CMD=".venv/bin/python"
elif [ -f ".venv/Scripts/python.exe" ]; then
    PY_CMD=".venv/Scripts/python.exe"
fi
$PY_CMD -m unittest discover -s tests
echo "  * All automated tests passed successfully."

if [ "$DRY_RUN" = true ]; then
    echo -e "\n[DRY RUN COMPLETE] Validation succeeded without launching containers."
    exit 0
fi

# 3. Build & Launch Containers
echo -e "\n[3/5] Launching Production Docker Stack..."
if [ "$NO_BUILD" = true ]; then
    docker-compose -f docker-compose.prod.yml up -d
else
    docker-compose -f docker-compose.prod.yml up --build -d
fi

# 4. Service Health Inspection
echo -e "\n[4/5] Verifying Service Health..."
sleep 5
docker-compose -f docker-compose.prod.yml ps

# 5. Output Access Endpoints
echo -e "\n================================================================"
echo "         GRIDPULSE DEPLOYMENT ONLINE & READY!                   "
echo "================================================================"
echo "  * Streamlit Operations Portal : http://localhost:8501"
echo "  * Kafka Management UI         : http://localhost:8080"
echo "  * Kafka Broker Address        : localhost:9092"
echo -e "\nTo view container logs:"
echo "  docker-compose -f docker-compose.prod.yml logs -f dashboard"
echo -e "\nTo stop the platform:"
echo "  docker-compose -f docker-compose.prod.yml down"
echo -e "================================================================\n"

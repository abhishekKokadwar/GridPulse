# Multi-stage lightweight production Dockerfile for GridPulse Streamlit Operations Portal
FROM python:3.11-slim AS base

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Create non-root system user for security
RUN groupadd -r gridpulse && useradd -r -g gridpulse -d /app -s /sbin/nologin gridpulse

# Copy application source code
COPY . /app

# Ensure correct permissions for data and cache directories
RUN chown -R gridpulse:gridpulse /app

# Switch to non-root user
USER gridpulse

# Expose Streamlit dashboard port
EXPOSE 8501

# Healthcheck to verify Streamlit webserver is responding
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl --fail http://localhost:8501/_stcore/health || exit 1

# Launch Streamlit application
ENTRYPOINT ["streamlit", "run", "dashboard/app.py"]

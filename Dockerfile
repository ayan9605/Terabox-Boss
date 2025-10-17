# =============================
# Stage 1: Builder
# =============================
FROM python:3.10-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# =============================
# Stage 2: Runtime
# =============================
FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8000

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Set working directory
WORKDIR /app

# ✅ Create non-root user BEFORE copying files
RUN useradd -m -u 1000 botuser

# Copy application code
COPY . .

# ✅ CRITICAL: Give write permissions to app directory for session files
RUN chown -R botuser:botuser /app && \
    chmod -R 755 /app

# ✅ Create sessions directory with proper permissions
RUN mkdir -p /app/sessions && \
    chown -R botuser:botuser /app/sessions && \
    chmod -R 777 /app/sessions

# Switch to non-root user
USER botuser

# Expose port
EXPOSE ${PORT}

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:${PORT}/health', timeout=5)" || exit 1

# Run with uvicorn
CMD ["sh", "-c", "uvicorn bot:app --host 0.0.0.0 --port ${PORT} --workers 1 --log-level info"]

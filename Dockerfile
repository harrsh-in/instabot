# Multi-stage build for lightweight production image

# Stage 1: Builder
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies (for cryptography)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: Runtime
FROM python:3.11-slim AS runtime

WORKDIR /app

# Create non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Copy installed dependencies from builder
COPY --from=builder /root/.local /home/appuser/.local

# Copy application code
COPY app.py models.py meta_service.py auth.py webhooks.py token_store.py legal.py wsgi.py ./

# Create data directory and set permissions
RUN mkdir -p data && chown -R appuser:appuser /app && chmod 755 /app/data

# Switch to non-root user
USER appuser

# Set environment variables
ENV PATH=/home/appuser/.local/bin:$PATH
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV FLASK_ENV=production

# Expose port 8000
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health')" || exit 1

# Run with gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "4", "--timeout", "30", "--access-logfile", "-", "--error-logfile", "-", "wsgi:application"]

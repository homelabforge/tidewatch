# Dockerfile for TideWatch - Intelligent Docker Container Update Manager
# Multi-stage production build with frontend built from source

# Stage 1: Build frontend
FROM node:25-alpine AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# Stage 2: Build backend
FROM python:3.14-slim AS backend-builder

WORKDIR /app

# Upgrade pip to latest version and clean up old metadata
RUN pip install --no-cache-dir --upgrade pip && \
    rm -rf /usr/local/lib/python3.14/site-packages/pip-25.2.dist-info 2>/dev/null || true

# Copy backend code and install from pyproject.toml
COPY backend ./
RUN pip install --no-cache-dir .

# Stage 3: Production image
FROM python:3.14-slim

# Build arguments for metadata
ARG BUILD_DATE

# OCI-standard labels
LABEL org.opencontainers.image.authors="HomeLabForge"
LABEL org.opencontainers.image.title="TideWatch"
LABEL org.opencontainers.image.url="https://www.homelabforge.io"
LABEL org.opencontainers.image.description="Intelligent Docker container update management and monitoring platform"

WORKDIR /app

# Install runtime dependencies (Docker CLI for compose operations)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        gnupg \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && chmod a+r /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*

# Copy Python dependencies from builder
COPY --from=backend-builder /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY --from=backend-builder /usr/local/bin /usr/local/bin

# Copy application code
COPY --from=backend-builder /app/app /app/app
COPY --from=backend-builder /app/pyproject.toml ./

# Copy frontend build
COPY --from=frontend-builder /app/frontend/dist ./static

# Create data directory for SQLite database
RUN mkdir -p /data

# Create non-root user for security
RUN useradd --uid 1000 --user-group --system --create-home --no-log-init tidewatch && \
    chown -R tidewatch:tidewatch /app /data

# Switch to non-root user
USER tidewatch

# Expose port
EXPOSE 8788

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    LOG_LEVEL=INFO \
    DATABASE_URL=sqlite+aiosqlite:////data/tidewatch.db

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8788/health || exit 1

# Run application with Granian (Rust-based ASGI server)
# Using 1 worker due to stateful background services (APScheduler)
# Granian auto-configures threads for optimal performance
CMD ["granian", "--interface", "asgi", "--host", "0.0.0.0", "--port", "8788", "--workers", "1", "app.main:app"]

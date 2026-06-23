# ── Stage 1: build deps ────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app
COPY app/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: runtime ────────────────────────────────────────────────────────
FROM python:3.11-slim

# Non-root user — least privilege inside the container
RUN useradd -m -u 1001 appuser

WORKDIR /app
COPY --from=builder /install /usr/local
COPY app/ .

USER appuser

# All config via env vars — no secrets baked in
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 5000

# gunicorn for production; 4 workers, bind on all interfaces
CMD ["gunicorn", "--workers", "4", "--bind", "0.0.0.0:5000", "--timeout", "30", "app:app"]

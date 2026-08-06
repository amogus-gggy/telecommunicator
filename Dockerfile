FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app alembic.ini .
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app app ./app

# Persistent data locations (owned by the non-root user so named volumes work).
RUN mkdir -p /data /app/uploads && chown -R app:app /data /app/uploads

USER app

EXPOSE 8000

# Alembic migrations run automatically on startup (see app/main.py lifespan).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

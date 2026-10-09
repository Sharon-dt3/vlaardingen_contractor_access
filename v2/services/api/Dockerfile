FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/services/api

WORKDIR /app/services/api

COPY services/api/requirements.lock ./requirements.lock
RUN pip install --no-cache-dir --requirement requirements.lock

COPY services/api/ /app/services/api/
COPY database/ /app/database/

RUN groupadd --system renewi \
    && useradd --system --gid renewi --home-dir /app renewi \
    && mkdir -p /var/lib/renewi/evidence \
    && chown -R renewi:renewi /app /var/lib/renewi

USER renewi

EXPOSE 8000

CMD ["sh", "-c", "python -m app.commands migrate && exec uvicorn app.main:app --host 0.0.0.0 --port ${BACKEND_PORT:-8000}"]

FROM python:3.12.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY alembic.ini ./
COPY alembic ./alembic
COPY db ./db
COPY docker ./docker
COPY rfid_ingestion ./rfid_ingestion
COPY rfid_inference ./rfid_inference
COPY rfid_movement ./rfid_movement
COPY rfid_location ./rfid_location

RUN chmod +x /app/docker/require-database-url.sh \
    && mkdir -p /app/data \
    && chown -R app:app /app

USER app

CMD ["python", "-m", "rfid_ingestion"]

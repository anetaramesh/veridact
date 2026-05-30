FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir ".[dev]"

COPY . .

ENV PYTHONPATH=/app
ENV AUDIT_DB_PATH=/app/data/audit.db

RUN mkdir -p /app/data

EXPOSE 8000

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

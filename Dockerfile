FROM node:20-slim AS dashboard-builder
WORKDIR /build
COPY dashboard/package*.json ./
RUN npm ci
COPY dashboard/ ./
RUN npm run build

FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir ".[dev]"

COPY . .

# Copy the built dashboard into the expected location
COPY --from=dashboard-builder /build/dist ./dashboard/dist

ENV PYTHONPATH=/app
ENV AUDIT_DB_PATH=/app/data/audit.db

RUN mkdir -p /app/data

EXPOSE 8000

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    antiword catdoc build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY enterprise_rag/ enterprise_rag/
COPY scripts/ scripts/

RUN pip install --no-cache-dir .

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    antiword catdoc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/uvicorn /usr/local/bin/uvicorn
COPY --from=builder /app .

EXPOSE 8080

CMD ["uvicorn", "enterprise_rag.api:app", "--host", "0.0.0.0", "--port", "8080"]

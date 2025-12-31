# Enterprise RAG (Postgres + pgvector, optional Neo4j)

## 1) Services starten

docker compose up -d

2) Python Setup

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

3) DB initialisieren

python scripts/init_db.py

4) Ordner ingestieren (PDF/DOCX/XLSX/HTML/ASPX)

python scripts/ingest_folder.py --folder /abs/path/to/data --recursive

5) Embeddings für Windows schreiben (Batch)

python scripts/embed_windows.py --batch-size 64

6) Query testen

python scripts/query.py --q "SSO Integration ISO 27001"

7) API starten (optional)

uvicorn app.api:app --host 0.0.0.0 --port 8080

Endpoints

    POST /ingest {"path": "/abs/file.pdf"}

    POST /search {"query": "...", "k": 8}


---

enterprise_rag/
├── README.md
├── requirements.txt
├── docker-compose.yml
├── .env.example
├── sql/
│   └── schema.sql
├── app/
│   ├── __init__.py
│   ├── api.py
│   ├── config.py
│   ├── log.py
│   ├── db.py
│   ├── neo4j_amp.py
│   ├── llm.py
│   ├── models.py
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── extractors.py
│   │   ├── normalize.py
│   │   ├── segment.py
│   │   └── ingest.py
│   ├── retrieval/
│   │   ├── __init__.py
│   │   ├── query_plan.py
│   │   ├── postgres_retrieval.py
│   │   ├── rerank.py
│   │   └── hybrid.py
│   └── reasoning/
│       ├── __init__.py
│       ├── pack.py
│       └── evidence.py
└── scripts/
    ├── init_db.py
    ├── ingest_folder.py
    ├── embed_windows.py
    └── query.py

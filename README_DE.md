[English](README.md) · [Deutsch](README_DE.md)

# Enterprise RAG

[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com/)
[![PostgreSQL 16](https://img.shields.io/badge/PostgreSQL-16-336791.svg)](https://www.postgresql.org/)
[![Neo4j 5](https://img.shields.io/badge/Neo4j-5-008CC1.svg)](https://neo4j.com/)

System zur Dokumentensuche und Fragenbeantwortung mit Hybridsuche, zitationsklaren Antworten und dokumentübergreifender Intelligenz.

## Funktionen

- **Hybridsuche** — BM25-Volltextsuche + Vektorähnlichkeit mit Cross-Encoder-Reranking
- **Zitationsklare Antworten** — Inline-Referenzen `[1]`, `[2]` mit Konfidenz-Scoring
- **Dokumentübergreifende Intelligenz** — Zitations-Graph-Traversierung via Neo4j für verlinkte Dokumente
- **Multi-Format-Ingestion** — PDF, DOCX, XLSX, HTML/ASPX mit automatischer Textextraktion
- **Streaming-API** — Server-Sent Events (SSE) für Echtzeit-Antwort-Streaming
- **Dynamische Kontextanpassung** — Passt das Kontextfenster automatisch an die Abfragekomplexität an
- **Kategorie-Filterung** — Dokumente nach Kategorie organisieren und filtern
- **Dokument-Versionierung** — Deduplizierung und Versionsverfolgung mit Archiv-Unterstützung
- **Modell-Profile** — Zwischen Instruct- (schnell) und Reasoning- (gründlich) Modus wechseln
- **Web-Crawler** — Dokumente von Webseiten extrahieren und ingesten mit musterbasiertem URL-Crawling

## Architektur

```
┌─ INGESTION ──────────────────────┐    ┌─ RETRIEVAL ──────────────────────┐
│                                  │    │                                  │
│  Datei (PDF/DOCX/XLSX/HTML)      │    │  Abfrage                         │
│   │                              │    │   │                              │
│   ├─ Textextraktion              │    │   ├─ Abfrageplanung (LLM)        │
│   ├─ Normalisierung              │    │   │   └─ BM25-Term-Extraktion    │
│   ├─ Gleitfenster-Segmentierung  │    │   │                              │
│   │   ├─ Fenster (mehrseitig)    │    │   ├─ Kandidaten-Generierung      │
│   │   └─ Anker (Absätze,         │    │   │   ├─ BM25-Volltextsuche      │
│   │       Tabellen, Listen)      │    │   │   └─ Vektorähnlichkeit       │
│   └─ Zitationsextraktion         │    │   │                              │
│       (URLs, ISO-Refs, Gesetze)  │    │   ├─ Hybridmischung (55/45)      │
│                                  │    │   ├─ Cross-Encoder-Reranking     │
│   ▼                              │    │   ├─ Pro-Dokument-Diversifikation│
│  PostgreSQL + Neo4j              │    │   └─ Zitations-Graph-Erweiterung │
│   ├─ Dokumente, Seiten, Fenster  │    │                                  │
│   ├─ Anker, Zitationen           │    └──────────────────────────────────┘
│   ├─ HNSW-Vektorindex            │
│   ├─ tsvector-Volltextindex      │    ┌─ REASONING ──────────────────────┐
│   └─ CITES-Graph-Kanten          │    │                                  │
│                                  │    │  Kontext-Packing                 │
└──────────────────────────────────┘    │   ├─ Fenster + Anker             │
                                        │   └─ Zitierte Dokumente (Neo4j)  │
                                        │                                  │
                                        │  Beweisextraktion (LLM)          │
                                        │   ├─ Antwort mit [1],[2]-Refs    │
                                        │   ├─ Konfidenz-Scoring           │
                                        │   └─ Quellenzuordnung            │
                                        │                                  │
                                        │  Streaming-Antwort (SSE)         │
                                        │   ├─ Quellen → Denken → Antwort  │
                                        │   └─ Instruct- / Reasoning-Modus │
                                        │                                  │
                                        └──────────────────────────────────┘
```

## Tech-Stack

| Komponente | Technologie |
|---|---|
| Sprache | Python 3.12 |
| Web-Framework | FastAPI + Uvicorn |
| Datenbank | PostgreSQL 16 + pgvector (HNSW-Indizes) |
| Graph-Datenbank | Neo4j 5 (Zitationsketten) |
| Cache / Queue | Redis 7 |
| LLM / Embeddings | Ollama (OpenAI-kompatible API) |
| Reranker | TEI mit BAAI/bge-reranker-v2-m3 |
| Observability | structlog + OpenTelemetry + Jaeger |
| Paketmanager | uv |

## Schnellstart

### Voraussetzungen

- Docker & Docker Compose
- Python 3.12+
- [uv](https://docs.astral.sh/uv/) Paketmanager
- Laufende Ollama-Instanz mit gewählten Modellen

### Setup

```bash
# Infrastruktur starten (PostgreSQL, Neo4j, Redis, TEI-Reranker, Jaeger)
docker compose up -d

# Python-Abhängigkeiten installieren
uv sync

# Umgebung konfigurieren
cp .env.example .env
# .env mit LLM/Embedding-Endpunkten anpassen

# Datenbankschema initialisieren
uv run python scripts/init_db.py
```

### Dokumente ingesten

```bash
# Dokumente aus einem Ordner ingesten
uv run python scripts/ingest_folder.py --folder /pfad/zu/docs --recursive

# Embeddings nachfüllen
uv run python scripts/embed_windows.py --batch-size 64

# Von einer Webseite crawlen und ingesten
uv run python scripts/crawl_url.py https://example.com/docs --depth 1
```

### API-Server starten

```bash
uv run uvicorn enterprise_rag.api:app --host 0.0.0.0 --port 8080
```

### Abfragen

```bash
# CLI-Abfrage
uv run python scripts/query.py --q "Was ist die aktuelle Richtlinie?" --k 8

# API-Anfrage
curl -X POST http://localhost:8080/search \
  -H "Content-Type: application/json" \
  -d '{"query": "Was ist die aktuelle Richtlinie?", "k": 8}'
```

## CLI-Skripte

### init_db.py

Datenbankschema aus `sql/schema.sql` initialisieren. Keine Parameter.

```bash
uv run python scripts/init_db.py
```

### ingest_folder.py

Dokumente aus dem Dateisystem in Masse ingesten.

| Flag | Standard | Beschreibung |
|---|---|---|
| `--folder` | *erforderlich* | Zu ingestierender Ordner |
| `--recursive` | `true` | Unterordner einschließen |
| `--type` | *alle* | Nur bestimmten Typ ingesten (`pdf`, `docx`, `xlsx`, `html`) |
| `--force` | `false` | Auch bei unverändertem Inhalt neu ingesten |

```bash
uv run python scripts/ingest_folder.py --folder /data/docs --recursive --type pdf
```

### embed_windows.py

Embeddings für alle nicht-eingebetteten Fenster nachfüllen.

| Flag | Standard | Beschreibung |
|---|---|---|
| `--batch-size` | `64` | Batch-Größe für Embedding |
| `--model` | *Env-Standard* | Zu nutzendes Embedding-Modell-Profil |
| `--all` | `false` | Alle Fenster neu einbetten, nicht nur fehlende |
| `--workers` | `4` | Anzahl paralleler Worker |

```bash
uv run python scripts/embed_windows.py --batch-size 128 --workers 8
```

### query.py

CLI-Abfrage-Interface zum Testen des Retrievals.

| Flag | Standard | Beschreibung |
|---|---|---|
| `--q` | *erforderlich* | Abfragetext |
| `--k` | `8` | Anzahl anzuzeigender Ergebnisse |
| `--timing` | `false` | Zeitaufschlüsselung anzeigen |

```bash
uv run python scripts/query.py --q "DSGVO Anforderungen" --k 5 --timing
```

### crawl_url.py

Web-Crawler zum Extrahieren und Ingesten von Dokumenten aus URLs.

| Flag | Standard | Beschreibung |
|---|---|---|
| `urls` | *positional* | Zu crawlende URLs nach Dokument-Links |
| `-f`, `--file` | — | URLs aus Textdatei lesen (eine pro Zeile) |
| `--dry-run` | `false` | Gefundene Links anzeigen ohne Herunterladen |
| `--download-dir` | *temp dir* | Verzeichnis zum Speichern heruntergeladener Dateien |
| `-q`, `--quiet` | `false` | Nur Zusammenfassung anzeigen |
| `--follow-pages` | `false` | HTML-Seiten-Links rekursiv folgen (BFS) |
| `--depth` | — | Maximale BFS-Tiefe (erforderlich mit `--follow-pages`) |
| `--max-pages` | *Env-Standard* | Max. Seiten beim rekursiven Crawlen |
| `--pattern` | — | URL-Muster mit `{}`-Platzhalter |
| `--start` | `1` | Erste Zahl im Muster-Modus |
| `--end` | `9999` | Letzte Zahl im Muster-Modus |
| `--pad-width` | `4` | Nullauffüllungsbreite für Muster-Zahlen |
| `--not-found-text` | — | Teilstring, der „nicht gefunden" anzeigt (erforderlich mit `--pattern`) |
| `--max-gaps` | `10` | Aufeinanderfolgende Fehltreffer vor Stopp des Muster-Crawlings |
| `--mark-unseen` | `false` | Nicht gefundene Dokumente nach Crawl als verwaist markieren |

```bash
# Rekursives Crawlen
uv run python scripts/crawl_url.py https://example.com/docs --follow-pages --depth 2

# Musterbasiertes Crawlen
uv run python scripts/crawl_url.py --pattern "https://example.com/info?id={}" \
  --start 1 --end 500 --pad-width 1 --not-found-text "nicht gefunden" --dry-run
```

### evaluate.py

Evaluierungs-Suite gegen Testfälle ausführen.

| Flag | Standard | Beschreibung |
|---|---|---|
| `--test-file` | — | Pfad zur Testfälle-JSON-Datei |
| `--output` | — | Pfad zum Speichern der Ergebnisse-JSON |
| `--create-sample` | `false` | Beispiel-Testfälle-Datei erstellen |
| `-v`, `--verbose` | `false` | Fortschritt während Evaluierung anzeigen |

```bash
uv run python scripts/evaluate.py --test-file tests/eval_cases.json --verbose --output results.json
```

### worker.py

Redis-Queue-Worker für asynchrone Ingestions-Aufgaben. Akzeptiert Queue-Namen als Positionsargumente.

```bash
uv run python scripts/worker.py                     # Alle Queues (Standard + Embeddings)
uv run python scripts/worker.py default              # Nur Standard-Queue
uv run python scripts/worker.py embeddings           # Nur Embeddings-Queue
```

## API-Endpunkte

| Methode | Pfad | Beschreibung |
|---|---|---|
| `GET` | `/health` | Liveness-Check |
| `GET` | `/health/ready` | Readiness-Check (PostgreSQL, Redis, Neo4j) |
| `POST` | `/ingest` | Einzelnes Dokument ingesten |
| `GET` | `/ingest/{job_id}` | Asynchronen Ingestions-Job-Status prüfen |
| `POST` | `/crawl` | Webseite nach Dokument-Links crawlen |
| `POST` | `/crawl/stream` | Streaming-Crawl-Fortschritt (SSE) |
| `POST` | `/search` | Suche mit strukturierter JSON-Antwort |
| `POST` | `/search/stream` | Suche mit Streaming-SSE-Antwort |
| `POST` | `/feedback` | Benutzerfeedback übermitteln |

### Such-Anfrage

```json
{
  "query": "Was ist die aktuelle Richtlinie?",
  "k": 8,
  "categories": ["security"],
  "llmModel": "instruct",
  "embeddingModel": "qwen"
}
```

### Streaming-Antwort (SSE)

```
event: meta
data: {"complexity": "simple", "hit_count": 42}

event: sources
data: [{"title": "Richtlinie 2024", "page_start": 3, ...}]

event: chunk
data: {"text": "Die aktuelle Richtlinie besagt..."}

event: done
data: {}
```

## Konfiguration

Die Konfiguration erfolgt über Umgebungsvariablen. `.env.example` enthält alle Optionen.

### Wichtige Einstellungen

| Variable | Standard | Beschreibung |
|---|---|---|
| `PG_DSN` | `localhost:5432` | PostgreSQL-Verbindungsstring |
| `LLM_MODEL` | `qwen3-32b-instruct` | Primäres LLM-Modell |
| `LLM_CONTEXT_LENGTH` | `16000` | LLM-Kontextfenstergröße |
| `EMBED_MODEL` | `qwen3-embedding-8b` | Embedding-Modell |
| `EMBED_DIM` | `4096` | Embedding-Dimensionen |
| `RERANK_ENABLED` | `true` | Cross-Encoder-Reranking aktivieren |
| `CANDIDATES_BM25` | `120` | BM25-Kandidaten-Pool-Größe |
| `CANDIDATES_VEC` | `120` | Vektor-Kandidaten-Pool-Größe |
| `RERANK_KEEP` | `18` | Nach Reranking behaltene Ergebnisse |
| `WINDOW_PAGES` | `2` | Seiten pro Gleitfenster |
| `WINDOW_STRIDE` | `1` | Fenster-Gleitschrittweite |
| `DYNAMIC_CONTEXT` | `true` | Dynamische Kontextanpassung |

### Modell-Profile

`MODEL_PROFILE` setzen für Voreinstellungen:

| Profil | Kontext | Max. Tokens | Anwendungsfall |
|---|---|---|---|
| `small` | 8K | 300 | Schnelle Antworten |
| `medium` | 16K | 500 | Ausgewogen (Standard) |
| `large` | 32K | 800 | Umfassende Antworten |

## Projektstruktur

```
├── enterprise_rag/
│   ├── api.py                     # FastAPI-Endpunkte
│   ├── config.py                  # Einstellungen und Modell-Profile
│   ├── models.py                  # Gemeinsame Datenmodelle
│   ├── db.py                      # PostgreSQL-Verbindungspool
│   ├── llm.py                     # LLM / Embedding / Reranker-Clients
│   ├── cache.py                   # Redis-Caching
│   ├── neo4j_amp.py               # Neo4j-Graph-Operationen
│   ├── log.py                     # Strukturiertes Logging
│   ├── telemetry.py               # OpenTelemetry-Tracing
│   ├── ingestion/
│   │   ├── extractors.py          # PDF/DOCX/XLSX/HTML-Extraktion
│   │   ├── normalize.py           # Textbereinigung
│   │   ├── segment.py             # Gleitfenster-Chunking
│   │   ├── citations.py           # Referenzextraktion
│   │   ├── versioning.py          # Dokument-Deduplizierung
│   │   ├── crawler.py             # Web-Crawler
│   │   └── ingest.py              # Ingestions-Orchestrierung
│   ├── retrieval/
│   │   ├── hybrid.py              # Such-Orchestrierung
│   │   ├── query_plan.py          # LLM-Abfrage-Umschreibung
│   │   ├── postgres_retrieval.py  # BM25 + Vektorsuche
│   │   ├── rerank.py              # Cross-Encoder-Reranking
│   │   ├── citation_expand.py     # Zitations-Graph-Traversierung
│   │   └── complexity.py          # Abfragekomplexitätsanalyse
│   └── reasoning/
│       ├── pack.py                # Kontext-Packing
│       └── evidence.py            # Antworterzeugung
├── scripts/                       # CLI-Werkzeuge (siehe CLI-Skripte)
├── sql/
│   └── schema.sql                 # Datenbankschema
├── tests/                         # Testsuite
├── docker-compose.yml             # Infrastruktur-Services
├── pyproject.toml                 # Abhängigkeiten
└── .env.example                   # Konfigurationsvorlage
```

## Entwicklung

```bash
# Mit Dev-Abhängigkeiten installieren
uv sync --extra dev

# Code-Formatierung
black --line-length 100 .

# Linting
ruff check .

# Typprüfung
mypy .

# Tests ausführen
pytest

# Einzelnen Test ausführen
pytest tests/test_specific.py::test_function
```

### Optionale Systemabhängigkeiten

Für Legacy-`.doc`-Datei-Unterstützung:

```bash
sudo apt install antiword    # Empfohlen
# oder
sudo apt install catdoc      # Alternative
```

## Autor

HN-Tran — <https://github.com/HN-Tran>

## Lizenz

Apache-2.0 — siehe [`LICENSE`](LICENSE).

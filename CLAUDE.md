# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FastAPI backend for an AI-powered Investor Intelligence Platform: ingests annual reports (PDF), extracts structured financial KPIs via a RAG pipeline (Azure AI Search + Azure OpenAI/GPT-5), persists them to Azure PostgreSQL, and serves a server-rendered dashboard + RAG chatbot. See `Architecture.md` for the full logical/physical architecture diagrams and `README.md` for feature list.

## Commands

### Local setup and run

```bash
uv venv
.venv\Scripts\activate          # Windows; `source .venv/bin/activate` on macOS/Linux
uv pip install -r requirements.txt
# create .env with AZURE_OPENAI_*, AZURE_SEARCH_*, POSTGRES_* (see database/postgres_sql.py and llm/azure_openai.py for the exact keys read)
python app.py                   # serves on http://localhost:8000
```

There is no automated test suite and no lint config in this repo. The closest thing to running a single unit is executing a pipeline module directly — most have a `if __name__ == "__main__"` smoke-test block that exercises just that stage against live Azure services, e.g.:

```bash
python -m ingestion.pdf_to_markdown      # converts data/raw_pdfs/*.pdf -> data/markdown/
python -m ingestion.semantic_chunker     # chunks one hardcoded markdown file
python -m ingestion.ingest_documents     # full ingest of data/raw_pdfs/
python -m rag.kpi_extractor_rag          # runs KPI extraction for a hardcoded company/year
python -m database.create_table          # creates DB + financial_metrics table
```

### Docker

```bash
docker build -t invint .
docker run -p 8000:8000 invint          # note: .env is NOT baked into the image (.dockerignore excludes it) — pass config separately, e.g. --env-file .env
```

### Azure AKS deployment

Two parallel deployment paths exist and are **not kept in sync**:

- **`deployment-Document.md`** — the manual, step-by-step runbook (imperative `kubectl` commands, secret named `acr-secret`/`app-env`). It has been corrected to match the real resource names (`inv-intelligence-cluster`, `invinteligence` ACR) and includes a "Known Issues" section and a first-person "Bugs I Encountered During Deployment" section documenting real incidents (RBAC role-assignment silently failing, Postgres firewall blocking AKS's outbound IP, missing env vars on the pod). **Read this before debugging any deployment issue** — it likely already covers the failure mode.
- **`.github/workflows/deploy.yaml`** — the automated CI/CD path, triggered on push to `main`. It builds/pushes the image, applies `k8s/deployment.yaml` + `k8s/service.yaml`, and creates a k8s secret named `invint-secrets` from GitHub Actions secrets (different secret name than the manual doc's `app-env`).
- `k8s/deployment.yaml` still hardcodes the **stale** ACR login server `invintelligence.azurecr.io` (missing the second `l` — the real registry is `invinteligence.azurecr.io`) and doesn't set an `imagePullSecrets`/RBAC-pull path — applying it as-is will likely hit the same `ImagePullBackOff` documented in `deployment-Document.md`'s bugs section.
- `CICD_Deployment_Guide.md` is a field-by-field annotated explainer of `k8s/deployment.yaml`, `k8s/service.yaml`, and `deploy.yaml` — useful if you need to explain what a specific YAML field does, not an operational runbook.

## Architecture

### Two FastAPI apps — only one is live

- **`app.py`** is the real entrypoint (what `dockerfile`'s `CMD` and `README.md` both run). It wires up `routes/ingestion.py` and `routes/chat.py` under `/api`, serves `templates/dashboard.html` at `/`, and on startup calls `create_database()` → `create_tables()` → `create_index()`.
- **`main.py`** is a separate, smaller FastAPI app (`routes/dashboard.py`, `routes/health.py`, port 8080) that duplicates the `/api/metrics` endpoint. It is not referenced by the Dockerfile or any deployment path — treat it as legacy/unused unless told otherwise.

### Ingestion / RAG pipeline (the core data flow)

`routes/ingestion.py` (`POST /api/upload`) drives `ingestion/ingest_documents.py::ingest_document`, which chains:

1. `ingestion/pdf_to_markdown.py` — PDF → Markdown (`pymupdf4llm`)
2. `ingestion/semantic_chunker.py` — Markdown → semantic chunks, using LangChain's `SemanticChunker` against Azure OpenAI embeddings
3. `vectorstore/azure_ai_search.py` (`AzureAISearchVectorStore.upload_chunks`) — embeds + uploads chunks to the Azure AI Search index (schema defined in `vectorstore/create_index.py`; fields: `id`, `company`, `year`, `source_file`, `content`, `content_vector`)
4. `rag/kpi_extractor_rag.py::extract_financial_metrics` — retrieves the newly-indexed chunks (`Retriever`, filtered by `company`/`year`) and calls `llm/azure_openai.py::get_structured_completion` to extract the 8 fixed KPI fields (Revenue, Net Income, Operating Income, Cash Flow, Total Assets, Total Liabilities, Top Risk Factors, Top Growth Drivers) as a Pydantic model
5. `database/save_metrics.py` — persists the extracted metrics into the `financial_metrics` Postgres table

Company/year are parsed from the PDF filename (`ingest_documents.py::parse_company_year`) — supports `2024_Apple.pdf` and `Apple_2024_AnnualReport.pdf`-style names.

`routes/chat.py` (`POST /api/chat`) is a separate, simpler path: retrieve via `Retriever.invoke()`, stuff context into a single-shot prompt, call Azure OpenAI chat completion directly (no reuse of `rag/kpi_extractor_rag.py`).

`llm/azure_openai.py::get_structured_completion` first tries native structured output (`client.beta.chat.completions.parse`); if the deployment doesn't support it, it falls back to a plain completion + manual JSON extraction + key-alias remapping (`_remap_to_aliases`) so LLM key-casing drift doesn't silently drop fields.

### Storage

All Postgres access goes through `database/postgres_sql.py::get_engine()`, which builds a SQLAlchemy engine from `POSTGRES_HOST/PORT/USER/PASSWORD/DATABASE` env vars (`sslmode=require`, credentials URL-encoded). There's a single table, `financial_metrics`, upserted by re-inserting a new row per extraction and reading the latest via `ROW_NUMBER() OVER (PARTITION BY company, year ORDER BY created_at DESC)` (see `database/metrics.py` / `routes/dashboard.py` — these two implement the identical query independently).

### Configuration

All runtime config is environment variables loaded via `python-dotenv` (`load_dotenv()` called independently in several modules) — there is no central settings module. `config/settings.yaml` exists but is **not loaded anywhere in the code**; don't treat it as authoritative.

### Frontend

`package.json` declares a React app (`react-scripts`, `react-router-dom`) but there is no corresponding `src/`/`public/` directory — it's leftover scaffolding from an earlier direction (see `project_journey.md` Phase 10). The actual shipped UI is server-rendered: `templates/dashboard.html` (Jinja2) + `static/style.css`, returned directly by `app.py`'s `/` route.

### Reference docs

`Architecture.md` has both logical (data pipeline) and physical (Azure deployment topology) Mermaid diagrams. `implementation_notes.md` and `project_journey.md` are phase-by-phase build diaries (useful for *why* a component exists, e.g. why Postgres over Azure SQL, how the Azure AI Search index was tuned) rather than current-state references — prefer reading the code/`Architecture.md` for current behavior.

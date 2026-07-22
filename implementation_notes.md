# AI-Powered Investor Intelligence Platform — Implementation Notes

Progress log for the ingestion pipeline, from PDF ingestion through semantic chunking setup. This follows the `ingestion/` folder of [AI-Powered-Investor-Intelligence-Platform](https://github.com/rishav-sah/AI-Powered-Investor-Intelligence-Platform).

---

## Phase 1: PDF → Markdown Conversion

**Goal:** Convert the source PDF (annual report) into Markdown so it can be processed downstream.

- Work is done inside the `ingestion/` folder.
- Script: `pdf_to_markdown.py`
- Library used: **PyMuPDF** — chosen because it helps preserve the structural layout of the document (headings, sections, etc.) better than plain text extraction.

### Steps to execute

1. Delete whatever already exists inside the `markdown` output folder (clean slate before each run).
2. Create a virtual environment:
   ```bash
   uv venv
   ```
3. Activate it:
   ```bash
   .venv\Scripts\activate
   ```
4. Install requirements:
   ```bash
   uv pip install -r requirements.txt
   ```
5. Run the conversion script:
   ```bash
   python pdf_to_markdown.py
   ```

✅ **Phase 1 complete** — PDF successfully converted into Markdown.

---

## Phase 2: Semantic Chunking

**Goal:** Split the converted Markdown into meaningful chunks using semantic similarity instead of naive fixed-width splitting.

- Location: `ingestion/semantic_chunker.py`

### Why embeddings are needed for chunking

Suppose the document has ~5 paragraphs. Feeding all of this data to an LLM in one go isn't possible because of the model's **context window limitation** — so chunking is required.

**Traditional (fixed-width) chunking:**
- Content is split directly based on a fixed token width (e.g., a 1200-token window groups roughly 1200 tokens together).
- **Limitation:** this approach risks losing context, since splits can happen mid-thought/mid-topic regardless of meaning.

**Semantic chunking (the approach used here):**
- First, an **embedding model** is used. Its job is to convert text data into an embedding (semantic vector).
- For each of the 5 paragraphs, the model generates a semantic vector. For example:

  ```
  P1 = [0.12, -0.43, 0.91, ...]
  P2 = [0.11, -0.41,  0.91, ...]
  P3 = [0.12,  0.55,  0.22, ...]
  P4 = [0.81,  0.22, -0.44, ...]
  ```

- Once we have these vectors, we perform a **similarity activity** based on the semantic vectors.
- Suppose we compare `P1` and `P2` and compute a similarity score.
- If the similarity score is close to `1`, the two paragraphs are considered similar, and we keep them grouped together in the same chunk.

We use **Azure OpenAI's text embedding model** (`text-embedding-ada-002`) to generate these embeddings.

### Why Azure AI Foundry is needed

To use the embedding model, we need an Azure OpenAI endpoint. This means we first need to **host/deploy the model** in Azure to get an OpenAI-compatible endpoint.

### Setting up the embedding deployment in Azure

**A. Create the Azure AI Foundry resource**

1. In the Azure Portal, open **Azure AI Foundry**.
2. Go to **Create resources**.
3. Under **Resource Group**, select **Create new resources** → name it (e.g., `inu-intelligence`).
4. Set the **Name** field (e.g., `inu-intelligence`).
5. Click **Review + Create**.
6. Click **Create**.

This step deploys the Azure AI Foundry service.

Once the deployment succeeds:
7. Go to **Resources**.
8. Go to the **Foundry portal**.

**B. Deploy the embedding model**

1. Go to **Overview**.
2. Click **Deploy a model** → **Discover**.
3. In **Discover models**, search for `text-embedding-ada-002`.
4. Select the `text-embedding-ada-002` model.
5. Click **Deploy** and select **Customize**.
6. Set the **token limit** to **150K**.
7. Click **Deploy**.

**C. Wire the credentials into the project**

1. Copy the **key** from the `text-embedding-ada-002` deployment.
2. Paste it under `AZURE_OPENAI_KEY` in `.env`.
3. Go back to **Home**, copy the **Azure OpenAI endpoint**.
4. Paste it under `OPENAI_ENDPOINT` (Azure OpenAI endpoint) in `.env`.

**D. Run the chunking script**

```bash
python semantic_chunker.py
```

---

## Phase 3: Vector Store Setup (Azure AI Search)

**Goal:** Persist the semantic chunks (from Phase 2) in a searchable vector store.

Run the chunking file (from Phase 2) first if not already done:
```bash
python semantic_chunker.py
```

### A. Create the Azure AI Search resource

1. In the Azure Portal, go to **Services** → click **Azure AI Search** → **Create**.
2. **Resource group:** select the existing `rg-inv-intelligence` resource group (created in Phase 2).
3. **Service name:** `ais-inv-intelli...` (Azure AI Search instance name).
4. **Pricing tier:** Basic.
5. **Review + Create** → **Create**.

> ⚠️ **Error faced:** the initial creation attempt did not go through. It succeeded after changing the **region** (e.g. to West US) and adjusting the service name — some regions don't have capacity/support for the Basic tier under certain subscriptions.

### B. Wire the credentials into the project

1. Once the service is created, go to **Resource** → **Security + Networking** → **Keys**.
2. Copy the **Primary admin key** → paste under `AZURE_SEARCH_API_KEY` in `.env`.
3. Go to **Overview** → copy the **URL** → paste under `AZURE_SEARCH_ENDPOINT` in `.env`.

### The ingestion → index pipeline

**Script:** `ingestion/ingest_document.py`

When run, this script:
1. Creates the embeddings for the chunks.
2. Creates the vector store / index (if not already present).
3. Injects the chunk data into that index.
4. As a first step, extracts the **company name** and **year** from the file (used as metadata/filter fields).

Run it as a module from the project root:
```bash
python -m ingestion.ingest_document
```

> ⚠️ **Error faced:** running `ingest_document.py` directly threw an error — the script assumed the search index already existed, but it hadn't been created yet. There's a separate script, `vectorstore/create_index.py`, responsible for actually creating the index (it defines the `searchable`/`filterable` fields required by the index schema), and that script had never been run.
>
> **Fix:** run the index-creation script first:
> ```bash
> python -m vectorstore.create_index
> ```
> Then verify the index was created by going to the **Azure AI Foundry** portal and viewing the newly created index. After that, re-run `python -m ingestion.ingest_document` — it now completes successfully.

### Index field design — `searchable` vs. `filterable`

- Fields marked `searchable=True` (e.g. `content`) are full-text searched against whatever query the user types.
- Fields marked `filterable=True` (e.g. `company`) are used to narrow results down by exact match.
- **Example:** if a user asks *"What is the total revenue for Apple?"*, the query text ("revenue") is searched against the `content` field, and the `filterable` `company` field is then used to restrict the results to Apple only — so data from unrelated companies doesn't leak into the answer. This two-step search + filter is done specifically to improve retrieval accuracy.

### Search algorithm

- Retrieval uses **keyword search**, specifically **BM25 (Best Match 25)** — a ranking function based on term frequency, an evolution of the classic **TF-IDF** principle.
- Example scoring:

  | Query: "What is total revenue?" | Score |
  |---|---|
  | Doc 1: "Total revenue increased to 1B" | ~0.9 |
  | Doc 2: "Risk factors include inflation" | ~0.1 |

  Doc 2 scores much lower since it's less relevant to the query.

**Verification:** re-run `ingest_document.py`, then check the index directly — searching "apple" surfaces the relevant chunks. At query time, the user's query is matched against `content` and filtered by `company`.

> ⚠️ **Error faced (rate limit):** the embedding model has a request-rate limit. Embedding succeeded for the first batch of chunks, but failed on the second batch with a rate-limit error.
>
> **Fix:** increase the model deployment's **tokens-per-minute (TPM)** quota in Azure AI Foundry — this does incur additional cost. Called out as a realistic constraint that shows up once you're embedding a large document, not just a toy example.

---

## Phase 4: KPI Extraction (RAG + GPT-5)

**Status so far:** PDF → Markdown ✅ · Semantic chunking ✅ · Vector store ✅

**Goal:** Retrieve the chunk content relevant to specific KPIs (revenue, net income, etc.) from the vector store, then pass it to a GPT-5 model to extract structured KPI values.

**Script:** `rag/kpi_extractor_rag.py`

Since this is a RAG operation, the LLM client needs to be imported first — the flow is: retrieve the relevant data, then feed it to the LLM.

### Deploying the GPT-5 model in Azure AI Foundry

1. Go to the **Azure AI Foundry** portal.
2. **View deployments**.
3. **Deploy a base model**.
4. Search `gpt-5`.
5. Select **gpt-5-chat-completion**.
6. Under **Resource**, customize the token limit to **150K tokens/minute**.
7. **Deploy**.
8. Copy the endpoint → paste under `AZURE_OPENAI_CHAT_ENDPOINT` in `.env`. (The API key is the same key already used for the embedding deployment.)

---

## Phase 5: PostgreSQL Storage (Azure Database for PostgreSQL Flexible Server)

**Rationale:** the KPI extractor now produces structured output, and that structured output needs to be handed off to the UI — so it needs a place to persist. Hence: a SQL database.

### A. Create the Postgres Flexible Server

1. Azure Portal → search **Azure Postgres**.
2. Select **Azure Database for PostgreSQL Flexible Server** → **Create**.
3. **Resource group:** select the existing `rg-inv-intelligence`.
4. **Workload type:** Dev (for lower cost).
5. **Authentication method:** PostgreSQL authentication only.
6. Use the login ID / password already defined in `.env`.
7. **Networking:** create the server without firewall rules for now (rules get added when actually connecting — see error below).

> Note: pgAdmin is needed afterward to connect to and manage the server.

### B. Wire the endpoint into the project

1. Once the deployment completes, go to **Resources**.
2. Copy the endpoint → paste under `POSTGRES_HOST` in `.env`.
3. Under **Settings → Connect**, you'll find the connection info for the server.
4. A default database is created automatically, but the project uses its **own custom database** instead of the default one.

### C. Connect via pgAdmin

1. Right-click **Servers** → **Create** → **Server Group** → name it `inv-intelligence` → **Save**.
2. Under that group, right-click → **Register** → **Server**.
3. Give it a name → go to the **Connection** tab → enter host name & password from `.env`:
   - **Host name/address:** same as `POSTGRES_HOST`
   - **Port:** `5432`
   - **Maintenance database:** same as `POSTGRES_DB` in `.env`
   - **Username:** `POSTGRES_USER` from `.env`
   - **Password:** `POSTGRES_PASSWORD` from `.env`
4. **Save**.

### D. Create the tables

**Script:** `database/create_tables.py`

> ⚠️ **Error faced (connection timeout):** running `python -m database.create_tables` (with the actual `create_table()` call commented out, to test connectivity only) failed with a "failed to connect to database" error.
>
> **Root cause:** the server's firewall was blocking the connection from the local machine.
>
> **Fix:** on the deployed database server in the Azure Portal, go to **Overview** → **Connect from VS Code** → **Connect** (this adds the required client-IP firewall rule automatically). Re-ran the file — it printed `Database "<name>" created successfully`.
>
> Verified in the Azure Portal: the database with the given name now appears in the table/database list. Reconnected via pgAdmin — the connection now succeeds.

Since no tables existed yet, uncommented the `create_table()` call in `database/create_tables.py` and re-ran the file — it created the tables successfully.

### E. Verify and test ingestion into Postgres

1. In pgAdmin: `inv-intel` → `financial-intelligence` database → **Schemas** → **public** → **Tables**.
2. Right-click `financial_metrics` → **Query Tool** → run:
   ```sql
   SELECT * FROM financial_metrics;
   ```
3. Confirmed the table exists with **8 columns**.

With the Postgres server ready and structured KPI output available, the next step is passing that structured output into code that inserts it into Postgres.

- **Script:** `database/save_metrics.py` — contains a sample metrics record used to test whether ingestion works end-to-end.
- Run:
  ```bash
  python -m database.save_metrics
  ```
- Re-ran the same `SELECT` query in pgAdmin — confirmed the sample data now shows up in the table.

---

## Phase 6: Wiring the KPI Extractor into the Pipeline

At this point the custom Postgres database exists and is being read from / written to.

**Goal:** connect the KPI extractor into the overall flow so that whenever KPIs are extracted, they're automatically ingested into Postgres as a one-time activity per uploaded document. Also configure the RAG pipeline so that once a user uploads a document, all steps run automatically in sequence.

**Plan:** build backend API routes that wrap all these functions (chunking, embedding, retrieval, extraction, storage) together, then wire those routes into `app.py` so the whole pipeline executes end-to-end from a single upload action.

- At the bottom of `rag/kpi_extractor_rag.py` there was commented-out code responsible for tying these steps together — uncommented it.
- Run:
  ```bash
  python -m rag.kpi_extractor_rag
  ```
- **Effect:** when a user uploads a file, this calls the extraction function once, which extracts and saves the KPIs.

### Debugging `kpi_extractor_rag.py`

To confirm the extractor works in isolation:
- Temporarily commented out the debug `print(f"[Extracted KPI...]")` statement (~line 92) and the `if __name__ == "__main__":` guard (~line 405) to sanity-check the flow directly.
- **What the code does:** it hits the vector store, retrieves the relevant content, and passes that content to the GPT-5 model, which returns structured output (JSON) covering the 8 KPIs the dashboard needs.

> ⚠️ **Bug faced:** the extractor was only returning the KPI *headings*, with no values — every field printed as `None`.

**Fix 1 — determinism (temperature):** for a task like "read a large token dump and copy out the exact number," the model needs to behave as deterministically as possible rather than being creative. Added `temperature=0` to the fallback response call in `llm/azure_openai.py`.

**Fix 2 — key normalization (also in `llm/azure_openai.py`):**
1. Added `_normalize_key()` and `_remap_to_aliases()` helper functions (roughly lines 12–32) that strip spaces/underscores and normalize casing from a JSON key, then match it against the response model's declared field aliases the same way.
2. In the JSON-fallback parsing block, replaced the direct
   ```python
   response_model.model_validate_json(json_text)
   ```
   call with:
   ```python
   data = json.loads(json_text)
   data = _remap_to_aliases(data)
   response_model.model_validate(data)
   ```

**Why this was needed:** the fallback path asks the LLM for free-form JSON with no schema enforcement, so it sometimes returned keys like `"Net Income"` (matching the prompt's exact wording) and other times `"NetIncome"`. Pydantic's alias matching is exact-string, so any key that didn't literally match the declared alias — e.g., one with a space in it — silently defaulted to `None` instead of raising an error. Only `"Revenue"` consistently worked, since it's a single word with no space to drop. Normalizing both sides before matching makes validation resilient to whichever casing/spacing the model happens to produce on a given run.

**Result:** after these fixes, running the extractor against a real document (Apple 2024 report) successfully hit the vector store → retrieved content → passed it to GPT-5 → got back structured output → inserted it into Postgres. Verified by re-running the `SELECT` query in pgAdmin and seeing the record show up correctly.

---

## Phase 7: Building the UI

**Status:** with ingestion, chunking, vector store, KPI extraction, and Postgres storage all wired together, the application is roughly **90% built**. The remaining piece is the UI.

**Structure:**
- `static/` — CSS
- `templates/` — HTML

**Routes:**
- Located under `routes/` — this folder holds all the routes created so far.
- First route implemented: `routes/ingestion.py` (handles document ingestion).

### Local testing (backend only)

1. In terminal:
   ```bash
   python main.py
   ```
2. Tried opening the browser at `localhost:8000`.

> ⚠️ **Error faced:** the app was actually running on port **8080**, not 8000. Fixed by browsing to `localhost:8080` instead.

3. Visiting the base URL (`/`) showed "details not found" — there's no root/UI route defined at this stage.
4. Visiting `/docs` showed the interactive, auto-generated API docs listing the available endpoints.

**Architecture note:** since backend and UI aren't split into separate microservices in this project, all APIs are exposed directly through the UI via `app.py`, rather than behind a dedicated API surface. In a production/industry setting, backend and UI would normally be split into separate microservices. Authentication is also currently missing from these APIs, in production, they should require authentication to be reachable.

### Moving to the full UI

1. All UI integration lives in `app.py`.
2. Run:
   ```bash
   python app.py
   ```
3. In the browser, go to `localhost:8000` — the UI now loads.

### End-to-end test — uploading a PDF via "Ingest Report"

The process, step by step:
1. Load the document's data into the vector store.
2. Retrieve the relevant content back out of the vector store.
3. Extract the KPIs required for the UI.
4. Inject the KPIs into Postgres (as a one-time activity per document).

---

## Status

- [x] Phase 1 — PDF to Markdown conversion
- [x] Phase 2 — Azure AI Foundry + embedding deployment configured, semantic chunker implemented
- [x] Phase 3 — Azure AI Search vector store created, index creation + document ingestion pipeline working
- [x] Phase 4 — GPT-5 deployed in Azure AI Foundry for KPI extraction
- [x] Phase 5 — Postgres Flexible Server deployed, tables created, ingestion tested
- [x] Phase 6 — KPI extractor wired end-to-end (vector store → GPT-5 → Postgres), key-normalization and determinism bugs fixed
- [x] Phase 7 — Backend routes + UI (`app.py`) running locally end-to-end; upload → ingest → extract → store flow verified

The contenarization and deployment using azure is covered in deployment-Document.md .
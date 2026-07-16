# AI-Powered Investor Intelligence Platform: Implementation Notes

## Phase 1: PDF → Markdown Conversion

**Goal:** Convert the source PDF (annual report) into Markdown so it can be processed downstream.

- Work is done inside the `ingestion/` folder.
- Script: `pdf_to_markdown.py`
- Library used: **PyMuPDF**, chosen because it helps preserve the structural layout of the document (headings, sections, etc.) better than plain text extraction.

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

✅ **Phase 1 complete**: PDF successfully converted into Markdown.

---

## Phase 2: Semantic Chunking

**Goal:** Split the converted Markdown into meaningful chunks using semantic similarity instead of naive fixed-width splitting.

- Location: `ingestion/semantic_chunker.py`

### Why embeddings are needed for chunking

Suppose the document has ~5 paragraphs. Feeding all of this data to an LLM in one go isn't possible because of the model's **context window limitation** so chunking is required.

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

## Status

- [x] Phase 1 — PDF to Markdown conversion
- [x] Phase 2 — Azure AI Foundry + embedding deployment configured, semantic chunker implemented
- [ ] Next: chunk storage / vectorstore integration
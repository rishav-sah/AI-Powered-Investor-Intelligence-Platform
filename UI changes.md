# UI Changes

## Why I made these changes

While cleaning up after some bad test uploads (a badly-named McDonald's PDF and a couple of failed Amazon annual report attempts), I realized there was no way to remove an uploaded document from the app itself. Every time I needed to get rid of a bad upload, I had to do it by hand in three different places: `kubectl exec` into the pod to delete the raw PDF and markdown files, run a raw SQL `DELETE` against Postgres for the KPI row, and there wasn't even a way to clean out the leftover chunks in Azure AI Search short of writing a one-off script. That's fine for me debugging from the terminal, but it means anyone actually using the dashboard has no way to fix a bad upload themselves — a wrong file, a duplicate, or a test document just sits there forever, and if enough of them pile up, wrong company data can even leak into the RAG retrieval for other companies (I'd already hit that exact bug once this session). I wanted a normal "delete" action, from the UI, that actually cleans up everywhere the data lives — not just the file.

Separately, I noticed the KPI cards (Revenue, Net Income, Operating Income, Cash Flow, Total Assets, Total Liabilities) list one row per company, and with my 3 test companies (Apple, Microsoft, Tesla) it happened to fit exactly — but there was no `max-height` or scroll on that list at all. As soon as I add a 4th or 5th company, each card would just keep growing taller instead of staying compact, pushing the whole page down. I wanted those lists capped at a fixed height with their own scrollbar instead, so the dashboard stays usable no matter how many companies I've ingested.

## What I changed

### 1. Delete an uploaded document, from the sidebar

Added a "Uploaded Documents" list to the sidebar, right under the upload progress bar. Each entry shows the filename, and hovering over it reveals a trash-can icon (kept hidden the rest of the time so the sidebar doesn't look cluttered). Clicking it asks for confirmation, then deletes the document and everything tied to it:

- the raw PDF and its converted markdown file,
- every chunk indexed for that file in Azure AI Search,
- the KPI row in Postgres for that company/year.

To make this work I had to add two new endpoints and a couple of backend pieces that didn't exist before:

- `GET /api/documents` — lists whatever's currently in `data/raw_pdfs`, with company/year parsed from each filename.
- `DELETE /api/documents/{file_name}` — does the actual cleanup. It re-parses the filename the same way ingestion does (so it agrees with whatever company/year the file was originally ingested under), deletes the matching search-index chunks via a new `delete_by_source_file()` method I added to `AzureAISearchVectorStore` (search by `source_file eq '<file>'`, collect the IDs, then `delete_documents`), deletes the Postgres row via a new `delete_metrics()` function, and finally removes the PDF and markdown files from disk.
- Added a basic path-traversal guard on the delete endpoint (checking the resolved path stays inside the upload directory) since the filename comes straight from the URL.

On the frontend, `loadDocuments()` fetches the list on page load and renders it into the sidebar; `deleteDocument()` handles the confirm-and-delete flow and reloads the page afterward so the KPI cards, stats, and document list all reflect the deletion.

### 2. Scrollable KPI value lists

Gave `.kpi-values-list` a fixed `max-height` with `overflow-y: auto`. The dashboard already has a themed scrollbar defined globally, so it picked that up automatically without needing any extra styling. Now the KPI cards stay a consistent height regardless of how many companies are ingested, and you scroll within the card instead of the whole page growing.

## How I verified it

I didn't want to test this against my real Apple/Microsoft/Tesla data, so I ran the app locally against the live Azure backend (had to add a firewall rule for my current IP first — same class of local-dev-firewall issue I'd already hit and documented earlier) and tested against a throwaway file instead:

- Confirmed `GET /api/documents` correctly lists the 3 real PDFs with their parsed company/year.
- Created a fake `2099_TestCorp.pdf`/`.md` pair, confirmed it showed up in the list, called `DELETE /api/documents/2099_TestCorp.pdf`, and confirmed: the response came back with `chunks_deleted: 0` (correct — this file was never actually indexed) and `metrics_deleted: true`, the file disappeared from the list on a follow-up `GET`, and both files were actually gone from disk.
- Confirmed deleting a nonexistent file returns a clean `404` instead of a crash.
- Confirmed a path-traversal attempt against the delete endpoint gets rejected (FastAPI's own routing already blocks slashes in the path parameter, and my own resolve()-based check is there as a second layer).
- Confirmed the new CSS actually reached the browser by fetching `/static/style.css` directly and checking both the `.kpi-values-list` and `.document-item`/`.documents-list` rules were present as written.

I didn't have a way to visually click through this in an actual browser from here, so I couldn't confirm things like the hover-reveal animation or the confirm dialog looked right — only that the markup, styles, and API calls were all wired correctly end to end. That gap turned out to matter (see below).

## Deploying it: one unrelated bug, then one real one

### Unrelated: the first deploy attempt failed to even start

Building and pushing the image, the new pod crash-looped with `exec: "uvicorn": executable file not found in $PATH`. Root cause had nothing to do with these UI changes: `requirements.txt` had been silently corrupted at some point — overwritten with garbled UTF-16 content missing `fastapi`, `uvicorn`, `openai`, and every `azure-*`/`langchain-*` package (the classic signature of a PowerShell `>`/`Out-File` redirect run without `-Encoding utf8`). Docker's build cache had been quietly reusing an old layer built from that broken file, which is why it wasn't obvious until I rebuilt with `--no-cache`. Restored `requirements.txt` from the last git commit (it was uncommitted corruption, not real work), rebuilt, and this time verified `uvicorn` and the new code were actually present *inside* the built image before pushing — a check I hadn't been doing before, and should have been.

### The real one: what I saw in the browser didn't match what I'd shipped

After that redeploy, I asked for a screenshot to confirm things looked right — and they didn't. The uploaded-documents list showed the file icon rendering huge (should've been a small 15×15px icon next to the filename), no hover effect, and no visible trash-can button at all. The KPI cards showed all 3 companies with no scrolling, like the `max-height` had never been applied.

My first assumption was a broken deploy again. It wasn't — I fetched `/static/style.css` and the page HTML directly from the live URL and both were **exactly** what I'd written: the `.document-item-icon { width: 15px; height: 15px; }` rule was there, the hover rule was there, `.kpi-values-list`'s `max-height`/`overflow-y` was there. I even checked for a competing CSS rule with higher specificity that might silently override the icon sizing — nothing.

That only left one explanation: the browser was showing a **stale cached copy** of `style.css` from before any of these classes existed. The stylesheet was linked as a plain `/static/style.css` with no version parameter, so once a browser had it cached from an earlier visit this session, it had no reason to ever re-fetch it — every redeploy since then would have looked identical from that browser's point of view, regardless of what the server actually started serving.

Fixed it properly instead of just saying "hard refresh": added a `STATIC_VERSION` in `app.py` (the process start timestamp, so it changes automatically on every deploy — no manual version bumping needed), passed it into the template, and changed the stylesheet link to `/static/style.css?v={{ static_version }}`. Now every deploy forces browsers to fetch the current CSS instead of trusting a stale cache.

While I was in there, I also noticed the KPI scroll fix, while technically correct, was invisible with only 3 test companies — 3 rows fit comfortably inside a 210px box with nothing left to scroll, so it looked identical to "not fixed" even once the cache issue was gone. Tightened `max-height` to 130px so scrolling is visibly demonstrable even at 3 companies, not just once a 4th or 5th gets added.

Rebuilt with `--no-cache`, verified `uvicorn`, the cache-busting change, and the new `max-height` were all actually present inside the built image (learned that lesson the hard way earlier in this same deploy), pushed, rolled out, and confirmed against the live public URL directly — the page now serves `/static/style.css?v=<timestamp>` and the CSS behind that URL has the 130px max-height.

**Lesson for next time:** anything served as a static asset needs cache-busting from day one, not bolted on after a confusing "it looks unchanged" report. And always verify a *built* image's actual contents before pushing — I'd already learned that once this session (the `requirements.txt` incident) and then needed the reminder again for the same deploy.

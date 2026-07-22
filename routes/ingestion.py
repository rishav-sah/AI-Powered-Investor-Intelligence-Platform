import shutil
import uuid
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from pathlib import Path
import os
from langchain_openai import AzureOpenAIEmbeddings
from vectorstore.azure_ai_search import AzureAISearchVectorStore
from ingestion.ingest_documents import ingest_document, parse_company_year
from database.metrics import delete_metrics

router = APIRouter()

UPLOAD_DIR = Path("data/raw_pdfs")
MARKDOWN_DIR = Path("data/markdown")

# In-memory job store. Fine for this app's single-replica deployment; would
# need a shared store (e.g. Redis) if this ever runs with multiple replicas/workers.
JOBS: dict[str, dict] = {}


def _make_embeddings() -> AzureOpenAIEmbeddings:
    return AzureOpenAIEmbeddings(
        model=os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
        max_retries=8
    )


def _make_vector_store() -> AzureAISearchVectorStore:
    return AzureAISearchVectorStore(
        endpoint=os.getenv("AZURE_SEARCH_ENDPOINT"),
        api_key=os.getenv("AZURE_SEARCH_API_KEY"),
        index_name=os.getenv("AZURE_SEARCH_INDEX_NAME")
    )


def _run_ingestion_job(job_id: str, file_path: Path) -> None:
    JOBS[job_id]["status"] = "running"

    def progress_callback(stage: str, message: str) -> None:
        JOBS[job_id]["stage"] = stage
        JOBS[job_id]["message"] = message

    try:
        ingest_document(
            pdf_path=str(file_path),
            embeddings=_make_embeddings(),
            vector_store=_make_vector_store(),
            progress_callback=progress_callback
        )
        JOBS[job_id]["status"] = "completed"
        JOBS[job_id]["stage"] = "done"
        JOBS[job_id]["message"] = "Ingestion complete"
    except ValueError as exc:
        JOBS[job_id]["status"] = "failed"
        JOBS[job_id]["error"] = str(exc)
    except RuntimeError as exc:
        JOBS[job_id]["status"] = "failed"
        JOBS[job_id]["error"] = str(exc)
    except Exception as exc:
        JOBS[job_id]["status"] = "failed"
        JOBS[job_id]["error"] = f"Unexpected error: {exc}"


@router.post("/upload", status_code=202)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...)
):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    file_path = UPLOAD_DIR / file.filename

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    job_id = str(uuid.uuid4())
    JOBS[job_id] = {
        "status": "queued",
        "stage": "queued",
        "message": "Waiting to start...",
        "file_name": file.filename,
        "error": None
    }

    background_tasks.add_task(_run_ingestion_job, job_id, file_path)

    return {
        "message": "Upload accepted, processing in background",
        "job_id": job_id,
        "file_name": file.filename
    }


@router.get("/upload/status/{job_id}")
async def get_upload_status(job_id: str):
    job = JOBS.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return job


@router.get("/documents")
async def list_documents():
    if not UPLOAD_DIR.exists():
        return {"documents": []}

    documents = []

    for pdf_file in sorted(UPLOAD_DIR.glob("*.pdf")):
        try:
            company, year = parse_company_year(pdf_file)
        except ValueError:
            company, year = None, None

        documents.append({
            "file_name": pdf_file.name,
            "company": company,
            "year": year,
            "size_bytes": pdf_file.stat().st_size
        })

    return {"documents": documents}


@router.delete("/documents/{file_name}")
async def delete_document(file_name: str):
    pdf_path = UPLOAD_DIR / file_name

    if pdf_path.resolve().parent != UPLOAD_DIR.resolve():
        raise HTTPException(status_code=400, detail="Invalid file name")

    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail=f"'{file_name}' not found")

    try:
        company, year = parse_company_year(pdf_path)
    except ValueError:
        company, year = None, None

    vector_store = AzureAISearchVectorStore(
        endpoint=os.getenv("AZURE_SEARCH_ENDPOINT"),
        api_key=os.getenv("AZURE_SEARCH_API_KEY"),
        index_name=os.getenv("AZURE_SEARCH_INDEX_NAME")
    )
    chunks_deleted = vector_store.delete_by_source_file(file_name)

    metrics_deleted = False
    if company and year:
        delete_metrics(company=company, year=year)
        metrics_deleted = True

    pdf_path.unlink(missing_ok=True)
    (MARKDOWN_DIR / f"{pdf_path.stem}.md").unlink(missing_ok=True)

    return {
        "message": "Document deleted successfully",
        "file_name": file_name,
        "chunks_deleted": chunks_deleted,
        "metrics_deleted": metrics_deleted
    }
import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import AzureOpenAIEmbeddings

from ingestion.pdf_to_markdown import PDFToMarkdownConverter
from ingestion.semantic_chunker import chunk_markdown
from vectorstore.azure_ai_search import AzureAISearchVectorStore
from rag.kpi_extractor_rag import extract_financial_metrics
from database.save_metrics import save_metrics
from vectorstore.azure_ai_search import Retriever

load_dotenv()


def parse_company_year(pdf_file: Path) -> tuple[str, str]:
    """Parse company and year from a PDF filename.

    Supports names like `2024_Apple.pdf` and `Apple_2024_AnnualReport.pdf`.
    """
    stem = pdf_file.stem
    parts = stem.split("_")

    if parts and parts[0].isdigit():
        return parts[-1], parts[0]

    if len(parts) >= 2 and parts[1].isdigit():
        return parts[0], parts[1]

    raise ValueError(
        f"Cannot parse company/year from filename '{pdf_file.name}'. "
        "Expected '<year>_<company>.pdf' or '<company>_<year>_...pdf', e.g. '2024_Apple.pdf'."
    )


def ingest_document(
    pdf_path: str,
    embeddings,
    vector_store,
    progress_callback=None
) -> None:
    """
    Ingest a single PDF document.

    progress_callback, if given, is called as progress_callback(stage, message)
    at each step so a caller (e.g. a background job) can report real progress
    instead of guessing.
    """
    def report(stage: str, message: str) -> None:
        if progress_callback:
            progress_callback(stage, message)

    pdf_file = Path(pdf_path)

    company, year = parse_company_year(pdf_file)
    print(f"Ingesting {pdf_file.name} as company={company!r}, year={year!r}")
    report("parsing", f"Parsed as {company} ({year})")

    report("converting", "Converting PDF to Markdown...")
    converter = PDFToMarkdownConverter()

    markdown_file = converter.convert_pdf(
        pdf_path=pdf_path,
        output_dir="data/markdown"
    )

    report("chunking", "Splitting into semantic chunks...")
    chunks = chunk_markdown(
        markdown_file=markdown_file,
        embeddings=embeddings
    )

    print(f"Generated {len(chunks)} chunks for {pdf_file.name}")

    report("indexing", f"Indexing {len(chunks)} chunks...")
    vector_store.upload_chunks(
        chunks=chunks,
        embeddings=embeddings,
        company=company,
        year=year,
        source_file=pdf_file.name
    )

    # Extract financial metrics using the newly ingested data
    report("extracting", "Extracting financial KPIs...")
    metrics = extract_financial_metrics(
        retriever=Retriever(vector_store.client),
        company=company,
        year=int(year) if year.isdigit() else None
    )

    # Persist metrics to PostgreSQL
    if metrics:
        report("saving", "Saving metrics...")
        save_metrics(company=company, year=int(year) if str(year).isdigit() else None, metrics=metrics)

    report("done", "Ingestion complete")


def ingest_directory(input_dir: str) -> None:
    """
    Ingest all PDFs from a directory.
    """
    embeddings = AzureOpenAIEmbeddings(
        model=os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
        max_retries=8
    )

    vector_store = AzureAISearchVectorStore(
        endpoint=os.getenv("AZURE_SEARCH_ENDPOINT"),
        api_key=os.getenv("AZURE_SEARCH_API_KEY"),
        index_name=os.getenv("AZURE_SEARCH_INDEX_NAME")
    )

    pdf_files = list(Path(input_dir).glob("*.pdf"))

    print(f"Found {len(pdf_files)} PDF(s)")

    for pdf_file in pdf_files:
        ingest_document(
            pdf_path=str(pdf_file),
            embeddings=embeddings,
            vector_store=vector_store
        )


if __name__ == "__main__":
    ingest_directory("data/raw_pdfs")
    # ingest_document("data/raw_pdfs/2024_Apple.pdf")
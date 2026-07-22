import uuid

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from types import SimpleNamespace


class AzureAISearchVectorStore:
    """Azure AI Search vector store."""

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        index_name: str
    ) -> None:
        self.client = SearchClient(
            endpoint=endpoint,
            index_name=index_name,
            credential=AzureKeyCredential(api_key)
        )

    def upload_chunks(
        self,
        chunks,
        embeddings,
        company: str,
        year: str,
        source_file: str
    ) -> None:
        """
        Upload chunks to Azure AI Search.
        """
        documents = []

        for chunk in chunks:
            vector = embeddings.embed_query(chunk.page_content)

            documents.append(
                {
                    "id": str(uuid.uuid4()),
                    "company": company,
                    "year": year,
                    "source_file": source_file,
                    "content": chunk.page_content,
                    "content_vector": vector
                }
            )

        result = self.client.upload_documents(documents)

        uploaded = sum(item.succeeded for item in result)

        print(f"Uploaded {uploaded}/{len(documents)} chunks.")

        if uploaded == 0 and documents:
            raise RuntimeError(
                f"No chunks were uploaded to the vector store for '{source_file}' "
                f"(company={company!r}, year={year!r}) — indexing failed."
            )

    def delete_by_source_file(self, source_file: str) -> int:
        """
        Delete all indexed chunks belonging to a given source file.

        Returns the number of chunks successfully deleted.
        """
        escaped = source_file.replace("'", "''")

        results = self.client.search(
            search_text="*",
            filter=f"source_file eq '{escaped}'",
            select=["id"]
        )

        ids = [{"id": result["id"]} for result in results]

        if not ids:
            return 0

        result = self.client.delete_documents(ids)

        return sum(item.succeeded for item in result)


class Retriever:
    """Simple wrapper around Azure Search client for retrieving relevant chunks.
    Mirrors the Retriever used in the RAG extractor.
    """
    def __init__(self, client):
        self.client = client

    def invoke(
        self,
        query: str,
        company: str | None = None,
        year: int | None = None,
        top_k: int = 20
    ) -> list:
        """Retrieve relevant chunks from Azure AI Search.
        Returns a list of SimpleNamespace objects with `page_content`.
        """
        filters = []
        if company:
            filters.append(f"company eq '{company}'")
        if year:
            filters.append(f"year eq '{year}'")
        filter_expr = " and ".join(filters) if filters else None
        results = (
            self.client.search(
                search_text=query,
                top=top_k,
                filter=filter_expr
            )
            if filter_expr
            else self.client.search(
                search_text=query,
                top=top_k
            )
        )
        documents = []
        for result in results:
            content = result.get("content", "")
            documents.append(SimpleNamespace(page_content=content))
        return documents
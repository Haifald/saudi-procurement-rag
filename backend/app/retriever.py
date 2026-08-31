from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings


PROJECT_ROOT = Path(__file__).resolve().parent.parent
EMBEDDINGS_DIR = str(PROJECT_ROOT / "embeddings")
EMBEDDING_MODEL = "intfloat/multilingual-e5-large"

_embeddings: HuggingFaceEmbeddings | None = None
_database: FAISS | None = None
_article_index: dict[tuple[str, int], Document] | None = None


def get_database() -> FAISS:
    global _embeddings, _database

    if _database is None:
        _embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
        _database = FAISS.load_local(
            EMBEDDINGS_DIR,
            _embeddings,
            allow_dangerous_deserialization=True,
        )

    return _database


def get_article_index() -> dict[tuple[str, int], Document]:
    global _article_index

    if _article_index is None:
        database = get_database()
        article_index: dict[tuple[str, int], Document] = {}

        for document_id in database.index_to_docstore_id.values():
            document = database.docstore.search(document_id)
            if isinstance(document, Document):
                key = (
                    document.metadata.get("source_type"),
                    document.metadata.get("article_number"),
                )
                article_index[key] = document

        _article_index = article_index

    return _article_index


def _with_query_prefix(query: str) -> str:
    """Add the E5 query prefix when it is missing."""
    return query if query.startswith("query:") else f"query: {query}"


def semantic_search(query: str, k: int = 10) -> list[Document]:
    database = get_database()
    return database.similarity_search(
        _with_query_prefix(query),
        k=k,
    )


def article_search(
    article_number: int,
    source_type: str | None = None,
) -> list[Document]:
    """Retrieve documents for an article directly from metadata."""
    article_index = get_article_index()
    source_types = (source_type,) if source_type else ("نظام", "لائحة")

    return [
        document
        for current_source in source_types
        if (document := article_index.get((current_source, article_number)))
    ]


def hybrid_search(
    query: str,
    article_number: int | None = None,
    source_type: str | None = None,
    k: int = 10,
) -> list[Document]:
    """Prioritize an exact article match, then add semantic results."""
    documents = (
        article_search(article_number, source_type=source_type)
        if article_number is not None
        else []
    )
    documents.extend(semantic_search(query, k=k))

    unique_documents: list[Document] = []
    seen_keys: set[tuple[str | None, int | None]] = set()

    for document in documents:
        key = (
            document.metadata.get("source_type"),
            document.metadata.get("article_number"),
        )
        if key not in seen_keys:
            seen_keys.add(key)
            unique_documents.append(document)

    return unique_documents[:k]


def search(query: str, k: int = 10) -> list[Document]:
    return semantic_search(query, k=k)
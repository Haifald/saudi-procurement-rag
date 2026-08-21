import logging
import re
from dataclasses import dataclass, field

from langchain_core.documents import Document

from .llm import extract_cited_sources, generate_answer, strip_source_marker
from .retriever import hybrid_search, search
from .utils import parse_article_number

logger = logging.getLogger(__name__)

DEFAULT_RESULT_COUNT = 10
FALLBACK_DISPLAY_SOURCE_COUNT = 2
MIN_RESULTS_BEFORE_EXPANSION = 2
EXPANSION_MULTIPLIER = 2


def _requested_source_type(question: str) -> str | None:
    """Return an explicitly named legal source, if the user named one."""
    mentions_regulation = "اللائحة" in question or "لائحة" in question
    mentions_system = "النظام" in question
    if mentions_regulation and mentions_system:
        return None
    if mentions_regulation:
        return "لائحة"
    if mentions_system:
        return "نظام"
    return None


def _clean_source_excerpt(text: str) -> str:
    """Make PDF-derived source excerpts legible without changing their meaning."""
    text = text.replace("ـ", "")

    paragraphs: list[str] = []
    for line in (line.strip() for line in text.splitlines()):
        if not line:
            continue
        is_list_item = bool(re.match(r"^(?:\d+\s*[.)-]|[-•])\s*", line))
        if is_list_item or not paragraphs:
            paragraphs.append(line)
        else:
            paragraphs[-1] = f"{paragraphs[-1]} {line}"
    return "\n".join(paragraphs)


@dataclass
class Source:
    """One retrieved document, shaped for display or API responses."""

    label: str
    source_type: str | None
    article_number: int | None
    bab: str
    fasl: str
    text: str
    cited: bool = False

    @classmethod
    def from_document(
        cls, document: Document, cited_keys: set[tuple[str, int]] | None = None
    ) -> "Source":
        source_type = document.metadata.get("source_type")
        article_number = document.metadata.get("article_number")
        cited_keys = cited_keys or set()
        text = document.page_content.replace("passage:", "").strip()
        # The first line is an ingestion header that may carry PDF formatting
        # noise. The frontend already displays a clean source label.
        text = _clean_source_excerpt(text.split("\n", maxsplit=1)[-1].strip())
        return cls(
            label=document.metadata.get("label", "مصدر غير معروف"),
            source_type=source_type,
            article_number=article_number,
            bab=document.metadata.get("bab", ""),
            fasl=document.metadata.get("fasl", ""),
            text=text,
            cited=(source_type, article_number) in cited_keys,
        )


@dataclass
class AskResponse:
    """The result of answering one question - the shape every frontend renders."""

    answer: str
    sources: list[Source] = field(default_factory=list)
    article_number: int | None = None
    has_unverified_citation: bool = False


def retrieve(question: str, k: int = DEFAULT_RESULT_COUNT) -> list[Document]:
    """Choose the retrieval strategy for a question and fetch Documents.

    - If the question names an article number, use hybrid search (exact
      article lookup + semantic results).
    - Otherwise, semantic search.
    - If too few results come back, expand with a wider semantic search.
    """
    article_number = parse_article_number(question)
    source_type = _requested_source_type(question)

    if article_number is not None:
        logger.info("Using hybrid search for article %s (%s)", article_number, source_type or "all sources")
        documents = hybrid_search(
            question,
            article_number=article_number,
            source_type=source_type,
            k=k,
        )
    else:
        logger.info("Using semantic search")
        documents = search(question, k=k)

    if len(documents) < MIN_RESULTS_BEFORE_EXPANSION:
        logger.info("Few results (%d); expanding with a wider semantic search", len(documents))
        documents = search(question, k=k * EXPANSION_MULTIPLIER)

    return documents


def answer_question(question: str, k: int = DEFAULT_RESULT_COUNT) -> AskResponse:
    question = question.strip()
    article_number = parse_article_number(question)
    requested_source_type = _requested_source_type(question)
    documents = retrieve(question, k=k)

    if not documents:
        logger.info("No documents retrieved for question: %s", question)
        return AskResponse(
            answer="لم يتم العثور على نتائج.",
            sources=[],
            article_number=article_number,
        )

    raw_answer = generate_answer(
        documents,
        question,
        article_number=article_number,
        requested_source_type=requested_source_type,
    )


    retrieved_keys = {
        (document.metadata.get("source_type"), document.metadata.get("article_number"))
        for document in documents
    }
    cited_keys = extract_cited_sources(raw_answer)
    answer = strip_source_marker(raw_answer)
    unverified = cited_keys - retrieved_keys
    if unverified:
        logger.warning(
            "LLM cited sources that were not retrieved for question %r: %s",
            question,
            unverified,
        )

    verified_keys = cited_keys & retrieved_keys
    displayed_documents = [
        document
        for document in documents
        if (document.metadata.get("source_type"), document.metadata.get("article_number"))
        in verified_keys
    ]
    matching_article_documents = [
        document
        for document in documents
        if document.metadata.get("article_number") == article_number
        and document.metadata.get("source_type") in {"نظام", "لائحة"}
    ]
    matching_article_source_types = {
        document.metadata.get("source_type") for document in matching_article_documents
    }
    if (
        article_number is not None
        and requested_source_type is None
        and {"نظام", "لائحة"}.issubset(matching_article_source_types)
    ):
    
        displayed_documents = matching_article_documents
    if not displayed_documents:
        displayed_documents = documents[:FALLBACK_DISPLAY_SOURCE_COUNT]

    return AskResponse(
        answer=answer,
        sources=[Source.from_document(document, cited_keys) for document in displayed_documents],
        article_number=article_number,
        has_unverified_citation=bool(unverified),
    )

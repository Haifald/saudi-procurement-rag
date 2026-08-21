import os
import re
import shutil
import subprocess
import tempfile
import logging
from pathlib import Path

import pdfplumber
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings


logger = logging.getLogger(__name__)



PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = str(PROJECT_ROOT / "data" / "mapping.pdf")
EMBEDDINGS_DIR = str(PROJECT_ROOT / "embeddings")
EMBEDDING_MODEL = "intfloat/multilingual-e5-large"
OCR_LANGUAGE = "ara"
OCR_RENDER_DPI = 300
TESSERACT_TIMEOUT_SECONDS = 45
LOCAL_TESSDATA_DIR = PROJECT_ROOT / ".tessdata"

def clean(text: str) -> str:
    """Normalize text extracted from the PDF."""
    text = text.replace("\ufeff", "")
    text = text.replace("ـ", "")
    text = re.sub(r"\r\n|\r", "\n", text)
    text = re.sub(r"[\u200e\u200f\u202a-\u202e\u200b]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return "\n".join(line.strip() for line in text.splitlines()).strip()


def split_nitham_and_laeeha(text: str) -> tuple[str, list[tuple[int, str]]]:
    """Separate the regulation text from its executive-regulation articles."""
    marker = re.compile(r'(\d+)المادةالائحـة')
    matches = [(match.start(), int(match.group(1))) for match in marker.finditer(text)]
    if not matches:
        return text, []

    nitham_text = text[: matches[0][0]]
    laeeha_chunks: list[tuple[int, str]] = []
    for index, (start, article_number) in enumerate(matches):
        end = matches[index + 1][0] if index + 1 < len(matches) else len(text)
        chunk = re.sub(r"^\d+المادةاللائحـة\s*", "", text[start:end]).strip()
        if chunk:
            laeeha_chunks.append((article_number, chunk))
    return nitham_text, laeeha_chunks


def get_section_info(text: str) -> dict[str, str]:
    """Extract chapter and section names when available."""
    chapter = re.search(r"([\u0600-\u06ff ]+)\d+البـ+اب", text)
    section = re.search(r"([\u0600-\u06ff ]+)\d+الفصل", text)
    return {
        "bab": clean_section_title(chapter.group(1)) if chapter else "",
        "fasl": clean_section_title(section.group(1)) if section else "",
    }


def _logical_lines(page: pdfplumber.page.Page) -> list[str]:
    """Rebuild logical RTL lines from positioned PDF words.

    The PDF stores Arabic words in visual order. Reversing each word and then
    reading words from right to left restores the intended line without mixing
    article blocks that share a page.
    """
    words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    rows: list[list[dict]] = []

    for word in sorted(words, key=lambda item: (item["top"], item["x0"])):
        if not rows or abs(word["top"] - rows[-1][0]["top"]) > 2:
            rows.append([word])
        else:
            rows[-1].append(word)

    def logical_word(word: str) -> str:
        return word if word.isdigit() or word == "لا" else word[::-1]

    return [
        " ".join(logical_word(word["text"]) for word in sorted(row, key=lambda item: item["x0"], reverse=True))
        for row in rows
    ]


def _normalise_layout_text(text: str) -> str:
    """Normalise visual PDF text only for matching headings and metadata."""
    text = text.replace("ـ", "")
    return re.sub(r"\s+", " ", text).strip()


def _section_from_line(line: str) -> dict[str, str]:
    """Read chapter/section labels from one reconstructed heading line."""
    normalised = _normalise_layout_text(line)
    result: dict[str, str] = {}
    bab = re.search(r"الباب\s*(\d+)\s*\|?\s*(.*?)(?=المادة|الفصل|$)", normalised)
    fasl = re.search(r"الفصل\s*(\d+)\s*\|?\s*(.*?)(?=المادة|$)", normalised)
    if bab:
        result["bab"] = f"الباب {bab.group(1)} — {bab.group(2).strip(' |')}".rstrip(" — ")
    if fasl:
        result["fasl"] = f"الفصل {fasl.group(1)} — {fasl.group(2).strip(' |')}".rstrip(" — ")
    return result


def _article_header(
    line: str, previous_line: str = "", next_line: str = ""
) -> tuple[str, int] | None:
    """Return (source_type, article_number) for a positioned PDF heading."""
    normalised = _normalise_layout_text(line)
    source_type = "نظام" if "النظام" in normalised else "لائحة" if "لائح" in normalised else None
    article = re.search(r"المادة\s*(\d+)", normalised)

    # The first system article puts "المادة 1" on one line and "النظام" on
    # the next line. Treat that adjacent source label as part of the heading.
    if source_type is None and article is not None:
        next_normalised = _normalise_layout_text(next_line)
        if "النظام" in next_normalised:
            source_type = "نظام"
        elif "لائح" in next_normalised:
            source_type = "لائحة"

    # Some system headings render as "النظام 19" without the word "المادة".
    if source_type and article is None and normalised.startswith(source_type):
        article = re.search(rf"{source_type}\s*(\d+)", normalised)

    # In a few early pages the article number is positioned at the end of the
    # preceding chapter line, while "النظام المادة" appears on the next line.
    if source_type and article is None and "المادة" in normalised:
        article = re.search(r"(\d+)\s*$", _normalise_layout_text(previous_line))

    # Some headings split the number onto the following line, e.g.
    # "النظام المادة" then "26".  This is a visual layout split, so only
    # accept an adjacent line made entirely of digits.
    if source_type and article is None and "المادة" in normalised:
        following_number = re.fullmatch(r"\s*(\d+)\s*", _normalise_layout_text(next_line))
        if following_number:
            article = following_number

    if source_type is None or article is None:
        return None

    article_number = int(article.group(1))
    return (source_type, article_number) if 1 <= article_number <= 200 else None


def _extract_positioned_articles(page: pdfplumber.page.Page) -> list[Document]:
    """Extract system and regulation articles from their visual page blocks."""
    section = {"bab": "", "fasl": ""}
    current: dict | None = None
    articles: list[Document] = []

    def finish_current() -> None:
        nonlocal current
        if current is None:
            return
        text = clean("\n".join(current["lines"]))
        if len(text) >= 20:
            source_type = current["source_type"]
            article_number = current["article_number"]
            articles.append(
                Document(
                    page_content=text,
                    metadata={
                        "source_type": source_type,
                        "article_number": article_number,
                        "label": f"{source_type} - المادة {article_number}",
                        "bab": current["section"]["bab"],
                        "fasl": current["section"]["fasl"],
                    },
                )
            )
        current = None

    lines = _logical_lines(page)
    previous_line = ""
    for index, raw_line in enumerate(lines):
        line = clean(raw_line)
        if not line:
            continue

        section.update(_section_from_line(line))
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        header = _article_header(line, previous_line, next_line)
        if header:
            finish_current()
            source_type, article_number = header
            current = {
                "source_type": source_type,
                "article_number": article_number,
                "section": section.copy(),
                "lines": [],
            }
            continue

        # Chapter and section labels describe metadata; they are not article text.
        if current and ("الباب" in line or "الفصل" in line):
            current["section"] = section.copy()
            continue

        if current:
            current["lines"].append(line)

        previous_line = line

    finish_current()
    return articles


def _tesseract_command() -> str | None:
    """Locate Tesseract without tying the project to one operating system."""
    configured = os.getenv("TESSERACT_CMD")
    if configured:
        return configured
    discovered = shutil.which("tesseract")
    if discovered:
        return discovered
    return None


def _ocr_page_text(page: pdfplumber.page.Page) -> str | None:
    """Read one rendered page with Arabic OCR, returning None on a safe fallback."""
    command = _tesseract_command()
    if command is None:
        return None

    image_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as image_file:
            image_path = Path(image_file.name)
        page.to_image(resolution=OCR_RENDER_DPI).original.save(image_path)

        arguments = [command, str(image_path), "stdout", "-l", OCR_LANGUAGE, "--psm", "6"]
        if LOCAL_TESSDATA_DIR.exists():
            arguments.extend(["--tessdata-dir", str(LOCAL_TESSDATA_DIR)])
        result = subprocess.run(
            arguments,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TESSERACT_TIMEOUT_SECONDS,
            check=False,
        )
        if result.returncode != 0:
            logger.warning("OCR failed for PDF page %s: %s", page.page_number, result.stderr.strip())
            return None
        return clean(result.stdout)
    except (OSError, subprocess.TimeoutExpired) as error:
        logger.warning("OCR unavailable for PDF page %s: %s", page.page_number, error)
        return None
    finally:
        if image_path is not None:
            image_path.unlink(missing_ok=True)


def _ocr_header_pattern(source_type: str, article_number: int) -> re.Pattern[str]:
    source_name = "النظام" if source_type == "نظام" else "اللائحة"
    # Tesseract sees the page visually, so this pattern is deliberately based
    # on the source name and article number rather than on PDF glyph order.
    return re.compile(
        rf"(?mi)^.*{source_name}.*?المادة\s*{article_number}(?!\d).*$"
    )


def _flexible_ocr_context_pattern(fragment: str) -> str:
    """Escape a PDF fragment while allowing OCR whitespace and empty numbers."""
    escaped = re.escape(re.sub(r"\s+", " ", fragment))
    escaped = escaped.replace(r"\(\ \)", r"\(\s*\d+\s*\)")
    return escaped.replace(r"\ ", r"\s+")


def _repair_empty_parentheses_from_ocr(pdf_text: str, ocr_text: str) -> str:
    repaired = pdf_text
    empty_parentheses = list(re.finditer(r"\(\s*\)", repaired))
    for occurrence in reversed(empty_parentheses):
        left = max(0, occurrence.start() - 70)
        right = min(len(repaired), occurrence.end() + 70)
        before = repaired[left:occurrence.start()]
        after = repaired[occurrence.end():right]
        pattern = re.compile(
            _flexible_ocr_context_pattern(before)
            + r"\(\s*(?P<number>\d+)\s*\)"
            + _flexible_ocr_context_pattern(after),
            re.DOTALL,
        )
        numbers = {match.group("number") for match in pattern.finditer(ocr_text)}
        if len(numbers) == 1:
            repaired = (
                repaired[:occurrence.start()]
                + f"({numbers.pop()})"
                + repaired[occurrence.end():]
            )
    return repaired


def _apply_ocr_to_page_articles(
    page: pdfplumber.page.Page, documents: list[Document]
) -> list[Document]:
    """Replace only validated article bodies with OCR text from the same page."""
    ocr_text = _ocr_page_text(page)
    if not ocr_text:
        for document in documents:
            document.metadata["extraction_method"] = "pdf"
        return documents

    matches: list[tuple[int, int, Document]] = []
    for document in documents:
        source_type = document.metadata["source_type"]
        article_number = document.metadata["article_number"]
        match = _ocr_header_pattern(source_type, article_number).search(ocr_text)
        if match:
            matches.append((match.start(), match.end(), document))

    matches.sort(key=lambda item: item[0])
    replacement_by_document: dict[int, str] = {}
    for index, (_, header_end, document) in enumerate(matches):
        next_start = matches[index + 1][0] if index + 1 < len(matches) else len(ocr_text)
        body = clean(ocr_text[header_end:next_start])
        repaired_body = _repair_empty_parentheses_from_ocr(document.page_content, body)
        if repaired_body != document.page_content:
            replacement_by_document[id(document)] = repaired_body

    for document in documents:
        replacement = replacement_by_document.get(id(document))
        if replacement is not None:
            document.page_content = replacement
            document.metadata["extraction_method"] = "pdf+ocr"
        else:
            document.metadata["extraction_method"] = "pdf"
    return documents


def clean_section_title(title: str) -> str:
    """Normalize stretched Arabic text extracted from PDF headings."""
    title = title.replace("ـ", "")
    title = re.sub(r"(?<=[\u0600-\u06ff])(?=النظام\b)", " ", title)
    return re.sub(r"\s+", " ", title).strip()


def load_and_build_docs() -> list[Document]:
    """Read positioned PDF blocks and merge continuation pages by article."""
    data_by_source: dict[str, dict[int, dict]] = {"نظام": {}, "لائحة": {}}

    with pdfplumber.open(DATA_PATH) as pdf:
        for page in pdf.pages:
            positioned_documents = _extract_positioned_articles(page)
            for document in _apply_ocr_to_page_articles(page, positioned_documents):
                source_type = document.metadata["source_type"]
                article_number = document.metadata["article_number"]
                entry = data_by_source[source_type].setdefault(
                    article_number,
                    {
                        "texts": [],
                        "section": {"bab": "", "fasl": ""},
                        "ocr_pages": 0,
                        "pdf_pages": 0,
                    },
                )
                entry["texts"].append(document.page_content)
                method_key = (
                    "ocr_pages"
                    if document.metadata.get("extraction_method") == "pdf+ocr"
                    else "pdf_pages"
                )
                entry[method_key] += 1
                for key in ("bab", "fasl"):
                    if document.metadata[key]:
                        entry["section"][key] = document.metadata[key]

    documents: list[Document] = []
    documents.extend(_build_documents(data_by_source["نظام"], "نظام", "نظام المنافسات والمشتريات الحكومية"))
    documents.extend(_build_documents(data_by_source["لائحة"], "لائحة", "اللائحة التنفيذية"))
    return documents


def _build_documents(data_by_article: dict[int, dict], source_type: str, title: str) -> list[Document]:
    """Create documents for one source type."""
    documents = []
    for article_number, data in sorted(data_by_article.items()):
        section = data["section"]
        full_text = "\n\n".join(data["texts"])
        header = f"{title} - المادة {article_number}"
        if section["bab"]:
            header += f" | {section['bab']}"
        if section["fasl"]:
            header += f" - {section['fasl']}"
        documents.append(
            Document(
                page_content=f"passage: {header}\n{full_text}",
                metadata={
                    "source_type": source_type,
                    "article_number": article_number,
                    "label": f"{source_type} - المادة {article_number}",
                    "bab": section["bab"],
                    "fasl": section["fasl"],
                    "ocr_pages": data["ocr_pages"],
                    "pdf_pages": data["pdf_pages"],
                },
            )
        )
    return documents


def print_ingestion_report(documents: list[Document]) -> None:
    """Print a short summary of the indexed articles."""
    nitham_numbers = sorted(
        document.metadata["article_number"]
        for document in documents
        if document.metadata["source_type"] == "نظام"
    )
    laeeha_numbers = sorted(
        document.metadata["article_number"]
        for document in documents
        if document.metadata["source_type"] == "لائحة"
    )
    print(f"System articles: {len(nitham_numbers)} -> {nitham_numbers}")
    print(f"Executive regulation articles: {len(laeeha_numbers)} -> {laeeha_numbers}")
    ocr_documents = sum(document.metadata.get("ocr_pages", 0) > 0 for document in documents)
    fallback_documents = sum(document.metadata.get("pdf_pages", 0) > 0 for document in documents)
    unrepaired_references = [
        document.metadata["label"]
        for document in documents
        if re.search(r"\(\s*\)", document.page_content)
    ]
    print(f"OCR-backed articles: {ocr_documents}")
    print(f"Articles with PDF fallback pages: {fallback_documents}")
    print(
        f"Articles with unrepaired empty numeric references: "
        f"{len(unrepaired_references)} -> {unrepaired_references}"
    )


def build_index(documents: list[Document]) -> None:
    """Embed documents and save the FAISS index locally."""
    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    database = FAISS.from_documents(documents, embeddings)
    os.makedirs(EMBEDDINGS_DIR, exist_ok=True)
    database.save_local(EMBEDDINGS_DIR)


if __name__ == "__main__":
    docs = load_and_build_docs()
    print_ingestion_report(docs)
    build_index(docs)

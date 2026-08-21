import logging
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .service import answer_question

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="المساعد القانوني - API",
    description="نظام المنافسات والمشتريات الحكومية السعودي ولائحته التنفيذية",
)

# The Next.js application normally proxies requests through its server route.
# Keeping this allow-list makes direct browser access safe for local development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if origin],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, description="سؤال المستخدم")


class SourceResponse(BaseModel):
    label: str
    source_type: str | None
    article_number: int | None
    bab: str
    fasl: str
    text: str
    cited: bool


class AskResponse(BaseModel):
    answer: str
    sources: list[SourceResponse]
    article_number: int | None
    has_unverified_citation: bool


@app.get("/health")
def health() -> dict[str, str]:
    """Basic liveness check - does not touch FAISS or the LLM."""
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest) -> AskResponse:
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="السؤال فارغ.")

    try:
        result = answer_question(question)
    except Exception:
        logger.exception("Failed to answer question: %s", question)
        raise HTTPException(
            status_code=500,
            detail="حدث خطأ أثناء معالجة السؤال.",
        )

    return AskResponse(
        answer=result.answer,
        sources=[SourceResponse(**source.__dict__) for source in result.sources],
        article_number=result.article_number,
        has_unverified_citation=result.has_unverified_citation,
    )

import logging
import os
import re

from dotenv import load_dotenv
from langchain_core.documents import Document
from openai import OpenAI


load_dotenv()

logger = logging.getLogger(__name__)
MODEL = "gpt-4o-mini"
NO_ANSWER_MESSAGE = "لا تتوفر معلومات كافية في المصادر المتاحة."
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))

# The model places sources in this internal marker. The service strips it
# before returning the answer, keeping legal prose clean and readable.
SOURCE_MARKER_PATTERN = re.compile(r"\[\[SOURCES:\s*(.*?)\]\]", re.DOTALL)
SOURCE_ENTRY_PATTERN = re.compile(r"(نظام|لائحة)\s*-\s*المادة\s*(\d+)")

SYSTEM_PROMPT = """أنت مستشار قانوني متخصص حصراً في نظام المنافسات والمشتريات الحكومية السعودي ولائحته التنفيذية.

التزم بالقواعد التالية:
1. استخدم المعلومات الموجودة في السياق فقط، ولا تضف معلومات خارجية.
2. لا تضع استشهادات أو أرقام مواد داخل نص الإجابة؛ ستعرض الواجهة المراجع الداعمة أسفلها.
3. صحح أي معلومة خاطئة في السؤال بوضوح قبل الإجابة.
4. إذا لم تجد إجابة مدعومة في السياق، أجب بالنص التالي فقط: "لا تتوفر معلومات كافية في المصادر المتاحة."
5. اكتب باللغة العربية الفصحى.
6. استخدم نقاطاً مرقمة للشروط والقوائم، وفقرة للتعريفات والأحكام العامة.
7. لا تستنتج أحكاماً قانونية غير مذكورة صراحة في المصادر.
8. إذا غطت المصادر جزءاً من السؤال فقط، أجب عن الجزء المدعوم واذكر أن الباقي غير مغطى.
9. عند تلخيص مادة أو حكم محدد، حافظ على جميع الشروط والاستثناءات والقيود والموافقات والمهل والإحالات الواردة في النص. لا تحذفها من أجل الاختصار.
10. إذا كان السؤال عن مادة محددة، غطِّ جميع فقراتها ذات الصلة بترتيبها المنطقي، ولا تضف تفصيلاً غير موجود في السياق."""


def _format_context(documents: list[Document]) -> str:
    """Format retrieved documents for the model prompt."""
    sections = []
    for document in documents:
        label = document.metadata.get("label", "مصدر")
        content = document.page_content.replace("passage:", "").strip()
        sections.append(f"[{label}]\n{content}")
    return "\n\n---\n\n".join(sections)


def _allowed_labels(documents: list[Document]) -> str:
    labels = [document.metadata.get("label") for document in documents]
    return "، ".join(label for label in labels if label) or "لا يوجد"


def _call_llm(messages: list[dict[str, str]]) -> str:
    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=0.0,
        max_tokens=2048,
    )
    return (response.choices[0].message.content or "").strip()


def extract_cited_sources(answer_text: str) -> set[tuple[str, int]]:
    """Read source keys from the marker that follows the response."""
    marker = SOURCE_MARKER_PATTERN.search(answer_text)
    if not marker:
        return set()
    return {
        (source_type, int(article_number))
        for source_type, article_number in SOURCE_ENTRY_PATTERN.findall(marker.group(1))
    }


def strip_source_marker(answer_text: str) -> str:
    """Remove the model-only source marker before sending an answer to the UI."""
    answer = SOURCE_MARKER_PATTERN.sub("", answer_text)
    # The UI renders plain text paragraphs, so Markdown heading markers would
    # be visible to users. Keep the requested headings as ordinary prose.
    return re.sub(r"(?m)^#{1,6}\s*", "", answer).strip()


def generate_answer(
    documents: list[Document],
    question: str,
    *,
    article_number: int | None = None,
    requested_source_type: str | None = None,
) -> str:
    """Generate a source-grounded Arabic legal answer."""
    if not documents:
        return NO_ANSWER_MESSAGE

    exact_article_sources = {
        document.metadata.get("source_type")
        for document in documents
        if document.metadata.get("article_number") == article_number
    }
    show_both_sources = (
        article_number is not None
        and requested_source_type is None
        and {"نظام", "لائحة"}.issubset(exact_article_sources)
    )
    ambiguity_instruction = ""
    if show_both_sources:
        ambiguity_instruction = f"""
- السؤال يذكر المادة {article_number} من دون تحديد المصدر، وتوجد المادة في النظام واللائحة التنفيذية. أجب عن المصدرين معاً.
- ابدأ بعبارة قصيرة توضح وجود مادة بالرقم نفسه في المصدرين، ثم أنشئ قسمين مستقلين بعنوانين: «النظام — المادة {article_number}» و«اللائحة التنفيذية — المادة {article_number}».
- لا تخلط الأحكام بين القسمين، واذكر في سطر المصادر التقني المادتين فقط إذا استخدمتهما فعلاً.
"""
    elif requested_source_type is not None:
        ambiguity_instruction = f"""
- المستخدم حدّد {requested_source_type} صراحة. أجب من هذا المصدر فقط، ولا تستخدم أو تستشهد بمادة المصدر الآخر ذات الرقم نفسه.
"""

    prompt = f"""## المصادر الداعمة المتاحة
{_allowed_labels(documents)}

## نصوص المواد
استخدم النص التالي فقط ولا تستخدم أي معرفة خارجية.
{_format_context(documents)}

## السؤال
{question}

## تعليمات الإخراج
- ابدأ بالإجابة مباشرة دون مقدمة.
- اكتب إجابة عربية واضحة ومتكاملة. يجوز تلخيص الصياغة، لكن لا تحذف أي شرط أو استثناء أو قيد أو موافقة أو مهلة أو إحالة وردت في النص.
- إذا كان السؤال عن مادة محددة، غطِّ كل فقراتها ذات الصلة بترتيبها المنطقي، واستخدم نقاطًا مرقمة عندما تكون الإجابة قائمة من أحكام أو شروط أو إجراءات.
- لا تذكر أرقام المواد أو أسماء المصادر أو أي صيغة استشهاد داخل الإجابة.
- اكتب نصاً عادياً فقط: لا تستخدم Markdown أو رموز العناوين مثل # أو ###.
{ambiguity_instruction}
- بعد الإجابة أضف سطرًا تقنيًا واحدًا فقط بصيغة:
  [[SOURCES: نظام - المادة 3; لائحة - المادة 12]]
  واستبدل الأمثلة بالمراجع التي استخدمتها فعلًا من قائمة المصادر المتاحة. لا تضف أي مرجع غير موجود فيها.
- إذا كانت المعلومة في السؤال خاطئة، ابدأ بـ "تصحيح:".
- إذا لم تجد إجابة، اكتب: "{NO_ANSWER_MESSAGE}"."""

    try:
        answer = _call_llm(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
        )
        return answer or NO_ANSWER_MESSAGE
    except Exception:
        logger.exception("Answer generation failed")
        return "حدث خطأ أثناء توليد الإجابة."

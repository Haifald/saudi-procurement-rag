import re


ARTICLE_NUMBER_PATTERN = re.compile(r"(?:المادة|مادة)\s*(\d+)")


def parse_article_number(text: str) -> int | None:
    """Return a valid article number found in the question."""
    match = ARTICLE_NUMBER_PATTERN.search(text)
    if not match:
        return None

    article_number = int(match.group(1))
    return article_number if 1 <= article_number <= 200 else None
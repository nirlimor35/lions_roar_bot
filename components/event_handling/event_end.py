"""Detect messages that indicate the incident is over (keywords + optional LLM)."""

from components.constants import EVENT_END_KEYWORDS
from components.utils import normalize_text

NON_END_OUTCOME_PHRASES: tuple[str, ...] = (
    "נפל בים",
    "נפלו בים",
    "נפילה בים",
    "נפילות בים",
    "נפלו בשטח פתוח",
    "נפילה בשטח פתוח",
    "נפילות בשטח פתוח",
    "נפל בשטח פתוח",
    "אין נפגעים",
    "ללא נפגעים",
)

NON_END_INSTRUCTION_PHRASES: tuple[str, ...] = (
    "להישאר במרחבים מוגנים",
    "יש להישאר במרחבים מוגנים",
    "הישארו במרחבים מוגנים",
    "להישאר במרחב מוגן",
    "יש להישאר במרחב מוגן",
    "הישארו במרחב מוגן",
    "אין לצאת מהמרחב המוגן",
    "לא לצאת מהמרחב המוגן",
    "להמשיך לשהות במרחב מוגן",
    "האירוע טרם הסתיים",
    "עד לסיום האירוע",
    "עד להודעה חדשה",
)


def event_end_keyword_match(text: str) -> bool:
    if not text:
        return False
    normalized = normalize_text(text)
    return any(kw in normalized for kw in EVENT_END_KEYWORDS)


def has_non_end_outcome_phrase(text: str) -> bool:
    """
    Outcome-only updates must not end the incident by themselves.
    We still allow explicit end keywords to close the incident.
    """
    if not text:
        return False
    normalized = normalize_text(text)
    return any(phrase in normalized for phrase in NON_END_OUTCOME_PHRASES)


def has_non_end_instruction_phrase(text: str) -> bool:
    """
    Ongoing safety instructions indicate the incident is still active, even if
    the text mentions "end" as part of a future condition (e.g. "until event end").
    """
    if not text:
        return False
    normalized = normalize_text(text)
    return any(phrase in normalized for phrase in NON_END_INSTRUCTION_PHRASES)

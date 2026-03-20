from datetime import timedelta
from enum import StrEnum


class LionsRoarStrEnum(StrEnum):
    """Base enum that shows the value (not the name) in repr for cleaner logs."""

    def __repr__(self) -> str:
        return self.value


class MessageTitles(LionsRoarStrEnum):
    ALERT = "🚨 התראה"
    WEAK_ALERT = "⚠️ התראה מוקדמת"
    INFORMATIONAL = "ℹ️ אירוע פעיל — לא בסביבה"
    UPDATE = "✏️ התראה מעודכנת"
    ENDED = "✅ האירוע הסתיים"


class FirstMessageStrength(LionsRoarStrEnum):
    NONE = "none"
    WEAK = "weak"
    INFORMATIONAL = "informational"
    STRONG = "strong"


ACTIVE_EVENT_TTL = timedelta(hours=3)


DEFAULT_ALERT_KEYWORDS: tuple[str, ...] = (
    "שיגור",
    "שיגורים",
    "ירי",
    "טיל",
    "טילים",
    "מטח",
    "מטחים",
    "רקטה",
    "רקטות",
    "יירוט",
    "יירוטים",
    "אזעקה",
    "אזעקות",
    "חדירה",
    "חדירת",
    "כטבמ",
    'כתב"מ',
    "כלי טיס עוין",
    "התרעה",
    "התרעות",
)

DEFAULT_RELEVANT_LOCATIONS: tuple[str, ...] = (
    "גבעתיים",
    "תל אביב",
    "תל-אביב",
    "רמת גן",
    "גוש דן",
    "המרכז",
    "מרכז",
    "ירקון",
)

DEFAULT_WEAK_FIRST_PHRASES: tuple[str, ...] = (
    "הכנה לשיגור",
    "שיגורים מאיראן",
    "תזוזות משגרים",
    "תנועת משגרים",
    "הכנה לירי",
    "היערכות לירי",
)


EVENT_END_KEYWORDS: tuple[str, ...] = (
    "האירוע הסתיים",
    "האירוע נגמר",
    "סיום האירוע",
    "סיום התרעה",
    "סיום אירוע",
    "אפשר לצאת",
    "ניתן לצאת",
    "מותר לצאת",
    "חזרה לשגרה",
    "חזרנו לשגרה",
    "ביטול התרעה",
    "ביטול האזעקה",
    "מצב שגרה",
    "המצב חזר לשגרה",
    "הותרה יציאה",
    "בטלנו התרעה",
    "הכול שקט",
    "הכל שקט",
    "אין אירוע",
    "סוף האירוע",
)

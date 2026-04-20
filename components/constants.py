from datetime import timedelta
from enum import StrEnum


class LionsRoarStrEnum(StrEnum):
    """Base enum that shows the value (not the name) in repr for cleaner logs."""

    def __repr__(self) -> str:
        return self.value


ACTIVE_INCIDENT_TTL = timedelta(hours=3)

RECENT_OUT_OF_SUBSCRIBER_WINDOW = timedelta(minutes=5)

RECENT_OUT_OF_SUBSCRIBER_MAX_UNIFIED_CHARS = 2500

INFORMATIONAL_GRACE_PERIOD = timedelta(minutes=5)

SOURCE_DELETED_GRACE_PERIOD = timedelta(minutes=2)

_CLOSE_REASON_LABELS = {
    "all_clear": "אירוע הסתיים",
    "out_of_subscriber_areas": "האירוע מחוץ לטווח",
    "ttl": "סגירה אוטומטית",
    "manual": "סגירה ידנית על ידי מנהל",
    "informational_grace": "סגירה אחרי המתנה — לא נרשמה הסלמה נוספת",
    "source_deleted": "ההודעה המקורית נמחקה",
}

_PRIORITY_TITLE_HIGH = "🚨 התרעה"
_PRIORITY_TITLE_WARNING = "⚠️ התראה מוקדמת"
_PRIORITY_TITLE_INFORMATIONAL = "ℹ️ אירוע פעיל — לא בסביבה"

_PRIORITY_TITLES = {
    "high": _PRIORITY_TITLE_HIGH,
    "warning": _PRIORITY_TITLE_WARNING,
    "informational": _PRIORITY_TITLE_INFORMATIONAL,
}


class CloseReason(LionsRoarStrEnum):
    """Why an incident was closed (shown in the Telegram footer)."""

    ALL_CLEAR = "all_clear"
    OUT_OF_SUBSCRIBER_AREAS = "out_of_subscriber_areas"
    TTL = "ttl"
    MANUAL = "manual"
    INFORMATIONAL_GRACE = "informational_grace"
    SOURCE_DELETED = "source_deleted"

    @property
    def close_reason_label(self) -> str:
        return _CLOSE_REASON_LABELS[self.value]


class AlertTitles:
    """Hebrew ending status titles (for HTML alerts)."""

    PENDING_CLOSE = "⏰ אירוע מועמד לסגירה"
    ENDED = "✅ האירוע הסתיים"


class MessagePriority(LionsRoarStrEnum):
    NONE = "none"
    INFORMATIONAL = "informational"
    WARNING = "warning"
    HIGH = "high"

    @property
    def alert_title_for_priority(self) -> str:
        return _PRIORITY_TITLES.get(self.value, _PRIORITY_TITLE_INFORMATIONAL)

class ModuleColors:
    INCIDENT_HANDLER = "\033[94mIncident Handler\033[0m"
    MESSAGE_PROCESSING = "\033[95mMessage Processing\033[0m"
    MAIN = "\033[96mMain\033[0m"
    LLM = "\033[92mLLM\033[0m"


class IncidentHandlerLog:
    NEW = "\033[93mNew Incident\033[0m"
    EXISTING = "\033[93mExisting Incident\033[0m"
    OPENED = "\033[91;1mOpened Incident\033[0m"
    NOT_OPENED = "\033[93;2mNot Opened\033[0m"
    ENDED = "\033[92;1mEnded Incident\033[0m"
    MANUAL = "\033[92;1mManual Close\033[0m"
    ENDED_CANDIDATE = "\033[92;2mEnded Incident Candidate\033[0m"


class MessageType(LionsRoarStrEnum):
    NEW_MESSAGE = "new_message"
    EDITED_MESSAGE = "edited_message"
    DELETED_MESSAGE = "deleted_message"

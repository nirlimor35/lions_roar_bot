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


class CloseReason(LionsRoarStrEnum):
    """Why an incident was closed (shown in the Telegram footer)."""

    ALL_CLEAR = "all_clear"
    OUT_OF_SUBSCRIBER_AREAS = "out_of_subscriber_areas"
    TTL = "ttl"
    MANUAL = "manual"
    INFORMATIONAL_GRACE = "informational_grace"
    SOURCE_DELETED = "source_deleted"


def close_reason_label(reason: CloseReason) -> str:
    """Hebrew explanation for subscribers."""
    if reason == CloseReason.ALL_CLEAR:
        return "אירוע הסתיים"
    if reason == CloseReason.OUT_OF_SUBSCRIBER_AREAS:
        return "האירוע מחוץ לטווח"
    if reason == CloseReason.TTL:
        return "סגירה אוטומטית"
    if reason == CloseReason.MANUAL:
        return "סגירה ידנית על ידי מנהל"
    if reason == CloseReason.INFORMATIONAL_GRACE:
        return "סגירה אחרי המתנה — לא נרשמה הסלמה נוספת"
    if reason == CloseReason.SOURCE_DELETED:
        return "ההודעה המקורית נמחקה"


class AlertTitles:
    """Hebrew alert headings by priority (for HTML alerts)."""

    HIGH = "🚨 התרעה"
    WARNING = "⚠️ התראה מוקדמת"
    INFORMATIONAL = "ℹ️ אירוע פעיל — לא בסביבה"
    PENDING_CLOSE = "⏰ אירוע מועמד לסגירה"
    ENDED = "✅ האירוע הסתיים"
    # Treat NONE like informational for display when an incident was opened.
    DEFAULT = INFORMATIONAL


class MessagePriority(LionsRoarStrEnum):
    NONE = "none"
    INFORMATIONAL = "informational"
    WARNING = "warning"
    HIGH = "high"


def alert_title_for_priority(priority: MessagePriority) -> str:
    """Headline line (no HTML) for an open incident."""
    if priority == MessagePriority.HIGH:
        return AlertTitles.HIGH
    if priority == MessagePriority.WARNING:
        return AlertTitles.WARNING
    if priority == MessagePriority.INFORMATIONAL:
        return AlertTitles.INFORMATIONAL
    return AlertTitles.DEFAULT


class MessageType(LionsRoarStrEnum):
    NEW_MESSAGE = "new_message"
    EDITED_MESSAGE = "edited_message"
    DELETED_MESSAGE = "deleted_message"

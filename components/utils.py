from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_IL_TZ = ZoneInfo("Asia/Jerusalem")


def normalize_text(text: str | None) -> str:
    """Collapse whitespace and strip; returns empty string for falsy input."""
    if not text:
        return ""
    return " ".join(text.strip().split())


def to_il_tz(dt: datetime) -> datetime:
    """Convert a UTC (or naive-UTC) datetime to Israel local time."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_IL_TZ)


def format_ts_il(dt: datetime) -> str:
    """Format a datetime as HH:MM DD/MM/YYYY in Israel local time."""
    return to_il_tz(dt).strftime("%H:%M %d/%m/%Y")


class ChannelWatermarks:
    """
    Tracks the latest seen message-id per channel so each message is processed
    at most once: skip when message_id <= watermark, advance watermark on process.
    """

    def __init__(self) -> None:
        self._latest_by_channel: dict[int, int] = {}

    def is_old(self, channel_id: int, message_id: int) -> bool:
        """True if we have already seen this message or a newer one from this channel."""
        return message_id <= self._latest_by_channel.get(channel_id, 0)

    def update(self, channel_id: int, message_id: int) -> None:
        """Record that we've seen this message; keep the highest id per channel."""
        current = self._latest_by_channel.get(channel_id, 0)
        self._latest_by_channel[channel_id] = max(current, message_id)

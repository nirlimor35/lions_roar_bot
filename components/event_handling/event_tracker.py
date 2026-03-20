"""Single active incident tracker with a configurable merge window."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from components.constants import ACTIVE_EVENT_TTL, FirstMessageStrength


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass
class ActiveEvent:
    event_id: str
    bot_message_id: int
    first_message_text: str
    unified_text: str
    channels: list[str]
    start_time: datetime
    end_time: datetime | None
    window_expires_at: datetime
    first_message_strength: FirstMessageStrength
    alert_strength: FirstMessageStrength


class EventTracker:
    """
    At most one open incident at a time (per process).
    An event expires automatically after ACTIVE_EVENT_TTL from its start_time.
    """

    def __init__(self) -> None:
        self._current: ActiveEvent | None = None

    def get_open_event(self) -> ActiveEvent | None:
        """Return the active mergeable event, or None if expired/ended/missing."""
        if self._current is None:
            return None
        ev = self._current
        if ev.end_time is not None:
            self._current = None
            return None
        if _utc_now() >= _ensure_utc(ev.window_expires_at):
            self._current = None
            return None
        return ev

    def create_event(
        self,
        *,
        bot_message_id: int,
        first_message_text: str,
        channel: str,
        start_time: datetime,
        first_message_strength: FirstMessageStrength,
    ) -> ActiveEvent:
        start = _ensure_utc(start_time)
        ev = ActiveEvent(
            event_id=str(uuid.uuid4()),
            bot_message_id=bot_message_id,
            first_message_text=first_message_text,
            unified_text=first_message_text,
            channels=[channel],
            start_time=start,
            end_time=None,
            window_expires_at=start + ACTIVE_EVENT_TTL,
            first_message_strength=first_message_strength,
            alert_strength=first_message_strength,
        )
        self._current = ev
        return ev

    def update_after_merge(self, unified_text: str, channel: str | None) -> None:
        ev = self.get_open_event()
        if ev is None:
            return
        ev.unified_text = unified_text
        if channel and channel not in ev.channels:
            ev.channels.append(channel)

    def end_event(self, end_time: datetime) -> ActiveEvent | None:
        """Mark the current event as ended; returns a snapshot for the final edit."""
        ev = self.get_open_event()
        if ev is None:
            return None
        ev.end_time = _ensure_utc(end_time)
        snapshot = ActiveEvent(
            event_id=ev.event_id,
            bot_message_id=ev.bot_message_id,
            first_message_text=ev.first_message_text,
            unified_text=ev.unified_text,
            channels=list(ev.channels),
            start_time=ev.start_time,
            end_time=ev.end_time,
            window_expires_at=ev.window_expires_at,
            first_message_strength=ev.first_message_strength,
            alert_strength=ev.alert_strength,
        )
        self._current = None
        return snapshot

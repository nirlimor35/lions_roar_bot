"""Single active incident tracker with a configurable merge window."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from components.constants import (
    ACTIVE_INCIDENT_TTL,
    RECENT_OUT_OF_SUBSCRIBER_MAX_UNIFIED_CHARS,
    RECENT_OUT_OF_SUBSCRIBER_WINDOW,
    CloseReason,
    MessagePriority,
)
from components.utils import ensure_utc, utc_now


@dataclass(frozen=True)
class RecentIncidentClosure:
    closed_at: datetime
    channels: frozenset[str]
    unified_text: str
    close_reason: CloseReason | None


@dataclass
class ActiveIncident:
    incident_id: str
    incident_message_id: int
    unified_text: str
    channels: list[str]
    start_time: datetime
    end_time: datetime | None
    expires_at: datetime
    alert_priority: MessagePriority
    log_file_suffix: str
    subject: str | None = None
    source_messages: dict[tuple[int, int], "IncidentSourceMessage"] | None = None


@dataclass
class IncidentSourceMessage:
    channel_id: int
    channel_name: str
    message_id: int
    raw_text: str
    sanitized_text: str
    message_ts: datetime


class IncidentTracker:
    """
    At most one open incident at a time (per process).

    An incident is mergeable until either the LLM marks it ended (`end_incident`) or
    the merge window (ACTIVE_INCIDENT_TTL) elapses. After either, the slot is empty —
    same as a cold start for opening the next incident.
    """

    _PENDING_DELETION_BUFFER_TTL = timedelta(seconds=120)

    def __init__(self) -> None:
        self._current_incident: ActiveIncident | None = None
        self._recent_closed_incident: RecentIncidentClosure | None = None
        self._pending_deletions: dict[tuple[int, int], datetime] = {}

    @staticmethod
    def _normalize_channel_id(channel_id: int) -> int:
        abs_id = abs(int(channel_id))
        as_text = str(abs_id)
        if as_text.startswith("100") and len(as_text) > 3:
            return int(as_text[3:])
        return abs_id

    @classmethod
    def _source_key(cls, channel_id: int, message_id: int) -> tuple[int, int]:
        return (cls._normalize_channel_id(channel_id), int(message_id))

    def has_source_message(self, channel_id: int, message_id: int) -> bool:
        incident = self._current_incident
        if incident is None or incident.source_messages is None:
            return False
        return self._source_key(channel_id, message_id) in incident.source_messages

    @property
    def source_message_count(self) -> int:
        incident = self._current_incident
        if incident is None or not incident.source_messages:
            return 0
        return len(incident.source_messages)

    def remove_source_message(
        self, channel_id: int, message_id: int
    ) -> IncidentSourceMessage | None:
        incident = self._current_incident
        if incident is None or incident.end_time is not None:
            return None
        if not incident.source_messages:
            return None
        key = self._source_key(channel_id, message_id)
        return incident.source_messages.pop(key, None)

    def get_source_sanitized_text(self, channel_id: int, message_id: int) -> str | None:
        incident = self._current_incident
        if incident is None or incident.source_messages is None:
            return None
        entry = incident.source_messages.get(self._source_key(channel_id, message_id))
        if entry is None:
            return None
        return entry.sanitized_text

    def upsert_source_message(
        self,
        *,
        channel_id: int,
        channel_name: str,
        message_id: int,
        raw_text: str,
        sanitized_text: str,
        message_ts: datetime,
    ) -> None:
        incident = self._current_incident
        if incident is None or incident.end_time is not None:
            return
        if incident.source_messages is None:
            incident.source_messages = {}
        key = self._source_key(channel_id, message_id)
        incident.source_messages[key] = IncidentSourceMessage(
            channel_id=self._normalize_channel_id(channel_id),
            channel_name=channel_name,
            message_id=int(message_id),
            raw_text=raw_text,
            sanitized_text=sanitized_text,
            message_ts=ensure_utc(message_ts),
        )

    def joined_remaining_sanitized_sources(self) -> str:
        incident = self._current_incident
        if incident is None or not incident.source_messages:
            return ""
        ordered = sorted(
            incident.source_messages.values(),
            key=lambda item: (
                ensure_utc(item.message_ts),
                item.channel_name,
                item.message_id,
            ),
        )
        parts: list[str] = []
        for item in ordered:
            t = (item.sanitized_text or "").strip()
            if t:
                parts.append(t)
        return "\n".join(parts)

    def source_messages_context(
        self,
        *,
        override_channel_id: int | None = None,
        override_message_id: int | None = None,
        override_sanitized_text: str | None = None,
    ) -> str:
        incident = self._current_incident
        if incident is None or not incident.source_messages:
            return ""
        override_key: tuple[int, int] | None = None
        if (
            override_channel_id is not None
            and override_message_id is not None
            and override_sanitized_text is not None
        ):
            override_key = self._source_key(override_channel_id, override_message_id)
        ordered = sorted(
            incident.source_messages.values(),
            key=lambda item: (
                ensure_utc(item.message_ts),
                item.channel_name,
                item.message_id,
            ),
        )
        lines: list[str] = []
        for item in ordered:
            key = self._source_key(item.channel_id, item.message_id)
            text = (
                override_sanitized_text
                if override_key is not None and key == override_key
                else item.sanitized_text
            )
            lines.append(
                f"- channel={item.channel_name} message_id={item.message_id} text={text}"
            )
        return "\n".join(lines)

    def record_pending_deletion(self, channel_id: int, message_id: int) -> None:
        key = self._source_key(channel_id, message_id)
        self._pending_deletions[key] = utc_now()
        self._evict_stale_pending_deletions()

    def check_pending_deletion(self, channel_id: int, message_id: int) -> bool:
        return self._source_key(channel_id, message_id) in self._pending_deletions

    def _evict_stale_pending_deletions(self) -> None:
        if not self._pending_deletions:
            return
        cutoff = utc_now() - self._PENDING_DELETION_BUFFER_TTL
        self._pending_deletions = {
            k: v for k, v in self._pending_deletions.items() if v > cutoff
        }

    def record_recent_incident_closure(
        self,
        *,
        closed_at: datetime,
        channels: list[str],
        unified_text: str,
        close_reason: CloseReason | None,
    ) -> None:
        self._recent_closed_incident = RecentIncidentClosure(
            closed_at=ensure_utc(closed_at),
            channels=frozenset(channels),
            unified_text=(unified_text or "").strip(),
            close_reason=close_reason,
        )

    def clear_recent_incident_closure(self) -> None:
        self._recent_closed_incident = None

    def recent_closure_prompt_appendix(
        self, *, message_ts: datetime, source_channel: str
    ) -> str | None:
        rec = self._recent_closed_incident
        if rec is None:
            return None
        now = ensure_utc(message_ts)
        if now - rec.closed_at > RECENT_OUT_OF_SUBSCRIBER_WINDOW:
            self._recent_closed_incident = None
            return None
        if source_channel not in rec.channels:
            return None
        text = rec.unified_text
        if len(text) > RECENT_OUT_OF_SUBSCRIBER_MAX_UNIFIED_CHARS:
            text = text[:RECENT_OUT_OF_SUBSCRIBER_MAX_UNIFIED_CHARS] + "…"
        reason = rec.close_reason.value if rec.close_reason else "unknown"
        base = (
            "Additional mandatory context — apply before classifying the incoming message:\n"
            "A prior incident from the same source channels was just closed within five minutes. "
            f"Close reason: {reason}. The last unified narrative was:\n\n"
            f'"""\n{text}\n"""\n\n'
            "If the new message is the same operational thread (same salvo, continuation line, "
            "or a minor wording refinement), do NOT open a new incident. In that case set "
            "qualified=False and priority=none.\n"
            "Only qualify the message if it clearly starts a separate new home-front event."
        )
        if rec.close_reason == CloseReason.OUT_OF_SUBSCRIBER_AREAS:
            return (
                f"{base}\n"
                "When the prior closure reason was out_of_subscriber_areas, be extra strict: "
                "for repeated lines, live-index style headers, or wording that does not clearly "
                "introduce NEW impact or shelter instructions for גבעתיים / גוש דן / המרכז, "
                "you MUST keep qualified=False and priority=none."
            )
        return base

    def get_open_incident(self) -> ActiveIncident | None:
        """Return the active mergeable incident, or None if missing, ended, or past TTL."""
        if self._current_incident is None:
            return None
        incident = self._current_incident
        if incident.end_time is not None:
            self._current_incident = None
            return None
        if utc_now() >= ensure_utc(incident.expires_at):
            self.evict_if_ttl_expired()
            return None
        return self._current_incident

    def evict_if_ttl_expired(self) -> ActiveIncident | None:
        """
        If the merge window has ended and the incident was not explicitly closed,
        clear the slot and return a snapshot (e.g. for logging or a final edit).
        Idempotent: returns None if nothing to evict.
        """
        if self._current_incident is None:
            return None
        incident = self._current_incident
        if incident.end_time is not None:
            return None
        if utc_now() < ensure_utc(incident.expires_at):
            return None
        end_ts = ensure_utc(incident.expires_at)
        snapshot = ActiveIncident(
            incident_id=incident.incident_id,
            incident_message_id=incident.incident_message_id,
            unified_text=incident.unified_text,
            channels=list(incident.channels),
            start_time=incident.start_time,
            end_time=end_ts,
            expires_at=incident.expires_at,
            alert_priority=incident.alert_priority,
            log_file_suffix=incident.log_file_suffix,
            subject=incident.subject,
            source_messages=dict(incident.source_messages or {}),
        )
        self._current_incident = None
        return snapshot

    def set_incident_message_id(self, incident_message_id: int) -> None:
        """Set the destination alert message id after the first send."""
        if self._current_incident is None:
            return
        self._current_incident.incident_message_id = incident_message_id

    def create_incident(
        self,
        *,
        incident_message_id: int = 0,
        unified_text: str,
        channel: str,
        source_channel_id: int,
        source_message_id: int,
        source_raw_text: str,
        source_sanitized_text: str,
        start_time: datetime,
        alert_priority: MessagePriority,
        log_file_suffix: str,
        subject: str | None = None,
    ) -> ActiveIncident:
        start_utc = ensure_utc(start_time)
        expires_at = ensure_utc(start_utc + ACTIVE_INCIDENT_TTL)
        incident = ActiveIncident(
            incident_id=str(uuid.uuid4()),
            incident_message_id=incident_message_id,
            unified_text=unified_text,
            channels=[channel],
            start_time=start_utc,
            end_time=None,
            expires_at=expires_at,
            alert_priority=alert_priority,
            log_file_suffix=log_file_suffix,
            subject=subject,
            source_messages={},
        )
        self._current_incident = incident
        self.upsert_source_message(
            channel_id=source_channel_id,
            channel_name=channel,
            message_id=source_message_id,
            raw_text=source_raw_text,
            sanitized_text=source_sanitized_text,
            message_ts=start_time,
        )
        return incident

    def update_after_merge(
        self,
        unified_text: str | None,
        channel: str | None,
        *,
        alert_priority: MessagePriority | None = None,
    ) -> None:
        if (
            self._current_incident is None
            or self._current_incident.end_time is not None
        ):
            return
        incident = self._current_incident
        if unified_text is not None and unified_text.strip():
            incident.unified_text = unified_text
            if channel and channel not in incident.channels:
                incident.channels.append(channel)
        if alert_priority is not None:
            incident.alert_priority = self._priority_logic(
                incident.alert_priority,
                alert_priority,
            )

    def end_incident(self, end_time: datetime) -> ActiveIncident | None:
        """Mark the current incident as ended; returns a snapshot for the final edit."""
        if (
            self._current_incident is None
            or self._current_incident.end_time is not None
        ):
            return None
        incident = self._current_incident
        incident.end_time = ensure_utc(end_time)
        snapshot = ActiveIncident(
            incident_id=incident.incident_id,
            incident_message_id=incident.incident_message_id,
            unified_text=incident.unified_text,
            channels=list(incident.channels),
            start_time=incident.start_time,
            end_time=incident.end_time,
            expires_at=incident.expires_at,
            alert_priority=incident.alert_priority,
            log_file_suffix=incident.log_file_suffix,
            subject=incident.subject,
            source_messages=dict(incident.source_messages or {}),
        )
        self._current_incident = None
        return snapshot

    @staticmethod
    def _priority_logic(
        original_priority: MessagePriority, new_priority: MessagePriority
    ) -> MessagePriority:
        return new_priority

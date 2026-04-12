import copy
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from loguru import logger

import components.llm.llm_client as LLMClient
from components.constants import (
    CloseReason,
    IncidentHandlerLog,
    MessagePriority,
    MessageType,
    ModuleColors,
)
from components.Incident.log import (
    append_incident_closure,
    append_message,
    new_incident_log_file_suffix,
)
from components.Incident.tracker import (
    ActiveIncident,
    IncidentSourceMessage,
    IncidentTracker,
)
from components.messages import TelegramMessageSender
from components.utils import (
    clamp_word_count,
    ensure_utc,
    fetch_replied_message_text,
    format_time_il_hm,
    json_log_maker,
    sanitize_alert_body_text,
    utc_now,
)


@dataclass
class ExistingIncidentPrep:
    incident_id: str
    incident_snapshot: ActiveIncident
    channel_id: int
    channel_name: str
    raw_text: str
    text: str
    event_type: MessageType
    message_ts: datetime
    message_id: int
    parent_message_id: int | None
    message: object
    source_messages_context: str | None
    is_source_edit: bool
    previous_source_text: str | None


@dataclass
class PendingClosedAlertEdit:
    incident_message_id: int
    channels: list[str]
    unified_text: str
    start_at: datetime
    end_at: datetime | None
    alert_priority: MessagePriority
    close_reason: CloseReason
    incident_start: datetime
    closed_at: datetime
    log_file_suffix: str


@dataclass(frozen=True)
class DeletedMessageGraceClose:
    incident_id: str


@dataclass
class SourceDeletionOutcome:
    removed: list[IncidentSourceMessage]
    grace_close: DeletedMessageGraceClose | None
    reprocess: bool
    incident_id: str


class IncidentHandler:
    def __init__(
        self,
        *,
        client,
        llm: LLMClient.LLMClient,
        telegram_sender: TelegramMessageSender,
        tracker: IncidentTracker,
        cancel_merge_deadline_task: Callable[[], None],
        schedule_informational_grace: Callable[[str], None],
        cancel_informational_grace: Callable[[], None],
        deferred_close_rule: Callable[[CloseReason], tuple[bool, int]],
        schedule_deferred_close: Callable[[str, CloseReason, int], None],
        cancel_deferred_close: Callable[[str], bool],
        has_pending_close_timer: Callable[[], bool],
        get_pending_close_info: Callable[[], tuple[CloseReason, int] | None],
    ) -> None:
        self._client = client
        self._llm = llm
        self._telegram_sender = telegram_sender
        self._tracker = tracker
        self._cancel_merge_deadline_task = cancel_merge_deadline_task
        self._schedule_informational_grace = schedule_informational_grace
        self._cancel_informational_grace = cancel_informational_grace
        self._deferred_close_rule = deferred_close_rule
        self._schedule_deferred_close = schedule_deferred_close
        self._cancel_deferred_close = cancel_deferred_close
        self._has_pending_close_timer = has_pending_close_timer
        self._get_pending_close_info = get_pending_close_info

    async def subject_line_for_closed_incident(
        self,
        *,
        unified_text: str,
        close_reason: CloseReason | None,
        incident_start: datetime,
        closed_at: datetime,
        log_file_suffix: str,
    ) -> str | None:
        llm_subject = await self._llm.summarize_closed_incident_subject(
            unified_text=unified_text,
            close_reason=close_reason,
        )
        raw = (llm_subject or "").strip()
        if raw:
            raw = clamp_word_count(raw, 12)
        if not raw:
            body = (unified_text or "").strip()
            if body:
                raw = clamp_word_count(body.split("\n")[0].strip(), 12)
        final = raw.strip()
        subject = final if final else None
        append_incident_closure(
            incident_start=incident_start,
            closed_at=closed_at,
            subject=subject or "",
            close_reason=close_reason.value if close_reason else None,
            log_file_suffix=log_file_suffix,
        )
        return subject

    def build_existing_incident_prep(
        self,
        *,
        opened_incident: ActiveIncident,
        channel_id: int,
        channel_name: str,
        raw_text: str,
        text: str,
        event_type: MessageType,
        message_ts: datetime,
        message_id: int,
        parent_message_id: int | None,
        message,
    ) -> ExistingIncidentPrep:
        is_source_edit = (
            event_type == MessageType.EDITED_MESSAGE
            and self._tracker.has_source_message(channel_id, message_id)
        )
        previous_source_text = (
            self._tracker.get_source_sanitized_text(channel_id, message_id)
            if is_source_edit
            else None
        )
        source_messages_context = self._tracker.source_messages_context(
            override_channel_id=channel_id if is_source_edit else None,
            override_message_id=message_id if is_source_edit else None,
            override_sanitized_text=text if is_source_edit else None,
        )
        return ExistingIncidentPrep(
            incident_id=opened_incident.incident_id,
            incident_snapshot=copy.deepcopy(opened_incident),
            channel_id=channel_id,
            channel_name=channel_name,
            raw_text=raw_text,
            text=text,
            event_type=event_type,
            message_ts=message_ts,
            message_id=message_id,
            parent_message_id=parent_message_id,
            message=message,
            source_messages_context=source_messages_context,
            is_source_edit=is_source_edit,
            previous_source_text=previous_source_text,
        )

    async def run_existing_incident_llm(
        self, prep: ExistingIncidentPrep
    ) -> LLMClient.LLMResponse:
        reply_parent_text = await fetch_replied_message_text(
            self._client, prep.channel_id, prep.message
        )
        logger.info(
            f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.EXISTING} | {json_log_maker(incident_id=prep.incident_id, channel=prep.channel_name, has_reply_parent=reply_parent_text is not None)} | LLM merge request",
        )
        return await self._llm.run_llm(
            event_message=prep.text,
            parent_message=reply_parent_text or None,
            incident=prep.incident_snapshot,
            message_type=prep.event_type,
            source_messages_context=prep.source_messages_context,
            is_source_edit=prep.is_source_edit,
            edited_message_previous_text=prep.previous_source_text,
            message_ts_il=None if prep.is_source_edit else format_time_il_hm(prep.message_ts),
        )

    async def apply_existing_incident_locked_phase(
        self,
        prep: ExistingIncidentPrep,
        llm_response: LLMClient.LLMResponse,
    ) -> PendingClosedAlertEdit | None:
        opened_incident = self._tracker.get_open_incident()
        if opened_incident is None or opened_incident.incident_id != prep.incident_id:
            logger.info(
                f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.EXISTING} | {json_log_maker(incident_id=prep.incident_id)} | Merge discarded (incident closed or replaced)",
            )
            return None

        pre_merge_unified = opened_incident.unified_text
        pre_merge_channels = list(opened_incident.channels)
        pre_merge_priority = opened_incident.alert_priority
        is_source_edit = prep.is_source_edit
        channel_id = prep.channel_id
        channel_name = prep.channel_name
        raw_text = prep.raw_text
        text = prep.text
        event_type = prep.event_type
        message_ts = prep.message_ts
        message_id = prep.message_id
        parent_message_id = prep.parent_message_id

        if (
            is_source_edit
            and llm_response is not None
            and llm_response.related is False
        ):
            logger.warning(
                f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.EXISTING} | {json_log_maker(incident_id=opened_incident.incident_id, message_id=message_id)} | Source-edit returned related=False; coercing to related=True",
            )
            llm_response.related = True

        if is_source_edit:
            self._tracker.upsert_source_message(
                channel_id=channel_id,
                channel_name=channel_name,
                message_id=message_id,
                raw_text=raw_text,
                sanitized_text=text,
                message_ts=message_ts,
            )

        has_response_text = (
            bool((llm_response.response_message or "").strip())
            if llm_response
            else False
        )
        if (
            llm_response is None
            or (not is_source_edit and llm_response.related is False)
            or (
                not llm_response.qualified
                and not llm_response.ended
                and not llm_response.related
                and (not is_source_edit or not has_response_text)
            )
        ):
            logger.info(
                f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.EXISTING} | {json_log_maker(incident_id=opened_incident.incident_id, related=getattr(llm_response, 'related', None), qualified=getattr(llm_response, 'qualified', None), ended=getattr(llm_response, 'ended', None), reasoning=getattr(llm_response, 'reasoning', None))} | LLM result ignored",
            )
            return None

        if not is_source_edit:
            self._tracker.upsert_source_message(
                channel_id=channel_id,
                channel_name=channel_name,
                message_id=message_id,
                raw_text=raw_text,
                sanitized_text=text,
                message_ts=message_ts,
            )

        append_message(
            channel_name=channel_name,
            message=raw_text,
            message_dt=message_ts,
            incident_start=opened_incident.start_time,
            message_id=message_id,
            parent_message_id=parent_message_id,
            llm_response=llm_response.to_log_dict(),
            log_file_suffix=opened_incident.log_file_suffix,
            event_type=event_type.value,
        )

        stripped = (llm_response.response_message or "").strip()
        self._tracker.update_after_merge(
            stripped if stripped else None,
            channel_name if stripped else None,
            alert_priority=llm_response.priority if llm_response.qualified or llm_response.ended else None,
        )
        if stripped:
            logger.info(
                f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.EXISTING} | {json_log_maker(incident_id=opened_incident.incident_id)} | Tracker merged text",
            )

        canceled_deferred_close = False
        close_timer_locked = self._has_pending_close_timer()
        pending_deferred = self._get_pending_close_info()
        pending_deferred_reason = pending_deferred[0] if pending_deferred else None
        if close_timer_locked:
            merged_incident = self._tracker.get_open_incident()
            escalated_to_high = (
                merged_incident is not None
                and merged_incident.alert_priority == MessagePriority.HIGH
            )
            cancel_for_source_deleted = (
                pending_deferred_reason == CloseReason.SOURCE_DELETED
            )
            cancel_for_active_signal = (
                llm_response is not None
                and not llm_response.ended
                and llm_response.qualified
            )
            if (
                escalated_to_high
                or cancel_for_source_deleted
                or cancel_for_active_signal
            ):
                canceled_deferred_close = self._cancel_deferred_close(
                    opened_incident.incident_id
                )
                self._cancel_informational_grace()
                close_timer_locked = False
                if escalated_to_high:
                    reason_log = "priority escalated to high"
                elif cancel_for_source_deleted:
                    reason_log = "source-deleted grace cancelled"
                else:
                    reason_log = "active merge signal cancelled pending close"
                logger.info(
                    f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.EXISTING} | {json_log_maker(incident_id=opened_incident.incident_id, ended=llm_response.ended)} | Close timer overridden — {reason_log}",
                )
            else:
                logger.info(
                    f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.EXISTING} | {json_log_maker(incident_id=opened_incident.incident_id, ended=llm_response.ended)} | Close timer active — skipping timer logic",
                )

        if not llm_response.ended and not close_timer_locked:
            canceled_deferred_close = self._cancel_deferred_close(
                opened_incident.incident_id
            )
            grace_incident = self._tracker.get_open_incident()
            if grace_incident is not None:
                if grace_incident.alert_priority in (
                    MessagePriority.INFORMATIONAL,
                    MessagePriority.NONE,
                ):
                    newly_informational = pre_merge_priority not in (
                        MessagePriority.INFORMATIONAL,
                        MessagePriority.NONE,
                    )
                    if newly_informational or canceled_deferred_close:
                        self._schedule_informational_grace(grace_incident.incident_id)
                else:
                    self._cancel_informational_grace()

        if llm_response.ended and not close_timer_locked:
            close_reason = llm_response.close_reason or CloseReason.ALL_CLEAR
            should_defer, defer_seconds = self._deferred_close_rule(close_reason)
            if should_defer and defer_seconds > 0:
                self._schedule_deferred_close(
                    opened_incident.incident_id,
                    close_reason,
                    defer_seconds,
                )
                open_incident = self._tracker.get_open_incident()
                if open_incident is not None and open_incident.incident_message_id:
                    await self._telegram_sender.edit_alert(
                        open_incident.incident_message_id,
                        channels=list(open_incident.channels),
                        unified_text=open_incident.unified_text,
                        start_at=open_incident.start_time,
                        ended_at=None,
                        alert_priority=open_incident.alert_priority,
                        subject=open_incident.subject,
                        pending_close_reason=close_reason,
                        pending_close_seconds=defer_seconds,
                    )
                logger.info(
                    f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.ENDED_CANDIDATE} | {json_log_maker(incident_id=opened_incident.incident_id, close_reason=close_reason, deferred_seconds=defer_seconds)} | Deferred close scheduled",
                )
                return None
            logger.info(
                f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.ENDED} | {json_log_maker(incident_id=opened_incident.incident_id, close_reason=close_reason)} | LLM ended incident",
            )
            self._cancel_deferred_close(opened_incident.incident_id)
            snapshot = self._tracker.end_incident(message_ts)
            self._cancel_merge_deadline_task()
            closed_at_outer: datetime | None = None
            if snapshot is not None:
                closed_at_outer = snapshot.end_time or ensure_utc(message_ts)
            if snapshot and closed_at_outer is not None:
                self._tracker.record_recent_incident_closure(
                    closed_at=closed_at_outer,
                    channels=list(snapshot.channels),
                    unified_text=snapshot.unified_text,
                    close_reason=close_reason,
                )
            if (
                snapshot
                and snapshot.incident_message_id
                and closed_at_outer is not None
            ):
                return PendingClosedAlertEdit(
                    incident_message_id=snapshot.incident_message_id,
                    channels=list(snapshot.channels),
                    unified_text=snapshot.unified_text,
                    start_at=snapshot.start_time,
                    end_at=snapshot.end_time,
                    alert_priority=snapshot.alert_priority,
                    close_reason=close_reason,
                    incident_start=snapshot.start_time,
                    closed_at=closed_at_outer,
                    log_file_suffix=snapshot.log_file_suffix,
                )
            return None

        open_incident = self._tracker.get_open_incident()
        if open_incident is None:
            logger.info(
                f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.EXISTING} | {json_log_maker(incident_id=prep.incident_id)} | No open slot after merge (already cleared)",
            )
            return None
        if not open_incident.incident_message_id:
            logger.info(
                f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.EXISTING} | {json_log_maker(incident_id=open_incident.incident_id)} | Recovery send (missing destination message_id)",
            )
            sent_message_id = await self._telegram_sender.send_alert(
                channels=list(open_incident.channels),
                unified_text=open_incident.unified_text,
                start_at=open_incident.start_time,
                alert_priority=open_incident.alert_priority,
                subject=open_incident.subject,
            )
            self._tracker.set_incident_message_id(sent_message_id)
            logger.info(
                f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.EXISTING} | {json_log_maker(incident_id=open_incident.incident_id, incident_message_id=sent_message_id)} | Recovery send stored",
            )
            return None
        if (
            open_incident.unified_text == pre_merge_unified
            and open_incident.alert_priority == pre_merge_priority
            and list(open_incident.channels) == pre_merge_channels
            and not canceled_deferred_close
        ):
            logger.info(
                f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.EXISTING} | {json_log_maker(incident_id=open_incident.incident_id)} | No Telegram edit (unchanged after merge)",
            )
            return None
        pending_close = self._get_pending_close_info()
        await self._telegram_sender.edit_alert(
            open_incident.incident_message_id,
            channels=list(open_incident.channels),
            unified_text=open_incident.unified_text,
            start_at=open_incident.start_time,
            ended_at=None,
            alert_priority=open_incident.alert_priority,
            subject=open_incident.subject,
            pending_close_reason=pending_close[0] if pending_close else None,
            pending_close_seconds=pending_close[1] if pending_close else None,
        )
        logger.info(
            f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.EXISTING} | {json_log_maker(incident_id=open_incident.incident_id, message_id=open_incident.incident_message_id)} | Destination alert edited (merged)",
        )
        return None

    def handle_message_deletion(
        self,
        *,
        channel_id: int,
        deleted_message_ids: list[int],
        message_ts: datetime,
    ) -> SourceDeletionOutcome | None:
        opened = self._tracker.get_open_incident()
        if opened is None:
            return None
        removed: list[IncidentSourceMessage] = []
        for mid in deleted_message_ids:
            if self._tracker.has_source_message(channel_id, mid):
                entry = self._tracker.remove_source_message(channel_id, mid)
                if entry is not None:
                    removed.append(entry)
        if not removed:
            return None
        incident_start = opened.start_time
        log_suffix = opened.log_file_suffix
        for ent in removed:
            append_message(
                channel_name=ent.channel_name,
                message=ent.raw_text,
                message_dt=message_ts,
                incident_start=incident_start,
                message_id=ent.message_id,
                parent_message_id=None,
                llm_response={"source_deleted": True},
                log_file_suffix=log_suffix,
                event_type=MessageType.DELETED_MESSAGE.value,
            )
        iid = opened.incident_id
        if self._tracker.source_message_count == 0:
            return SourceDeletionOutcome(
                removed=removed,
                grace_close=DeletedMessageGraceClose(incident_id=iid),
                reprocess=False,
                incident_id=iid,
            )
        return SourceDeletionOutcome(
            removed=removed,
            grace_close=None,
            reprocess=True,
            incident_id=iid,
        )

    async def apply_reprocess_after_deletion(
        self,
        *,
        incident_id: str,
        llm_response: LLMClient.LLMResponse,
    ) -> PendingClosedAlertEdit | None:
        opened_incident = self._tracker.get_open_incident()
        if opened_incident is None or opened_incident.incident_id != incident_id:
            logger.info(
                f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.EXISTING} | {json_log_maker(incident_id=incident_id)} | Reprocess-after-deletion discarded (incident closed or replaced)",
            )
            return None

        pre_merge_unified = opened_incident.unified_text
        pre_merge_channels = list(opened_incident.channels)
        pre_merge_priority = opened_incident.alert_priority

        if llm_response is not None and llm_response.related is False:
            logger.warning(
                f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.EXISTING} | {json_log_maker(incident_id=opened_incident.incident_id)} | Reprocess returned related=False; coercing to related=True",
            )
            llm_response.related = True

        stripped = (llm_response.response_message or "").strip() if llm_response else ""
        ignored = llm_response is None or (
            not llm_response.qualified and not llm_response.ended and not stripped
        )
        if ignored:
            fb_raw = self._tracker.joined_remaining_sanitized_sources()
            fb = sanitize_alert_body_text(fb_raw) if fb_raw else ""
            if not fb:
                logger.info(
                    f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.EXISTING} | {json_log_maker(incident_id=opened_incident.incident_id)} | Reprocess ignored and no fallback text",
                )
                return None
            self._tracker.update_after_merge(
                fb, None, alert_priority=pre_merge_priority
            )
            logger.info(
                f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.EXISTING} | {json_log_maker(incident_id=opened_incident.incident_id)} | Reprocess fallback from remaining sources",
            )
        else:
            self._tracker.update_after_merge(
                stripped if stripped else None,
                None,
                alert_priority=llm_response.priority,
            )
            if stripped:
                logger.info(
                    f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.EXISTING} | {json_log_maker(incident_id=opened_incident.incident_id)} | Tracker reprocessed text",
                )

        reprocess_ts = utc_now()
        canceled_deferred_close = False
        close_timer_locked = self._has_pending_close_timer()
        pending_deferred = self._get_pending_close_info()
        pending_deferred_reason = pending_deferred[0] if pending_deferred else None
        if close_timer_locked:
            merged_incident = self._tracker.get_open_incident()
            escalated_to_high = (
                merged_incident is not None
                and merged_incident.alert_priority == MessagePriority.HIGH
            )
            cancel_for_source_deleted = (
                pending_deferred_reason == CloseReason.SOURCE_DELETED
                and self._tracker.source_message_count > 0
            )
            cancel_for_active_signal = (
                llm_response is not None
                and not llm_response.ended
                and llm_response.qualified
            )
            if (
                escalated_to_high
                or cancel_for_source_deleted
                or cancel_for_active_signal
            ):
                canceled_deferred_close = self._cancel_deferred_close(
                    opened_incident.incident_id
                )
                self._cancel_informational_grace()
                close_timer_locked = False
                if escalated_to_high:
                    reason_log = "priority escalated to high"
                elif cancel_for_source_deleted:
                    reason_log = "source-deleted grace cancelled"
                else:
                    reason_log = "active reprocess signal cancelled pending close"
                logger.info(
                    f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.EXISTING} | {json_log_maker(incident_id=opened_incident.incident_id)} | Close timer overridden — {reason_log}",
                )
            else:
                logger.info(
                    f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.EXISTING} | {json_log_maker(incident_id=opened_incident.incident_id)} | Close timer active — skipping timer logic",
                )

        eff = llm_response if llm_response is not None else None
        ended_flag = bool(eff and eff.ended)
        if not ended_flag and not close_timer_locked:
            canceled_deferred_close = self._cancel_deferred_close(
                opened_incident.incident_id
            )
            grace_incident = self._tracker.get_open_incident()
            if grace_incident is not None:
                if grace_incident.alert_priority in (
                    MessagePriority.INFORMATIONAL,
                    MessagePriority.NONE,
                ):
                    newly_informational = pre_merge_priority not in (
                        MessagePriority.INFORMATIONAL,
                        MessagePriority.NONE,
                    )
                    if newly_informational or canceled_deferred_close:
                        self._schedule_informational_grace(grace_incident.incident_id)
                else:
                    self._cancel_informational_grace()

        if ended_flag and not close_timer_locked and eff:
            close_reason = eff.close_reason or CloseReason.ALL_CLEAR
            should_defer, defer_seconds = self._deferred_close_rule(close_reason)
            if should_defer and defer_seconds > 0:
                self._schedule_deferred_close(
                    opened_incident.incident_id,
                    close_reason,
                    defer_seconds,
                )
                open_incident = self._tracker.get_open_incident()
                if open_incident is not None and open_incident.incident_message_id:
                    await self._telegram_sender.edit_alert(
                        open_incident.incident_message_id,
                        channels=list(open_incident.channels),
                        unified_text=open_incident.unified_text,
                        start_at=open_incident.start_time,
                        ended_at=None,
                        alert_priority=open_incident.alert_priority,
                        subject=open_incident.subject,
                        pending_close_reason=close_reason,
                        pending_close_seconds=defer_seconds,
                    )
                logger.info(
                    f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.ENDED_CANDIDATE} | {json_log_maker(incident_id=opened_incident.incident_id, close_reason=close_reason, deferred_seconds=defer_seconds)} | Deferred close scheduled (reprocess)",
                )
                return None
            logger.info(
                f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.ENDED} | {json_log_maker(incident_id=opened_incident.incident_id, close_reason=close_reason)} | LLM ended incident (reprocess)",
            )
            self._cancel_deferred_close(opened_incident.incident_id)
            snapshot = self._tracker.end_incident(reprocess_ts)
            self._cancel_merge_deadline_task()
            closed_at_outer: datetime | None = None
            if snapshot is not None:
                closed_at_outer = snapshot.end_time or ensure_utc(reprocess_ts)
            if snapshot and closed_at_outer is not None:
                self._tracker.record_recent_incident_closure(
                    closed_at=closed_at_outer,
                    channels=list(snapshot.channels),
                    unified_text=snapshot.unified_text,
                    close_reason=close_reason,
                )
            if (
                snapshot
                and snapshot.incident_message_id
                and closed_at_outer is not None
            ):
                return PendingClosedAlertEdit(
                    incident_message_id=snapshot.incident_message_id,
                    channels=list(snapshot.channels),
                    unified_text=snapshot.unified_text,
                    start_at=snapshot.start_time,
                    end_at=snapshot.end_time,
                    alert_priority=snapshot.alert_priority,
                    close_reason=close_reason,
                    incident_start=snapshot.start_time,
                    closed_at=closed_at_outer,
                    log_file_suffix=snapshot.log_file_suffix,
                )
            return None

        open_incident = self._tracker.get_open_incident()
        if open_incident is None:
            logger.info(
                f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.EXISTING} | {json_log_maker(incident_id=incident_id)} | No open slot after reprocess (already cleared)",
            )
            return None
        if not open_incident.incident_message_id:
            logger.info(
                f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.EXISTING} | {json_log_maker(incident_id=open_incident.incident_id)} | Recovery send (reprocess, missing destination message_id)",
            )
            sent_message_id = await self._telegram_sender.send_alert(
                channels=list(open_incident.channels),
                unified_text=open_incident.unified_text,
                start_at=open_incident.start_time,
                alert_priority=open_incident.alert_priority,
                subject=open_incident.subject,
            )
            self._tracker.set_incident_message_id(sent_message_id)
            logger.info(
                f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.EXISTING} | {json_log_maker(incident_id=open_incident.incident_id, incident_message_id=sent_message_id)} | Recovery send stored (reprocess)",
            )
            return None
        if (
            open_incident.unified_text == pre_merge_unified
            and open_incident.alert_priority == pre_merge_priority
            and list(open_incident.channels) == pre_merge_channels
            and not canceled_deferred_close
        ):
            logger.info(
                f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.EXISTING} | {json_log_maker(incident_id=open_incident.incident_id)} | No Telegram edit (unchanged after reprocess)",
            )
            return None
        pending_close = self._get_pending_close_info()
        await self._telegram_sender.edit_alert(
            open_incident.incident_message_id,
            channels=list(open_incident.channels),
            unified_text=open_incident.unified_text,
            start_at=open_incident.start_time,
            ended_at=None,
            alert_priority=open_incident.alert_priority,
            subject=open_incident.subject,
            pending_close_reason=pending_close[0] if pending_close else None,
            pending_close_seconds=pending_close[1] if pending_close else None,
        )
        logger.info(
            f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.EXISTING} | {json_log_maker(incident_id=open_incident.incident_id, message_id=open_incident.incident_message_id)} | Destination alert edited (reprocess)",
        )
        return None

    async def run_new_incident_qualification_llm(
        self,
        *,
        channel_id: int,
        channel_name: str,
        text: str,
        event_type: MessageType,
        message,
        recent_closure_appendix: str | None,
    ) -> LLMClient.LLMResponse:
        logger.info(
            f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.NEW} | {json_log_maker(channel=channel_name)} | LLM qualification request",
        )
        reply_parent_text = await fetch_replied_message_text(
            self._client, channel_id, message
        )
        return await self._llm.run_llm(
            event_message=text,
            incident=None,
            message_type=event_type,
            parent_message=reply_parent_text or None,
            recent_closure_appendix=recent_closure_appendix,
        )

    async def commit_new_incident_after_llm(
        self,
        *,
        channel_id: int,
        channel_name: str,
        raw_text: str,
        text: str,
        event_type: MessageType,
        message_ts: datetime,
        message_id: int,
        parent_message_id: int | None,
        response: LLMClient.LLMResponse,
    ) -> datetime | None:
        if self._tracker.get_open_incident() is not None:
            logger.warning(
                f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.NEW} | {json_log_maker(channel=channel_name)} | Open slot already occupied; discarding new-incident LLM result",
            )
            return None
        if (
            response is None
            or not response.qualified
            or response.priority == MessagePriority.NONE
        ):
            logger.info(
                f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.NOT_OPENED} | {json_log_maker(channel=channel_name, qualified=getattr(response, 'qualified', None), priority=getattr(response, 'priority', None), reasoning=getattr(response, 'reasoning', None))}",
            )
            return None

        log_file_suffix = new_incident_log_file_suffix()

        append_message(
            channel_name=channel_name,
            message=raw_text,
            message_dt=message_ts,
            incident_start=message_ts,
            message_id=message_id,
            parent_message_id=parent_message_id,
            llm_response=response.to_log_dict(),
            log_file_suffix=log_file_suffix,
            event_type=event_type.value,
        )

        initial_text = (
            sanitize_alert_body_text(response.response_message)
            if response.response_message
            else text
        ).strip()

        if not initial_text:
            logger.info(
                f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.NOT_OPENED} | {json_log_maker(channel=channel_name)} | Empty body after sanitize",
            )
            return None

        incident_message_id = await self._telegram_sender.send_alert(
            channels=[channel_name],
            unified_text=initial_text,
            start_at=message_ts,
            alert_priority=response.priority,
            subject=None,
        )
        logger.info(
            f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.OPENED} | {json_log_maker(channel=channel_name, destination_message_id=incident_message_id, priority=response.priority)} | Alert sent to destination",
        )
        created = self._tracker.create_incident(
            incident_message_id=incident_message_id,
            unified_text=initial_text,
            channel=channel_name,
            source_channel_id=channel_id,
            source_message_id=message_id,
            source_raw_text=raw_text,
            source_sanitized_text=text,
            start_time=message_ts,
            alert_priority=response.priority,
            log_file_suffix=log_file_suffix,
            subject=None,
        )
        self._tracker.clear_recent_incident_closure()
        logger.info(
            f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.OPENED} | {json_log_maker(incident_id=created.incident_id, incident_message_id=incident_message_id, priority=response.priority, merge_expires_at=ensure_utc(created.expires_at).isoformat())} | Tracker slot created",
        )
        if created.alert_priority in (
            MessagePriority.INFORMATIONAL,
            MessagePriority.NONE,
        ):
            self._schedule_informational_grace(created.incident_id)
        return created.expires_at

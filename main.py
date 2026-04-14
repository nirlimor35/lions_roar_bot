import asyncio
import copy
import os
import sys
from datetime import datetime, timedelta

import yaml
from loguru import logger
from telethon import TelegramClient, events

from components.bot_admin import (
    is_manual_close_command,
    parse_manual_close_command,
    run_bot_dm_updates_loop,
)
from components.constants import (
    INFORMATIONAL_GRACE_PERIOD,
    CloseReason,
    IncidentHandlerLog,
    MessagePriority,
    MessageType,
    ModuleColors,
)
from components.handle_wm import ChannelWatermarks, EditTextCache
from components.Incident.handler import (
    ExistingIncidentPrep,
    IncidentHandler,
    PendingClosedAlertEdit,
)
from components.Incident.tracker import ActiveIncident, IncidentTracker
from components.llm.groq_client import GroqClient
from components.llm.llm_client import LLMClient
from components.messages import TelegramMessageSender
from components.utils import (
    ensure_utc,
    get_reply_message_id,
    json_log_maker,
    message_contains_video,
    message_timestamp_for_deletion_event,
    message_timestamp_for_incident,
    monitored_chats_list,
    resolve_monitored_peer_ids,
    resolve_source_chat,
    sanitize_alert_body_text,
    to_il_tz,
    utc_now,
)


def _pair_from_llm_models(
    raw: dict | None, provider: str
) -> tuple[str | None, str | None]:
    if not isinstance(raw, dict):
        return None, None
    block = raw.get(provider)
    if isinstance(block, dict):
        d = block.get("day")
        n = block.get("night")
        return (
            str(d).strip() if d else None,
            str(n).strip() if n else None,
        )
    if provider == "openai":
        d, n = raw.get("day"), raw.get("night")
        if isinstance(d, str) or isinstance(n, str):
            return (
                str(d).strip() if isinstance(d, str) and d else None,
                str(n).strip() if isinstance(n, str) and n else None,
            )
    return None, None


class LionsRoar:
    # Class-level load so config is available before __init__ (used by class attributes below).
    with open(f"{os.path.dirname(__file__)}/config.yaml", "r") as f:
        config = yaml.safe_load(f.read())

    session_name = config.get("session_name")
    app_id = config.get("app_id")
    api_hash = config.get("api_hash")
    is_debug = config.get("is_debug")

    destination_chat_id = config.get(
        "destination_chat_id_debug" if is_debug else "destination_chat_id"
    )
    monitored_chats = config.get("monitored_chats")

    used_llm = (config.get("used_llm") or "openai").strip().lower()
    _llm_type_raw = (config.get("llm_type") or config.get("used_llm") or "openai").strip().lower()
    llm_type = _llm_type_raw if _llm_type_raw in ("openai", "groq") else "openai"
    _llm_models = config.get("LLM_models")
    _llm_models = _llm_models if isinstance(_llm_models, dict) else {}
    _openai_day, _openai_night = _pair_from_llm_models(_llm_models, "openai")
    _groq_day, _groq_night = _pair_from_llm_models(_llm_models, "groq")
    if llm_type == "groq":
        day_model = _groq_day or "llama-3.1-8b-instant"
        night_model = _groq_night or "openai/gpt-oss-120b"
    else:
        day_model = _openai_day or "gpt-5.4-mini"
        night_model = _openai_night or "gpt-5.4"
    openai_api_key = config.get("openai_api_key")
    groq_api_key = config.get("groq_api_key")

    # Bot credentials
    bot_token = config.get("bot_token")

    def __init__(self):
        cfg = type(self).config
        # Dedupe by channel message id; tracker lock for short atomic mutations; semaphore
        # serializes one channel pipeline at a time so LLM can run without holding the tracker lock.
        self._watermarks = ChannelWatermarks()
        self._edit_text_cache = EditTextCache()
        self._open_incident_lock = asyncio.Lock()
        self._incident_pipeline_sem = asyncio.Semaphore(1)
        self._client = TelegramClient(self.session_name, self.app_id, self.api_hash)
        self._tracker = IncidentTracker()
        if self.llm_type == "groq":
            if not self.groq_api_key:
                logger.error(
                    f"{ModuleColors.MAIN} | {json_log_maker(llm_type=self.llm_type)} | groq_api_key missing"
                )
                sys.exit(1)
            self._llm = GroqClient(
                api_key=self.groq_api_key,
                model=self._resolve_model_for_current_israel_time,
            )
        else:
            self._llm = LLMClient(
                api_key=self.openai_api_key,
                model=self._resolve_model_for_current_israel_time,
            )
        tb_cfg = cfg.get("telegram_bot_api")
        tb_section = tb_cfg if isinstance(tb_cfg, dict) else {}
        self._telegram_sender = TelegramMessageSender(
            bot_token=self.bot_token,
            chat_id=self.destination_chat_id,
            api_max_attempts=max(1, int(tb_section.get("max_attempts", 6))),
            rate_limit_fallback_base_seconds=float(
                tb_section.get("rate_limit_base_seconds", 2.0)
            ),
            rate_limit_fallback_max_seconds=float(
                tb_section.get("rate_limit_max_seconds", 90.0)
            ),
        )
        self._incident_handler = IncidentHandler(
            client=self._client,
            llm=self._llm,
            telegram_sender=self._telegram_sender,
            tracker=self._tracker,
            cancel_merge_deadline_task=self._cancel_merge_deadline_task,
            schedule_informational_grace=self._schedule_informational_grace,
            cancel_informational_grace=self._cancel_informational_grace,
            deferred_close_rule=self._deferred_close_rule,
            schedule_deferred_close=self._schedule_deferred_close,
            cancel_deferred_close=self._cancel_deferred_close,
            has_pending_close_timer=self._has_pending_close_timer,
            get_pending_close_info=self._get_pending_close_info,
        )
        self._merge_deadline_task: asyncio.Task | None = None
        self._informational_grace_task: asyncio.Task | None = None
        self._deferred_close_task: asyncio.Task | None = None
        self._deferred_close_incident_id: str | None = None
        self._deferred_close_reason: CloseReason | None = None
        self._deferred_close_fire_at: datetime | None = None
        self._admin_command_chat_id: int | None = None
        self._admin_user_ids: frozenset[int] = frozenset()
        self._monitored_peer_ids: frozenset[int] | None = None
        # Used by _process_message_with_retries: cap attempts and grow delay as 1s, 2s, 4s, ...
        self._message_process_max_attempts = max(
            1, int(cfg.get("message_processing_max_attempts", 3))
        )
        self._message_process_retry_base_sec = float(
            cfg.get("message_processing_retry_base_seconds", 1.0)
        )
        self._deferred_close_config = self._load_deferred_close_config(cfg)
        logger.info(
            f"{ModuleColors.MAIN} | {json_log_maker(deferred_close=self._deferred_close_config)} | Deferred-close config loaded"
        )

    def _resolve_model_for_current_israel_time(self) -> str:
        israel_now = to_il_tz(utc_now())
        minutes_since_midnight = (israel_now.hour * 60) + israel_now.minute
        is_night_window = minutes_since_midnight >= (
            18 * 60 + 30
        ) or minutes_since_midnight < (8 * 60)
        return self.night_model if is_night_window else self.day_model

    @staticmethod
    def _deferred_close_defaults() -> dict[str, dict[str, int | bool]]:
        return {
            CloseReason.ALL_CLEAR.value: {"enabled": True, "seconds": 120},
            CloseReason.OUT_OF_SUBSCRIBER_AREAS.value: {
                "enabled": True,
                "seconds": 120,
            },
            CloseReason.SOURCE_DELETED.value: {"enabled": True, "seconds": 120},
            CloseReason.INFORMATIONAL_GRACE.value: {"enabled": False, "seconds": 0},
            CloseReason.TTL.value: {"enabled": False, "seconds": 0},
            CloseReason.MANUAL.value: {"enabled": False, "seconds": 0},
        }

    @staticmethod
    def _coerce_bool(value, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "on"}:
                return True
            if lowered in {"0", "false", "no", "off"}:
                return False
        if isinstance(value, int):
            return value != 0
        return default

    @staticmethod
    def _coerce_non_negative_seconds(value, default: int) -> int:
        if isinstance(value, bool):
            return default
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return max(0, parsed)

    def _load_deferred_close_config(
        self, cfg: dict
    ) -> dict[str, dict[str, int | bool]]:
        defaults = self._deferred_close_defaults()
        loaded = cfg.get("deferred_close")
        deferred_close_section = loaded if isinstance(loaded, dict) else {}
        result: dict[str, dict[str, int | bool]] = {}
        for reason_value, reason_defaults in defaults.items():
            reason_cfg = deferred_close_section.get(reason_value)
            reason_section = reason_cfg if isinstance(reason_cfg, dict) else {}
            enabled = self._coerce_bool(
                reason_section.get("enabled"),
                bool(reason_defaults["enabled"]),
            )
            seconds = self._coerce_non_negative_seconds(
                reason_section.get("seconds"),
                int(reason_defaults["seconds"]),
            )
            result[reason_value] = {"enabled": enabled, "seconds": seconds}
        return result

    def _deferred_close_rule(self, close_reason: CloseReason) -> tuple[bool, int]:
        if close_reason == CloseReason.MANUAL:
            return False, 0
        section = self._deferred_close_config.get(
            close_reason.value, {"enabled": False, "seconds": 0}
        )
        return bool(section["enabled"]), int(section["seconds"])

    def _cancel_deferred_close(self, incident_id: str | None = None) -> bool:
        task = self._deferred_close_task
        if task is None or task.done():
            self._deferred_close_task = None
            self._deferred_close_incident_id = None
            self._deferred_close_reason = None
            self._deferred_close_fire_at = None
            return False
        if incident_id is not None and self._deferred_close_incident_id != incident_id:
            return False
        logger.info(
            f"{ModuleColors.MAIN} | {json_log_maker(incident_id=self._deferred_close_incident_id)} | Cancelling deferred-close task"
        )
        task.cancel()
        self._deferred_close_task = None
        self._deferred_close_incident_id = None
        self._deferred_close_reason = None
        self._deferred_close_fire_at = None
        return True

    def _has_pending_close_timer(self) -> bool:
        if (
            self._deferred_close_task is not None
            and not self._deferred_close_task.done()
        ):
            return True
        if (
            self._informational_grace_task is not None
            and not self._informational_grace_task.done()
        ):
            return True
        return False

    def _get_pending_close_info(self) -> tuple[CloseReason, int] | None:
        if (
            self._deferred_close_task is not None
            and not self._deferred_close_task.done()
            and self._deferred_close_reason is not None
            and self._deferred_close_fire_at is not None
        ):
            remaining = max(
                0, int((self._deferred_close_fire_at - utc_now()).total_seconds())
            )
            return (self._deferred_close_reason, remaining)
        return None

    def _schedule_deferred_close(
        self, incident_id: str, close_reason: CloseReason, delay_seconds: int
    ) -> None:
        self._cancel_deferred_close()
        logger.info(
            f"{ModuleColors.MAIN} | {json_log_maker(incident_id=incident_id, close_reason=close_reason, delay_s=delay_seconds)} | Scheduling deferred-close task"
        )
        self._deferred_close_incident_id = incident_id
        self._deferred_close_reason = close_reason
        self._deferred_close_fire_at = ensure_utc(
            utc_now() + timedelta(seconds=delay_seconds)
        )
        self._deferred_close_task = asyncio.create_task(
            self._fire_deferred_close(incident_id, close_reason, delay_seconds)
        )

    async def _fire_deferred_close(
        self, incident_id: str, close_reason: CloseReason, delay_seconds: int
    ) -> None:
        me = asyncio.current_task()
        try:
            delay = max(0.0, float(delay_seconds))
            if delay > 0:
                await asyncio.sleep(delay)
            async with self._open_incident_lock:
                opened = self._tracker.get_open_incident()
                if opened is None or opened.incident_id != incident_id:
                    logger.info(
                        f"{ModuleColors.MAIN} | {json_log_maker(incident_id=incident_id, close_reason=close_reason)} | Deferred-close fired | skip (incident not open/mismatched)"
                    )
                    return
                snapshot = self._tracker.end_incident(utc_now())
            if snapshot is None:
                return
            self._cancel_merge_deadline_task()
            if snapshot.end_time is not None:
                self._tracker.record_recent_incident_closure(
                    closed_at=snapshot.end_time,
                    channels=list(snapshot.channels),
                    unified_text=snapshot.unified_text,
                    close_reason=close_reason,
                )
            closed_subject = None
            if snapshot.end_time is not None:
                closed_subject = (
                    await self._incident_handler.subject_line_for_closed_incident(
                        unified_text=snapshot.unified_text,
                        close_reason=close_reason,
                        incident_start=snapshot.start_time,
                        closed_at=snapshot.end_time,
                        log_file_suffix=snapshot.log_file_suffix,
                    )
                )
            if snapshot.incident_message_id:
                try:
                    await self._telegram_sender.edit_alert(
                        snapshot.incident_message_id,
                        channels=list(snapshot.channels),
                        unified_text=snapshot.unified_text,
                        start_at=snapshot.start_time,
                        ended_at=snapshot.end_time,
                        alert_priority=snapshot.alert_priority,
                        close_reason=close_reason,
                        subject=closed_subject,
                    )
                except Exception:
                    logger.exception(
                        f"{ModuleColors.INCIDENT_HANDLER} | Failed to edit alert after deferred close"
                    )
                else:
                    logger.info(
                        f"{ModuleColors.INCIDENT_HANDLER} | {json_log_maker(incident_id=snapshot.incident_id, message_id=snapshot.incident_message_id, close_reason=close_reason)} | Deferred-close destination alert edited"
                    )
            logger.info(
                f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.ENDED} | {json_log_maker(incident_id=snapshot.incident_id, close_reason=close_reason)} | Incident closed after deferred close"
            )
        except asyncio.CancelledError:
            raise
        finally:
            if me is not None and self._deferred_close_task is me:
                self._deferred_close_task = None
                self._deferred_close_incident_id = None
                self._deferred_close_reason = None
                self._deferred_close_fire_at = None

    def _cancel_merge_deadline_only(self) -> None:
        task = self._merge_deadline_task
        if task is not None and not task.done():
            logger.info(
                f"{ModuleColors.INCIDENT_HANDLER} | Cancelling merge-deadline task (incident ended or rescheduled)"
            )
            task.cancel()
        self._merge_deadline_task = None

    def _cancel_informational_grace(self) -> None:
        task = self._informational_grace_task
        if task is not None and not task.done():
            logger.info(
                f"{ModuleColors.INCIDENT_HANDLER} | Cancelling informational-grace task (incident ended or priority changed)"
            )
            task.cancel()
        self._informational_grace_task = None

    def _cancel_merge_deadline_task(self) -> None:
        self._cancel_merge_deadline_only()
        self._cancel_informational_grace()

    def _schedule_informational_grace(self, incident_id: str) -> None:
        prev = self._informational_grace_task
        if prev is not None and not prev.done():
            prev.cancel()
        logger.info(
            f"{ModuleColors.INCIDENT_HANDLER} | {json_log_maker(incident_id=incident_id, delay_s=INFORMATIONAL_GRACE_PERIOD.total_seconds())} | Scheduling informational-grace close",
        )
        self._informational_grace_task = asyncio.create_task(
            self._fire_informational_grace(incident_id)
        )

    def _schedule_merge_deadline(self, expires_at: datetime) -> None:
        # One timer per open incident; replaces any previous deadline task.
        self._cancel_merge_deadline_task()
        expires = ensure_utc(expires_at)
        logger.info(
            f"{ModuleColors.INCIDENT_HANDLER} | {json_log_maker(expires_at=expires.isoformat())} | Scheduling merge-deadline task",
        )
        task = asyncio.create_task(self._fire_merge_deadline(expires))
        self._merge_deadline_task = task

    async def _fire_merge_deadline(self, expires_at: datetime) -> None:
        me = asyncio.current_task()
        try:
            # Wait until merge window end, then clear the slot if still open (TTL eviction).
            delay = (ensure_utc(expires_at) - utc_now()).total_seconds()
            logger.info(
                f"{ModuleColors.INCIDENT_HANDLER} | {json_log_maker(sleep_s=max(0.0, delay), expires_at=ensure_utc(expires_at).isoformat())} | Merge-deadline waiter started",
            )
            if delay > 0:
                await asyncio.sleep(delay)
            async with self._open_incident_lock:
                ended = self._tracker.evict_if_ttl_expired()
            if ended is None:
                logger.info(
                    f"{ModuleColors.INCIDENT_HANDLER} | Merge-deadline fired, no TTL eviction (slot empty or already closed)"
                )
            if ended is not None:
                self._cancel_deferred_close(ended.incident_id)
                self._cancel_informational_grace()
                display_unified = (ended.unified_text or "").rstrip()
                end_ts = ended.end_time
                if end_ts is not None:
                    self._tracker.record_recent_incident_closure(
                        closed_at=end_ts,
                        channels=list(ended.channels),
                        unified_text=ended.unified_text,
                        close_reason=CloseReason.TTL,
                    )
                closed_subject = None
                if end_ts is not None:
                    closed_subject = (
                        await self._incident_handler.subject_line_for_closed_incident(
                            unified_text=ended.unified_text,
                            close_reason=CloseReason.TTL,
                            incident_start=ended.start_time,
                            closed_at=end_ts,
                            log_file_suffix=ended.log_file_suffix,
                        )
                    )
                if ended.incident_message_id and end_ts is not None:
                    try:
                        await self._telegram_sender.edit_alert(
                            ended.incident_message_id,
                            channels=list(ended.channels),
                            unified_text=display_unified,
                            start_at=ended.start_time,
                            ended_at=end_ts,
                            alert_priority=ended.alert_priority,
                            close_reason=CloseReason.TTL,
                            subject=closed_subject,
                        )
                    except Exception:
                        logger.exception(
                            f"{ModuleColors.INCIDENT_HANDLER} | Failed to edit alert after TTL expiry"
                        )
                    else:
                        logger.info(
                            f"{ModuleColors.INCIDENT_HANDLER} | {json_log_maker(incident_id=ended.incident_id, message_id=ended.incident_message_id)} | TTL destination alert edited",
                        )
                logger.info(
                    f"{ModuleColors.INCIDENT_HANDLER} | {json_log_maker(incident_id=ended.incident_id, unified_text_len=len(ended.unified_text))} | Incident TTL finalized",
                )
        except asyncio.CancelledError:
            raise
        finally:
            # Drop task handle when this run finishes or is cancelled so a new deadline can be scheduled.
            if me is not None and self._merge_deadline_task is me:
                self._merge_deadline_task = None

    async def _fire_informational_grace(self, incident_id: str) -> None:
        me = asyncio.current_task()
        try:
            delay = max(0.0, INFORMATIONAL_GRACE_PERIOD.total_seconds())
            logger.info(
                f"{ModuleColors.INCIDENT_HANDLER} | {json_log_maker(sleep_s=delay, incident_id=incident_id)} | Informational-grace waiter started",
            )
            if delay > 0:
                await asyncio.sleep(delay)
            async with self._open_incident_lock:
                opened = self._tracker.get_open_incident()
                if (
                    opened is None
                    or opened.incident_id != incident_id
                    or opened.alert_priority != MessagePriority.INFORMATIONAL
                ):
                    logger.info(
                        f"{ModuleColors.INCIDENT_HANDLER} | {json_log_maker(incident_id=incident_id)} | Informational-grace fired | skip (no matching open informational incident)",
                    )
                    return
                should_defer, defer_seconds = self._deferred_close_rule(
                    CloseReason.INFORMATIONAL_GRACE
                )
                if should_defer and defer_seconds > 0:
                    pending_message_id = opened.incident_message_id
                    pending_channels = list(opened.channels)
                    pending_unified_text = opened.unified_text
                    pending_start_time = opened.start_time
                    pending_priority = opened.alert_priority
                    pending_subject = opened.subject
                    self._schedule_deferred_close(
                        incident_id, CloseReason.INFORMATIONAL_GRACE, defer_seconds
                    )
                    logger.info(
                        f"{ModuleColors.INCIDENT_HANDLER} | {json_log_maker(incident_id=incident_id, close_reason=CloseReason.INFORMATIONAL_GRACE, deferred_seconds=defer_seconds)} | Informational-grace converted to deferred close",
                    )
                    if pending_message_id:
                        await self._telegram_sender.edit_alert(
                            pending_message_id,
                            channels=pending_channels,
                            unified_text=pending_unified_text,
                            start_at=pending_start_time,
                            ended_at=None,
                            alert_priority=pending_priority,
                            subject=pending_subject,
                            pending_close_reason=CloseReason.INFORMATIONAL_GRACE,
                            pending_close_seconds=defer_seconds,
                        )
                    return
                snapshot = self._tracker.end_incident(utc_now())
            self._cancel_merge_deadline_only()
            if snapshot is None:
                return
            self._cancel_deferred_close(snapshot.incident_id)
            if snapshot.end_time is not None:
                self._tracker.record_recent_incident_closure(
                    closed_at=snapshot.end_time,
                    channels=list(snapshot.channels),
                    unified_text=snapshot.unified_text,
                    close_reason=CloseReason.INFORMATIONAL_GRACE,
                )
            closed_subject = None
            if snapshot.end_time is not None:
                closed_subject = (
                    await self._incident_handler.subject_line_for_closed_incident(
                        unified_text=snapshot.unified_text,
                        close_reason=CloseReason.INFORMATIONAL_GRACE,
                        incident_start=snapshot.start_time,
                        closed_at=snapshot.end_time,
                        log_file_suffix=snapshot.log_file_suffix,
                    )
                )
            if snapshot.incident_message_id:
                try:
                    await self._telegram_sender.edit_alert(
                        snapshot.incident_message_id,
                        channels=list(snapshot.channels),
                        unified_text=snapshot.unified_text,
                        start_at=snapshot.start_time,
                        ended_at=snapshot.end_time,
                        alert_priority=snapshot.alert_priority,
                        close_reason=CloseReason.INFORMATIONAL_GRACE,
                        subject=closed_subject,
                    )
                except Exception:
                    logger.exception(
                        f"{ModuleColors.INCIDENT_HANDLER} | Failed to edit alert after informational-grace close"
                    )
                else:
                    logger.info(
                        f"{ModuleColors.INCIDENT_HANDLER} | {json_log_maker(incident_id=snapshot.incident_id, message_id=snapshot.incident_message_id)} | Informational-grace destination alert edited",
                    )
            logger.info(
                f"{ModuleColors.INCIDENT_HANDLER} | {json_log_maker(incident_id=snapshot.incident_id)} | Incident closed after informational grace",
            )
        except asyncio.CancelledError:
            raise
        finally:
            if me is not None and self._informational_grace_task is me:
                self._informational_grace_task = None

    async def _resolve_monitored_chats(self) -> None:
        # Populate frozenset used by _is_monitored_chat; no-op when monitored_chats is empty.
        logger.info(f"{ModuleColors.MAIN} | Resolving monitored chat peers from config")
        self._monitored_peer_ids = await resolve_monitored_peer_ids(
            self._client, self.monitored_chats
        )

    def _is_monitored_chat(self, event) -> bool:
        # Empty monitored_chats means "all chats"; otherwise require resolved peer id set.
        if not self.monitored_chats:
            return True
        peers = self._monitored_peer_ids
        if not peers:
            return False
        cid = event.chat_id
        return cid is not None and cid in peers

    async def _process_message(
        self,
        event,
        event_type: str,
        *,
        skip_new_message_watermark_check: bool = False,
        skip_edit_text_cache_gate: bool = False,
    ) -> None:
        if not self._is_monitored_chat(event):
            return
        message = event.message
        channel_id = event.chat_id
        message_id = message.id
        is_new_message = event_type == MessageType.NEW_MESSAGE

        if channel_id is None:
            return
        if is_new_message:
            if not skip_new_message_watermark_check and self._watermarks.is_old(
                channel_id, message_id
            ):
                logger.debug(
                    f"{ModuleColors.MESSAGE_PROCESSING} | Duplicate new_message skipped"
                )
                return

        channel_name = await resolve_source_chat(event)
        if message_contains_video(message):
            logger.debug(
                f"{ModuleColors.MESSAGE_PROCESSING} | Skipped (message contains video)"
            )
            return
        raw_text = message.text or ""
        parent_message_id = get_reply_message_id(message)
        text = sanitize_alert_body_text(message.text)
        if not text:
            return

        # In-channel /close is handled only on the dedicated admin path below, not here.
        if text and is_manual_close_command(text):
            return
        if is_new_message:
            self._edit_text_cache.record(channel_id, message_id, raw_text)

        prep: ExistingIncidentPrep | None = None
        recent_appendix: str | None = None
        message_ts = message_timestamp_for_incident(
            message, is_edited_event=(event_type == MessageType.EDITED_MESSAGE)
        )

        async with self._open_incident_lock:
            opened_incident: ActiveIncident | None = self._tracker.get_open_incident()
            if event_type == MessageType.EDITED_MESSAGE:
                latest_seen = self._watermarks.latest(channel_id)
                if opened_incident is None and message_id < latest_seen:
                    logger.debug(
                        f"{ModuleColors.MESSAGE_PROCESSING} | Ignoring edited_message opener candidate as old"
                    )
                    return
                if not skip_edit_text_cache_gate:
                    edit_text = raw_text
                    is_duplicate_edit = self._edit_text_cache.is_duplicate(
                        channel_id, message_id, edit_text
                    )
                    bypass_duplicate_dedup = (
                        is_duplicate_edit
                        and opened_incident is None
                        and message_id > latest_seen
                    )
                    if is_duplicate_edit and not bypass_duplicate_dedup:
                        logger.debug(
                            f"{ModuleColors.MESSAGE_PROCESSING} | {json_log_maker(type=event_type, channel_id=channel_id, message_id=message_id)} | Edit deduped (unchanged text)"
                        )
                        return
                    if bypass_duplicate_dedup:
                        logger.info(
                            f"{ModuleColors.MESSAGE_PROCESSING} | {json_log_maker(type=event_type, channel_id=channel_id, message_id=message_id, latest_seen=latest_seen)} | Edit dedup bypassed (awaiting finalized new_message consumption)"
                        )
                    self._edit_text_cache.record(channel_id, message_id, edit_text)
            logger.info(
                f"{ModuleColors.INCIDENT_HANDLER} | {json_log_maker(type=event_type, channel=channel_name, message_id=message_id, open_incident_id=opened_incident.incident_id if opened_incident else None)} | Incident pipeline",
            )
            if opened_incident is not None:
                prep = self._incident_handler.build_existing_incident_prep(
                    opened_incident=opened_incident,
                    channel_id=channel_id,
                    channel_name=channel_name,
                    raw_text=raw_text,
                    text=text,
                    event_type=event_type,
                    message_ts=message_ts,
                    message_id=message_id,
                    parent_message_id=parent_message_id,
                    message=message,
                )
            else:
                recent_appendix = self._tracker.recent_closure_prompt_appendix(
                    message_ts=message_ts,
                    source_channel=channel_name,
                )

        if prep is not None:
            await self._run_merge_pipeline(prep)
        else:
            await self._run_new_incident_pipeline(
                channel_id=channel_id,
                channel_name=channel_name,
                raw_text=raw_text,
                text=text,
                event_type=event_type,
                message_ts=message_ts,
                message_id=message_id,
                parent_message_id=parent_message_id,
                message=message,
                recent_appendix=recent_appendix,
            )
        if is_new_message:
            self._watermarks.update(channel_id, message_id)

    async def _run_merge_pipeline(self, prep: ExistingIncidentPrep) -> None:
        llm_merge = await self._incident_handler.run_existing_incident_llm(prep)
        pending_close: PendingClosedAlertEdit | None = None
        recovered_merge_deadline: datetime | None = None
        async with self._open_incident_lock:
            pending_close = (
                await self._incident_handler.apply_existing_incident_locked_phase(
                    prep, llm_merge
                )
            )
            if (
                pending_close is None
                and self._tracker.get_open_incident() is None
                and self._can_reopen_from_discarded_merge(prep, llm_merge)
            ):
                logger.warning(
                    f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.EXISTING} | {json_log_maker(incident_id=prep.incident_id, channel=prep.channel_name, message_id=prep.message_id)} | Recovering from discarded merge by opening a new incident from in-flight LLM result",
                )
                recovered_merge_deadline = (
                    await self._incident_handler.commit_new_incident_after_llm(
                        channel_id=prep.channel_id,
                        channel_name=prep.channel_name,
                        raw_text=prep.raw_text,
                        text=prep.text,
                        event_type=prep.event_type,
                        message_ts=prep.message_ts,
                        message_id=prep.message_id,
                        parent_message_id=prep.parent_message_id,
                        response=llm_merge,
                    )
                )
        if recovered_merge_deadline is not None:
            self._schedule_merge_deadline(recovered_merge_deadline)
            return
        if pending_close is not None:
            closed_subject = (
                await self._incident_handler.subject_line_for_closed_incident(
                    unified_text=pending_close.unified_text,
                    close_reason=pending_close.close_reason,
                    incident_start=pending_close.incident_start,
                    closed_at=pending_close.closed_at,
                    log_file_suffix=pending_close.log_file_suffix,
                )
            )
            try:
                await self._telegram_sender.edit_alert(
                    pending_close.incident_message_id,
                    channels=pending_close.channels,
                    unified_text=pending_close.unified_text,
                    start_at=pending_close.start_at,
                    ended_at=pending_close.end_at,
                    alert_priority=pending_close.alert_priority,
                    close_reason=pending_close.close_reason,
                    subject=closed_subject,
                )
            except Exception:
                logger.exception(
                    f"{ModuleColors.INCIDENT_HANDLER} | Failed to edit alert after LLM-close (outside tracker lock)"
                )
            else:
                logger.info(
                    f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.EXISTING} | {json_log_maker(incident_id=prep.incident_id, message_id=pending_close.incident_message_id)} | Destination alert edited (closed)",
                )

    @staticmethod
    def _can_reopen_from_discarded_merge(
        prep: ExistingIncidentPrep,
        llm_merge,
    ) -> bool:
        if llm_merge is None:
            return False
        if llm_merge.ended:
            return False
        if not llm_merge.qualified:
            return False
        if llm_merge.priority == MessagePriority.NONE:
            return False
        if llm_merge.related is False:
            return False
        return True

    async def _run_new_incident_pipeline(
        self,
        *,
        channel_id: int,
        channel_name: str,
        raw_text: str,
        text: str,
        event_type: str,
        message_ts: datetime,
        message_id: int,
        parent_message_id: int | None,
        message,
        recent_appendix: str | None,
    ) -> None:
        async with self._incident_pipeline_sem:
            async with self._open_incident_lock:
                if self._tracker.get_open_incident() is not None:
                    prep = self._incident_handler.build_existing_incident_prep(
                        opened_incident=self._tracker.get_open_incident(),
                        channel_id=channel_id,
                        channel_name=channel_name,
                        raw_text=raw_text,
                        text=text,
                        event_type=event_type,
                        message_ts=message_ts,
                        message_id=message_id,
                        parent_message_id=parent_message_id,
                        message=message,
                    )
                else:
                    prep = None
            if prep is not None:
                await self._run_merge_pipeline(prep)
                return

            qualification = (
                await self._incident_handler.run_new_incident_qualification_llm(
                    channel_id=channel_id,
                    channel_name=channel_name,
                    text=text,
                    event_type=event_type,
                    message=message,
                    recent_closure_appendix=recent_appendix,
                )
            )
            merge_deadline_at: datetime | None = None
            async with self._open_incident_lock:
                if self._tracker.get_open_incident() is not None:
                    logger.info(
                        f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.NEW} | {json_log_maker(channel=channel_name)} | Slot filled during qualification; converting to merge",
                    )
                    prep = self._incident_handler.build_existing_incident_prep(
                        opened_incident=self._tracker.get_open_incident(),
                        channel_id=channel_id,
                        channel_name=channel_name,
                        raw_text=raw_text,
                        text=text,
                        event_type=event_type,
                        message_ts=message_ts,
                        message_id=message_id,
                        parent_message_id=parent_message_id,
                        message=message,
                    )
                else:
                    prep = None
            if prep is not None:
                await self._run_merge_pipeline(prep)
                return

            async with self._open_incident_lock:
                merge_deadline_at = (
                    await self._incident_handler.commit_new_incident_after_llm(
                        channel_id=channel_id,
                        channel_name=channel_name,
                        raw_text=raw_text,
                        text=text,
                        event_type=event_type,
                        message_ts=message_ts,
                        message_id=message_id,
                        parent_message_id=parent_message_id,
                        response=qualification,
                    )
                )
                pre_deleted_grace_id: str | None = None
                if (
                    merge_deadline_at is not None
                    and self._tracker.check_pending_deletion(channel_id, message_id)
                ):
                    logger.info(
                        f"{ModuleColors.INCIDENT_HANDLER} | {json_log_maker(channel=channel_name, message_id=message_id)} | Source pre-deleted during qualification — triggering deletion",
                    )
                    pre_deletion = self._incident_handler.handle_message_deletion(
                        channel_id=channel_id,
                        deleted_message_ids=[message_id],
                        message_ts=message_timestamp_for_deletion_event(),
                    )
                    if (
                        pre_deletion is not None
                        and pre_deletion.grace_close is not None
                    ):
                        pre_deleted_grace_id = pre_deletion.grace_close.incident_id
        if merge_deadline_at is not None:
            self._schedule_merge_deadline(merge_deadline_at)
        if pre_deleted_grace_id is not None:
            await self._apply_source_deleted_grace_close(pre_deleted_grace_id)

    async def _process_message_with_retries(self, event, event_type: str) -> None:
        """Run _process_message with exponential backoff on transient failures."""
        max_a = self._message_process_max_attempts
        base = self._message_process_retry_base_sec
        for attempt in range(1, max_a + 1):
            try:
                await self._process_message(
                    event,
                    event_type,
                    skip_new_message_watermark_check=attempt > 1,
                    skip_edit_text_cache_gate=attempt > 1,
                )
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Last attempt: log full traceback; earlier attempts: warn and backoff (watermark not advanced on exception).
                if attempt >= max_a:
                    logger.exception(
                        f"{ModuleColors.MESSAGE_PROCESSING} | {json_log_maker(type=event_type, max_attempts=max_a)} | Error handling after {max_a} attempts"
                    )
                    return
                delay = base * (2 ** (attempt - 1))
                logger.warning(
                    f"{ModuleColors.MESSAGE_PROCESSING} | {json_log_maker(type=event_type, attempt=attempt, max_attempts=max_a, delay=delay)} | Error handling; retrying in {delay:.1f}s: {exc}"
                )
                await asyncio.sleep(delay)

    async def _apply_source_deleted_grace_close(self, incident_id: str) -> None:
        self._cancel_informational_grace()
        should_defer, seconds = self._deferred_close_rule(CloseReason.SOURCE_DELETED)
        if should_defer and seconds > 0:
            self._schedule_deferred_close(
                incident_id, CloseReason.SOURCE_DELETED, seconds
            )
            async with self._open_incident_lock:
                open_i = self._tracker.get_open_incident()
            if open_i is None or open_i.incident_id != incident_id:
                logger.warning(
                    f"{ModuleColors.INCIDENT_HANDLER} | {json_log_maker(incident_id=incident_id)} | Source-deleted grace skip (incident not open)",
                )
                return
            if open_i.incident_message_id:
                pending = self._get_pending_close_info()
                pr = pending[0] if pending else CloseReason.SOURCE_DELETED
                ps = pending[1] if pending else seconds
                try:
                    await self._telegram_sender.edit_alert(
                        open_i.incident_message_id,
                        channels=list(open_i.channels),
                        unified_text=open_i.unified_text,
                        start_at=open_i.start_time,
                        ended_at=None,
                        alert_priority=open_i.alert_priority,
                        subject=open_i.subject,
                        pending_close_reason=pr,
                        pending_close_seconds=ps,
                    )
                except Exception:
                    logger.exception(
                        f"{ModuleColors.INCIDENT_HANDLER} | Failed to edit alert after source-deleted grace schedule"
                    )
                else:
                    logger.info(
                        f"{ModuleColors.INCIDENT_HANDLER} | {json_log_maker(incident_id=incident_id, message_id=open_i.incident_message_id)} | Source-deleted pending close banner set",
                    )
            logger.info(
                f"{ModuleColors.INCIDENT_HANDLER} | {json_log_maker(incident_id=incident_id, delay_s=seconds)} | Source-deleted grace close scheduled",
            )
            return

        self._cancel_deferred_close(incident_id)
        snapshot = None
        async with self._open_incident_lock:
            opened = self._tracker.get_open_incident()
            if opened is None or opened.incident_id != incident_id:
                return
            snapshot = self._tracker.end_incident(utc_now())
        if snapshot is None:
            return
        self._cancel_merge_deadline_task()
        if snapshot.end_time is not None:
            self._tracker.record_recent_incident_closure(
                closed_at=snapshot.end_time,
                channels=list(snapshot.channels),
                unified_text=snapshot.unified_text,
                close_reason=CloseReason.SOURCE_DELETED,
            )
        closed_subject = None
        if snapshot.end_time is not None:
            closed_subject = (
                await self._incident_handler.subject_line_for_closed_incident(
                    unified_text=snapshot.unified_text,
                    close_reason=CloseReason.SOURCE_DELETED,
                    incident_start=snapshot.start_time,
                    closed_at=snapshot.end_time,
                    log_file_suffix=snapshot.log_file_suffix,
                )
            )
        if snapshot.incident_message_id and snapshot.end_time is not None:
            try:
                await self._telegram_sender.edit_alert(
                    snapshot.incident_message_id,
                    channels=list(snapshot.channels),
                    unified_text=snapshot.unified_text,
                    start_at=snapshot.start_time,
                    ended_at=snapshot.end_time,
                    alert_priority=snapshot.alert_priority,
                    close_reason=CloseReason.SOURCE_DELETED,
                    subject=closed_subject,
                )
            except Exception:
                logger.exception(
                    f"{ModuleColors.INCIDENT_HANDLER} | Failed to edit alert after immediate source-deleted close"
                )
            else:
                logger.info(
                    f"{ModuleColors.INCIDENT_HANDLER} | {json_log_maker(incident_id=snapshot.incident_id, message_id=snapshot.incident_message_id)} | Immediate source-deleted close — destination alert edited",
                )

    async def _process_deletion(self, event) -> None:
        chat_id = getattr(event, "chat_id", None)
        if chat_id is None:
            return
        if not self._is_monitored_chat(event):
            return
        deleted_raw = getattr(event, "deleted_ids", None) or []
        deleted_ids = [int(x) for x in deleted_raw]
        if not deleted_ids:
            return
        message_ts = message_timestamp_for_deletion_event(event)
        reprocess_pack: tuple[ActiveIncident, str, str] | None = None
        grace_incident_id: str | None = None
        async with self._open_incident_lock:
            for mid in deleted_ids:
                self._tracker.record_pending_deletion(chat_id, mid)
            outcome = self._incident_handler.handle_message_deletion(
                channel_id=chat_id,
                deleted_message_ids=deleted_ids,
                message_ts=message_ts,
            )
            if outcome is None:
                return
            logger.info(
                f"{ModuleColors.INCIDENT_HANDLER} | {json_log_maker(chat_id=chat_id, deleted_ids=deleted_ids, incident_id=outcome.incident_id, grace=bool(outcome.grace_close), reprocess=outcome.reprocess)} | Source message deletion processed",
            )
            if outcome.grace_close is not None:
                grace_incident_id = outcome.grace_close.incident_id
            elif outcome.reprocess:
                opened = self._tracker.get_open_incident()
                if opened is None:
                    return
                reprocess_pack = (
                    copy.deepcopy(opened),
                    self._tracker.source_messages_context(),
                    outcome.incident_id,
                )

        if grace_incident_id is not None:
            await self._apply_source_deleted_grace_close(grace_incident_id)
            return
        if reprocess_pack is None:
            return
        incident_for_llm, ctx, incident_id = reprocess_pack
        llm_response = await self._llm.reprocess_after_deletion(
            incident=incident_for_llm,
            source_messages_context=ctx,
        )
        pending_close: PendingClosedAlertEdit | None = None
        async with self._open_incident_lock:
            pending_close = await self._incident_handler.apply_reprocess_after_deletion(
                incident_id=incident_id,
                llm_response=llm_response,
            )
        if pending_close is not None:
            closed_subject = (
                await self._incident_handler.subject_line_for_closed_incident(
                    unified_text=pending_close.unified_text,
                    close_reason=pending_close.close_reason,
                    incident_start=pending_close.incident_start,
                    closed_at=pending_close.closed_at,
                    log_file_suffix=pending_close.log_file_suffix,
                )
            )
            try:
                await self._telegram_sender.edit_alert(
                    pending_close.incident_message_id,
                    channels=pending_close.channels,
                    unified_text=pending_close.unified_text,
                    start_at=pending_close.start_at,
                    ended_at=pending_close.end_at,
                    alert_priority=pending_close.alert_priority,
                    close_reason=pending_close.close_reason,
                    subject=closed_subject,
                )
            except Exception:
                logger.exception(
                    f"{ModuleColors.INCIDENT_HANDLER} | Failed to edit alert after reprocess close (deletion pipeline)"
                )
            else:
                logger.info(
                    f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.EXISTING} | {json_log_maker(incident_id=incident_id, message_id=pending_close.incident_message_id)} | Destination alert edited (closed after reprocess)",
                )

    async def init_watermarks(self) -> None:
        # With no allowlist, startup scan is skipped; first live message sets position.
        if not self.monitored_chats:
            logger.info(
                f"{ModuleColors.MAIN} | Watermarks | skip init (no monitored_chats allowlist)"
            )
            return

        chats = monitored_chats_list(self.monitored_chats)
        logger.info(
            f"{ModuleColors.MAIN} | {json_log_maker(monitored_chat_count=len(chats))} | Watermarks init start"
        )
        for chat in chats:
            try:
                entity = await self._client.get_entity(chat)
                channel_id = getattr(entity, "id", None)
                if channel_id is None:
                    continue
                messages = await self._client.get_messages(entity, limit=1)

                # Start past the latest post so backlog is not replayed as "new" on boot.
                if messages:
                    self._watermarks.update(channel_id, messages[0].id)
                    logger.info(
                        f"{ModuleColors.MAIN} | {json_log_maker(chat=chat, channel_id=channel_id, message_id=messages[0].id)} | Watermarks seeded from latest message",
                    )
                else:
                    self._watermarks.update(channel_id, 0)
                    logger.info(
                        f"{ModuleColors.MAIN} | {json_log_maker(chat=chat, channel_id=channel_id)} | Watermarks empty history",
                    )

            except Exception as e:
                logger.warning(
                    f"{ModuleColors.MAIN} | {json_log_maker(chat=chat)} | Could not init watermark: {e}"
                )

    async def _manual_close_incident(
        self, custom_close_reason: str | None = None
    ) -> str:
        """End open incident if any; edit destination alert; return Hebrew status."""
        snapshot = None
        async with self._open_incident_lock:
            opened = self._tracker.get_open_incident()
            if opened is None:
                logger.info(
                    f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.MANUAL} | no open incident"
                )
                return "אין אירוע פתוח כרגע."
            logger.info(
                f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.MANUAL} | {json_log_maker(incident_id=opened.incident_id)} | Manual close - ending incident",
            )
            self._cancel_deferred_close(opened.incident_id)

            snapshot = self._tracker.end_incident(utc_now())
            self._cancel_merge_deadline_task()
            if snapshot and snapshot.end_time is not None:
                self._tracker.record_recent_incident_closure(
                    closed_at=snapshot.end_time,
                    channels=list(snapshot.channels),
                    unified_text=snapshot.unified_text,
                    close_reason=CloseReason.MANUAL,
                )

        closed_subject = None
        if snapshot and snapshot.end_time is not None:
            closed_subject = (
                await self._incident_handler.subject_line_for_closed_incident(
                    unified_text=snapshot.unified_text,
                    close_reason=CloseReason.MANUAL,
                    incident_start=snapshot.start_time,
                    closed_at=snapshot.end_time,
                    log_file_suffix=snapshot.log_file_suffix,
                )
            )
        if snapshot and snapshot.incident_message_id:
            try:
                await self._telegram_sender.edit_alert(
                    snapshot.incident_message_id,
                    channels=list(snapshot.channels),
                    unified_text=snapshot.unified_text,
                    start_at=snapshot.start_time,
                    ended_at=snapshot.end_time,
                    alert_priority=snapshot.alert_priority,
                    close_reason=CloseReason.MANUAL,
                    subject=closed_subject,
                    custom_close_reason=custom_close_reason,
                )
            except Exception:
                logger.exception(
                    f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.MANUAL} | Failed to edit alert after manual close"
                )
            else:
                logger.info(
                    f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.MANUAL} | {json_log_maker(incident_id=snapshot.incident_id, message_id=snapshot.incident_message_id)} | destination alert edited",
                )
        elif snapshot:
            logger.info(
                f"{ModuleColors.INCIDENT_HANDLER} | {IncidentHandlerLog.MANUAL} | {json_log_maker(incident_id=snapshot.incident_id)} | Snapshot without destination message_id",
            )
        return "האירוע נסגר ידנית."

    def _register_handlers(self) -> None:
        @self._client.on(events.NewMessage)
        async def on_admin_close_command(event):
            try:
                if not is_manual_close_command(event.message.text):
                    return
                # Same command string as bot DM, but only from configured Telethon chat + allowlisted user ids.
                if (
                    self._admin_command_chat_id is None
                    or event.chat_id != self._admin_command_chat_id
                    or event.sender_id not in self._admin_user_ids
                ):
                    return
                logger.info(
                    f"{ModuleColors.MESSAGE_PROCESSING} | {json_log_maker(user_id=event.sender_id, chat_id=event.chat_id)} | Close command received"
                )
                _, reason_text = parse_manual_close_command(event.message.text)
                reply = await self._manual_close_incident(reason_text)
                await event.reply(reply)
                if type(self).config.get("delete_admin_command_message", True):
                    try:
                        await event.delete()
                    except Exception:
                        logger.debug(
                            f"{ModuleColors.MESSAGE_PROCESSING} | {json_log_maker(user_id=event.sender_id, chat_id=event.chat_id)} | Could not delete admin command message",
                            exc_info=True,
                        )
            except Exception:
                logger.exception(
                    f"{ModuleColors.MESSAGE_PROCESSING} | {json_log_maker(user_id=event.sender_id, chat_id=event.chat_id)} | Error handling admin close command"
                )

        @self._client.on(events.NewMessage)
        async def on_new_message(event):
            # Monitored channel posts (and everything else) flow through dedupe + optional incident logic.
            await self._process_message_with_retries(event, MessageType.NEW_MESSAGE)

        @self._client.on(events.MessageEdited)
        async def on_edited_message(event):
            # Lets the LLM merge late corrections; opener path when no incident uses watermark guard above.
            await self._process_message_with_retries(event, MessageType.EDITED_MESSAGE)

        @self._client.on(events.MessageDeleted)
        async def on_message_deleted(event):
            try:
                await self._process_deletion(event)
            except Exception:
                logger.exception(
                    f"{ModuleColors.MESSAGE_PROCESSING} | Error handling MessageDeleted",
                )

    async def main(self):
        await self._client.start()

        me = await self._client.get_me()
        username = getattr(me, "username", None)

        logger.info(f"{ModuleColors.MAIN} | Connected as {username or me.id}")
        logger.info(
            f"{ModuleColors.MAIN} | Monitoring chats={self.monitored_chats or 'all'}"
        )

        cfg = type(self).config
        ac = cfg.get("admin_command_chat_id")
        self._admin_command_chat_id = int(ac) if ac is not None else me.id
        au = cfg.get("admin_user_ids")
        # Telethon /close allowlist: defaults to the logged-in account only.
        self._admin_user_ids = (
            frozenset(int(x) for x in au) if au else frozenset({me.id})
        )
        await self._resolve_monitored_chats()
        await self.init_watermarks()
        self._register_handlers()
        logger.info(f"{ModuleColors.MAIN} | Telethon event handlers registered")

        # Bot API long poll in parallel — does not block Telethon; uses same manual_close + send_plain_text.
        if not self.is_debug:
            logger.info(
                f"{IncidentHandlerLog.MANUAL} | {json_log_maker(chat_id=self._admin_command_chat_id, allowed_user_ids=sorted(self._admin_user_ids), enable_bot_dm_commands=cfg.get('enable_bot_dm_commands', True))}"
            )
            asyncio.create_task(
                run_bot_dm_updates_loop(
                    bot_token=self.bot_token,
                    admin_user_ids=self._admin_user_ids,
                    enabled=cfg.get("enable_bot_dm_commands", True),
                    manual_close=self._manual_close_incident,
                    send_plain_text=self._telegram_sender.send_plain_text,
                )
            )
        await self._client.run_until_disconnected()


if __name__ == "__main__":
    import logging

    logger.configure(
        handlers=[
            {
                "sink": sys.stdout,
                "format": "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level}</level> | {message}",
                "level": "DEBUG",
                "colorize": True,
            }
        ]
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    logger.info("\033[93;1mStarting Lions Roar\033[00m")

    lions_roar = LionsRoar()
    asyncio.run(lions_roar.main())

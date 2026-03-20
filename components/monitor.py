import asyncio
import logging
from datetime import datetime, timezone

from telethon import TelegramClient, events
from telethon.errors import UserNotParticipantError

from components.ai.openai_client import OpenAIAlertsClient
from components.classifier import MessageClassifier
from components.config import Config
from components.constants import FirstMessageStrength
from components.event_handling.event_end import (
    event_end_keyword_match,
    has_non_end_instruction_phrase,
    has_non_end_outcome_phrase,
)
from components.event_handling.event_tracker import EventTracker
from components.notifications.alert import AlertSender
from components.utils import ChannelWatermarks, normalize_text, to_il_tz

logger = logging.getLogger(__name__)


class TelegramMonitor:
    """
    Wires together the Telegram client, deduplication cache, classifier,
    event tracker, OpenAI merge, and alert sender.
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._client = TelegramClient(
            config.session_name, config.api_id, config.api_hash
        )
        self._watermarks = ChannelWatermarks()
        self._tracker = EventTracker()
        self._classifier = MessageClassifier(
            config.alert_keywords,
            config.relevant_locations,
            config.weak_first_phrases,
        )
        target_chat = (
            config.target_debug_chat_id
            if config.is_debug and config.target_debug_chat_id
            else config.bot_target_chat_id
        )
        self._control_chat_ref = target_chat
        self._control_chat_ids: set[int] = set()
        self._control_chat_usernames: set[str] = set()
        self._sender = AlertSender(
            config.bot_token,
            target_chat,
            pin_on_edit=config.alert_pin_on_edit,
            bump_on_edit=config.alert_bump_on_edit,
            delete_bump_message=config.alert_delete_bump_message,
        )
        self._openai: OpenAIAlertsClient | None = None
        if config.openai_api_key:
            self._openai = OpenAIAlertsClient(
                config.openai_api_key,
                model=config.openai_model,
            )
        else:
            logger.warning(
                "OPENAI_API_KEY missing — cannot merge follow-ups; gate alerts still work"
            )
        # Prevent duplicate incident-open sends for the same source message id.
        self._source_message_gated: set[tuple[int, int]] = set()
        # Serialize the "open new incident" critical section across event handlers.
        self._incident_open_lock = asyncio.Lock()
        self._register_handlers()

    @staticmethod
    def _extract_command_token(text: str) -> str:
        first = normalize_text(text).split(" ", 1)[0].lower()
        return first.split("@", 1)[0]

    def _parse_manual_close_reason(self, text: str) -> str | None:
        normalized = normalize_text(text)
        if not normalized:
            return None
        cmd = self._extract_command_token(normalized)
        if cmd not in {"/close_incident", "/closeincident", "/end_incident"}:
            return None
        first_token = normalized.split(" ", 1)[0]
        reason = normalized[len(first_token) :].strip()
        return reason

    @staticmethod
    def _possible_chat_ids(chat_id: int) -> set[int]:
        """
        Build equivalent Telegram chat-id forms to compare reliably across
        environment values and Telethon event ids.
        """
        ids = {chat_id}
        abs_id = abs(chat_id)
        ids.add(-abs_id)
        ids.add(abs_id)
        as_text = str(abs_id)
        if not as_text.startswith("100"):
            ids.add(int(f"-100{as_text}"))
        return ids

    async def _resolve_control_chat_refs(self) -> None:
        ref = str(self._control_chat_ref).strip()
        if not ref:
            return
        if ref.startswith("@"):
            self._control_chat_usernames.add(ref[1:].lower())
        try:
            self._control_chat_ids.add(int(ref))
        except ValueError:
            pass

        try:
            entity = await self._client.get_entity(ref)
        except Exception:
            logger.warning("Could not resolve control chat entity for ref=%s", ref)
            return

        ent_id = getattr(entity, "id", None)
        if isinstance(ent_id, int):
            self._control_chat_ids.update(self._possible_chat_ids(ent_id))
        username = getattr(entity, "username", None)
        if username:
            self._control_chat_usernames.add(str(username).lower())

    async def _is_control_chat(self, event) -> bool:
        if event.chat_id is not None:
            possible = self._possible_chat_ids(int(event.chat_id))
            if self._control_chat_ids.intersection(possible):
                return True
        chat = getattr(event, "chat", None)
        username = getattr(chat, "username", None)
        if username and str(username).lower() in self._control_chat_usernames:
            return True
        return False

    async def _is_sender_admin(self, event) -> bool:
        # Channel posts are authored by channel/admin identity, not always a user participant.
        if bool(getattr(event.message, "post", False)):
            return True

        sender_id = getattr(event, "sender_id", None)
        if (
            isinstance(sender_id, int)
            and event.chat_id is not None
            and sender_id in self._possible_chat_ids(int(event.chat_id))
        ):
            return True

        try:
            sender = await event.get_sender()
            if sender is None:
                return False
            perms = await self._client.get_permissions(event.chat_id, sender)
            return bool(
                getattr(perms, "is_admin", False) or getattr(perms, "is_creator", False)
            )
        except UserNotParticipantError:
            # Seen when the sender is not represented as a normal participant user.
            return bool(getattr(event.message, "post", False))
        except Exception:
            logger.exception("Manual close admin check failed")
            return False

    async def _handle_manual_close_command(self, event) -> bool:
        text = normalize_text(getattr(event.message, "message", ""))
        reason = self._parse_manual_close_reason(text)
        if reason is None:
            return False
        if not await self._is_control_chat(event):
            return False

        if not await self._is_sender_admin(event):
            logger.warning(
                "Manual close rejected: sender is not admin | chat_id=%s | message_id=%s",
                event.chat_id,
                getattr(event.message, "id", "unknown"),
            )
            try:
                await event.reply("אין הרשאת מנהל לסגירה ידנית.")
            except Exception:
                logger.debug("Could not send unauthorized manual-close reply")
            return True

        async with self._incident_open_lock:
            open_ev = self._tracker.get_open_event()
            if open_ev is None:
                try:
                    await event.reply("אין אירוע פתוח לסגירה.")
                except Exception:
                    logger.debug("Could not send 'no open event' manual-close reply")
                return True

            message_ts = self._message_timestamp(event.message)
            close_text = (
                f"סגירה ידנית: {reason}" if reason else "סגירה ידנית על ידי מנהל הערוץ"
            )
            unified_with_end = self._append_event_line(
                open_ev.unified_text,
                close_text,
                message_ts,
            )
            self._tracker.update_after_merge(unified_with_end, None)
            ended = self._tracker.end_event(message_ts)
            if ended is None:
                try:
                    await event.reply("לא ניתן היה לסגור את האירוע.")
                except Exception:
                    logger.debug("Could not send manual-close failure reply")
                return True

            try:
                await self._sender.edit_alert(
                    ended.bot_message_id,
                    ended.channels,
                    ended.unified_text,
                    ended.start_time,
                    ended_at=ended.end_time,
                    is_update=True,
                    alert_strength=ended.alert_strength,
                    first_message_strength=ended.first_message_strength,
                )
                try:
                    await event.reply("האירוע נסגר ידנית.")
                except Exception:
                    logger.debug("Could not send manual-close success reply")
            except Exception:
                logger.exception("Manual close failed to edit alert")
                try:
                    await event.reply("נכשלה סגירה ידנית (שגיאת עריכת הודעה).")
                except Exception:
                    logger.debug("Could not send manual-close edit-error reply")
            return True

    @staticmethod
    def _message_timestamp(message) -> datetime:
        d = getattr(message, "date", None)
        if d is None:
            return datetime.now(timezone.utc)
        if d.tzinfo is None:
            return d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)

    @staticmethod
    def _format_event_line(text: str, event_time: datetime) -> str:
        hhmm = to_il_tz(event_time).strftime("%H:%M")
        return f"• {hhmm} {normalize_text(text)}"

    def _append_event_line(
        self, unified_text: str, text: str, event_time: datetime
    ) -> str:
        line = self._format_event_line(text, event_time)
        current = unified_text.strip()
        if not current:
            return line
        if line in current:
            return current
        return f"{current}\n{line}"

    @staticmethod
    def _upgrade_alert_strength(
        open_ev,
        classifier: MessageClassifier,
        new_text: str,
    ) -> None:
        """
        Mutate open_ev.alert_strength based on accumulated context:

        - WEAK  + follow-up is location-relevant  → STRONG   (confirmed local threat)
        - WEAK  + follow-up confirms real event   → INFORMATIONAL  (real but not local yet)
        - INFORMATIONAL + location now appears    → STRONG   (escalated to local threat)

        The event stays open in all cases so future messages can still escalate it.
        """
        current = open_ev.alert_strength

        if classifier.is_strong_signal(open_ev.unified_text):
            open_ev.alert_strength = FirstMessageStrength.STRONG
            return

        if current == FirstMessageStrength.WEAK and classifier.is_candidate(new_text):
            open_ev.alert_strength = FirstMessageStrength.INFORMATIONAL

    def _is_monitored_chat(self, event) -> bool:
        if not self._config.monitored_chats:
            return True
        if event.chat_id in self._config.monitored_chats:
            return True
        username = getattr(event.chat, "username", None)
        return bool(username and username in self._config.monitored_chats)

    async def _get_source_name(self, event) -> str:
        try:
            chat = await event.get_chat()
            return (
                getattr(chat, "title", None)
                or getattr(chat, "username", None)
                or str(getattr(chat, "id", "Unknown chat"))
            )
        except Exception:
            return "Unknown chat"

    async def _is_event_end(self, text: str) -> bool:
        if has_non_end_instruction_phrase(text):
            logger.debug(
                "Non-end instruction detected; waiting for explicit end signal"
            )
            return False
        if event_end_keyword_match(text):
            return True
        if has_non_end_outcome_phrase(text):
            logger.debug(
                "Non-end outcome update detected; waiting for explicit end signal"
            )
            return False
        if self._openai is None:
            return False
        try:
            return await self._openai.check_event_end_llm(text)
        except Exception:
            logger.exception("check_event_end_llm failed")
            return False

    async def _handle_open_event_flow(
        self,
        event,
        text: str,
        source_name: str,
    ) -> bool:
        """
        If an event is open: handle end-of-event or merge. Returns True if handled
        (caller should not run gate for this message).
        """
        open_ev = self._tracker.get_open_event()
        if open_ev is None:
            return False

        message_ts = self._message_timestamp(event.message)
        if await self._is_event_end(text):
            # Ensure explicit end message is included in the incident chronology.
            unified_with_end = self._append_event_line(
                open_ev.unified_text, text, message_ts
            )
            self._tracker.update_after_merge(unified_with_end, source_name)

            ended = self._tracker.end_event(message_ts)
            if ended is None:
                return True
            try:
                await self._sender.edit_alert(
                    ended.bot_message_id,
                    ended.channels,
                    ended.unified_text,
                    ended.start_time,
                    ended_at=ended.end_time,
                    is_update=True,
                    alert_strength=ended.alert_strength,
                    first_message_strength=ended.first_message_strength,
                )
            except Exception:
                logger.exception("Failed to edit alert after event end")
            return True

        if self._openai is None:
            logger.error(
                "Open event active but OPENAI_API_KEY missing — skipping merge"
            )
            return True

        try:
            unified = await self._openai.merge_unified_text(
                open_ev.unified_text,
                text,
                new_event_time_hhmm=to_il_tz(message_ts).strftime("%H:%M"),
            )
        except Exception:
            logger.exception("merge_unified_text failed")
            return True

        if unified is None:
            logger.debug(
                "Open event: unrelated message ignored | source=%s | message_id=%s",
                source_name,
                getattr(event.message, "id", "unknown"),
            )
            return True

        self._tracker.update_after_merge(unified, source_name)
        open_ev = self._tracker.get_open_event()
        if open_ev is None:
            return True

        self._upgrade_alert_strength(
            open_ev=open_ev,
            classifier=self._classifier,
            new_text=text,
        )

        try:
            await self._sender.edit_alert(
                open_ev.bot_message_id,
                open_ev.channels,
                open_ev.unified_text,
                open_ev.start_time,
                ended_at=None,
                is_update=True,
                alert_strength=open_ev.alert_strength,
                first_message_strength=open_ev.first_message_strength,
            )
        except Exception:
            logger.exception("Failed to edit merged alert")
        return True

    async def _process_event(self, event, event_type: str) -> None:
        if not self._is_monitored_chat(event):
            return

        message = event.message
        channel_id = event.chat_id
        message_id = message.id

        if event_type == "new_message":
            if self._watermarks.is_old(channel_id, message_id):
                logger.debug(
                    "Duplicate new_message skipped | channel_id=%s | message_id=%s",
                    channel_id,
                    message_id,
                )
                return
            self._watermarks.update(channel_id, message_id)

        text = normalize_text(message.message)
        source_name = await self._get_source_name(event)

        logger.debug(
            "Message | source=%s | chat_id=%s | message_id=%s | event_type=%s | text=%.120s",
            source_name,
            event.chat_id,
            message.id,
            event_type,
            text or "(empty)",
        )

        if not text:
            return
        if self._parse_manual_close_reason(text) is not None:
            return

        open_ev = self._tracker.get_open_event()
        if open_ev is not None:
            await self._handle_open_event_flow(event, text, source_name)
            return

        # --- Gate: no open event ---

        strength = await self._classifier.classify(text, source_name)
        if strength == FirstMessageStrength.NONE:
            logger.debug(
                "Classified not relevant | source=%s | message_id=%s",
                source_name,
                message.id,
            )
            return

        if event_type != "new_message":
            logger.debug(
                "Ignoring edited_message as incident opener | source=%s | message_id=%s",
                source_name,
                message.id,
            )
            return

        key = (channel_id, message_id)
        should_handle_open_event = False

        async with self._incident_open_lock:
            # Another coroutine may have opened an incident while we were classifying.
            if self._tracker.get_open_event() is not None:
                should_handle_open_event = True
            elif key in self._source_message_gated:
                logger.debug(
                    "Gate already sent for message | channel_id=%s | message_id=%s",
                    channel_id,
                    message_id,
                )
                return
            else:
                self._source_message_gated.add(key)
                msg_ts = self._message_timestamp(message)
                try:
                    initial_unified = self._format_event_line(text, msg_ts)
                    mid = await self._sender.send_alert(
                        channels=[source_name],
                        unified_text=initial_unified,
                        start_at=msg_ts,
                        ended_at=None,
                        is_update=False,
                        alert_strength=strength,
                        first_message_strength=strength,
                    )
                except Exception:
                    self._source_message_gated.discard(key)
                    logger.exception("send_alert failed")
                    return

                self._tracker.create_event(
                    bot_message_id=mid,
                    first_message_text=initial_unified,
                    channel=source_name,
                    start_time=msg_ts,
                    first_message_strength=strength,
                )
                return

        if should_handle_open_event:
            await self._handle_open_event_flow(event, text, source_name)

    def _get_username(self, me) -> str:
        first_name = getattr(me, "first_name", None)
        last_name = getattr(me, "last_name", None)
        built_username = (
            f"{first_name}_{last_name}" if first_name and last_name else None
        )
        me_username = getattr(me, "username", None)
        return built_username or me_username or f"ID {me.id}"

    def _register_handlers(self) -> None:
        @self._client.on(events.NewMessage)
        async def on_new_message(event):
            try:
                if await self._handle_manual_close_command(event):
                    return
                await self._process_event(event, "new_message")
            except Exception:
                logger.exception("Error handling new message")

        @self._client.on(events.MessageEdited)
        async def on_edited_message(event):
            try:
                await self._process_event(event, "edited_message")
            except Exception:
                logger.exception("Error handling edited message")

    async def _init_watermarks(self) -> None:
        if not self._config.monitored_chats:
            logger.debug(
                "No monitored_chats set; watermarks will be built as messages arrive"
            )
            return

        for chat in self._config.monitored_chats:
            try:
                entity = await self._client.get_entity(chat)
                channel_id = getattr(entity, "id", None)

                if channel_id is None:
                    continue

                messages = await self._client.get_messages(entity, limit=1)

                if messages:
                    self._watermarks.update(channel_id, messages[0].id)
                    logger.debug(
                        "Watermark init | channel_id=%s | latest_message_id=%s",
                        channel_id,
                        messages[0].id,
                    )
                else:
                    self._watermarks.update(channel_id, 0)

            except Exception as e:
                logger.warning("Could not init watermark for %s: %s", chat, e)

    async def run(self) -> None:
        await self._client.start()
        me = await self._client.get_me()
        username = self._get_username(me)
        logger.info("Connected as %s", username)
        logger.info("Monitoring chats=%s", self._config.monitored_chats or "all")

        if self._config.is_debug:
            logger.info(
                "Debug mode: alerts sent to '%s'",
                self._config.target_debug_chat_id
                or "(not set, using BOT_TARGET_CHAT_ID)",
            )

        await self._resolve_control_chat_refs()
        await self._init_watermarks()
        await self._client.run_until_disconnected()

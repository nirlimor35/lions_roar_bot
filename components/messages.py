from __future__ import annotations

import asyncio
import html
from datetime import datetime, timedelta

import httpx
from loguru import logger

from components.constants import (
    AlertTitles,
    CloseReason,
    MessagePriority,
    ModuleColors,
    alert_title_for_priority,
    close_reason_label,
)
from components.utils import (
    ensure_utc,
    format_timelined_alert_body,
    format_ts_il,
    json_log_maker,
    sanitize_alert_body_text,
    utc_now,
)

# Telegram HTML has no dir/align; RLM per line fixes LTR-only lines (e.g. English
# channel names) so they align with Hebrew. RLI/PDI isolates English runs further.
_RLM = "\u200f"  # Right-to-Left Mark
_RLI = "\u2067"  # Right-to-Left Isolate
_PDI = "\u2069"  # Pop Directional Isolate


class TelegramMessageSender:
    """Outbound Telegram alerts via Bot API (httpx): HTML send/edit, pin, and bump-on-edit."""

    def __init__(
        self,
        bot_token: str,
        chat_id: int,
        *,
        pin_on_edit: bool = True,
        bump_on_edit: bool = True,
        delete_bump_message: bool = True,
    ) -> None:
        self._chat_id = chat_id
        self._base_url = f"https://api.telegram.org/bot{bot_token}"
        self._pin_on_edit = pin_on_edit
        self._bump_on_edit = bump_on_edit
        self._delete_bump_message = delete_bump_message

    @staticmethod
    def _elapsed_minutes(start: datetime, end: datetime) -> int:
        """Return elapsed time in whole minutes, rounded up to at least 1."""
        start = ensure_utc(start)
        end = ensure_utc(end)
        secs = max(0, int((end - start).total_seconds()))
        return max(1, (secs + 59) // 60)

    @staticmethod
    def _telegram_rtl_html(html: str) -> str:
        """Prefix each non-empty line with RLM so mixed Hebrew/English alerts align RTL."""
        return "\n".join(
            (_RLM + line) if line.strip() else line for line in html.split("\n")
        )

    def _build_alert_html(
        self,
        channels: list[str],
        unified_text: str,
        start_at: datetime,
        ended_at: datetime | None = None,
        *,
        alert_priority: MessagePriority = MessagePriority.HIGH,
        close_reason: CloseReason | None = None,
        subject: str | None = None,
        custom_close_reason: str | None = None,
        pending_close_reason: CloseReason | None = None,
        pending_close_seconds: int | None = None,
        alert_body_segments: list[tuple[datetime, str]] | None = None,
    ) -> str:
        if ended_at is not None:
            prefix = AlertTitles.ENDED
        elif pending_close_reason is not None:
            prefix = AlertTitles.PENDING_CLOSE
        else:
            prefix = alert_title_for_priority(alert_priority)

        safe_channels = [html.escape(c) for c in channels]
        if len(safe_channels) <= 1:
            ch = safe_channels[0] if safe_channels else "—"
            channel_block = f"<b>ערוץ:</b> {_RLI}{ch}{_PDI}"
        else:
            channel_block = "\n".join(
                ["<b>ערוצים:</b>", *[f"{_RLI}- {name}{_PDI}" for name in safe_channels]]
            )

        if alert_body_segments:
            body_plain = format_timelined_alert_body(unified_text, alert_body_segments)
        else:
            body_plain = sanitize_alert_body_text(unified_text)

        lines = [
            f"<b>{html.escape(prefix)}</b>",
            channel_block,
        ]
        if subject and subject.strip():
            lines.append(f"<b>נושא:</b> {html.escape(subject.strip())}")

        lines.extend(
            [
                f"<b>התחלה:</b> {html.escape(format_ts_il(start_at))}",
                "",
                html.escape(body_plain),
            ]
        )
        if ended_at is None and pending_close_reason is not None:
            wait_seconds = max(0, int(pending_close_seconds or 0))
            wait_minutes = max(1, (wait_seconds + 59) // 60)
            expected_close_at = ensure_utc(utc_now() + timedelta(seconds=wait_seconds))
            lines.append("")
            lines.append(
                f"<b>סטטוס:</b> מועמד לסגירה בעוד כ-{wait_minutes} דקות"
            )
            lines.append(
                f"<b>סגירה צפויה:</b> {html.escape(format_ts_il(expected_close_at))}"
            )
            lines.append(
                f"<b>סיבת סגירה צפויה:</b> {html.escape(close_reason_label(pending_close_reason))}"
            )
        if ended_at is not None:
            mins = self._elapsed_minutes(start_at, ended_at)
            reason = close_reason if close_reason is not None else CloseReason.ALL_CLEAR
            lines.append("")
            lines.append(
                f"<b>זמן סגירה:</b> {html.escape(format_ts_il(ended_at))} "
                f"(<b>משך:</b> {mins} דקות)"
            )
            # lines.append("")
            reason_line = (
                custom_close_reason.strip()
                if custom_close_reason and custom_close_reason.strip()
                else close_reason_label(reason)
            )
            lines.append(f"<b>סיבת סגירה:</b> {html.escape(reason_line)}")
        inner = "\n".join(lines)
        return self._telegram_rtl_html(inner)

    @staticmethod
    def _is_not_modified_error(resp: httpx.Response) -> bool:
        """Telegram edit no-op: same content already on message."""
        if resp.status_code != 400:
            return False
        try:
            payload = resp.json()
            description = str(payload.get("description", "")).lower()
        except Exception:
            description = resp.text.lower()
        return "message is not modified" in description

    async def _request_with_retry(
        self,
        endpoint: str,
        payload: dict,
        *,
        max_attempts: int = 3,
    ) -> httpx.Response:
        """
        POST to Telegram Bot API with retries on 5xx, 429, and network errors.
        Non-retryable 4xx (except 429) are returned immediately.
        """
        for attempt in range(1, max_attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(
                        f"{self._base_url}/{endpoint}",
                        json=payload,
                    )
                if resp.is_success:
                    return resp
                if resp.status_code == 429:
                    wait_s = float(attempt)
                    ra = resp.headers.get("Retry-After")
                    if ra:
                        try:
                            wait_s = float(ra)
                        except ValueError:
                            pass
                    logger.warning(
                        f"{ModuleColors.MESSAGE_PROCESSING} | {json_log_maker(endpoint=endpoint, attempt=attempt, max_attempts=max_attempts)} | Rate limited (429)"
                    )
                    if attempt < max_attempts:
                        await asyncio.sleep(wait_s)
                        continue
                    return resp
                if 400 <= resp.status_code < 500:
                    return resp
                logger.warning(
                    f"{ModuleColors.MESSAGE_PROCESSING} | {json_log_maker(endpoint=endpoint, attempt=attempt, max_attempts=max_attempts)} | Failed: {resp.status_code} {resp.text[:300]}"
                )
                if attempt < max_attempts:
                    await asyncio.sleep(float(attempt))
                    continue
                return resp
            except httpx.HTTPError as exc:
                logger.warning(
                    f"{ModuleColors.MESSAGE_PROCESSING} | {json_log_maker(endpoint=endpoint, attempt=attempt, max_attempts=max_attempts)} | Network error: {exc}"
                )
                if attempt < max_attempts:
                    await asyncio.sleep(float(attempt))
                    continue
                raise

    async def _pin_chat_message(self, message_id: int) -> None:
        """Pin the alert so it stays in the chat header (requires pin admin rights)."""
        resp = await self._request_with_retry(
            "pinChatMessage",
            {
                "chat_id": self._chat_id,
                "message_id": message_id,
                "disable_notification": False,
            },
        )
        if not resp.is_success:
            logger.warning(
                f"{ModuleColors.MESSAGE_PROCESSING} | {json_log_maker(endpoint='pinChatMessage', status_code=resp.status_code, text=resp.text)} | Pin chat message failed (bot may lack pin admin or chat type unsupported)"
            )

    async def _bump_edit_notification(self, reply_to_message_id: int) -> None:
        """
        Telegram does not notify on editMessageText. A short reply triggers
        sound / chat reorder like a normal message; optional delete keeps thread tidy.
        """
        resp = await self._request_with_retry(
            "sendMessage",
            {
                "chat_id": self._chat_id,
                "text": "🔔",
                "reply_to_message_id": reply_to_message_id,
                "disable_notification": False,
                "disable_web_page_preview": True,
            },
        )
        if not resp.is_success:
            logger.warning(
                f"{ModuleColors.MESSAGE_PROCESSING} | {json_log_maker(endpoint='sendMessage', status_code=resp.status_code, text=resp.text)} | Edit bump sendMessage failed"
            )
            return
        bump_id = int(resp.json()["result"]["message_id"])
        if not self._delete_bump_message:
            return
        del_resp = await self._request_with_retry(
            "deleteMessage",
            {
                "chat_id": self._chat_id,
                "message_id": bump_id,
            },
        )
        if not del_resp.is_success:
            logger.warning(
                f"{ModuleColors.MESSAGE_PROCESSING} | {json_log_maker(endpoint='deleteMessage', status_code=del_resp.status_code, text=del_resp.text)} | Delete message (bump) failed"
            )

    async def send_alert(
        self,
        channels: list[str],
        unified_text: str,
        start_at: datetime,
        ended_at: datetime | None = None,
        *,
        alert_priority: MessagePriority = MessagePriority.HIGH,
        close_reason: CloseReason | None = None,
        subject: str | None = None,
        custom_close_reason: str | None = None,
        pending_close_reason: CloseReason | None = None,
        pending_close_seconds: int | None = None,
        alert_body_segments: list[tuple[datetime, str]] | None = None,
    ) -> int:
        body = self._build_alert_html(
            channels,
            unified_text,
            start_at,
            ended_at,
            alert_priority=alert_priority,
            close_reason=close_reason,
            subject=subject,
            custom_close_reason=custom_close_reason,
            pending_close_reason=pending_close_reason,
            pending_close_seconds=pending_close_seconds,
            alert_body_segments=alert_body_segments,
        )
        resp = await self._request_with_retry(
            "sendMessage",
            {
                "chat_id": self._chat_id,
                "text": body,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )
        if not resp.is_success:
            logger.error(
                f"{ModuleColors.MESSAGE_PROCESSING} | {json_log_maker(endpoint='sendMessage', status_code=resp.status_code, text=resp.text)} | API error"
            )
        resp.raise_for_status()
        new_id = int(resp.json()["result"]["message_id"])
        logger.info(
            f"{ModuleColors.MESSAGE_PROCESSING} | {json_log_maker(destination_chat_id=self._chat_id, message_id=new_id)} | SendMessage (alert) ok"
        )
        return new_id

    async def send_plain_text(self, chat_id: int, text: str) -> None:
        """Send a plain text message to any chat (e.g. bot DM replies for admin commands)."""
        resp = await self._request_with_retry(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": True,
            },
        )
        if not resp.is_success:
            logger.warning(
                f"{ModuleColors.MESSAGE_PROCESSING} | {json_log_maker(endpoint='sendMessage', status_code=resp.status_code, text=resp.text)} | SendMessage (plain) failed"
            )
            return
        logger.info(
            f"{ModuleColors.MESSAGE_PROCESSING} | {json_log_maker(chat_id=chat_id, text_len=len(text))} | SendMessage (plain) ok"
        )

    async def edit_alert(
        self,
        message_id: int,
        channels: list[str],
        unified_text: str,
        start_at: datetime,
        ended_at: datetime | None = None,
        *,
        alert_priority: MessagePriority = MessagePriority.HIGH,
        close_reason: CloseReason | None = None,
        subject: str | None = None,
        custom_close_reason: str | None = None,
        pending_close_reason: CloseReason | None = None,
        pending_close_seconds: int | None = None,
        alert_body_segments: list[tuple[datetime, str]] | None = None,
    ) -> bool:
        body = self._build_alert_html(
            channels,
            unified_text,
            start_at,
            ended_at,
            alert_priority=alert_priority,
            close_reason=close_reason,
            subject=subject,
            custom_close_reason=custom_close_reason,
            pending_close_reason=pending_close_reason,
            pending_close_seconds=pending_close_seconds,
            alert_body_segments=alert_body_segments,
        )
        resp = await self._request_with_retry(
            "editMessageText",
            {
                "chat_id": self._chat_id,
                "message_id": message_id,
                "text": body,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )
        if not resp.is_success:
            if self._is_not_modified_error(resp):
                logger.info(
                    f"{ModuleColors.MESSAGE_PROCESSING} | {json_log_maker(message_id=message_id)} | EditMessageText no-op (message not modified)",
                )
                return False
            logger.error(
                f"{ModuleColors.MESSAGE_PROCESSING} | {json_log_maker(endpoint='editMessageText', status_code=resp.status_code, text=resp.text)} | EditMessageText error"
            )
        resp.raise_for_status()

        logger.info(
            f"{ModuleColors.MESSAGE_PROCESSING} | {json_log_maker(destination_chat_id=self._chat_id, message_id=message_id)} | EditMessageText (alert) ok"
        )
        if self._pin_on_edit:
            await self._pin_chat_message(message_id)
        if self._bump_on_edit:
            await self._bump_edit_notification(message_id)
        return True

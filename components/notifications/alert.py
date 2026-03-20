from __future__ import annotations

import html
import logging
from datetime import datetime, timezone

import httpx

from components.constants import FirstMessageStrength, MessageTitles
from components.utils import format_ts_il

logger = logging.getLogger(__name__)


class AlertSender:
    def __init__(
        self,
        bot_token: str,
        target_chat_id: str,
        *,
        pin_on_edit: bool = True,
        bump_on_edit: bool = True,
        delete_bump_message: bool = True,
    ):
        self._bot_token = bot_token
        self._target_chat_id = target_chat_id
        self._base_url = f"https://api.telegram.org/bot{bot_token}"
        self._pin_on_edit = pin_on_edit
        self._bump_on_edit = bump_on_edit
        self._delete_bump_message = delete_bump_message

    @staticmethod
    def _elapsed_minutes(start: datetime, end: datetime) -> int:
        """Return elapsed time in whole minutes, rounded up to at least 1."""
        s = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
        e = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
        secs = max(0, int((e - s).total_seconds()))
        return max(1, (secs + 59) // 60)

    @staticmethod
    def _alert_title_prefix(
        *,
        is_update: bool,
        alert_strength: FirstMessageStrength,
        first_message_strength: FirstMessageStrength,
    ) -> str:
        if not is_update:
            if alert_strength == FirstMessageStrength.WEAK:
                return MessageTitles.WEAK_ALERT.value
            if alert_strength == FirstMessageStrength.INFORMATIONAL:
                return MessageTitles.INFORMATIONAL.value
            return MessageTitles.ALERT.value

        # Promoted from weak/informational → strong: show as a full ALERT, not an update.
        if (
            alert_strength == FirstMessageStrength.STRONG
            and first_message_strength != FirstMessageStrength.STRONG
        ):
            return MessageTitles.ALERT.value
        if alert_strength == FirstMessageStrength.INFORMATIONAL:
            return MessageTitles.INFORMATIONAL.value
        return MessageTitles.UPDATE.value

    def _build_alert_html(
        self,
        channels: list[str],
        unified_text: str,
        start_at: datetime,
        ended_at: datetime | None = None,
        *,
        is_update: bool = False,
        alert_strength: FirstMessageStrength = FirstMessageStrength.STRONG,
        first_message_strength: FirstMessageStrength = FirstMessageStrength.STRONG,
    ) -> str:
        prefix = self._alert_title_prefix(
            is_update=is_update,
            alert_strength=alert_strength,
            first_message_strength=first_message_strength,
        )
        safe_channels = [html.escape(c) for c in channels]
        if len(safe_channels) <= 1:
            channel_block = f"<b>ערוץ:</b> {safe_channels[0] if safe_channels else '—'}"
        else:
            channel_block = "\n".join(
                ["<b>ערוצים:</b>", *[f"- {name}" for name in safe_channels]]
            )

        lines = [
            f"<b>{html.escape(prefix)}</b>",
            channel_block,
            f"<b>התחלה:</b> {html.escape(format_ts_il(start_at))}",
            "",
            html.escape(unified_text),
        ]
        if ended_at is not None:
            mins = self._elapsed_minutes(start_at, ended_at)
            lines.append("")
            lines.append(
                f"<b>סיום:</b> {html.escape(format_ts_il(ended_at))} "
                f"(<b>משך:</b> {mins} דקות)"
            )
        return "\n".join(lines)

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

    async def send_alert(
        self,
        channels: list[str],
        unified_text: str,
        start_at: datetime,
        ended_at: datetime | None = None,
        *,
        is_update: bool = False,
        alert_strength: FirstMessageStrength = FirstMessageStrength.STRONG,
        first_message_strength: FirstMessageStrength = FirstMessageStrength.STRONG,
    ) -> int:
        body = self._build_alert_html(
            channels,
            unified_text,
            start_at,
            ended_at,
            is_update=is_update,
            alert_strength=alert_strength,
            first_message_strength=first_message_strength,
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self._base_url}/sendMessage",
                json={
                    "chat_id": self._target_chat_id,
                    "text": body,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
            if not resp.is_success:
                logger.error("Telegram API error %s: %s", resp.status_code, resp.text)
            resp.raise_for_status()
            return int(resp.json()["result"]["message_id"])

    async def _pin_chat_message(self, message_id: int) -> None:
        """Pin the alert so it stays in the chat header (requires pin admin rights)."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self._base_url}/pinChatMessage",
                json={
                    "chat_id": self._target_chat_id,
                    "message_id": message_id,
                    "disable_notification": False,
                },
            )
            if not resp.is_success:
                logger.warning(
                    "pinChatMessage failed %s: %s (bot may lack pin admin or chat type unsupported)",
                    resp.status_code,
                    resp.text,
                )

    async def _bump_edit_notification(self, reply_to_message_id: int) -> None:
        """
        Telegram does not notify on editMessageText. A short reply triggers
        sound / chat reorder like a normal message; optional delete keeps thread tidy.
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self._base_url}/sendMessage",
                json={
                    "chat_id": self._target_chat_id,
                    "text": "🔔",
                    "reply_to_message_id": reply_to_message_id,
                    "disable_notification": False,
                    "disable_web_page_preview": True,
                },
            )
            if not resp.is_success:
                logger.warning(
                    "edit bump sendMessage failed %s: %s",
                    resp.status_code,
                    resp.text,
                )
                return
            bump_id = int(resp.json()["result"]["message_id"])
            if not self._delete_bump_message:
                return
            del_resp = await client.post(
                f"{self._base_url}/deleteMessage",
                json={
                    "chat_id": self._target_chat_id,
                    "message_id": bump_id,
                },
            )
            if not del_resp.is_success:
                logger.warning(
                    "deleteMessage (bump) failed %s: %s",
                    del_resp.status_code,
                    del_resp.text,
                )

    async def edit_alert(
        self,
        message_id: int,
        channels: list[str],
        unified_text: str,
        start_at: datetime,
        ended_at: datetime | None = None,
        *,
        is_update: bool = True,
        alert_strength: FirstMessageStrength = FirstMessageStrength.STRONG,
        first_message_strength: FirstMessageStrength = FirstMessageStrength.STRONG,
    ) -> bool:
        body = self._build_alert_html(
            channels,
            unified_text,
            start_at,
            ended_at,
            is_update=is_update,
            alert_strength=alert_strength,
            first_message_strength=first_message_strength,
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self._base_url}/editMessageText",
                json={
                    "chat_id": self._target_chat_id,
                    "message_id": message_id,
                    "text": body,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
            if not resp.is_success:
                if self._is_not_modified_error(resp):
                    logger.debug(
                        "Telegram editMessageText no-op (message not modified) | message_id=%s",
                        message_id,
                    )
                    return False
                logger.error(
                    "Telegram editMessageText error %s: %s", resp.status_code, resp.text
                )
            resp.raise_for_status()

        if self._pin_on_edit:
            await self._pin_chat_message(message_id)
        if self._bump_on_edit:
            await self._bump_edit_notification(message_id)
        return True

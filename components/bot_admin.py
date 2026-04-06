"""Bot API long-poll for /close in private chat; shared command matching for Telethon."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable

import httpx
from loguru import logger

from components.constants import ModuleColors
from components.utils import json_log_maker

_MANUAL_CLOSE_CMD = re.compile(r"^/close(?:@\S+)?\s*(.*)$")
_START_CMD = re.compile(r"^/start(?:@\S+)?\s*$")

HELP_TEXT = (
    "Lions Roar — שלח /close כדי לסגור אירוע פתוח. "
    "אפשר להוסיף טקסט אחרי הפקודה והוא יוצג כסיבת הסגירה בהתראה (במקום 'סגירה ידנית'). "
    "ההודעה לא תופיע בערוץ ההתראות."
)


def parse_manual_close_command(text: str | None) -> tuple[bool, str | None]:
    if not text:
        return False, None
    m = _MANUAL_CLOSE_CMD.match(text.strip())
    if not m:
        return False, None
    rest = m.group(1).strip()
    return True, rest if rest else None


def is_manual_close_command(text: str | None) -> bool:
    ok, _ = parse_manual_close_command(text)
    return ok


async def run_bot_dm_updates_loop(
    *,
    bot_token: str | None,
    admin_user_ids: frozenset[int],
    enabled: bool,
    manual_close: Callable[[str | None], Awaitable[str]],
    send_plain_text: Callable[[int, str], Awaitable[None]],
) -> None:
    if not enabled:
        return
    if not bot_token:
        logger.warning(
            f"{ModuleColors.INCIDENT_HANDLER} | Bot DM commands enabled but bot_token is missing; skipping getUpdates"
        )
        return
    base = f"https://api.telegram.org/bot{bot_token}"
    offset = 0
    logger.info(f"{ModuleColors.INCIDENT_HANDLER} | Bot DM: polling getUpdates for /close")
    while True:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(45.0)) as client:
                resp = await client.post(
                    f"{base}/getUpdates",
                    json={
                        "offset": offset,
                        "timeout": 30,
                        "allowed_updates": ["message"],
                    },
                )
            if not resp.is_success:
                logger.warning(
                    f"{ModuleColors.INCIDENT_HANDLER} | getUpdates failed {resp.status_code}: {resp.text[:300]}"    
                )
                await asyncio.sleep(5)
                continue
            data = resp.json()
            if not data.get("ok"):
                logger.warning(f"{ModuleColors.INCIDENT_HANDLER} | getUpdates not ok: {data}")
                await asyncio.sleep(5)
                continue
            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message")
                if not msg:
                    continue
                chat = msg.get("chat") or {}
                if chat.get("type") != "private":
                    continue
                uid = (msg.get("from") or {}).get("id")
                if uid not in admin_user_ids:
                    continue
                text = (msg.get("text") or "").strip()
                chat_id = chat.get("id")
                if chat_id is None:
                    continue
                if _START_CMD.match(text):
                    logger.info(
                        f"{ModuleColors.INCIDENT_HANDLER} | Bot DM | {json_log_maker(user_id=uid, chat_id=chat_id)} | /start"
                    )
                    await send_plain_text(chat_id, HELP_TEXT)
                    continue
                ok_close, reason_text = parse_manual_close_command(text)
                if not ok_close:
                    continue
                logger.info(
                    f"{ModuleColors.INCIDENT_HANDLER} | Bot DM | {json_log_maker(user_id=uid, chat_id=chat_id)} | Manual close command"
                )
                reply = await manual_close(reason_text)
                await send_plain_text(chat_id, reply)
        except asyncio.CancelledError:
            raise
        except httpx.HTTPError as exc:
            logger.warning(f"{ModuleColors.INCIDENT_HANDLER} | getUpdates HTTP error: {exc}")
            await asyncio.sleep(5)
        except Exception:
            logger.exception(f"{ModuleColors.INCIDENT_HANDLER} | getUpdates loop error")
            await asyncio.sleep(5)

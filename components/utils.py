import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from loguru import logger
from telethon import utils as tg_utils
from telethon.tl import types

from components.constants import ModuleColors

_IL_TZ = ZoneInfo("Asia/Jerusalem")


def utc_now() -> datetime:
    """Current time as timezone-aware UTC."""
    return datetime.now(timezone.utc)


def ensure_utc(dt: datetime) -> datetime:
    """Normalize to timezone-aware UTC (naive datetimes are treated as UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_reply_message_id(message) -> int | None:
    reply_to_header = getattr(message, "reply_to", None)
    if reply_to_header is not None:
        pid = getattr(reply_to_header, "reply_to_msg_id", None)
        if pid is not None:
            return pid
    return getattr(message, "reply_to_msg_id", None)


def message_timestamp(message) -> datetime:
    d = getattr(message, "date", None)
    if d is None:
        return utc_now()
    return ensure_utc(d)


def to_il_tz(dt: datetime) -> datetime:
    """Convert a UTC (or naive-UTC) datetime to Israel local time."""
    return ensure_utc(dt).astimezone(_IL_TZ)


def format_ts_il(dt: datetime) -> str:
    """Format a datetime as HH:MM DD/MM/YYYY in Israel local time."""
    return to_il_tz(dt).strftime("%H:%M %d/%m/%Y")


def format_time_il_hm(dt: datetime) -> str:
    return to_il_tz(ensure_utc(dt)).strftime("%H:%M")


def split_last_sentence(body: str) -> tuple[str, str]:
    b = (body or "").strip()
    if not b:
        return "", ""
    for sep in (".\n", ". "):
        pos = b.rfind(sep)
        if pos != -1:
            head = b[: pos + 1].strip()
            tail = b[pos + len(sep) :].strip()
            if tail:
                return head, tail
    return "", b


def format_timelined_alert_body(
    unified_text: str, segments: list[tuple[datetime, str]]
) -> str:
    base = sanitize_alert_body_text(unified_text)
    if not segments:
        return base
    if len(segments) == 1:
        ts, txt = segments[0]
        body = (txt or "").strip()
        if not body:
            return base
        return f"{format_time_il_hm(ts)} {body}"
    ts_last = segments[-1][0]
    head, tail = split_last_sentence(base)
    if head and tail:
        return f"{head}\n\n{format_time_il_hm(ts_last)} {tail}"
    last_src = (segments[-1][1] or "").strip()
    if last_src:
        return f"{base}\n\n{format_time_il_hm(ts_last)} {last_src}"
    return f"{base}\n\n{format_time_il_hm(ts_last)}"


def monitored_chats_list(monitored_chats) -> list:
    """Normalize config to a list (YAML may use a single string or omit the list)."""
    if not monitored_chats:
        return []
    if isinstance(monitored_chats, str):
        return [monitored_chats]
    return list(monitored_chats)


def _peer_ids_for_config_int(n: int) -> frozenset[int]:
    """Match Telethon's events.common._into_id_set for positive IDs."""
    if n < 0:
        return frozenset({n})
    return frozenset(
        {
            tg_utils.get_peer_id(types.PeerUser(n)),
            tg_utils.get_peer_id(types.PeerChat(n)),
            tg_utils.get_peer_id(types.PeerChannel(n)),
        }
    )


async def resolve_monitored_peer_ids(
    client, monitored_chats_config
) -> frozenset[int] | None:
    """
    Build the set of marked peer ids (event.chat_id) that count as monitored.

    Raw config matching was wrong in several ways: (1) YAML often gives numeric
    ids as strings, so `event.chat_id in monitored_chats` never matched; (2) bare
    positive channel ids (e.g. 1446968422) are not the same as marked ids
    (-1001446968422) that Telethon uses on events; (3) event.chat is often None
    until fetched, so username-based checks silently failed.
    """
    raw = monitored_chats_list(monitored_chats_config)
    if not raw:
        logger.info(f"{ModuleColors.MAIN} | Monitored peers allowlist empty, using all chats")
        return None
    result: set[int] = set()
    for chat in raw:
        if isinstance(chat, bool):
            continue
        try:
            if isinstance(chat, int):
                result.update(_peer_ids_for_config_int(chat))
                continue
            if isinstance(chat, str):
                s = chat.strip()
                if s.startswith("@"):
                    s = s[1:]
                if not s:
                    continue
                if s.removeprefix("-").isdigit():
                    result.update(_peer_ids_for_config_int(int(s)))
                    continue
                ent = await client.get_entity(s)
                result.add(tg_utils.get_peer_id(ent))
                continue
            logger.warning(
                f"{ModuleColors.MAIN} | {json_log_maker(type=type(chat), chat=chat)} | Unsupported monitored_chats entry type"
            )
        except Exception as e:
            logger.warning(f"{ModuleColors.MAIN} | Could not resolve monitored chat {chat!r}: {e}")
    peer_ids = frozenset(result)
    logger.info(
        f"{ModuleColors.MAIN} | {json_log_maker(count=len(peer_ids), peer_ids=sorted(peer_ids))} | Monitored peers resolved"
    )
    return peer_ids


async def resolve_source_chat(event) -> str:
    try:
        chat = await event.get_chat()
        title = getattr(chat, "title", None)
        username = getattr(chat, "username", None)
        cid = getattr(chat, "id", None)
        display = (
            (str(title).strip() if title else None)
            or (str(username).strip() if username else None)
            or (str(cid) if cid is not None else "Unknown chat")
        )
        return display
    except Exception:
        return "Unknown chat"


# Last paragraph is dropped only when it looks like a channel footer (links / promo),
# not when it is real content (e.g. "דרום הארץ" after a blank line).
_FOOTER_LAST_PARAGRAPH = re.compile(
    r"https?://|t\.me/|telegram\.me/|@[\w\d_]{3,}",
    re.IGNORECASE,
)


def clamp_word_count(text: str, max_words: int = 6) -> str:
    """Return up to the first max_words whitespace-separated tokens (summary lines)."""
    if not text:
        return ""
    parts = text.strip().split()
    if not parts:
        return ""
    return " ".join(parts[:max_words])


def sanitize_alert_body_text(text: str) -> str:
    if not text:
        return ""
    text = text.strip()
    if "\n\n" not in text:
        return text
    parts = text.split("\n\n")
    if len(parts) < 2:
        return text
    last = parts[-1].strip()
    if last and _FOOTER_LAST_PARAGRAPH.search(last):
        return "\n\n".join(parts[:-1]).strip()
    return text


# Parent message body in reply-threads can be long (graphics captions, etc.).
REPLY_PARENT_TEXT_MAX_CHARS = 3500


def _synthetic_reply_parent(parent_message_id: int, reason_hebrew: str) -> str:
    """So the LLM still sees a THREAD when Telegram says reply_to_msg_id but fetch failed."""
    return (
        f"[הודעת האב בערוץ (id {parent_message_id}) — {reason_hebrew}. "
        "יש תגובה בשרשור לפרסום הזה; שקלול יחד עם גוף ההודעה הנוכחית.]"
    )


async def fetch_replied_message_text(
    client, chat_id: int, message
) -> str | None:
    """
    If this Telegram message is a reply, fetch the parent message text/caption.

    Returns sanitized body or None. Same sanitization as inbound alerts so channel
    footers stay consistent.
    """
    reply_to_header = getattr(message, "reply_to", None)
    parent_message_id = None
    if reply_to_header is not None:
        parent_message_id = getattr(reply_to_header, "reply_to_msg_id", None)
    if parent_message_id is None:
        parent_message_id = getattr(message, "reply_to_msg_id", None)
    if parent_message_id is None:
        return None

    entity_for_parent_fetch = chat_id
    reply_to_peer_id = (
        getattr(reply_to_header, "reply_to_peer_id", None)
        if reply_to_header is not None
        else None
    )
    if reply_to_peer_id is not None:
        try:
            entity_for_parent_fetch = await client.get_input_entity(reply_to_peer_id)
        except Exception:
            logger.warning(
                f"{ModuleColors.MESSAGE_PROCESSING} | Could not resolve reply_to_peer_id; using synthetic parent | parent_message_id={parent_message_id}",
                exc_info=True,
            )
            return _synthetic_reply_parent(
                parent_message_id, "לא ניתן לפתור peer של ההורה"
            )

    try:
        fetch_result = await client.get_messages(
            entity_for_parent_fetch, ids=parent_message_id
        )
    except Exception:
        logger.warning(
            f"{ModuleColors.MESSAGE_PROCESSING} | get_messages failed for reply parent | parent_message_id={parent_message_id}",
            exc_info=True,
        )
        return _synthetic_reply_parent(
            parent_message_id, "טעינת ההודעה נכשלה"
        )

    if fetch_result is None:
        return _synthetic_reply_parent(
            parent_message_id, "אין תוצאה מטעינה"
        )
    # Telethon: get_messages(..., ids=one_id) often returns a single Message, not a list.
    try:
        parent_message = fetch_result[0]
    except TypeError:
        parent_message = fetch_result
    except IndexError:
        return _synthetic_reply_parent(
            parent_message_id, "הודעת האב לא נמצאה"
        )
    if parent_message is None:
        return _synthetic_reply_parent(
            parent_message_id, "הודעת האב ריקה"
        )
    parent_body_raw = (
        getattr(parent_message, "message", None)
        or getattr(parent_message, "text", None)
        or ""
    ).strip()
    if not parent_body_raw:
        # Keep THREAD context: many alert posts are image+graphics with little caption.
        parent_body_raw = (
            f"[הודעת האב (id {parent_message_id}) ללא טקסט או כיתוב — כנראה תמונה/מדיה. "
            "התגובה של המשתמש מתייחסת לאותה פרסום.]"
        )

    sanitized_parent_text = sanitize_alert_body_text(parent_body_raw)
    if len(sanitized_parent_text) > REPLY_PARENT_TEXT_MAX_CHARS:
        sanitized_parent_text = (
            sanitized_parent_text[:REPLY_PARENT_TEXT_MAX_CHARS].rstrip() + "…"
        )

    return sanitized_parent_text


def message_contains_video(message) -> bool:
    if getattr(message, "video", None) is not None:
        return True
    if getattr(message, "video_note", None) is not None:
        return True
    doc = getattr(message, "document", None)
    if doc is not None:
        mime = getattr(doc, "mime_type", None) or ""
        if mime.startswith("video/"):
            return True
    return False


def json_log_maker(**kwargs: dict) -> dict:
    log = {}
    for key, value in kwargs.items():
        log[key] = value
    return log

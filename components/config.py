import os
from dataclasses import dataclass
from pathlib import Path
from typing import FrozenSet, Union

from dotenv import load_dotenv

from components.constants import (
    DEFAULT_ALERT_KEYWORDS,
    DEFAULT_RELEVANT_LOCATIONS,
    DEFAULT_WEAK_FIRST_PHRASES,
)

load_dotenv(dotenv_path=Path(".env"))


def _parse_bool(value: str | None) -> bool:
    """Parse common boolean env values: 1/true/yes → True, else False."""
    if not value:
        return False
    return value.strip().lower() in ("1", "true", "yes")


def _require_env(key: str) -> str:
    """Return the env value for *key*, raising a clear error if it is missing."""
    value = os.environ.get(key)
    if not value:
        raise EnvironmentError(f"Required environment variable '{key}' is not set.")
    return value


@dataclass(frozen=True)
class Config:
    api_id: int
    api_hash: str
    session_name: str
    monitored_chats: FrozenSet[Union[int, str]]
    alert_keywords: tuple[str, ...]
    relevant_locations: tuple[str, ...]
    weak_first_phrases: tuple[str, ...]
    bot_token: str
    bot_target_chat_id: str
    is_debug: bool
    target_debug_chat_id: str | None
    openai_api_key: str | None
    openai_model: str | None
    alert_pin_on_edit: bool
    alert_bump_on_edit: bool
    alert_delete_bump_message: bool

    @classmethod
    def from_env(cls) -> "Config":
        """Load and validate configuration from environment variables."""
        is_debug = _parse_bool(os.environ.get("IS_DEBUG"))
        target_debug_chat_id = os.environ.get("TARGET_DEBUG_CHAT_ID")
        raw_chats = os.environ.get(
            "MONITORED_CHATS",
            "nirtestlionsroar"
            if is_debug
            else "raknetooooo,newssil,News_il_h,TheBigBadShadow",
        )
        monitored: set[Union[int, str]] = set()
        for part in raw_chats.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                monitored.add(int(part))
            except ValueError:
                monitored.add(part)

        return cls(
            api_id=int(_require_env("API_ID")),
            api_hash=_require_env("API_HASH"),
            session_name=_require_env("TG_SESSION_NAME"),
            monitored_chats=frozenset(monitored),
            alert_keywords=DEFAULT_ALERT_KEYWORDS,
            relevant_locations=DEFAULT_RELEVANT_LOCATIONS,
            weak_first_phrases=DEFAULT_WEAK_FIRST_PHRASES,
            bot_token=_require_env("BOT_TOKEN"),
            bot_target_chat_id=_require_env("BOT_TARGET_CHAT_ID"),
            is_debug=is_debug,
            target_debug_chat_id=target_debug_chat_id,
            openai_api_key=os.environ.get("OPENAI_API_KEY") or None,
            openai_model=os.environ.get("OPENAI_MODEL") or None,
            alert_pin_on_edit=not _parse_bool(
                os.environ.get("ALERT_DISABLE_PIN_ON_EDIT")
            ),
            alert_bump_on_edit=not _parse_bool(
                os.environ.get("ALERT_DISABLE_BUMP_ON_EDIT")
            ),
            alert_delete_bump_message=not _parse_bool(
                os.environ.get("ALERT_KEEP_BUMP_MESSAGE")
            ),
        )

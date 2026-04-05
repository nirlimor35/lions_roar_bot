def _normalize_channel_id(channel_id: int) -> int:
    """
    Normalize equivalent Telegram chat-id forms to one key.
    Examples:
      -1001667357802 -> 1667357802
       1667357802    -> 1667357802
      -1667357802    -> 1667357802
    """
    abs_id = abs(int(channel_id))
    as_text = str(abs_id)
    if as_text.startswith("100") and len(as_text) > 3:
        return int(as_text[3:])
    return abs_id


class ChannelWatermarks:
    """
    Tracks the latest seen message-id per channel so each message is processed
    at most once: skip when message_id <= watermark, advance watermark on process.
    """

    def __init__(self) -> None:
        self._latest_by_channel: dict[int, int] = {}

    @staticmethod
    def _canonical_chat_key(channel_id: int) -> int:
        return _normalize_channel_id(channel_id)

    def is_old(self, channel_id: int, message_id: int) -> bool:
        """True if we have already seen this message or a newer one from this channel."""
        key = self._canonical_chat_key(channel_id)
        return message_id <= self._latest_by_channel.get(key, 0)

    def update(self, channel_id: int, message_id: int) -> None:
        """Record that we've seen this message; keep the highest id per channel."""
        key = self._canonical_chat_key(channel_id)
        current = self._latest_by_channel.get(key, 0)
        self._latest_by_channel[key] = max(current, message_id)

    def latest(self, channel_id: int) -> int:
        """Return latest seen message id for the channel (0 if unseen)."""
        key = self._canonical_chat_key(channel_id)
        return self._latest_by_channel.get(key, 0)


class EditTextCache:
    """
    Tracks the last processed raw text per (channel, message_id) for edited messages.

    Telegram fires MessageEdited for link-preview attachment without changing message.text.
    Skipping edits whose text is identical to what was already processed prevents those
    silent re-fires from closing and re-opening incidents.
    """

    def __init__(self) -> None:
        self._last_text: dict[tuple[int, int], str] = {}

    def _key(self, channel_id: int, message_id: int) -> tuple[int, int]:
        return (_normalize_channel_id(channel_id), message_id)

    def is_duplicate(self, channel_id: int, message_id: int, text: str) -> bool:
        return self._last_text.get(self._key(channel_id, message_id)) == text

    def record(self, channel_id: int, message_id: int, text: str) -> None:
        self._last_text[self._key(channel_id, message_id)] = text

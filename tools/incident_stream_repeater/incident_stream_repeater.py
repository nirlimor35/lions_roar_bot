import asyncio
import json
import sys
from pathlib import Path

import yaml
from telethon import TelegramClient

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

with open(_ROOT / "config.yaml", "r") as f:
    _cfg = yaml.safe_load(f.read())

_SESSION_PATH = _ROOT / "lions_roar"
CHAT_ID = -1003728308111
_JSON_PATH = _ROOT / "message-loss-bugfix" / "second_batch_chronological.json"

with open(_JSON_PATH, "r") as f:
    _entries = json.load(f)


async def main() -> None:
    client = TelegramClient(
        str(_SESSION_PATH),
        int(_cfg["app_id"]),
        str(_cfg["api_hash"]),
    )
    async with client:
        for entry in _entries:
            gap_ms = int(entry.get("time_gap_ms", 10))
            await asyncio.sleep(max(0.0, gap_ms / 1000.0))
            text = entry.get("text") or ""
            ch = entry.get("channel_name", "")
            print(f"[{ch}] {text[:120]}{'…' if len(text) > 120 else ''}")
            await client.send_message(CHAT_ID, text)


if __name__ == "__main__":
    asyncio.run(main())

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

with open(_ROOT / "container_logs/log_2.json", "r") as f:
    data = json.load(f)

entries = [e for e in data if e.get("message") is not None]


async def main() -> None:
    client = TelegramClient(
        str(_SESSION_PATH),
        int(_cfg["app_id"]),
        str(_cfg["api_hash"]),
    )
    async with client:
        for i, entry in enumerate(entries):
            await _replay_entry(client, entry)
            if i >= len(entries) - 1:
                break
            if not await asyncio.to_thread(_wants_continue_after_prompt):
                break


async def _replay_entry(client: TelegramClient, entry: dict) -> None:
    final_text = entry["message"]
    previous = entry.get("previous_message")
    if previous:
        print(previous)
        sent = await client.send_message(CHAT_ID, previous)
        await asyncio.sleep(5)
        print(final_text)
        await sent.edit(final_text)
        return
    print(final_text)
    await client.send_message(CHAT_ID, final_text)


def _wants_continue_after_prompt() -> bool:
    reply = input("should send next message? Y/n ").strip().lower()
    return reply != "n"


if __name__ == "__main__":
    asyncio.run(main())

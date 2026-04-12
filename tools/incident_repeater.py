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


async def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] != "":
        log_file = sys.argv[1]
        if not log_file.endswith(".json"):
            log_file = f"{log_file}.json"
        with open(_ROOT / f"container_logs/{log_file}", "r") as f:
            data = json.load(f)

        entries = [e for e in data if e.get("message") is not None]
    else:
        exit("log file is required")
    client = TelegramClient(
        str(_SESSION_PATH),
        int(_cfg["app_id"]),
        str(_cfg["api_hash"]),
    )
    async with client:
        last_sent_by_message_id: dict[int, object] = {}
        for i, entry in enumerate(entries):
            await _replay_entry(client, entry, last_sent_by_message_id)
            if i >= len(entries) - 1:
                break
            if not await asyncio.to_thread(_wants_continue_after_prompt):
                break


async def _replay_entry(
    client: TelegramClient,
    entry: dict,
    last_sent_by_message_id: dict[int, object],
) -> None:
    final_text = entry["message"]
    llm_response = entry.get("llm_response") or {}
    mid = entry.get("message_id")
    et = entry.get("event_type")
    if llm_response.get("source_deleted"):
        if mid is not None and int(mid) in last_sent_by_message_id:
            sent = last_sent_by_message_id.pop(int(mid))
            print(final_text)
            await sent.delete()
            return
        print(final_text)
        sent = await client.send_message(CHAT_ID, final_text)
        await asyncio.sleep(1)
        await sent.delete()
        return
    previous = entry.get("previous_message")
    if previous:
        print(previous)
        sent = await client.send_message(CHAT_ID, previous)
        await asyncio.sleep(5)
        print(final_text)
        await sent.edit(final_text)
        if mid is not None:
            last_sent_by_message_id[int(mid)] = sent
        return
    if (
        et == "edited_message"
        and mid is not None
        and int(mid) in last_sent_by_message_id
    ):
        sent = last_sent_by_message_id[int(mid)]
        print(final_text)
        await sent.edit(final_text)
        return
    print(final_text)
    sent = await client.send_message(CHAT_ID, final_text)
    if mid is not None:
        last_sent_by_message_id[int(mid)] = sent


def _wants_continue_after_prompt() -> bool:
    reply = input("should send next message? Y/n ").strip().lower()
    return reply != "n"


if __name__ == "__main__":
    asyncio.run(main())

import json
import secrets
import string
from datetime import datetime
from pathlib import Path

from components.utils import to_il_tz

_INCIDENT_LOG_SUFFIX_ALPHABET = string.ascii_letters + string.digits


def new_incident_log_file_suffix() -> str:
    return "".join(
        secrets.choice(_INCIDENT_LOG_SUFFIX_ALPHABET) for _ in range(5)
    )


def _incident_log_filename(incident_start: datetime, log_file_suffix: str) -> str:
    base = to_il_tz(incident_start).strftime("%Y-%m-%dT%H:%M")
    return f"{base}-{log_file_suffix}.json"


def append_message(
    channel_name: str,
    message: str,
    message_dt: datetime,
    incident_start: datetime,
    message_id: int,
    llm_response: dict,
    log_file_suffix: str,
    tagged_message_id: int | None = None,
    event_type: str = "new_message",
    data_dir: str = "data",
) -> None:
    target = Path(data_dir) / _incident_log_filename(incident_start, log_file_suffix)
    target.parent.mkdir(parents=True, exist_ok=True)

    records: list[dict]
    if target.exists():
        try:
            loaded = json.loads(target.read_text(encoding="utf-8"))
            records = loaded if isinstance(loaded, list) else []
        except (json.JSONDecodeError, OSError):
            records = []
    else:
        records = []

    record: dict = {
        "channel_name": channel_name,
        "message_id": message_id,
        "message": message,
        "datetime": to_il_tz(message_dt).strftime("%Y-%m-%d %H:%M:%S"),
        "llm_response": llm_response,
        "event_type": event_type,
        "is_tagged": tagged_message_id is not None,
    }
    if tagged_message_id is not None:
        record["tagged_message_id"] = tagged_message_id
    records.append(record)

    tmp_target = target.with_suffix(f"{target.suffix}.tmp")
    tmp_target.write_text(
        json.dumps(records, ensure_ascii=False, indent=4),
        encoding="utf-8",
    )
    tmp_target.replace(target)


def append_incident_closure(
    incident_start: datetime,
    closed_at: datetime,
    subject: str,
    close_reason: str | None,
    log_file_suffix: str,
    data_dir: str = "data",
) -> None:
    target = Path(data_dir) / _incident_log_filename(incident_start, log_file_suffix)
    target.parent.mkdir(parents=True, exist_ok=True)

    records: list[dict]
    if target.exists():
        try:
            loaded = json.loads(target.read_text(encoding="utf-8"))
            records = loaded if isinstance(loaded, list) else []
        except (json.JSONDecodeError, OSError):
            records = []
    else:
        records = []

    record = {
        "event": "incident_closed",
        "subject": subject,
        "close_reason": close_reason,
        "datetime": to_il_tz(closed_at).strftime("%Y-%m-%d %H:%M:%S"),
    }
    records.append(record)

    tmp_target = target.with_suffix(f"{target.suffix}.tmp")
    tmp_target.write_text(
        json.dumps(records, ensure_ascii=False, indent=4),
        encoding="utf-8",
    )
    tmp_target.replace(target)

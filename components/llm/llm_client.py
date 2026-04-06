import json
from collections.abc import Callable
from dataclasses import dataclass

from loguru import logger
from openai import AsyncOpenAI

from components.constants import (
    CloseReason,
    MessagePriority,
    MessageType,
    ModuleColors,
    close_reason_label,
)
from components.Incident.tracker import ActiveIncident
from components.llm.prompts import (
    build_closed_subject_prompt,
    build_first_prompt,
    build_ongoing_prompt,
    build_reprocess_after_deletion_prompt,
)
from components.utils import json_log_maker


@dataclass
class LLMResponse:
    response_message: str | None
    qualified: bool
    priority: MessagePriority = MessagePriority.NONE
    related: bool = False
    ended: bool = False
    close_reason: CloseReason | None = None
    # Present when qualified and priority is high: up to 6 words, Hebrew.
    subject: str | None = None

    def to_log_dict(self) -> dict:
        return {
            "response_message": self.response_message,
            "qualified": self.qualified,
            "priority": self.priority.value,
            "related": self.related,
            "ended": self.ended,
            "close_reason": self.close_reason.value if self.close_reason else None,
            "subject": self.subject,
        }


class LLMClient:
    def __init__(self, openai_api_key: str, model: str | Callable[[], str]):
        self._client = AsyncOpenAI(api_key=openai_api_key)
        self._model = model

    def _resolve_model(self) -> str:
        if callable(self._model):
            resolved_model = self._model()
            return str(resolved_model).strip()
        return str(self._model).strip()

    @staticmethod
    def _coerce_bool(value) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes")
        return bool(value)

    @staticmethod
    def _coerce_close_reason(raw) -> CloseReason | None:
        if raw is None or raw == "":
            return None
        s = str(raw).strip().lower().replace("-", "_")
        try:
            return CloseReason(s)
        except ValueError:
            return None

    @staticmethod
    def _coerce_priority(raw) -> MessagePriority:
        if isinstance(raw, MessagePriority):
            return raw
        if raw is None:
            return MessagePriority.NONE
        try:
            return MessagePriority(str(raw).strip().lower())
        except ValueError:
            return MessagePriority.NONE

    def _llm_response_from_json(self, response_json: dict) -> LLMResponse:
        """Build LLMResponse with typed fields; JSON often uses string booleans."""
        related = (
            self._coerce_bool(response_json["related"])
            if "related" in response_json
            else False
        )
        ended = (
            self._coerce_bool(response_json["ended"])
            if "ended" in response_json
            else False
        )
        subj_raw = response_json.get("subject")
        subject: str | None = None
        if subj_raw is not None:
            s = str(subj_raw).strip()
            if s:
                subject = s

        return LLMResponse(
            response_message=response_json.get("response_message"),
            qualified=self._coerce_bool(response_json.get("qualified")),
            priority=self._coerce_priority(response_json.get("priority")),
            related=related,
            ended=ended,
            close_reason=self._coerce_close_reason(response_json.get("close_reason")),
            subject=subject,
        )

    async def _ask_llm(
        self, user_content: str, system_prompt: str, message_type: MessageType
    ) -> LLMResponse:
        response = await self._client.chat.completions.create(
            model=self._resolve_model(),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_completion_tokens=1024,
        )
        content = response.choices[0].message.content
        try:
            response_json = json.loads(content)
        except json.JSONDecodeError:
            logger.warning(f"{ModuleColors.LLM} | {json_log_maker(content=content)} | Bad JSON")
            return LLMResponse(
                response_message=None, 
                qualified=False, 
                priority=MessagePriority.NONE
            )
        return self._llm_response_from_json(response_json)

    async def run_llm(
        self,
        event_message: str,
        message_type: MessageType,
        incident: ActiveIncident | None = None,
        parent_message: str | None = None,
        recent_closure_appendix: str | None = None,
        source_messages_context: str | None = None,
        is_source_edit: bool = False,
        edited_message_previous_text: str | None = None,
    ) -> LLMResponse:
        if parent_message:
            user_content = (
                f"parent message for context: {parent_message}\n"
                f"new update: {event_message}"
            )
        else:
            user_content = event_message

        if incident is None:
            system_prompt = build_first_prompt(recent_closure_appendix)
            response = await self._ask_llm(
                user_content, system_prompt, MessageType.NEW_MESSAGE
            )
            logger.info(
                f"{ModuleColors.LLM} | {json_log_maker(message_type=message_type, qualified=response.qualified, priority=response.priority)} | New-incident prompt"
            )
            return response

        system_prompt = build_ongoing_prompt(
            existing_update=incident.unified_text,
            existing_priority=incident.alert_priority,
            source_messages_context=source_messages_context,
            is_source_edit=is_source_edit,
            edited_message_previous_text=edited_message_previous_text,
        )
        response = await self._ask_llm(user_content, system_prompt, message_type)
        logger.info(
            f"{ModuleColors.LLM} | {json_log_maker(message_type=message_type, incident_id=incident.incident_id, related=response.related, qualified=response.qualified, ended=response.ended, priority=response.priority)} | Merge prompt"
        )
        return response

    async def reprocess_after_deletion(
        self,
        *,
        incident: ActiveIncident,
        source_messages_context: str,
    ) -> LLMResponse:
        system_prompt = build_reprocess_after_deletion_prompt(
            existing_update=incident.unified_text,
            existing_priority=str(incident.alert_priority.value),
            source_messages_context=source_messages_context,
        )
        user_content = (
            "Recompute the incident narrative and priority from the remaining sources only."
        )
        response = await self._ask_llm(
            user_content, system_prompt, MessageType.DELETED_MESSAGE
        )
        logger.info(
            f"{ModuleColors.LLM} | {json_log_maker(incident_id=incident.incident_id, qualified=response.qualified, ended=response.ended, priority=response.priority)} | Reprocess-after-deletion prompt"
        )
        return response

    async def summarize_closed_incident_subject(
        self,
        *,
        unified_text: str,
        close_reason: CloseReason | None,
    ) -> str | None:
        reason = close_reason or CloseReason.ALL_CLEAR
        prompt = build_closed_subject_prompt(
            close_reason_code=reason.value,
            close_reason_label_text=close_reason_label(reason),
        )
        response = await self._client.chat.completions.create(
            model=self._resolve_model(),
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": (unified_text or "").strip() or "(אין טקסט מאוחד)",
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_completion_tokens=256,
        )
        content = response.choices[0].message.content
        try:
            response_json = json.loads(content)
        except json.JSONDecodeError:
            logger.warning(
                f"{ModuleColors.LLM} | {json_log_maker(content=content)} | Closed-subject Bad JSON"
            )
            return None
        subj_raw = response_json.get("subject")
        if subj_raw is None:
            return None
        s = str(subj_raw).strip()
        return s if s else None

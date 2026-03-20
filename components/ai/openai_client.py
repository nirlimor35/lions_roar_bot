"""OpenAI helpers: narrative merge and event-end fallback."""

from __future__ import annotations

import json
import logging
import re

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class OpenAIAlertsClient:
    # New default; can be overridden by OPENAI_MODEL in env.
    DEFAULT_MODEL = "gpt-4.1-mini"

    MERGE_SYSTEM = """You merge chronological emergency updates into one concise, accurate summary.

Hard accuracy rules:
1) Do not invent facts and do not infer outcomes that are not explicitly stated in the new message.
2) Keep launch waves/scopes separate:
   - If the new message says things like "additional launches", "another wave", or equivalent, treat it as a new wave.
   - Outcomes from a previous wave (e.g., "fell into the sea", "no casualties") must NOT be applied to the new wave unless explicitly stated.
3) If the new message corrects the previous text for the same wave, replace the outdated part.
4) If the outcome of the new wave is unknown, state uncertainty factually (e.g., "the outcome of the additional launches is still unclear").
5) Keep it short and clear, with no title and no quotes.
6) First decide if the new message is related to the currently open incident.
   - If unrelated (politics, diplomacy, general commentary, background analysis, or any topic not updating the active incident), set related=false and do not merge.
7) Preserve scope:
   - Only include locations/details that belong to the same active incident context.
   - If a detail may be a separate arena/incident and there is no explicit linkage, omit it from the merged incident summary.
8) Writing quality and structure:
   - Hebrew only.
   - No repetition or duplicated meaning.
   - Output must be a chronological bullet list (oldest to newest).
   - Each bullet must start exactly with: "• HH:mm " (24h format).
   - Use the provided new-message time for the new/updated bullet for that message.
   - Keep the whole summary concise.
   - Keep uncertainty precise (e.g., "היעד המדויק טרם התברר") and tied to the relevant wave.
   - Avoid generic vague phrases like "יעד לא ידוע" unless clearly scoped.
9) The final merged text in "unified" must be in Hebrew.

Return JSON only in this exact shape: {"related": true|false, "unified":"..."}
If related=false, keep "unified" as an empty string."""

    EVENT_END_SYSTEM = """Decide whether the next message clearly states that the alert/emergency incident has ended
(people can return to routine, all-clear, incident over, etc.).

Return JSON only: {"ended": true} or {"ended": false}"""

    def __init__(self, api_key: str, model: str | None = None) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model if model is not None else self.DEFAULT_MODEL

    @staticmethod
    def _extract_json_object(raw: str) -> dict:
        raw = raw.strip()
        # Allow markdown code fences
        fence = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", raw)
        if fence:
            raw = fence.group(1).strip()
        return json.loads(raw)

    async def merge_unified_text(
        self,
        current_unified: str,
        new_text: str,
        new_event_time_hhmm: str,
    ) -> str | None:
        user = (
            f"Current accumulated summary:\n{current_unified}\n\n"
            f"New message event time (Asia/Jerusalem, HH:mm):\n{new_event_time_hhmm}\n\n"
            f"New message to merge:\n{new_text}"
        )
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": self.MERGE_SYSTEM},
                {"role": "user", "content": user},
            ],
            temperature=0.0,
            max_tokens=500,
        )
        raw = (response.choices[0].message.content or "").strip()
        try:
            data = self._extract_json_object(raw)
            if not bool(data.get("related")):
                logger.debug("merge_unified_text: unrelated update skipped")
                return None
            unified = (data.get("unified") or "").strip()
            if not unified:
                logger.warning(
                    "merge_unified_text: related=true but empty unified; keeping current summary"
                )
                return current_unified
            return unified
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            logger.warning("merge_unified_text: bad JSON %s | raw=%.200s", e, raw)
            # Conservative fallback: avoid injecting unrelated content on parse failure.
            return current_unified

    async def check_event_end_llm(self, text: str) -> bool:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": self.EVENT_END_SYSTEM},
                {"role": "user", "content": text},
            ],
            temperature=0.0,
            max_tokens=50,
        )
        raw = (response.choices[0].message.content or "").strip()
        try:
            data = self._extract_json_object(raw)
            return bool(data.get("ended"))
        except (json.JSONDecodeError, TypeError):
            logger.debug("check_event_end_llm: parse fail | raw=%.120s", raw)
            return False

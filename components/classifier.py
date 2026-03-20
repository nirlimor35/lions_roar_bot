import logging

from components.constants import FirstMessageStrength
from components.utils import normalize_text

logger = logging.getLogger(__name__)


class MessageClassifier:
    """
    Two-stage classifier:
      1. is_candidate — cheap keyword scan for strong signals (area + rockets).
      2. classify     — strong (keywords + location), weak (weak-first phrases), else none.
    """

    def __init__(
        self,
        alert_keywords: tuple[str, ...],
        relevant_locations: tuple[str, ...],
        weak_first_phrases: tuple[str, ...],
    ) -> None:
        self._keywords = alert_keywords
        self._locations = relevant_locations
        self._weak_phrases = weak_first_phrases

    def is_candidate(self, text: str) -> bool:
        """
        Returns True if the message contains at least one alert keyword.
        Keep this broad so important alerts are never dropped before the LLM.
        """
        if not text:
            return False
        normalized = normalize_text(text)
        return any(kw in normalized for kw in self._keywords)

    def is_strong_signal(self, text: str) -> bool:
        """Keywords plus monitored-area substring (same rule as strong classify)."""
        if not self.is_candidate(text):
            return False
        normalized = normalize_text(text)
        return any(loc in normalized for loc in self._locations)

    def _is_weak_first(self, normalized: str) -> bool:
        return any(phrase in normalized for phrase in self._weak_phrases)

    async def classify(self, text: str, source_name: str) -> FirstMessageStrength:
        normalized = normalize_text(text)

        if self.is_strong_signal(text):
            logger.debug(
                "classify strong | source=%s | text=%.80s",
                source_name,
                text,
            )
            return FirstMessageStrength.STRONG

        if self._is_weak_first(normalized):
            logger.debug(
                "classify weak | source=%s | text=%.80s",
                source_name,
                text,
            )
            return FirstMessageStrength.WEAK

        if self.is_candidate(text):
            logger.debug(
                "Pre-filter keywords but no area / weak phrase | text=%.80s",
                text,
            )
        else:
            logger.debug("Pre-filter skipped | text=%.80s", text)
        return FirstMessageStrength.NONE

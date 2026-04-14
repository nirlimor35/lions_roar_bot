from collections.abc import Callable

from components.llm.llm_client import LLMClient

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterClient(LLMClient):
    def __init__(
        self,
        api_key: str,
        model: str | Callable[[], str],
    ) -> None:
        super().__init__(api_key=api_key, model=model, base_url=OPENROUTER_BASE_URL)

from collections.abc import Callable

from components.llm.llm_client import LLMClient

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"


class GroqClient(LLMClient):
    def __init__(
        self,
        api_key: str,
        model: str | Callable[[], str],
    ) -> None:
        super().__init__(api_key=api_key, model=model, base_url=DEEPSEEK_BASE_URL)

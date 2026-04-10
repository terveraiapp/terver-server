import os
from langchain_core.language_models import BaseChatModel


def get_llm() -> BaseChatModel:
    """
    Factory function that returns the active LLM provider based on ACTIVE_PROVIDER env var.

    Supports:
    - "gemini" (default): Google Gemini via langchain_google_genai
    - "claude": Anthropic Claude via langchain_anthropic

    Returns:
        BaseChatModel: The configured LLM instance
    """
    provider = os.environ.get("ACTIVE_PROVIDER", "gemini").lower()

    if provider == "claude":
        from app.providers.claude import get_claude_llm
        return get_claude_llm()

    from app.providers.gemini import get_gemini_llm
    return get_gemini_llm()

import os
from langchain_anthropic import ChatAnthropic


def get_claude_llm() -> ChatAnthropic:
    """
    Initialize and return a ChatAnthropic instance.

    Uses claude-sonnet-4-6 as the model.
    Requires ANTHROPIC_API_KEY environment variable.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable is required")
    return ChatAnthropic(
        model="claude-sonnet-4-6",
        api_key=api_key,
        max_tokens=16000,
        temperature=0.1,
    )

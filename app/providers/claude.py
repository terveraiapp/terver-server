import os
from langchain_anthropic import ChatAnthropic


def get_claude_llm() -> ChatAnthropic:
    """
    Initialize and return a ChatAnthropic instance.

    Uses claude-opus-4-6 as the most capable model for complex tasks.
    Requires ANTHROPIC_API_KEY environment variable.
    """
    return ChatAnthropic(
        model="claude-sonnet-4-6",
        api_key=os.environ["ANTHROPIC_API_KEY"],
        max_tokens=16000,
        temperature=0.1,
    )

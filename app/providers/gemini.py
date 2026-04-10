import os
from langchain_google_genai import ChatGoogleGenerativeAI


def get_gemini_llm() -> ChatGoogleGenerativeAI:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is required")
    return ChatGoogleGenerativeAI(
        model="gemini-3.1-pro-preview",
        google_api_key=api_key,
        temperature=0.1,
        thinking_level="high",
        include_thoughts=True,
    )

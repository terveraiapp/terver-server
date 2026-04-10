import os
from langchain_google_genai import ChatGoogleGenerativeAI


def get_gemini_llm() -> ChatGoogleGenerativeAI:
    """
    Initialize and return a ChatGoogleGenerativeAI instance.

    Uses gemini-2.0-flash-001 as the stable production model.
    Requires GEMINI_API_KEY environment variable.
    """
    return ChatGoogleGenerativeAI(
        model="gemini-2.0-flash-001",
        google_api_key=os.environ["GEMINI_API_KEY"],
        temperature=0.1,
    )

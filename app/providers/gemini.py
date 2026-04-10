import os
from langchain_google_genai import ChatGoogleGenerativeAI


def get_gemini_llm() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model="gemini-3.1-pro-preview",
        google_api_key=os.environ["GEMINI_API_KEY"],
        temperature=0.1,
        thinking_level="high",
        include_thoughts=True,
    )

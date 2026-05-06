"""
Singleton LLM clients.
All services import from here — never instantiate clients directly.
Both clients are configured with max_retries=3 (SDK-level exponential backoff).
"""

import os
import anthropic
from openai import OpenAI

_anthropic: anthropic.Anthropic | None = None
_openai: OpenAI | None = None


def get_anthropic() -> anthropic.Anthropic:
    global _anthropic
    if _anthropic is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set in .env")
        _anthropic = anthropic.Anthropic(api_key=api_key, max_retries=3)
    return _anthropic


def get_openai() -> OpenAI:
    global _openai
    if _openai is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set in .env")
        _openai = OpenAI(api_key=api_key, max_retries=3)
    return _openai
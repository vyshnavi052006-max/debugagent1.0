"""
groq_client.py
--------------
Thin wrapper around the free Groq API (https://console.groq.com) used for:
  - domain classification (is this a coding/debugging question?)
  - bug analysis & root cause reasoning
  - generating a fix
  - plain-English explanation

Reads GROQ_API_KEY from the environment. Never hardcode keys in source.
"""

import os
from typing import Optional

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

_client: Optional[Groq] = None
MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")


def _get_client() -> Groq:
    global _client
    if _client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Copy .env.example to .env and add your free key "
                "from https://console.groq.com/keys"
            )
        _client = Groq(api_key=api_key)
    return _client


def ask(system_prompt: str, user_prompt: str, temperature: float = 0.3, max_tokens: int = 800) -> str:
    """Single-turn helper: returns the model's text response."""
    client = _get_client()
    completion = client.chat.completions.create(
        model=MODEL,
        temperature=temperature,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return completion.choices[0].message.content.strip()

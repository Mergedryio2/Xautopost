from __future__ import annotations

from typing import Literal

import google.generativeai as genai
from openai import AsyncOpenAI

Provider = Literal["openai", "gemini"]


async def generate_content(
    *,
    provider: Provider,
    model: str,
    system_prompt: str,
    api_key: str,
    user_prompt: str = "Generate one tweet now.",
    max_tokens: int = 400,
) -> str:
    """Call the AI provider, returning the generated text."""

    if provider == "openai":
        client = AsyncOpenAI(api_key=api_key)
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
        )
        return (resp.choices[0].message.content or "").strip()

    if provider == "gemini":
        # google-generativeai 0.8 uses module-level configure(); on a single-user
        # desktop this is fine, but concurrent calls with different keys would race.
        genai.configure(api_key=api_key)
        gmodel = genai.GenerativeModel(
            model_name=model, system_instruction=system_prompt
        )
        resp = await gmodel.generate_content_async(user_prompt)
        return (resp.text or "").strip()

    raise ValueError(f"unknown provider: {provider}")

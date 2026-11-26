import os
from pathlib import Path

from openai import OpenAI

from chat.env import load_env

BASE_URL = "https://ai.reg.cloud/v1"
MODEL = "deepseek-v4.1-flash"
SYSTEM_PROMPT = (
    "Ты помощник сотрудников по внутренним регламентам. "
    "Отвечай кратко и по делу на русском языке. "
    "Если в вопросе не хватает данных для однозначного ответа, задай уточняющий вопрос."
)

_client: OpenAI | None = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        load_env(Path(__file__).resolve().parents[1] / "secrets" / "env")
        api_key = os.environ.get("API_KEY")
        if not api_key:
            raise RuntimeError("API_KEY is not set")
        _client = OpenAI(api_key=api_key, base_url=BASE_URL)
    return _client


def complete(messages: list[dict[str, str]]) -> str:
    response = get_client().chat.completions.create(
        model=MODEL,
        max_tokens=2500,
        temperature=0.5,
        presence_penalty=0,
        top_p=0.95,
        messages=[{"role": "system", "content": SYSTEM_PROMPT}, *messages],
    )
    return response.choices[0].message.content or ""

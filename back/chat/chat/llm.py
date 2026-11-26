import os
from pathlib import Path

from openai import OpenAI

from chat.env import load_env
from chat.knowledge import latest_question, render_context

BASE_URL = "https://ai.reg.cloud/v1"
MODEL = "deepseek-v4.1-flash"
SYSTEM_PROMPT = (
    "Ты помощник сотрудников по внутренним регламентам. "
    "Отвечай кратко и по делу на русском языке. "
    "Используй только глоссарий и фрагменты регламентов из этого сообщения. "
    "Сокращение и его полные формы из глоссария означают одно и то же. "
    "Для каждого раздела, на который опирается ответ, вставь его markdown-ссылку из контекста. "
    "Текст ссылки — заголовок раздела, адрес начинается с /kb/. "
    "Не пиши слово «Ссылка» и не используй другую разметку. "
    "Если используешь термин глоссария, можно сослаться на него как [РП](/kb/glossary#s-РП), подставив сокращение. "
    "Другие URL не добавляй. "
    "Если подходящие фрагменты относятся к разным регламентам и из вопроса неясно, "
    "какой имеется в виду, задай уточняющий вопрос. "
    "Если фрагментов недостаточно для однозначного ответа, задай уточняющий вопрос. "
    "Если в фрагментах нет ответа, прямо скажи об этом и ничего не выдумывай."
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
    system = f"{SYSTEM_PROMPT}\n\n{render_context(latest_question(messages))}"
    response = get_client().chat.completions.create(
        model=MODEL,
        max_tokens=2500,
        temperature=0.5,
        presence_penalty=0,
        top_p=0.95,
        messages=[{"role": "system", "content": system}, *messages],
    )
    return response.choices[0].message.content or ""

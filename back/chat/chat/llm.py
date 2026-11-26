import logging
import os
from dataclasses import dataclass
from pathlib import Path

from openai import OpenAI, OpenAIError
from openai.types.chat import ChatCompletionMessageParam

from chat.env import load_env
from chat.knowledge import Clause, prompt_context, search_clauses
from chat.reasoning import (
    Dialogue,
    allowed_sections,
    bad_links,
    cited_document_ids,
    drop_bad_links,
    link_document_titles,
    read_dialogue,
    regulations_are_separate,
    render_turn,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://ai.reg.cloud/v1"
MODEL = "deepseek-v4.1-flash"
TEMPERATURE = 0.2
SYSTEM_PROMPT = (
    "Ты помощник сотрудников по внутренним регламентам. "
    "Отвечай кратко и по делу на русском языке. "
    "Используй только глоссарий и пункты регламентов из этого сообщения. "
    "Сокращение и его полные формы из глоссария означают одно и то же. "
    "Пункты в сообщении — кандидаты по совпадению слов, от более похожих к менее похожим. "
    "В ответ включи только пункты, из которых следует ответ на действие и этап из вопроса. "
    "Пункт про другой этап или другое событие не цитируй, даже если слова совпадают. "
    "Регламент без такого пункта не упоминай. Отброшенное не перечисляй и не объясняй. "
    "Для каждого пункта, на который опирается ответ, вставь его markdown-ссылку из контекста. "
    "Текст ссылки — номер пункта, адрес начинается с /kb/. "
    "Если называешь регламент, вставь markdown-ссылку на документ целиком, например "
    "[Организация проектной деятельности](/kb/project-activity-technical-directorate). "
    "Не пиши слово «Ссылка» и не выделяй название звёздочками. "
    "Если используешь термин глоссария, можно сослаться на него как [РП](/kb/glossary#s-РП), подставив сокращение. "
    "Другие URL не добавляй. "
    "Если в пунктах нет ответа, прямо скажи об этом и ничего не выдумывай."
)
EMPTY_REPLY = (
    "В приложенных фрагментах нет подтверждённого ответа. "
    "Следующий шаг — обращение в управление качества."
)

_client: OpenAI | None = None


@dataclass(frozen=True)
class TurnResult:
    reply: str
    allowed: frozenset[tuple[str, str]]
    clause_ids: frozenset[str]


def get_client() -> OpenAI:
    global _client
    if _client is None:
        load_env(Path(__file__).resolve().parents[1] / "secrets" / "env")
        api_key = os.environ.get("API_KEY")
        if not api_key:
            raise RuntimeError("API_KEY is not set")
        _client = OpenAI(api_key=api_key, base_url=BASE_URL)
    return _client


def _chat_messages(messages: list[dict[str, str]]) -> list[ChatCompletionMessageParam]:
    converted: list[ChatCompletionMessageParam] = []
    for item in messages:
        role = item["role"]
        content = item["content"]
        if role == "user":
            converted.append({"role": "user", "content": content})
        elif role == "assistant":
            converted.append({"role": "assistant", "content": content})
        elif role == "system":
            converted.append({"role": "system", "content": content})
        else:
            raise ValueError(f"unsupported message role: {role}")
    return converted


def rewrite_query(question: str) -> str:
    text = question.strip()
    if not text:
        return ""
    context = prompt_context()
    headings = "\n".join(f"- {heading}" for heading in context.headings)
    aliases = context.aliases
    prompt = (
        "Перепиши вопрос сотрудника в одну строку поисковых слов из регламентов. "
        "Используй термины заголовков и сокращения глоссария. Без пояснений.\n\n"
        f"Вопрос:\n{text}\n\nЗаголовки:\n{headings}\n\nГлоссарий:\n{aliases}"
    )
    try:
        response = get_client().chat.completions.create(
            model=MODEL,
            max_tokens=900,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
    except OpenAIError:
        logger.exception("query rewrite failed")
        return ""
    rewritten = (response.choices[0].message.content or "").strip().splitlines()
    if not rewritten:
        return ""
    line = rewritten[0].strip().strip("\"'")
    if len(line) > 400:
        return ""
    logger.info("rewritten query: %s", line)
    return line


def complete(messages: list[dict[str, str]]) -> str:
    return answer_turn(messages).reply


def answer_turn(messages: list[dict[str, str]]) -> TurnResult:
    dialogue = read_dialogue(messages)
    question = _search_question(dialogue)
    found = search_clauses(question, document_ids=dialogue.document_ids())
    clauses = [clause for clause, _score in found]
    logger.info(
        "knowledge context for %r: %s",
        dialogue.latest[:180],
        "; ".join(f"{clause.document_id} / {clause.clause_id}" for clause in clauses) or "none",
    )
    system = f"{SYSTEM_PROMPT}\n\n{render_turn(dialogue, clauses)}"
    reply = _generate(system, messages)
    allowed = allowed_sections(clauses)
    if reply and _needs_retry(reply, clauses, allowed):
        retried = _generate(f"{system}\n\n{_retry_note(reply, clauses, allowed)}", messages)
        if retried:
            reply = retried
    cleaned = link_document_titles(drop_bad_links(reply, allowed))
    if not cleaned:
        cleaned = EMPTY_REPLY
    return TurnResult(
        reply=cleaned,
        allowed=frozenset(allowed),
        clause_ids=frozenset(clause.clause_id for clause in clauses),
    )


def _search_question(dialogue: Dialogue) -> str:
    base = dialogue.search_text()
    rewritten = rewrite_query(base)
    if not rewritten:
        return base
    return f"{base}\n{rewritten}"


def _generate(system: str, messages: list[dict[str, str]]) -> str:
    response = get_client().chat.completions.create(
        model=MODEL,
        max_tokens=2500,
        temperature=TEMPERATURE,
        presence_penalty=0,
        top_p=0.95,
        messages=[{"role": "system", "content": system}, *_chat_messages(messages)],
    )
    return (response.choices[0].message.content or "").strip()


def _needs_retry(reply: str, clauses: list[Clause], allowed: set[tuple[str, str]]) -> bool:
    if bad_links(reply, allowed):
        return True
    return not regulations_are_separate(reply, clauses, cited_document_ids(reply))


def _retry_note(reply: str, clauses: list[Clause], allowed: set[tuple[str, str]]) -> str:
    lines = ["Исправь ответ."]
    rejected = bad_links(reply, allowed)
    if rejected:
        lines.append("Удали утверждения со ссылками вне подборки: " + ", ".join(rejected))
        lines.append("Оставляй только ссылки из приложенных пунктов.")
    cited = cited_document_ids(reply)
    if not regulations_are_separate(reply, clauses, cited):
        cited_links: list[str] = []
        seen: set[str] = set()
        for clause in clauses:
            if clause.document_id not in cited or clause.document_id in seen:
                continue
            seen.add(clause.document_id)
            cited_links.append(f"[{clause.document}](/kb/{clause.document_id})")
        lines.append(
            "Ответ по нескольким регламентам раздели на части. "
            "Первая строка каждой части — ссылка на документ, без звёздочек: "
            + "; ".join(cited_links)
        )
    return "\n".join(lines)

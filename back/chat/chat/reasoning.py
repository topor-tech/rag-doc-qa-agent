"""Decide what a turn may claim, then keep the reply inside that shortlist."""

import re
from dataclasses import dataclass

from chat.knowledge import MAX_CLARIFICATIONS, Clause, prompt_context

_KB_LINK = re.compile(r"\(/kb/([^)#\s]+)#(s-[^)\s]+)\)")


@dataclass(frozen=True)
class Directorate:
    id: str
    title: str
    document_ids: frozenset[str]
    pattern: re.Pattern[str]


DIRECTORATES = (
    Directorate(
        "ib",
        "Дирекция ИБ",
        frozenset({"project-activity-ib", "presales-activity-ib"}),
        re.compile(
            r"дирекци[а-яё]*\s+иб|\bиб\b|информационн[а-яё]+\s+безопасност",
            re.IGNORECASE,
        ),
    ),
    Directorate(
        "dbrct",
        "ДБРЦТ",
        frozenset({"project-activity-dbrct"}),
        re.compile(r"дбрцт|бизнес-решен|цифров[а-яё]+\s+трансформац", re.IGNORECASE),
    ),
    Directorate(
        "technical",
        "Техническая дирекция",
        frozenset({"project-activity-technical-directorate"}),
        re.compile(r"техническ[а-яё]+\s+дирекц|техдирекц", re.IGNORECASE),
    ),
)


@dataclass(frozen=True)
class Dialogue:
    original: str
    latest: str
    directorate_id: str | None
    clarification_count: int

    def search_text(self) -> str:
        parts = [self.original.strip()]
        latest = self.latest.strip()
        if latest and latest != parts[0]:
            parts.append(latest)
        title = directorate_title(self.directorate_id)
        if title:
            parts.append(title)
        return "\n".join(part for part in parts if part)

    def document_ids(self) -> frozenset[str] | None:
        for item in DIRECTORATES:
            if item.id == self.directorate_id:
                return item.document_ids
        return None


def directorate_title(directorate_id: str | None) -> str:
    for item in DIRECTORATES:
        if item.id == directorate_id:
            return item.title
    return ""


def named_directorates(text: str) -> set[str]:
    return {item.id for item in DIRECTORATES if item.pattern.search(text)}


def read_dialogue(messages: list[dict[str, str]]) -> Dialogue:
    users = [item.get("content", "") for item in messages if item.get("role") == "user"]
    original = users[0] if users else ""
    latest = users[-1] if users else ""
    latest_named = named_directorates(latest)
    directorate_id: str | None
    if len(latest_named) == 1:
        directorate_id = next(iter(latest_named))
    else:
        named = named_directorates("\n".join(users))
        directorate_id = next(iter(named)) if len(named) == 1 else None
    clarifications = sum(
        1 for item in messages if item.get("role") == "assistant" and "?" in item.get("content", "")
    )
    return Dialogue(original, latest, directorate_id, clarifications)


def render_turn(dialogue: Dialogue, clauses: list[Clause]) -> str:
    context = prompt_context()
    document_ids: list[str] = []
    for clause in clauses:
        if clause.document_id not in document_ids:
            document_ids.append(clause.document_id)
    lines = [
        "Глоссарий. Сокращение и полные формы ниже означают одно и то же.",
        context.glossary.strip(),
        "",
        "Термин глоссария цитируй ссылкой вида [РП](/kb/glossary#s-РП), подставив сокращение.",
        "",
        "Регламенты. Ссылка на документ целиком:",
    ]
    lines.extend(f"- [{document.title}]({document.path})" for document in context.regulations)
    lines.append("")
    lines.append("document_id: " + (", ".join(document_ids) if document_ids else "нет"))
    chosen = directorate_title(dialogue.directorate_id)
    lines.append(f"Выбранная дирекция: {chosen or 'не указана'}.")
    if not clauses:
        lines.append(_empty_instruction(dialogue))
        return "\n".join(lines)
    lines.append(_mode_instruction(dialogue, clauses, document_ids))
    if dialogue.clarification_count >= MAX_CLARIFICATIONS:
        lines.append(
            "Уточнения уже заданы три раза. Не задавай новый вопрос. "
            "Если пунктов достаточно, ответь. Если нет, скажи, что следующий шаг — управление качества."
        )
    lines.append(
        "Кандидаты по совпадению слов, по убыванию совпадения. "
        "Прочитай все. В ответ оставь только пункты, которые подходят к вопросу."
    )
    for clause in clauses:
        link = f"[{clause.clause_id}]({clause.path})"
        document_link = f"[{clause.document}](/kb/{clause.document_id})"
        lines.append(f"\n{document_link}\n## {clause.heading}\n{link}\n{clause.body.strip()}")
    return "\n".join(lines)


def _empty_instruction(dialogue: Dialogue) -> str:
    text = (
        "Фрагменты по этому вопросу не найдены. "
        "Скажи, что в регламентах нет ответа, и ничего не выдумывай. "
        "Следующий шаг — обращение в управление качества."
    )
    if dialogue.clarification_count >= MAX_CLARIFICATIONS:
        text += " Уточнения уже заданы три раза. Не задавай новый вопрос."
    return text


def _mode_instruction(dialogue: Dialogue, clauses: list[Clause], document_ids: list[str]) -> str:
    links = document_links(clauses)
    joined = "; ".join(links)
    if len(document_ids) <= 1:
        title_link = links[0] if links else ""
        return (
            f"Кандидаты из одного регламента {title_link}. "
            "Отвечай только по тем пунктам, которые подходят к вопросу. Неподходящие пропусти. "
            "Текст ссылки на пункт — номер пункта, например [2.6](/kb/project-activity-ib#s-2). "
            "Если называешь регламент, вставь ссылку на документ целиком без звёздочек. "
            "Если подходящие пункты противоречат друг другу в одной и той же ситуации, покажи оба и назови противоречие. "
            "Не выбирай победителя."
        )
    if dialogue.clarification_count >= MAX_CLARIFICATIONS:
        return (
            f"Кандидаты из разных регламентов: {joined}. "
            "Не объединяй их шаги. Не задавай вопрос. "
            "В ответ возьми только пункты, которые описывают ситуацию из вопроса. "
            "Если подходят разные регламенты, раздели ответ на блоки. "
            "Первая строка блока — ссылка на документ из списка выше, без звёздочек. "
            "Если ни один пункт не подходит, скажи, что следующий шаг — управление качества."
        )
    return (
        f"Кандидаты из разных регламентов: {joined}. "
        "Не объединяй их шаги в одну процедуру. "
        "В ответ возьми только пункты, которые описывают ситуацию из вопроса. "
        "Если подходит один регламент, ответь по нему. "
        "Если подходят разные и они расходятся, ответь отдельным блоком на каждый. "
        "Первая строка блока — ссылка на документ из списка выше, без звёздочек."
    )


def document_links(clauses: list[Clause]) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for clause in clauses:
        if clause.document_id in seen:
            continue
        seen.add(clause.document_id)
        links.append(f"[{clause.document}](/kb/{clause.document_id})")
    return links


def link_document_titles(reply: str) -> str:
    """Turn a bare or bold regulation title into a document link."""
    catalog = sorted(
        prompt_context().catalog,
        key=lambda document: len(document.title),
        reverse=True,
    )
    linked: list[str] = []
    for line in reply.splitlines():
        rewritten = line
        stripped = line.strip()
        for document in catalog:
            link = f"[{document.title}]({document.path})"
            if stripped in {link, f"**{link}**"}:
                rewritten = link
                break
            heading = stripped.lstrip("#").strip()
            bold = f"**{document.title}**"
            if stripped in {document.title, bold} or heading == document.title:
                rewritten = link
                break
            if bold in rewritten and link not in rewritten:
                rewritten = rewritten.replace(bold, link)
        linked.append(rewritten)
    return "\n".join(linked)


def allowed_sections(clauses: list[Clause]) -> set[tuple[str, str]]:
    return {(clause.document_id, clause.section_id) for clause in clauses}


def link_targets(reply: str) -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    for match in _KB_LINK.finditer(reply):
        document_id = match.group(1)
        anchor = match.group(2)
        section_id = anchor[2:] if anchor.startswith("s-") else anchor
        found.append((document_id, section_id, match.group(0)))
    return found


def bad_links(reply: str, allowed: set[tuple[str, str]]) -> list[str]:
    bad: list[str] = []
    for document_id, section_id, raw in link_targets(reply):
        if document_id == "glossary":
            continue
        if (document_id, section_id) not in allowed:
            bad.append(raw)
    return bad


def drop_bad_links(reply: str, allowed: set[tuple[str, str]]) -> str:
    kept_lines: list[str] = []
    for line in reply.splitlines():
        if not bad_links(line, allowed):
            kept_lines.append(line)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", line)
        kept = [sentence for sentence in sentences if not bad_links(sentence, allowed)]
        if kept:
            kept_lines.append(" ".join(kept))
    return "\n".join(kept_lines).strip()


def cited_document_ids(reply: str) -> list[str]:
    seen: list[str] = []
    for document_id, _section_id, _raw in link_targets(reply):
        if document_id == "glossary" or document_id in seen:
            continue
        seen.append(document_id)
    return seen


def regulations_are_separate(reply: str, clauses: list[Clause], cited_ids: list[str]) -> bool:
    if len(cited_ids) < 2:
        return True
    titles = {clause.document_id: clause.document for clause in clauses}
    return all(titles.get(document_id, "") in reply for document_id in cited_ids)

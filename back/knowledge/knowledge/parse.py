"""Split regulation and glossary markdown the same way the chat catalog used to."""

import re
from dataclasses import dataclass

GLOSSARY_NAME = "glossary.md"
GLOSSARY_ID = "glossary"
CASE_SENSITIVE_ABBREVIATIONS = frozenset({"ПО", "ТП", "КП", "ЗП", "КИ", "СБ"})

_NUMBERED_HEADING = re.compile(r"^(\d+)\.\s+")
_CLAUSE_LINE = re.compile(r"^(?:\*\*)?(\d+(?:\.\d+)+)\.(?:\*\*)?(?:\s+(.*))?$")
_ALIAS_PREFIXES = ("то же:", "должность:", "документ:", "вместе с")


@dataclass(frozen=True)
class ParsedClause:
    clause_id: str
    position: int
    body: str


@dataclass(frozen=True)
class ParsedSection:
    section_id: str
    position: int
    heading: str
    anchor: str
    body: str
    clauses: tuple[ParsedClause, ...]


@dataclass(frozen=True)
class ParsedAlias:
    abbreviation: str
    phrases: tuple[str, ...]
    case_sensitive: bool


@dataclass(frozen=True)
class ParsedDocument:
    id: str
    kind: str
    title: str
    source_name: str
    source_markdown: str
    sections: tuple[ParsedSection, ...]
    aliases: tuple[ParsedAlias, ...]


def parse_document(text: str, source_name: str) -> ParsedDocument:
    if source_name == GLOSSARY_NAME:
        return _parse_glossary(text, source_name)
    return _parse_regulation(text, source_name)


def _parse_regulation(text: str, source_name: str) -> ParsedDocument:
    document_id = source_name.removesuffix(".md")
    title = source_name
    preamble: list[str] = []
    sections: list[tuple[str, str]] = []
    heading: str | None = None
    body: list[str] = []

    def flush() -> None:
        nonlocal heading, body
        if heading is None:
            return
        sections.append((heading, "\n".join(body).strip()))
        heading = None
        body = []

    for line in text.splitlines():
        if line.startswith("## "):
            flush()
            heading = line[3:].strip()
            body = []
            continue
        if line.startswith("# ") and heading is None and not sections:
            title = line[2:].strip()
            continue
        if heading is None:
            preamble.append(line)
        else:
            body.append(line)
    flush()
    preamble_text = "\n".join(preamble).strip()
    raw: list[tuple[str, str, str]] = []
    if preamble_text:
        raw.append(("intro", "Введение", preamble_text))
    raw.extend((_section_id(heading), heading, body) for heading, body in sections)
    parsed = _sections(document_id, raw, with_clauses=True)
    _require_unique_sections(parsed, source_name)
    return ParsedDocument(
        id=document_id,
        kind="regulation",
        title=title,
        source_name=source_name,
        source_markdown=text,
        sections=parsed,
        aliases=(),
    )


def _parse_glossary(text: str, source_name: str) -> ParsedDocument:
    title = "Корпоративный глоссарий"
    intro: list[str] = []
    raw: list[tuple[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and not raw:
            title = stripped[2:].strip()
            continue
        if "=" in stripped and not stripped.startswith("#"):
            abbreviation = stripped.split("=", 1)[0].strip()
            if not abbreviation:
                continue
            raw.append((abbreviation, stripped))
            continue
        if raw:
            heading, body = raw[-1]
            raw[-1] = (heading, f"{body}\n{line}".strip())
        else:
            intro.append(line)
    intro_text = "\n".join(intro).strip()
    labeled: list[tuple[str, str, str]] = []
    if intro_text:
        labeled.append(("intro", "Введение", intro_text))
    labeled.extend((abbreviation, abbreviation, body) for abbreviation, body in raw)
    sections = _sections(GLOSSARY_ID, labeled, with_clauses=False)
    _require_unique_sections(sections, source_name)
    return ParsedDocument(
        id=GLOSSARY_ID,
        kind="glossary",
        title=title,
        source_name=source_name,
        source_markdown=text,
        sections=sections,
        aliases=tuple(_aliases(text)),
    )


def _sections(
    document_id: str,
    raw: list[tuple[str, str, str]],
    *,
    with_clauses: bool,
) -> tuple[ParsedSection, ...]:
    sections: list[ParsedSection] = []
    for position, (section_id, heading, body) in enumerate(raw):
        clauses = _clauses(section_id, body) if with_clauses else ()
        _require_unique_clauses(clauses, document_id, section_id)
        sections.append(
            ParsedSection(
                section_id=section_id,
                position=position,
                heading=heading,
                anchor=f"s-{section_id}",
                body=body,
                clauses=clauses,
            )
        )
    return tuple(sections)


def _section_id(heading: str) -> str:
    match = _NUMBERED_HEADING.match(heading)
    if match:
        return match.group(1)
    slug = re.sub(r"[^\w]+", "-", heading.casefold(), flags=re.UNICODE).strip("-")
    return slug or "section"


def _clauses(section_id: str, body: str) -> tuple[ParsedClause, ...]:
    found: list[tuple[str, str]] = []
    current_id: str | None = None
    lines: list[str] = []
    preamble: list[str] = []

    def flush() -> None:
        nonlocal current_id, lines
        if current_id is None:
            return
        found.append((current_id, "\n".join(lines).strip()))
        current_id = None
        lines = []

    for line in body.splitlines():
        match = _CLAUSE_LINE.match(line.strip())
        if match:
            flush()
            current_id = match.group(1)
            lines = [line.strip()]
            continue
        if current_id is None:
            preamble.append(line)
        else:
            lines.append(line)
    flush()
    preamble_text = "\n".join(preamble).strip()
    if preamble_text:
        found.insert(0, (section_id, preamble_text))
    if not found:
        found.append((section_id, body.strip()))
    return tuple(
        ParsedClause(clause_id=clause_id, position=position, body=text)
        for position, (clause_id, text) in enumerate(found)
    )


def _aliases(text: str) -> list[ParsedAlias]:
    groups: list[ParsedAlias] = []
    seen: set[str] = set()
    for line in text.splitlines():
        raw = line.strip()
        if "=" not in raw or raw.startswith("#"):
            continue
        left, right = raw.split("=", 1)
        abbreviation = left.strip()
        if not abbreviation:
            continue
        if abbreviation in seen:
            raise RuntimeError(f"duplicate glossary abbreviation {abbreviation!r}")
        seen.add(abbreviation)
        phrases = [abbreviation]
        for part in right.split(";"):
            cleaned = _clean_alias(part)
            if cleaned:
                phrases.append(cleaned)
        groups.append(
            ParsedAlias(
                abbreviation=abbreviation,
                phrases=tuple(phrases),
                case_sensitive=abbreviation in CASE_SENSITIVE_ABBREVIATIONS,
            )
        )
    return groups


def _clean_alias(part: str) -> str:
    text = part.strip().strip(".")
    folded = text.casefold()
    for prefix in _ALIAS_PREFIXES:
        if folded.startswith(prefix):
            text = text[len(prefix) :].strip()
            break
    return text.strip(" .")


def _require_unique_sections(sections: tuple[ParsedSection, ...], source_name: str) -> None:
    seen: set[str] = set()
    for section in sections:
        if section.section_id in seen:
            raise RuntimeError(f"duplicate section id {section.section_id!r} in {source_name}")
        seen.add(section.section_id)


def _require_unique_clauses(
    clauses: tuple[ParsedClause, ...], document_id: str, section_id: str
) -> None:
    seen: set[str] = set()
    for clause in clauses:
        if clause.clause_id in seen:
            raise RuntimeError(
                f"duplicate clause id {clause.clause_id!r} in {document_id}/{section_id}"
            )
        seen.add(clause.clause_id)

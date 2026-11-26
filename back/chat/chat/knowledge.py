"""Regulation files for the system prompt.

The glossary is small and needed on every turn, so it is always included.
The four regulations are large, so only sections matched to the current
question are added. `KNOWLEDGE_DIR` overrides the default data folder.
"""

import logging
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

logger = logging.getLogger(__name__)

GLOSSARY_NAME = "glossary.md"
GLOSSARY_ID = "glossary"
TOP_K = 8
MIN_SCORE_RATIO = 0.4
MAX_CONTEXT_CHARS = 18_000

# These short forms are also everyday Russian words in another case.
CASE_SENSITIVE_ABBREVIATIONS = frozenset({"ПО", "ТП", "КП", "ЗП", "КИ", "СБ"})

_STOPWORDS = frozenset(
    {
        "и",
        "в",
        "во",
        "на",
        "по",
        "что",
        "как",
        "для",
        "это",
        "или",
        "не",
        "от",
        "к",
        "ко",
        "с",
        "со",
        "за",
        "из",
        "при",
        "ли",
        "же",
        "бы",
        "то",
        "а",
        "но",
        "да",
        "если",
        "когда",
        "где",
        "кто",
        "чем",
        "чтобы",
        "какой",
        "какая",
        "какие",
        "какое",
        "можно",
        "нужно",
        "надо",
        "мне",
        "меня",
        "его",
        "ее",
        "её",
        "их",
        "мы",
        "вы",
        "он",
        "она",
        "они",
        "этот",
        "эта",
        "эти",
        "тот",
        "та",
        "те",
        "уже",
        "ещё",
        "еще",
        "только",
        "также",
        "тоже",
        "над",
        "под",
        "без",
        "до",
        "после",
        "через",
        "между",
        "про",
        "об",
        "обо",
        "все",
        "всё",
        "очень",
        "просто",
        "сейчас",
        "потом",
        "тогда",
        "потому",
        "поэтому",
        "который",
        "которая",
        "которые",
        "которое",
        "быть",
        "был",
        "была",
        "были",
        "будет",
        "есть",
        "нет",
        "ну",
        "вот",
        "там",
        "тут",
        "the",
        "and",
        "for",
        "with",
    }
)
_SUFFIXES = (
    "иями",
    "ями",
    "ами",
    "ого",
    "ему",
    "ому",
    "ыми",
    "ими",
    "ою",
    "ею",
    "ая",
    "яя",
    "ое",
    "ее",
    "ые",
    "ие",
    "ую",
    "юю",
    "ой",
    "ый",
    "ий",
    "ых",
    "их",
    "ов",
    "ев",
    "ах",
    "ях",
    "ом",
    "ем",
    "ам",
    "ям",
    "ей",
    "а",
    "я",
    "ы",
    "и",
    "е",
    "у",
    "ю",
    "о",
)
_TOKEN = re.compile(r"[A-Za-zА-ЯЁа-яё0-9]+(?:-[A-Za-zА-ЯЁа-яё0-9]+)*")
_ALIAS_PREFIXES = ("то же:", "должность:", "документ:", "вместе с")
_NUMBERED_HEADING = re.compile(r"^(\d+)\.\s+")


@dataclass(frozen=True)
class Section:
    document: str
    heading: str
    body: str
    source_name: str
    document_id: str
    section_id: str
    anchor: str

    @property
    def path(self) -> str:
        return f"/kb/{self.document_id}#{self.anchor}"


@dataclass(frozen=True)
class Document:
    id: str
    title: str
    source_name: str
    sections: tuple[Section, ...]


@dataclass(frozen=True)
class Corpus:
    glossary: str
    glossary_document: Document
    documents: tuple[Document, ...]
    document_titles: tuple[str, ...]
    sections: tuple[Section, ...]
    section_terms: tuple[tuple[str, ...], ...]
    alias_groups: tuple[tuple[str, ...], ...]


_corpus: Corpus | None = None
_lock = Lock()


def knowledge_dir() -> Path:
    configured = os.environ.get("KNOWLEDGE_DIR")
    if configured:
        path = Path(configured)
        if not path.is_dir():
            raise RuntimeError(f"KNOWLEDGE_DIR does not exist: {path}")
        return path
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "data" / "knowlage_files"
        if candidate.is_dir():
            return candidate
    raise RuntimeError("knowledge directory not found; set KNOWLEDGE_DIR")


def load_knowledge(directory: Path | None = None) -> Corpus:
    global _corpus
    corpus = _read_corpus(directory or knowledge_dir())
    with _lock:
        _corpus = corpus
    logger.info(
        "loaded knowledge: %s documents, %s sections",
        len(corpus.documents),
        len(corpus.sections),
    )
    return corpus


def get_corpus() -> Corpus:
    with _lock:
        corpus = _corpus
    if corpus is None:
        return load_knowledge()
    return corpus


def latest_question(messages: list[dict[str, str]]) -> str:
    questions = [item["content"] for item in messages if item.get("role") == "user"]
    if not questions:
        return ""
    if len(questions) >= 2 and len(questions[-1]) < 160:
        return f"{questions[-2]}\n{questions[-1]}"
    return questions[-1]


def render_context(question: str) -> str:
    corpus = get_corpus()
    selected = select_sections(question, corpus)
    logger.info(
        "knowledge context for %r: %s",
        question[:180],
        "; ".join(f"{item.source_name} / {item.heading}" for item in selected) or "none",
    )
    lines = [
        "Глоссарий. Сокращение и полные формы ниже означают одно и то же.",
        corpus.glossary.strip(),
        "",
        "Термин глоссария цитируй ссылкой вида [РП](/kb/glossary#s-РП), подставив сокращение.",
        "",
        "Регламенты:",
    ]
    lines.extend(f"- {title}" for title in corpus.document_titles)
    lines.append("")
    if not selected:
        lines.append(
            "Фрагменты по этому вопросу не найдены. "
            "Задай уточняющий вопрос или скажи, что в приведённых материалах нет ответа."
        )
        return "\n".join(lines)
    lines.append("Фрагменты, отобранные по текущему вопросу:")
    for section in selected:
        link = f"[{section.heading}]({section.path})"
        lines.append(
            f"\n# {section.document}\n## {section.heading}\n{link}\n{section.body.strip()}"
        )
    return "\n".join(lines)


def search_sections(question: str, corpus: Corpus | None = None) -> list[tuple[Section, float]]:
    corpus = get_corpus() if corpus is None else corpus
    query_terms = _query_terms(question, corpus.alias_groups)
    if not query_terms or not corpus.sections:
        return []
    scores = _bm25(query_terms, corpus.section_terms)
    ranked = sorted(
        zip(scores, corpus.sections, strict=True), key=lambda item: item[0], reverse=True
    )
    best = ranked[0][0]
    if best <= 0:
        return []
    selected: list[tuple[Section, float]] = []
    size = 0
    for score, section in ranked:
        if score < best * MIN_SCORE_RATIO:
            break
        if selected and size + len(section.body) > MAX_CONTEXT_CHARS:
            break
        selected.append((section, score))
        size += len(section.body)
        if len(selected) >= TOP_K:
            break
    return selected


def select_sections(question: str, corpus: Corpus | None = None) -> list[Section]:
    return [section for section, _score in search_sections(question, corpus)]


def find_document(document_id: str, corpus: Corpus | None = None) -> Document | None:
    corpus = get_corpus() if corpus is None else corpus
    if document_id == corpus.glossary_document.id:
        return corpus.glossary_document
    for document in corpus.documents:
        if document.id == document_id:
            return document
    return None


def find_section(document_id: str, section_id: str, corpus: Corpus | None = None) -> Section | None:
    document = find_document(document_id, corpus)
    if document is None:
        return None
    for section in document.sections:
        if section.section_id == section_id:
            return section
    return None


def find_glossary_term(term: str, corpus: Corpus | None = None) -> Section | None:
    text = term.strip()
    if not text:
        return None
    document = (get_corpus() if corpus is None else corpus).glossary_document
    for section in document.sections:
        if section.section_id == text:
            return section
    folded = text.casefold()
    for section in document.sections:
        if section.section_id in CASE_SENSITIVE_ABBREVIATIONS:
            continue
        if section.section_id.casefold() == folded:
            return section
    return None


def section_snippet(body: str, limit: int = 240) -> str:
    text = re.sub(r"\s+", " ", body).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def document_markdown(document: Document, corpus: Corpus | None = None) -> str:
    corpus = get_corpus() if corpus is None else corpus
    if document.id == corpus.glossary_document.id:
        return corpus.glossary.strip()
    parts = [f"# {document.title}"]
    for section in document.sections:
        if section.section_id == "intro":
            parts.append(section.body)
            continue
        block = f"## {section.heading}"
        if section.body:
            block = f"{block}\n\n{section.body}"
        parts.append(block)
    return "\n\n".join(parts)


def _read_corpus(directory: Path) -> Corpus:
    glossary_path = directory / GLOSSARY_NAME
    if not glossary_path.is_file():
        raise RuntimeError(f"glossary not found: {glossary_path}")
    glossary = glossary_path.read_text(encoding="utf-8")
    glossary_document = _parse_glossary(glossary)
    documents: list[Document] = []
    sections: list[Section] = []
    for path in sorted(directory.glob("*.md")):
        if path.name == GLOSSARY_NAME:
            continue
        document = _parse_regulation(path.read_text(encoding="utf-8"), path.name)
        documents.append(document)
        sections.extend(document.sections)
    if not sections:
        raise RuntimeError(f"no regulation markdown in {directory}")
    return Corpus(
        glossary=glossary,
        glossary_document=glossary_document,
        documents=tuple(documents),
        document_titles=tuple(document.title for document in documents),
        sections=tuple(sections),
        section_terms=tuple(_section_terms(section) for section in sections),
        alias_groups=_parse_alias_groups(glossary),
    )


def _parse_regulation(text: str, source_name: str) -> Document:
    document_id = Path(source_name).stem
    title = source_name
    preamble: list[str] = []
    sections: list[Section] = []
    heading: str | None = None
    body: list[str] = []

    def flush() -> None:
        nonlocal heading, body
        if heading is None:
            return
        sections.append(
            _new_section(
                document=title,
                heading=heading,
                body="\n".join(body).strip(),
                source_name=source_name,
                document_id=document_id,
                section_id=_section_id_for_heading(heading),
            )
        )
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
    if preamble_text:
        sections.insert(
            0,
            _new_section(
                document=title,
                heading="Введение",
                body=preamble_text,
                source_name=source_name,
                document_id=document_id,
                section_id="intro",
            ),
        )
    _require_unique(sections, source_name)
    return Document(
        id=document_id,
        title=title,
        source_name=source_name,
        sections=tuple(sections),
    )


def _parse_glossary(text: str) -> Document:
    title = "Корпоративный глоссарий"
    intro: list[str] = []
    sections: list[Section] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and not sections:
            title = stripped[2:].strip()
            continue
        if "=" in stripped and not stripped.startswith("#"):
            abbreviation = stripped.split("=", 1)[0].strip()
            if not abbreviation:
                continue
            sections.append(
                _new_section(
                    document=title,
                    heading=abbreviation,
                    body=stripped,
                    source_name=GLOSSARY_NAME,
                    document_id=GLOSSARY_ID,
                    section_id=abbreviation,
                )
            )
            continue
        if sections:
            previous = sections[-1]
            sections[-1] = _new_section(
                document=previous.document,
                heading=previous.heading,
                body=f"{previous.body}\n{line}".strip(),
                source_name=previous.source_name,
                document_id=previous.document_id,
                section_id=previous.section_id,
            )
        else:
            intro.append(line)
    intro_text = "\n".join(intro).strip()
    if intro_text:
        sections.insert(
            0,
            _new_section(
                document=title,
                heading="Введение",
                body=intro_text,
                source_name=GLOSSARY_NAME,
                document_id=GLOSSARY_ID,
                section_id="intro",
            ),
        )
    _require_unique(sections, GLOSSARY_NAME)
    return Document(
        id=GLOSSARY_ID,
        title=title,
        source_name=GLOSSARY_NAME,
        sections=tuple(sections),
    )


def _new_section(
    *,
    document: str,
    heading: str,
    body: str,
    source_name: str,
    document_id: str,
    section_id: str,
) -> Section:
    return Section(
        document=document,
        heading=heading,
        body=body,
        source_name=source_name,
        document_id=document_id,
        section_id=section_id,
        anchor=f"s-{section_id}",
    )


def _section_id_for_heading(heading: str) -> str:
    match = _NUMBERED_HEADING.match(heading)
    if match:
        return match.group(1)
    return _slug(heading)


def _slug(heading: str) -> str:
    slug = re.sub(r"[^\w]+", "-", heading.casefold(), flags=re.UNICODE).strip("-")
    return slug or "section"


def _require_unique(sections: list[Section], source_name: str) -> None:
    seen: set[str] = set()
    for section in sections:
        if section.section_id in seen:
            raise RuntimeError(f"duplicate section id {section.section_id!r} in {source_name}")
        seen.add(section.section_id)


def _parse_alias_groups(glossary: str) -> tuple[tuple[str, ...], ...]:
    groups: list[tuple[str, ...]] = []
    for line in glossary.splitlines():
        raw = line.strip()
        if "=" not in raw or raw.startswith("#"):
            continue
        left, right = raw.split("=", 1)
        phrases = [left.strip()]
        for part in right.split(";"):
            cleaned = _clean_alias(part)
            if cleaned:
                phrases.append(cleaned)
        groups.append(tuple(phrases))
    return tuple(groups)


def _clean_alias(part: str) -> str:
    text = part.strip().strip(".")
    folded = text.casefold()
    for prefix in _ALIAS_PREFIXES:
        if folded.startswith(prefix):
            text = text[len(prefix) :].strip()
            break
    return text.strip(" .")


def _query_terms(question: str, groups: tuple[tuple[str, ...], ...]) -> list[str]:
    terms = {term for term in (_index_term(token) for token in _TOKEN.findall(question)) if term}
    for phrases in groups:
        if any(_phrase_in(phrase, question) for phrase in phrases):
            for phrase in phrases:
                terms.update(
                    term
                    for term in (_index_term(token) for token in _TOKEN.findall(phrase))
                    if term
                )
    return list(terms)


def _phrase_in(phrase: str, question: str) -> bool:
    parts = phrase.split()
    if not parts:
        return False
    body = r"\s+".join(re.escape(part) for part in parts)
    flags = 0 if phrase in CASE_SENSITIVE_ABBREVIATIONS else re.IGNORECASE
    return re.search(rf"(?<!\w){body}(?!\w)", question, flags) is not None


def _section_terms(section: Section) -> tuple[str, ...]:
    heading = [_index_term(token) for token in _TOKEN.findall(section.heading)]
    document = [_index_term(token) for token in _TOKEN.findall(section.document)]
    body = [_index_term(token) for token in _TOKEN.findall(section.body)]
    return tuple(term for term in (*heading, *heading, *heading, *document, *body) if term)


def _index_term(token: str) -> str | None:
    if token in CASE_SENSITIVE_ABBREVIATIONS:
        return token
    folded = token.casefold()
    if folded in _STOPWORDS:
        return None
    if folded.isdigit():
        return folded if len(folded) >= 2 else None
    if _is_abbreviation(token):
        return folded
    if any("а" <= char <= "я" or char == "ё" for char in folded):
        stemmed = _stem(folded)
        if len(stemmed) < 4 or stemmed in _STOPWORDS:
            return None
        return stemmed
    if len(folded) < 3:
        return None
    return folded


def _is_abbreviation(token: str) -> bool:
    letters = [char for char in token if char.isalpha()]
    if not letters or len(token) > 12:
        return False
    if all(char.isupper() for char in letters):
        return True
    return any(char.isupper() for char in letters[1:])


def _stem(folded: str) -> str:
    for suffix in _SUFFIXES:
        if folded.endswith(suffix) and len(folded) - len(suffix) >= 4:
            folded = folded[: -len(suffix)]
            break
    if len(folded) > 6:
        return folded[:6]
    return folded


def _bm25(query_terms: list[str], docs: tuple[tuple[str, ...], ...]) -> list[float]:
    k1 = 1.5
    b = 0.75
    doc_count = len(docs)
    df: dict[str, int] = {}
    for doc in docs:
        for term in set(doc):
            df[term] = df.get(term, 0) + 1
    avgdl = sum(len(doc) for doc in docs) / doc_count
    scores: list[float] = []
    unique_query = set(query_terms)
    for doc in docs:
        tf: dict[str, int] = {}
        for term in doc:
            tf[term] = tf.get(term, 0) + 1
        doc_len = len(doc) or 1
        score = 0.0
        for term in unique_query:
            freq = tf.get(term, 0)
            if freq == 0:
                continue
            idf = math.log(1 + (doc_count - df[term] + 0.5) / (df[term] + 0.5))
            denom = freq + k1 * (1 - b + b * doc_len / avgdl)
            score += idf * (freq * (k1 + 1)) / denom
        scores.append(score)
    return scores

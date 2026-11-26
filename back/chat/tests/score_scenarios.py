"""Score regulation scenarios against one chat turn.

Run from ``back/chat``:

    uv run python -m tests.score_scenarios --limit 8
"""

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

from chat.llm import answer_turn
from chat.reasoning import bad_links

_SCENARIO = re.compile(r"^## \d+\. (.+)$", re.MULTILINE)
_SOURCE = re.compile(r"\*\*Источник:\*\*\s*(.+)")
_RANGE = re.compile(r"(\d+(?:\.\d+)+)\s*[–-]\s*(\d+(?:\.\d+)+)")
_CLAUSE = re.compile(r"\d+(?:\.\d+)+")


@dataclass(frozen=True)
class Scenario:
    source: str
    question: str
    clauses: frozenset[str]


def scenarios_dir() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "data" / "tests_data"
        if candidate.is_dir():
            return candidate
    raise RuntimeError("tests_data not found")


def load_scenarios(directory: Path | None = None) -> list[Scenario]:
    root = directory or scenarios_dir()
    items: list[Scenario] = []
    for path in sorted(root.glob("*.md")):
        items.extend(_parse_markdown(path.read_text(encoding="utf-8"), path.name))
    jsonl = root / "regulations-test-scenarios.jsonl"
    if jsonl.is_file():
        for line in jsonl.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            items.append(
                Scenario(
                    source=jsonl.name,
                    question=row["question"].strip(),
                    clauses=expand_clause_ref(str(row.get("clauses", ""))),
                )
            )
    return items


def _parse_markdown(text: str, source: str) -> list[Scenario]:
    items: list[Scenario] = []
    parts = re.split(r"(?=^## \d+\. )", text, flags=re.MULTILINE)
    for part in parts:
        match = _SCENARIO.match(part)
        if match is None:
            continue
        source_line = _SOURCE.search(part)
        items.append(
            Scenario(
                source=source,
                question=match.group(1).strip(),
                clauses=expand_clause_ref(source_line.group(1) if source_line else ""),
            )
        )
    return items


def expand_clause_ref(text: str) -> frozenset[str]:
    found: set[str] = set()
    ranges = list(_RANGE.finditer(text))
    for match in ranges:
        found.update(_expand_range(match.group(1), match.group(2)))
    covered = [match.span() for match in ranges]
    for match in _CLAUSE.finditer(text):
        if any(start <= match.start() < end for start, end in covered):
            continue
        found.add(match.group(0))
    return frozenset(found)


def _expand_range(start: str, end: str) -> set[str]:
    start_parts = start.split(".")
    end_parts = end.split(".")
    if len(start_parts) != len(end_parts) or start_parts[:-1] != end_parts[:-1]:
        return {start, end}
    left = int(start_parts[-1])
    right = int(end_parts[-1])
    if right < left or right - left > 12:
        return {start, end}
    prefix = ".".join(start_parts[:-1])
    return {f"{prefix}.{number}" for number in range(left, right + 1)}


def classify(reply: str) -> str:
    has_link = "/kb/" in reply and "#s-" in reply
    if "?" in reply and not has_link:
        return "asked"
    if not has_link:
        return "refused"
    return "answered"


def clause_hit(reply: str, expected: frozenset[str]) -> bool:
    if not expected:
        return True
    return any(re.search(rf"(?<![\d.]){re.escape(clause)}(?![\d.])", reply) for clause in expected)


def score(scenario: Scenario) -> dict[str, object]:
    result = answer_turn([{"role": "user", "content": scenario.question}])
    links_ok = not bad_links(result.reply, set(result.allowed))
    return {
        "source": scenario.source,
        "question": scenario.question,
        "kind": classify(result.reply),
        "links_ok": links_ok,
        "clause_hit": clause_hit(result.reply, scenario.clauses),
        "expected_clauses": sorted(scenario.clauses),
        "reply": result.reply,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    scenarios = load_scenarios()
    if args.limit > 0:
        scenarios = scenarios[: args.limit]
    rows: list[dict[str, object]] = []
    total = len(scenarios)
    for index, scenario in enumerate(scenarios, start=1):
        print(f"{index}/{total} {scenario.source}: {scenario.question}", flush=True)
        row = score(scenario)
        rows.append(row)
        mark = "ok" if row["links_ok"] and row["clause_hit"] else "miss"
        print(f"- [{mark}] {row['kind']} {scenario.source}: {scenario.question}", flush=True)
    answered = sum(row["kind"] == "answered" for row in rows)
    asked = sum(row["kind"] == "asked" for row in rows)
    refused = sum(row["kind"] == "refused" for row in rows)
    links = sum(bool(row["links_ok"]) for row in rows)
    clauses = sum(bool(row["clause_hit"]) for row in rows)
    print(
        f"scenarios {len(rows)}: answered {answered}, asked {asked}, refused {refused}; "
        f"links in shortlist {links}; expected clause present {clauses}",
        flush=True,
    )


if __name__ == "__main__":
    main()

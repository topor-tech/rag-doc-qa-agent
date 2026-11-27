"""Ask each regulation scenario to the chat API and judge it against the etalon.

The questions and expected answers come from ``data/tests_data``.
The markdown files repeat the same items as ``regulations-test-scenarios.jsonl``,
so the run uses the jsonl file.

    uv run python -m chat.etalon_integration
    uv run python -m chat.etalon_integration --limit 2
"""

import argparse
import io
import json
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path

from openai import OpenAIError

from chat.llm import MODEL, get_client

API_TIMEOUT_SECONDS = 180
JUDGE_TIMEOUT_SECONDS = 90
STARTUP_TIMEOUT_SECONDS = 40

_CONTEXT = {
    "project-activity-dbrct.md": "Контекст: проектная деятельность ДБРЦТ.",
    "presales-activity-ib.md": "Контекст: пресейловая деятельность Дирекции ИБ.",
    "project-activity-technical-directorate.md": "Контекст: Техническая дирекция.",
    "project-activity-ib.md": "Контекст: проектная деятельность Дирекции ИБ.",
}

_JUDGE_INSTRUCTIONS = (
    "Ты проверяешь ответ внутреннего помощника по регламенту.\n"
    "Сравни ответ с эталоном по смыслу. Перефраз допустим. Ссылки на пункты не обязательны.\n"
    "Вердикт pass, если в ответе есть те же решения, роли, сроки, исключения и запреты, "
    "что в эталоне, и нет противоречия эталону.\n"
    "Вердикт fail, если пропущен существенный факт эталона, есть противоречие, "
    "ответ уклончивый, это отказ или уточняющий вопрос вместо ответа по эталону.\n"
    "Лишние верные подробности не считай ошибкой.\n"
    "problems — короткие фразы на русском. Каждая фраза называет, что требует эталон "
    "и чем ответ от него отличается. При pass список пустой.\n"
    'Ответь только JSON: {"pass": true, "problems": []}'
)


@dataclass(frozen=True)
class Scenario:
    id: str
    document: str
    question: str
    expected_answer: str

    def asked_question(self) -> str:
        context = _CONTEXT.get(self.document)
        if context is None:
            raise KeyError(f"no directorate context for {self.document}")
        return f"{context}\n\n{self.question}"


@dataclass(frozen=True)
class Row:
    scenario_id: str
    passed: bool
    problems: tuple[str, ...]


def scenarios_file() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "data" / "tests_data" / "regulations-test-scenarios.jsonl"
        if candidate.is_file():
            return candidate
    raise RuntimeError("regulations-test-scenarios.jsonl not found")


def load_scenarios(path: Path | None = None) -> list[Scenario]:
    source = path or scenarios_file()
    items: list[Scenario] = []
    for line in source.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = _object(json.loads(line))
        items.append(
            Scenario(
                id=_text(row, "id"),
                document=_text(row, "document"),
                question=_text(row, "question"),
                expected_answer=_text(row, "expected_answer"),
            )
        )
    return items


def run_suite(base_url: str, scenarios: list[Scenario], workers: int) -> list[Row]:
    get_client()
    if workers < 1:
        raise ValueError("workers must be at least 1")
    rows: list[Row | None] = [None] * len(scenarios)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(check_scenario, base_url, scenario): index
            for index, scenario in enumerate(scenarios)
        }
        for done, future in enumerate(as_completed(futures), start=1):
            index = futures[future]
            row = future.result()
            rows[index] = row
            mark = "pass" if row.passed else "fail"
            detail = "" if row.passed else " — " + "; ".join(row.problems)
            print(
                f"{done}/{len(scenarios)} {mark} {scenarios[index].id}{detail}",
                file=sys.stderr,
                flush=True,
            )
    return [row for row in rows if row is not None]


def check_scenario(base_url: str, scenario: Scenario) -> Row:
    try:
        answer = ask(base_url, scenario.asked_question())
    except (OSError, TimeoutError, RuntimeError, urllib.error.URLError) as exc:
        return Row(scenario.id, False, (f"запрос к API не выполнен: {exc}",))
    try:
        return judge(scenario, answer)
    except (OpenAIError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        return Row(scenario.id, False, (f"проверка эталона не выполнена: {exc}",))


def ask(base_url: str, question: str) -> str:
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
    created = post_json(opener, f"{base_url}/sessions", None)
    session_id = _text(created, "id")
    payload = post_json(
        opener,
        f"{base_url}/sessions/{session_id}/messages",
        {"content": question},
    )
    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise RuntimeError("session response has no messages")
    reply = ""
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role == "assistant" and isinstance(content, str):
            reply = content
    if not reply.strip():
        raise RuntimeError("API returned an empty answer")
    return reply.strip()


def judge(scenario: Scenario, answer: str) -> Row:
    prompt = (
        f"{_JUDGE_INSTRUCTIONS}\n\n"
        f"Вопрос:\n{scenario.asked_question()}\n\n"
        f"Эталон:\n{scenario.expected_answer}\n\n"
        f"Ответ:\n{answer[:6000]}"
    )
    raw = complete_judge(prompt)
    verdict = _object(json.loads(_json_object(raw)))
    problems = _problems(verdict.get("problems"))
    passed = verdict.get("pass") is True and not problems
    if passed:
        return Row(scenario.id, True, ())
    if not problems:
        problems = ("ответ не совпал с эталоном",)
    return Row(scenario.id, False, problems)


def complete_judge(prompt: str) -> str:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = get_client().chat.completions.create(
                model=MODEL,
                max_tokens=500,
                temperature=0,
                timeout=JUDGE_TIMEOUT_SECONDS,
                messages=[{"role": "user", "content": prompt}],
            )
            text = (response.choices[0].message.content or "").strip()
            if text:
                return text
            last_error = RuntimeError("judge returned an empty response")
        except OpenAIError as exc:
            last_error = exc
        time.sleep(1.5 * (attempt + 1))
    if last_error is None:
        raise RuntimeError("judge request failed")
    raise last_error


def render_table(rows: list[Row]) -> str:
    passed = sum(1 for row in rows if row.passed)
    lines = [
        f"passed {passed} of {len(rows)}",
        "",
        "| id | pass | problems |",
        "| --- | --- | --- |",
    ]
    for row in rows:
        problems = _cell("; ".join(row.problems))
        mark = "pass" if row.passed else "fail"
        lines.append(f"| {row.scenario_id} | {mark} | {problems} |")
    return "\n".join(lines)


@contextmanager
def serve(base_url: str) -> Iterator[str]:
    if base_url:
        yield base_url.rstrip("/")
        return
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    log_path = Path(tempfile.gettempdir()) / f"etalon-api-{port}.log"
    try:
        with log_path.open("w", encoding="utf-8") as log_file:
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "chat.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                cwd=Path(__file__).resolve().parents[1],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
            )
            try:
                _wait_until_ready(url, proc, log_path, log_file)
                yield url
            finally:
                _stop(proc)
    finally:
        with suppress(OSError):
            log_path.unlink(missing_ok=True)


def post_json(
    opener: urllib.request.OpenerDirector,
    url: str,
    payload: dict[str, object] | None,
) -> dict[str, object]:
    body = b"{}" if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    last_error: Exception | None = None
    for attempt in range(3):
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        try:
            with opener.open(request, timeout=API_TIMEOUT_SECONDS) as response:
                return _object(json.loads(response.read().decode()))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            error: Exception = RuntimeError(f"HTTP {exc.code}: {detail}")
            if exc.code < 500 and exc.code != 429:
                raise error from exc
            last_error = error
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
        time.sleep(1.5 * (attempt + 1))
    if last_error is None:
        raise RuntimeError(f"request failed: {url}")
    raise last_error


def _wait_until_ready(
    base_url: str,
    proc: subprocess.Popen[str],
    log_path: Path,
    log_file: io.TextIOBase,
) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            break
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=2) as response:
                if response.status == 200:
                    return
        except urllib.error.URLError, TimeoutError, OSError:
            time.sleep(0.4)
    log_file.flush()
    log_text = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
    raise RuntimeError(f"API did not become ready\n{log_text}")


def _stop(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _json_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError(f"judge did not return JSON: {text[:300]}")
    return text[start : end + 1]


def _problems(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    items: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            items.append(item.strip())
    return tuple(items)


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError("expected a JSON object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError("expected string keys")
        result[key] = item
    return result


def _text(row: dict[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is missing")
    return value.strip()


def _cell(value: str) -> str:
    return " ".join(value.replace("|", "/").split())


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


def main() -> None:
    _configure_stdio()
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--base-url", default="")
    args = parser.parse_args()
    scenarios = load_scenarios()
    if args.limit > 0:
        scenarios = scenarios[: args.limit]
    with serve(args.base_url) as base_url:
        rows = run_suite(base_url, scenarios, args.workers)
    print(render_table(rows))
    if any(not row.passed for row in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

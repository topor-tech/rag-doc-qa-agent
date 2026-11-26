import os
from pathlib import Path

from openai import OpenAI


def load_env(path: Path) -> None:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


load_env(Path(__file__).resolve().parents[1] / "secrets" / "env")
api_key = os.environ["API_KEY"]
url = "https://ai.reg.cloud/v1"
client = OpenAI(api_key=api_key, base_url=url)
response = client.chat.completions.create(
    model="deepseek-v4.1-flash",
    max_tokens=2500,
    temperature=0.5,
    presence_penalty=0,
    top_p=0.95,
    messages=[{"role": "user", "content": "Как написать хороший код?"}],
)
print(response.choices[0].message.content)

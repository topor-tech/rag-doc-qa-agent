"""The catalog MCP server is the knowledge service at http://127.0.0.1:8001/mcp."""


def main() -> None:
    raise SystemExit(
        "Knowledge MCP is served at http://127.0.0.1:8001/mcp. Start it with: "
        "uv run python -m knowledge  (from back/knowledge)"
    )


if __name__ == "__main__":
    main()

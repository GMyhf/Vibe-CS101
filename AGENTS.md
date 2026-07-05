# Repository Guidelines

## Project Structure & Module Organization
This is a Python 3.11+ package with no runtime third-party dependencies. The active source lives in `vibe_cs101/`: CLI entry points in `cli.py` and `__main__.py`, retrieval/indexing in `fetch.py`, `indexer.py`, and `store.py`, agent and LLM integration in `agent.py`, `tools.py`, and `llm.py`, and the standard-library Web UI backend in `server.py`. Static browser assets are in `vibe_cs101/web/`. Tests mirror the package in `tests/test_*.py`. Generated data, local indexes, virtual environments, and secrets are ignored via `.gitignore`.

## Build, Test, and Development Commands
- `python3 -m unittest discover -s tests -v`: run the full test suite used by CI.
- `python3 -m vibe_cs101 quickstart`: download the prebuilt SQLite index for local use.
- `python3 -m vibe_cs101 update && python3 -m vibe_cs101 index`: fetch upstream materials and rebuild `data/index.db`.
- `python3 -m vibe_cs101 search "动态规划" --limit 3`: smoke-test local search behavior.
- `python3 -m vibe_cs101 serve`: start the local Web UI at `http://127.0.0.1:8101`.
- `pip install -e .`: install the editable `vibe-cs101` console script.

## Coding Style & Naming Conventions
Follow the existing standard-library Python style: 4-space indentation, type hints where they clarify interfaces, small functions, and explicit error handling. Use `snake_case` for functions, variables, modules, and test names; use `PascalCase` for classes. Keep user-facing CLI text consistent with the existing bilingual Chinese/English tone. There is no configured formatter or linter, so match nearby code and keep imports grouped as standard library, then local imports.

## Testing Guidelines
Tests use `unittest` and should live in `tests/test_<module>.py`. Name test classes after the behavior under test, and name methods `test_<expected_behavior>`. Prefer temporary directories, mocks, and environment patching over writing into the real `data/` directory. Add or update focused tests when changing CLI behavior, persistence, indexing, search, authentication, rate limiting, or Web API responses.

## Commit & Pull Request Guidelines
Git history mostly follows concise Conventional Commit prefixes such as `feat:`, `fix:`, and `chore:`. Use an imperative summary, for example `fix: reject unsafe usernames`. Pull requests should include a short problem/solution description, test results, linked issues when applicable, and screenshots or notes for Web UI changes.

## Security & Configuration Tips
Do not commit `.env`, API keys, `data/`, downloaded indexes, or user/session databases. Remote `serve --host 0.0.0.0` deployments must configure authentication keys and should use TLS or a reverse proxy, as described in `README.md`.

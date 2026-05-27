---
name: test-and-lint
description: Run the test suite (pytest) and linter (ruff) for the Web3 Crew AI repo. Use this before opening a PR, after editing tools/agents/tasks, or when CI fails and you need to reproduce locally.
---

# Test & Lint

Web3 Crew AI uses **pytest** for unit tests and **ruff** for linting + formatting.
Both must pass before a PR is mergeable.

## Run the full test suite

```bash
uv run pytest
```

As of the defensive-execution phase (Phase 6), the suite covers:

- LLM provider factory (`tests/test_llm.py`)
- Settings loader incl. all gas / RBF / budget knobs (`tests/test_settings.py`)
- All four agent definitions (`tests/test_agents.py`)
- All six tools — Token data, DexScreener, Contract analyzer, Rug-pull
  detector, Safe transaction (the bulk of the suite), Telegram bot
  (`tests/test_tools.py`, `tests/test_telegram_bot.py`)
- Crew orchestration glue (`tests/test_crew.py`)

Target: **73+ tests passing**, no skips, no warnings about
`PytestUnraisableExceptionWarning`.

## Run a single file / single test

```bash
uv run pytest tests/test_tools.py
uv run pytest tests/test_tools.py::test_status_0_returns_reverted
uv run pytest -k "rbf or budget" -v
```

`-v` shows individual test names. `-x` stops on first failure. `--lf` re-runs
only the last failed tests.

## Lint

```bash
uv run ruff check src/ tests/
```

For auto-fixable issues (unused imports, sorting, formatting):

```bash
uv run ruff check --fix src/ tests/
uv run ruff format src/ tests/
```

Ruff config lives in `pyproject.toml` under `[tool.ruff]`. Notable rules:

- `line-length = 100`
- Selected rule sets: `E`, `F`, `I` (isort), `UP` (pyupgrade), `B` (bugbear)
- Tests are allowed to use longer parametrize tables and magic numbers

## Coverage (optional)

`pytest-cov` is not in the default deps but works fine if you add it locally:

```bash
uv run pytest --cov=src/web3_crew --cov-report=term-missing
```

`safe_transaction.py`, `contract_analyzer.py`, and `telegram_bot.py` should
all be > 90% covered. Lower coverage on `crew.py` is expected because
CrewAI execution is mocked.

## CI parity

The repo currently has no GitHub Actions CI workflow committed (as of Phase 6).
PR checks are manual: run `uv run pytest` and `uv run ruff check src/ tests/`
locally and confirm both are clean before opening a PR.

## Common failure patterns

- **`web3.exceptions.MissingABI`** in a tool test → the test is calling a
  contract method without mocking the ABI. Mock at the `Contract` boundary, not
  inside `safe_transaction`.
- **Flaky test on `test_telegram_bot.py`** → telegram-python-bot uses asyncio;
  rerun once. If still red, check the event loop fixture in `conftest.py`.
- **`ruff` complains about new files** → run `uv run ruff format <path>` and
  re-check.

## What this skill is NOT

- Coverage threshold enforcement (no `--cov-fail-under` gate yet)
- E2E tests against real RPC / real Telegram (those are run manually)
- Performance / load tests

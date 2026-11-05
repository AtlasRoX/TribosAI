# Contributing to Tribos

> **Tribos**: a research partner for engineering, physics and mathematics
> **Made by ChronoStrider Engineering**

Thank you for your interest in contributing to Tribos. Bug reports, feature ideas, corrections and documentation
improvements are all welcome. Please read this page before opening an issue or a pull request.

## Reporting bugs and requesting features

Use the [GitHub issue tracker](https://github.com/AtlasRoX/TribosAI/issues). Check open and recently closed issues
first, and follow the bug or feature template. For a wrong answer, include the question, the answer and what you
expected; the conversation ID shown at the top of the chat helps us find the run and the checks it made.

## Pull requests

1. Work against the latest `main`, and open an issue first for any larger change.
2. Read [AGENTS.md](https://github.com/AtlasRoX/TribosAI/blob/main/AGENTS.md) for the architecture map and the conventions (tools, settings, verification, the
   sandbox). Every new `TRIBOS_*` variable is a `Setting(...)` in `tribos/config/settings.py`, and the configuration
   reference is regenerated with `scripts/gen_env_reference.py`.
3. Keep the checks green:

   ```sh
   uv run pytest -q                                              # offline: no network, no model calls
   uv run ruff check tribos app tests scripts --select F,E9
   uv run bandit -c pyproject.toml -r tribos app --severity-level high
   uv run python scripts/gen_env_reference.py --check
   cd web && npm run typecheck && npx eslint src && npm test && npx next build
   ```

4. Tests must not need the network: use the fakes in `tests/fakes.py` and `tests/agentic_fakes.py`.
5. Never commit `.env` or any key.

Good first contributions are issues labelled *help wanted*, new deterministic tools for a domain engine (each with a
precise description, a JSON schema and a test against known answers), and documentation fixes.

## Code of conduct

This project follows the [Apache Code of Conduct](https://www.apache.org/foundation/policies/conduct).

## Security issues

Please report a potential vulnerability privately through GitHub's
[security advisories](https://github.com/AtlasRoX/TribosAI/security/advisories/new) for this repository, not in a
public issue.

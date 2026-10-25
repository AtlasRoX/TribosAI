# Tribos Developer Guide

> **Tribos** — Engineering & Scientific R&D Assistant  
> **Made by ChronoStrider Engineering**

This guide covers the complete development setup, tooling, and workflow for the **Tribos** project, made by **ChronoStrider Engineering** (**ChronoStrider Engineering**).

## 📋 Table of Contents

1. [Quick Start](#quick-start)
2. [Development Environment Setup](#development-environment-setup)
3. [Project Structure](#project-structure)
4. [Development Tools](#development-tools)
5. [Code Quality & Security](#code-quality-security)
6. [Dependency Management](#dependency-management)
7. [Testing](#testing)
8. [CI/CD Pipeline](#cicd-pipeline)
9. [Docker & Deployment](#docker-deployment)
10. [Security Best Practices](#security-best-practices)
11. [Common Development Tasks](#common-development-tasks)
12. [Troubleshooting](#troubleshooting)

---

## 🚀 Quick Start

### Prerequisites

- Python 3.12+
- Git
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (modern Python package manager)
- libmagic (for file security validation):
  - **macOS**: `brew install libmagic`
  - **Linux**: `sudo apt-get install libmagic1`
  - **Windows**: Bundled with python-magic-bin

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/AtlasRoX/trib
cd Tribos

# 2. Install dependencies (creates virtual environment automatically)
uv sync --extra dev --frozen

# 3. Set up pre-commit hooks (optional but recommended)
uv run pre-commit install

# 4. Set up API keys
export OPENAI_API_KEY=sk-...
export NVIDIA_API_KEY=nvapi-...
export ZOTERO_API_KEY=...
export ZOTERO_USER_ID=...

# 5. Test installation
uv run python -c "import tribos; print('✅ Installation successful!')"
```

---

## 🛠 Development Environment Setup

### Modern Python Stack

This project uses a modern Python development stack:

- **📦 uv**: Ultra-fast Python package manager and dependency resolver
- **🏗️ hatchling**: Modern build backend (PEP 621 compliant)
- **📝 pyproject.toml**: Single source of truth for project configuration
- **🔒 uv.lock**: Reproducible dependency resolution

### Why uv over pip/conda?

- **10-100x faster** than pip for dependency resolution
- **Automatic virtual environment management**
- **Built-in lock file support** for reproducible builds
- **Better dependency conflict resolution**
- **Native pyproject.toml support**

---

## 📂 Project Structure

```
Tribos/
├── tribos/                   # Main package
│   ├── agents/               # Orchestrator, query planning, prompts, citations
│   ├── agentic/              # Agentic frameworks, Auto router, jobs, code sandbox
│   ├── archivon/             # Literature search and citation grounding
│   ├── axiom/                # Computer algebra and the verified mathematics agent
│   ├── dynamis/              # Numerical simulation and optimization
│   ├── physis/               # Constants, units, materials and reference data
│   ├── datasets/             # Uploaded datasets (tables, HDF5, MAT)
│   ├── vision/               # Image input (OCR and vision models)
│   ├── verify/               # Claim verification
│   ├── export/, provenance/  # Report export, run manifests and re-runs
│   ├── config/               # Settings registry (TRIBOS_*)
│   └── evals/                # Evaluation harness
├── app/backend/              # FastAPI API (main.py, routers/)
├── web/                      # Next.js web app
├── docker/                   # backend/web Dockerfiles and compose.yml
├── tests/                    # Test suite
├── docs/                     # Documentation
├── pyproject.toml            # Project configuration (dependencies, tools)
├── uv.lock                   # Lock file for reproducible builds
└── .pre-commit-config.yaml   # Pre-commit hooks configuration
```

---

## 🔧 Development Tools

### Code Quality Tools

All tools are configured in `pyproject.toml` and run automatically via pre-commit:

#### ⚡ **Ruff** - Fast Linting & Import Sorting

```bash
# Lint and auto-fix issues
uv run ruff check --fix .

# Check only (no fixes)
uv run ruff check .

# Format imports and code style
uv run ruff format .
```

#### 📋 **Pylint** - Comprehensive Static Analysis

```bash
# Analyze entire codebase (configuration in pyproject.toml)
uv run pylint tribos/

# Analyze specific component
uv run pylint tribos/axiom/

# Generate JSON report for CI/CD
uv run pylint tribos/ --output-format=json --reports=no > pylint-report.json
```

#### 🔍 **MyPy** - Static Type Checking

```bash
# Type check the main package
uv run mypy tribos/

# Type check everything
uv run mypy .
```

### Security Tools

#### 🛡️ **Bandit** - Security Vulnerability Scanner

```bash
# Scan for security issues
uv run bandit -r tribos/

# Generate detailed report
uv run bandit -r tribos/ -f json -o security-report.json
```

#### 🔒 **Dependency Vulnerability Scanning**

```bash
# Scan dependencies for known vulnerabilities
uv run pip-audit

# Alternative scanner
uv run safety check

# Scan with detailed output
uv run pip-audit --desc --format=json
```

---

## 🔄 Code Quality & Security

### Pre-commit Hooks

Pre-commit runs automatically before every commit to ensure code quality:

```bash
# Install hooks (one-time setup)
uv run pre-commit install

# Run hooks manually on all files
uv run pre-commit run --all-files

# Run specific hook
uv run pre-commit run ruff
uv run pre-commit run mypy
```

### What runs on each commit

1. **Ruff** - Lints and fixes imports
2. **MyPy** - Type checking (configured but currently disabled in pre-commit)
3. **Bandit** - Security scanning
4. **pip-audit** - Dependency vulnerability check
5. **General checks** - Trailing whitespace, YAML validation, etc.

### Bypassing Pre-commit (Emergency Only)

```bash
# Skip pre-commit hooks (not recommended)
git commit --no-verify -m "emergency fix"
```

---

## 📦 Dependency Management

### Adding Dependencies

```bash
# Add runtime dependency
uv add numpy>=1.24.0

# Add development dependency
uv add --group dev pytest>=7.0.0

# Add optional dependency group
uv add --optional ml torch>=2.0.0
```

### Updating Dependencies

```bash
# Update all dependencies
uv sync --upgrade

# Update specific package
uv add package_name@latest

# Update dev dependencies
uv sync --extra dev --upgrade
```

### Lock File Management

```bash
# Generate/update lock file
uv lock

# Install from lock file (production)
uv sync --frozen

# Install with development tools
uv sync --extra dev --frozen
```

### Dependency Groups

- **Main**: Core runtime dependencies
- **Dev**: Development tools (ruff, mypy, etc.)
- **Optional**: Feature-specific dependencies

---

## 🧪 Testing

### Running Tests

```bash
# Run all tests
uv run pytest

# Run with coverage (as CI does)
uv run coverage run --source=tribos,app --omit="*/tests/*" -m pytest tests/ && uv run coverage report

# Run specific test file
uv run pytest tests/test_datasets.py

# Run integration tests only
uv run pytest -m integration
```

### Test Categories

- **Unit tests**: Fast, isolated tests
- **Integration tests**: Cross-component tests (marked with `@pytest.mark.integration`)

---

## 🔄 CI/CD Pipeline

### GitHub Actions Workflows

The project uses GitHub Actions for automated testing and deployment:

```yaml
# .github/workflows/ci.yml (example)
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v1
      - run: uv sync --extra dev
      - run: uv run pytest
      - run: uv run pip-audit
```

### Manual CI Commands

```bash
# Run the same checks as CI locally
uv run pytest                    # Tests
uv run pylint tribos/   # Static analysis (config in pyproject.toml)
uv run pip-audit                 # Security scan
uv run safety check              # Alternative security scan
uv run bandit -r tribos/ # Security scan
uv run mypy tribos/     # Type checking
```

### Automated Security Workflows

The project includes comprehensive automated security scanning:

```bash
# Weekly security audit (runs automatically)
.github/workflows/security_audit.yml   # pip-audit + safety + bandit

# SonarCloud analysis (self-contained quality gate workflow)
.github/workflows/sonarcloud.yml       # Generates reports and uploads one stable scan

# Manual security audit
uv run pip-audit --desc
uv run safety check --json
uv run bandit -c pyproject.toml -r tribos/
```

---

## 🐳 Docker & Deployment

### Building Docker Images

There are two images: the API and the web app.

```bash
# API (context: the repository root)
docker build -f docker/backend.Dockerfile -t tribos-backend .

# Web app (context: web/; NEXT_PUBLIC_API_URL is inlined at build time)
docker build -f docker/web.Dockerfile --build-arg NEXT_PUBLIC_API_URL=http://localhost:8000 -t tribos-web web

# Both, with the data volume and loopback-only ports
docker compose -f docker/compose.yml up --build
```

### Production Deployment

```bash
# Install production dependencies only (excludes dev, test and docs tools)
uv sync --frozen
# Documentation build: uv sync --frozen --extra docs

# Build production package
uv build

# Install built package
pip install dist/tribos-*.whl
```

---

## 🚨 Security Best Practices

### Regular Security Scans

```bash
# Weekly security scan (runs automatically in CI)
uv run pip-audit --desc
uv run safety check --json
uv run bandit -c pyproject.toml -r tribos/

# Check for outdated packages with vulnerabilities
uv run pip-audit --desc --format=json
```

### Upload Security

Uploads go to the API, never to a UI process: `POST /api/datasets` (`app/backend/routers/datasets.py`,
`tribos/datasets/`) and `POST /api/vision/read` (`app/backend/routers/vision.py`). Both authenticate before the
multipart body is parsed, refuse a `Content-Length` over the cap with 413, accept only listed extensions or image
types, keep server-generated paths under the upload root (uploader file names are sanitized display names only)
and validate the content before it is stored. `GET /api/datasets/limits` returns the accepted extensions and the
per-kind caps (`TRIBOS_UPLOAD_MAX_MB_*`).

### Dependency Updates

- **Dependabot** automatically creates PRs for security updates (weekly)
- **Pre-commit hooks** catch vulnerabilities before commit
- **CI pipeline** blocks PRs with security issues
- **Weekly security audits** with SARIF uploads to GitHub Security

### API Key Management

```bash
# Set environment variables (never commit these!)
export OPENAI_API_KEY=sk-...
export NVIDIA_API_KEY=nvapi-...
export ZOTERO_API_KEY=...
export ZOTERO_USER_ID=...

# Use .env file for local development (add to .gitignore!)
echo "OPENAI_API_KEY=sk-..." >> .env
```

---

## 🛠 Common Development Tasks

### Starting Development

```bash
# 1. Activate environment and install dependencies
uv sync --extra dev --frozen

# 2. Run pre-commit setup
uv run pre-commit install

# 3. Start coding!
```

### Before Committing

```bash
# 1. Run quality checks
uv run ruff check --fix .
uv run pylint tribos/
uv run mypy tribos/

# 2. Run tests
uv run pytest

# 3. Security scan
uv run pip-audit

# 4. Commit (pre-commit will run automatically)
git add .
git commit -m "your message"
```

### Adding a New Agent

1. Create new directory: `tribos/talk2newagent/`
2. Add dependencies to `pyproject.toml`
3. Update package configuration
4. Add tests and documentation
5. Update Docker configuration

---

## 🐛 Troubleshooting

### Common Issues

#### Dependency Conflicts

```bash
# Clear cache and reinstall
rm -rf .venv uv.lock
uv sync --extra dev
```

#### Pre-commit Issues

```bash
# Reinstall hooks
uv run pre-commit uninstall
uv run pre-commit install

# Update hook versions
uv run pre-commit autoupdate
```

#### Import Errors

```bash
# Verify installation
uv run python -c "import tribos; print('OK')"

# Check Python path
uv run python -c "import sys; print(sys.path)"
```

#### Type Checking Errors

```bash
# Install missing type stubs
uv add --group dev types-requests types-PyYAML

# Run with verbose output
uv run mypy --verbose tribos/
```

### Performance Issues

```bash
# Profile dependency resolution
uv sync --extra dev --verbose

# Check lock file
uv lock --verbose
```

---

## 📚 Additional Resources

### Core Tools

- [uv Documentation](https://docs.astral.sh/uv/) - Modern Python package manager
- [Hatchling](https://hatch.pypa.io/latest/) - Modern build backend
- [Ruff Rules](https://docs.astral.sh/ruff/rules/) - Fast Python linter
- [MyPy Configuration](https://mypy.readthedocs.io/en/stable/config_file.html) - Static type checking
- [Pre-commit Hooks](https://pre-commit.com/) - Git hook framework

### Security Tools

- [Bandit](https://bandit.readthedocs.io/) - Security linter for Python
- [pip-audit](https://pypi.org/project/pip-audit/) - Dependency vulnerability scanner
- [Safety](https://pyup.io/safety/) - Dependency vulnerability checker
- [python-magic](https://pypi.org/project/python-magic/) - File type detection

### CI/CD & Quality

- [SonarCloud Setup Guide](SONARCLOUD_SETUP.md) - Complete SonarCloud integration guide
- [SonarCloud](https://sonarcloud.io/) - Code quality and security analysis
- [GitHub Actions](https://docs.github.com/en/actions) - CI/CD workflows
- [Dependabot](https://docs.github.com/en/code-security/dependabot) - Automated dependency updates

---

## 🤝 Contributing

1. **Fork** the repository
2. **Create** feature branch: `git checkout -b feature/amazing-feature`
3. **Setup** development environment: `uv sync --extra dev --frozen`
4. **Install** pre-commit: `uv run pre-commit install`
5. **Make** changes and ensure all checks pass
6. **Commit** with descriptive message
7. **Push** to your fork and create Pull Request

All contributions are automatically scanned for:

- **Code formatting and style** (Ruff)
- **Type safety** (MyPy - configured, ready to enable)
- **Security vulnerabilities** (Bandit + pip-audit + Safety)
- **Test coverage** (pytest with coverage reporting)
- **Code quality** (SonarCloud analysis)
- **Dependency security** (Automated weekly scans)

---

**Happy coding! 🚀**

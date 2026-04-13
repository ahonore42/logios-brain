# Contributing to Logios Brain

Thank you for your interest in contributing.

## Development Setup

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) for package management
- Docker and Docker Compose (for local infrastructure)
- An NVIDIA NIM account (optional, for live embedding tests)

### Initial Setup

```bash
# Clone the repository
git clone https://github.com/YOUR_HANDLE/logios-brain.git
cd logios-brain

# Install dependencies
uv sync

# Copy environment file
cp .env.example .env
# Edit .env with your credentials

# Start infrastructure
docker compose up -d

# Verify the app is running
curl http://localhost:8000/health
```

### Running Tests

```bash
# All tests
uv run pytest tests/ -q

# With coverage
uv run pytest tests/ --cov=app --cov-report=term-missing

# Specific test file
uv run pytest tests/test_auth_router.py -v

# Live integration tests (require LLM_API_KEY)
uv run pytest tests/test_embeddings.py tests/test_entity_extraction_live.py -v
```

### Code Quality

Run before every commit:

```bash
# Format
uv run ruff format .

# Lint
uv run ruff check .

# Type check
uv run mypy app/ --ignore-missing-imports
```

All three must pass for CI to green-light a PR.

## Pull Request Process

### 1. Branch from `main`

```bash
git checkout -b feat/my-feature
# or
git checkout -b fix/my-bug
```

### 2. Make your changes

- Follow the existing code style (enforced by `ruff` and `mypy`)
- Add tests for new functionality
- Update documentation if applicable
- Keep commits atomic and reasonably sized

### 3. Commit

```bash
git add .
git commit -m "feat(memory): add context endpoint for turn-based retrieval"
```

Use [Conventional Commits](https://www.conventionalcommits.org/):
- `feat:` — new feature
- `fix:` — bug fix
- `refactor:` — code change that neither fixes a bug nor adds a feature
- `docs:` — documentation only
- `test:` — adding or correcting tests
- `chore:` — maintenance tasks (deps, CI, config)

### 4. Push and open a PR

```bash
git push origin feat/my-feature
```

Open a PR against `main`. Describe what changed and why.

## What to Contribute

### High-value contributions

- New agent framework integrations (`app/integrations/`)
- Bug fixes with tests
- Documentation improvements
- Performance improvements to existing features
- Additional test coverage

### Before starting large contributions

Open an issue first to discuss the change. This prevents duplicated effort and ensures the design aligns with the project goals.

## Architecture Decisions

When making architectural changes, refer to the architecture docs in `docs/architecture/`. Key principles:

- **Agents cannot prevent snapshots** — memory writes are server-controlled
- **Evidence is the source of truth for provenance** — every generation gets a receipt
- **Identity memories are owner-only** — agents cannot write `type='identity'`
- **No automatic behavioral adaptation** — improvements require human review

## Reporting Issues

Bug reports and feature requests are welcome. Please include:

- Python version, OS
- Steps to reproduce (for bugs)
- Expected vs actual behavior
- Relevant logs or error messages

## Code of Conduct

Be respectful and constructive. Disagreements about design are normal and healthy.

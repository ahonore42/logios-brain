# Changelog

All notable changes to Logios Brain are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project uses [Conventional Commits](https://www.conventionalcommits.org/).

## [Unreleased]

## [0.1.0] — 2026-04-12

### Added

- **init.sh** — Single-command first-time setup: generates secrets, starts Docker services, provisions agent token
- **provision.py** — One-command agent token provisioning via stdlib only (no httpx dependency)
- **Makefile** — Local dev workflow: `dev`, `start`, `logs`, `stop`, `clean`, `test`, `provision`
- **docker-compose healthchecks** — All 5 services (postgres, qdrant, neo4j, redis, app) now have health checks; app depends on all others becoming healthy before starting
- **app container** — Runs in Docker alongside infrastructure services; env vars use Docker DNS names; migrations auto-run on startup
- **hooks router** — Server-side HTTP hooks API at `/hooks/*`: trigger registration, buffer, check (with direct `_upsert_memory` call), flush, and force snapshot
- **hooks library** — Client-side `WorkingMemory` and `SnapshotTrigger` for agents that prefer a Python package over HTTP
- **context endpoint** — `POST /memories/context` returns identity + episodic memories for an agent turn
- **identity memories** — Owner-only CRUD at `/memories/identity`; type=`identity'` memories are always injected at session start
- **forget endpoint** — `POST /memories/forget` applies negative retrieval filters
- **digest endpoint** — `GET /memories/digest` surfaces unused, low-relevance, and checkpoint memories for human review
- **agent framework integrations** — Complete implementations for Hermes, OpenClaw, Pi Coding Agent, GoClaw, Claude Agent SDK, and ZeroClaw MCP server
- **OTP bypass** — `EMAILS_ENABLED=false` (default) returns OTP directly in `POST /auth/setup` response
- **content fingerprinting** — SHA256-based deduplication in `upsert_memory` PL/pgSQL function
- **evidence layer** — Dual Postgres + Neo4j provenance: `EvidencePath`, `EvidenceStep` chains with `[:NEXT]` ordering, `REPLACES` versioning for facts
- **memory type system** — Four memory types: `standard`, `identity` (owner-only), `checkpoint` (server-triggered), `manual`
- **deploy.sh** — Generic VPS deploy script; pulls latest, rebuilds, waits for healthy
- **CI/CD** — GitHub Actions: ruff format, ruff check, mypy, pytest with Neo4j and Qdrant service containers

### Changed

- **README** — Docker-first quick start; Bearer token auth throughout; removed manual `uv sync`/`alembic` steps
- **deploy.sh** — Removed Hetzner-specific references; uses Docker-first workflow with `docker compose up -d --build`
- **Quick Start** — Now shows `./scripts/init.sh` single command instead of multi-step manual process
- **health check** — App service health check now uses `curl` against `/health`

### Fixed

- Docker daemon flag parsing in GitHub Actions (Neo4j/Qdrant health checks)
- redis-py type stubs (`Awaitable[Any] | Any` mismatch on synchronous methods)
- spaCy entity preflight graceful degradation when model is missing
- Missing pythonpath in pytest config
- CI database dependency ordering (alembic upgrade before pytest)

### Removed

- `docs/setup/` — All 11 deprecated setup guide files (superseded by `docs/connecting-agents.md`)

# PostgreSQL Architecture: SQLAlchemy, Alembic, and psycopg

This document describes how PostgreSQL connectivity, schema migrations, and async I/O are organized in Logios Brain.

---

## Layers Overview

```
┌──────────────────────────────────────────────────────┐
│  Application Code (routes, CRUD, business logic)     │
├──────────────────────────────────────────────────────┤
│  SQLAlchemy ORM  (app/models.py, app/crud/)         │
│  AsyncSession + async_sessionmaker                   │
├──────────────────────────────────────────────────────┤
│  SQLAlchemy Core  (async engine, connection pool)     │
│  create_async_engine()                               │
├──────────────────────────────────────────────────────┤
│  psycopg3  (postgresql+psycopg://)                 │
│  AsyncConnection — async PostgreSQL driver           │
├──────────────────────────────────────────────────────┤
│  PostgreSQL  (Docker container, pgvector)            │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│  Alembic  (alembic/ env.py, versions/)              │
│  async_engine_from_config() + run_sync()            │
│  Migrations applied via psycopg3 sync path          │
├──────────────────────────────────────────────────────┤
│  psycopg3  (postgresql+psycopg://)                 │
│  Standard Connection — synchronous driver            │
└──────────────────────────────────────────────────────┘
```

The application and Alembic both use `psycopg3`, but in different modes:
- **Application**: `create_async_engine()` + `AsyncConnection` (full async path)
- **Alembic**: `async_engine_from_config()` + `run_sync()` bridge (async engine, sync migration execution)

---

## SQLAlchemy

**Docs**: https://docs.sqlalchemy.org/en/20/

SQLAlchemy is a comprehensive Python toolkit for working with databases. It has two main layers:

### SQLAlchemy Core
The foundational layer providing the **SQL Expression Language** — a composable way to construct SQL statements programmatically, independent of any ORM concepts. Core handles connection management, pooling, transactions, and result handling.

### SQLAlchemy ORM
Built on top of Core. Provides **object-relational mapping** — Python classes mapped to database tables, with sessions that track changes and flush them to the database.

### Key components used in this project

- **`create_async_engine()`** — creates an `AsyncEngine` that manages an async connection pool using a dialect like `psycopg`. The engine itself is not async, but it produces `AsyncConnection` objects.

- **`AsyncConnection`** — obtained via `engine.connect()`. Represents an async database session. All operations (`execute()`, `begin()`, `run_sync()`) are `await`-able.

- **`async_sessionmaker`** — a factory for creating `AsyncSession` objects. Configured with the engine and `expire_on_commit=False`.

- **`AsyncSession`** — the async ORM session. Used in FastAPI route handlers via the `get_db()` dependency. All session operations (`execute()`, `commit()`, `close()`) are async.

```python
# app/database.py (simplified)
engine = create_async_engine(url, echo=False)
session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

async def get_db():
    async with session_factory() as session:
        yield session
```

### Why `greenlet`?
SQLAlchemy's async extension requires **greenlet**. Greenlet is a library that allows synchronous Python code to be suspended and resumed inside an async context. When SQLAlchemy Core code calls `await` on a database operation, greenlet handles the context switch. Without greenlet, async SQLAlchemy cannot function.

---

## Alembic

**Docs**: https://alembic.sqlalchemy.org/en/latest/

Alembic is a **database migration tool** for SQLAlchemy. It manages schema changes as versioned migration scripts, supporting both autogeneration from models and hand-written SQL migrations.

### Core concepts

- **Revision** — a unique identifier (e.g., `0e75a53e20cb`) representing a point in the schema history.
- **Migration** — a Python file in `alembic/versions/` defining `upgrade()` and `downgrade()` functions.
- **Revision chain** — the ordered sequence of applied migrations tracked in the `alembic_version` table.
- **Autogenerate** — compares `Base.metadata` (derived from SQLAlchemy models) against the live database and generates the migration delta automatically.

### The `env.py` pattern

The `env.py` file is the entry point every Alembic command runs. Its job is to create a SQLAlchemy engine/connection and hand it to Alembic's migration context.

The async pattern (from the Alembic cookbook):

```python
# alembic/env.py
import asyncio
from sqlalchemy.ext.asyncio import async_engine_from_config

def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()

async def run_async_migrations():
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()

def run_migrations_online():
    asyncio.run(run_async_migrations())
```

Key insight: `async_engine_from_config()` creates an async engine, but `connection.run_sync()` bridges to Alembic's synchronous migration API. This is the supported way to run Alembic migrations with async drivers.

### Migration workflow in this project

1. Models are defined in `app/models.py` using SQLAlchemy ORM `Mapped[]` types.
2. `alembic revision --autogenerate -m "description"` compares models to the live DB and generates a migration file in `alembic/versions/`.
3. `alembic upgrade head` applies pending migrations via the async engine + run_sync bridge.
4. `alembic.ini` stores the connection URL template; `env.py` reads `DATABASE_URL` from the environment and converts it to `postgresql+psycopg://`.

### Why a separate migration tool?

SQLAlchemy's `Base.metadata.create_all()` can create tables from models, but it cannot manage schema evolution (altering columns, adding indexes, etc.) in a versioned, reversible way. Alembic adds:
- **Revision history** — know exactly what schema version the DB is at
- **Directional migrations** — `upgrade()` and `downgrade()` for forward/backward changes
- **Autogenerate** — diff models against DB to produce accurate migration scripts
- **Offline mode** — generate SQL scripts without a live connection

---

## psycopg

**Package name**: `psycopg` (there is no `psycopg3` package — it is simply `psycopg` version 3)

**Docs**: https://www.psycopg.org/psycopg3/docs/

psycopg is the most widely-used PostgreSQL adapter for Python. Version 3 (`psycopg`) is a complete rewrite with first-class async support.

### Sync vs Async modes

**Sync mode** — uses `psycopg.connect()` which returns a blocking `Connection`. All operations block the current thread. Suitable for scripts, CLI tools, and synchronous web frameworks.

**Async mode** — uses `psycopg.AsyncConnection.connect()` which returns an `AsyncConnection`. All operations are `await`-able. Required for `asyncio`-based frameworks like FastAPI.

Both modes share the same connection and cursor API — the only difference is whether you `await` or call synchronously.

### psycopg URL scheme in this project

- `postgresql://` — base PostgreSQL URL (no driver specified)
- `postgresql+psycopg://` — explicitly requests psycopg3 driver with async support

SQLAlchemy's `create_async_engine()` and `async_engine_from_config()` both accept `postgresql+psycopg://` and use psycopg's async mode automatically.

### Why psycopg and not asyncpg?

Both drivers support async PostgreSQL access:

| Feature | asyncpg | psycopg |
|---|---|---|
| Package name | `asyncpg` | `psycopg` |
| Async support | Yes (async-only) | Yes (sync + async) |
| SQLAlchemy dialect | `postgresql+asyncpg://` | `postgresql+psycopg://` |
| Can run sync SQLAlchemy migrations | No | Yes |

`asyncpg` is async-only — it cannot be used in synchronous code paths. Since Alembic's migration execution is synchronous (it calls `context.run_migrations()` in a non-async context), `asyncpg` cannot drive Alembic migrations. `psycopg` supports both sync and async, making it the single driver choice for both the async application and the async-enabled Alembic migration runner.

---

## How They Work Together in Logios Brain

### Application request lifecycle

```
FastAPI route handler
  → injects AsyncSession via get_db() dependency
    → async_sessionmaker produces AsyncSession
      → AsyncSession.execute() → AsyncConnection
        → psycopg AsyncConnection (postgresql+psycopg://)
          → PostgreSQL
```

### Alembic migration lifecycle

```
alembic upgrade head
  → env.py: run_migrations_online()
    → asyncio.run(run_async_migrations())
      → async_engine_from_config(url, postgresql+psycopg://)
        → AsyncConnection.connect()
          → psycopg AsyncConnection
            → PostgreSQL (for schema inspection during autogenerate)
        → connection.run_sync(do_run_migrations)
          → Alembic context runs upgrade() synchronously
            → op.create_table(), op.create_index(), etc.
              → psycopg sync path (inside run_sync greenlet bridge)
```

The critical bridge is `connection.run_sync()` — it takes a synchronous function (`do_run_migrations`) and executes it inside an async context, with greenlet handling the translation between async and sync worlds. This is the only way to connect Alembic's sync migration API to an async driver.

---

## Reference Links

- **SQLAlchemy 2.0**: https://docs.sqlalchemy.org/en/20/
- **SQLAlchemy asyncio extension**: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
- **Alembic**: https://alembic.sqlalchemy.org/en/latest/
- **Alembic asyncio cookbook**: https://alembic.sqlalchemy.org/en/latest/cookbook.html
- **psycopg3**: https://www.psycopg.org/psycopg3/docs/
- **psycopg3 async usage**: https://www.psycopg.org/psycopg3/docs/basic/usage.html
- **Alembic tutorial**: https://alembic.sqlalchemy.org/en/latest/tutorial.html
- **SQLAlchemy async tutorial**: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html

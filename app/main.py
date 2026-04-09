"""FastAPI entrypoint. Routes are organized in app/routes/."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import close_db, get_engine
from app.routes.health import router as health_router
from app.routes.memory import router as memory_router
from app.routes.skills import router as skills_router
from app.routes.graph import router as graph_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = get_engine()
    async with engine.begin():
        # Schema creation happens via Alembic migrations
        pass
    yield
    await close_db()


app = FastAPI(title="Logios Brain MCP Server", lifespan=lifespan)

app.include_router(health_router)
app.include_router(memory_router)
app.include_router(skills_router)
app.include_router(graph_router)

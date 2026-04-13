"""FastAPI entrypoint. Routes are organized in app/routes/."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db.database import close_db, get_engine
from app.mcp.server import mcp
from app.auth import AuthMiddleware
from app.routes.auth import router as auth_router
from app.routes.graph import router as graph_router
from app.routes.health import router as health_router
from app.routes.hooks import router as hooks_router
from app.routes.memory import router as memory_router
from app.routes.skills import router as skills_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = get_engine()
    async with engine.begin():
        pass
    # Initialize MCP session manager so it starts before handling requests
    _ = mcp.streamable_http_app()
    async with mcp.session_manager.run():
        yield
    await close_db()


app = FastAPI(title="Logios Brain", lifespan=lifespan)

app.add_middleware(AuthMiddleware)

app.include_router(auth_router)
app.include_router(health_router)
app.include_router(memory_router)
app.include_router(skills_router)
app.include_router(graph_router)
app.include_router(hooks_router)

app.mount("/mcp", mcp.streamable_http_app())

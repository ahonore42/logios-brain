"""Agent framework integrations — Logios Brain implements each framework's native interface.

Each module exposes a ``connect()`` factory that returns the framework-specific
interface (MemoryManager, Gateway extension, pipeline stage, storage adapter, etc.)
configured to communicate with Logios Brain.

Example usage::

    # Hermes Agent — register Logios as an external MemoryManager provider
    from app.integrations.hermes import connect as hermes_connect
    memory_manager = hermes_connect("http://localhost:8000", "your-api-key")
    agent = HermesAgent(external_memory_manager=memory_manager)

    # OpenClaw Gateway — load Logios as a Gateway extension
    from app.integrations.openclaw import connect as openclaw_connect
    extension = openclaw_connect("http://localhost:8000", "your-api-key")
    gateway.register_extension("logios", extension)

    # GoClaw pipeline — add Logios memory stage
    from app.integrations.goclaw import LogiosMemoryStage
    pipeline.add_stage(LogiosMemoryStage("http://localhost:8000", "your-api-key"))

    # Claude Agent SDK — use Logios as a storage adapter
    from app.integrations.claude_agent_sdk import LogiosStorageAdapter
    adapter = LogiosStorageAdapter("http://localhost:8000", "your-api-key")
"""

from app.integrations.hermes import connect as hermes_connect
from app.integrations.openclaw import connect as openclaw_connect
from app.integrations.pi import connect as pi_connect
from app.integrations.goclaw import connect as goclaw_connect
from app.integrations.claude_agent_sdk import LogiosStorageAdapter
from app.integrations.zeroclaw import LogiosMCPServer

__all__ = [
    "hermes_connect",
    "openclaw_connect",
    "pi_connect",
    "goclaw_connect",
    "LogiosStorageAdapter",
    "LogiosMCPServer",
]

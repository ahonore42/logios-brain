"""Hook library for agents using Logios Brain as memory backend.

This package is the client-side library agents import to use Logios as memory
backend. It handles:
- Working memory buffering in Redis
- Snapshot trigger logic (token threshold, call count, time-based)
- Communicating with Logios via its MCP API

Example usage with Claude Agent SDK::

    from app.hooks import WorkingMemory, SnapshotTrigger
    from app.config import REDIS_URL

    working = WorkingMemory(redis_url=REDIS_URL, session_id="sess_123", agent_id="agent_abc")
    trigger = SnapshotTrigger(mode="call_count", threshold=20, working_memory=working)

    # Register with Claude Agent SDK
    def after_tool_call(tool_name, input, result):
        working.buffer(tool_name, summarize(result), embed(result))
        if trigger.should_fire(turn_index=current_turn, token_percent=context_pct):
            snapshot = working.flush()
            call_logios_remember(snapshot)
            trigger.mark_fired(current_turn)
"""

from app.hooks.trigger import SnapshotTrigger
from app.hooks.working_memory import WorkingMemory

__all__ = ["SnapshotTrigger", "WorkingMemory"]

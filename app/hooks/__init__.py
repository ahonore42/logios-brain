"""Hook library for agents using Logios Brain as memory backend.

This package is the client-side library agents import to use Logios as memory
backend. It handles:
- Working memory buffering in Redis
- Snapshot trigger logic (token threshold, call count, time-based)
- Evidence recording after agent generations
- Communicating with Logios via its HTTP API

Example usage::

    from app.hooks import WorkingMemory, SnapshotTrigger, record_generation, GenerationRecord
    from app.config import REDIS_URL

    working = WorkingMemory(redis_url=REDIS_URL, session_id="sess_123", agent_id="agent_abc")
    trigger = SnapshotTrigger(mode="call_count", threshold=20, working_memory=working)

    # After each tool call (in PostToolUse hook)
    working.buffer(tool_name, summarize(result), embed(result))

    # When trigger fires
    if trigger.should_fire(turn_index=current_turn, token_percent=context_pct):
        working.snapshot(api_base_url="http://localhost:8000", api_key="your-key", turn_count=current_turn)
        trigger.mark_fired(current_turn)

    # After agent generates output
    receipt = record_generation(
        api_base_url="http://localhost:8000",
        api_key="your-key",
        record=GenerationRecord(
            skill_name="analysis",
            output=agent_output,
            model="microsoft/phi-3-mini-128k-instruct",
            machine="desktop-mac",
            session_id="sess_123",
            evidence=[...],
        ),
    )
"""

from app.hooks.evidence import GenerationRecord, record_generation
from app.hooks.trigger import SnapshotTrigger
from app.hooks.working_memory import WorkingMemory

__all__ = [
    "GenerationRecord",
    "record_generation",
    "SnapshotTrigger",
    "WorkingMemory",
]

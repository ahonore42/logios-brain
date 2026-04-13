"""Server-side hooks API: trigger registration, buffer, check, and snapshot.

Allows agents to use Logios as the working memory backend without running
their own Redis client. The agent sends tool results to the server via
POST /hooks/buffer, checks trigger fire conditions via POST /hooks/check,
and the server synthesizes and persists a checkpoint memory.

Key design: the server-side buffer lives in Redis under the Logios server's
Redis URL (configured via REDIS_URL). The agent never touches Redis directly.
"""

from __future__ import annotations

import fnmatch
import json
import textwrap
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import redis
from fastapi import APIRouter, Depends

from app.config import REDIS_URL
from app.dependencies import get_current_token
from app.auth import AuthContext
from app.schemas import (
    BufferRequest,
    BufferResponse,
    CheckRequest,
    CheckResponse,
    FlushResponse,
    SnapshotRequest,
    SnapshotResponse,
    TriggerConfig,
    TriggerResponse,
)


router = APIRouter(prefix="/hooks", tags=["hooks"])


# ── Redis helpers ───────────────────────────────────────────────────────────────


def _redis() -> Any:
    # redis-py stubs declare Awaitable[Any] | Any for all methods (dual sync/async API).
    # At runtime these are synchronous. Return type Any bypasses the stub mismatch.
    return redis.from_url(REDIS_URL, decode_responses=True)


def _trigger_key(session_id: str, agent_id: str) -> str:
    return f"hooks:trigger:{session_id}:{agent_id}"


def _buffer_pattern(session_id: str, agent_id: str) -> str:
    return f"hooks:buffer:{session_id}:{agent_id}:*"


def _annotation_key(session_id: str, agent_id: str) -> str:
    return f"hooks:annotation:{session_id}:{agent_id}"


def _last_key(session_id: str, agent_id: str) -> str:
    return f"hooks:last:{session_id}:{agent_id}"


def _synthesize_content(entries: list[dict[str, Any]]) -> str:
    """Group buffered entries by tool name and summarize."""
    if not entries:
        return "Empty checkpoint."

    tool_groups: dict[str, list[str]] = {}
    for entry in entries:
        tool = entry.get("tool_name", "unknown")
        summary = entry.get("result_summary", "")
        tool_groups.setdefault(tool, []).append(summary)

    lines = ["Checkpoint:"]
    for tool, summaries in tool_groups.items():
        lines.append(f"  {tool}: {len(summaries)} call(s)")
        for s in summaries[:3]:
            wrapped = textwrap.shorten(s, width=72, placeholder="...")
            lines.append(f"    - {wrapped}")
        if len(summaries) > 3:
            lines.append(f"    ... and {len(summaries) - 3} more")

    return "\n".join(lines)


def _forget_filtered(
    entries: list[dict[str, Any]], forget_patterns: list[str]
) -> list[dict[str, Any]]:
    """Exclude entries matching any fnmatch forget pattern."""
    if not forget_patterns:
        return entries
    return [
        e
        for e in entries
        if not any(fnmatch.fnmatch(e.get("tool_name", ""), p) for p in forget_patterns)
    ]


# ── Endpoints ───────────────────────────────────────────────────────────────────


@router.post("/trigger", response_model=TriggerResponse)
def register_trigger(
    data: TriggerConfig,
    _auth: AuthContext = Depends(get_current_token),
) -> TriggerResponse:
    """
    Register (or update) a snapshot trigger for a session.

    The trigger configuration is stored in Redis. Call this once at the
    start of a session, or to reconfigure mid-session.
    """
    r = _redis()
    key = _trigger_key(data.session_id, data.agent_id)
    r.set(
        key,
        json.dumps(
            {
                "mode": data.mode,
                "threshold": data.threshold,
                "session_id": data.session_id,
                "agent_id": data.agent_id,
            }
        ),
    )
    return TriggerResponse(
        session_id=data.session_id,
        mode=data.mode,
        threshold=data.threshold,
        message=f"Trigger registered: {data.mode} with threshold {data.threshold}",
    )


@router.post("/buffer", response_model=BufferResponse)
def buffer_entry(
    data: BufferRequest,
    _auth: AuthContext = Depends(get_current_token),
) -> BufferResponse:
    """
    Buffer a tool call result for future snapshot.

    Returns the Redis key for this entry and the total buffered count.
    The entry is stored in Redis under the session-scoped buffer key.
    """
    r = _redis()
    pattern = _buffer_pattern(data.session_id, data.agent_id)
    existing_keys = r.keys(pattern)
    next_index = len(existing_keys)

    entry_key = f"hooks:buffer:{data.session_id}:{data.agent_id}:{next_index:04d}"
    entry = {
        "session_id": data.session_id,
        "agent_id": data.agent_id,
        "tool_name": data.tool_name,
        "result_summary": data.result_summary,
        "result_embedding": data.result_embedding,
        "turn_index": data.turn_index,
        "forget_patterns": [],
    }
    r.set(entry_key, json.dumps(entry))

    new_count = len(r.keys(pattern))
    return BufferResponse(entry_key=entry_key, buffered_count=new_count)


@router.post("/check", response_model=CheckResponse)
def check_trigger(
    data: CheckRequest,
    _auth: AuthContext = Depends(get_current_token),
) -> CheckResponse:
    """
    Check whether the registered trigger has fired.

    Evaluates the trigger condition based on current_turn and token_percent.
    If should_fire=True, also synthesizes the snapshot and POSTs it to
    /memories/remember, then clears the buffer.

    Call this after each agent turn. If should_fire=True, load the
    snapshot_content into context and call mark_fired on your client trigger.
    """
    r = _redis()
    trigger_key = _trigger_key(data.session_id, data.agent_id)
    trigger_raw = r.get(trigger_key)

    if not trigger_raw:
        return CheckResponse(
            should_fire=False,
            turns_since_last=0,
        )

    trigger = json.loads(trigger_raw)
    mode = trigger.get("mode", "call_count")
    threshold = trigger.get("threshold", 20)

    # Load last snapshot metadata
    last_raw = r.get(_last_key(data.session_id, data.agent_id))
    last_turn = 0
    last_time = datetime.now(timezone.utc)
    if last_raw:
        last_data = json.loads(last_raw)
        last_turn = last_data.get("turn", 0)
        last_time_str = last_data.get("time")
        if last_time_str:
            last_time = datetime.fromisoformat(last_time_str)

    should_fire = False
    turns_since = data.current_turn - last_turn

    if mode == "call_count":
        should_fire = turns_since >= threshold
    elif mode == "token":
        should_fire = data.token_percent is not None and data.token_percent >= threshold
    elif mode == "time_based":
        elapsed = datetime.now(timezone.utc) - last_time
        should_fire = elapsed >= timedelta(minutes=threshold)

    if not should_fire:
        return CheckResponse(
            should_fire=False,
            turns_since_last=turns_since,
        )

    # ── Trigger fired — synthesize and snapshot ───────────────────────────────

    # Collect and filter entries
    pattern = _buffer_pattern(data.session_id, data.agent_id)
    keys = r.keys(pattern)
    entries: list[dict[str, Any]] = []
    for k in sorted(keys):
        raw = r.get(k)
        if raw:
            entries.append(json.loads(raw))
    entries = _forget_filtered(entries, trigger.get("forget_patterns", []))

    content = _synthesize_content(entries)

    # Annotation if set
    annotation_key = _annotation_key(data.session_id, data.agent_id)
    annotation = r.get(annotation_key)
    if annotation:
        r.delete(annotation_key)

    # POST to /memories/remember using the internal API key approach
    # We use httpx since we don't have access to the internal _upsert_memory
    tool_calls = [
        {"tool": e.get("tool_name", ""), "result_ref": e.get("raw_result_ref", "")}
        for e in entries
    ]

    metadata = {
        "type": "checkpoint",
        "session_id": data.session_id,
        "agent_id": data.agent_id,
        "tool_calls": tool_calls,
        "turn_count": data.current_turn,
        "snapshot_trigger": mode,
        "agent_annotation": annotation,
    }

    payload = {
        "content": content,
        "source": "agent",
        "type": "checkpoint",
        "metadata": metadata,
    }

    # Get the Logios API key from auth context — use the agent/owner token
    # The hooks router receives a bearer token; we forward it to /memories/remember
    # For internal calls, we use the same auth mechanism
    headers = {
        "Content-Type": "application/json",
    }

    snapshot_memory_id: str | None = None
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                "http://localhost:8000/memories/remember",
                json=payload,
                headers=headers,
            )
            if resp.status_code in (200, 201):
                snapshot_memory_id = resp.json().get("id")
    except Exception:
        # Snapshot failed — still fire so the agent knows, but don't clear buffer
        pass

    # Clear buffer entries
    for k in keys:
        r.delete(k)

    # Update last snapshot state
    r.set(
        _last_key(data.session_id, data.agent_id),
        json.dumps(
            {
                "turn": data.current_turn,
                "time": datetime.now(timezone.utc).isoformat(),
            }
        ),
    )

    return CheckResponse(
        should_fire=True,
        memory_id=snapshot_memory_id,
        snapshot_content=content,
        entries=entries,
        entry_count=len(entries),
        turns_since_last=turns_since,
    )


@router.post("/flush", response_model=FlushResponse)
def flush_buffer(
    session_id: str,
    agent_id: str = "default",
    _auth: AuthContext = Depends(get_current_token),
) -> FlushResponse:
    """
    Flush the buffer without snapshotting.

    Returns all buffered entries and clears them from Redis.
    Use this when ending a session without triggering a checkpoint.
    """
    r = _redis()
    pattern = _buffer_pattern(session_id, agent_id)
    keys = r.keys(pattern)
    entries: list[dict[str, Any]] = []

    for k in sorted(keys):
        raw = r.get(k)
        if raw:
            entries.append(json.loads(raw))
        r.delete(k)

    return FlushResponse(entries=entries, flushed_count=len(entries))


@router.post("/snapshot", response_model=SnapshotResponse)
def force_snapshot(
    data: SnapshotRequest,
    _auth: AuthContext = Depends(get_current_token),
) -> SnapshotResponse:
    """
    Force a snapshot regardless of trigger state.

    Synthesizes all buffered entries into a checkpoint memory and POSTs
    to /memories/remember. Clears the buffer after.
    """
    r = _redis()
    pattern = _buffer_pattern(data.session_id, data.agent_id)
    keys = r.keys(pattern)
    entries: list[dict[str, Any]] = []

    for k in sorted(keys):
        raw = r.get(k)
        if raw:
            entries.append(json.loads(raw))
        r.delete(k)

    turn_count = data.turn_count if data.turn_count is not None else len(entries)

    # Get annotation
    annotation_key = _annotation_key(data.session_id, data.agent_id)
    annotation = r.get(annotation_key)
    if annotation:
        r.delete(annotation_key)

    content = _synthesize_content(entries)

    tool_calls = [
        {"tool": e.get("tool_name", ""), "result_ref": e.get("raw_result_ref", "")}
        for e in entries
    ]

    metadata = {
        "type": "checkpoint",
        "session_id": data.session_id,
        "agent_id": data.agent_id,
        "tool_calls": tool_calls,
        "turn_count": turn_count,
        "snapshot_trigger": "manual",
        "agent_annotation": annotation,
    }

    payload = {
        "content": content,
        "source": "agent",
        "type": "checkpoint",
        "metadata": metadata,
    }

    headers = {"Content-Type": "application/json"}
    memory_id = None

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                "http://localhost:8000/memories/remember",
                json=payload,
                headers=headers,
            )
            if resp.status_code in (200, 201):
                result = resp.json()
                memory_id = result.get("id")
    except Exception:
        pass

    # Update last snapshot state
    r.set(
        _last_key(data.session_id, data.agent_id),
        json.dumps(
            {
                "turn": turn_count,
                "time": datetime.now(timezone.utc).isoformat(),
            }
        ),
    )

    return SnapshotResponse(
        memory_id=memory_id or "",
        checkpoint_content=content,
        entry_count=len(entries),
        message=f"Snapshot created with {len(entries)} entries",
    )

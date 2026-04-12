"""Working memory: Redis-backed buffer for tool call results before snapshot."""

from __future__ import annotations

import fnmatch
import json
import textwrap
from typing import Any, Literal, Optional, cast

import httpx
import redis


class WorkingMemory:
    """
    Client-side Redis buffer for tool call results.

    Buffers tool call results in Redis before a snapshot fires. Each entry
    is stored with a session-scoped key and a monotonically increasing turn index.
    Forget filters are applied to entries in-memory when flush() is called.

    Usage::

        working = WorkingMemory(
            redis_url="redis://localhost:6379/0",
            session_id="sess_abc123",
            agent_id="agent_xyz",
        )

        # After each tool call
        working.buffer("read_file", "auth/middleware.py: 120 lines, routes: /auth/setup, /auth/verify", embedding)

        # When trigger fires
        entries = working.flush()  # returns list, clears buffer

    """

    KEY_PREFIX = "working"

    def __init__(
        self,
        redis_url: str,
        session_id: str,
        agent_id: str,
    ) -> None:
        self._redis = redis.from_url(redis_url, decode_responses=True)
        self._session_id = session_id
        self._agent_id = agent_id
        self._turn_index = 0
        self._forget_patterns: list[str] = []

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def agent_id(self) -> str:
        return self._agent_id

    def _entry_key(self, turn_index: int) -> str:
        return f"{self.KEY_PREFIX}:{self._session_id}:tool:{turn_index:04d}"

    def _scan_pattern(self) -> str:
        return f"{self.KEY_PREFIX}:{self._session_id}:*"

    def buffer(
        self,
        tool_name: str,
        result_summary: str,
        result_embedding: Optional[list[float]] = None,
    ) -> str:
        """
        Buffer a tool call result.

        Returns the Redis key for this entry.
        """
        entry_key = self._entry_key(self._turn_index)
        entry: dict[str, Any] = {
            "session_id": self._session_id,
            "agent_id": self._agent_id,
            "tool_name": tool_name,
            "result_summary": result_summary,
            "result_embedding": result_embedding or [],
            "raw_result_ref": entry_key,
            "turn_index": self._turn_index,
            "forget_patterns": [],
        }
        self._redis.set(entry_key, json.dumps(entry))
        self._turn_index += 1
        return entry_key

    def forget(self, pattern: str) -> None:
        """
        Register a forget pattern for future retrieval filtering.

        The pattern is fnmatch-style (e.g. "*.py", "read_file").
        Entries matching this pattern will be excluded from flush() results
        and from retrieval queries. Only affects retrieval — data remains
        in Redis until the snapshot fires.
        """
        if pattern not in self._forget_patterns:
            self._forget_patterns.append(pattern)

    def _matches_any_pattern(self, tool_name: str) -> bool:
        for pat in self._forget_patterns:
            if fnmatch.fnmatch(tool_name, pat):
                return True
        return False

    def _apply_forget_filters(self, entries: list[dict]) -> list[dict]:
        """Filter out entries matching any forget pattern."""
        return [e for e in entries if not self._matches_any_pattern(e.get("tool_name", ""))]

    def flush(self) -> list[dict]:
        """
        Clear the buffer and return all buffered entries.

        Forget filters are applied before returning. Entries matching any
        forget pattern are excluded.
        """
        pattern = self._scan_pattern()
        keys = cast("list[str]", self._redis.keys(pattern))
        entries: list[dict] = []

        for key in keys:
            raw = cast("str | None", self._redis.get(key))
            if raw:
                entries.append(json.loads(raw))
            self._redis.delete(key)

        self._turn_index = 0
        return self._apply_forget_filters(entries)

    def get_forget_filters(self) -> list[str]:
        """Return all registered forget patterns."""
        return list(self._forget_patterns)

    def get_buffered_count(self) -> int:
        """Return the number of entries currently buffered (before forget filters)."""
        pattern = self._scan_pattern()
        return len(cast("list[str]", self._redis.keys(pattern)))

    def _annotation_key(self) -> str:
        return f"{self.KEY_PREFIX}:{self._session_id}:annotation"

    def annotate(self, annotation: str) -> None:
        """
        Store an agent-provided annotation to be included in the next snapshot.

        The annotation is stored in Redis under a session-scoped key. It is
        picked up by the next snapshot() call and included in the checkpoint
        metadata as agent_annotation, then cleared.
        """
        key = self._annotation_key()
        self._redis.set(key, annotation)

    def _get_and_clear_annotation(self) -> Optional[str]:
        """Retrieve and clear the stored annotation. Returns None if none set."""
        key = self._annotation_key()
        annotation = cast("str | None", self._redis.get(key))
        if annotation:
            self._redis.delete(key)
        return annotation if annotation else None

    def _synthesize_content(self, entries: list[dict]) -> str:
        """
        Synthesize buffered entries into a checkpoint content string.

        Groups entries by tool name and summarizes the work done.
        """
        if not entries:
            return "Empty checkpoint."

        tool_groups: dict[str, list[str]] = {}
        for entry in entries:
            tool = entry.get("tool_name", "unknown")
            summary = entry.get("result_summary", "")
            if tool not in tool_groups:
                tool_groups[tool] = []
            tool_groups[tool].append(summary)

        lines = ["Checkpoint:"]
        for tool, summaries in tool_groups.items():
            lines.append(f"  {tool}: {len(summaries)} call(s)")
            for s in summaries[:3]:
                wrapped = textwrap.shorten(s, width=72, placeholder="...")
                lines.append(f"    - {wrapped}")
            if len(summaries) > 3:
                lines.append(f"    ... and {len(summaries) - 3} more")

        return "\n".join(lines)

    def snapshot(
        self,
        api_base_url: str,
        api_key: str,
        trigger_mode: Literal["token", "call_count", "time_based"] = "call_count",
        turn_count: Optional[int] = None,
    ) -> dict:
        """
        Flush the buffer, synthesize into a checkpoint memory, and POST to Logios.

        Returns the JSON response from POST /memories/remember.

        The synthesized content summarizes all buffered tool results grouped by
        tool name. The checkpoint metadata includes the full tool_calls list
        (with Redis refs for reconstruction), turn_count, trigger_mode, and
        the agent_annotation if one was provided via annotate().

        Usage::

            if trigger.should_fire(turn_index=14):
                result = working.snapshot(
                    api_base_url="http://localhost:8000",
                    api_key="your-brain-key",
                    trigger_mode="call_count",
                    turn_index=14,
                )
                trigger.mark_fired(14)
        """
        entries = self.flush()
        annotation = self._get_and_clear_annotation()
        turn_count = turn_count if turn_count is not None else self._turn_index

        content = self._synthesize_content(entries)

        tool_calls = [
            {
                "tool": e.get("tool_name", ""),
                "result_ref": e.get("raw_result_ref", ""),
            }
            for e in entries
        ]

        metadata = {
            "type": "checkpoint",
            "session_id": self._session_id,
            "agent_id": self._agent_id,
            "tool_calls": tool_calls,
            "turn_count": turn_count,
            "snapshot_trigger": trigger_mode,
            "agent_annotation": annotation,
        }

        payload = {
            "content": content,
            "source": "agent",
            "type": "checkpoint",
            "metadata": metadata,
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                f"{api_base_url.rstrip('/')}/memories/remember",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            return response.json()

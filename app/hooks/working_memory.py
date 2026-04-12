"""Working memory: Redis-backed buffer for tool call results before snapshot."""

from __future__ import annotations

import fnmatch
from typing import cast
import json
from typing import Any, Optional

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

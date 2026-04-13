"""Hermes Agent integration — Logios as a MemoryProvider plugin.

Implements the Hermes MemoryProvider interface (from agent/memory_provider.py).
Hermes coordinates one built-in provider + one external plugin provider.

Architecture:
- Built-in provider owns the static identity/instruction layer (~12k token
  system prompt block, loaded once at session start from MEMORY.md/USER.md).
  This CANNOT be replaced or disabled.
- External provider (this module) is ADDITIVE — it adds episodic recall,
  working memory buffering, and per-turn context injection on top of the
  built-in layer.

Key Hermes lifecycle events:
- initialize()           → called once at agent startup
- prefetch(query)        → called BEFORE each API call (per-turn recall)
- sync_turn()            → called AFTER each turn (persist working memory)
- queue_prefetch(query)  → called after each turn (queue next turn's recall)
- on_session_end()      → called at session boundaries only
- on_pre_compress()      → called before context compression
- on_memory_write()      → called when Hermes's built-in memory tool fires

Usage::

    from app.integrations.hermes import LogiosMemoryProvider

    provider = LogiosMemoryProvider(
        api_base_url="http://localhost:8000",
        api_key="tok_your_api_key",
        session_id="sess_abc123",
        agent_id="hermes-1",
        redis_url="redis://localhost:6379",
        snapshot_threshold=20,
    )

    # Register with Hermes Agent
    memory_manager.add_provider(provider)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx

from app.hooks import SnapshotTrigger, WorkingMemory

if TYPE_CHECKING:
    from app.hooks.working_memory import WorkingMemory

logger = logging.getLogger(__name__)

# Default number of memories to return per prefetch
DEFAULT_TOP_K = 8


class LogiosMemoryProvider:
    """
    Hermes MemoryProvider backed by Logios Brain.

    Additive to Hermes's built-in provider — never disables or replaces it.
    Only one external provider is allowed; Hermes enforces this.

    Memory lifecycle:
    1. initialize()        — warm up Redis connection
    2. prefetch(query)    — return episodic memories for current turn
    3. sync_turn()        — buffer the completed turn's user/assistant content
    4. queue_prefetch()   — background prefetch for next turn
    5. on_session_end()    — flush working memory as a checkpoint
    6. on_pre_compress()  — contribute memories before context compression
    7. on_memory_write()  — mirror Hermes built-in memory writes to Logios
    8. shutdown()          — flush any remaining buffer on exit
    """

    def __init__(
        self,
        api_base_url: str,
        api_key: str,
        session_id: str,
        agent_id: str,
        redis_url: str,
        snapshot_threshold: int = 20,
    ) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.api_key = api_key
        self.session_id = session_id
        self.agent_id = agent_id
        self.snapshot_threshold = snapshot_threshold

        self._working: "WorkingMemory | None" = None
        self._trigger: "SnapshotTrigger | None" = None
        self._turn_index = 0
        self._cached_prefetch: str | None = None
        self._initialized = False

    @property
    def name(self) -> str:
        return "logios"

    # ── Availability ─────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Return True if Logios Brain is reachable."""
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(f"{self.api_base_url}/health")
                return resp.status_code == 200
        except Exception:
            return False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def initialize(self, session_id: str, **kwargs) -> None:
        """Initialize working memory and snapshot trigger for this session.

        Called once at agent startup. Stores session_id from Hermes and
        sets up the Redis-backed working memory buffer.
        """
        self.session_id = session_id

        self._working = WorkingMemory(
            redis_url=f"redis://{self._redis_host()}:6379/0",
            session_id=session_id,
            agent_id=self.agent_id,
        )
        self._trigger = SnapshotTrigger(
            mode="call_count",
            threshold=self.snapshot_threshold,
            working_memory=self._working,
        )
        self._turn_index = 0
        self._cached_prefetch = None
        self._initialized = True
        logger.info("LogiosMemoryProvider initialized for session %s", session_id)

    def _redis_host(self) -> str:
        """Extract hostname from redis URL for Docker networking."""
        from urllib.parse import urlparse

        parsed = urlparse(self.api_base_url)
        # In Docker, app can't reach host localhost — use service name
        if parsed.hostname in ("localhost", "127.0.0.1"):
            return "host.docker.internal"
        return "localhost"

    def shutdown(self) -> None:
        """Flush working memory on shutdown."""
        if self._working and self._trigger and self._turn_index > 0:
            if self._trigger.should_fire(self._turn_index):
                self._working.snapshot(
                    api_base_url=self.api_base_url,
                    api_key=self.api_key,
                    turn_count=self._turn_index,
                )
        self._initialized = False
        logger.info("LogiosMemoryProvider shutdown complete")

    # ── System prompt ────────────────────────────────────────────────────────

    def system_prompt_block(self) -> str:
        """
        Return empty string.

        Hermes's built-in provider already loads the identity/instruction
        layer (~12k tokens) into the system prompt at session start.
        Injecting Logios identity memories here would duplicate context.
        """
        return ""

    # ── Per-turn recall ───────────────────────────────────────────────────────

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        """
        Return episodic memories from Logios for the upcoming turn.

        Called BEFORE each API call by MemoryManager.prefetch_all().
        Returns formatted text to inject as context — additive to the
        built-in provider's system prompt block.

        Uses a cached result from the previous turn's queue_prefetch() to
        avoid redundant HTTP calls at per-turn frequency.
        """
        if self._cached_prefetch is not None:
            result = self._cached_prefetch
            self._cached_prefetch = None
            return result

        # Fallback: blocking recall if no prefetch was queued
        try:
            payload = {
                "query": query or f"session {session_id or self.session_id}",
                "session_id": session_id or self.session_id,
                "top_k": DEFAULT_TOP_K,
            }
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    f"{self.api_base_url}/memories/context",
                    json=payload,
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()

            identity = data.get("identity_memories", [])
            episodic = data.get("episodic_memories", [])

            parts = []
            for mem in identity:
                parts.append(f"[identity] {mem.get('content', '')}")
            for mem in episodic:
                parts.append(f"[memory] {mem.get('content', '')}")

            return "\n".join(parts)
        except Exception as e:
            logger.warning("Logios prefetch failed (non-fatal): %s", e)
            return ""

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        """
        Queue a background recall for the NEXT turn.

        Called after each turn completes. Stores the result in a instance
        cache so the next prefetch() call returns instantly without an
        HTTP round-trip.
        """
        def _background_recall() -> None:
            try:
                payload = {
                    "query": query or f"session {session_id or self.session_id}",
                    "session_id": session_id or self.session_id,
                    "top_k": DEFAULT_TOP_K,
                }
                with httpx.Client(timeout=10.0) as client:
                    resp = client.post(
                        f"{self.api_base_url}/memories/context",
                        json=payload,
                        headers=self._headers(),
                    )
                    resp.raise_for_status()
                    data = resp.json()

                identity = data.get("identity_memories", [])
                episodic = data.get("episodic_memories", [])

                parts = []
                for mem in identity:
                    parts.append(f"[identity] {mem.get('content', '')}")
                for mem in episodic:
                    parts.append(f"[memory] {mem.get('content', '')}")

                self._cached_prefetch = "\n".join(parts)
            except Exception as e:
                logger.debug("Logios background prefetch failed: %s", e)
                self._cached_prefetch = ""

        # Fire in a background thread — prefetch must return fast
        import threading
        t = threading.Thread(target=_background_recall, daemon=True)
        t.start()

    # ── Per-turn sync ────────────────────────────────────────────────────────

    def sync_turn(
        self, user_content: str, assistant_content: str, *, session_id: str = ""
    ) -> None:
        """
        Buffer a completed turn for future snapshot.

        Called after each turn by MemoryManager.sync_all().
        Stores the turn in Redis. Auto-snapshots when the threshold is hit.
        """
        self._turn_index += 1

        if self._working is None or self._trigger is None:
            return

        # Summarize the turn for working memory
        summary = (
            f"user: {user_content[:200]}\nassistant: {assistant_content[:200]}"
        )
        self._working.buffer(
            tool_name="_hermes_turn",
            result_summary=summary,
            result_embedding=[0.0] * 4096,  # embeddings not available post-turn
        )

        if self._trigger.should_fire(self._turn_index):
            self._working.snapshot(
                api_base_url=self.api_base_url,
                api_key=self.api_key,
                turn_count=self._turn_index,
            )
            self._trigger.mark_fired(self._turn_index)

    # ── Session lifecycle ────────────────────────────────────────────────────

    def on_turn_start(self, turn_number: int, message: str, **kwargs) -> None:
        """
        Per-turn tick — increment turn counter.

        Hermes calls this before each turn. We use it to track turn index.
        The actual per-turn recall context is delivered via prefetch(), not here.
        """
        self._turn_index = turn_number

    def on_session_end(self, messages: list[dict[str, Any]]) -> None:
        """
        Flush working memory as a checkpoint when session ends.

        Called at session boundaries (CLI exit, /reset, gateway expiry).
        NOT called after every turn.
        """
        if self._working is None or self._trigger is None:
            return

        if self._trigger.should_fire(self._turn_index):
            self._working.snapshot(
                api_base_url=self.api_base_url,
                api_key=self.api_key,
                turn_count=self._turn_index,
            )
            self._trigger.mark_fired(self._turn_index)
        self._working.forget("*")  # clear buffer after session end

    def on_pre_compress(self, messages: list[dict[str, Any]]) -> str:
        """
        Contribute memories to the compression summary.

        Called before context compression discards old messages.
        Returns formatted text for the compressor to include.
        """
        try:
            # Extract a query from the last user message in the truncated window
            query = ""
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        query = content[:200]
                    break

            payload = {"query": query or "session", "top_k": 5}
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    f"{self.api_base_url}/memories/search",
                    json=payload,
                    headers=self._headers(),
                )
                resp.raise_for_status()
                results = resp.json()

            if not results:
                return ""

            parts = ["[Pre-compress memory recall]"]
            for mem in results:
                parts.append(f"- {mem.get('content', '')}")
            return "\n".join(parts)
        except Exception as e:
            logger.debug("Logios on_pre_compress failed (non-fatal): %s", e)
            return ""

    def on_memory_write(self, action: str, target: str, content: str) -> None:
        """
        Mirror Hermes built-in memory writes to Logios.

        Called when the agent uses Hermes's built-in memory tool
        (e.g. /memory add, /memory replace, /memory remove).
        """
        if target not in ("memory", "user"):
            return

        try:
            memory_type = "identity" if target == "user" else "standard"
            payload = {
                "content": content,
                "source": "hermes-builtin",
                "type": memory_type,
                "session_id": self.session_id,
                "metadata": {
                    "hermes_action": action,
                    "hermes_target": target,
                    "agent_id": self.agent_id,
                },
            }
            with httpx.Client(timeout=10.0) as client:
                client.post(
                    f"{self.api_base_url}/memories/remember",
                    json=payload,
                    headers=self._headers(),
                )
        except Exception as e:
            logger.warning("Logios on_memory_write failed (non-fatal): %s", e)

    # ── Tools (none — context-only provider) ─────────────────────────────────

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """
        Return no tools.

        Logios is a context-only provider — all operations happen via
        prefetch/sync_turn/snapshot behind the scenes. No tool schemas needed.
        """
        return []

    # ── Internal ────────────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }


# ── Convenience factory ───────────────────────────────────────────────────────


def connect(
    api_base_url: str,
    api_key: str,
    session_id: str,
    agent_id: str,
    redis_url: str = "redis://localhost:6379",
    snapshot_threshold: int = 20,
) -> LogiosMemoryProvider:
    """
    Build a Logios Hermes MemoryProvider and configure Redis URL.

    Args:
        api_base_url:        Logios Brain HTTP base (e.g. "http://localhost:8000")
        api_key:             Logios API key (from owner setup)
        session_id:          Unique session identifier
        agent_id:            Unique agent identifier
        redis_url:           Redis URL for working memory buffer
        snapshot_threshold:  Tool calls before auto-snapshot (default: 20)

    Returns:
        LogiosMemoryProvider — pass to MemoryManager.add_provider()
    """
    return LogiosMemoryProvider(
        api_base_url=api_base_url,
        api_key=api_key,
        session_id=session_id,
        agent_id=agent_id,
        redis_url=redis_url,
        snapshot_threshold=snapshot_threshold,
    )

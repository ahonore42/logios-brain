"""Snapshot trigger logic for server-controlled memory snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from app.hooks.working_memory import WorkingMemory


@dataclass
class SnapshotTrigger:
    """
    Server-side snapshot trigger.

    Evaluates whether a snapshot should fire based on configurable thresholds.
    The trigger is stateless — it tracks its own last_snapshot_turn and
    last_snapshot_time to evaluate should_fire().

    Usage::

        working = WorkingMemory(...)
        trigger = SnapshotTrigger(
            mode="call_count",
            threshold=20,
            working_memory=working,
        )

        for turn_index, token_pct in enumerate(token_usages):
            if trigger.should_fire(turn_index=turn_index, token_percent=token_pct):
                snapshot = working.flush()
                call_logios_remember(snapshot)
                trigger.mark_fired(turn_index)
    """

    mode: Literal["token", "call_count", "time_based"]
    """Mode determines which threshold is evaluated."""

    threshold: int
    """
    Threshold value:
    - call_count: fire every N tool calls
    - token: fire when context usage >= N percent (e.g. 80)
    - time_based: fire if N minutes have passed since last snapshot
    """

    working_memory: WorkingMemory
    """Back-reference to the working memory buffer."""

    last_snapshot_turn: int = 0
    """Turn index when the last snapshot fired."""

    last_snapshot_time: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    """UTC timestamp of the last snapshot."""

    def should_fire(self, turn_index: int, token_percent: float | None = None) -> bool:
        """
        Return True if the snapshot trigger condition is met.
        """
        if self.mode == "call_count":
            return (turn_index - self.last_snapshot_turn) >= self.threshold
        elif self.mode == "token":
            if token_percent is None:
                return False
            return token_percent >= self.threshold
        elif self.mode == "time_based":
            elapsed = datetime.now(timezone.utc) - self.last_snapshot_time
            return elapsed >= timedelta(minutes=self.threshold)
        return False

    def mark_fired(self, turn_index: int) -> None:
        """
        Record that a snapshot fired at the given turn index.
        """
        self.last_snapshot_turn = turn_index
        self.last_snapshot_time = datetime.now(timezone.utc)

    def reset(self) -> None:
        """
        Reset trigger state — clears last snapshot time and turn.
        Call when starting a new session.
        """
        self.last_snapshot_turn = 0
        self.last_snapshot_time = datetime.now(timezone.utc)

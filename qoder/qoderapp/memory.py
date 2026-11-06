"""Review state kept in PowerContext.

The desk remembers, for every topic, which notes the reader already
mastered and which ones are still open.  The state is written through the
public Memory application, so a later run of the service finds the same
Scope, reads the record back and can tell the reader what is still open.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    RememberMemoryRequest,
    SearchMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.config import RuntimeConfig
from powercontext.builtin.scope import ScopeDraft

from qoderapp.config import Settings

STATE_MARKER = "RESEARCH-DESK-STATE"


@dataclass
class TopicState:
    """The review state of one topic."""

    topic: str
    mastered: list[str] = field(default_factory=list)
    open_notes: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    reviews: int = 0

    def to_payload(self) -> str:
        # The marker is part of the stored text so that the fulltext query
        # that looks the state up finds it again.  Without it the record
        # would only be reachable by luck, through a word of the payload.
        return f"{STATE_MARKER} " + json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_payload(cls, payload: str) -> "TopicState":
        text = payload.strip()
        if text.startswith(STATE_MARKER):
            text = text[len(STATE_MARKER) :].strip()
        data = json.loads(text)
        return cls(
            topic=str(data.get("topic", "")),
            mastered=list(data.get("mastered", [])),
            open_notes=list(data.get("open_notes", [])),
            questions=list(data.get("questions", [])),
            reviews=int(data.get("reviews", 0)),
        )


@dataclass
class DeskMemory:
    """PowerContext backed store of the review state."""

    settings: Settings

    def _config(self) -> BuiltinConfig:
        path = Path(self.settings.state_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return BuiltinConfig(
            database=SQLiteConfig(url=f"sqlite+aiosqlite:///{path.as_posix()}"),
            runtime=RuntimeConfig(artifact_processing_families=()),
        )

    async def _scope_id(self, runtime, scope: str) -> str:
        try:
            created = await runtime.scopes.create(
                ScopeDraft(title=scope, summary="Research desk state", idempotency_key=scope)
            )
        except Exception:
            for descriptor in await runtime.scopes.list():
                if descriptor.title == scope:
                    return descriptor.scope_id
            raise
        return created.scope_id

    async def load(self, topic: str) -> TopicState | None:
        """Read the review state of one topic back."""

        async with open_builtin_runtime(self._config()) as runtime:
            scope_id = await self._scope_id(runtime, self.settings.scope)
            page = await runtime.memory.for_scope(scope_id).search(
                SearchMemoryRequest(query=STATE_MARKER, mode="fts", limit=20)
            )
            newest: TopicState | None = None
            for hit in page.hits:
                if not hit.text.startswith(STATE_MARKER):
                    continue
                state = TopicState.from_payload(hit.text)
                if state.topic != topic:
                    continue
                # The memory is append only, so the newest record of a topic is
                # the one with the highest revision.
                if newest is None or state.reviews > newest.reviews:
                    newest = state
            return newest

    async def save(self, state: TopicState) -> None:
        """Persist the review state of one topic."""

        async with open_builtin_runtime(self._config()) as runtime:
            scope_id = await self._scope_id(runtime, self.settings.scope)
            await runtime.memory.for_scope(scope_id).remember(
                RememberMemoryRequest(
                    entries=(MemoryEntryInput(kind="fact", text=state.to_payload()),)
                )
            )

    async def all_states(self) -> list[TopicState]:
        """Read every stored review state back."""

        async with open_builtin_runtime(self._config()) as runtime:
            scope_id = await self._scope_id(runtime, self.settings.scope)
            page = await runtime.memory.for_scope(scope_id).search(
                SearchMemoryRequest(query=STATE_MARKER, mode="fts", limit=50)
            )
            newest: dict[str, TopicState] = {}
            for hit in page.hits:
                if not hit.text.startswith(STATE_MARKER):
                    continue
                state = TopicState.from_payload(hit.text)
                current = newest.get(state.topic)
                if current is None or state.reviews > current.reviews:
                    newest[state.topic] = state
            return list(newest.values())

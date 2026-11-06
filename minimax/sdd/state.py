"""Task state kept in PowerContext.

The state records what a task needs, what has been done and which verification
results already exist.  It is written through the public Memory API, so a later
process reads it back with the same runtime and continues the work.
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

from sdd.config import Settings

STATE_MARKER = "SDD-STATE"


@dataclass
class TaskRecord:
    """The persisted state of one development task."""

    task: str
    scope: str
    specs: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    done: list[str] = field(default_factory=list)
    todo: list[str] = field(default_factory=list)
    verification: list[str] = field(default_factory=list)
    proposal: str = ""
    revision: int = 0

    def to_payload(self) -> str:
        # The marker is part of the stored text so that the fulltext query
        # that looks the state up finds it again.  Without it the record
        # would only be reachable by luck, through a word of the payload.
        return f"{STATE_MARKER} " + json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_payload(cls, payload: str) -> "TaskRecord":
        text = payload.strip()
        if text.startswith(STATE_MARKER):
            text = text[len(STATE_MARKER) :].strip()
        return cls(**json.loads(text))


class TaskStateStore:
    """PowerContext backed store of the task state.

    The state is written through the public Memory application, so a later
    process opens the same SQLite database, finds the same Scope and reads the
    record back.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _config(self) -> BuiltinConfig:
        path = Path(self._settings.state_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return BuiltinConfig(
            database=SQLiteConfig(url=f"sqlite+aiosqlite:///{path.as_posix()}"),
            runtime=RuntimeConfig(artifact_processing_families=()),
        )

    async def _scope_id(self, runtime, scope: str) -> str:
        """Return the Scope id, creating the Scope the first time it is used."""

        try:
            created = await runtime.scopes.create(
                ScopeDraft(
                    title=scope,
                    summary="SDD task state",
                    idempotency_key=scope,
                )
            )
        except Exception:
            # The scope already exists; look it up by its title.
            for descriptor in await runtime.scopes.list():
                if descriptor.title == scope:
                    return descriptor.scope_id
            raise
        return created.scope_id

    async def load(self, scope: str) -> TaskRecord | None:
        """Read the state of one scope back, or ``None`` when nothing is stored."""

        async with open_builtin_runtime(self._config()) as runtime:
            scope_id = await self._scope_id(runtime, scope)
            page = await runtime.memory.for_scope(scope_id).search(
                SearchMemoryRequest(query=STATE_MARKER, mode="fts", limit=10)
            )
            newest: TaskRecord | None = None
            for hit in page.hits:
                if not hit.text.startswith(STATE_MARKER):
                    continue
                record = TaskRecord.from_payload(hit.text)
                # The memory is append only, so the newest record of a scope is
                # the one with the highest revision.
                if newest is None or record.revision > newest.revision:
                    newest = record
            return newest

    async def save(self, record: TaskRecord) -> None:
        """Persist the state of one task."""

        record.revision += 1
        async with open_builtin_runtime(self._config()) as runtime:
            scope_id = await self._scope_id(runtime, record.scope)
            await runtime.memory.for_scope(scope_id).remember(
                RememberMemoryRequest(
                    entries=(
                        MemoryEntryInput(
                            kind="fact",
                            text=record.to_payload(),
                        ),
                    ),
                )
            )

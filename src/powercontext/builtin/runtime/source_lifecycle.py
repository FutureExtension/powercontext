# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Dependency-aware Source lifecycle for one Scope.

A Source that stops being usable withdraws the Memory entries and Topic Memory
artifacts that depend on it. The dependency graph is supplied by the caller, so the
runtime never has to infer a relationship from prose.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory.models import MemoryCitation
from powercontext.builtin.persistence.tables import (
    SOURCE_LIFECYCLE_EVENTS_TABLE,
    SOURCE_LIFECYCLE_NODES_TABLE,
    SOURCES_TABLE,
    TOPIC_MEMORY_ACTIVE_CHUNKS_TABLE,
    TOPIC_MEMORY_ACTIVE_TOPICS_TABLE,
)
from powercontext.limits import MAX_SOURCE_LIFECYCLE_NODE_ID_LENGTH

SOURCE_KIND = "source"
MEMORY_KIND = "memory"
TOPIC_KIND = "topic"
ALL_POLICY = "all"
ANY_POLICY = "any"


class SourceLifecycleError(ValueError):
    """Raised when a registration or an event breaks the dependency contract."""


class SourceLifecycleEvent(BaseModel):
    """One availability change of one registered Source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    reason: str
    revision: int
    sequence: int
    available: bool

    @field_validator("node_id", "reason")
    @classmethod
    def require_text(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("must not be blank")  # noqa: TRY003
        return value

    @field_validator("revision", "sequence")
    @classmethod
    def require_positive(cls, value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError("must be a positive integer")  # noqa: TRY003
        return value


@dataclass(frozen=True)
class LifecycleNode:
    """One registered dependency node of one Scope."""

    node_id: str
    kind: str
    parents: tuple[str, ...]
    policy: str
    revision: int | None
    reference: dict[str, Any]
    available: bool
    withdrawn: dict[str, Any] | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "kind": self.kind,
            "parents": list(self.parents),
            "policy": self.policy,
            "revision": self.revision,
            "reference": self.reference,
            "available": self.available,
            "withdrawn": self.withdrawn,
        }

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> LifecycleNode:
        return cls(
            node_id=str(value["node_id"]),
            kind=str(value["kind"]),
            parents=tuple(str(item) for item in value.get("parents", ())),
            policy=str(value.get("policy", ALL_POLICY)),
            revision=None if value.get("revision") is None else int(value["revision"]),
            reference=dict(value.get("reference") or {}),
            available=bool(value.get("available", True)),
            withdrawn=None if value.get("withdrawn") is None else dict(value["withdrawn"]),
        )


@dataclass
class LifecycleState:
    """The whole dependency state of one Scope."""

    nodes: dict[str, LifecycleNode]
    events: dict[str, dict[int, SourceLifecycleEvent]]


def _node_id(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SourceLifecycleError("node_id must be a non-empty string")
    if len(value) > MAX_SOURCE_LIFECYCLE_NODE_ID_LENGTH:
        raise SourceLifecycleError("node_id is too long")
    return value


def _parents(value: object) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise SourceLifecycleError("parents must be a sequence of node identifiers")
    parents = tuple(_node_id(item) for item in value)
    if not parents:
        raise SourceLifecycleError("a derived node needs at least one parent")
    if len(set(parents)) != len(parents):
        raise SourceLifecycleError("parents must be unique")
    return parents


def _policy(value: object) -> str:
    if value not in {ALL_POLICY, ANY_POLICY}:
        raise SourceLifecycleError("policy must be 'all' or 'any'")
    return str(value)


def _supported(state: LifecycleState, parents: tuple[str, ...], policy: str) -> bool:
    support = [state.nodes[parent].available for parent in parents if parent in state.nodes]
    if not support:
        return False
    return all(support) if policy == ALL_POLICY else any(support)


def _descendants(state: LifecycleState, node_id: str) -> list[str]:
    children: dict[str, list[str]] = {}
    for node in state.nodes.values():
        for parent in node.parents:
            children.setdefault(parent, []).append(node.node_id)
    found: list[str] = []
    pending = list(children.get(node_id, ()))
    while pending:
        current = pending.pop()
        if current in found:
            continue
        found.append(current)
        pending.extend(children.get(current, ()))
    return found


def _recompute(state: LifecycleState, changed: set[str]) -> set[str]:
    """Recompute the availability of the descendants of the changed nodes."""

    updated: set[str] = set()
    pending = list(changed)
    while pending:
        current = pending.pop()
        for child in _descendants(state, current):
            node = state.nodes[child]
            available = _supported(state, node.parents, node.policy)
            if available != node.available:
                state.nodes[child] = LifecycleNode(
                    node_id=node.node_id,
                    kind=node.kind,
                    parents=node.parents,
                    policy=node.policy,
                    revision=node.revision,
                    reference=node.reference,
                    available=available,
                    withdrawn=node.withdrawn,
                )
                updated.add(child)
                pending.append(child)
    return updated



def _require_known_parents(state: LifecycleState, parents: tuple[str, ...], node_id: str) -> None:
    """Reject an unknown parent, a self reference and any dependency cycle."""

    for parent in parents:
        if parent not in state.nodes:
            raise SourceLifecycleError("a parent of the node is not registered")
    seen: set[str] = set()
    pending = list(parents)
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        if current == node_id:
            raise SourceLifecycleError("the dependency would form a cycle")
        node = state.nodes.get(current)
        if node is not None:
            pending.extend(node.parents)


def _available_nodes(state: LifecycleState) -> list[str]:
    """Return the sorted identifiers of every available node."""

    return sorted(node_id for node_id, node in state.nodes.items() if node.available)
async def _load_state(connection: AsyncConnection, scope_id: str) -> LifecycleState:
    nodes: dict[str, LifecycleNode] = {}
    rows = await connection.execute(
        select(SOURCE_LIFECYCLE_NODES_TABLE).where(
            SOURCE_LIFECYCLE_NODES_TABLE.c.scope_id == scope_id
        )
    )
    for row in rows:
        payload = json.loads(bytes(row._mapping["node"]).decode("utf-8"))
        node = LifecycleNode.from_json(payload)
        nodes[node.node_id] = node
    events: dict[str, dict[int, SourceLifecycleEvent]] = {}
    rows = await connection.execute(
        select(SOURCE_LIFECYCLE_EVENTS_TABLE).where(
            SOURCE_LIFECYCLE_EVENTS_TABLE.c.scope_id == scope_id
        )
    )
    for row in rows:
        payload = json.loads(bytes(row._mapping["event"]).decode("utf-8"))
        event = SourceLifecycleEvent.model_validate(payload)
        events.setdefault(event.node_id, {})[event.sequence] = event
    return LifecycleState(nodes=nodes, events=events)


async def _save_node(connection: AsyncConnection, scope_id: str, node: LifecycleNode) -> None:
    payload = json.dumps(node.to_json(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    await connection.execute(
        delete(SOURCE_LIFECYCLE_NODES_TABLE).where(
            SOURCE_LIFECYCLE_NODES_TABLE.c.scope_id == scope_id,
            SOURCE_LIFECYCLE_NODES_TABLE.c.node_id == node.node_id,
        )
    )
    await connection.execute(
        insert(SOURCE_LIFECYCLE_NODES_TABLE).values(
            scope_id=scope_id,
            node_id=node.node_id,
            kind=node.kind,
            node=payload,
        )
    )


async def _save_event(
    connection: AsyncConnection,
    scope_id: str,
    event: SourceLifecycleEvent,
) -> None:
    payload = json.dumps(event.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    await connection.execute(
        delete(SOURCE_LIFECYCLE_EVENTS_TABLE).where(
            SOURCE_LIFECYCLE_EVENTS_TABLE.c.scope_id == scope_id,
            SOURCE_LIFECYCLE_EVENTS_TABLE.c.node_id == event.node_id,
            SOURCE_LIFECYCLE_EVENTS_TABLE.c.sequence == event.sequence,
        )
    )
    await connection.execute(
        insert(SOURCE_LIFECYCLE_EVENTS_TABLE).values(
            scope_id=scope_id,
            node_id=event.node_id,
            sequence=event.sequence,
            event=payload,
        )
    )


async def _require_source(connection: AsyncConnection, scope_id: str, source_ref) -> None:
    found = await connection.scalar(
        select(SOURCES_TABLE.c.source_id).where(
            SOURCES_TABLE.c.scope_id == scope_id,
            SOURCES_TABLE.c.source_id == source_ref.source_id,
        )
    )
    if found is None:
        raise SourceLifecycleError("the registered Source does not exist in this Scope")


__all__ = [
    "LifecycleNode",
    "_available_nodes",
    "LifecycleState",
    "SourceLifecycleError",
    "SourceLifecycleEvent",
]
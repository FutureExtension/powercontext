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

"""Branch-aware capture of Pi session events with durable incremental progress."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import quote

from pydantic import BaseModel, JsonValue

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.connectors import (
    ConnectorRunCompletion,
    ConnectorRunSession,
    ConnectorRunStatus,
    ConnectorSubmissionStatus,
)
from powercontext.sources.definitions import AdapterSourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

PI_EVENT_SOURCE_NAME = "pi-event"
PI_EVENT_SOURCE_VERSION = "1"
PI_SESSION_CONNECTOR_NAME = "pi-session-history"
PI_SESSION_CONNECTOR_VERSION = "1"

_PI_SESSION_VERSION = 3
_PI_CHECKPOINT_VERSION = 1
_PI_HEADER_TYPE = "session"
_PI_MESSAGE_TYPE = "message"
_PI_COMPACTION_TYPE = "compaction"
_PI_BRANCH_SUMMARY_TYPE = "branch_summary"
_PI_CUSTOM_MESSAGE_TYPE = "custom_message"
_PI_SUMMARY_TYPES = frozenset({_PI_COMPACTION_TYPE, _PI_BRANCH_SUMMARY_TYPE})
_PI_CUSTOM_ROLE = "custom"
_PI_TOOL_RESULT_ROLE = "toolResult"
_PI_BASH_ROLE = "bashExecution"


class PiSessionInput(BaseModel):
    """One offline Pi session archive addressed by its selected leaf."""

    content: bytes
    leaf_id: str | None = None


class PiEventInput(BaseModel):
    """One visible Pi event captured from the ancestor chain of a leaf."""

    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


class PiEventSource(Source):
    """Captured Pi event that can be used as Artifact evidence."""

    source_id: str
    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


def pi_event_source_id(session_id: str, event_id: str) -> str:
    """Return the stable identity of one captured Pi event."""

    _require_identity_part("session_id", session_id)
    _require_identity_part("event_id", event_id)
    identity = f"pi:{quote(session_id, safe='')}:{quote(event_id, safe='')}"
    if len(identity) > MAX_SOURCE_ID_LENGTH:
        digest = hashlib.sha256(f"{session_id}\x00{event_id}".encode()).hexdigest()
        identity = f"pi:{digest}"
    return identity


def parse_pi_session(value: PiSessionInput) -> tuple[PiEventInput, ...]:
    """Parse one Pi session archive into the visible events of the selected branch."""

    session_id, chain, _ = _parse_session(value)
    return tuple(_visible_events(session_id, chain))


class PiEventAdapter:
    """Resolve and read the runtime's Pi event Source."""

    input_class = PiEventInput
    name = PI_EVENT_SOURCE_NAME
    source_class = PiEventSource

    async def resolve(self, value: PiEventInput, /) -> PiEventSource:
        source_id = pi_event_source_id(value.session_id, value.event_id)
        return PiEventSource(
            name=source_id,
            definition_version=PI_EVENT_SOURCE_VERSION,
            materialization=SourceMaterialization.CAPTURED,
            source_id=source_id,
            session_id=value.session_id,
            event_id=value.event_id,
            parent_id=value.parent_id,
            event_type=value.event_type,
            role=value.role,
            content=value.content,
            record=value.record,
        )

    async def read(self, source: PiEventSource, /) -> PiEventInput:
        return PiEventInput(
            session_id=source.session_id,
            event_id=source.event_id,
            parent_id=source.parent_id,
            event_type=source.event_type,
            role=source.role,
            content=source.content,
            record=source.record,
        )


class PiEventTextEvidenceProjection:
    """Expose one captured Pi event without coupling consumers to the event Source."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PiEventSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PiEventSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PI_EVENT_SOURCE_NAME,
            source_id=source.source_id,
            content=source.content,
            metadata={
                "session_id": source.session_id,
                "event_id": source.event_id,
                "parent_id": source.parent_id,
                "event_type": source.event_type,
                "role": source.role,
            },
        )


PI_EVENT_ADAPTER = PiEventAdapter()
PI_EVENT_SOURCE_DEFINITION = AdapterSourceDefinition(
    PI_EVENT_ADAPTER,
    version=PI_EVENT_SOURCE_VERSION,
    projections=(PiEventTextEvidenceProjection(),),
)


class PiSessionConnector:
    """Import the visible events of one Pi branch without repeating known history."""

    name = PI_SESSION_CONNECTOR_NAME
    version = PI_SESSION_CONNECTOR_VERSION
    source_definitions = frozenset({PI_EVENT_SOURCE_NAME})

    def __init__(self, path: str | Path, leaf_id: str | None = None) -> None:
        self._path = Path(path)
        self._leaf_id = leaf_id

    async def run(self, session: ConnectorRunSession, /) -> ConnectorRunCompletion:
        """Parse the archive and submit only the events this branch still misses."""

        content = self._read_archive()
        session_id, chain, nodes = _parse_session(PiSessionInput(content=content, leaf_id=self._leaf_id))
        document, imported = _checkpoint_state(session.checkpoint)
        _reject_rewritten_events(session_id, nodes, imported)

        known = _imported_entries(document)
        for event in _visible_events(session_id, chain):
            source_id = pi_event_source_id(event.session_id, event.event_id)
            if source_id in imported:
                continue
            outcome = await session.submit(source_id, PI_EVENT_SOURCE_NAME, event)
            if outcome.status is not ConnectorSubmissionStatus.ACCEPTED:
                return ConnectorRunCompletion(status=ConnectorRunStatus.INCOMPLETE, checkpoint=session.checkpoint)
            known[source_id] = {"event_id": event.event_id, "digest": _record_digest(event.record)}
        document["events"] = known
        document["version"] = _PI_CHECKPOINT_VERSION
        return ConnectorRunCompletion(status=ConnectorRunStatus.COMPLETE, checkpoint=document)

    def _read_archive(self) -> bytes:
        try:
            return self._path.read_bytes()
        except OSError as error:
            raise ValueError(f"Pi session archive could not be read: {self._path}") from error


def _parse_session(value: PiSessionInput) -> tuple[str, list[dict[str, JsonValue]], dict[str, dict[str, JsonValue]]]:
    """Return the session id, the selected ancestor chain, and every parsed record."""

    if not isinstance(value, PiSessionInput):
        raise ValueError("Pi session input must be a PiSessionInput")
    records = _read_records(_decode_archive(value.content))
    session_id = _read_session_id(records[0])
    nodes = _build_nodes(records[1:])
    leaf_id = _select_leaf(value.leaf_id, nodes)
    return session_id, _ancestor_chain(nodes, leaf_id), nodes


def _decode_archive(content: bytes) -> str:
    if not isinstance(content, (bytes, bytearray)):
        raise ValueError("Pi session content must be bytes")
    try:
        return bytes(content).decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("Pi session content must be valid UTF-8") from error


def _read_records(text: str) -> list[dict[str, JsonValue]]:
    records: list[dict[str, JsonValue]] = []
    for number, line in enumerate(text.split("\n"), start=1):
        if line.endswith("\r"):
            line = line[:-1]
        if not line.strip():
            continue
        try:
            record = json.loads(line, parse_constant=_reject_json_constant)
        except json.JSONDecodeError as error:
            raise ValueError(f"Pi session line {number} is not valid JSON") from error
        if not isinstance(record, dict):
            raise ValueError(f"Pi session line {number} must be a JSON object")
        records.append(record)
    if not records:
        raise ValueError("Pi session must start with a session header")
    return records


def _reject_json_constant(value: str) -> JsonValue:
    raise ValueError(f"Pi session contains the non-JSON constant {value}")


def _read_session_id(header: dict[str, JsonValue]) -> str:
    if header.get("type") != _PI_HEADER_TYPE:
        raise ValueError("Pi session must start with a session header")
    version = header.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version != _PI_SESSION_VERSION:
        raise ValueError(f"Pi session version must be {_PI_SESSION_VERSION}")
    session_id = header.get("id")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("Pi session id must be a non-empty string")
    return session_id


def _build_nodes(records: list[dict[str, JsonValue]]) -> dict[str, dict[str, JsonValue]]:
    nodes: dict[str, dict[str, JsonValue]] = {}
    for record in records:
        event_id = record.get("id")
        if not isinstance(event_id, str) or not event_id:
            raise ValueError("Pi session event id must be a non-empty string")
        if event_id in nodes:
            raise ValueError(f"Pi session event id is duplicated: {event_id!r}")
        if "parentId" not in record:
            raise ValueError(f"Pi session event {event_id!r} must declare a parent")
        parent_id = record["parentId"]
        if parent_id is not None and not isinstance(parent_id, str):
            raise ValueError(f"Pi session event {event_id!r} declares an invalid parent")
        nodes[event_id] = record
    for event_id, record in nodes.items():
        parent_id = _parent_id(record)
        if parent_id is not None and parent_id not in nodes:
            raise ValueError(f"Pi session event {event_id!r} references the missing parent {parent_id!r}")
    return nodes


def _parent_id(record: dict[str, JsonValue]) -> str | None:
    parent_id = record.get("parentId")
    if isinstance(parent_id, str) and parent_id:
        return parent_id
    return None


def _select_leaf(leaf_id: str | None, nodes: dict[str, dict[str, JsonValue]]) -> str:
    if leaf_id is None:
        last = next(reversed(nodes), None)
        if last is None:
            raise ValueError("Pi session must contain at least one event")
        return last
    if not isinstance(leaf_id, str) or not leaf_id:
        raise ValueError("Pi session leaf id must be a non-empty string")
    if leaf_id not in nodes:
        raise ValueError(f"Pi session does not contain the leaf {leaf_id!r}")
    return leaf_id


def _ancestor_chain(nodes: dict[str, dict[str, JsonValue]], leaf_id: str) -> list[dict[str, JsonValue]]:
    chain: list[dict[str, JsonValue]] = []
    visited: set[str] = set()
    current: str | None = leaf_id
    while current is not None:
        if current in visited:
            raise ValueError(f"Pi session branch contains a cycle at {current!r}")
        visited.add(current)
        chain.append(nodes[current])
        current = _parent_id(nodes[current])
    chain.reverse()
    return chain


def _visible_events(session_id: str, chain: list[dict[str, JsonValue]]) -> list[PiEventInput]:
    """Return the visible events of one branch, keeping the original graph relations."""

    events: list[PiEventInput] = []
    for record in chain:
        visible = _visible_text(record)
        if visible is None:
            continue
        role, content = visible
        events.append(
            PiEventInput(
                session_id=session_id,
                event_id=record["id"],
                parent_id=_parent_id(record),
                event_type=record["type"],
                role=role,
                content=content,
                record=record,
            )
        )
    return events


def _visible_text(record: dict[str, JsonValue]) -> tuple[str, str] | None:
    """Return the visible role and full text of one event, or None when it has no body."""

    event_type = record.get("type")
    if event_type == _PI_MESSAGE_TYPE:
        message = record.get("message")
        if not isinstance(message, dict):
            return None
        role = message.get("role")
        if not isinstance(role, str) or not role:
            return None
        if role == _PI_TOOL_RESULT_ROLE:
            body = _tool_result_text(message)
        elif role == _PI_BASH_ROLE:
            body = _bash_execution_text(message)
        else:
            body = _blocks_text(message.get("content"))
    elif event_type in _PI_SUMMARY_TYPES:
        role = event_type
        summary = record.get("summary")
        body = summary if isinstance(summary, str) else ""
    elif event_type == _PI_CUSTOM_MESSAGE_TYPE:
        role = _PI_CUSTOM_ROLE
        body = _blocks_text(_custom_content(record))
    else:
        return None
    if not body:
        return None
    return role, f"{role}: {body}"


def _custom_content(record: dict[str, JsonValue]) -> JsonValue:
    content = record.get("content")
    if content is not None:
        return content
    message = record.get("message")
    if isinstance(message, dict):
        return message.get("content")
    return None


def _blocks_text(content: JsonValue) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
        elif block_type == "toolCall":
            parts.append(_tool_call_text(block))
    return "\n".join(parts)


def _tool_call_text(block: dict[str, JsonValue]) -> str:
    name = block.get("name")
    call_id = block.get("id")
    arguments = block.get("arguments")
    encoded = _compact_json(arguments if isinstance(arguments, dict) else {})
    return f"[tool_call {_text_or_empty(name)} {_text_or_empty(call_id)}] {encoded}"


def _tool_result_text(message: dict[str, JsonValue]) -> str:
    name = message.get("toolName")
    call_id = message.get("toolCallId")
    text = _blocks_text(message.get("content"))
    prefix = f"[tool_result {_text_or_empty(name)} {_text_or_empty(call_id)}]"
    return f"{prefix} {text}" if text else prefix


def _bash_execution_text(message: dict[str, JsonValue]) -> str:
    command = message.get("command")
    output = message.get("output")
    head = f"$ {_text_or_empty(command)}"
    return f"{head}\n{output}" if isinstance(output, str) and output else head


def _compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _text_or_empty(value: JsonValue) -> str:
    return value if isinstance(value, str) else ""


def _record_digest(record: dict[str, JsonValue]) -> str:
    encoded = _compact_json(record).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _checkpoint_state(previous: JsonValue) -> tuple[dict[str, JsonValue], dict[str, str]]:
    """Return the mutable checkpoint document and the digests of imported events."""

    document: dict[str, JsonValue] = dict(previous) if isinstance(previous, dict) else {}
    imported: dict[str, str] = {}
    events = document.get("events")
    if isinstance(events, dict):
        for source_id, entry in events.items():
            if not isinstance(source_id, str) or not isinstance(entry, dict):
                continue
            digest = entry.get("digest")
            if isinstance(digest, str):
                imported[source_id] = digest
    return document, imported


def _imported_entries(document: dict[str, JsonValue]) -> dict[str, JsonValue]:
    events = document.get("events")
    return dict(events) if isinstance(events, dict) else {}


def _reject_rewritten_events(
    session_id: str,
    nodes: dict[str, dict[str, JsonValue]],
    imported: dict[str, str],
) -> None:
    """Fail when an already imported event was rewritten in the archive."""

    current = {
        pi_event_source_id(session_id, event_id): _record_digest(record) for event_id, record in nodes.items()
    }
    for source_id, digest in imported.items():
        recorded = current.get(source_id)
        if recorded is not None and recorded != digest:
            raise ValueError(f"Pi event {source_id!r} was rewritten after it was imported")


def _require_identity_part(field: str, value: object) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")


__all__ = [
    "PI_EVENT_SOURCE_DEFINITION",
    "PiEventInput",
    "PiEventSource",
    "PiSessionConnector",
    "PiSessionInput",
    "pi_event_source_id",
    "parse_pi_session",
]

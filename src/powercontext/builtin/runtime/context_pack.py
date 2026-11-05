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

"""Versioned Context Pack and prefix-reuse delta wire protocol.

The wire format is an interoperability contract: a receiver must be able to rebuild the
exact target pack from a base pack and a delta without any sender-side state.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from typing import Any

PACK_SCHEMA = "powercontext.context-pack.v1"
DELTA_SCHEMA = "powercontext.context-pack-delta.v1"
DEFAULT_CHUNK_BYTES = 512
_DIGEST_PREFIX = "sha256:"


class ContextPackError(ValueError):
    """Protocol or chunking validation failure."""


def _canonical(payload: dict[str, Any]) -> bytes:
    """Encode one payload as the canonical JSON the wire contract defines."""

    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _encode_items(items: tuple[bytes, ...]) -> list[str]:
    return [base64.b64encode(item).decode("ascii") for item in items]


def _digest(items: tuple[bytes, ...]) -> str:
    """Return the digest of one pack over its canonical schema and item list."""

    unsigned = {"schema": PACK_SCHEMA, "items": _encode_items(items)}
    return _DIGEST_PREFIX + hashlib.sha256(_canonical(unsigned)).hexdigest()


def _decode_items(values: object) -> tuple[bytes, ...]:
    if not isinstance(values, list):
        raise ContextPackError("items must be an array of Base64 strings")
    decoded: list[bytes] = []
    for value in values:
        if not isinstance(value, str):
            raise ContextPackError("items must be an array of Base64 strings")
        try:
            decoded.append(base64.b64decode(value, validate=True))
        except (binascii.Error, ValueError) as error:
            raise ContextPackError("items must contain valid Base64 strings") from error
    return tuple(decoded)


def _require_digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.startswith(_DIGEST_PREFIX):
        raise ContextPackError(f"{field} must be a sha256 digest")
    hexdigest = value.removeprefix(_DIGEST_PREFIX)
    if len(hexdigest) != 64 or hexdigest.lower() != hexdigest:
        raise ContextPackError(f"{field} must be a sha256 digest")
    try:
        int(hexdigest, 16)
    except ValueError as error:
        raise ContextPackError(f"{field} must be a sha256 digest") from error
    return value


def _pack_payload(items: tuple[bytes, ...], digest: str) -> bytes:
    """Encode one pack, resolving the self-referential byte count exactly."""

    encoded = _encode_items(items)
    guess = 0
    for _ in range(8):
        payload = {"byte_count": guess, "digest": digest, "items": encoded, "schema": PACK_SCHEMA}
        body = _canonical(payload)
        if len(body) == guess:
            return body
        guess = len(body)
    raise ContextPackError("context pack byte count does not converge")


@dataclass(frozen=True)
class ContextPack:
    """One complete context payload split into bounded, literal chunks."""

    items: tuple[bytes, ...]
    digest: str
    byte_count: int

    @classmethod
    def build(cls, items: tuple[bytes, ...]) -> "ContextPack":
        """Build one pack from literal chunks."""

        materialized = tuple(bytes(item) for item in items)
        digest = _digest(materialized)
        payload = _pack_payload(materialized, digest)
        return cls(items=materialized, digest=digest, byte_count=len(payload))

    @classmethod
    def from_content(cls, content: str | bytes, *, chunk_bytes: int = DEFAULT_CHUNK_BYTES) -> "ContextPack":
        """Split one content payload into deterministic, valid UTF-8 chunks."""

        if isinstance(chunk_bytes, bool) or not isinstance(chunk_bytes, int) or chunk_bytes <= 0:
            raise ContextPackError("chunk_bytes must be a positive integer")
        if isinstance(content, str):
            data = content.encode("utf-8")
        elif isinstance(content, (bytes, bytearray)):
            data = bytes(content)
        else:
            raise ContextPackError("content must be text or bytes")
        if not data:
            return cls.build(())
        chunks: list[bytes] = []
        start = 0
        while start < len(data):
            end = min(start + chunk_bytes, len(data))
            while end > start:
                try:
                    data[start:end].decode("utf-8")
                    break
                except UnicodeDecodeError:
                    end -= 1
            if end == start:
                raise ContextPackError("chunk_bytes cannot hold one UTF-8 character")
            chunks.append(data[start:end])
            start = end
        return cls.build(tuple(chunks))

    def to_bytes(self) -> bytes:
        """Encode the pack for the wire."""

        return _pack_payload(self.items, self.digest)

    @classmethod
    def from_bytes(cls, data: bytes) -> "ContextPack":
        """Decode and validate one pack received from the wire."""

        payload = _decode_object(data)
        if set(payload) != {"schema", "items", "digest", "byte_count"}:
            raise ContextPackError("context pack must contain exactly schema, items, digest and byte_count")
        if payload["schema"] != PACK_SCHEMA:
            raise ContextPackError("context pack schema is not supported")
        items = _decode_items(payload["items"])
        digest = _require_digest(payload["digest"], "digest")
        if _digest(items) != digest:
            raise ContextPackError("context pack digest does not match its items")
        byte_count = payload["byte_count"]
        if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count < 0:
            raise ContextPackError("byte_count must be a non-negative integer")
        if byte_count != len(data):
            raise ContextPackError("context pack byte count does not match the received payload")
        return cls(items=items, digest=digest, byte_count=byte_count)


@dataclass(frozen=True)
class ContextPackDelta:
    """The suffix that turns one base pack into the target pack."""

    base_digest: str
    target_digest: str
    prefix_items: int
    appended: tuple[bytes, ...]

    @classmethod
    def between(cls, base: "ContextPack", target: "ContextPack") -> "ContextPackDelta":
        """Select a valid common prefix and carry the remaining target chunks."""

        prefix = 0
        for left, right in zip(base.items, target.items):
            if left != right:
                break
            prefix += 1
        return cls(
            base_digest=base.digest,
            target_digest=target.digest,
            prefix_items=prefix,
            appended=target.items[prefix:],
        )

    def to_bytes(self) -> bytes:
        """Encode the delta for the wire."""

        payload = {
            "schema": DELTA_SCHEMA,
            "base_digest": self.base_digest,
            "target_digest": self.target_digest,
            "prefix_items": self.prefix_items,
            "appended": _encode_items(self.appended),
        }
        return _canonical(payload)

    @property
    def byte_count(self) -> int:
        """Return the exact wire size of this delta."""

        return len(self.to_bytes())

    @classmethod
    def from_bytes(cls, data: bytes) -> "ContextPackDelta":
        """Decode and validate one delta received from the wire."""

        payload = _decode_object(data)
        if set(payload) != {"schema", "base_digest", "target_digest", "prefix_items", "appended"}:
            raise ContextPackError("context pack delta must contain exactly its five wire fields")
        if payload["schema"] != DELTA_SCHEMA:
            raise ContextPackError("context pack delta schema is not supported")
        base_digest = _require_digest(payload["base_digest"], "base_digest")
        target_digest = _require_digest(payload["target_digest"], "target_digest")
        prefix_items = payload["prefix_items"]
        if isinstance(prefix_items, bool) or not isinstance(prefix_items, int) or prefix_items < 0:
            raise ContextPackError("prefix_items must be a non-negative integer")
        appended = _decode_items(payload["appended"])
        return cls(
            base_digest=base_digest,
            target_digest=target_digest,
            prefix_items=prefix_items,
            appended=appended,
        )


def apply_context_pack_delta(base: ContextPack, delta: ContextPackDelta) -> ContextPack:
    """Rebuild the target pack from the base pack and one delta."""

    if not isinstance(base, ContextPack):
        raise ContextPackError("base must be a context pack")
    if not isinstance(delta, ContextPackDelta):
        raise ContextPackError("delta must be a context pack delta")
    if delta.base_digest != base.digest:
        raise ContextPackError("delta base digest does not match the base pack")
    prefix = delta.prefix_items
    if isinstance(prefix, bool) or not isinstance(prefix, int) or prefix < 0:
        raise ContextPackError("prefix_items must be a non-negative integer")
    if prefix > len(base.items):
        raise ContextPackError("prefix_items exceeds the base pack")
    rebuilt = ContextPack.build(base.items[:prefix] + tuple(delta.appended))
    if rebuilt.digest != delta.target_digest:
        raise ContextPackError("delta target digest does not match the rebuilt pack")
    return rebuilt


def _decode_object(data: bytes) -> dict[str, Any]:
    if not isinstance(data, (bytes, bytearray)):
        raise ContextPackError("wire payload must be bytes")
    try:
        payload = json.loads(bytes(data).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContextPackError("wire payload must be valid UTF-8 JSON") from error
    if not isinstance(payload, dict):
        raise ContextPackError("wire payload must be a JSON object")
    return payload


__all__ = [
    "DEFAULT_CHUNK_BYTES",
    "ContextPack",
    "ContextPackDelta",
    "ContextPackError",
    "apply_context_pack_delta",
]

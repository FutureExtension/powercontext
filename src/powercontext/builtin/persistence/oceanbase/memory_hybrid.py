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

"""One native statement that returns both lexical and vector Memory candidates.

The frozen path issued two statements for one hybrid search: a FULLTEXT scan
over the active-head projection and an HNSW top-k over the vector projection.
This module keeps that candidate set but retrieves both channels with a single
statement, so the database performs the fulltext scan and the vector index
scan once and returns both ordered candidate lists.

The statement keeps every filter inside the database: the Scope, the requested
Memory artifacts, the optional tag filter and the candidate limit all apply
before the two candidate lists are unioned.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from sqlalchemy import Table, bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

from powercontext.builtin.artifacts.memory import (
    CapabilityNotSupportedError,
    EmbeddingProfile,
    MemoryCapabilities,
    MemoryProjection,
    MemorySearchChannels,
    MemorySearchRequest,
)
from powercontext.builtin.artifacts.memory.canonical import validate_embedding
from powercontext.builtin.persistence.memory_index import memory_channel_hits
from powercontext.builtin.persistence.tags import memory_tag_parameters, memory_tag_sql
from powercontext.builtin.persistence.oceanbase.memory_index import OceanBaseMemoryVectorIndex

_OCEANBASE_HYBRID_SEARCH_SQL = """
WITH fts_candidates AS (
    SELECT h.scope_id AS scope_id,
           h.memory_artifact_id AS memory_artifact_id,
           h.head_revision AS head_revision,
           h.entry_id AS entry_id,
           h.entry_version_id AS entry_version_id,
           v.text,
           'fts' AS channel,
           NULL AS distance,
           MATCH(h.searchable_text) AGAINST (:analyzed_query IN BOOLEAN MODE) AS fts_score
    FROM pc_memory_entry_heads h
    JOIN pc_memory_entry_versions v
      ON v.scope_id = h.scope_id
     AND v.memory_artifact_id = h.memory_artifact_id
     AND v.entry_version_id = h.entry_version_id
    WHERE h.scope_id = :scope_id
      AND h.memory_artifact_id IN :memory_artifact_ids
      AND MATCH(h.searchable_text) AGAINST (:analyzed_query IN BOOLEAN MODE)
{fts_tag_predicate}
    ORDER BY fts_score DESC,
             memory_artifact_id,
             entry_id,
             entry_version_id
    LIMIT :candidate_limit
),
vector_candidates AS (
    SELECT m.scope_id AS scope_id,
           m.memory_artifact_id AS memory_artifact_id,
           m.head_revision AS head_revision,
           m.entry_id AS entry_id,
           m.entry_version_id AS entry_version_id,
           v.text,
           'vector' AS channel,
           l2_distance(m.embedding, :query_vector) AS distance,
           NULL AS fts_score
    FROM pc_memory_vector_entries m
    JOIN pc_memory_entry_versions v
      ON v.scope_id = m.scope_id
     AND v.memory_artifact_id = m.memory_artifact_id
     AND v.entry_version_id = m.entry_version_id
    WHERE m.scope_id = :scope_id
      AND m.memory_artifact_id IN :memory_artifact_ids
{vector_tag_predicate}
    ORDER BY l2_distance(m.embedding, :query_vector) APPROXIMATE
    LIMIT :candidate_limit
)
SELECT f.scope_id,
       f.memory_artifact_id,
       f.head_revision,
       f.entry_id,
       f.entry_version_id,
       f.text,
       f.channel,
       f.distance,
       f.fts_score
FROM fts_candidates f
UNION ALL
SELECT g.scope_id,
       g.memory_artifact_id,
       g.head_revision,
       g.entry_id,
       g.entry_version_id,
       g.text,
       g.channel,
       g.distance,
       g.fts_score
FROM vector_candidates g
"""


def _fts_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    """Order lexical candidates exactly like the former FTS candidate query."""

    return (
        -float(row["fts_score"] or 0.0),
        str(row["memory_artifact_id"]),
        str(row["entry_id"]),
        str(row["entry_version_id"]),
    )


def _vector_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    """Order vector candidates by distance, then by identity."""

    distance = row["distance"]
    return (
        float(distance) if distance is not None else 0.0,
        str(row["memory_artifact_id"]),
        str(row["entry_id"]),
        str(row["entry_version_id"]),
    )


def _ordered(
    rows: Sequence[Mapping[str, Any]],
    channel: str,
    key: Callable[[Mapping[str, Any]], tuple[Any, ...]],
) -> list[Mapping[str, Any]]:
    """Return one channel of the result, ordered deterministically."""

    return sorted((row for row in rows if row["channel"] == channel), key=key)


class OceanBaseMemoryHybridIndex:
    """Retrieve both candidate channels with exactly one native statement."""

    def __init__(self, profile: EmbeddingProfile, *, vector_index: OceanBaseMemoryVectorIndex) -> None:
        if profile.dimension < 1 or profile.distance != "l2" or profile.normalization != "unit":
            raise CapabilityNotSupportedError(
                "vector",
                "OceanBase requires a positive unit-normalized L2 embedding profile",
            )
        self.profile = profile
        self._vector_index = vector_index
        self.capabilities = MemoryCapabilities(
            tag_filter=True,
            fts=False,
            vector=True,
            embedding_profile=profile,
        )
        self.tables: tuple[Table, ...] = ()
        self._plain_sql = _OCEANBASE_HYBRID_SEARCH_SQL.format(
            fts_tag_predicate="",
            vector_tag_predicate="",
        )
        self._tagged_sql = _OCEANBASE_HYBRID_SEARCH_SQL.format(
            fts_tag_predicate=memory_tag_sql("h").strip(),
            vector_tag_predicate=memory_tag_sql("m").strip(),
        )

    def _statement(self, tagged: bool):
        # Loaded on demand: only the OceanBase and seekdb backends use it.
        from pyobvector import VECTOR

        sql = self._tagged_sql if tagged else self._plain_sql
        binds = [
            bindparam("memory_artifact_ids", expanding=True),
            bindparam("query_vector", type_=VECTOR(self.profile.dimension)),
        ]
        if tagged:
            binds.extend(
                (
                    bindparam("tag_keys", expanding=True),
                    bindparam("tag_hashes", expanding=True),
                )
            )
        return text(sql).bindparams(*binds)

    async def initialize(self, connection: AsyncConnection, /) -> None:
        del connection

    async def replace(
        self,
        connection: AsyncConnection,
        scope_id: str,
        memory_ref: object,
        projections: tuple[MemoryProjection, ...],
        /,
    ) -> None:
        del connection, scope_id, memory_ref, projections

    async def delete(
        self,
        connection: AsyncConnection,
        scope_id: str,
        memory_ref: object,
        entry_ids: tuple[str, ...],
        /,
    ) -> None:
        del connection, scope_id, memory_ref, entry_ids

    async def upsert(
        self,
        connection: AsyncConnection,
        scope_id: str,
        memory_ref: object,
        projections: tuple[MemoryProjection, ...],
        /,
    ) -> None:
        del connection, scope_id, memory_ref, projections

    async def search(
        self,
        connection: AsyncConnection,
        scope_id: str,
        request: MemorySearchRequest,
        /,
    ) -> MemorySearchChannels:
        if request.mode != "hybrid":
            return MemorySearchChannels()
        if request.embedding_profile != self.profile or request.query_vector is None:
            raise CapabilityNotSupportedError("embedding-profile")
        if not await self._vector_index.vector_complete(  # type: ignore[attr-defined]
            connection, scope_id, request.memories, self.profile
        ):
            raise CapabilityNotSupportedError("vector")
        tagged = request.tag_filter is not None
        rows = (
            await connection.execute(
                self._statement(tagged),
                {
                    "scope_id": scope_id,
                    "memory_artifact_ids": tuple(memory.artifact_id for memory in request.memories),
                    "analyzed_query": request.analyzed_query,
                    "query_vector": validate_embedding(
                        request.query_vector,
                        dimension=self.profile.dimension,
                    ),
                    "candidate_limit": request.candidate_limit,
                    **memory_tag_parameters(request.tag_filter),
                },
            )
        ).mappings().all()
        # A UNION ALL does not guarantee that each branch keeps its own
        # ORDER BY, so the two channels are ordered here. The candidate
        # sets already match the former two-statement path because the
        # branch LIMIT is applied before the union.
        fts_rows = _ordered(rows, "fts", _fts_key)
        vector_rows = _ordered(rows, "vector", _vector_key)
        return MemorySearchChannels(
            fts=memory_channel_hits(fts_rows, request.memories),
            vector=memory_channel_hits(vector_rows, request.memories),
        )

    async def vector_complete(
        self,
        connection: AsyncConnection,
        scope_id: str,
        memories: tuple[object, ...],
        profile: EmbeddingProfile,
        /,
    ) -> bool:
        return await self._vector_index.vector_complete(  # type: ignore[attr-defined]
            connection, scope_id, memories, profile
        )

    async def hydrate(
        self,
        connection: AsyncConnection,
        projections: tuple[MemoryProjection, ...],
        /,
    ) -> tuple[MemoryProjection, ...]:
        del connection
        return projections


__all__ = ["OceanBaseMemoryHybridIndex"]

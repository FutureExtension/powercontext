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

"""Count the persisted Source journal identities one processor has not consumed.

Counting uses the persisted journal identity, never the Source body, its token
count or the number of generated results. A repeated capture of an existing
identity keeps its original journal position, so it never raises the count.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from powercontext.builtin.persistence.cursors import SourceCursorRepository
from powercontext.builtin.persistence.tables import SOURCES_TABLE


class SourceCountRepository:
    """Read the pending Source identity count of one processor binding."""

    def __init__(self, cursors: SourceCursorRepository | None = None) -> None:
        self._cursors = cursors if cursors is not None else SourceCursorRepository()

    async def pending_count(
        self,
        connection: AsyncConnection,
        scope_id: str,
        binding_name: str,
        /,
    ) -> int:
        """Count the journal identities after one binding's committed cursor."""

        cursor = await self._cursors.load(connection, scope_id, binding_name)
        return await self._count_after(connection, scope_id, 0 if cursor is None else cursor.cursor.sequence)

    async def pending_counts(
        self,
        connection: AsyncConnection,
        scope_ids: Sequence[str],
        binding_name: str,
        /,
    ) -> dict[str, int]:
        """Count the pending identities of one bounded Scope selection."""

        if not scope_ids:
            return {}
        cursors = await self._cursors.load_many(connection, scope_ids, binding_name)
        counts: dict[str, int] = {}
        for scope_id in scope_ids:
            stored = cursors.get(scope_id)
            after = 0 if stored is None else stored.cursor.sequence
            counts[scope_id] = await self._count_after(connection, scope_id, after)
        return counts

    @staticmethod
    async def _count_after(connection: AsyncConnection, scope_id: str, after: int) -> int:
        value = await connection.scalar(
            select(func.count())
            .select_from(SOURCES_TABLE)
            .where(
                SOURCES_TABLE.c.scope_id == scope_id,
                SOURCES_TABLE.c.journal_position > after,
            )
        )
        return int(value or 0)


__all__ = ["SourceCountRepository"]
